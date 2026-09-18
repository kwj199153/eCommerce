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
