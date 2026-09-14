"""
店秘书「决策层 B」—— 意图预判短路层测试

三层验证：

1. **命中面**：高置信度的纯导航 / 纯系统操作必须走短路（含明确动作与目标值）。
2. **保守性（最重要）**：任何疑似复合意图 / 疑问句 / 带任务诉求的句子
   **必须放行给 LLM** —— 短路误判没有补救路径（LLM 根本没被调用），
   所以这里用「宁可放过」的断言把边界钉死。
3. **同构性**：短路产出的动作对象，与 LLM 路径产出的动作对象**结构一致**
   （同一套 action 枚举 + 同名字段），前端 dispatch 无需分支。

不依赖真实 LLM、不依赖数据库。
"""

import pytest

from modules.secretary import intent_shortcut


# --------------------------------------------------------------------------- #
# 1. 命中面：纯导航 / 纯系统操作
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query,expected",
    [
        # 主题：动词 + 明确目标值
        ("切换深色", {"action": "set_theme", "mode": "dark"}),
        ("换成浅色", {"action": "set_theme", "mode": "light"}),
        ("改成马卡龙", {"action": "set_theme", "mode": "macaron"}),
        ("切换深色模式", {"action": "set_theme", "mode": "dark"}),
        ("跟随系统", {"action": "set_theme", "mode": "system"}),
        # 账户菜单网关
        ("打开设置", {"action": "account_menu", "target": "settings"}),
        ("打开订阅", {"action": "account_menu", "target": "subscription"}),
        ("退出登录", {"action": "account_menu", "target": "logout"}),
        # 资料库视图
        ("打开产品库", {"action": "navigate", "view": "products"}),
        ("打开选品库", {"action": "navigate", "view": "candidates"}),
        ("打开平台规则", {"action": "navigate", "view": "rules"}),
        # 纯导航切 Agent（无 query）
        ("去选品分析师", {"action": "switch_agent", "agentId": "product-research"}),
        ("打开竞品监控员", {"action": "switch_agent", "agentId": "competitor-intel"}),
        ("切到广告分析师", {"action": "switch_agent", "agentId": "ad-analysis"}),
    ],
)
def test_shortcut_hits(query, expected):
    """这些句子必须短路命中，且动作与目标值精确。"""
    got = intent_shortcut.match(query)
    assert got == expected, f"{query!r} → {got!r}，期望 {expected!r}"


def test_shortcut_switch_agent_carries_no_query():
    """★ 短路切 Agent **绝不带 query**。

    带诉求的句子必须交给 LLM（它才知道要不要把老板原话塞进 query 透传给子 Agent）。
    短路一律产出纯导航动作 —— 这是本层不越权的核心约定。
    """
    got = intent_shortcut.match("去选品分析师")
    assert got == {"action": "switch_agent", "agentId": "product-research"}
    assert "query" not in got


# --------------------------------------------------------------------------- #
# 2. 保守性：必须放行给 LLM
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query",
    [
        # ▶ 带业务诉求（要「干活」）—— LLM 需判是否 switch_agent + query
        "帮我找厨房用品的蓝海机会",
        "优化下我的标题",
        "生成一张水壶的白底图",
        "分析下这个广告",
        "哪些品类好卖",
        "比较一下这两个竞品",
        # ▶ 复合意图（连接词）
        "切换深色，然后打开设置",
        "打开产品库再切到选品分析师",
        "先去选品分析师",
        "切换深色顺便打开设置",
        # ▶ 疑问句（在问，不是在下令）
        "怎么切换主题？",
        "深色模式在哪里",
        "打开设置有什么用？",
        # ▶ 空 / 空白
        "",
        "   ",
    ],
)
def test_shortcut_must_defer_to_llm(query):
    """★ 这些都是「不确定」的句子 → 必须返回 None（放行 LLM）。

    宁可走 LLM 多花 2~4 秒，也不能短路误判跳错地方。
    """
    assert intent_shortcut.match(query) is None, f"{query!r} 不该被短路"


def test_compound_marker_blocks_shortcut():
    """连接词「然后」单独就能阻断短路（多步诉求 LLM 才处理得了）。"""
    assert intent_shortcut.match("切换深色") is not None
    assert intent_shortcut.match("切换深色然后打开设置") is None


def test_business_verb_blocks_shortcut():
    """业务动词阻断：即使句首是「打开」，含业务动作也要交给 LLM。"""
    assert intent_shortcut.match("打开产品库") is not None
    # 「打开产品库并优化标题」既有导航又有业务动词
    assert intent_shortcut.match("打开产品库并优化标题") is None


def test_overlong_text_blocks_shortcut():
    """超长句子信息量大，不适合表匹配。"""
    long_query = "切换深色" + "很" * intent_shortcut.MAX_SHORTCUT_CHARS
    assert intent_shortcut.match(long_query) is None


