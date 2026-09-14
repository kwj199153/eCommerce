"""CosyVoice 声音复刻 + 语音合成客户端（REST / httpx 直连）。

为什么不用 dashscope SDK：``requirements.txt`` 里没有这个依赖，项目既有的 LLM 调用
（``ai_infra/llm/dashscope_client.py``）与出图（``aigc_media/image_client.py``）都是
httpx 直连，保持一致。

涉及的三个 REST 端点（**都在 dashscope.aliyuncs.com，北京地域旧域名仍可用**）：

1. **音色管理**（创建 / 列表 / 详情 / 更新 / 删除）——
   同一端点，靠 ``input.action`` 区分：
   ``POST /api/v1/services/audio/tts/customization``
2. **语音合成（非实时 HTTP）**——
   ``POST /api/v1/services/audio/tts/SpeechSynthesizer``
   ★ 返回的是**音频 URL**（24 小时后过期）→ 调用方必须转存（见 ``service.py``）。

（北京地域也可用业务空间专属域名 ``{WorkspaceId}.cn-beijing.maas.aliyuncs.com``，
本模块默认走通用域名 ``dashscope.aliyuncs.com`` 以保持与既有两个客户端一致；
如需切换只改 ``_API_BASE``。）

几个实测/文档确认的硬约束，别踩：
- **音色与模型死绑**：创建时的 ``target_model`` 必须与合成时的 ``model`` 完全一致，
  否则合成失败 → ``target_model`` 必须落库。
- **音色 ID 字段名不一致**：CosyVoice 返回 ``voice_id``，Qwen 返回 ``voice``。
  本模块只做 CosyVoice，严格读 ``voice_id``。
- **创建音色是异步的**：先返回 voice_id，状态为 ``DEPLOYING``（审核中），
  需轮询到 ``OK`` 才可用；``UNDEPLOYED`` = 审核未通过（不可用，必须显式报错）。
- **音频必须公网可访问**（CosyVoice 走 ``url`` 参数，不支持 base64）——
  这是与万相图生图最大的差别（那边 base64 可以，这边不行）。
- ``prefix`` 只允许数字和英文字母，不超过 10 字符。
"""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from core.logger import get_logger

logger = get_logger(__name__)

#: 通用域名（北京地域）。如需业务空间专属域名，改这里一处即可。
_API_BASE = "https://dashscope.aliyuncs.com/api/v1"
CUSTOMIZATION_URL = f"{_API_BASE}/services/audio/tts/customization"
SYNTHESIS_URL = f"{_API_BASE}/services/audio/tts/SpeechSynthesizer"

#: 声音复刻（注册/管理音色）固定模型名，不要改
ENROLLMENT_MODEL = "voice-enrollment"

#: 默认驱动模型。客服场景选 v3-flash：成本低 + 支持情感指令 + 流式。
#: ★ cosyvoice-v3.5-* 仅北京地域可用，且**无系统音色**（只能配复刻/设计音色）。
DEFAULT_TARGET_MODEL = "cosyvoice-v3-flash"

#: 支持声音复刻的模型白名单（北京地域全系）
SUPPORTED_TARGET_MODELS = (
    "cosyvoice-v3.5-plus",
    "cosyvoice-v3.5-flash",
    "cosyvoice-v3-plus",
    "cosyvoice-v3-flash",
    "cosyvoice-v2",
    "cosyvoice-v1",
)

#: 音频硬要求（用于后端二次校验，前端也会校验一遍）
MAX_SAMPLE_BYTES = 10 * 1024 * 1024      # 10 MB
MIN_SAMPLE_SECONDS = 5.0                  # 至少 5 秒连续清晰朗读
MAX_SAMPLE_SECONDS = 60.0                 # 最长 60 秒
ALLOWED_SAMPLE_EXTS = (".wav", ".mp3", ".m4a")

#: 音色状态机（CosyVoice 专属）
STATUS_DEPLOYING = "DEPLOYING"
STATUS_OK = "OK"
STATUS_UNDEPLOYED = "UNDEPLOYED"

#: ``prefix`` 只允许数字和英文字母，≤10 字符
_PREFIX_RE = re.compile(r"^[0-9A-Za-z]{1,10}$")


