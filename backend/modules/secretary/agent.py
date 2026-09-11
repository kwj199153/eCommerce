"""
店秘书（主 Agent / 编排层）

定位：全局入口，把用户一句话翻译成「回复 + 动作」。
- 动作分两类：①业务执行（调细粒度能力工具出结果）②导航（切 Agent / 打开资料库）。
- 它**不产出业务结果本身**，只做路由与调度。

实现：
- 继承 `ai_infra.BaseAgent`，注入「业务工具（listing 4 个）+ 导航工具（2 个）」。
- 通过「bind_tools + LLM 调用」让 LLM 决定调哪个工具、填什么参。
- 6 个业务 agent 本体零改动；导航动作由前端 dispatchAppAction 落地。
"""

import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent
from modules.listing_generator.tools import listing_tools
from modules.aigc_media.tools import aigc_tools
from modules.product_research.tools import product_research_tools
from modules.customer_service.tools import customer_service_tools
from modules.ad_analysis.tools import ad_analysis_tools
from modules.secretary.navigation_tools import navigation_tools
from modules.secretary.product_tools import build_product_tools
from modules.secretary.shop_tools import build_shop_tools

SECRETARY_SYSTEM_PROMPT = """你是「店管家 AI」的店秘书，一个跨境电商运营助手。

你的职责：理解老板的一句话需求，判断它是「要干活」还是「要跳转」，然后调用合适的工具。

可用的工具分四类：

【Listing 业务工具】
- optimize_listing_title：优化 Listing 标题
- generate_bullet_points：生成五点描述（卖点）
- generate_product_description：生成产品描述
- generate_search_terms：生成后台搜索词

【AIGC 业务工具】
- generate_product_image：生成产品图片（含提示词、SEO 关键词）
- analyze_main_image：分析主图质量（评分、CTR 预测、改进建议）
- generate_a_plus_content：生成 A+ 内容（EBC 品牌内容）
- generate_brand_story：生成品牌故事（定位、使命、标语）
- translate_content：多语言内容翻译（含 SEO 优化）
- generate_infographic：生成营销信息图规格
- check_image_compliance：检查图片合规性
- generate_video_script：生成短视频脚本（分镜、旁白、钩子）

【选品分析业务工具】
- analyze_blue_ocean：蓝海品类挖掘（低竞争 + 有需求 + 有利润筛选候选商品）
- analyze_profit：利润分析（净利润 / ROI / 盈亏平衡点）
- analyze_pain_points：痛点分析（提炼用户差评痛点与改进方向）
- compare_competitors：竞品对比（Listing 质量、价格、优劣势）

【智能客服业务工具】
- search_faq：搜索客服知识库（FAQ）
- create_ticket：创建客服工单
- analyze_sentiment：分析文本情感（正面/负面/中性）
- get_conversation_summary：获取客服对话摘要

【广告分析业务工具】
- diagnose_ad_account：广告账户健康诊断（评级 + 问题清单）
- analyze_search_terms：搜索词效果分析（高效/低效/浪费词）
- optimize_bids：出价优化建议（策略 + 目标 ACOS）
- analyze_ad_competitors：竞品广告分析（策略/展示份额/关键词重叠）
- optimize_budget：预算分配优化（提升 ROI）
- detect_ad_anomalies：广告异常检测（花费突增/转化骤降）

【导航工具】
- switch_agent：切换到某个业务 Agent（如选品、广告、做图、改文案）
- open_view：打开某个资料库 / 看板（产品库、选品库、竞品监控等）
- handoff_to_agent：把对话交接给专业 Agent 接管，让它追问缺失信息后执行
- set_theme：切换界面外观主题（浅色 / 深色 / 跟随系统）

【产品选择工具】
- select_product：选中产品库里的第 N 个产品（默认第一个）作为「工作商品」

【店铺切换工具】
- switch_shop：切换当前工作的店铺（数据源），按店铺名或序号切

规则：
1. 老板要「做具体的事」（如润色标题、生成卖点、做图、翻译、写视频脚本、找蓝海、算利润、查 FAQ、建工单）→ 调对应的业务工具，拿到结果后简洁汇报。
2. 老板要「找某个专职助手 / 看某个库」→ 调 switch_agent 或 open_view。
3. 老板要「选第 N 个产品再切到某 Agent 干活」→ 先调 select_product 选中产品，再调 switch_agent 切过去。两者一起完成才算满足意图。
4. 与工具无关的闲聊，礼貌回应即可，不要强行调用工具。
5. 一次只做最贴合意图的一件事，不要多调无关工具。
6. 【重要】老板提出专业生成类需求（生图/视频脚本/A+内容），但关键信息不足（如生图缺材质/造型/视角/是否需要 logo/产品细节）时，**不要**自己用默认值调业务工具硬凑结果，而是调 handoff_to_agent 把对话交接给专业 Agent，让它在自己的领域内逐项追问补齐后再执行。判断标准：老板一句话里，生成所需的核心参数（≥2 个）缺失时即视为信息不足。
7. 【兜底】若你调用了业务工具（如 generate_product_image），而它返回了 needs_clarification=true 和 missing_fields（缺失字段清单），**不要**把假结果汇报成已完成，也**不要**用默认值再次调用；应把 missing_fields 逐项转述给老板，请其补充后再继续。
8. 老板要「切店铺/换店铺/用 XX 店」→ 调 switch_shop 切数据源。
"""


class SecretaryAgent(BaseAgent):
    """店秘书主 Agent"""

    def __init__(self, llm=None, shop_id: Optional[str] = None, **kwargs):
        # 产品选择工具按店铺动态构建（shop_id 为空时返回空标记，由前端提示）
        product_tools = build_product_tools(shop_id)
        shop_tools = build_shop_tools()
        super().__init__(
            agent_name="secretary",
            system_prompt=SECRETARY_SYSTEM_PROMPT,
            tools=listing_tools + aigc_tools + product_research_tools + customer_service_tools + ad_analysis_tools + navigation_tools + product_tools + shop_tools,
            llm=llm,
            max_iterations=6,
            metadata={"role": "orchestrator"},
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
    """
    global _agent
    if shop_id is None:
        if _agent is None:
            _agent = SecretaryAgent()
        return _agent
    return SecretaryAgent(shop_id=shop_id)


async def route(query: str, shop_id: Optional[str] = None, history: Optional[list[dict]] = None) -> dict:
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

    Returns:
        {"reply": str, "actions": [dict], "action": dict|None, "tool_calls": [str]}
    """
    agent = get_secretary_agent(shop_id)

    # 拼接历史上下文 + 当前消息（历史在前，当前在后）
    messages: list = []
    if history:
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

    # 直接跑图（不传 checkpointer，上下文由前端显式传入的 history 承载）
    state = await agent.graph.ainvoke(
        {"messages": messages},
        config={"configurable": {"thread_id": "secretary-default"}},
    )

    messages = state.get("messages", [])

    # 1) 按顺序收集所有动作标记（导航/选择工具的 ToolMessage 内容）
    actions: list[dict] = []
    # 2) 提取工具调用名
    tool_calls: list[str] = []
    # 3) 最终回复文本（最后一条 AIMessage 的非空 content）
    reply = "处理完成"

    for m in messages:
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
                    "open_drawer",
                    "handoff",
                    "set_theme",
                    "switch_shop",
                ):
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

    return {
        "reply": reply,
        "actions": actions,
        "action": actions[-1] if actions else None,
        "tool_calls": tool_calls,
    }
