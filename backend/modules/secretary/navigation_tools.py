"""
店秘书「导航工具」注册表

把「切 Agent」「打开资料库视图」这类前端导航动作，包装成 langchain 工具，
让主 Agent 用 tool_calls 统一表达「导航」和「业务执行」两类意图。

设计要点：
- 参数用枚举（Literal）约束，LLM 只能从合法候选里选，天然防幻觉。
- 工具本身不真正执行导航（后端无法操作前端视图），只返回一个结构化标记，
  由 orchestrator 端点透传给前端，前端再调 dispatchAppAction 落地。
- agentId / view 的合法值，与前端 appActions.ts 的 AppView + agent.ts 的
  AGENT_LIST 严格对齐。
"""

import json
from typing import Literal

from langchain_core.tools import StructuredTool
from ai_infra.tools.clarification import make_clarification_tool
from ai_infra.tools.side_effects import READ_ONLY_METADATA


# 与前端 stores/agent.ts 的 AGENT_LIST 对齐（不含 secretary 自身）
AGENT_IDS = [
    "product-research",
    "competitor-intel",
    "aigc-media",
    "listing-generator",
    "ad-analysis",
    "customer-service",
    "review-analyst",
]

# 与前端 utils/appActions.ts 的 AppView 对齐
VIEW_IDS = ["faq", "candidates", "products", "assets", "rules", "monitor"]

# 账户菜单网关的 target（与前端 appActions.ts 的 account_menu 对齐）
ACCOUNT_MENU_TARGETS = ["settings", "memory", "subscription", "logout"]

AgentId = Literal[
    "product-research",
    "competitor-intel",
    "aigc-media",
    "listing-generator",
    "ad-analysis",
    "customer-service",
    "review-analyst",
]
ViewId = Literal["faq", "candidates", "products", "assets", "rules", "monitor"]
AccountMenuTarget = Literal["settings", "memory", "subscription", "logout"]
# ⚠️ 必须与前端 frontend/src/theme/presets.ts 的 `ThemeName` 保持一致（外加 system）。
# 本枚举是**工具签名**的一部分 → LLM 只能从这里取值，所以加主题时漏改这里，
# 表现是「老板说『换成马卡龙』，主 Agent 找不到该枚举值 → 答『没这个主题』或切错」。
# 漂移由前端自检脚本兜底：frontend/scripts/check-theme-boot.py
ThemeMode = Literal["light", "dark", "macaron", "system"]


def _switch_agent(agent_id: AgentId, query: str = "") -> str:
    """切换到指定的业务 Agent，并可把老板的具体诉求一并转达给它。

    Args:
        agent_id: 目标 Agent 标识（枚举值）。
        query: 老板诉求的**原话**（可选）。两种用法：
            ① 纯导航 —— 老板只说「去选品页 / 打开选品分析师」，query 留空，
               切过去后由老板自己输入；
            ② 路由带参（更常见）—— 老板带着明确任务来（如「比较好卖的品类
               有哪些」「帮我找厨房用品的蓝海机会」「优化下这个标题」），
               把老板原话填进 query，子 Agent 切换过去后会**自动接着执行**。
    """
    payload: dict = {"action": "switch_agent", "agentId": agent_id}
    if query and query.strip():
        payload["query"] = query.strip()
    return json.dumps(payload, ensure_ascii=False)


def _open_view(view: ViewId) -> str:
    """打开指定的资料库 / 看板视图。

    Args:
        view: 目标视图标识（枚举值）。
    """
    return f'{{"action": "navigate", "view": "{view}"}}'


def _open_account_menu(target: AccountMenuTarget) -> str:
    """打开账户菜单里的某一项（设置 / 记忆与进化 / 订阅与计费 / 退出登录）。

    这是「账户 / 系统」类操作的统一网关：把侧栏账户下拉菜单里的跳转项
    收敛成单一工具，用 target 区分具体要打开哪一项。MCP 式单接口思路。

    Args:
        target: 目标菜单项（settings=设置；memory=记忆与进化；
            subscription=订阅与计费；logout=退出登录）。
    """
    return f'{{"action": "account_menu", "target": "{target}"}}'


def _set_theme(mode: ThemeMode) -> str:
    """切换界面外观主题（浅色 / 深色 / 马卡龙 / 跟随系统）。

    Args:
        mode: 目标主题（light 浅色 / dark 深色 / macaron 马卡龙（粉彩甜点风，浅色族）
            / system 跟随系统）。老板用中文口语说「马卡龙」「粉一点」「甜一点」时用 macaron。
    """
    return f'{{"action": "set_theme", "mode": "{mode}"}}'