class VoiceCloneError(RuntimeError):
    """声音复刻链路失败：未配置密钥 / 参数被拒 / 审核未过 / 超时。

    ★ 调用方必须把 message 原样透给用户 —— 项目铁律：失败显式报错并给原因，
    **禁止静默退回默认音色**（老板：空状态优于虚构默认）。
    """


def _api_key() -> str:
    """取 DashScope API Key。

    顺序与 ``ai_infra/llm/dashscope_client.py`` / ``aigc_media/image_client.py``
    保持一致：**先 config 后环境变量**。原因：``.env`` 由 pydantic-settings 读进
    ``Settings`` 对象，**不会**写进 ``os.environ``。
    """
    key = ""
    try:
        from core.config import config as app_config

        key = (app_config.dashscope_api_key or "").strip()
    except Exception:  # noqa: BLE001 - 配置不可用时退回环境变量
        pass
    if not key:
        key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise VoiceCloneError(
            "缺少 DashScope API Key（config.dashscope_api_key 与环境变量 DASHSCOPE_API_KEY 均为空）"
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"message": (resp.text or "")[:300]}


def _raise_for_dashscope(resp: httpx.Response, body: dict, what: str) -> None:
    """统一把 DashScope 的错误体翻译成带原因的异常。"""
    if resp.status_code < 400 and not body.get("code"):
        return
    code = body.get("code") or f"HTTP {resp.status_code}"
    msg = body.get("message") or ""
    raise VoiceCloneError(f"{what}失败：{code} {msg}".strip())


async def _post(url: str, payload: dict, *, timeout: float = 60.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=_headers())
    return {"__status__": resp.status_code, "__resp__": resp, **_safe_json(resp)}


def normalize_prefix(shop_id: str, user_seed: str = "") -> str:
    """生成合法的音色 ``prefix``（仅数字/英文字母、≤10 字符）。

    ``shop_id`` 形如 ``store_ab12cd``；取其中的字母数字片段 + 用户种子，
    保证同一店铺重新创建音色时前缀稳定（便于 ``list_voice`` 按前缀找回）。
    """
    raw = re.sub(r"[^0-9A-Za-z]", "", f"{shop_id}{user_seed}")
    if not raw:
        raw = "shopvoice"
    prefix = raw[:10]
    if not _PREFIX_RE.match(prefix):  # 兜底（理论上到不了这里）
        prefix = "shopvoice"[:10]
    return prefix


async def create_voice(
    *,
    audio_url: str,
    target_model: str = DEFAULT_TARGET_MODEL,
    prefix: str,
    language_hint: str = "zh",
    enable_preprocess: bool = False,
) -> str:
    """创建复刻音色，返回 ``voice_id``（★ 此时状态通常是 DEPLOYING，还不能用）。

    ``audio_url`` 必须**公网可访问**（CosyVoice 只收 URL，不收 base64）。
    """
    if target_model not in SUPPORTED_TARGET_MODELS:
        raise VoiceCloneError(
            f"不支持的 target_model：{target_model}（可选：{'、'.join(SUPPORTED_TARGET_MODELS)}）"
        )
    if not _PREFIX_RE.match(prefix):
        raise VoiceCloneError(f"prefix 非法：{prefix!r}（仅数字和英文字母，不超过 10 个字符）")
    if not (audio_url or "").strip():
        raise VoiceCloneError("缺少音频样本公网 URL")

    payload = {
        "model": ENROLLMENT_MODEL,
        "input": {
            "action": "create_voice",
            "target_model": target_model,
            "prefix": prefix,
            "url": audio_url,
            "language_hints": [language_hint or "zh"],
            # 有背景噪音才开；安静环境关闭更还原音色
            "enable_preprocess": bool(enable_preprocess),
        },
    }

    body = await _post(CUSTOMIZATION_URL, payload)
    resp = body.pop("__resp__")
    body.pop("__status__", None)
    _raise_for_dashscope(resp, body, "创建音色")

    voice_id = str(((body.get("output") or {}).get("voice_id") or "")).strip()
    if not voice_id:
        raise VoiceCloneError(f"创建音色未返回 voice_id：{body}")
    logger.info(f"[cosyvoice] 音色已创建 voice_id={voice_id} target_model={target_model} prefix={prefix}")
    return voice_id


