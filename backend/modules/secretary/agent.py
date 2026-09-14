"""
店秘书（主 Agent / 编排层）

定位：全局入口，把用户一句话翻译成「回复 + 动作」。
- 动作分两类：①路由（切到专职 Agent / 打开资料库 / 交接）②系统操作（切主题/店铺/产品、开账户菜单、查订阅）。
- 它**不产出业务结果本身**，只做路由与调度，业务专业实现全部下沉到各专职 Agent。

实现：
- 继承 `ai_infra.BaseAgent`，注入「导航/系统工具（约 9 个）」。
- 通过「bind_tools + LLM 调用」让 LLM 决定调哪个工具、填什么参。
- 业务 Agent 的工具**不注入主 Agent**（分层路由：主 Agent 管路由，子 Agent 管实现）。
"""

import json
import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger

from ai_infra.base_agent import BaseAgent
from modules.secretary import intent_shortcut
from modules.secretary.navigation_tools import navigation_tools
from modules.secretary.subscription_tools import subscription_tools
from modules.secretary.product_tools import build_product_tools
from modules.secretary.shop_tools import build_shop_tools

SECRETARY_SYSTEM_PROMPT = """你是「店管家 AI」的店秘书，一个跨境电商运营助手。

你的职责：**只做「路由调度 + 系统操作」，不做业务实现**。

你是全局入口，负责把老板的一句话翻译成「切到哪个专职 Agent」或「打开哪个界面 / 改哪个系统状态」。业务的专业实现（生成 listing、做图、算利润、广告分析、竞品监控、经营复盘、客服问答）**一律交给对应的专职 Agent**，你只负责把老板「送」到那里，不要自己动手生成业务结果。

可用的工具分三类：

【路由工具】
- switch_agent：把老板切换到某个专职 Agent 的对话页（老板要「做专业的事」时用它）。**带 query 参数**：若老板带着明确诉求来，把老板原话填进 query，子 Agent 切换过去后会**自动接着执行**；只有纯「去 XX 页面」才留空。
- handoff_to_agent：老板提出专业生成类需求（生图/视频脚本/A+内容等）但关键信息不足时，把对话交接给专职 Agent，让它逐项追问补齐后执行
- select_product：选中产品库里的某个产品作为「工作商品」（切 Agent 前的前置动作）

【系统/店铺/UI 工具】
- open_view：打开资料库 / 看板（产品库、选品库、竞品监控等）
- open_account_menu：打开账户菜单项（设置 / 记忆与进化 / 订阅与计费 / 退出登录）——账户类跳转的统一网关
- set_theme：切换界面主题（浅色 / 深色 / 跟随系统）
- switch_shop：切换当前工作的店铺（数据源）
- get_my_subscription：查询当前账号的订阅套餐详情（套餐名/状态/价格/周期/特性）

规则：
1. 老板要「做专业的事」（改 listing、做图、写视频脚本、找蓝海、算利润、广告分析、竞品监控、经营复盘、客服问答）→ 调 switch_agent 切到对应专职 Agent。你**不负责**生成这些业务结果。
   **关键**：老板几乎总是带着具体诉求来的（如「比较好卖的品类有哪些」「帮我找厨房用品的蓝海机会」「优化下我的标题」），此时**必须把老板原话填进 query 参数**，子 Agent 会自动接着干活，不要切完就停、让老板再打一遍。只有老板单纯说「去选品页 / 打开选品分析师」这类纯导航时才留空 query。
2. 老板要「看某个库 / 看板」→ 调 open_view。
3. 老板要「打开账户相关功能」（设置、记忆、订阅、退出登录）→ 调 open_account_menu 并选对应 target。
4. 老板要「改界面主题」→ 调 set_theme；「换店铺」→ 调 switch_shop；「选产品」→ 调 select_product。
5. 老板问「订阅/套餐/账单/续费」→ 调 get_my_subscription 查询后直接回答；若返回 found=false，直接说「当前未订阅」并建议去订阅页面。
6. 【重要】老板提出专业生成类需求但关键信息不足（如生图缺材质/造型/视角/是否需要 logo/产品细节，≥2 个核心参数缺失）时，调 handoff_to_agent 交接给专职 Agent 追问，不要自己硬凑。
7. 与工具无关的闲聊，礼貌回应即可，不要强行调用工具。
8. 一次只做最贴合意图的一件事，不要多调无关工具。

各专职 Agent 与触发场景对应：
- 「找蓝海/选品/利润测算」→ product-research（选品分析师）
- 「竞品/对手/竞争分析」→ competitor-intel（竞品监控员）
- 「做图/视频/素材/A+内容」→ aigc-media（AIGC 媒体生成器）
- 「改文案/标题/五点/描述/关键词」→ listing-generator（Listing 优化师）
- 「广告/ACOS/出价/投放」→ ad-analysis（广告分析师）
- 「客服/工单/售后/买家」→ customer-service（智能客服）
- 「复盘/周报/月报/经营大盘/业绩/报表」→ review-analyst（运营复盘师）
"""


