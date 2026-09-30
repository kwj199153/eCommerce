"""
LLM 输出校验回归测试（★ P0-8，2026-09-27）

背景：结构化输出（JSON）解析失败时，旧实现**同形退化**成 `{"raw_text": ...}`：
  - 与「LLM 合法返回含 raw_text 字段的 JSON」同形 ⇒ 判据只能靠猜；
  - 返回类型仍是 dict ⇒ 下游 `isinstance(x, dict)` 恒真 ⇒ **失败被当成成功**；
  - `llm_structured()` 无条件 `success=True` ⇒ 上层拿不可用结果标 `enhanced=True`。

本文件钉死四件事：
  1. 失败载荷是**相异**结构（带 `__llm_parse_failed__` 标记），判定入口唯一；
  2. 合法含 `raw_text` 的 JSON **不得**被误判成失败（防假阴）；
  3. 输出被 max_tokens 截断时 `reason == "truncated"`（与纯格式错分开归因）；
  4. `llm_structured()` 在解析失败时 `success=False`（不再是假成功）。
"""

import json

import pytest

from ai_infra.base_agent import BaseAgent
from ai_infra.llm.dashscope_client import (
    FINISH_REASON_TRUNCATED,
    LLM_PARSE_FAILED_KEY,
    DashScopeLLM,
    LLMResponse,
    is_llm_parse_failed,
)
from core.observability.metrics import LLM_OUTPUT_INVALID


# ====== 1. 判定入口 ======

def test_parse_failed_payload_is_recognized():
    """失败载荷必须被唯一入口认出来"""
    payload = {LLM_PARSE_FAILED_KEY: True, "raw_text": "不是 JSON", "reason": "json_decode_error"}
    assert is_llm_parse_failed(payload) is True


def test_legal_payload_with_raw_text_key_is_not_failed():
    """★ 防假阴：LLM 合法返回含 `raw_text` 字段的 JSON，不得被判成解析失败。

    这正是旧判据 `"raw_text" in data` 会踩的坑 —— 业务完全可能让 LLM 输出
    {"raw_text": "...", "translation": "..."} 这种结构。
    """
    assert is_llm_parse_failed({"raw_text": "原文", "translation": "译文"}) is False


def test_non_dict_is_not_failed():
    assert is_llm_parse_failed([]) is False
    assert is_llm_parse_failed("raw") is False
    assert is_llm_parse_failed(None) is False


def test_mark_must_be_exactly_true():
    """标记必须是**显式布尔 True** —— 字符串 "True" / 1 都不算（防止手滑写成字符串）"""
    assert is_llm_parse_failed({LLM_PARSE_FAILED_KEY: "True"}) is False
    assert is_llm_parse_failed({LLM_PARSE_FAILED_KEY: 1}) is False
    assert is_llm_parse_failed({LLM_PARSE_FAILED_KEY: True}) is True


# ====== 2. structured_chat 的失败形态 ======

def _client(monkeypatch, content: str, finish_reason: str = "stop"):
    """构造一个 `chat()` 返回固定内容的 DashScopeLLM（不出网）。"""
    client = DashScopeLLM.__new__(DashScopeLLM)
    client.model = "qwen-max"

    async def _fake_chat(*_a, **_kw):
        return LLMResponse(
            content=content,
            model="qwen-max",
            finish_reason=finish_reason,
            raw_response={},
        )

    monkeypatch.setattr(client, "chat", _fake_chat)
    return client


@pytest.mark.asyncio
async def test_structured_chat_returns_distinct_payload_on_bad_json(monkeypatch):
    """解析失败 → 相异结构（带标记 + reason），不再是裸 `{"raw_text": ...}`"""
    client = _client(monkeypatch, "这不是 JSON")
    out = await client.structured_chat("u", "s", output_format="json")

    assert is_llm_parse_failed(out) is True
    assert out["reason"] == "json_decode_error"
    assert out["raw_text"] == "这不是 JSON"
    assert out["truncated"] is False


@pytest.mark.asyncio
async def test_structured_chat_marks_truncation_separately(monkeypatch):
    """★ 截断与纯格式错必须分开归因：前者调 max_tokens，后者改提示词"""
    client = _client(monkeypatch, '{"a": 1', finish_reason=FINISH_REASON_TRUNCATED)
    out = await client.structured_chat("u", "s", output_format="json")

    assert is_llm_parse_failed(out) is True
    assert out["reason"] == "truncated"
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_structured_chat_strips_markdown_fence(monkeypatch):
    """正常路径不受影响：```json 包裹要能剥掉"""
    body = json.dumps({"rules": [{"title": "t", "content": "c"}]}, ensure_ascii=False)
    client = _client(monkeypatch, "```json\n" + body + "\n```")
    out = await client.structured_chat("u", "s", output_format="json")

    assert is_llm_parse_failed(out) is False
    assert out["rules"][0]["title"] == "t"


