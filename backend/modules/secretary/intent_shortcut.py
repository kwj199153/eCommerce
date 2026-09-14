"""
店秘书「决策层 B」—— 意图预判短路层

定位：`route()` 的第一道闸门。把**高置信度的纯导航 / 纯系统操作**指令直接翻译成
动作，跳过整次 LLM 调用（省 1 次 LLM ≈ 2~4 秒 + 一次 token 消耗）。

设计原则（与项目既有的 listing 路由层一致）：
    **关键词表做加速器，LLM 做兜底** —— 不是二选一。
    短路只在「几乎不可能有第二种解读」时触发；有任何复合意图的迹象就放行给 LLM。

为什么必须保守（宁可放过，不可错杀）：
    短路一旦误判，老板会看到「明明说了 A，结果跳去了 B」，
    且没有任何补救路径 —— 因为 LLM 根本没被调用。
    因此这里的判据是**否定优先**：先排除「复合/带任务诉求」的句子，再匹配纯动作。

复合意图的识别（`_looks_compound`）：
    - 出现「然后 / 再 / 顺便 / 之后 / 接着」等连接词
    - 出现业务动词（优化 / 生成 / 分析 / 找 / 算 / 看看…）→ 说明老板想「干活」，
      即便句子里含「打开 XX」也应交给 LLM 决定（可能要 switch_agent + query）
    - 句子过长（> MAX_SHORTCUT_CHARS）→ 信息量大，不适合走表

命中结果直接复用 `navigation_tools` 里同名工具函数的返回值（JSON 字符串），
保证短路与 LLM 两条路径产出**完全同构**的动作对象。
"""

import json
from typing import Optional

# --------------------------------------------------------------------------- #
# 阈值与词表
# --------------------------------------------------------------------------- #

#: 超过这个长度就认为句子信息量大，不适合走条件反射式短路
MAX_SHORTCUT_CHARS = 16

#: 「复合意图」连接词 —— 出现即视为多步诉求，交给 LLM
_COMPOUND_MARKERS = (
    "然后",
    "接着",
    "再",
    "顺便",
    "之后",
    "同时",
    "并且",
    "还有",
    "以及",
    "先",
    "帮我",
    "请",
)

#: 业务动词 —— 出现说明老板要「干活」而非「纯导航」，交给 LLM
#: （这类诉求往往需要 switch_agent + query 透传，甚至 handoff 追问）
#:
#: ★ 必须按**词边界**匹配，不能裸子串 —— 否则「分析」会命中「分析**师**」、
#:   「找」会命中「选品**找**不到」这类无关位置，把纯导航句误判成业务诉求。
#:   （项目铁律：词→目标匹配必须词边界，禁子串。）
_BUSINESS_VERBS = (
    "优化",
    "生成",
    "写",
    "做",
    "分析",
    "找",
    "算",
    "挖掘",
    "诊断",
    "复盘",
    "对比",
    "比较",
    "推荐",
    "看看",
    "看一下",
    "查一下",
    "怎么样",
    "哪些",
    "什么",
    "如何",
    "为什么",
)

#: Agent 名后缀 —— 出现「分析师 / 监控员 / 优化师」等**职位名**时，
#: 说明老板是在「找某个 Agent」，不是在发业务指令。
#: 判定业务动词前先剥离这些后缀，避免「分析」误命中「分析师」。
_AGENT_ROLE_SUFFIXES = ("分析师", "监控员", "优化师", "生成器", "客服", "助手", "师", "员")

#: 主题切换动词 —— 本身就是完整指令，不要求句首导航前缀
_THEME_VERBS = ("切换", "换", "改成", "改为", "调成", "调为", "模式", "主题", "跟随")

#: 账户菜单的**自足动词** —— 「退出登录」「查看订阅」这类两句就完整，
#: 不必以「打开 / 去」开头。
_ACCOUNT_SELF_CONTAINED = ("退出", "登出", "注销", "查看", "我的", "我要")