class SecretaryAgent(BaseAgent):
    """店秘书主 Agent"""

    def __init__(self, llm=None, shop_id: Optional[str] = None, checkpointer=None, **kwargs):
        # 产品选择工具按店铺动态构建（shop_id 为空时返回空标记，由前端提示）
        product_tools = build_product_tools(shop_id)
        shop_tools = build_shop_tools()
        super().__init__(
            agent_name="secretary",
            system_prompt=SECRETARY_SYSTEM_PROMPT,
            tools=navigation_tools + subscription_tools + product_tools + shop_tools,
            llm=llm,
            max_iterations=6,
            metadata={"role": "orchestrator"},
            checkpointer=checkpointer,
            **kwargs,
        )


# 单例（不含店铺绑定；店铺相关工具按请求动态重建）
_agent: Optional[SecretaryAgent] = None


def get_secretary_agent(shop_id: Optional[str] = None) -> SecretaryAgent:
    """获取店秘书实例。

    因为 select_product 工具需要按店铺绑定 shop_id，而单例无法感知每个请求的
    店铺上下文，所以：
    - shop_id 为空：返回共享单例（工具集不含产品选择，或含空 shop 的产品工具）
    - shop_id 非空：每次新建实例（开销可接受，agent 初始化很轻）

    决策层 C：优先尝试绑定全局 checkpointer（跨轮持久化）；若未初始化（如
    测试环境 / DB 未连），退化为无 checkpointer 的内存态，不抛错。
    """
    global _agent
    from core.checkpoint import get_checkpointer
    cp = get_checkpointer()
    if shop_id is None:
        if _agent is None:
            _agent = SecretaryAgent(checkpointer=cp)
        return _agent
    return SecretaryAgent(shop_id=shop_id, checkpointer=cp)


