# -*- coding: utf-8 -*-
"""一次性补丁（第 289 轮 P1 后半）：把「差评处理」接进客服 Agent 的功能栏 + 右栏面板。

三件事必须**同一批**做完（`check-tool-reality.cjs` 的 F1 判「注册了却没入口」⇒ 只注册不接线的工具会直接把门禁打红）：
  1. `toolDefinitions.ts`：给 `customer-service` 登记 `review-desk`（mode='form'）
  2. `TaskConfigPanel/index.vue`：按 `currentTool.id === 'review-desk'` 分支渲染新面板
  3. `api/trade.ts`：补 `listShopReviews`（近期差评列表）
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
TOOLS = SRC / "components" / "ChatPanel" / "tools" / "toolDefinitions.ts"
PANEL = SRC / "components" / "TaskConfigPanel" / "index.vue"
API = SRC / "api" / "trade.ts"


def _read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write(p: Path, s: str) -> None:
    p.write_bytes(s.encode("utf-8"))


def sub(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    assert n == 1, f"锚点命中 {n} 次（须为 1）：{label}"
    return src.replace(old, new, 1)


# ---------------- 1. 工具目录

t = _read(TOOLS)

t = sub(
    t,
    """  'customer-service': [
    { id: 'order-track', name: '订单追踪', icon: '📦', description: '订单状态与物流查询', mode: 'form', status: 'active', category: '订单' },
  ],""",
    """  'customer-service': [
    { id: 'order-track', name: '订单追踪', icon: '📦', description: '订单状态与物流查询', mode: 'form', status: 'active', category: '订单' },
    // ★ 第 289 轮新增：差评工作台。为什么它走**功能栏（form 工具）**而不是
    //   对话框上方的快捷卡片：它是**确定性**的 —— 「列差评 / 关联的缺口在哪 /
    //   有没有处置」是查表就能答的问题，不需要 LLM 推理；
    //   而快捷卡片（skill）那一路要点的是「帮我归因、怎么赔、回复怎么说」，
    //   那才是不确定结论。两者的落点也因此不同：form 工具点击后在右栏出面板，
    //   skill chip 是在对话里一轮推理。
    //   ⇒ 注意唯一不属于它的东西：**批准 / 发放**（发券退款不可逆）只走
    //      面板里的人工按钮 + REST，不进任何 Agent 工具。
    { id: 'review-desk', name: '差评处理', icon: '📉', description: '本店差评清单与处置（含关联不上产品的孤儿差评）', mode: 'form', status: 'active', category: '售后' },
  ],""",
    "登记 review-desk 工具",
)

_write(TOOLS, t)

# ---------------- 2. 右栏面板分支

p = _read(PANEL)

p = sub(
    p,
    "import OrderTrackConfig from './configs/OrderTrackConfig.vue'",
    "import OrderTrackConfig from './configs/OrderTrackConfig.vue'\n"
    "import ReviewDeskConfig from './configs/ReviewDeskConfig.vue'",
    "import 面板组件",
)

p = sub(
    p,
    """      <!-- 订单追踪配置 -->
      <OrderTrackConfig""",
    """      <!-- ★ 差评工作台（第 289 轮 P1）：客服 Agent 功能栏「差评处理」按钮的落点。
           以**差评**为主语（区别于资料库里以**处置**为主语的 DispositionLibrary），
           没有它则「还没处置过的差评」永远不出现在任何界面上。 -->
      <ReviewDeskConfig v-else-if="currentTool.id === 'review-desk'" />

      <!-- 订单追踪配置 -->
      <OrderTrackConfig""",
    "面板分支",
)

_write(PANEL, p)

# ---------------- 3. api

a = _read(API)

a = sub(
    a,
    """/**
 * 某个 SPU 名下的差评 —— 产品详情「差评 tab」的数据源。""",
    """/**
 * 本店近期的中差评 —— 「差评工作台」的主列表。
 *
 * ★ 这个端点此前是缺的：`service.list_recent_negative_reviews` 只有 Agent 工具
 *   一个调用点，没有 HTTP 出口 ⇒ 前端要拿差评清单只能退而用「处置列表」，
 *   而那只看得见**已经处置过**的差评（历史差评从未被处置过 ⇒ 永远是空列表）。
 *   差评以差评为主语，处置以处置为主语，两者不能互相顶替。
 */
export async function listShopReviews(params?: {
  max_rating?: number
  days?: number
  limit?: number
  offset?: number
}): Promise<{ items: ProductReview[]; total: number; limit: number; offset: number }> {
  return request.get('/trade/reviews', { params })
}

/**
 * 某个 SPU 名下的差评 —— 产品详情「差评 tab」的数据源。""",
    "api 加 listShopReviews",
)

_write(API, a)

print("patched: toolDefinitions.ts / TaskConfigPanel/index.vue / api/trade.ts")