#: 「纯导航」句式标记 —— 命中才考虑短路切 Agent
_NAV_PREFIXES = ("去", "打开", "切到", "切换到", "进入", "回到", "看看")

#: 主题名 → ThemeMode
_THEME_WORDS: tuple[tuple[str, str], ...] = (
    ("马卡龙", "macaron"),
    ("粉", "macaron"),
    ("甜", "macaron"),
    ("浅色", "light"),
    ("明亮", "light"),
    ("白色", "light"),
    ("亮色", "light"),
    ("深色", "dark"),
    ("暗色", "dark"),
    ("黑色", "dark"),
    ("夜间", "dark"),
    ("暗黑", "dark"),
    ("跟随系统", "system"),
    ("跟随电脑", "system"),
    ("系统主题", "system"),
)

#: 视图名 → ViewId（顺序敏感：长词在前，避免「选品库」被「选品」抢先）
_VIEW_WORDS: tuple[tuple[str, str], ...] = (
    ("产品库", "products"),
    ("商品库", "products"),
    ("选品库", "candidates"),
    ("候选库", "candidates"),
    ("竞品监控池", "monitor"),
    ("监控池", "monitor"),
    ("竞品监控", "monitor"),
    ("平台规则", "rules"),
    ("规则库", "rules"),
    ("素材库", "assets"),
    ("话术库", "faq"),
    ("知识库", "faq"),
    ("FAQ", "faq"),
)

#: 账户菜单 target 词
_ACCOUNT_WORDS: tuple[tuple[str, str], ...] = (
    ("退出登录", "logout"),
    ("登出", "logout"),
    ("注销", "logout"),
    ("订阅", "subscription"),
    ("套餐", "subscription"),
    ("账单", "subscription"),
    ("续费", "subscription"),
    ("计费", "subscription"),
    ("记忆", "memory"),
    ("设置", "settings"),
    ("偏好", "settings"),
)

#: Agent 触发词 → agentId（顺序敏感：先匹配长词/更专有的词）
_AGENT_WORDS: tuple[tuple[str, str], ...] = (
    ("广告分析师", "ad-analysis"),
    ("广告分析", "ad-analysis"),
    ("复盘师", "review-analyst"),
    ("运营复盘", "review-analyst"),
    ("选品分析师", "product-research"),
    ("选品分析", "product-research"),
    ("竞品监控员", "competitor-intel"),
    ("竞品分析", "competitor-intel"),
    ("媒体生成器", "aigc-media"),
    ("AIGC", "aigc-media"),
    ("aigc", "aigc-media"),
    ("listing优化师", "listing-generator"),
    ("Listing优化师", "listing-generator"),
    ("文案优化师", "listing-generator"),
    ("智能客服", "customer-service"),
    ("客服助手", "customer-service"),
)


# --------------------------------------------------------------------------- #
# 判定
# --------------------------------------------------------------------------- #


def _looks_compound(text: str) -> bool:
    """判断是否含「复合意图」迹象（含则必须交给 LLM）。

    两类迹象：
    ① 连接词（「然后」「顺便」…）→ 多步诉求。
    ② 业务动词（「优化」「生成」…）→ 老板要干活，可能需 switch_agent + query。

    ★ 第 ② 类必须**先剥离 Agent 职位名后缀**再判，否则「分析」会命中
      「分析**师**」→「去选品分析师」这种纯导航句被误判成业务诉求。
    """
    if len(text) > MAX_SHORTCUT_CHARS:
        return True
    if any(m in text for m in _COMPOUND_MARKERS):
        return True

    # 剥离 Agent 职位名后缀，避免「分析师」「监控员」里的动词字被误命中。
    # 例：「去选品分析师」→ 剥离「分析师」→「去选品」→ 不含业务动词 → 可短路。
    stripped = text
    for suffix in _AGENT_ROLE_SUFFIXES:
        stripped = stripped.replace(suffix, "")

    if any(v in stripped for v in _BUSINESS_VERBS):
        return True
    return False


