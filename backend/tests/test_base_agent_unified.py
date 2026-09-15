"""唯一基类 BaseAgent 收敛后的结构性验收。

本文件钉住五件事，每条都对应一个**曾经真实存在**的缺陷：

1. 6 个业务 agent 都是 `BaseAgent` 子类
   —— 此前它们的基类是三元表达式 `LLMEnabledAgent if LLM_AVAILABLE else object`，
      与另一个基类互不继承，是「两套基类并行」的根源。

2. 6 个 agent 里不再有 `LLM_AVAILABLE` 三元基类与「假兜底类」
   —— `except ImportError` 里定义的兜底类**永远不会被继承**（降级时三元表达式选
      `object`），是死代码；`LLM_AVAILABLE` 判据也是冗余的（import 成功才不会加载到类体）。

3. `_mock_result` 不再谎报 `success=True`
   —— 原实现返回 `success=True` + `"[模拟响应] 由于 …"`，把「LLM 挂了」表达成
      「分析成功」，违反项目判据「异常显式降级，禁静默 mock」。

4. **图路径的 LLM 用量真的进了请求级计量器**
   —— `BaseAgent._llm_call_node` 原先对 `usage_metadata` 只打 `logger.debug`，
      从不调 `record_llm_usage`；测试之所以绿，是因为 conftest 的离线桩**自己**记了账。
      真实 `ChatOpenAI` 的 token 因此只进日志、不进 `subscriptions` 表，
      走图路径的「店秘书」与「router 层」消耗全部漏计。

5. **RAG 链路的「生产者 ↔ 消费者」字段名双向一致**
   —— 这条链上曾同时存在三层独立的失配，任一层坏掉都表现为「RAG 静默降级」：
      ① 生产者写 `LLMCallResult(_sources=...)`，dataclass 无该字段 ⇒ TypeError ⇒ except 降级
      ② 消费者读 `hasattr(rag_result, '_sources')`，真名是 `sources` ⇒ 恒 False ⇒ 引用来源恒空
      ③ 消费者读 `sentiment.level`，`SentimentAnalysis` 的字段是 `sentiment`
         ⇒ AttributeError ⇒ 外层 except 吞掉 ⇒ **RAG 路径从未真正生效过**
"""


import pathlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_infra.base_agent import BaseAgent

# conftest 的 autouse 夹具 `_no_real_llm` 会**类级**替换
# `BaseAgent._llm_with_tools` 为离线桩。这里在收集期（早于夹具执行）保存原始实现，
# 供「未打桩路径」的断言使用。
_ORIGINAL_LLM_WITH_TOOLS = BaseAgent._llm_with_tools

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# (模块路径, 文件名, 类名)
BUSINESS_AGENTS = [
    ("ad_analysis", "agent_ad.py", "AdAnalysisAgent"),
    ("aigc_media", "agent_aigc.py", "AIGCMediaAgent"),
    ("competitor_intel", "agent_competitor.py", "CompetitorIntelligenceAgent"),
    ("customer_service", "agent_cs.py", "CustomerServiceAgent"),
    ("listing_generator", "agent_listing.py", "ListingGeneratorAgent"),
    ("product_research", "agent_product_research.py", "ProductResearchAgent"),
]


def _agent_files():
    for mod, fname, clsname in BUSINESS_AGENTS:
        yield mod, fname, clsname, BACKEND / "modules" / mod / fname


# ---------------------------------------------------------------- 1. 继承关系


@pytest.mark.parametrize("mod,fname,clsname", BUSINESS_AGENTS)
def test_business_agent_inherits_base_agent(mod, fname, clsname):
    """6 个业务 agent 必须（直接）继承唯一基类 BaseAgent。"""
    from ai_infra.base_agent import BaseAgent

    module = __import__(f"modules.{mod}.{fname[:-3]}", fromlist=[clsname])
    cls = getattr(module, clsname)

    assert issubclass(cls, BaseAgent), f"{clsname} 未继承 BaseAgent"
    # 直接基类就应是 BaseAgent（不是某个中间壳）
    assert BaseAgent in cls.__bases__, (
        f"{clsname}.__bases__={cls.__bases__}，应为 (BaseAgent,)"
    )


# ---------------------------------------------------------------- 2. 无残留


@pytest.mark.parametrize("mod,fname,clsname", BUSINESS_AGENTS)
def test_no_llm_available_or_fake_fallback(mod, fname, clsname):
    """不得再有 `LLM_AVAILABLE` / `LLMEnabledAgent` / 旧 integration 导入。"""
    text = (BACKEND / "modules" / mod / fname).read_text(encoding="utf-8")

    assert "LLM_AVAILABLE" not in text, f"{fname}: 仍有 LLM_AVAILABLE 残留"
    assert "LLMEnabledAgent" not in text, f"{fname}: 仍有 LLMEnabledAgent 残留"
    assert "from ai_infra.llm.integration" not in text, (
        f"{fname}: 仍在导入已删除的 ai_infra.llm.integration"
    )
    # 「假兜底类」的特征写法
    assert "class LLMEnabledAgent" not in text, f"{fname}: 仍有假兜底类"


