import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface TableColumn {
  title: string
  dataIndex: string
  key: string
}

export const useResultStore = defineStore('result', () => {
  // 内容类型
  const contentType = ref<'table' | 'chart' | 'report' | 'image' | 'code' | 'json' | 'listing' | 'profit_analysis' | 'ad_diagnosis' | 'order_info' | 'ticket' | 'competitor_monitor' | 'market_share' | 'pricing_strategy' | 'review_analysis' | 'intruder_detection' | 'buy_box_analysis' | 'competitor_comparison' | 'generated_image' | 'main_image_analysis' | 'a_plus_content' | 'brand_story' | 'translation' | 'infographic' | 'compliance_report' | 'video_script' | null>(null)

  // 表格数据
  const tableData = ref<any[]>([])
  const tableColumns = ref<TableColumn[]>([])

  // 报告内容（Markdown）
  const reportContent = ref('')

  // 图片
  const imageSrc = ref('')

  // 代码
  const codeContent = ref('')

  // 原始 JSON 数据
  const rawData = ref<any>(null)

  // Listing 数据（专用）
  const listingData = ref<{
    title: any
    bullet_points: any
    description: any
    search_terms: any
    seo_score: any
  } | null>(null)

  // 利润分析数据（专用）
  const profitData = ref<{
    net_profit?: number
    roi?: number
    profit_margin?: number
    breakeven_quantity?: number
    price?: number
    fee_breakdown?: Array<{ name: string; amount: number }>
    monthly_projection?: Array<{ volume: number; revenue: number; total_cost: number; net_profit: number }>
    sensitivity_analysis?: Array<{ scenario: string; roi: number; net_profit: number }>
    recommendations?: string[]
  } | null>(null)

  // 广告分析数据（专用）
  const adData = ref<{
    overall_score?: number
    grade?: string
    metrics?: Array<{ name: string; value: number; unit: string; benchmark: number; status: string }>
    campaigns?: Array<any>
    top_issues?: Array<any>
    recommendations?: Array<string>
  } | null>(null)

  // 订单数据（专用）
  const orderData = ref<{
    order_id?: string
    status?: string
    status_text?: string
    product_name?: string
    total?: number
    created_at?: string
    tracking_number?: string
    carrier?: string
    estimated_delivery?: string
  } | null>(null)

  // 工单数据（专用）
  const ticketData = ref<{
    ticket_id?: string
    subject?: string
    category?: string
    priority?: string
    status?: string
    created_at?: string
    sla_deadline?: string
    auto_replies?: string[]
  } | null>(null)

  // 竞品监控数据（专用）
  const competitorData = ref<{
    type?: string
    competitors?: Array<any>
    summary?: any
    product?: any
    price_trend?: any[]
    ranking_trend?: any[]
    analysis?: any
  } | null>(null)

  // 市场份额数据（专用）
  const marketShareData = ref<{
    category?: string
    total_market_estimate?: number
    competitors?: Array<any>
    insights?: string[]
    concentration_ratio?: any
  } | null>(null)

  // 入侵者检测数据（专用）
  const intruderData = ref<{
    category?: string
    detection_date?: string
    new_competitors?: Array<any>
    threat_summary?: any
    response_strategies?: Array<any>
  } | null>(null)

  // AIGC 生成图片数据（专用）
  const generatedImageData = ref<{
    image_id?: string
    prompt?: string
    image_type?: string
    style?: string
    description?: string
    suggested_captions?: string[]
    seo_keywords?: string[]
    usage_tips?: string[]
    variation_suggestions?: Array<any>
    style_guide?: Record<string, string>
  } | null>(null)

  // 主图分析数据（专用）
  const mainImageAnalysisData = ref<{
    overall_score?: number
    ctr_prediction?: number
    visual_appeal?: Record<string, number>
    compliance_check?: any
    improvement_suggestions?: string[]
    ab_test_variants?: Array<any>
  } | null>(null)

  // A+ 内容数据（专用）
  const aPlusContentData = ref<{
    product_asin?: string
    brand_name?: string
    modules?: Array<any>
    total_modules?: number
    estimated_read_time?: number
    optimization_tips?: string[]
  } | null>(null)

  // 品牌故事数据（专用）
  const brandStoryData = ref<{
    brand_name?: string
    brand_positioning?: string
    brand_mission?: string
    brand_values?: string[]
    origin_story?: string
    unique_selling_proposition?: string
    tagline_options?: string[]
    about_brand_text?: string
    storytelling_angles?: Array<any>
  } | null>(null)

  // 翻译结果数据（专用）
  const translationData = ref<{
    original_text?: string
    translated_text?: string
    source_lang?: string
    target_lang?: string
    seo_optimized?: boolean
    keyword_inclusion?: Array<any>
    cultural_notes?: string[]
    alternative_versions?: Array<any>
  } | null>(null)

  // 合规检查报告数据（专用）
  const complianceReportData = ref<{
    overall_status?: string
    score?: number
    issues?: Array<any>
    passed_checks?: string[]
    recommendations?: string[]
  } | null>(null)

  // 视频脚本数据（专用）
  const videoScriptData = ref<{
    title?: string
    total_duration?: number
    format?: string
    target_platform?: string
    scenes?: Array<any>
    hook_lines?: string[]
    cta_suggestions?: string[]
    hashtag_recommendations?: string[]
    production_notes?: string[]
  } | null>(null)

  // 是否有内容
  const hasContent = computed(() => contentType.value !== null)

  // 设置表格数据
  const setTableData = (data: any[], columns: TableColumn[]) => {
    contentType.value = 'table'
    tableData.value = data
    tableColumns.value = columns
  }

  // 设置报告内容
  const setReportContent = (content: string) => {
    contentType.value = 'report'
    reportContent.value = content
  }

  // 设置图片
  const setImage = (src: string) => {
    contentType.value = 'image'
    imageSrc.value = src
  }

  // 设置代码
  const setCode = (code: string) => {
    contentType.value = 'code'
    codeContent.value = code
  }

  // 设置原始 JSON 数据
  const setRawData = (data: any) => {
    contentType.value = 'json'
    rawData.value = data
  }

  /**
   * 智能设置数据（根据 displayType 自动选择展示方式）
   * 用于 Agent 返回结果后的自动渲染
   */
  const setResultData = (data: any, displayType?: string) => {
    if (!data) return

    const type = displayType || data.type || 'json'

    switch (type) {
      case 'blue_ocean_analysis':
        // 蓝海分析：渲染为表格
        const opportunities = data.opportunities || []
        if (opportunities.length > 0) {
          setTableData(
            opportunities.map((opp: any, index: number) => ({
              key: index,
              ...opp,
            })),
            [
              { title: '品类', dataIndex: 'category', key: 'category' },
              { title: '搜索量', dataIndex: 'search_volume', key: 'search_volume' },
              { title: '竞争度', dataIndex: 'competition', key: 'competition' },
              { title: '趋势', dataIndex: 'trend', key: 'trend' },
              { title: '机会评分', dataIndex: 'opportunity_score', key: 'opportunity_score' },
              { title: '建议售价区间', dataIndex: 'suggested_price_range', key: 'suggested_price_range' },
              { title: '预估利润率', dataIndex: 'estimated_margin', key: 'estimated_margin' },
            ]
          )
          // 同时保存原始数据和摘要
          rawData.value = data
        }
        break

      case 'profit_analysis':
        // 利润分析：专用可视化 + 报告
        const analysis = data.analysis || data
        const feesBreakdown = data.fee_breakdown || data.fees || []

        // 设置专用利润数据（供 SmartPanel 可视化使用）
        contentType.value = 'profit_analysis'
        profitData.value = {
          net_profit: analysis.net_profit ?? data.net_profit,
          roi: analysis.roi_percentage ?? data.roi ?? data.roi_percentage,
          profit_margin: data.margin_percentage ?? analysis.profit_margin,
          breakeven_quantity: analysis.break_even_quantity ?? data.breakeven_quantity,
          price: analysis.selling_price ?? data.price,
          fee_breakdown: feesBreakdown.length > 0 ? feesBreakdown : undefined,
          monthly_projection: data.monthly_projection,
          sensitivity_analysis: data.sensitivity_analysis,
          recommendations: data.recommendations || data.suggestions,
        }

        // 同时生成报告文本
        let report = `## 💰 SKU 利润分析\n\n`
        report += `**产品**: ${analysis.product_name || data.product_name || '未知'}\n\n`
        report += `**售价**: $${analysis.selling_price || data.price} | **成本**: $${analysis.cost_price || data.cost}\n\n`

        if (feesBreakdown && feesBreakdown.length > 0) {
          report += `### 费用明细\n\n`
          report += `| 项目 | 金额 | 占比 |\n|------|------|------|\n`
          const totalPrice = analysis.selling_price || data.price || 1
          feesBreakdown.forEach((fee: any) => {
            report += `| ${fee.name} | $${fee.amount} | ${((fee.amount / totalPrice) * 100).toFixed(1)}% |\n`
          })
        }

        report += `\n### 利润总结\n\n`
        report += `- **净利润/件**: $${analysis.net_profit ?? data.net_profit}\n`
        report += `- **ROI**: ${analysis.roi_percentage ?? data.roi ?? 0}%\n`
        report += `- **盈亏平衡点**: ${analysis.break_even_quantity ?? data.breakeven_quantity ?? 0} 件/月\n`
        report += `- **利润率**: ${data.margin_percentage ?? analysis.profit_margin ?? 0}%\n`

        if (data.recommendations?.length) {
          report += `\n### 💡 建议\n\n`
          data.recommendations.forEach((r: string, i: number) => {
            report += `${i + 1}. ${r}\n`
          })
        }

        setReportContent(report)
        rawData.value = data
        break

      case 'pain_point_analysis':
        // 痛点分析：渲染为表格 + 建议
        const painAnalysis = data.analysis || {}
        const painPoints = painAnalysis.pain_points || []

        let painReport = `## 😟 用户痛点分析\n\n`
        painReport += `**产品 ASIN**: ${painAnalysis.product_asin}\n\n`
        painReport += `**分析的评论数**: ${painAnalysis.total_reviews_analyzed} (差评: ${painAnalysis.negative_review_count})\n\n`
        painReport += `**市场空白度评分**: ${painAnalysis.market_gap_score}/100\n\n`

        if (painPoints.length > 0) {
          painReport += `### 高频痛点\n\n`
          painReport += `| 痛点 | 出现次数 | 占比 |\n|------|---------|------|\n`
          painPoints.forEach((pp: any) => {
            painReport += `| ${pp.pain_point} | ${pp.count} | ${pp.percentage}% |\n`
          })

          painReport += `\n### 💡 改进建议\n\n`
          const suggestions = painAnalysis.improvement_suggestions || []
          suggestions.forEach((s: string, i: number) => {
            painReport += `${i + 1}. ${s}\n`
          })
        }

        setReportContent(painReport)
        rawData.value = data
        break

      case 'competitor_analysis':
        // 竞品对比：渲染为表格
        const competitors = data.competitors || []
        if (competitors.length > 0) {
          setTableData(
            competitors.map((c: any, index: number) => ({
              key: index,
              asin: c.product?.asin || c.asin,
              title: c.product?.title || c.title,
              price: c.product?.price || c.price,
              rating: c.product?.rating || c.rating,
              review_count: c.product?.review_count || c.review_count,
              listing_quality_score: c.listing_quality_score,
              price_positioning: c.price_positioning,
              strengths: c.strengths?.join('; ') || '',
              weaknesses: c.weaknesses?.slice(0, 2).join('; ') || '',
            })),
            [
              { title: 'ASIN', dataIndex: 'asin', key: 'asin' },
              { title: '产品名称', dataIndex: 'title', key: 'title' },
              { title: '价格', dataIndex: 'price', key: 'price' },
              { title: '评分', dataIndex: 'rating', key: 'rating' },
              { title: '评论数', dataIndex: 'review_count', key: 'review_count' },
              { title: 'Listing质量', dataIndex: 'listing_quality_score', key: 'listing_quality_score' },
              { title: '定位策略', dataIndex: 'price_positioning', key: 'price_positioning' },
              { title: '优势', dataIndex: 'strengths', key: 'strengths' },
              { title: '劣势', dataIndex: 'weaknesses', key: 'weaknesses' },
            ]
          )
          rawData.value = data
        }
        break

      case 'complete_listing':
        // 完整 Listing：渲染为专用 Listing 预览格式
        const listing = data.listing || data
        contentType.value = 'listing'
        listingData.value = {
          title: listing.title || {},
          bullet_points: listing.bullet_points || {},
          description: listing.description || {},
          search_terms: listing.search_terms || {},
          seo_score: listing.seo_score || {},
        }
        rawData.value = data
        break

      case 'seo_analysis':
        // SEO 分析：渲染为评分报告
        const seoScore = data.seo_score || data
        const grade = seoScore.overall_score >= 90 ? 'A' : seoScore.overall_score >= 80 ? 'B' : seoScore.overall_score >= 70 ? 'C' : seoScore.overall_score >= 60 ? 'D' : 'F'

        let seoReport = `## 🔍 SEO 诊断报告\n\n`
        seoReport += `### 综合评分\n\n`
        seoReport += `**${seoScore.overall_score}/100** (等级: **${grade}**)\n\n`
        seoReport += `| 维度 | 得分 |\n|------|------|\n`
        seoReport += `| 标题 | ${seoScore.title_score}/100 |\n`
        seoReport += `| 五点描述 | ${seoScore.bullet_score}/100 |\n`
        seoReport += `| 产品描述 | ${seoScore.description_score}/100 |\n`
        seoReport += `| 关键词 | ${seoScore.keywords_score}/100 |\n`

        const improvements = seoScore.improvement_areas || []
        if (improvements.length > 0) {
          seoReport += `\n### 📋 待改进项\n\n`
          improvements.forEach((item: string, i: number) => {
            seoReport += `${i + 1}. ${item}\n`
          })
        }

        setReportContent(seoReport)
        rawData.value = data
        break

      case 'ad_diagnosis':
        // 广告诊断：专用可视化 + 报告
        contentType.value = 'ad_diagnosis'
        adData.value = {
          overall_score: data.overall_score,
          grade: data.grade,
          metrics: data.metrics || [],
          campaigns: data.campaigns || [],
          top_issues: data.top_issues || [],
          recommendations: data.recommendations || [],
        }

        // 同时生成报告
        let adReport = `## 📊 广告账户诊断报告\n\n`
        adReport += `**综合评分**: ${data.overall_score}/100（等级：**${data.grade}**）\n\n`

        if (data.metrics) {
          adReport += `### 核心指标\n\n`
          adReport += `| 指标 | 当前值 | 基准 | 状态 |\n|------|--------|------|------|\n`
          data.metrics.forEach((m: any) => {
            const statusIcon = m.status === 'good' ? '✅' : m.status === 'warning' ? '⚠️' : '❌'
            adReport += `| ${m.name} | ${m.value}${m.unit} | ${m.benchmark}${m.unit} | ${statusIcon} |\n`
          })
        }

        if (data.campaigns?.length) {
          adReport += `\n### Campaign 健康度\n\n`
          adReport += `| Campaign | 类型 | 花费 | ACoS | RoAS | 健康分 |\n|----------|------|------|------|------|--------|\n`
          data.campaigns.forEach((c: any) => {
            adReport += `| ${c.campaign_name} | ${c.campaign_type} | $${c.spend.toFixed(0)} | ${c.acos}% | ${c.roas}x | ${c.health_score} |\n`
          })
        }

        if (data.top_issues?.length) {
          adReport += `\n### ⚠️ 主要问题\n\n`
          data.top_issues.slice(0, 5).forEach((issue: any, i: number) => {
            adReport += `${i + 1}. **${issue.title}**: ${issue.description}\n`
          })
        }

        if (data.recommendations?.length) {
          adReport += `\n### 💡 优化建议\n\n`
          data.recommendations.forEach((rec: string) => {
            adReport += `- ${rec}\n`
          })
        }

        setReportContent(adReport)
        rawData.value = data
        break

      case 'order_info':
        // 订单信息：专用可视化
        contentType.value = 'order_info'
        orderData.value = {
          order_id: data.order_id,
          status: data.status,
          status_text: data.status_text,
          product_name: data.product_name,
          total: data.total,
          created_at: data.created_at,
          tracking_number: data.tracking_number,
          carrier: data.carrier,
          estimated_delivery: data.estimated_delivery,
        }
        break

      case 'ticket':
      case 'ticket_prompt':
      case 'escalation_notice':
        // 工单信息：专用可视化
        contentType.value = 'ticket'
        const ticket = data.ticket || data
        ticketData.value = {
          ticket_id: ticket.ticket_id,
          subject: ticket.subject || data.subject,
          category: ticket.category || data.category,
          priority: ticket.priority || data.priority,
          status: ticket.status || 'open',
          created_at: ticket.created_at,
          sla_deadline: ticket.sla_deadline,
          auto_replies: ticket.auto_replies || data.auto_replies || [],
        }
        break

      case 'monitor_dashboard':
      case 'single_monitor':
        // 竞品监控：专用可视化
        contentType.value = 'competitor_monitor'
        competitorData.value = {
          type: data.type,
          competitors: data.competitors,
          summary: data.summary,
          product: data.product,
          price_trend: data.price_trend,
          ranking_trend: data.ranking_trend,
          analysis: data.analysis,
        }
        rawData.value = data
        break

      case 'market_share':
        // 市场份额分析：专用可视化
        contentType.value = 'market_share'
        marketShareData.value = {
          category: data.category,
          total_market_estimate: data.total_market_estimate,
          competitors: data.competitors,
          insights: data.insights,
          concentration_ratio: data.concentration_ratio,
        }

        // 生成报告
        let msReport = `## 🌍 市场格局分析\n\n`
        msReport += `**类目**: ${data.category}\n\n`
        msReport += `**预估市场规模**: $${(data.total_market_estimate / 1000).toFixed(1)}K/月\n\n`

        if (data.competitors?.length) {
          msReport += `### 品牌市场份额\n\n`
          msReport += `| 品牌 | 市场份额 | BSR排名 | 月营收估算 | 趋势 |\n|------|---------|---------|-----------|------|\n`
          data.competitors.forEach((c: any) => {
            const trendIcon = c.trend === 'rising' ? '📈' : c.trend === 'declining' ? '📉' : '➡️'
            msReport += `| ${c.brand_name} | ${c.estimated_market_share}% | #${c.bsr_rank} | $${(c.revenue_estimate / 1000).toFixed(1)}K | ${trendIcon} |\n`
          })
        }

        if (data.concentration_ratio) {
          msReport += `\n### 市场集中度\n\n`
          msReport += `- **CR4（前4名集中度）**: ${data.concentration_ratio.CR4}%\n`
          msReport += `- **HHI（赫芬达尔指数）**: ${data.concentration_ratio.HHI}\n`
          msReport += `- **市场类型**: ${data.concentration_ratio.market_type === 'competitive' ? '竞争型' : data.concentration_ratio.market_type === 'high_concentration' ? '高集中度' : '中度集中'}\n`
        }

        if (data.insights?.length) {
          msReport += `\n### 💡 关键洞察\n\n`
          data.insights.forEach((insight: string) => {
            msReport += `- ${insight}\n`
          })
        }

        setReportContent(msReport)
        rawData.value = data
        break

      case 'pricing_strategy':
        // 定价策略：报告 + 数据
        contentType.value = 'pricing_strategy'

        let pricingReport = `## 💵 定价策略分析\n\n`
        if (data.strategies?.length) {
          data.strategies.forEach((s: any, i: number) => {
            const typeNames: Record<string, string> = {
              premium: '高端定价',
              economy: '经济型定价',
              competitive: '竞争导向定价',
              dynamic: '动态定价',
            }
            pricingReport += `### ${i + 1}. ${s.strategy_type in typeNames ? typeNames[s.strategy_type] : s.strategy_type}\n\n`
            pricingReport += `- **均价**: $${s.base_price}\n`
            pricingReport += `- **平均折扣**: ${s.avg_discount}%\n`
            pricingReport += `- **促销频率**: ${s.promo_frequency === 'high' ? '高' : s.promo_frequency === 'medium' ? '中' : '低'}\n`
            pricingReport += `- **价格弹性**: ${s.price_elasticity}\n`
            pricingReport += `- **价格波动率**: ${s.price_volatility}%\n\n`

            if (s.recommendations?.length) {
              pricingReport += `**建议**:\n`
              s.recommendations.forEach((r: string) => {
                pricingReport += `- ${r}\n`
              })
              pricingReport += '\n'
            }
          })
        }

        setReportContent(pricingReport)
        rawData.value = data
        break

      case 'review_analysis':
        // 评论分析：报告 + SWOT
        contentType.value = 'review_analysis'

        let reviewReport = `## 📝 竞品评论深度分析\n\n`
        if (data.analyses?.length) {
          data.analyses.forEach((a: any) => {
            reviewReport += `### ${a.brand} - ${a.product}\n\n`
            reviewReport += `**综合评分**: ⭐${a.overall_rating} (${a.total_reviews} 条评论)\n\n`

            if (a.swot) {
              reviewReport += `**SWOT 分析**:\n\n`
              reviewReport += `✅ 优势: ${a.swot.strengths.join(', ')}\n`
              reviewReport += `❌ 劣势: ${a.swot.weaknesses.join(', ')}\n\n`
            }

            if (a.actionable_intelligence?.length) {
              reviewReport += `**可行动情报**:\n\n`
              a.actionable_intelligence.forEach((intel: string) => {
                reviewReport += `- ${intel}\n`
              })
              reviewReport += '\n'
            }
          })
        }

        setReportContent(reviewReport)
        rawData.value = data
        break

      case 'intruder_detection':
        // 入侵者检测：专用可视化 + 警报
        contentType.value = 'intruder_detection'
        intruderData.value = {
          category: data.category,
          detection_date: data.detection_date,
          new_competitors: data.new_competitors,
          threat_summary: data.threat_summary,
          response_strategies: data.response_strategies,
        }

        let intruderReport = `## 🚨 新竞争者入侵警报\n\n`
        intruderReport += `**检测时间**: ${data.detection_date}\n`
        intruderReport += `**监控类目**: ${data.category}\n\n`

        if (data.threat_summary) {
          intruderReport += `### 威胁概览\n\n`
          intruderReport += `- 🔴 高威胁: ${data.threat_summary.high_threat || 0} 个\n`
          intruderReport += `- 🟡 中等威胁: ${data.threat_summary.medium_threat || 0} 个\n`
          intruderReport += `- 🟢 低威胁: ${data.threat_summary.low_threat || 0} 个\n\n`
        }

        if (data.new_competitors?.length) {
          intruderReport += `### 新进入者详情\n\n`
          data.new_competitors.forEach((intruder: any) => {
            const threatIcon = intruder.threat_level === 'high' ? '🔴' : intruder.threat_level === 'medium' ? '🟡' : '🟢'
            intruderReport += `${threatIcon} **${intruder.brand}** (${intruder.asin})\n`
            intruderReport += `   - 价格: $${intruder.price} | 进入日期: ${intruder.entry_date}\n`
            intruderReport += `   - 原因: ${intruder.reasons.slice(0, 2).join('、')}\n\n`
          })
        }

        if (data.response_strategies?.length) {
          intruderReport += `### 📋 应对策略\n\n`
          data.response_strategies.slice(0, 3).forEach((s: any) => {
            intruderReport += `- **[${s.priority}]** ${s.actions.slice(0, 2).join('、')}\n`
          })
        }

        setReportContent(intruderReport)
        rawData.value = data
        break

      case 'buy_box_analysis':
        // Buy Box 分析：报告 + 数据
        contentType.value = 'buy_box_analysis'

        let bbReport = `## 🛒 Buy Box 竞争分析\n\n`
        if (data.analyses?.length) {
          data.analyses.forEach((a: any) => {
            bbReport += `### ${a.brand} - ${a.product}\n\n`
            const bb = a.buy_box_analysis
            if (bb) {
              bbReport += `- **当前赢家**: ${bb.current_winner}\n`
              bbReport += `- **赢取价格**: $${bb.winning_price}\n`
              bbReport += `- **Buy Box 占有率**: ${bb.buy_box_percentage}%\n`
              bbReport += `- **竞争力得分**: ${a.competitiveness_score}/100\n`
              bbReport += `- **需降价至**: $${bb.price_to_win} 才能赢取\n\n`
            }
          })
        }

        if (data.best_practices?.length) {
          bbReport += `### ✅ Buy Box 最佳实践\n\n`
          data.best_practices.forEach((bp: string) => {
            bbReport += `${bp}\n`
          })
        }

        setReportContent(bbReport)
        rawData.value = data
        break

      case 'competitor_comparison':
        // 竞品对比：表格 + 报告
        contentType.value = 'competitor_comparison'

        if (data.comparison) {
          const comp = data.comparison

          // 生成对比表格
          if (comp.overall_ranking?.length) {
            setTableData(
              comp.overall_ranking.map((r: any) => ({
                key: r.asin,
                ...r,
              })),
              [
                { title: '排名', dataIndex: 'rank', key: 'rank' },
                { title: '品牌', dataIndex: 'brand', key: 'brand' },
                { title: 'ASIN', dataIndex: 'asin', key: 'asin' },
                { title: '综合得分', dataIndex: 'overall_score', key: 'overall_score' },
              ]
            )
          }

          // 生成对比报告
          let compReport = `## ⚔️ 竞品多维度对比\n\n`
          compReport += `**参与对比**: ${data.compared_count} 个产品\n\n`

          if (comp.value_score?.length) {
            compReport += `### 性价比排行\n\n`
            compReport += `| 排名 | 品牌 | 性价比分 | 评分 | 价格 |\n|------|------|---------|------|------|\n`
            comp.value_score.forEach((v: any, i: number) => {
              compReport += `| ${i + 1} | ${v.brand} | ${v.value_score} | ⭐${v.rating} | $${v.price} |\n`
            })
          }

          if (comp.recommendations?.length) {
            compReport += `\n### 💡 对比结论\n\n`
            comp.recommendations.forEach((r: string) => {
              compReport += `- ${r}\n`
            })
          }

          if (comp.differentiation_analysis?.gap_opportunities?.length) {
            compReport += `\n### 🎯 市场空白机会\n\n`
            comp.differentiation_analysis.gap_opportunities.forEach((g: string) => {
              compReport += `- ${g}\n`
            })
          }

          setReportContent(compReport)
        }

        rawData.value = data
        break

      case 'generated_image':
        // AI 生成图片：专用可视化
        contentType.value = 'generated_image'
        generatedImageData.value = {
          image_id: data.image_id,
          prompt: data.prompt,
          image_type: data.image_type,
          style: data.style,
          description: data.description,
          suggested_captions: data.suggested_captions,
          seo_keywords: data.seo_keywords,
          usage_tips: data.usage_tips,
          variation_suggestions: data.variation_suggestions,
          style_guide: data.style_guide,
        }
        break

      case 'main_image_analysis':
        // 主图分析：专用可视化 + 报告
        contentType.value = 'main_image_analysis'
        mainImageAnalysisData.value = {
          overall_score: data.overall_score,
          ctr_prediction: data.ctr_prediction,
          visual_appeal: data.visual_appeal,
          compliance_check: data.compliance_check,
          improvement_suggestions: data.improvement_suggestions,
          ab_test_variants: data.ab_test_variants,
        }

        // 生成分析报告
        let miaReport = `## 🖼️ 主图质量诊断报告\n\n`
        miaReport += `**综合评分**: ${data.overall_score}/100\n\n`
        miaReport += `**预估 CTR**: ${(data.ctr_prediction * 100).toFixed(1)}%\n\n`

        if (data.visual_appeal) {
          miaReport += `### 视觉吸引力\n\n`
          miaReport += `| 维度 | 得分 |\n|------|------|\n`
          Object.entries(data.visual_appeal).forEach(([key, value]: [string, any]) => {
            const names: Record<string, string> = {
              visual_appeal: '视觉吸引力',
              clarity: '清晰度',
              color_quality: '色彩质量',
              composition: '构图',
              brand_presence: '品牌呈现',
            }
            miaReport += `| ${names[key] || key} | ${value}/100 |\n`
          })
        }

        if (data.compliance_check) {
          const cc = data.compliance_check
          miaReport += `\n### ✅ 合规检查 (${cc.passed?.length || 0}/${(cc.passed?.length || 0) + (cc.issues?.length || 0)} 通过)\n\n`
          if (cc.issues?.length) {
            cc.issues.forEach((issue: any) => {
              const icon = issue.severity === 'critical' ? '🚫' : issue.severity === 'warning' ? '⚠️' : '✅'
              miaReport += `${icon} ${issue.check}: ${issue.suggestion}\n`
            })
          }
        }

        if (data.improvement_suggestions?.length) {
          miaReport += `\n### 💡 优化建议\n\n`
          data.improvement_suggestions.forEach((s: string, i: number) => {
            miaReport += `${i + 1}. ${s}\n`
          })
        }

        if (data.ab_test_variants?.length) {
          miaReport += `\n### 🧪 A/B 测试变体\n\n`
          data.ab_test_variants.forEach((v: any) => {
            miaReport += `- **${v.variant}**: ${v.description} (预估CTR: ${(v.predicted_ctr * 100).toFixed(1)}%)\n`
          })
        }

        setReportContent(miaReport)
        rawData.value = data
        break

      case 'a_plus_content':
        // A+ 内容：专用可视化 + 报告
        contentType.value = 'a_plus_content'
        aPlusContentData.value = {
          product_asin: data.product_asin,
          brand_name: data.brand_name,
          modules: data.modules,
          total_modules: data.total_modules,
          estimated_read_time: data.estimated_read_time,
          optimization_tips: data.optimization_tips,
        }

        let apcReport = `## 📝 A+/EBC 内容生成完成\n\n`
        apcReport += `**产品 ASIN**: ${data.product_asin}\n`
        apcReport += `**品牌**: ${data.brand_name}\n`
        apcReport += `**模块数量**: ${data.total_modules}\n`
        apcReport += `**预计阅读时间**: ${Math.floor((data.estimated_read_time || 0) / 60)}分${((data.estimated_read_time || 0) % 60)}秒\n\n`

        if (data.modules?.length) {
          apcReport += `### 内容模块\n\n`
          data.modules.forEach((m: any, i: number) => {
            apcReport += `#### 模块 ${i + 1}: ${m.title}\n\n`
            apcReport += `- **类型**: ${m.module_type}\n`
            apcReport += `- **字数**: ~${m.character_count} 字\n`
            apcReport += `- **需要图片**: ${m.images_needed} 张\n`
            apcReport += `- **SEO 评分**: ${m.seo_score}/100\n`
            apcReport += `\n**内容预览**:\n${m.content.slice(0, 200)}...\n\n`
          })
        }

        if (data.optimization_tips?.length) {
          apcReport += `### ✨ 优化建议\n\n`
          data.optimization_tips.forEach((t: string) => {
            apcReport += `- ${t}\n`
          })
        }

        setReportContent(apcReport)
        rawData.value = data
        break

      case 'brand_story':
        // 品牌故事：报告展示
        contentType.value = 'brand_story'
        brandStoryData.value = {
          brand_name: data.brand_name,
          brand_positioning: data.brand_positioning,
          brand_mission: data.brand_mission,
          brand_values: data.brand_values,
          origin_story: data.origin_story,
          unique_selling_proposition: data.unique_selling_proposition,
          tagline_options: data.tagline_options,
          about_brand_text: data.about_brand_text,
          storytelling_angles: data.storytelling_angles,
        }

        let bsReport = `## 🏆 品牌故事文案\n\n`
        bsReport += `**品牌**: ${data.brand_name}\n\n`
        bsReport += `### 品牌定位\n\n${data.brand_positioning}\n\n`
        bsReport += `### 品牌使命\n\n${data.brand_mission}\n\n`
        bsReport += `### 核心价值观\n\n`
        data.brand_values?.forEach((v: string) => {
          bsReport += `- ${v}\n`
        })
        bsReport += `\n### 起源故事\n\n${data.origin_story}\n\n`
        bsReport += `### 独特卖点 (USP)\n\n${data.unique_selling_proposition}\n\n`

        if (data.tagline_options?.length) {
          bsReport += `### Slogan 建议\n\n`
          data.tagline_options.forEach((t: string, i: number) => {
            bsReport += `${i + 1}. ${t}\n`
          })
        }

        if (data.about_brand_text) {
          bsReport += `\n### 完整 About 描述（可用于 Amazon Store）\n\n${data.about_brand_text}\n`
        }

        setReportContent(bsReport)
        rawData.value = data
        break

      case 'translation':
        // 翻译结果：对比展示
        contentType.value = 'translation'
        translationData.value = {
          original_text: data.original_text,
          translated_text: data.translated_text,
          source_lang: data.source_lang,
          target_lang: data.target_lang,
          seo_optimized: data.seo_optimized,
          keyword_inclusion: data.keyword_inclusion,
          cultural_notes: data.cultural_notes,
          alternative_versions: data.alternative_versions,
        }

        let transReport = `## 🌍 翻译结果\n\n`
        transReport += `**原文** (${data.source_lang}):\n> ${data.original_text}\n\n`
        transReport += `**译文** (${data.target_lang}):\n> ${data.translated_text}\n\n`
        transReport += `**SEO 优化**: ${data.seo_optimized ? '✅ 已优化' : '❌ 未优化'}\n\n`

        if (data.keyword_inclusion?.length) {
          transReport += `### 关键词保留情况\n\n`
          transReport += `| 关键词 | 位置 |\n|--------|------|\n`
          data.keyword_inclusion.forEach((k: any) => {
            transReport += `| ${k.keyword} | ${k.position} |\n`
          })
        }

        if (data.cultural_notes?.length) {
          transReport += `\n### 📌 文化注意事项\n\n`
          data.cultural_notes.forEach((note: string) => {
            transReport += `- ${note}\n`
          })
        }

        if (data.alternative_versions?.length) {
          transReport += `\n### 📝 替代版本\n\n`
          data.alternative_versions.forEach((v: any) => {
            transReport += `- **${v.version}**: ${v.text}\n`
          })
        }

        setReportContent(transReport)
        rawData.value = data
        break

      case 'compliance_report':
        // 合规检查报告：专用可视化
        contentType.value = 'compliance_report'
        complianceReportData.value = {
          overall_status: data.overall_status,
          score: data.score,
          issues: data.issues,
          passed_checks: data.passed_checks,
          recommendations: data.recommendations,
        }

        let crReport = `## ✅ 图片合规检查报告\n\n`
        const statusIcon = data.overall_status === 'pass' ? '✅ 通过' : data.overall_status === 'warning' ? '⚠️ 警告' : '🚫 不通过'
        crReport += `**总体状态**: ${statusIcon}\n`
        crReport += `**得分**: ${data.score}/100\n\n`

        if (data.passed_checks?.length) {
          crReport += `### ✅ 通过项 (${data.passed_checks.length})\n\n`
          data.passed_checks.slice(0, 8).forEach((check: string) => {
            crReport += `- ${check}\n`
          })
          if (data.passed_checks.length > 8) {
            crReport += `- ...等 ${data.passed_checks.length} 项\n`
          }
        }

        if (data.issues?.length) {
          crReport += `\n### ❌ 问题项 (${data.issues.length})\n\n`
          data.issues.forEach((issue: any) => {
            const icon = issue.severity === 'critical' ? '🚫' : '⚠️'
            crReport += `${icon} **[${issue.issue_type}]** ${issue.affected_area}\n`
            crReport += `   - ${issue.description}\n`
            crReport += `   - 💡 ${issue.suggestion}\n\n`
          })
        }

        if (data.recommendations?.length) {
          crReport += `### 💡 建议\n\n`
          data.recommendations.forEach((r: string) => {
            crReport += `- ${r}\n`
          })
        }

        setReportContent(crReport)
        rawData.value = data
        break

      case 'video_script':
        // 视频脚本：分镜展示
        contentType.value = 'video_script'
        videoScriptData.value = {
          title: data.title,
          total_duration: data.total_duration,
          format: data.format,
          target_platform: data.target_platform,
          scenes: data.scenes,
          hook_lines: data.hook_lines,
          cta_suggestions: data.cta_suggestions,
          hashtag_recommendations: data.hashtag_recommendations,
          production_notes: data.production_notes,
        }

        let vsReport = `## 🎬 视频脚本\n\n`
        vsReport += `**标题**: ${data.title}\n`
        vsReport += `**总时长**: ${data.total_duration}秒 | **平台**: ${data.target_platform}\n\n`

        if (data.scenes?.length) {
          vsReport += `### 分镜头脚本\n\n`
          data.scenes.forEach((scene: any) => {
            vsReport += `#### 场景 ${scene.scene_number} (${scene.duration}s)\n\n`
            vsReport += `- **画面**: ${scene.visual_description}\n`
            vsReport += `- **字幕**: ${scene.text_overlay}\n`
            vsReport += `- **配音**: ${scene.voiceover}\n`
            vsReport += `- **音乐**: ${scene.background_music}\n`
            vsReport += `- **转场**: ${scene.transition}\n\n`
          })
        }

        if (data.hook_lines?.length) {
          vsReport += `### 🎯 黄金3秒钩子备选\n\n`
          data.hook_lines.forEach((h: string, i: number) => {
            vsReport += `${i + 1}. ${h}\n`
          })
        }

        if (data.cta_suggestions?.length) {
          vsReport += `\n ### 📢 CTA 引导建议\n\n`
          data.cta_suggestions.forEach((cta: string) => {
            vsReport += `- ${cta}\n`
          })
        }

        if (data.hashtag_recommendations?.length) {
          vsReport += `\n### #️⃣ 推荐话题标签\n\n`
          vsReport += `${data.hashtag_recommendations.join(' ')}\n`
        }

        if (data.production_notes?.length) {
          vsReport += `\n### 📋 制作备注\n\n`
          data.production_notes.forEach((note: string) => {
            vsReport += `- ${note}\n`
          })
        }

        setReportContent(vsReport)
        rawData.value = data
        break

      default:
        // 默认：显示 JSON
        setRawData(data)
    }
  }

  // 清空所有内容
  const clear = () => {
    contentType.value = null
    tableData.value = []
    tableColumns.value = []
    reportContent.value = ''
    imageSrc.value = ''
    codeContent.value = ''
    rawData.value = null
    listingData.value = null
    profitData.value = null
    adData.value = null
    orderData.value = null
    ticketData.value = null
    competitorData.value = null
    marketShareData.value = null
    intruderData.value = null
    generatedImageData.value = null
    mainImageAnalysisData.value = null
    aPlusContentData.value = null
    brandStoryData.value = null
    translationData.value = null
    complianceReportData.value = null
    videoScriptData.value = null
  }

  return {
    contentType,
    hasContent,
    tableData,
    tableColumns,
    reportContent,
    imageSrc,
    codeContent,
    rawData,
    listingData,
    profitData,
    adData,
    orderData,
    ticketData,
    competitorData,
    marketShareData,
    intruderData,
    generatedImageData,
    mainImageAnalysisData,
    aPlusContentData,
    brandStoryData,
    translationData,
    complianceReportData,
    videoScriptData,
    setTableData,
    setReportContent,
    setImage,
    setCode,
    setRawData,
    clear,
  }
})
