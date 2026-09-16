"""通义万相出图客户端（REST 异步任务：提交 → 轮询）。

支持两条通道，**端点和模型都不同**，别混：

- **文生图** ``text2image``  → ``/services/aigc/text2image/image-synthesis`` + ``wanx2.1-t2i-turbo``
- **图生图** ``image_edit``  → ``/services/aigc/image2image/image-synthesis`` + ``wanx2.1-imageedit``

为什么不用 dashscope SDK：requirements 里没有这个依赖，项目既有的 LLM 调用
（``ai_infra/llm/dashscope_client.py``）也是 httpx 直连，保持一致。

★ 图生图的底图**不需要图床**：官方文档明确 ``base_image_url`` 三选一 ——
公网 URL / 本地文件（仅 SDK）/ **base64 data URI**。前端 ``readAsDataURL`` 产出
的 ``data:image/png;base64,...`` 可直接透传。（曾经以为必须公网地址而放弃图生图，
是误判。）

两个实测坑（2026-09-13 真机验证）：
1. ``size`` 必须写 ``1024*1024``（**星号**）。写小写 ``x`` 会返回
   ``InvalidParameter: size is not in the correct format``。
2. 出图返回的是 OSS 临时链接，**24 小时过期**（实测 ``Expires`` 窗口正好 24h）
   → 调用方必须转存（见 ``storage.persist_remote_image``），否则归档到素材库
   的图片次日全部失效。

另一个坑（2026-09-14）：图生图端点的 ``parameters`` **不接受 size / negative_prompt**
（通用图像编辑只有 n / seed / watermark + 功能专属参数如 strength）→ 硬塞会被拒。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import httpx

from core.logger import get_logger
from core.resilience import RetryPolicy, call_with_retry

logger = get_logger(__name__)

_API_BASE = "https://dashscope.aliyuncs.com/api/v1"
SUBMIT_URL = f"{_API_BASE}/services/aigc/text2image/image-synthesis"
#: 图生图（图像编辑）是**另一个端点**，别与 text2image 混用
IMAGE_EDIT_URL = f"{_API_BASE}/services/aigc/image2image/image-synthesis"
TASK_URL = _API_BASE + "/tasks/{task_id}"

#: turbo ≈ 15-25s / 约 ¥0.14 每张；plus 更精细但 30-60s、更贵
DEFAULT_MODEL = "wanx2.1-t2i-turbo"
#: 图生图模型：wanx2.1-imageedit（官方文档实测同价 ¥0.14/张）
DEFAULT_EDIT_MODEL = "wanx2.1-imageedit"
#: 分辨率必须用星号分隔（实测小写 x 被拒）
DEFAULT_SIZE = "1024*1024"

#: 图生图默认编辑指令（description_edit = 按文字指令改图，产品主体尽量保持不变）
DEFAULT_EDIT_FUNCTION = "description_edit"
#: 修改幅度 [0,1]。偏小 → 更忠于原图（电商要的是「保产品、换背景」）
DEFAULT_EDIT_STRENGTH = 0.5

#: 单次请求最多并发出图数，避免触发服务端限流。
#: 实测（2026-09-14）：3 并发提交 4 张时 2 张被服务端 429 拒掉，
#: 降到 2 并发 + 退避重试后 4 张全成。
MAX_CONCURRENCY = 2

#: 命中这些关键词 → 判定为「可重试」（服务端瞬时压力，等一会儿就好）。
#: ★ 这是**万相特有的 provider 知识**，所以留在本模块 ——
#:   resilience 只提供判定钩子（`RetryPolicy.retry_if`），不替我们决定
#:   万相的错误码长什么样。
_RETRYABLE_MARKERS = ("429", "throttling", "ratequota", "rate limit", "超时", "timeout")


def _is_retryable(exc: BaseException) -> bool:
    """万相的失败是**业务错误码 / 文案**（如 ``Throttling.RateQuota``），

    抛出来的是 ``ImageGenError`` 而不是 ``httpx.HTTPStatusError`` ——
    所以"该不该重试"只能从文案里读，类型判定帮不上忙。
    这正是 ``RetryPolicy.retry_if`` 存在的理由。
    """
    low = str(exc).lower()
    return any(m in low for m in _RETRYABLE_MARKERS)


#: 万相出图的重试策略（第 96 轮收敛到 `core/resilience.py`，逻辑不再写在本地）。
#:   · ``attempts=4`` = 1 次初始 + 3 次重试 —— 与原
#:     ``for attempt in range(MAX_RETRIES + 1)`` 配 ``attempt < MAX_RETRIES``
#:     的**实际**语义一致（原代码写成 MAX_RETRIES=3，实际跑 4 次）。
#:   · 退避 ``2s → 5s → 10s``：``base=2 × 2.5^(n-1)`` = 2 / 5 / 12.5，
#:     过 ``max_delay=10`` 封顶 ⇒ 2 / 5 / 10，与原固定表 ``RETRY_BACKOFF_SECONDS``
#:     **逐项等价**（不是"差不多"）。
#:   · ``retry_if``：上面的文案判定（不给它，classify 认不出 ImageGenError）。
_RETRY_POLICY = RetryPolicy(
    attempts=4,
    base_delay=2.0,
    multiplier=2.5,
    max_delay=10.0,
    retry_if=_is_retryable,
)


class ImageGenError(RuntimeError):
    """文生图失败：未配置密钥 / 提交被拒 / 任务 FAILED / 超时。"""


def is_enabled() -> bool:
    """真实出图开关。设 ``AIGC_IMAGE_REAL_GEN=0`` 可关闭（测试与离线演示用）。"""
    return os.getenv("AIGC_IMAGE_REAL_GEN", "1").strip().lower() not in ("0", "false", "no")


def _api_key() -> str:
    """取 DashScope API Key。

    顺序与 ``ai_infra/llm/dashscope_client.py`` 保持一致：**先 config 后环境变量**。
    原因：`.env` 是由 pydantic-settings 读进 ``Settings`` 对象的，它**不会**写进
    ``os.environ`` —— 只用 ``os.getenv`` 在正常启动路径下会拿不到 key。
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
        raise ImageGenError("缺少 DashScope API Key（config.dashscope_api_key 与环境变量 DASHSCOPE_API_KEY 均为空）")
    return key


