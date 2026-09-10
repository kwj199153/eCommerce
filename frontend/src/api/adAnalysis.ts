/**
 * 广告分析 API 接口
 */

import request from './request'

/**
 * 广告账户健康诊断
 */
export function diagnoseAdAccount(data: {
  time_range?: string
  campaign_ids?: string[]
  include_benchmark?: boolean
}) {
  return request.post('/ad-analysis/diagnose', data)
}

/**
 * 搜索词效果分析
 */
export function analyzeSearchTerms(data: {
  time_range?: string
  campaign_type?: string
  min_spend?: number
  min_clicks?: number
  sort_by?: string
}) {
  return request.post('/ad-analysis/search-terms', data)
}

/**
 * 出价优化建议
 */
export function optimizeBids(data: {
  strategy?: string
  keywords?: string[]
  max_budget_change?: number
  target_acos?: number
}) {
  return request.post('/ad-analysis/bid-optimize', data)
}

/**
 * 竞品广告分析
 */
export function analyzeCompetitors(data: {
  competitor_asins?: string[]
  auto_detect?: boolean
  include_keywords?: boolean
  time_range?: string
}) {
  return request.post('/ad-analysis/competitors', data)
}

/**
 * 预算分配优化
 */
export function optimizeBudget(data: {
  total_daily_budget?: number
  target_roas?: number
  min_campaign_budget?: number
  seasonality_factor?: string
}) {
  return request.post('/ad-analysis/budget', data)
}

/**
 * 异常检测
 */
export function detectAnomalies(data: {
  check_period?: string
  sensitivity?: string
  alert_thresholds?: Record<string, number>
}) {
  return request.post('/ad-analysis/anomalies', data)
}

/**
 * 广告分析师对话（主入口）
 */
export function chatWithAdAnalyst(data: {
  message: string
  context_id?: string
  stream?: boolean
}) {
  return request.post('/ad-analysis/chat', data)
}

/**
 * 查询广告分析 Agent 能力
 */
export function getAdAnalysisCapabilities() {
  return request.get('/ad-analysis/capabilities')
}