async def query_voice(voice_id: str) -> dict:
    """查询音色详情，返回 ``{status, target_model, gmt_create, resource_link}``。"""
    if not voice_id:
        raise VoiceCloneError("缺少 voice_id")
    payload = {
        "model": ENROLLMENT_MODEL,
        "input": {"action": "query_voice", "voice_id": voice_id},
    }
    body = await _post(CUSTOMIZATION_URL, payload, timeout=30.0)
    resp = body.pop("__resp__")
    body.pop("__status__", None)
    _raise_for_dashscope(resp, body, "查询音色详情")
    return body.get("output") or {}


async def list_voices(*, prefix: str = "", page_index: int = 0, page_size: int = 50) -> list[dict]:
    """查询音色列表。CosyVoice 侧返回 ``voice_list``（无分页字段）。"""
    inp: dict = {"action": "list_voice", "page_index": page_index, "page_size": page_size}
    if prefix:
        inp["prefix"] = prefix
    payload = {"model": ENROLLMENT_MODEL, "input": inp}
    body = await _post(CUSTOMIZATION_URL, payload, timeout=30.0)
    resp = body.pop("__resp__")
    body.pop("__status__", None)
    _raise_for_dashscope(resp, body, "查询音色列表")
    return list((body.get("output") or {}).get("voice_list") or [])


async def delete_voice(voice_id: str) -> None:
    """删除音色（释放配额）。"""
    if not voice_id:
        raise VoiceCloneError("缺少 voice_id")
    payload = {
        "model": ENROLLMENT_MODEL,
        "input": {"action": "delete_voice", "voice_id": voice_id},
    }
    body = await _post(CUSTOMIZATION_URL, payload, timeout=30.0)
    resp = body.pop("__resp__")
    body.pop("__status__", None)
    _raise_for_dashscope(resp, body, "删除音色")
    logger.info(f"[cosyvoice] 音色已删除 voice_id={voice_id}")


async def wait_until_ready(
    voice_id: str,
    *,
    poll_interval: float = 5.0,
    timeout: float = 120.0,
) -> str:
    """轮询音色状态直到 ``OK``，返回最终状态。

    三种结局：``OK`` 直接返回；``UNDEPLOYED`` 抛错（审核未过，**绝不放行**）；
    超时抛错（仍在 DEPLOYING，提示用户稍后重试而非静默降级）。
    """
    waited = 0.0
    while waited < timeout:
        info = await query_voice(voice_id)
        status = str(info.get("status") or "").upper()
        if status == STATUS_OK:
            logger.info(f"[cosyvoice] 音色就绪 voice_id={voice_id} 耗时≈{waited:.0f}s")
            return STATUS_OK
        if status == STATUS_UNDEPLOYED:
            raise VoiceCloneError(
                f"音色审核未通过（{STATUS_UNDEPLOYED}），请更换更清晰、无背景噪音的音频样本后重试"
            )
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    raise VoiceCloneError(
        f"音色仍在审核中（{STATUS_DEPLOYING}，{timeout:.0f}s 未就绪，voice_id={voice_id}），请稍后重新查询"
    )


async def synthesize(
    text: str,
    *,
    voice_id: str,
    model: str = DEFAULT_TARGET_MODEL,
    audio_format: str = "mp3",
    sample_rate: int = 24000,
) -> str:
    """用复刻音色合成语音，返回**音频 URL**（★ 24 小时后过期，调用方必须转存）。

    ``model`` 必须与创建音色时的 ``target_model`` 完全一致，否则合成失败。
    """
    if not (text or "").strip():
        raise VoiceCloneError("合成文本为空")
    if not voice_id:
        raise VoiceCloneError("缺少 voice_id")
    if model not in SUPPORTED_TARGET_MODELS:
        raise VoiceCloneError(f"不支持的合成模型：{model}")

    payload = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice_id,
            "format": audio_format,
            "sample_rate": sample_rate,
        },
    }
    body = await _post(SYNTHESIS_URL, payload, timeout=90.0)
    resp = body.pop("__resp__")
    body.pop("__status__", None)
    _raise_for_dashscope(resp, body, "语音合成")

    output = body.get("output") or {}
    url = str(output.get("audio", {}).get("url") or output.get("url") or "").strip()
    if not url:
        raise VoiceCloneError(f"语音合成未返回音频 URL：{body}")
    logger.info(f"[cosyvoice] 合成完成 voice_id={voice_id} model={model} 文本长度={len(text)}")
    return url
