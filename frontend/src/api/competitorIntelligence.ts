/**
 * 竞品情报监控 API
 */

import request from './request'

// ==================== 类型定义 ====================

export interface CompetitorInfo {
  asin: string
  title: string
  brand: string
  price: number
  currency?: string
  bsr_rank?: number
  review_count?: number
  rating?: number
  category?: string
  is_prime?: boolean
  stock_status?: string
  last_updated?: string
}

export interface PricePoint {
  date: string
  price: number
}

export interface RankingPoint {
  date: string
  bsr_rank: number
}

export interface MonitorAlert {
  type: string
  severity: string
  message: string
  timestamp: string
}

export interface MarketShareItem {
  competitor_asin: string
  brand_name: string
  estimated_market_share: number
  bsr_rank: number
  revenue_estimate: number
  trend: 'rising' | 'stable' | 'declining'
}

export interface PricingStrategy {
  strategy_type: 'premium' | 'economy' | 'competitive' | 'dynamic'
  base_price: number
  avg_discount: number
  promo_frequency: string
  price_elasticity: number
  price_volatility: number
  recommendations: string[]
}

export interface ReviewInsight {
  aspect: string
  topic: string
  sentiment_score: number
  mention_count: number
  example_quotes: string[]
}

export interface ReviewSWOT {
  strengths: string[]
  weaknesses: string[]
  opportunities: string[]
  threats: string[]
}

export interface IntruderAlert {
  asin: string
  title: string
  brand: string
  entry_date: string
  price: number
  threat_level: 'high' | 'medium' | 'low'
  reasons: string[]
  our_product_affected: boolean
}

export interface BuyBoxSeller {
  seller_name: string
  price: number
  shipping: number
  in_stock: boolean
}

export interface BuyBoxAnalysis {
  current_winner: string
  winning_price: number
  our_price_competitiveness: number
  all_sellers: BuyBoxSeller[]
  buy_box_percentage: number
  price_to_win: number
  featured_offer_reason: string
}

export interface ComparisonDimension {
  dimension: string
  values: { asin: string; brand: string; value: any }[]
  best: string
  best_value: any
}

// ==================== API 函数 ====================

/**
 * 竞品 Listing 监控
 */
export async function monitorCompetitor(asin?: string, days = 30) {
  return request.post('/competitor/monitor', { asin, days })
}

/**
 * 获取监控仪表盘
 */
export async function getMonitorDashboard() {
  return request.get('/competitor/monitor/dashboard')
}

/**
 * ASIN 批量追踪
 */
export async function trackBatchAsins(asins: string[], includeHistory = true) {
  return request.post('/competitor/track/batch', {
    asins,
    include_history: includeHistory,
  })
}

/**
 * 市场份额分析
 */
export async function analyzeMarketShare(category: string) {
  return request.post('/competitor/market-share', { category })
}

/**
 * 按类目获取市场份额（快捷接口）
 */
export async function getMarketShareByCategory(category: string) {
  return request.get(`/competitor/market-share/${encodeURIComponent(category)}`)
}

/**
 * 定价策略分析
 */
export async function analyzePricingStrategy(asin?: string, analysisDepth = 'standard') {
  return request.post('/competitor/pricing/analyze', {
    asin,
    analysis_depth: analysisDepth,
  })
}

/**
 * 竞品评论深度分析
 */
export async function analyzeCompetitorReviews(
  asin: string,
  aspects?: string[],
  sampleSize = 100
) {
  return request.post('/competitor/reviews/analyze', {
    asin,
    aspects,
    sample_size: sampleSize,
  })
}

/**
 * 快捷评论分析
 */
export async function getReviewAnalysis(asin: string) {
  return request.get(`/competitor/reviews/${asin}`)
}

/**
 * 入侵者检测
 */
export async function detectIntruders(category: string, lookbackDays = 30) {
  return request.post('/competitor/intruders/detect', {
    category,
    lookback_days: lookbackDays,
  })
}

/**
 * 快捷入侵者检测
 */
export async function detectIntrudersByCategory(category: string) {
  return request.get(`/competitor/intruders/${encodeURIComponent(category)}`)
}

/**
 * Buy Box 竞争分析
 */
export async function analyzeBuyBox(asin?: string, marketplace = 'US') {
  return request.post('/competitor/buy-box/analyze', {
    asin,
    marketplace,
  })
}

/**
 * 多维度竞品对比
 */
export async function compareCompetitors(asins: string[]) {
  return request.post('/competitor/compare', {
    asins,
    dimensions: ['price', 'rating', 'reviews', 'bsr', 'value'],
  })
}

/**
 * 通用分析入口（自然语言）
 */
export async function generalCompetitorAnalysis(query: string, context?: Record<string, any>) {
  return request.post('/competitor/analyze', null, {
    params: { query },
    data: context,
  })
}
