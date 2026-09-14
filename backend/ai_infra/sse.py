"""
SSE（Server-Sent Events）流式输出工具

为业务 Agent 提供统一的 SSE 事件流封装，把 LLM 的逐 token 输出
转发给前端实现打字机效果。

统一事件协议（text/event-stream，每条以 \\n\\n 分隔）：
    event: delta         # 增量文本
    data: {"text": "..."}

    event: progress      # 阶段进度（耗时步骤前的状态提示，非正文）
    data: {"text": "正在挖掘蓝海品类数据…"}

    event: meta          # 元信息（可选：结构化结果、展示类型）
    data: {"display_type": "...", "data": {...}}

    event: done          # 结束
    data: {"text": "完整文本"}

    event: error         # 出错
    data: {"message": "..."}

使用方式：
    from ai_infra.sse import sse_event_stream, progress

    @router.post("/chat/stream")
    async def chat_stream(request: ...):
        async def gen():
            async for chunk in agent.llm_stream(prompt, ...):
                yield sse_event("delta", {"text": chunk})
            yield sse_event("done", {"text": full})
        return StreamingResponse(gen(), media_type="text/event-stream")

    # 迭代器里混入 progress：yield 一个 dict 即会被识别成 progress 事件
    async def gen():
        yield progress("正在分析…")          # → event: progress
        yield "正文片段"                      # → event: delta
"""

import json
from typing import AsyncIterable, Optional


def sse_event(event: str, data: dict) -> str:
    """构造单条 SSE 消息（含 event 字段和 JSON data）"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def progress(text: str) -> dict:
    """构造一条「阶段进度」标记。

    供各业务 Agent 的 stream_chat 在**耗时步骤之前** yield，
    让前端把「AI 正在思考…」换成具体的阶段文案（如「正在挖掘蓝海品类数据…」），
    避免长任务期间零输出导致的「卡死」错觉。

    注意：这是迭代器里的**结构化 chunk**（dict），由 sse_event_stream 识别并
    转成 `event: progress`；它不计入正文，因此不会被拼进最终文本。
    """
    return {"event": "progress", "text": text}


def sse_comment(text: str) -> str:
    """发送 SSE 注释（用于 keep-alive，前端会忽略）"""
    return f": {text}\n\n"



async def sse_keepalive() -> AsyncIterable[str]:
    """心跳占位（可选，由调用方按需使用）"""
    yield sse_comment("keep-alive")


async def sse_event_stream(
    chunks: AsyncIterable,
    meta: Optional[dict] = None,
    full_text: str = "",
) -> AsyncIterable[str]:
    """
    把逐段文本流包装成标准 SSE 事件流。

    迭代器可混入两类元素：
    - str：正文增量 → `event: delta`
    - dict：结构化事件 → 按 `event` 字段分发（默认 progress），
      例如 `{"event": "progress", "text": "正在分析…"}`。
      结构化事件**不计入正文**。

    Args:
        chunks: 逐 token 文本 / 结构化事件迭代器
        meta: 可选的元信息（结构化数据 + 展示类型），在 done 前发送
        full_text: 累计的完整文本（若不传则内部累加）
    """
    accumulated = full_text

    async for chunk in chunks:
        if chunk is None:
            continue

        # 结构化事件（进度提示等）：不拼进正文，单独发一条对应事件
        if isinstance(chunk, dict):
            event_type = chunk.get("event") or "progress"
            payload = chunk.get("data")
            if payload is None:
                payload = {"text": str(chunk.get("text", ""))}
            yield sse_event(event_type, payload)
            continue

        chunk = str(chunk)
        if not chunk:
            continue
        accumulated += chunk
        yield sse_event("delta", {"text": chunk})

    if meta:
        yield sse_event("meta", meta)

    yield sse_event("done", {"text": accumulated})
