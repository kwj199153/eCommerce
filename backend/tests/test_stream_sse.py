"""
SSE 流式输出回归测试

覆盖：
1. 6 个 Agent 的 /chat/stream 端点均已注册
2. SSE 响应头正确（text/event-stream）
3. 事件协议正确：delta 增量 + done 收尾
4. LLM 不可用时降级为规则引擎文本（不报错）
"""

import json

import pytest


STREAM_ENDPOINTS = [
    ("/api/v1/listing/chat/stream", {"message": "生成一款便携咖啡研磨器的标题"}, "json"),
    ("/api/v1/ad-analysis/chat/stream", {"message": "给我一些广告优化建议"}, "json"),
    ("/api/v1/customer-service/chat/stream", {"message": "你们的退换货政策是什么"}, "json"),
    ("/api/v1/aigc/chat/stream", {"message": "帮我写一段品牌故事"}, "json"),
    ("/api/v1/competitor/chat/stream?query=分析市场", None, "query"),
    ("/api/v1/product-research/chat/stream", {"message": "帮我分析厨房用品"}, "json"),
]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析成 [(event, data_dict), ...]"""
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event, data = None, {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = {"raw": line[6:]}
        if event:
            events.append((event, data))
    return events


def test_all_six_stream_endpoints_registered():
    """6 个 Agent 都应有 /chat/stream 端点"""
    from main import app

    paths = {r.path for r in app.routes if hasattr(r, "path")}
    expected = [
        "/api/v1/listing/chat/stream",
        "/api/v1/ad-analysis/chat/stream",
        "/api/v1/customer-service/chat/stream",
        "/api/v1/aigc/chat/stream",
        "/api/v1/competitor/chat/stream",
        "/api/v1/product-research/chat/stream",
    ]
    missing = [p for p in expected if p not in paths]
    assert not missing, f"缺失流式端点: {missing}"


async def test_listing_stream_returns_sse_events(client, auth_off, fake_llm):
    r = await client.post(
        "/api/v1/listing/chat/stream",
        json={"message": "生成一款便携咖啡研磨器的标题"},
    )
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers.get("content-type", "")

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "delta" in kinds, f"缺少 delta 事件: {kinds}"
    assert "done" in kinds, f"缺少 done 事件: {kinds}"

    streamed = "".join(d.get("text", "") for e, d in events if e == "delta")
    done_text = next(d.get("text", "") for e, d in events if e == "done")
    assert streamed, "delta 内容为空"
    assert done_text == streamed, "done 的完整文本应与 delta 累积一致"


async def test_listing_stream_degrades_without_llm(client, auth_off, monkeypatch):
    """关闭 LLM 时，流式端点应降级为规则引擎文本而非报错"""
    from modules.listing_generator.agent_listing import ListingGeneratorAgent

    monkeypatch.setattr(ListingGeneratorAgent, "ENABLE_LLM", False)

    r = await client.post(
        "/api/v1/listing/chat/stream",
        json={"message": "生成一款便携咖啡研磨器的标题"},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "error" not in kinds, f"降级路径不应报错: {events}"
    assert any(e in ("delta", "done") for e in kinds), f"降级应有文本输出: {kinds}"
    total = "".join(d.get("text", "") for e, d in events)
    assert total.strip(), "降级输出为空"


@pytest.mark.parametrize("path,payload,kind", STREAM_ENDPOINTS)
async def test_all_stream_endpoints_respond(client, auth_off, fake_llm, path, payload, kind):
    """所有流式端点都应返回 SSE 且不 5xx"""
    if kind == "json":
        r = await client.post(path, json=payload)
    else:
        r = await client.post(path)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    assert "text/event-stream" in r.headers.get("content-type", ""), path
