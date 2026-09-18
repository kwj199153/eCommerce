"""语音克隆业务服务层。

职责：样本校验 → 转存 → 创建音色（异步）→ 轮询就绪 → 试听合成 → 删除。
**所有失败一律抛 ``VoiceCloneError`` 并携带可直接展示给用户的原因**——
项目铁律：附加模块同样不允许静默退回默认值/默认音色。

与主功能的隔离：
- 本文件只 import ``core.*`` 与 ``modules.voice_clone.*``（外加同级的 aigc_media
  ``storage`` 复用「远程资源转存」这一纯工具，不构成业务耦合 —— 它不读任何业务表）。
- **不读任何业务表**（不碰 products / listing / customer_service 的数据）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from core.database import async_session_factory
from core.logger import get_logger

from . import client
from . import mirror
from .client import VoiceCloneError  # re-export：调用方只认这一个异常类型

logger = get_logger(__name__)

#: 试听默认文案（用户可在面板里改）
DEFAULT_PREVIEW_TEXT = "您好，很高兴为您服务"

#: 回调给前端的「授权文案」标准版本号。用户勾选时前端把**当时的原话**一起送来，
#: 后端原样快照落库 —— 日后前端改了措辞也能证明当时授权的是哪一版。
AGREEMENT_VERSION = "v1"

#: 音频样本转存目录（挂在 /static 下）
SAMPLE_SUBDIR = "voice"

#: ★ 「单店铺单音色」守卫要拦下的本模块落库状态。
#: 注意是本模块**自己的词表**（ready/pending），不是远端的 OK/DEPLOYING ——
#: 两套词表混用会让守卫变死代码（实测踩过：第二次 enroll 直接覆盖已就绪音色）。
_SINGLE_VOICE_BLOCKING_STATUSES = ("ready", "pending")

#: 远程样本下载超时
_SAMPLE_TIMEOUT = 120.0


def _now() -> str:
    return datetime.utcnow().isoformat()


# --------------------------------------------------------------------------- #
# 样本处理
# --------------------------------------------------------------------------- #

def validate_sample(*, filename: str, size: int, duration: Optional[float]) -> None:
    """校验音频样本是否满足 CosyVoice 硬要求。不满足 → 立即抛错并说清原因。

    ``duration`` 由前端用 ``HTMLAudioElement`` 测得（后端不引入音频解析依赖）；
    为 ``None`` 时跳过时长判断 —— 但**不静默放行**，由调用方在响应里标注
    ``duration_verified=False``，让用户知道这一项没被验证。
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in client.ALLOWED_SAMPLE_EXTS:
        raise VoiceCloneError(
            f"音频格式不支持：{ext or '（无扩展名）'}（仅支持 WAV / MP3 / M4A）"
        )
    if size <= 0:
        raise VoiceCloneError("音频文件为空")
    if size > client.MAX_SAMPLE_BYTES:
        raise VoiceCloneError(
            f"音频文件过大：{size / 1024 / 1024:.1f} MB（上限 10 MB）"
        )
    if duration is not None:
        if duration < client.MIN_SAMPLE_SECONDS:
            raise VoiceCloneError(
                f"音频太短：{duration:.1f} 秒（至少需要 {client.MIN_SAMPLE_SECONDS:.0f} 秒连续清晰朗读）"
            )
        if duration > client.MAX_SAMPLE_SECONDS:
            raise VoiceCloneError(
                f"音频过长：{duration:.1f} 秒（最长 {client.MAX_SAMPLE_SECONDS:.0f} 秒）"
            )


def sample_public_url(local_static_path: str, *, base_url: str = "") -> str:
    """把 ``/static/voice/xxx.wav`` 变成 CosyVoice 能取到的公网 URL。

    ★ CosyVoice 的 ``url`` 参数**必须公网可访问**（不像万相图生图能收 base64）。
    本地开发环境下 ``base_url`` 通常是 ``http://localhost:8000`` —— 那是**外网取不到的**，
    调用方必须显式告知用户，本函数不做任何「看起来能用」的伪装。
    """
    if not (base_url or "").strip():
        raise VoiceCloneError(
            "缺少公网访问地址（PUBLIC_BASE_URL）。声音复刻要求音频样本公网可访问，"
            "本地 localhost 地址服务端取不到 —— 请配置 PUBLIC_BASE_URL 或改用已部署环境。"
        )
    return f"{base_url.rstrip('/')}{local_static_path}"