async def route(query: str, shop_id: Optional[str] = None, history: Optional[list[dict]] = None, session_id: Optional[str] = None) -> dict:
    """一次路由调用，返回结构化结果。

    直接执行图并捕获消息流，从中提取：
    - reply：最终 LLM 回复文本
    - actions：有序的动作列表（switch_agent / navigate / select_product），
      前端按顺序依次 dispatch（例如「先选产品，再切 Agent」）
    - action：向后兼容，取 actions 里最后一个（单动作场景等价）
    - tool_calls：本次实际调用的工具名列表

    Args:
        query: 用户当前这一句话。
        shop_id: 当前店铺 ID（供 select_product 等按店铺过滤）。
        history: 本会话的历史消息（[{role, content}]，role ∈ user/assistant），
            用于让 LLM 感知多轮上下文（如「再切换」能理解上一轮在说主题）。
            历史里**不应**包含当前 query（前端取的是「当前消息之前」的最近 N 条）。
        session_id: 会话 ID。非空时作为 checkpointer 的 thread_id，实现跨轮
            持久化（决策层 C）；同时优先于前端显式传的 history。

    Returns:
        {"reply": str, "actions": [dict], "action": dict|None, "tool_calls": [str],
         "route_mode": "shortcut"|"llm", "shortcut_rule": str}
    """
    started = time.perf_counter()

    # ===== 决策层 B：意图预判短路 =====
    # 高置信度的「纯导航 / 纯系统操作」直接产出动作，**跳过整次 LLM 调用**。
    # 判据在 intent_shortcut 里是「否定优先」：只要疑似复合意图就放行给 LLM。
    shortcut = intent_shortcut.match(query)
    if shortcut is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            f"[secretary] 决策层B 短路命中 rule={shortcut.get('action')} "
            f"shop={shop_id or '-'} session={session_id or '-'} "
            f"cost={elapsed_ms:.1f}ms query={query[:40]!r}"
        )
        return {
            "reply": intent_shortcut.build_reply(shortcut),
            "actions": [shortcut],
            "action": shortcut,
            "tool_calls": intent_shortcut.to_tool_calls(shortcut),
            "route_mode": "shortcut",
            "shortcut_rule": shortcut.get("action", ""),
        }

    agent = get_secretary_agent(shop_id)

    # 决策层 C：session_id 作为 checkpointer 的 thread_id，实现跨轮持久化。
    # 关键语义：checkpointer 会自动把同一 thread_id 的历史消息注入上下文，
    # 因此有 session_id 时**不应再手动拼 history**（否则历史重复两份）。
    thread_id = session_id or "secretary-default"
    use_checkpoint = session_id is not None and agent.checkpointer is not None

    # 拼接输入消息：
    # - 有 checkpointer：只传当前 query，历史由 checkpointer 自动恢复
    # - 无 checkpointer：手动拼 history（决策层 A 的会话级记忆）
    messages: list = []
    if not use_checkpoint and history:
        for h in history:
            role = (h or {}).get("role")
            content = (h or {}).get("content", "")
            if not content:
                continue
            if role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=query))

    state = await agent.graph.ainvoke(
        {"messages": messages},
        config={"configurable": {"thread_id": thread_id}},
    )

    messages = state.get("messages", [])

    # 只提取「本轮新增」的消息：定位最后一条 HumanMessage（= 本轮输入），其后的即为本轮产出。
    #
    # 为什么不用 aget_state 取调用前的历史长度（旧实现）：
    #   ① 多一次 DB 往返；② 连接池紧张时会 PoolTimeout，而当时的
    #   `except Exception: prev_count = 0` 会把它静默吞掉 → prev_count=0 →
    #   历史里的动作被当作本轮新增重复提取 → 前端重复切 Agent（切到 A 又切到 B）。
    # 用「最后一条 HumanMessage 之后」切分不依赖 DB，天然免疫该问题；
    # LLM 只产出 AIMessage / ToolMessage，不会再产生 HumanMessage，
    # 因此最后一条 HumanMessage 必然是本轮输入。
    last_human_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last_human_idx = i
    new_messages = messages[last_human_idx + 1:]

    # 1) 按顺序收集所有动作标记（导航/选择工具的 ToolMessage 内容）
    actions: list[dict] = []
    # 2) 提取工具调用名
    tool_calls: list[str] = []
    # 3) 最终回复文本（最后一条 AIMessage 的非空 content）
    reply = "处理完成"
    # 动作去重：LLM 偶尔会在一次回复里重复调用同一工具（如两次 switch_agent 同名同参），
    # 重复执行对前端无意义（切两次同一 Agent），这里按「动作签名」去重，保留首次出现。
    _seen_actions: set[str] = set()

    for m in new_messages:
        cls = m.__class__.__name__
        if cls == "ToolMessage":
            content = str(m.content)
            # 业务工具的 JSON 结果里也可能有 "action" 字段，需精确匹配导航/选择标记
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("action") in (
                    "switch_agent",
                    "navigate",
                    "select_product",
                    "account_menu",
                    "handoff",
                    "set_theme",
                    "switch_shop",
                ):
                    sig = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
                    if sig not in _seen_actions:
                        _seen_actions.add(sig)
                        actions.append(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        elif cls == "AIMessage":
            # 记录 tool_calls
            if getattr(m, "tool_calls", None):
                tool_calls.extend(tc.get("name") for tc in m.tool_calls if tc.get("name"))
            # 最后一条有内容的 AIMessage 作为回复
            content = m.content
            if isinstance(content, str) and content.strip():
                reply = content
            elif isinstance(content, list):
                # content 可能是多模态块列表
                text = "".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")
                )
                if text.strip():
                    reply = text

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        f"[secretary] 决策层B LLM 兜底 shop={shop_id or '-'} "
        f"session={session_id or '-'} cost={elapsed_ms:.1f}ms "
        f"tools={tool_calls or '-'} actions={len(actions)} query={query[:40]!r}"
    )

    return {
        "reply": reply,
        "actions": actions,
        "action": actions[-1] if actions else None,
        "tool_calls": tool_calls,
        "route_mode": "llm",
        "shortcut_rule": "",
    }