def test_theme_requires_explicit_verb():
    """★ 只出现主题词、没有切换动词 → 不短路。

    「深色」两个字单独出现可能是任何意思（如「深色的图」），
    必须有「切换 / 换 / 改成」类动词才敢认定是切换指令。
    """
    assert intent_shortcut.match("深色") is None
    assert intent_shortcut.match("马卡龙") is None
    assert intent_shortcut.match("切换深色") is not None


# --------------------------------------------------------------------------- #
# 3. 同构性：与 LLM 路径产出结构一致
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query",
    [
        "切换深色",
        "打开设置",
        "打开产品库",
        "去选品分析师",
    ],
)
def test_shortcut_action_shape_matches_llm_path(query):
    """短路动作必须与 navigation_tools 里工具函数的产出**字段名完全一致**。

    否则前端 dispatchAppAction 需要按来源分支 —— 那就失去「两条路一条链路」的意义。
    """
    action = intent_shortcut.match(query)
    assert action is not None
    assert isinstance(action, dict)
    assert isinstance(action.get("action"), str)

    # action 值必须在 agent.py 的动作白名单内
    allowed = {
        "switch_agent",
        "navigate",
        "select_product",
        "account_menu",
        "handoff",
        "set_theme",
        "switch_shop",
    }
    assert action["action"] in allowed

    # 与 navigation_tools 的同类动作字段名对齐
    shape = {
        "set_theme": {"mode"},
        "navigate": {"view"},
        "account_menu": {"target"},
        "switch_agent": {"agentId"},
    }[action["action"]]
    assert shape.issubset(set(action.keys())), f"{action} 缺字段 {shape - set(action)}"


def test_shortcut_values_are_valid_enums():
    """短路产出的目标值必须是**合法枚举**（与后端工具签名同一套值）。

    硬编码字符串写错（如 mode="darkk"）不会报错，只会静默切错 → 必须断言。
    """
    from modules.secretary.navigation_tools import (
        ACCOUNT_MENU_TARGETS,
        AGENT_IDS,
        VIEW_IDS,
    )

    theme_modes = {"light", "dark", "macaron", "system"}
    for query, check in [
        ("切换深色", ("set_theme", theme_modes, "mode")),
        ("打开设置", ("account_menu", set(ACCOUNT_MENU_TARGETS), "target")),
        ("打开产品库", ("navigate", set(VIEW_IDS), "view")),
        ("去选品分析师", ("switch_agent", set(AGENT_IDS), "agentId")),
    ]:
        action = intent_shortcut.match(query)
        expected_action, valid_values, field = check
        assert action is not None and action["action"] == expected_action
        assert action[field] in valid_values, f"{query!r} 产出非法 {field}={action[field]!r}"


def test_build_reply_and_tool_calls_nonempty():
    """短路结果的 reply 与 tool_calls 必须非空（前端展示 + 埋点都依赖）。"""
    for query in ["切换深色", "打开设置", "打开产品库", "去选品分析师"]:
        action = intent_shortcut.match(query)
        reply = intent_shortcut.build_reply(action)
        calls = intent_shortcut.to_tool_calls(action)
        assert reply.strip(), f"{query!r} 的 reply 为空"
        assert calls, f"{query!r} 的 tool_calls 为空"


# --------------------------------------------------------------------------- #
# 4. route() 集成：短路真的跳过了 LLM
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_route_shortcut_skips_llm(monkeypatch):
    """★ 集成验证：短路命中时，`get_secretary_agent` **根本不被调用**。

    这是本层存在的全部意义 —— 省掉整次 LLM。若哪天有人在短路块之前
    又加了「先构建 agent」之类的前置动作，这个断言会立刻红。
    """
    from modules.secretary import agent as agent_mod

    called = {"built": False}

    def _boom(*args, **kwargs):
        called["built"] = True
        raise AssertionError("短路命中时不该构建 Agent（不该调 LLM）")

    monkeypatch.setattr(agent_mod, "get_secretary_agent", _boom)

    result = await agent_mod.route("切换深色", shop_id="store_1")

    assert called["built"] is False
    assert result["route_mode"] == "shortcut"
    assert result["action"] == {"action": "set_theme", "mode": "dark"}
    assert result["actions"] == [result["action"]]
    assert result["tool_calls"] == ["set_theme"]


@pytest.mark.asyncio
async def test_route_shortcut_result_shape(monkeypatch):
    """短路返回体必须和 LLM 路径**同一个 schema**（多出 route_mode/shortcut_rule）。"""
    from modules.secretary import agent as agent_mod

    monkeypatch.setattr(agent_mod, "get_secretary_agent", lambda *a, **k: None)

    result = await agent_mod.route("打开产品库", shop_id="store_1")

    for key in ("reply", "actions", "action", "tool_calls", "route_mode", "shortcut_rule"):
        assert key in result, f"缺字段 {key}"
    assert result["route_mode"] == "shortcut"
    assert result["shortcut_rule"] == "navigate"
    assert result["action"] == {"action": "navigate", "view": "products"}