def test_integration_module_is_removed():
    """LLMEnabledAgent 所在的壳模块应已被删除（能力已并入 BaseAgent）。"""
    assert not (BACKEND / "ai_infra" / "llm" / "integration.py").exists()


def test_llm_call_result_lives_in_base_agent():
    """LLMCallResult 应随壳一起并入 base_agent，且带 sources 字段。

    `sources` 字段是修掉的真 bug：原 `llm_rag_answer` 以 `_sources=` 传入，
    而 dataclass 无该字段 ⇒ 成功路径必抛 TypeError 并被 except 吞掉，
    症状是「RAG 问答永远降级成普通 LLM」。
    """
    from ai_infra.base_agent import LLMCallResult

    fields = set(LLMCallResult.__dataclass_fields__)
    assert "sources" in fields, "LLMCallResult 缺少 sources 字段"
    assert {"success", "content", "fallback", "error"} <= fields


# ---------------------------------------------------------------- 3. 降级语义


def test_mock_result_does_not_report_success():
    """降级结果必须诚实表达失败：success=False + error 有原因 + 内容留空。"""
    from ai_infra.base_agent import BaseAgent

    agent = BaseAgent(agent_name="mock-probe")
    result = agent._mock_result("原始查询", "unit-test-reason")

    assert result.success is False, "降级结果不得报告 success=True（禁静默 mock）"
    assert result.fallback is True
    assert result.error and "unit-test-reason" in result.error
    assert result.content == "", "降级时内容应留空（空状态优于虚构默认）"
    assert agent.llm_stats["mock_calls"] == 1


# ---------------------------------------------------------------- 4. 计费


