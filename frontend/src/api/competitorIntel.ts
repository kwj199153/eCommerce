/**
 * 竞品情报 API
 *
 * 与后端 /api/v1/competitor/* 端点交互。
 *
 * ★ 形状提醒（本轮接线实测）：本模块的 `/compare` **不经 ApiResponse 包装**，
 *   后端直返 `CompetitorAnalysisResponse{success, intent, data, message, timestamp}`；
 *   而 `/ad-analysis/*` 与 `/listing/*` 返回的是 `{success, data, message}`（`data` 里才是业务体）。
 *   取数据前先看清是哪一种 —— 两种混用会静默拿到 undefined。
 */

import request from './request'
import { streamSSE, type SSEHandlers } from './stream'

export interface CompetitorCompareRequest {
  /** 2-10 个 ASIN（后端硬校验：<2 直接 400） */
  asins: string[]
  dimensions?: string[]
}

/**
 * 多维度竞品对比
 *
 * 返回 `{success, data:{type, compared_count, competitors[], comparison{...}}, message}`
 * ★ 注意 `data.competitors[]` **只有** `{asin, brand, title}` 三个字段；
 *   价格 / 评分 / 评论数 / 性价比 / 排名都在 `data.comparison.*` 里，
 *   由 `utils/toolResultAdapters.ts::adaptCompetitorCompare` 负责重建。
 */
export function compareCompetitors(
  data: CompetitorCompareRequest,
  config?: Record<string, any>,
): Promise<any> {
  return request.post('/competitor/compare', data, config) as any
}

// ==================== 对话（技能点名 · 第 189 轮）====================

/**
 * 把「技能名」拼进 URL 的 query string（**竞品模块专用**）。
 *
 * ★★ 为什么本模块的 skill 必须走 URL 而不是 body —— 这是全仓唯一的例外。
 *   后端 `/competitor/analyze` 与 `/competitor/chat/stream` 的入参是**裸标量**
 *   `query: str = Query(...)`（见 `modules/competitor_intel/router.py` L252/L279），
 *   请求体里根本不存在能放 skill 的 pydantic 模型 ⇒ 后端读的是 `Query(...)`。
 *   而 `streamSSE()` 的实现**只发 body JSON**（`api/stream.ts` 的
 *   `JSON.stringify(body)`，没有第二个参数）⇒ 把 skill 塞进 body 传过去，
 *   后端永远收不到，而请求仍然 200、仍然出正文 —— 又是一例「技能静默不生效」。
 *   ⇒ 这两个端点只能把 skill 拼在 URL 上。
 */
function _queryWithSkill(query: string, skill?: string | null): string {
  const params = new URLSearchParams({ query })
  if (skill) params.set('skill', skill)
  return params.toString()
}

/**
 * 通用分析入口（`POST /competitor/analyze`）。
 *
 * 返回 `{success, data, message, timestamp}`（**非** ApiResponse 的 `{success,data,message}`）。
 * body 传 `{}`：后端还有个 `context: Optional[dict] = None` 的可选 body 参数，
 * 而 `service.general_analysis` 里是 `ctx = dict(context or {})` ⇒ `{}` 与 `None` 等价。
 */
export function analyzeCompetitor(
  query: string,
  skill?: string | null,
): Promise<any> {
  return request.post(
    `/competitor/analyze?${_queryWithSkill(query, skill)}`,
    {},
    { silentError: true },
  ) as any
}

/**
 * 竞品情报对话（`POST /competitor/chat/stream`，SSE 流式）。
 *
 * 走 `api/stream.ts` 的 `streamSSE`（它内部用 fetch，带 Authorization / X-Shop-ID），
 * `skill` 同样拼在 URL 上（原因见 `_queryWithSkill`）。
 *
 * ★ `options.signal` 透传给 `streamSSE` —— 「停止生成」按钮靠它真的中断这条流。
 *   不传的后果：点了停止也照渲染到结束（`fetch` 收不到 abort），而界面看不出异常。
 */
export function streamCompetitorChat(
  query: string,
  skill: string | null,
  handlers: SSEHandlers,
  options: { signal?: AbortSignal } = {},
): Promise<string> {
  return streamSSE(`/competitor/chat/stream?${_queryWithSkill(query, skill)}`, {}, handlers, options)
}