async def persist_sample(content: bytes, filename: str) -> str:
    """把上传的音频存到 ``uploads/voice/``，返回 ``/static/voice/<name>``。

    命名 = 内容 sha1 前 16 位 + 原扩展名 → 相同内容重复上传不堆垃圾（幂等）。

    ★ 落盘后**顺带镜像到云端静态目录**（若配置了 ``VOICE_SAMPLE_MIRROR_SSH_HOST``）——
    因为 CosyVoice 是**服务端主动来拉**，本地 localhost 它够不着。
    镜像失败**不阻塞本地流程**（本地文件已写好，可以正常预览），
    但会记录 warning；真正需要公网时由 ``sample_public_url`` 给出明确原因。
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in client.ALLOWED_SAMPLE_EXTS:
        raise VoiceCloneError(f"音频格式不支持：{ext}")

    # 内容寻址用（非安全用途）；usedforsecurity=False 让 FIPS 环境也放行
    name = hashlib.sha1(content, usedforsecurity=False).hexdigest()[:16] + ext
    target_dir = _voice_upload_root()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    if not target.exists():
        target.write_bytes(content)
        logger.info(f"[voice-clone] 样本已落盘 {SAMPLE_SUBDIR}/{name}（{len(content)} 字节）")

    # 镜像到云端（未配置时 mirror.push_file 直接返回空串，静默跳过）
    if mirror.is_enabled():
        try:
            remote = mirror.push_file(target)
            logger.info(f"[voice-clone] 样本已镜像云端 {remote}")
        except mirror.MirrorError as exc:
            # 不抛出：本地已可用，公网不可用的问题留给 sample_public_url 统一报
            logger.warning(f"[voice-clone] 样本镜像失败（本地不受影响）：{exc}")

    return f"/static/{SAMPLE_SUBDIR}/{name}"


def _voice_upload_root() -> Path:
    """``uploads/voice`` 的绝对路径。

    与 ``aigc_media.storage.upload_root`` 同源（都按 ``backend/`` 解析），
    这里独立实现以免引入对该模块的运行时依赖（可插拔约束）。
    """
    from core.config import config

    root = Path(config.upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root / SAMPLE_SUBDIR


async def persist_remote_audio(url: str) -> str:
    """下载远程音频（合成结果）到本地，返回 ``/static/voice/<name>``。

    ★ 合成的音频 URL **24 小时后过期**（与万相出图同一套路）→ 必须即时转存，
    否则用户第二天打开面板发现试听「静默失效」。
    """
    if not url:
        raise VoiceCloneError("音频 URL 为空")

    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in client.ALLOWED_SAMPLE_EXTS:
        ext = ".mp3"
    # 内容寻址用（非安全用途）；usedforsecurity=False 让 FIPS 环境也放行
    name = "tts-" + hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16] + ext
    target_dir = _voice_upload_root()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name

    if not target.exists():
        async with httpx.AsyncClient(timeout=_SAMPLE_TIMEOUT, follow_redirects=True) as c:
            resp = await c.get(url)
        if resp.status_code >= 400:
            raise VoiceCloneError(f"音频下载失败（HTTP {resp.status_code}）")
        target.write_bytes(resp.content)
        logger.info(f"[voice-clone] 合成音频已转存 {SAMPLE_SUBDIR}/{name}（{len(resp.content)} 字节）")

    return f"/static/{SAMPLE_SUBDIR}/{name}"


# --------------------------------------------------------------------------- #
# 落库读写
# --------------------------------------------------------------------------- #

async def get_record(shop_id: str):
    """按店铺取音色记录（一个店铺一条）。无记录返回 ``None``。"""
    if not shop_id:
        return None
    from .db_model import ShopVoice

    async with async_session_factory() as session:
        row = (
            await session.execute(select(ShopVoice).where(ShopVoice.shop_id == shop_id))
        ).scalars().first()
        return row


async def upsert_record(shop_id: str, **fields):
    """按 ``shop_id`` 插入或更新，返回 ORM 对象。"""
    if not shop_id:
        raise VoiceCloneError("缺少 shop_id（请求头未带 X-Shop-ID）")
    from .db_model import ShopVoice

    async with async_session_factory() as session:
        row = (
            await session.execute(select(ShopVoice).where(ShopVoice.shop_id == shop_id))
        ).scalars().first()
        if row is None:
            row = ShopVoice(
                # 内容寻址用（非安全用途）；usedforsecurity=False 让 FIPS 环境也放行
                id="voice-" + hashlib.sha1(shop_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16],
                shop_id=shop_id,
            )
            session.add(row)
        for k, v in fields.items():
            if v is not None:
                setattr(row, k, v)
        row.updatedAt = _now()
        await session.commit()
        await session.refresh(row)
        return row


async def delete_record(shop_id: str, *, also_remote: bool = True, force: bool = False) -> dict:
    """删除音色记录；``also_remote`` 为真时同时释放远端配额。

    ★ 设计要点（``force=False`` 的默认行为）：**远端删除失败不阻塞本地清理**。

    理由：远端音色可能已经被平台自动回收（1 年未使用会删）、或账号/Key 变更导致
    查不到 —— 此时若坚持「远端删不掉就不删本地」，用户会永久卡在一个删不掉的
    记录上（死局）。正确处理是：本地删掉 + **把远端失败原因如实回报**，
    让用户知道「远端可能残留一个音色占配额」。

    ``force=True`` 时跳过远端调用，纯本地清理（用于远端已确认不存在的场景）。
    """
    if not shop_id:
        return {"removed": False, "remote_deleted": False, "warning": ""}
    from .db_model import ShopVoice

    remote_error = ""
    remote_deleted = False
    async with async_session_factory() as session:
        row = (
            await session.execute(select(ShopVoice).where(ShopVoice.shop_id == shop_id))
        ).scalars().first()
        if row is None:
            return {"removed": False, "remote_deleted": False, "warning": ""}

        if also_remote and not force and row.voice_id:
            try:
                await client.delete_voice(row.voice_id)
                remote_deleted = True
            except Exception as exc:  # noqa: BLE001 - 远端失败不阻塞本地清理，但必须上报
                remote_error = str(exc)
                logger.warning(
                    f"[voice-clone] 远端删除失败（不影响本地清理）shop={shop_id} "
                    f"voice_id={row.voice_id}：{remote_error}"
                )

        await session.delete(row)
        await session.commit()

    logger.info(f"[voice-clone] 已删除音色记录 shop={shop_id} remote_deleted={remote_deleted}")
    return {
        "removed": True,
        "remote_deleted": remote_deleted,
        "warning": (
            f"本地记录已删除，但远端音色删除失败（{remote_error}）。"
            "远端可能残留该音色仍占用配额，可稍后在阿里云百炼控制台手动清理。"
            if remote_error
            else ""
        ),
    }


# --------------------------------------------------------------------------- #
# 对外业务编排
# --------------------------------------------------------------------------- #

async def ensure_no_existing_voice(shop_id: str) -> None:
    """★ 「单店铺单音色」前置守卫。

    **必须在任何文件系统操作之前调用** —— 否则用户传了个不存在的 sample_url 时，
    会先报「样本文件不存在」，把「已有音色」这个真正的原因盖掉
    （实测踩到：端口层先读文件，守卫永远轮不到触发）。
    """
    if not shop_id:
        return
    existing = await get_record(shop_id)
    if existing is not None and existing.status in _SINGLE_VOICE_BLOCKING_STATUSES:
        raise VoiceCloneError(
            f"当前店铺已有音色（状态：{existing.status}），请先删除后再重新克隆（MVP：单店铺单音色）"
        )


async def enroll(
    *,
    shop_id: str,
    content: bytes,
    filename: str,
    duration: Optional[float],
    authorized_by: str,
    agreement_snapshot: str,
    target_model: str = client.DEFAULT_TARGET_MODEL,
    language_hint: str = "zh",
    enable_preprocess: bool = False,
    public_base_url: str = "",
) -> dict:
    """完整创建流程：校验 → 落盘 → 建音色 → 轮询就绪 → 落库。

    失败时：**保留 ``status=failed`` + ``error_msg``**（不删记录），
    让前端能显示「上次为什么失败」，而不是用户面对一个空白面板。
    """
    shop_id = (shop_id or "").strip()
    if not shop_id:
        raise VoiceCloneError("缺少 shop_id（请求头未带 X-Shop-ID）")
    if not (authorized_by or "").strip():
        raise VoiceCloneError("缺少授权人（请先登录）")
    if not (agreement_snapshot or "").strip():
        raise VoiceCloneError("缺少授权确认记录（请勾选授权条款后再提交）")

    validate_sample(filename=filename, size=len(content), duration=duration)

    # ★ MVP 约束「单店铺单音色」：已有可用（或审核中）音色 → 必须先删再克隆。
    #   这里比对的是**本模块自己的落库词表**（"ready"/"pending"），不是远端的 "OK"
    #   —— 两套词表混用会让这个守卫变成死代码（曾经踩过）。
    await ensure_no_existing_voice(shop_id)

    local_path = await persist_sample(content, filename)
    audio_url = sample_public_url(local_path, base_url=public_base_url)

    prefix = client.normalize_prefix(shop_id)
    await upsert_record(
        shop_id,
        status="pending",
        error_msg="",
        sample_url=local_path,
        sample_name=filename,
        sample_size=len(content),
        sample_duration=int(duration or 0),
        target_model=target_model,
        authorized_at=_now(),
        authorized_by=authorized_by,
        agreement_snapshot=agreement_snapshot,
    )

    try:
        voice_id = await client.create_voice(
            audio_url=audio_url,
            target_model=target_model,
            prefix=prefix,
            language_hint=language_hint,
            enable_preprocess=enable_preprocess,
        )
    except Exception as exc:  # noqa: BLE001 - 显式落库失败原因，绝不静默
        msg = str(exc)
        await upsert_record(shop_id, status="failed", error_msg=msg)
        logger.error(f"[voice-clone] 创建音色失败 shop={shop_id}：{msg}")
        raise

    await upsert_record(shop_id, voice_id=voice_id, status="pending", error_msg="")

    try:
        final_status = await client.wait_until_ready(voice_id)
    except Exception as exc:  # noqa: BLE001 - 同上，保留 voice_id 供重试查询
        msg = str(exc)
        await upsert_record(shop_id, status="failed", error_msg=msg)
        logger.error(f"[voice-clone] 音色未就绪 shop={shop_id} voice_id={voice_id}：{msg}")
        raise

    row = await upsert_record(
        shop_id,
        status="ready",
        error_msg="",
        target_model=target_model,
        preview_text=DEFAULT_PREVIEW_TEXT,
    )
    return serialize(row, duration_verified=duration is not None)


async def refresh_status(shop_id: str) -> dict:
    """重新查询远端状态并同步落库（用于「审核中」的后续确认）。"""
    row = await get_record(shop_id)
    if row is None:
        raise VoiceCloneError("当前店铺尚未创建音色")
    if not row.voice_id:
        raise VoiceCloneError("记录里没有 voice_id，无法查询（请重新创建音色）")

    info = await client.query_voice(row.voice_id)
    remote = str(info.get("status") or "").upper()
    if remote == client.STATUS_OK:
        row = await upsert_record(shop_id, status="ready", error_msg="")
    elif remote == client.STATUS_UNDEPLOYED:
        row = await upsert_record(
            shop_id,
            status="failed",
            error_msg="音色审核未通过（UNDEPLOYED），请更换更清晰的音频样本后重试",
        )
    else:
        # DEPLOYING 等中间态：不改 status，仅回报当前远端状态
        return {**serialize(row), "remote_status": remote, "ready": False}
    return {**serialize(row), "remote_status": remote, "ready": remote == client.STATUS_OK}


#: 对话播报单次朗读的字符上限。
#:
#: 对话正文是「一眼扫过」的，不是为朗读写的：太长会让首字等待变久、听感冗长。
#: 超限时截到最近的句末并在响应里如实回报 ``truncated``（不静默丢内容）。
MAX_SPEECH_CHARS = 400

#: 单段朗读的**软上限**。
#:
#: 段越短首声越快，段越长合成请求越少。取 110 是两点之间的折中 —— 实测
#: 合成 ≈ 0.9s + 0.025s/字、播放 ≈ 0.2s/字，所以**段只要长过 6 字，合成就永远快于播放**，
#: 于是「预取」必然赶得上播放；段大小实际只影响请求数，不影响能否无缝接力。
MAX_SEGMENT_CHARS = 110

#: **首段**上限。首声延迟**只由第一段决定** ⇒ 首段刻意切得更小以抢首包。
FIRST_SEGMENT_CHARS = 45

#: 单段朗读的**下限**（净化后字数）。
#:
#: ★ 这条不是审美，是**实测出来的硬约束**：合成耗时 ≈ 0.9s + 0.025s/字（有 ≈0.9s 固定开销），
#: 播放耗时 ≈ 0.2s/字 ⇒ 解 ``0.9 + 0.025N < 0.2N`` 得 **N > 5.1 字**。
#: 段短于这个数时「合成比播放还慢」，双缓冲会被抽干、段间接不上
#: （实测「请稍等。」4 字：合成 821ms vs 播放 800ms，余量 **-0.02s**）。
#: 取 12 留出余量，顺便让极短句并入相邻段、减少请求数。
MIN_SEGMENT_CHARS = 12

# --------------------------------------------------------------------------- #
# 朗读净化（纯函数，离线可测）
# --------------------------------------------------------------------------- #

_FENCED_CODE_RE = re.compile(r"```.*?```", re.S)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BARE_URL_RE = re.compile(r"https?://\S+")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_HRULE_RE = re.compile(r"^[ \t]*([-*_])\1{2,}[ \t]*$", re.M)
#: markdown 表格的分隔行（``| --- | --- |``）—— 必须在拆竖线**之前**整行删掉，
#: 否则会残留成「--- ---」被念出来（实测）
_TABLE_SEP_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$", re.M
)
_HEADING_RE = re.compile(r"^#{1,6}\s*", re.M)
_QUOTE_RE = re.compile(r"^>\s?", re.M)
_BULLET_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])\s+", re.M)
_PIPE_RE = re.compile(r"\s*\|\s*")
_EMPHASIS_RE = re.compile(r"\*\*|__|\*|~~")
_ARROW_RE = re.compile(r"[→←↑↓⟶⟵]")
#: emoji / 装饰符号 / 项目符号 —— TTS 会把它们念成「大括号笑脸」之类，必须去掉
_SYMBOL_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # 绘文字
    "\U0001F1E6-\U0001F1FF"  # 区域指示符（国旗）
    "\U00002600-\U000027BF"  # 杂项符号 / 装饰符号（✅ ⚠ ⭐ …）
    "\u2022\u25A0-\u25FF"    # 项目符号 / 几何形状（• ▪ ● ▶ …）
    "\u2B00-\u2BFF"          # 杂项符号与箭头
    "\uFE00-\uFE0F\u200D\u20E3"  # 变体选择符 / 零宽连接符 / 键帽
    "]"
)
_SPACE_RUN_RE = re.compile(r"[ \t\u3000]{2,}")

#: 中文之间的空格几乎都是 markdown 标记（``**粗体**``、``[链接](url)``）被抹掉后留下的
#: 残渣 —— 念不出停顿、只让文本变脏。拉丁词之间的空格必须保留（"ACoS 32%"）。
_CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_SPACE_RE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")

#: 标点前的空格（箭头→逗号、被删的括号都会造成）—— 一律去掉
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+(?=[，。！？；：、,.!?;:])")

#: 中文标点后的空格同理。**只处理中文标点**：英文的 ``", "`` 必须保留那一个空格
_SPACE_AFTER_CJK_PUNCT_RE = re.compile(r"(?<=[，。！？；：、])[ \t]+")

#: 句末标点（截断点与「换行补句号」共用一套，避免两处口径分叉）
_SENTENCE_END = "。！？!?…"

#: 「上一行已以此结尾就不补句号」的标点集合（比句末多一个「.»：``...`` 已经算停顿了）
_NO_PERIOD_AFTER = _SENTENCE_END + "，,、：:；;."

#: 「允许切段」的标点 = 句末标点 + 逗号类停顿符。
#:
#: ★ 为什么**只在这些字符之后**断开：这是「逐段净化后拼接 == 整段净化」这条不变量的前提。
#: ``to_speech_text`` 的「换行补句号」规则遇到以这些字符结尾的行**不会**补句号，
#: 于是段边界两侧拼起来与整段处理的结果一致（有单测钉住）。
_SPLIT_AFTER = _SENTENCE_END + "，、；：,;:"
_SPLIT_AFTER_SET = set(_SPLIT_AFTER)
_SPLIT_RE = re.compile(rf"(?<=[{re.escape(_SPLIT_AFTER)}])")


def _raw_slices(markdown: str) -> list[tuple[str, int, bool]]:
    """按「可切段标点」把原文切成 ``(原文片, 片末偏移, 是否以句末标点结尾)``。

    偏移是**原文坐标系**的 —— 前端拿它当游标（``raw_end``）做去重：
    流式场景下会反复对「更长的原文」重算计划，已经念过的段必须能被认出来。
    """
    out: list[tuple[str, int, bool]] = []
    pos = 0
    for piece in _SPLIT_RE.split(markdown):
        if not piece:
            continue
        pos += len(piece)
        out.append((piece, pos, piece[-1] in _SENTENCE_END))
    return out


def split_speech_segments(
    markdown: str,
    *,
    max_chars: int = MAX_SPEECH_CHARS,
    max_segment_chars: int = MAX_SEGMENT_CHARS,
    first_segment_chars: int = FIRST_SEGMENT_CHARS,
    min_segment_chars: int = MIN_SEGMENT_CHARS,
) -> list[dict]:
    """把一条回复切成**保序、不重不漏**的朗读段，供前端逐段合成 / 逐段播放。

    与 ``to_speech_text`` 的分工：那个函数管「一句话怎么念干净」，本函数管
    「一长篇怎么切成几口」。净化**仍走同一个** ``to_speech_text``（不是另写一套），
    只是逐段独立净化后再拼接 —— 单测钉住「拼接 == 整段净化」这条不变量。

    返回的每个段：

    - ``text``    → 净化后的朗读文本（可直接交给 ``speak`` 合成；对已净化的文本重复净化是幂等的）
    - ``raw_end`` → 该段末尾在**原文**中的偏移（前端游标）
    - ``stable``  → 该段**原文内容已定型**：后续再来的新内容不会改变它，现在念是安全的。
      ``stable=False`` 只可能出现在**最后一段**（它含仍在增长的尾部），必须等流结束后再念
    - ``chars``   → 净化后字数

    ★ ``stable`` 有**两条**判据，缺一不可（第二条是写不变量测试时实测补上的）：

    1. **分组是主动关闭的** —— 达到段长上限，或遇到句末标点。
       若只是「输入用完了」，文本一长这一组还会继续吃进新片。
    2. **最后一片以可切段标点收尾** —— 否则它本身就是那一片还在增长的尾巴。

    只满足 ① 会把「因达到段长上限而切断、但结尾那片仍在长」的段误判为定型：
    前端的游标跳过它不念，下一轮又把它当新段念一遍 ⇒ **同一句话被念两遍**。
    两条都满足时该组必然稳定 —— 两个条件都只依赖**已冻结的切片前缀**，
    所以后续再来多少内容，这一组都会被逐字重现。
    """
    raw = str(markdown or "")
    if not raw.strip():
        return []

    slices = _raw_slices(raw)
    segments: list[dict] = []
    used = 0

    i = 0
    total = len(slices)
    while i < total:
        # 首段切小抢首包，后续段切大压请求数
        target = first_segment_chars if not segments else max_segment_chars
        buf: list[str] = []
        raw_len = 0
        raw_end = slices[i][1]
        # ① 分组是否被「主动关闭」（达到段长上限 / 遇到句末标点），而非「输入用完了」
        closed = False
        text = ""
        while i < total:
            piece, off, _is_sentence_end = slices[i]
            buf.append(piece)
            raw_len += len(piece)
            raw_end = off
            i += 1
            if raw_len >= target or piece[-1] in _SENTENCE_END:
                text = to_speech_text("".join(buf), max_chars=10**9)
                # ★ 够长才收口：太短的段「合成比播放还慢」，会抽干双缓冲（见 MIN_SEGMENT_CHARS）
                if len(text) >= min_segment_chars:
                    closed = True
                    break
        if not closed:
            # 没主动收口（输入用完了 / 一路都太短）→ 按当前收进的内容重算一次净化
            text = to_speech_text("".join(buf), max_chars=10**9)
        # ② 最后一片是否以可切段标点收尾（= 这一片自己已经完整，不是在长的那片）
        stable = closed and buf[-1][-1] in _SPLIT_AFTER_SET

        if not text:
            continue  # 整段都是 markdown 符号 / emoji → 没得念，且**不占预算**
        if used + len(text) > max_chars:
            # 超上限：在剩余预算内截到句末，然后收工（由 speech_plan 如实回报 truncated）
            room = max_chars - used
            clipped = _clip_at_sentence(text, room) if room > 0 else ""
            if clipped:
                segments.append(
                    {"text": clipped, "raw_end": raw_end, "stable": stable, "chars": len(clipped)}
                )
            break
        segments.append({"text": text, "raw_end": raw_end, "stable": stable, "chars": len(text)})
        used += len(text)

    return segments


def speech_plan(markdown: str, *, max_chars: int = MAX_SPEECH_CHARS) -> dict:
    """``split_speech_segments`` + 元信息（``/speak-plan`` 直接返回这个）。

    ``truncated`` 用「计划会念的字数 < 全文净化后字数」判定 —— 是**算出来的**，
    不是猜的：前端据此如实告知「只念了前一段」，不静默截断。
    """
    segments = split_speech_segments(markdown, max_chars=max_chars)
    clean_chars = len(to_speech_text(markdown, max_chars=10**9))
    plan_chars = sum(s["chars"] for s in segments)
    return {
        "segments": segments,
        "clean_chars": clean_chars,
        "plan_chars": plan_chars,
        "truncated": plan_chars < clean_chars,
        "source_chars": len(str(markdown or "")),
    }


def _clip_at_sentence(text: str, max_chars: int) -> str:
    """超长时截到最近的句末，找不到句末才硬截（宁可少念半句，不要念到一半断气）。"""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    cut = max(window.rfind(ch) for ch in _SENTENCE_END)
    if cut >= max_chars // 2:
        return window[: cut + 1]
    return window


def to_speech_text(markdown: str, *, max_chars: int = MAX_SPEECH_CHARS) -> str:
    """把 markdown 正文净化成「适合朗读」的纯文本。

    对话正文是**给眼睛看的**：``**加粗**``、表格竖线、代码块、emoji、链接括号全在里面。
    直接丢给 TTS，这些符号会被逐个念出来（实测听感极差）。
    本函数只做**朗读净化**，不改语义：

    - 代码块整体丢弃（念代码无意义且必念错）；行内代码保留内容、去掉反引号
    - 链接/图片：保留锚文本、丢掉 URL（念 URL 无意义）；裸 URL 一并丢弃
    - markdown 标记（``#`` / ``>`` / ``-`` / ``**`` / ``|``）去掉，箭头转成停顿
    - 换行转成句号（已有句末标点时跳过），保证 TTS 有停顿；连续空白折叠

    **不做**的事：不加语气词、不改写句子、不猜标点 —— 那是文案层的活，不是净化层的活。
    """
    if not markdown:
        return ""
    text = str(markdown)

    text = _FENCED_CODE_RE.sub(" ", text)
    text = _IMAGE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BARE_URL_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _HRULE_RE.sub("", text)
    text = _TABLE_SEP_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    text = _QUOTE_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _PIPE_RE.sub(" ", text)
    text = _EMPHASIS_RE.sub("", text)
    text = _ARROW_RE.sub("，", text)
    text = _SYMBOL_RE.sub("", text)

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if lines and lines[-1][-1] not in _NO_PERIOD_AFTER:
            lines[-1] += "。"
        lines.append(line)
    text = "".join(lines)

    text = _SPACE_RUN_RE.sub(" ", text)
    text = _CJK_SPACE_RE.sub("", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub("", text)
    text = _SPACE_AFTER_CJK_PUNCT_RE.sub("", text)
    text = text.strip()
    return _clip_at_sentence(text, max_chars).strip()


async def preview(
    *,
    shop_id: str,
    text: str = "",
    target_model: str = "",
    remember_text: bool = True,
) -> dict:
    """试听合成：用已就绪的音色合成一段话，转存后返回本地可长期访问的 URL。

    ``remember_text=False`` 供对话播报（``speak``）复用本函数 ——
    此时**不回写** ``preview_text``（那是面板试听的样例文案，不该被对话正文冲掉）。
    """
    row = await get_record(shop_id)
    if row is None:
        raise VoiceCloneError("当前店铺尚未创建音色")
    if row.status != "ready" or not row.voice_id:
        raise VoiceCloneError(
            f"音色尚不可用（当前状态：{row.status}）"
            + (f"：{row.error_msg}" if row.error_msg else "")
        )

    use_text = (text or "").strip() or (row.preview_text or "").strip() or DEFAULT_PREVIEW_TEXT
    model = (target_model or "").strip() or row.target_model or client.DEFAULT_TARGET_MODEL

    # ★ 音色与模型死绑：库里的 target_model 才是权威值，前端传歪了要纠正而不是盲从
    if model != row.target_model:
        logger.warning(
            f"[voice-clone] 合成模型与创建时不一致，已纠正为库中值：{model} → {row.target_model}"
        )
        model = row.target_model

    remote_url = await client.synthesize(use_text, voice_id=row.voice_id, model=model)
    # ★ 远程 URL 24h 过期 → 立即转存，否则次日试听静默失效
    local_url = await persist_remote_audio(remote_url)

    # ★ 只有「面板试听」才回写试听文案；对话播报不回写 ——
    #   否则老板每跟店秘书说一句，自己设的试听样例就被冲掉一次。
    if remember_text:
        await upsert_record(shop_id, preview_text=use_text)

    return {
        "audio_url": local_url,
        "text": use_text,
        "model": model,
        "expires_hint": "已转存到本地静态目录，长期有效（远端链接 24 小时过期）",
    }


async def speak(*, shop_id: str, text: str, target_model: str = "") -> dict:
    """对话播报：用已就绪的复刻音色朗读一段 Agent 回复。

    与 ``preview``（面板试听）**共用同一条合成链路**，但有两点必须区分开：

    1. **不回写 ``preview_text``**。试听的语义是「用户选定的试听样例」，
       播报的语义是「这条回复的原话」—— 共用写回会让两者互相污染。
    2. **正文先做朗读净化**（``to_speech_text``）。面板试听是用户手敲的原文，
       而对话正文是 markdown，直接念会把 ``**``、``|``、反引号一个个念出来。

    返回里额外带 ``truncated`` / ``source_chars``：超长时如实告知**只念了一部分**，
    绝不假装念完了（项目铁律：不静默丢内容）。
    """
    full_clean = to_speech_text(text, max_chars=10**9)
    spoken = to_speech_text(text)
    if not spoken:
        raise VoiceCloneError("这条回复没有可朗读的正文（可能是纯卡片或纯符号）")

    out = await preview(
        shop_id=shop_id,
        text=spoken,
        target_model=target_model,
        remember_text=False,
    )
    out["spoken_text"] = out.pop("text")
    out["truncated"] = spoken != full_clean
    out["source_chars"] = len(str(text or ""))
    return out


def serialize(row, *, duration_verified: bool = True) -> dict:
    """ORM → 前端契约。**不返回 agreement_snapshot 全文以外的新字段名**，保持稳定。"""
    if row is None:
        return {
            "exists": False,
            "status": "none",
            "ready": False,
        }
    return {
        "exists": True,
        "id": row.id,
        "shop_id": row.shop_id,
        "voice_id": row.voice_id or "",
        "voice_name": row.voice_name or "",
        "target_model": row.target_model or "",
        "status": row.status or "pending",
        "ready": row.status == "ready",
        "error_msg": row.error_msg or "",
        "sample_url": row.sample_url or "",
        "sample_name": row.sample_name or "",
        "sample_size": row.sample_size or 0,
        "sample_duration": row.sample_duration or 0,
        "duration_verified": duration_verified,
        "authorized_at": row.authorized_at or "",
        "authorized_by": row.authorized_by or "",
        "authorized": bool(row.authorized_at and row.authorized_by),
        "preview_text": row.preview_text or DEFAULT_PREVIEW_TEXT,
        "createdAt": row.createdAt or "",
        "updatedAt": row.updatedAt or "",
    }