class _MeterStubLLM:
    """只回一条带 usage_metadata 的 AIMessage，不打网络。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(
            content="stub",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            },
        )


async def test_graph_path_records_llm_usage(monkeypatch):
    """`_llm_call_node` 必须把 usage_metadata 记入请求级计量器。

    ★ 反向注入验证：把 base_agent.py 中 `_llm_call_node` 里的
      `record_llm_usage(...)` 调用删掉，本用例立即变红（snapshot.calls 为 0）。
      改造前该路径**没有任何测试覆盖**——绿是假绿，靠 conftest 的桩代为记账。
    """
    from core.billing.llm_meter import reset_meter, snapshot

    from ai_infra.base_agent import BaseAgent

    agent = BaseAgent(agent_name="meter-probe")
    monkeypatch.setattr(agent, "_llm_with_tools", lambda: _MeterStubLLM())

    reset_meter()
    await agent._llm_call_node({"messages": [HumanMessage(content="hi")]})
    snap = snapshot()

    assert snap.calls == 1, "图路径的 LLM 调用未被计量（record_llm_usage 未生效）"
    assert snap.input_tokens == 100
    assert snap.output_tokens == 50
    assert snap.total_tokens == 150
    # 成本必须复用 DashScopeLLM 的定价口径（唯一真源），而不是恒 0
    assert snap.cost > 0, "成本未被计算（应复用 DashScopeLLM._compute_cost）"
    assert snap.models.get("qwen-plus", 0) == 1


async def test_graph_path_metering_is_idempotent_per_call(monkeypatch):
    """同一请求内两次节点调用应累加，而不是相互覆盖。"""
    from core.billing.llm_meter import reset_meter, snapshot

    from ai_infra.base_agent import BaseAgent

    agent = BaseAgent(agent_name="meter-probe-2")
    monkeypatch.setattr(agent, "_llm_with_tools", lambda: _MeterStubLLM())

    reset_meter()
    await agent._llm_call_node({"messages": [HumanMessage(content="a")]})
    await agent._llm_call_node({"messages": [HumanMessage(content="b")]})
    snap = snapshot()

    assert snap.calls == 2
    assert snap.input_tokens == 200
    assert snap.total_tokens == 300


# ---------------------------------------------------------------- 5. 无参 super


def test_bare_super_call_is_supported():
    """子类以 `super().__init__()` 无参调用必须可用（6 个 agent 的实际形态）。"""

    from ai_infra.base_agent import BaseAgent

    class _Sub(BaseAgent):
        ENABLE_LLM = True

        def __init__(self):
            super().__init__()
            self.agent_name = "sub_agent"      # 子类在 super 之后覆盖
            self.system_prompt = "you are sub"

    s = _Sub()
    assert s.agent_name == "sub_agent"
    assert s.tools == []
    # default_metadata 是 property，必须反映**覆盖后**的 agent_name
    assert s.default_metadata["agent_name"] == "sub_agent"


def test_llm_with_tools_raises_explicitly_when_llm_unavailable():
    """图路径缺 LLM 时给显式错误，而不是 AttributeError: 'NoneType'。

    ★ 必须调用**原始**实现（`_ORIGINAL_LLM_WITH_TOOLS`）：conftest 已把该
      类方法整体替换为离线桩，桩当然不会抛错 —— 直接调 `agent._llm_with_tools()`
      会因夹具而变成一次无效断言（这正是本用例第一次写时踩的坑）。
    """
    agent = BaseAgent(agent_name="nollm")
    agent._llm_override = None
    agent._llm_resolved = True
    agent._llm_default = None

    with pytest.raises(RuntimeError) as ei:
        _ORIGINAL_LLM_WITH_TOOLS(agent)
    assert "LangChain 模型" in str(ei.value)


# ---------------------------------------------------------------- 6. RAG 契约双向门禁

# 门禁必须**双向**：既断言生产者把字段带出来，也**真跑消费者**断言未静默降级。
# 只断言前者 = 上一轮那 19 项测试的形态（测试全绿而 RAG 从未生效）。


def test_llm_call_result_declares_rag_contract_fields():
    """生产者侧：字段名必须与消费者的读取名一致。"""
    from ai_infra.base_agent import LLMCallResult

    fields = set(LLMCallResult.__dataclass_fields__)
    assert "sources" in fields, "缺 sources ⇒ 消费者读不到引用来源"
    assert "confidence" in fields, "缺 confidence ⇒ 消费者读到恒 0"
    # 反向：带下划线的私有名是历史错误形态，不得再出现
    assert "_sources" not in fields, "字段名不得退回 `_sources`（消费者按 `sources` 读）"
    assert "_confidence" not in fields


def test_agent_cs_does_not_read_nonexistent_attributes():
    """消费者侧（静态）：不得再读不存在的属性。

    ★ 剥注释后断言 —— 否则讲解「原写法」的注释会把本用例绊倒。
    """
    src = (BACKEND / "modules" / "customer_service" / "agent_cs.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        ln for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )
    assert "_sources" not in code, (
        "agent_cs 仍读 `_sources`：LLMCallResult 无该属性 ⇒ hasattr 恒 False "
        "⇒ 引用来源恒空、静默丢失"
    )
    assert "sentiment.level" not in code, (
        "agent_cs 仍读 `sentiment.level`：SentimentAnalysis 无该字段 "
        "⇒ AttributeError ⇒ 整条 RAG 路径静默降级到关键词匹配"
    )
    # 正向锚：必须读到真名
    assert "rag_result.sources" in code, "应直读 `rag_result.sources`"
    assert "rag_result.confidence" in code, "应直读 `rag_result.confidence`"


@pytest.mark.asyncio
async def test_customer_service_rag_path_does_not_silently_degrade():
    """消费者侧（行为）：真跑 `_handle_faq_query`，必须走 RAG 而非静默降级。

    ★ 本组核心门禁 —— 一次性覆盖上文三层失配。
      反向注入：把任一层改回旧写法，本用例必红。
    """
    from ai_infra.rag import Document, RAGResponse, RetrievalResult
    from modules.customer_service.agent_cs import (
        ConversationContext,
        CustomerServiceAgent,
    )

    class _StubRAG:
        """桩 RAG 引擎：不碰网络/embedding，只回一个带 sources + confidence 的结果。"""

        async def answer(self, query, llm_client=None, system_prompt=None, top_k=3):
            return RAGResponse(
                answer="订单在支付成功后 24-48 小时内发货。",
                sources=[
                    RetrievalResult(
                        document=Document(
                            page_content="订单发货需要多长时间？", doc_id="d1"
                        ),
                        score=0.91,
                        source="hybrid",
                    ),
                    RetrievalResult(
                        document=Document(
                            page_content="如何查看物流信息？", doc_id="d2"
                        ),
                        score=0.83,
                        source="hybrid",
                    ),
                ],
                query=query,
                confidence=0.87,
                fallback=False,
            )

    agent = CustomerServiceAgent()
    # 短路懒加载属性，避免真调 embedding / LLM
    agent._rag_engine = _StubRAG()
    agent._llm_client = object()
    agent._rag_initialized = True

    resp = await agent._handle_faq_query(
        "订单多久发货？",
        None,
        ConversationContext(conversation_id="unified-rag-test"),
        agent._analyze_sentiment("订单多久发货？"),
    )

    assert resp.data.get("source") == "rag_hybrid", (
        f"未走 RAG 路径（实际 source={resp.data.get('source')!r}）"
        " —— RAG 链路又被静默降级了"
    )
    assert resp.data["sources"], "引用来源为空 ⇒ 消费者没读到 sources"
    assert resp.data["confidence"] == 0.87, "置信度没传到消费者"
    assert resp.data["type"] == "rag_answer"
    assert "参考了 2 条知识库文献" in resp.content
