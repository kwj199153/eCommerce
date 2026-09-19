/**
 * 店秘书（主 Agent / 编排层）API 接口
 */

import request from './request'
import type { ThemeMode } from '@/theme/presets'

/** 后端 orchestrator 返回的动作 */
export interface SecretaryAction {
  action: 'switch_agent' | 'navigate' | 'select_product' | 'open_drawer' | 'account_menu' | 'handoff' | 'set_theme' | 'switch_shop'
  agentId?: string
  /** switch_agent 专属：老板原话（路由带参）。非空时子 Agent 切换后自动续跑 */
  query?: string
  view?: string
  /** select_product 专属：选中的产品（id 用于前端从 productLibrary 定位完整对象） */
  product?: { id: string; title: string; asin: string; spu_id?: string } | null
  /** open_drawer 专属：drawer 标识（settings | memory） */
  drawer?: 'settings' | 'memory'
  /** account_menu 专属：账户菜单 target（settings | memory | subscription | logout） */
  target?: 'settings' | 'memory' | 'subscription' | 'logout'
  /** handoff 专属：已识别的意图 + 需追问的缺失字段 */
  intent?: string
  missing_fields?: string[]
  /**
   * set_theme 专属：目标主题。
   * ★ 刻意**引用** `ThemeMode` 而不是写死字面量 —— 主题清单的真源是
   *   `@/theme/presets` 的 `ThemeName`，写死会产生第 3 个复制点（加主题时静默漏改）。
   */
  mode?: ThemeMode
  /** switch_shop 专属：目标店铺（id 用于前端 shopStore.setCurrentShop） */
  shop?: { id: string; name: string; platform: string } | null
  index?: number
  total?: number
}

/**
 * 子任务状态取值域。
 *
 * ★ 真源是后端 `backend/ai_infra/plan.py::TASK_STATUSES`。前端引用它**只为渲染**
 *   （挑图标/配色），**不用来做判定** —— 「完成了几项 / 共几项」一律读后端算好的
 *   `PlanSummary.completed` / `.total`。前端再 `items.filter(...)` 数一遍就是
 *   第二份实现：后端改了判据（比如 `blocked` 也算完成）它不会跟着变，
 *   而界面会安静地显示错的进度。
 * ★ 类型上保留 `| string` 不是为了宽容乱写，而是为了**后端新增状态时前端不崩**
 *   （`PlanChecklist.vue` 的渲染表必须有兜底分支）。
 */
export type PlanTaskStatus = 'pending' | 'in_progress' | 'completed' | 'blocked'

export interface PlanTask {
  id: string
  content: string
  status: PlanTaskStatus
  /** 该步的补充说明（完成结论 / 卡住的原因），后端已截断到 200 字符 */
  note: string
}

export interface PlanSummary {
  total: number
  completed: number
  /**
   * 各状态计数。★ 键由后端给（= `TASK_STATUSES` 全集，恒含四个键，值为 0 也在）
   *   —— 前端**不要**自己枚举状态种类，直接用这个字典。
   */
  by_status: Record<string, number>
  items: PlanTask[]
}

export interface SecretaryResponse {
  reply: string
  /** 有序动作列表（如「先选产品，再切 Agent」），前端按顺序执行 */
  actions: SecretaryAction[]
  /** 向后兼容：= actions 最后一个 */
  action: SecretaryAction | null
  tool_calls: string[]
  /** 会话 ID（后端返回，前端持久化后后续请求带回，实现跨会话记忆） */
  session_id?: string | null
  /**
   * 本会话的子任务计划（第 148 轮批 C3 后端产出，第 155 轮补上前端消费）。
   *
   * ★ 后端**只在真有计划时才带这个键**（`null` / `undefined` = 没计划）。
   *   恒返回一个空计划会让调用方分不清「这个 Agent 没开启规划」与
   *   「开启了但这一轮还没规划」。
   * ★ 它**不属于任何一条消息**：计划存在后端图状态里（随 checkpointer 落 PG），
   *   刻意不放进消息序列 —— 所以对话变长、历史被裁剪，它都不会丢。
   *   前端因此也把它存成**会话级状态**（`chatStore.planByAgent`）而不是消息附件。
   */
  plan?: PlanSummary | null
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

/**
 * 店秘书对话（全局入口）
 * 后端主 Agent 识别意图：调业务工具出结果，或返回导航/选择动作。
 * history 传本会话历史消息（不含当前 message），用于多轮上下文连贯。
 * session_id 传会话 ID（跨会话记忆，非空时后端从 DB 读历史 + checkpoint 持久化）。
 */
export function chatWithSecretary(data: {
  message: string
  history?: HistoryMessage[]
  session_id?: string | null
}): Promise<SecretaryResponse> {
  return request.post('/orchestrator/chat', data)
}

/** `GET /orchestrator/plan` 的响应信封。`plan: null` 与"读不到"**同一个响应**。 */
export interface PlanEnvelope {
  plan: PlanSummary | null
}

/**
 * 读会话当前子任务计划（只读：不推进对话、不调 LLM、**不消耗对话次数**）。
 *
 * 为什么需要它：`chatWithSecretary` 每次都会把 `plan` 带回来，但那是**对话的
 * 副产品** —— 老板刷新页面后前端手上没有"最近一次响应"，计划条就会空着，
 * 直到他再随便说一句话。而计划是**跨轮持续的状态**，理应有个不依赖
 * 「刚好聊过一句」的读取方式。
 *
 * ★ `session_id` 走 **query**（后端用 `Query(...)` 声明）。这不是随手选的：
 *   本仓踩过一次「裸标量形参按 query 解析、前端发 body ⇒ 稳定 422 ⇒ 功能
 *   '看起来做了'但从未生效」，所以两边的形状必须一起对齐。
 * ★ 后端对 `null` 不区分原因（没计划 / 没会话 / 没身份 / 读失败）——
 *   前端也**不得**据此推断"这个会话不存在"，那正是枚举探针。
 */
export function fetchCurrentPlan(sessionId: string): Promise<PlanEnvelope> {
  return request.get('/orchestrator/plan', { params: { session_id: sessionId } })
}
