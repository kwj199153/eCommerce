"""Agent 目录 —— 后端 `agent_name` 与前端 `agent id` 的**唯一桥接真源**（第 181 轮）

==============================================================================
★ 为什么必须有这张表
==============================================================================
本项目的 Agent 有**两套 ID**，且它们**对不上**（第 181 轮实测）：

    前端 `frontend/src/stores/agent.ts`（界面路由用）
        secretary / product-research / competitor-intel / aigc-media /
        listing-generator / ad-analysis / customer-service / review-analyst

    后端各 Agent 的 `self.agent_name`（注入与日志用）
        secretary / ProductResearcher / competitor_intel / AIGC 媒体生成器 /
        ListingGenerator / ad_analysis / 智能客服 / review_analyst

八个里只有两个（`secretary` / `competitor_intel`… 其实只 `secretary` 一个完全一致，
其余大小写或语种都不同）能直接对上。这是本仓反复吃过的那类问题：

    **同名概念两套 ID 空间 ⇒ 归属/装配链在中间断掉，且不报错。**

技能启用必须存**后端 `agent_name`**（因为 `PromptContext.agent_name` 是它，
注入发生在后端），而勾选界面要展示**前端 id/名称**。
⇒ 两边的映射**必须只有一个源**，否则改一处就静默失配。

==============================================================================
★ 这张表就是那个唯一的源，它有两条硬约束
==============================================================================
  ① `name` 必须是**后端真实存在**的 `agent_name` 字面量
     —— 由 `tests/test_skill_agent_catalog.py` 用 AST 扫描全仓 `agent_name=` 赋值钉住；
        扫不到 ⇒ 说明后端改名了而本表没跟，**当场红**。
  ② `id` 必须是前端 `AGENT_LIST` 里真实存在的 id
     —— 同一门禁用正则扫 `frontend/src/stores/agent.ts` 钉住。

★ 为什么不干脆把后端 `agent_name` 统一改成前端 id？
  它会牵动三处已上线的东西（日志里的 agent 名、
  `prompt_sections` provider 按 agent_name 的分支、已有的会话/记忆归属口径），
  属于「改名字去解决一个映射问题」—— 成本远高于加一张 15 行的表。
  本表是**桥**，不是重复：它只声明「这两个字符串指的是同一个 Agent」。

==============================================================================
★ 谁来消费
==============================================================================
  · `GET /api/v1/agents`            —— 前端勾选界面的数据源
  · `PUT /api/v1/skills/{id}/agents`—— 校验被勾选的 agent 是真实存在的
  · 后端注入（`provider`）          —— 反查展示名用于日志/文案
"""

from typing import Dict, List, Optional

#: 平台全部 Agent。**顺序即界面展示顺序**（与前端 `AGENT_LIST` 一致）。
#:
#: 字段：
#:   name —— 后端 `agent_name`（技能启用的**存值**，权威 key）
#:   id   —— 前端 agent id（界面路由用）
#:   title—— 展示名（中文）
#:   description —— 一句话职责（界面副标题）
AGENT_CATALOG: List[Dict[str, str]] = [
    {
        "name": "secretary",
        "id": "secretary",
        "title": "店秘书",
        "description": "全局调度：一句话直达对应 Agent 或打开资料库",
    },
    {
        "name": "ProductResearcher",
        "id": "product-research",
        "title": "选品分析师",
        "description": "蓝海挖掘、利润计算、竞品分析",
    },
    {
        "name": "competitor_intel",
        "id": "competitor-intel",
        "title": "竞品监控员",
        "description": "价格追踪、上新监控、舆情分析",
    },
    {
        "name": "AIGC 媒体生成器",
        "id": "aigc-media",
        "title": "AIGC 媒体生成器",
        "description": "AI 商品绘图、主图诊断、短视频分镜、AI 视频生成",
    },
    {
        "name": "ListingGenerator",
        "id": "listing-generator",
        "title": "Listing 优化师",
        "description": "标题、五点、描述、关键词生成优化",
    },
    {
        "name": "ad_analysis",
        "id": "ad-analysis",
        "title": "广告分析师",
        "description": "广告诊断、词报告、出价优化、竞品监控",
    },
    {
        "name": "智能客服",
        "id": "customer-service",
        "title": "智能客服",
        "description": "FAQ 问答、订单追踪、工单管理",
    },
    {
        "name": "review_analyst",
        "id": "review-analyst",
        "title": "运营复盘师",
        "description": "周报/月度复盘、广告归因、商品表现、利润审计、行动计划",
    },
]

#: `agent_name` → 目录项（enabled_agents 校验与展示名反查用）
_BY_NAME: Dict[str, Dict[str, str]] = {a["name"]: a for a in AGENT_CATALOG}


#: 「工具化路由子层」的 `agent_name` 后缀。
#:
#: ★★★ 为什么需要归一（第 198 轮实测的**既有缺陷**）：
#:   `listing_generator` / `product_research` / `review_analyst` / `competitor_intel`
#:   的 `_build_router()` 把子层建成 `agent_name=f"{self.agent_name}_router"`，
#:   而技能启用（`skills.enabled_agents`）存的是**业务** agent_name（只能取
#:   本文件 `AGENT_CATALOG` 的值，见 `service._validate_agents`）。
#:   技能目录与正文的过滤都是 `agent_name in enabled_agents` ⇒ 走工具通道时
#:   名字对不上 ⇒ 技能**静默不注入**：目录段为空、正文读不到、`load_skill`
#:   无从调用，而且**一处日志都没有**。
#:   ⇒ 在注入边界把后缀剥掉。这是唯一真源式修法：两个 provider 共用本函数，
#:     不要在各自那里各写一份判定。
ROUTER_SUFFIX = "_router"


def business_agent_name(agent_name: str) -> str:
    """把「工具化路由子层」的 `X_router` 归一回业务 Agent 名 `X`。

    非 `_router` 结尾的名字**原样返回** —— 本函数是**归一**，不是改写：
    匿名探针（如 `probe-memoryless`）与业务名都要能穿过。
    """
    name = str(agent_name or "")
    if len(name) > len(ROUTER_SUFFIX) and name.endswith(ROUTER_SUFFIX):
        return name[: -len(ROUTER_SUFFIX)]
    return name

def all_agent_names() -> tuple:
    """全部**合法**的 agent_name（技能启用只能存这里的值）。"""
    return tuple(a["name"] for a in AGENT_CATALOG)


def agent_title(agent_name: str) -> str:
    """取展示名；未知 agent 原样返回 —— 日志里宁可显示怪名字，
    也不要因为一次改名让整轮对话挂掉。"""
    item = _BY_NAME.get(str(agent_name or ""))
    return item["title"] if item else str(agent_name or "")


def is_known_agent(agent_name: str) -> bool:
    return str(agent_name or "") in _BY_NAME


def find_by_id(agent_id: str) -> Optional[Dict[str, str]]:
    """按前端 id 反查（前端传 id 过来时用）。"""
    key = str(agent_id or "")
    for item in AGENT_CATALOG:
        if item["id"] == key:
            return item
    return None


__all__ = [
    "AGENT_CATALOG",
    "ROUTER_SUFFIX",
    "business_agent_name",
    "all_agent_names",
    "agent_title",
    "is_known_agent",
    "find_by_id",
]