def _headers(async_mode: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_api_key()}"}
    if async_mode:
        # 万相只支持异步调用；缺这个 header 会直接报错
        headers["X-DashScope-Async"] = "enable"
    return headers


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"message": (resp.text or "")[:200]}


async def submit(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    n: int = 1,
    negative_prompt: str | None = None,
) -> str:
    """提交出图任务，返回 ``task_id``。"""
    payload: dict = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": n},
    }
    if negative_prompt:
        payload["input"]["negative_prompt"] = negative_prompt

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(SUBMIT_URL, json=payload, headers=_headers(async_mode=True))

    body = _safe_json(resp)
    if resp.status_code >= 400 or body.get("code"):
        raise ImageGenError(
            f"提交失败（HTTP {resp.status_code}）：{body.get('code')} {body.get('message')}"
        )

    task_id = str(((body.get("output") or {}).get("task_id") or "")).strip()
    if not task_id:
        raise ImageGenError(f"提交未返回 task_id：{body}")
    logger.info(f"[wanx] 出图任务已提交 task_id={task_id} model={model} n={n}")
    return task_id


async def wait_for_images(
    task_id: str,
    *,
    poll_interval: float = 3.0,
    timeout: float = 180.0,
) -> list[str]:
    """轮询任务直到 SUCCEEDED，返回图片 URL 列表（**24h 后过期**）。"""
    waited = 0.0
    async with httpx.AsyncClient(timeout=20.0) as client:
        while waited < timeout:
            await asyncio.sleep(poll_interval)
            waited += poll_interval
            resp = await client.get(TASK_URL.format(task_id=task_id), headers=_headers())
            body = _safe_json(resp)
            output = body.get("output") or {}
            status = output.get("task_status")

            if status == "SUCCEEDED":
                urls = [r["url"] for r in (output.get("results") or []) if r.get("url")]
                if not urls:
                    raise ImageGenError("任务成功但未返回图片 URL")
                logger.info(f"[wanx] 出图完成 task_id={task_id} 张数={len(urls)} 耗时≈{waited:.0f}s")
                return urls
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise ImageGenError(f"出图任务 {status}：{output.get('code')} {output.get('message')}")

    raise ImageGenError(f"出图任务超时（{timeout:.0f}s 未完成，task_id={task_id}）")


async def text2image(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    n: int = 1,
    negative_prompt: str | None = None,
    poll_interval: float = 3.0,
    timeout: float = 180.0,
) -> list[str]:
    """提交 + 轮询一步到位，返回图片 URL 列表（**24h 后过期，需转存**）。"""
    task_id = await submit(prompt, model=model, size=size, n=n, negative_prompt=negative_prompt)
    return await wait_for_images(task_id, poll_interval=poll_interval, timeout=timeout)


