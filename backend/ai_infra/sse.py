"""
SSE（Server-Sent Events）流式输出工具

为业务 Agent 提供统一的 SSE 事件流封装，把 LLM 的逐 token 输出
转发给前端实现打字机效果。

统一事件协议（text/event-stream，每条以 \\n\\n 分隔）：
    event: delta         # 增量文本
    data: {"text": "..."}

    event: meta          # 元信息（可选：结构化结果、展示类型）
    data: {"display_type": "...", "data": {...}}

    event: done          # 结束
    data: {"text": "完整文本"}

    event: error         # 出错
    data: {"message": "..."}

使用方式：
    from ai_infra.sse import sse_event_stream

    @router.post("/chat/stream")
    async def chat_stream(request: ...):
        async def gen():
            async for chunk in agent.llm_stream(prompt, ...):
                yield sse_event("delta", {"text": chunk})
            yield sse_event("done", {"text": full})
        return StreamingResponse(gen(), media_type="text/event-stream")
"""

import json
from typing import AsyncIterable, Optional


def sse_event(event: str, data: dict) -> str:
    """构造单条 SSE 消息（含 event 字段和 JSON data）"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_comment(text: str) -> str:
    """发送 SSE 注释（用于 keep-alive，前端会忽略）"""
    return f": {text}\n\n"


async def sse_keepalive() -> AsyncIterable[str]:
    """心跳占位（可选，由调用方按需使用）"""
    yield sse_comment("keep-alive")


async def sse_event_stream(
    chunks: AsyncIterable[str],
    meta: Optional[dict] = None,
    full_text: str = "",
) -> AsyncIterable[str]:
    """
    把逐段文本流包装成标准 SSE 事件流。

    Args:
        chunks: 逐 token 文本迭代器
        meta: 可选的元信息（结构化数据 + 展示类型），在 done 前发送
        full_text: 累计的完整文本（若不传则内部累加）
    """
    accumulated = full_text

    async for chunk in chunks:
        if chunk is None:
            continue
        chunk = str(chunk)
        if not chunk:
            continue
        accumulated += chunk
        yield sse_event("delta", {"text": chunk})

    if meta:
        yield sse_event("meta", meta)

    yield sse_event("done", {"text": accumulated})