def _find(text: str, table: tuple[tuple[str, str], ...]) -> Optional[str]:
    """在词表里找第一个命中的关键词，返回其映射值。"""
    for word, value in table:
        if word in text:
            return value
    return None


def _has_nav_prefix(text: str) -> bool:
    """句首是否为导航式动词（「去」「打开」「切到」…）。

    用于区分「打开设置」（导航）与「设置里有什么功能」（疑问）。
    """
    return any(text.startswith(p) or p in text[:4] for p in _NAV_PREFIXES)


def match(text: str) -> Optional[dict]:
    """意图预判：命中则返回动作 dict，未命中/不确定返回 None。

    Returns:
        形如 ``{"action": "set_theme", "mode": "dark"}`` 的动作对象；
        或 None（表示「交给 LLM 兜底」）。

    优先级说明（从高到低，因为越具体的越不容易误判）：
        主题 > 账户菜单 > **Agent** > 视图

    ★ Agent 排在视图之前：因为「竞品监控员」含「竞品监控」这个视图词，
      但老板说的是**人**（Agent）不是**页**（视图）—— 职位名后缀更具体，应优先。
    """
    text = (text or "").strip()
    if not text:
        return None

    # 疑问句一律不短路（「怎么切换主题」「深色模式在哪」都是在问，不是在命令）
    if text.endswith(("？", "?")) or "怎么" in text or "在哪" in text:
        return None

    if _looks_compound(text):
        return None

    # ① 主题（最具体：有动词 + 有明确目标值；动词自身即完整指令，不要求导航前缀）
    mode = _find(text, _THEME_WORDS)
    if mode and any(k in text for k in _THEME_VERBS):
        return {"action": "set_theme", "mode": mode}

    # ② 账户菜单（账户/系统类跳转的统一网关）
    #    前提放宽：以导航动词开头，**或**本身就是自足动词短语（「退出登录」「查看订阅」）
    if _has_nav_prefix(text) or any(k in text for k in _ACCOUNT_SELF_CONTAINED):
        target = _find(text, _ACCOUNT_WORDS)
        if target:
            return {"action": "account_menu", "target": target}

    # ③ 切 Agent（只在「纯导航」句式下短路：不带 query，否则必须走 LLM）
    if _has_nav_prefix(text):
        agent_id = _find(text, _AGENT_WORDS)
        if agent_id:
            return {"action": "switch_agent", "agentId": agent_id}

    # ④ 资料库视图
    if _has_nav_prefix(text) or "看板" in text or "列表" in text:
        view = _find(text, _VIEW_WORDS)
        if view:
            return {"action": "navigate", "view": view}

    return None


def build_reply(payload: dict) -> str:
    """为短路结果生成一句自然回复（与 LLM 路径的 reply 语义对齐）。"""
    if not isinstance(payload, dict):
        return "好的。"
    action = payload.get("action")
    if action == "set_theme":
        return {
            "light": "好的，已切换到浅色模式。",
            "dark": "好的，已切换到深色模式。",
            "macaron": "好的，已切换到马卡龙主题。",
            "system": "好的，已切换为跟随系统。",
        }.get(payload.get("mode", ""), "好的，主题已切换。")
    if action == "switch_agent":
        return "好的，已为你切换。"
    if action == "navigate":
        return "好的，已为你打开。"
    if action == "account_menu":
        return "好的，已为你打开。"
    return "好的。"


def to_tool_calls(payload: dict) -> list[str]:
    """把动作反推成「工具名」，让短路路径的 tool_calls 字段与 LLM 路径同构。"""
    if not isinstance(payload, dict):
        return []
    return {
        "set_theme": ["set_theme"],
        "switch_agent": ["switch_agent"],
        "navigate": ["open_view"],
        "account_menu": ["open_account_menu"],
    }.get(payload.get("action", ""), [])


def as_json(payload: dict) -> str:
    """序列化（与 navigation_tools 里工具函数的返回格式一致），便于测试比对。"""
    return json.dumps(payload, ensure_ascii=False)