async def _gather_many(
    items: list[str],
    runner: Callable[[str], Awaitable[list[str]]],
    *,
    concurrency: int = MAX_CONCURRENCY,
) -> list[tuple[str, str | None, str | None]]:
    """并发出图跑批：``runner`` 收单个提示词、返回图片 URL 列表。

    把「并发闸门 + 限流退避重试 + 逐项降级」抽出来给文生图/图生图共用 ——
    两条通道的失败模式完全一样（服务端 429 / 超时），没理由写两遍。
    单个失败不影响其余（长任务里最怕一张图挂掉就全灭）。
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(prompt: str) -> tuple[str, str | None, str | None]:
        """单张出图：限流/超时会退避重试，其余错误直接降级（**不抛**）。

        ★ 两条语义必须原样保留（收敛只搬逻辑）：
          1. **逐项降级**：单张失败返回 ``(prompt, None, 原因)`` 而不是抛错 ——
             长任务里最怕一张图挂掉就全灭。
          2. 两条日志：重试时的 warning、以及**重试后成功**的 info
             （后者是运维信号：出现过抖动但恢复了）。用 ``retried`` 计数器
             在 ``on_retry`` 回调里记下，成功时补打。
        """
        async with sem:
            retried = {"n": 0}

            def _note(_what: str, attempt: int, attempts: int, delay: float, exc: BaseException) -> None:
                retried["n"] = attempt
                logger.warning(
                    f"[wanx] 第 {attempt}/{attempts} 次失败（可重试），{delay:.0f}s 后重试：{str(exc)[:140]}"
                )

            try:
                urls = await call_with_retry(
                    lambda: runner(prompt),
                    policy=_RETRY_POLICY,
                    what=f"wanx 出图（{prompt[:24]}）",
                    on_retry=_note,
                )
                first = urls[0]
            except Exception as exc:  # noqa: BLE001 - 逐项降级，把原因带给调用方
                logger.error(f"[wanx] 单张出图失败：{exc}")
                return prompt, None, str(exc)

            if retried["n"]:
                logger.info(f"[wanx] 第 {retried['n']} 次重试成功")
            return prompt, first, None

    return await asyncio.gather(*(_one(p) for p in items))


async def text2image_many(
    prompts: list[str],
    *,
    concurrency: int = MAX_CONCURRENCY,
    **kwargs,
) -> list[tuple[str, str | None, str | None]]:
    """并发出多张文生图，返回 ``[(prompt, urls[0], error), ...]``（顺序与入参一致）。"""

    async def _run(prompt: str) -> list[str]:
        return await text2image(prompt, **kwargs)

    return await _gather_many(prompts, _run, concurrency=concurrency)


async def submit_image_edit(
    prompt: str,
    *,
    base_image: str,
    model: str = DEFAULT_EDIT_MODEL,
    function: str = DEFAULT_EDIT_FUNCTION,
    strength: float | None = DEFAULT_EDIT_STRENGTH,
    n: int = 1,
) -> str:
    """提交图生图（图像编辑）任务，返回 ``task_id``。

    ``base_image`` 支持**公网 URL 或 base64 data URI**（``data:image/png;base64,...``）。
    实测前端 ``FileReader.readAsDataURL`` 的产物可直接用，**无需图床**。

    注意：本端点的 ``parameters`` 不收 ``size`` / ``negative_prompt``。
    """
    payload: dict = {
        "model": model,
        "input": {
            "function": function,
            "prompt": prompt,
            "base_image_url": base_image,
        },
        "parameters": {"n": n},
    }
    # strength 仅对 stylization_all / description_edit 有意义
    if strength is not None and function in ("stylization_all", "description_edit"):
        payload["parameters"]["strength"] = strength

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(IMAGE_EDIT_URL, json=payload, headers=_headers(async_mode=True))

    body = _safe_json(resp)
    if resp.status_code >= 400 or body.get("code"):
        raise ImageGenError(
            f"图生图提交失败（HTTP {resp.status_code}）：{body.get('code')} {body.get('message')}"
        )

    task_id = str(((body.get("output") or {}).get("task_id") or "")).strip()
    if not task_id:
        raise ImageGenError(f"图生图提交未返回 task_id：{body}")
    logger.info(
        f"[wanx] 图生图任务已提交 task_id={task_id} model={model} function={function} n={n} "
        f"base_image={'base64(%d字符)' % len(base_image) if base_image.startswith('data:') else base_image[:80]}"
    )
    return task_id


async def image_edit(
    prompt: str,
    *,
    base_image: str,
    model: str = DEFAULT_EDIT_MODEL,
    function: str = DEFAULT_EDIT_FUNCTION,
    strength: float | None = DEFAULT_EDIT_STRENGTH,
    n: int = 1,
    poll_interval: float = 3.0,
    timeout: float = 180.0,
) -> list[str]:
    """提交 + 轮询一步到位，返回图片 URL 列表（**24h 后过期，需转存**）。"""
    task_id = await submit_image_edit(
        prompt,
        base_image=base_image,
        model=model,
        function=function,
        strength=strength,
        n=n,
    )
    return await wait_for_images(task_id, poll_interval=poll_interval, timeout=timeout)


async def image_edit_many(
    prompts: list[str],
    *,
    base_image: str,
    concurrency: int = MAX_CONCURRENCY,
    **kwargs,
) -> list[tuple[str, str | None, str | None]]:
    """并发出多张图生图（**同一张底图**配不同提示词，返回顺序与入参一致）。"""

    async def _run(prompt: str) -> list[str]:
        return await image_edit(prompt, base_image=base_image, **kwargs)

    return await _gather_many(prompts, _run, concurrency=concurrency)