@pytest.mark.asyncio
async def test_unclosed_fence_does_not_raise_indexerror(monkeypatch):
    """★ 只有开头 ``` 没有结尾时，旧实现 `split("\n",1)[1]` 会抛 IndexError。

    那会让「输出格式问题」被记成「LLM 调用失败」——归因方向直接跑偏。
    """
    client = _client(monkeypatch, "```json\n{'a': 1")
    out = await client.structured_chat("u", "s", output_format="json")

    # 不抛异常，且仍走相异失败结构
    assert is_llm_parse_failed(out) is True
    assert out["reason"] == "json_decode_error"


def test_invalid_output_metric_is_recorded():
    """失败必须进指标 —— 否则「输出不可用率」这个告警信号无从计算。

    ★ `_Counter` 有 `__slots__`，`monkeypatch.setattr(obj, "inc", ...)` 会撞
      read-only；改为从 `render()` 读真实曝光值、断言 **delta**（基线现算，
      不手写期望值 —— 手写会在别的用例先跑过时变成假红/假绿）。
    """
    from ai_infra.llm import dashscope_client as dc

    def _sample(reason: str) -> float:
        for line in LLM_OUTPUT_INVALID.render():
            if 'model="qwen-max"' in line and f'reason="{reason}"' in line:
                return float(line.rsplit(" ", 1)[1])
        return 0.0

    before = _sample("json_decode_error")
    dc._llm_parse_failed_result("x", model="qwen-max", reason="json_decode_error")
    assert _sample("json_decode_error") == before + 1


# ====== 3. llm_structured 不得再报假成功 ======

class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    async def structured_chat(self, **_kw):
        return self._payload


def _agent(payload) -> BaseAgent:
    """构造最小可用的 BaseAgent（跳过 __init__，只补 `llm_structured` 用到的属性）。"""
    agent = BaseAgent.__new__(BaseAgent)
    agent.agent_name = "test-agent"
    agent.ENABLE_LLM = True
    agent.FALLBACK_TO_MOCK = False
    agent.ANALYSIS_MODEL = "qwen-max"
    agent._llm_stats = {"errors": 0, "total_tokens": 0, "total_cost": 0.0, "calls": 0}
    agent._llm_client = _FakeLLM(payload)
    return agent


@pytest.mark.asyncio
async def test_llm_structured_reports_failure_on_unparsable_output():
    """★ 修复前：`success=True` 无条件写死 ⇒ 失败载荷被当成成功（假成功）。

    下游 `product_research` 的 `if llm_result.success and isinstance(content, dict)`
    就是这么把不可用结果标成 `enhanced=True` 的。
    """
    bad = {
        LLM_PARSE_FAILED_KEY: True,
        "raw_text": "半个 JSON",
        "reason": "truncated",
        "truncated": True,
    }
    res = await _agent(bad).llm_structured("u", "s", output_format="json")

    assert res.success is False
    assert res.error
    assert "解析失败" in res.error
    # content 仍回传（供排障），但调用方必须先看 success
    assert is_llm_parse_failed(res.content) is True


@pytest.mark.asyncio
async def test_llm_structured_still_succeeds_on_valid_json():
    """正常路径不受影响"""
    res = await _agent({"summary": "ok"}).llm_structured("u", "s", output_format="json")

    assert res.success is True
    assert res.content == {"summary": "ok"}
    assert res.error is None


# ====== 4. 形态门禁：防旧判据复活 ======

def test_no_legacy_raw_text_judgement_in_production():
    """★ 防复活：生产代码里不得再出现 ``"raw_text" in ...`` 作为解析失败判据。

    它是同一判定的第二份实现，且会把「LLM 合法返回含 raw_text 字段的 JSON」
    误判成失败（假阴）。判定只有 `is_llm_parse_failed()` 一处。

    ★ 走 AST 而不是源码 grep：grep 会被注释/docstring/本测试自己的文案骗过
      （判据禁「源码字符串包含」——docstring 会让它恒绿）。
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    hits = []
    for base in ("ai_infra", "modules"):
        for p in (root / base).rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, ast.In) for op in node.ops):
                    continue
                left = node.left
                if isinstance(left, ast.Constant) and left.value == "raw_text":
                    hits.append(f"{p.relative_to(root)}:{node.lineno}")
    assert not hits, f'仍在用旧判据 `"raw_text" in ...`（会假阴）: {hits}'