def _handoff_to_agent(agent_id: AgentId, intent: str, missing_fields: list[str]) -> str:
    """把当前对话「交接」给某个专业 Agent 接管。

    适用场景：老板提出一个专业生成类需求，但主 Agent 判断当前信息不足，
    不足以直接产出结果（例如「帮我生成一张水壶的白底图」—— 缺少材质、
    造型、视角、是否需要 logo、产品细节等关键字段）。

    此时**不要**自己调用业务工具用默认值硬凑结果，而是调用本工具：
    - 把已识别的意图（intent）交给专业 Agent
    - 列出需要向老板追问的缺失字段（missing_fields）
    - 专业 Agent 会接管对话，逐项追问补齐后再执行

    Args:
        agent_id: 接管对话的目标 Agent 标识（枚举值）。
        intent: 已识别的意图，一句话描述老板想做什么（原样转述老板诉求）。
        missing_fields: 需要向老板追问的缺失字段清单（如 ["材质", "造型", "视角", "是否需要 logo"]）。
    """
    payload = {
        "action": "handoff",
        "agentId": agent_id,
        "intent": intent,
        "missing_fields": missing_fields,
    }
    return json.dumps(payload, ensure_ascii=False)


navigation_tools = [
    StructuredTool.from_function(
        func=_switch_agent,
        name="switch_agent",
        description=(
            "切换到某个业务 Agent 的对话页。当老板想找某个专职 Agent 干活时使用。"
            "**重要**：若老板带着明确诉求（想让它「分析 / 找 / 优化 / 做 / 看看」某件事），"
            "必须把老板原话填进 query，子 Agent 会自动接着执行；"
            "只有单纯的「去 XX 页面 / 打开 XX 分析师」才留空。"
            "各 Agent 与触发词对应如下："
            "「找蓝海/选品/利润测算/哪些品类好卖」→ product-research（选品分析师）；"
            "「竞品/对手/竞争分析」→ competitor-intel（竞品监控员）；"
            "「做图/视频/素材」→ aigc-media（AIGC 媒体生成器）；"
            "「改文案/标题/五点/描述/关键词」→ listing-generator（Listing 优化师）；"
            "「广告/ACOS/出价/投放」→ ad-analysis（广告分析师）；"
            "「客服/工单/售后」→ customer-service（智能客服）；"
            "「复盘/周报/月报/经营大盘/业绩/报表/总结」→ review-analyst（运营复盘师）。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        func=_open_view,
        name="open_view",
        description=(
            "打开资料库 / 看板视图。当老板想查看或管理某类数据时使用，例如"
            "「打开产品库」→ products，「打开选品库」→ candidates，"
            "「打开竞品监控」→ monitor（仅竞品价格/上新监控，不含经营复盘），"
            "「打开平台规则」→ rules。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        func=_open_account_menu,
        name="open_account_menu",
        description=(
            "打开账户菜单里的某一项（账户/系统类跳转的统一网关）。老板想打开账户相关功能时使用："
            "「打开设置/个人设置/偏好/系统设置」→ settings；"
            "「打开记忆与进化/查看记忆」→ memory；"
            "「查看订阅/订阅与计费/我的套餐/账单/续费」→ subscription；"
            "「退出登录/登出/注销」→ logout。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        func=_set_theme,
        name="set_theme",
        description=(
            "切换界面外观主题。老板想改界面颜色/明暗时使用，直接切换，无需引导去设置。"
            "「切换浅色/浅色模式/明亮/白色」→ light；"
            "「切换深色/深色模式/暗色/黑色/夜间」→ dark；"
            "「跟随系统」→ system。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    # ★ 第 145 轮 批 B3：先「问」再「交接」—— `ask_clarification` 排在这里不是
    #   装饰：它和 `handoff_to_agent` 的优先关系是「能在**当前会话**里问清楚，
    #   就不要把对话交接走」（交接会切走前端 Agent，是更重的动作、也会丢当前上下文）。
    #   工具排列顺序对 LLM 有弱提示作用，但真正的约束写在
    #   `agent.py::SECRETARY_SYSTEM_PROMPT` 第 6 条 —— 两处一起改才生效。
    make_clarification_tool(),
    StructuredTool.from_function(
        func=_handoff_to_agent,
        name="handoff_to_agent",
        description=(
            "把对话交接给某个专业 Agent 接管，让它在自己的领域内逐项追问补齐缺失信息后执行。"
            "当老板提出专业生成类需求（如「生成一张 XX 的白底图」「写一个 XX 的视频脚本」「做 A+ 内容」）"
            "但主 Agent 判断关键信息不足（如生图缺材质/造型/视角/是否需要 logo/产品细节）时，"
            "**必须**调用本工具交接，而不是自己用默认值硬凑结果。"
            "各 Agent 与触发词对应同 switch_agent："
            "「做图/生成产品图/主图/白底图/素材」→ aigc-media；"
            "「视频脚本」→ aigc-media；"
            "「A+/EBC/详情页内容」→ aigc-media；"
            "「改文案/标题/五点/描述」→ listing-generator。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
]
