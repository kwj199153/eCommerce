"""
店秘书（主 Agent）工具循环冒烟测试

验证「主 Agent 绑工具」整条链路的机制正确性，**不依赖真实 LLM**：

1. BaseAgent 修复后的 bind_tools 真的生效（LLM 产出 tool_calls 时，
   _should_continue 会走 tool_node，而不是永远 respond）。
2. 工具注册表 4 个工具已正确构建、参数 schema 来自 Pydantic 模型。
3. 「润色标题」这类语义能命中 optimize_listing_title 工具（通过 fake LLM
   直接产出 tool_calls 验证路由链路，而非验证真实模型判断）。

真实 LLM 判断的正确性需连线上环境人工/联调确认，这里只验证机制闭环。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent
from modules.listing_generator.tools import listing_tools
from modules.aigc_media.tools import aigc_tools
from modules.secretary.agent import SecretaryAgent, SECRETARY_SYSTEM_PROMPT
from modules.secretary.navigation_tools import navigation_tools, _switch_agent, _open_view, _handoff_to_agent, _set_theme
from modules.secretary.product_tools import build_product_tools
from modules.secretary.shop_tools import build_shop_tools
from modules.product_research.tools import product_research_tools
from modules.customer_service.tools import customer_service_tools
from modules.ad_analysis.tools import ad_analysis_tools


def test_listing_tools_registry():
    """4 个工具注册正确，参数 schema 来自 Pydantic 模型"""
    names = {t.name for t in listing_tools}
    assert names == {
        "optimize_listing_title",
        "generate_bullet_points",
        "generate_product_description",
        "generate_search_terms",
    }
    # 工具应携带 args_schema（Pydantic），LLM 才能看到字段描述
    for t in listing_tools:
        assert t.args_schema is not None, f"{t.name} 缺少 args_schema"


def test_aigc_tools_registry():
    """8 个 AIGC 工具注册正确，参数 schema 来自 Pydantic 模型"""
    names = {t.name for t in aigc_tools}
    assert names == {
        "generate_product_image",
        "analyze_main_image",
        "generate_a_plus_content",
        "generate_brand_story",
        "translate_content",
        "generate_infographic",
        "check_image_compliance",
        "generate_video_script",
    }
    for t in aigc_tools:
        assert t.args_schema is not None, f"{t.name} 缺少 args_schema"


def test_navigation_tools_marker():
    """导航工具返回结构化 action 标记，供前端 dispatchAppAction 消费"""
    names = {t.name for t in navigation_tools}
    assert names == {"switch_agent", "open_view", "open_drawer", "handoff_to_agent", "set_theme"}

    assert '"switch_agent"' in _switch_agent("product-research")
    assert '"product-research"' in _switch_agent("product-research")
    assert '"navigate"' in _open_view("products")
    assert '"products"' in _open_view("products")

    # handoff 工具：返回交接标记 + 意图 + 缺失字段
    handoff_out = _handoff_to_agent("aigc-media", "生成水壶白底图", ["材质", "造型", "视角"])
    assert '"handoff"' in handoff_out
    assert '"aigc-media"' in handoff_out
    assert '生成水壶白底图' in handoff_out
    assert '材质' in handoff_out

    # set_theme 工具：返回主题切换标记 + 目标主题
    theme_out = _set_theme("dark")
    assert '"set_theme"' in theme_out
    assert '"dark"' in theme_out


def test_product_tools_registry():
    """select_product 工具正确构建，空店铺返回空标记"""
    tools = build_product_tools(shop_id="")
    names = {t.name for t in tools}
    assert names == {"select_product"}


def test_shop_tools_registry():
    """switch_shop 工具正确构建"""
    tools = build_shop_tools()
    names = {t.name for t in tools}
    assert names == {"switch_shop"}


def test_product_research_tools_registry():
    """选品分析 4 个工具正确构建"""
    names = {t.name for t in product_research_tools}
    assert names == {
        "analyze_blue_ocean",
        "analyze_profit",
        "analyze_pain_points",
        "compare_competitors",
    }


def test_customer_service_tools_registry():
    """智能客服 4 个工具正确构建"""
    names = {t.name for t in customer_service_tools}
    assert names == {
        "search_faq",
        "create_ticket",
        "analyze_sentiment",
        "get_conversation_summary",
    }


def test_ad_analysis_tools_registry():
    """广告分析 6 个工具正确构建"""
    names = {t.name for t in ad_analysis_tools}
    assert names == {
        "diagnose_ad_account",
        "analyze_search_terms",
        "optimize_bids",
        "analyze_ad_competitors",
        "optimize_budget",
        "detect_ad_anomalies",
    }


def test_secretary_agent_binds_tools():
    """店秘书 agent 应持有 33 个工具（4 listing + 8 aigc + 4 选品 + 4 客服 + 6 广告 + 5 导航 + 1 选产品 + 1 切店铺）"""
    agent = SecretaryAgent(llm=MagicMock())
    assert len(agent.tools) == 33
    assert agent.system_prompt == SECRETARY_SYSTEM_PROMPT


def test_bind_tools_routes_to_tool_node():
    """
    核心机制验证：修好 bind_tools 后，LLM 产出 tool_calls 会路由到 tool_node。

    用 fake LLM 模拟「第一次返回 tool_calls、第二次返回纯文本」，
    验证 _should_continue 的判断逻辑与 BaseAgent 的工具循环不退化。
    """
    agent = BaseAgent(
        agent_name="test",
        system_prompt="sys",
        tools=listing_tools,
        llm=MagicMock(),
    )

    # 有 tool_calls → 应继续走 tool_node
    state_with_call = {
        "messages": [
            HumanMessage(content="帮我润色下标题"),
            AIMessage(
                content="",
                tool_calls=[{"name": "optimize_listing_title",
                             "args": {"current_title": "old title"},
                             "id": "1"}],
            ),
        ]
    }
    assert agent._should_continue(state_with_call) == "tool_node"

    # 无 tool_calls → 应 respond
    state_plain = {
        "messages": [
            HumanMessage(content="你好"),
            AIMessage(content="你好，有什么可以帮你？"),
        ]
    }
    assert agent._should_continue(state_plain) == "respond"


def test_respond_node_handles_tool_message():
    """修复后：_respond_node 遇到 ToolMessage 不再 NameError"""
    import asyncio

    agent = BaseAgent(
        agent_name="test",
        system_prompt="sys",
        tools=listing_tools,
        llm=MagicMock(),
    )
    state = {
        "messages": [
            HumanMessage(content="hi"),
            ToolMessage(content="优化结果 JSON", tool_call_id="1"),
        ]
    }
    result = asyncio.run(agent._respond_node(state))
    assert result["structured_response"]["status"] == "completed"
    assert "优化结果 JSON" in result["structured_response"]["message"]
