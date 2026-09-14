"""语音克隆（客服音色）API。

★ 可插拔约束：
- 路由前缀 ``/voice-clone`` **独立**，不混进任何既有业务 prefix。
- **不 import 任何业务模块**；主功能也不 import 本模块。
- 路由是否挂载由 ``core/config.voice_clone_enabled`` 总开关决定（在 ``main.py``）。
  关闭时这些端点**根本不存在**（前端拿到 404 → 入口直接隐藏）。
- 附加模块同样受项目铁律约束：失败显式报错并给原因，禁止静默退回默认音色。

端点：
POST   /api/v1/voice-clone/sample    - 上传音频样本（校验 + 落盘），返回本地 URL 与校验结论
POST   /api/v1/voice-clone/enroll    - 创建音色（含授权留痕），返回音色状态
GET    /api/v1/voice-clone/status    - 查询当前店铺音色状态（可选 refresh=true 拉远端）
POST   /api/v1/voice-clone/preview   - 用已就绪音色试听合成，返回本地音频 URL
POST   /api/v1/voice-clone/speak     - 对话播报：把 Agent 回复合成语音（不回写试听文案）
POST   /api/v1/voice-clone/speak-plan - 对话播报分句计划（纯计算：净化 + 切段，不合成）
DELETE /api/v1/voice-clone           - 删除音色（同时释放远端配额）
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile

from core.config import config
from core.logger import get_logger
from core.tenant.middleware import get_current_shop_id

from . import service
from .client import DEFAULT_TARGET_MODEL, VoiceCloneError

logger = get_logger(__name__)

#: ★ 独立前缀，与既有业务路由完全隔离
router = APIRouter(prefix="/voice-clone", tags=["客服语音（附加模块）"])


def _fail(exc: Exception) -> HTTPException:
    """统一把业务异常翻成 400 + 可展示原因。

    项目铁律：失败必须显式给出原因。前端拿到 ``detail`` 直接展示，
    **不允许**包装成「操作成功」或悄悄用系统默认音色顶上。
    """
    return HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- #
# 1. 上传样本
# --------------------------------------------------------------------------- #

@router.post("/sample")
async def upload_sample(
    file: UploadFile = File(..., description="音频样本：WAV(16bit) / MP3 / M4A，≤10MB"),
    duration: Optional[float] = Form(default=None, description="前端测得的时长（秒）"),
):
    """上传并校验音频样本。

    本端点**不创建音色** —— 只是把样本落盘 + 返回校验结论，
    让用户在提交授权前先知道「这个文件到底行不行」。
    """
    content = await file.read()
    filename = file.filename or "sample.wav"
    try:
        service.validate_sample(filename=filename, size=len(content), duration=duration)
        local_url = await service.persist_sample(content, filename)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc

    return {
        "url": local_url,
        "name": filename,
        "size": len(content),
        "duration": duration,
        "duration_verified": duration is not None,
        "message": "样本校验通过，可继续创建音色"
        if duration is not None
        else "样本已保存；未取得时长，服务端将不做时长校验",
    }


# --------------------------------------------------------------------------- #
# 2. 创建音色
# --------------------------------------------------------------------------- #

@router.post("/enroll")
async def enroll_voice(
    sample_url: str = Body(..., embed=True, description="上传样本返回的 /static/voice/xxx"),
    filename: str = Body(default="sample.wav", embed=True),
    duration: Optional[float] = Body(default=None, embed=True),
    authorized_by: str = Body(..., embed=True, description="当前用户 ID"),
    agreement_snapshot: str = Body(
        ..., embed=True, description="用户勾选授权时前端展示的文案原文（原样快照落库）"
    ),
    target_model: str = Body(default=DEFAULT_TARGET_MODEL, embed=True),
    language_hint: str = Body(default="zh", embed=True),
    enable_preprocess: bool = Body(default=False, embed=True),
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """用已上传的样本创建复刻音色。

    创建是**异步**的：内部会轮询到 ``OK`` 才返回 ``ready=true``；
    若超时仍在审核中，返回 ``status=pending`` 并明确告知「稍后查询」——
    **不会**假装成功。
    """
    if not shop_id:
        raise HTTPException(status_code=400, detail="缺少 X-Shop-ID 请求头")

    # ★ 守卫要排在**读文件之前**：否则「样本文件不存在」会盖掉「已有音色」这个
    #   用户真正需要知道的原因（实测踩到）。
    try:
        await service.ensure_no_existing_voice(shop_id)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc

    # 样本已落盘 → 从本地读回内容做二次校验（避免只信前端传参）
    try:
        content = _read_local_sample(sample_url)
        service.validate_sample(filename=filename, size=len(content), duration=duration)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc

    try:
        result = await service.enroll(
            shop_id=shop_id,
            content=content,
            filename=filename,
            duration=duration,
            authorized_by=authorized_by,
            agreement_snapshot=agreement_snapshot,
            target_model=target_model,
            language_hint=language_hint,
            enable_preprocess=enable_preprocess,
            public_base_url=config.public_base_url,
        )
    except VoiceCloneError as exc:
        raise _fail(exc) from exc
    return result


def _read_local_sample(sample_url: str) -> bytes:
    """从 ``/static/voice/xxx`` 读回样本内容（防路径穿越）。"""
    from pathlib import Path

    if not sample_url or "/static/" not in sample_url:
        raise VoiceCloneError(f"样本地址无效：{sample_url!r}")
    rel = sample_url.split("/static/", 1)[1]
    root = service._voice_upload_root().parent  # uploads/
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise VoiceCloneError("样本地址非法（路径穿越）")
    if not target.exists():
        raise VoiceCloneError(f"样本文件不存在：{sample_url}")
    return target.read_bytes()


# --------------------------------------------------------------------------- #
# 3. 查询状态
# --------------------------------------------------------------------------- #

@router.get("/status")
async def voice_status(
    refresh: bool = Query(default=False, description="true 时向远端拉取最新状态并同步落库"),
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """查询当前店铺的音色状态。无记录时返回 ``exists=false``（前端显示空状态）。"""
    if not shop_id:
        return {"exists": False, "status": "none", "ready": False}
    try:
        if refresh:
            return await service.refresh_status(shop_id)
        row = await service.get_record(shop_id)
        return service.serialize(row)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc


# --------------------------------------------------------------------------- #
# 4. 试听合成
# --------------------------------------------------------------------------- #

@router.post("/preview")
async def preview_voice(
    text: str = Body(default="", embed=True, description="留空则用面板里保存的试听文案"),
    target_model: str = Body(default="", embed=True),
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """用已就绪的音色合成一段试听音频。音色未就绪时**明确报错**，不做兜底。"""
    if not shop_id:
        raise HTTPException(status_code=400, detail="缺少 X-Shop-ID 请求头")
    try:
        return await service.preview(shop_id=shop_id, text=text, target_model=target_model)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc


# --------------------------------------------------------------------------- #
# 4.1 对话播报（Agent 回复 → 语音）
# --------------------------------------------------------------------------- #

@router.post("/speak")
async def speak_voice(
    text: str = Body(..., embed=True, description="Agent 回复正文（markdown，后端做朗读净化）"),
    target_model: str = Body(default="", embed=True),
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """把一条 Agent 回复合成成语音，返回可长期访问的音频 URL。

    ★ 与 ``/preview`` 的两点区别（都是「为什么不能复用同一个端点」的理由）：

    1. **不回写 ``preview_text``**。试听文案是用户在面板里选定的样例，
       对话正文每轮都不同 —— 共用写回会让老板的试听样例被自己的对话冲掉。
    2. **正文先做朗读净化**（去 markdown / emoji / 代码块）。面板试听是手敲原文，
       对话正文是 markdown，直接念会把 ``**``、``|``、反引号一个个念出来。

    音色未就绪时**明确报错并给原因**，不做兜底、不静默换默认音色。
    """
    if not shop_id:
        raise HTTPException(status_code=400, detail="缺少 X-Shop-ID 请求头")
    try:
        return await service.speak(shop_id=shop_id, text=text, target_model=target_model)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc


# --------------------------------------------------------------------------- #
# 4.2 对话播报：分句计划（纯计算）
# --------------------------------------------------------------------------- #

@router.post("/speak-plan")
async def speak_plan(
    text: str = Body(..., embed=True, description="Agent 回复正文（markdown，后端净化 + 切段）"),
):
    """把一条回复切成朗读段。**纯计算：不合成、不查库、不落库**（实测 ~1ms）。

    为什么单独给个端点、而不是让前端自己切句：切句规则与净化规则是**同一条业务规则的
    两面** —— 断点必须落在「换行补句号」不生效的位置（见 ``service._SPLIT_AFTER`` 的说明）。
    前端再实现一遍就是同一规则两套实现，早晚分叉。

    前端的用法（分句流水线）：

    1. 流式期间反复对「到目前为止的原文」重算，**只取 `final=True` 的段** ——
       `final` 段以句末标点收尾，是确定的完整句，于是首句一完成就能开念；
    2. 用返回的 `raw_end` 当**游标**去重，已念过的段不会重念；
    3. 流结束后再算一次，把结尾那段 `final=False` 的碎片补上。

    同一段 `text` 反复调用是幂等的（无状态），可以随便重试。
    """
    return service.speech_plan(text)


# --------------------------------------------------------------------------- #
# 5. 删除音色
# --------------------------------------------------------------------------- #

@router.delete("")
async def delete_voice(
    force: bool = Query(
        default=False,
        description="true 时跳过远端调用，仅清理本地记录（远端音色已确认不存在时用）",
    ),
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """删除当前店铺的音色。

    默认会同时调远端释放配额，但**远端失败不阻塞本地清理**（否则远端音色被平台
    回收后用户会永久卡住）—— 此时返回 ``warning`` 说明远端残留情况。
    """
    if not shop_id:
        raise HTTPException(status_code=400, detail="缺少 X-Shop-ID 请求头")
    try:
        result = await service.delete_record(shop_id, also_remote=True, force=force)
    except VoiceCloneError as exc:
        raise _fail(exc) from exc
    if not result["removed"]:
        raise HTTPException(status_code=404, detail="当前店铺没有可删除的音色")
    return {
        "success": True,
        "remote_deleted": result["remote_deleted"],
        "message": "音色已删除" if result["remote_deleted"] else "本地记录已删除",
        "warning": result["warning"],
    }


@router.get("/config")
async def voice_config():
    """面板初始化用的静态配置（模型候选 / 默认试听文案 / 音频限制）。

    前端不必硬编码这些值 —— 尤其音频限制，改后端一处即可生效。
    """
    from . import client

    from . import mirror

    # 公网回源体检：提前告诉前端「配好了没」，别等用户点了「开始克隆」才报错
    public_base = (config.public_base_url or "").strip()
    mirror_check = mirror.check_connectivity()
    if public_base:
        if mirror_check["enabled"] and not mirror_check["ok"]:
            # 配了镜像但连不通 → 大概率拉不到文件
            public_ready = False
            public_reason = f"公网地址已配置，但样本镜像不可用：{mirror_check['reason']}"
        elif mirror_check["enabled"]:
            public_ready = True
            public_reason = f"公网地址 {public_base} + 样本镜像已连通"
        else:
            # 没配镜像 → 只能寄希望于部署环境本身能回源
            public_ready = True
            public_reason = (
                f"公网地址 {public_base} 已配置（未启用样本镜像："
                "若该地址能直接访问本服务的 /static，则可用）"
            )
    else:
        public_ready = False
        public_reason = (
            "未配置 PUBLIC_BASE_URL。声音复刻要求音频样本公网可访问，"
            "本地 localhost 服务端取不到 —— 请配置 PUBLIC_BASE_URL 并确保样本能被公网回源。"
        )

    return {
        "enabled": bool(config.voice_clone_enabled),
        "default_target_model": DEFAULT_TARGET_MODEL,
        "public_ready": public_ready,
        "public_base_url": public_base,
        "public_reason": public_reason,
        "mirror": mirror_check,
        "target_models": [
            {
                "value": m,
                "label": m,
                "note": "仅北京地域可用，无系统音色" if "v3.5" in m else "",
            }
            for m in client.SUPPORTED_TARGET_MODELS
        ],
        "default_preview_text": service.DEFAULT_PREVIEW_TEXT,
        "agreement_version": service.AGREEMENT_VERSION,
        "sample_limits": {
            "max_bytes": client.MAX_SAMPLE_BYTES,
            "min_seconds": client.MIN_SAMPLE_SECONDS,
            "max_seconds": client.MAX_SAMPLE_SECONDS,
            "exts": list(client.ALLOWED_SAMPLE_EXTS),
            "require_public_url": not bool(config.public_base_url),
        },
    }
