<template>
  <div class="smart-panel">
    <div class="panel-header">
      <h4>展示区</h4>
      <a-button
        type="text"
        size="small"
        @click="handleClear"
        :disabled="!hasContent"
      >
        清空
      </a-button>
    </div>

    <!-- 空状态 -->
    <div v-if="!hasContent" class="empty-state">
      <AppstoreOutlined style="font-size: 48px; color: #d9d9d9; margin-bottom: 16px" />
      <p>暂无展示内容</p>
      <p class="hint">Agent 返回的结构化数据将在此处展示</p>
    </div>

    <!-- 智能自适应内容 -->
    <div v-else class="panel-content">
      <!-- 表格数据 -->
      <template v-if="contentType === 'table' && tableData">
        <a-table
          :columns="tableColumns"
          :data-source="tableData"
          :pagination="{ pageSize: 10, size: 'small' }"
          size="small"
          :scroll="{ y: 400 }"
        />
      </template>

      <!-- 图表（TODO: 集成 ECharts）-->
      <template v-else-if="contentType === 'chart'">
        <div class="chart-placeholder">
          <LineChartOutlined style="font-size: 32px; color: #1890ff" />
          <p>图表展示区域</p>
          <p class="hint">（待集成 ECharts）</p>
        </div>
      </template>

      <!-- 报告文档 -->
      <template v-else-if="contentType === 'report'">
        <div class="report-content" v-html="renderMarkdown(reportContent)"></div>
      </template>

      <!-- 图片预览 -->
      <template v-else-if="contentType === 'image'">
        <a-image :src="imageSrc" :preview="{ visible: true }" />
      </template>

      <!-- 代码块 -->
      <template v-else-if="contentType === 'code'">
        <pre class="code-block"><code>{{ codeContent }}</code></pre>
      </template>

      <!-- 利润测算分析 -->
      <template v-else-if="contentType === 'profit_analysis' && profitData">
        <div class="profit-analysis">
          <!-- 核心指标卡片 -->
          <div class="profit-kpi-grid">
            <div class="kpi-card kpi-profit" :class="{ negative: (profitData?.net_profit ?? 0) <= 0 }">
              <span class="kpi-label">净利/件</span>
              <span class="kpi-value">${{ profitData?.net_profit?.toFixed(2) || '0.00' }}</span>
            </div>
            <div class="kpi-card kpi-roi">
              <span class="kpi-label">ROI</span>
              <a-tag :color="getRoiColor(profitData.roi)" class="kpi-value-tag">
                {{ profitData.roi?.toFixed(1) || '0' }}%
              </a-tag>
            </div>
            <div class="kpi-card kpi-margin">
              <span class="kpi-label">利润率</span>
              <span class="kpi-value">{{ profitData.profit_margin?.toFixed(1) || '0' }}%</span>
            </div>
            <div class="kpi-card kpi-breakeven">
              <span class="kpi-label">盈亏平衡</span>
              <span class="kpi-value">{{ profitData.breakeven_quantity || 0 }} 件/月</span>
            </div>
          </div>

          <!-- 费用结构 -->
          <div class="fee-structure" v-if="profitData.fee_breakdown">
            <h4 class="section-title">💰 费用结构分析</h4>
            <div class="fee-list">
              <div
                v-for="(fee, idx) in profitData.fee_breakdown"
                :key="idx"
                class="fee-item"
              >
                <span class="fee-name">{{ fee.name }}</span>
                <div class="fee-bar-wrapper">
                  <div
                    class="fee-bar"
                    :style="{
                      width: `${(fee.amount / (profitData.price || 1)) * 100}%`,
                      backgroundColor: getFeeColor(idx),
                    }"
                  ></div>
                </div>
                <span class="fee-amount">${{ fee.amount?.toFixed(2) }}</span>
                <span class="fee-percent">{{ ((fee.amount / (profitData.price || 1)) * 100).toFixed(1) }}%</span>
              </div>
            </div>
          </div>

          <!-- 月度利润预估 -->
          <div class="monthly-projection" v-if="profitData.monthly_projection">
            <h4 class="section-title">📈 月度利润预估</h4>
            <a-table
              :columns="projectionColumns"
              :data-source="profitData.monthly_projection"
              size="small"
              :pagination="false"
            />
          </div>

          <!-- 敏感性分析 -->
          <div class="sensitivity" v-if="profitData.sensitivity_analysis">
            <h4 class="section-title">🎯 敏感性分析</h4>
            <div class="sensitivity-list">
              <div
                v-for="(item, idx) in profitData.sensitivity_analysis"
                :key="idx"
                class="sensitivity-item"
              >
                <span>{{ item.scenario }}</span>
                <span :class="['sensitivity-value', item.roi >= 20 ? 'positive' : 'negative']">
                  ROI {{ item.roi?.toFixed(1) }}%
                </span>
                <span :class="['sensitivity-value', item.net_profit > 0 ? 'positive' : 'negative']">
                  ${{ item.net_profit?.toFixed(2) }}/件
                </span>
              </div>
            </div>
          </div>

          <!-- 建议 -->
          <div class="recommendations" v-if="profitData.recommendations?.length">
            <h4 class="section-title">💡 优化建议</h4>
            <ul class="rec-list">
              <li v-for="(rec, idx) in profitData.recommendations" :key="idx">{{ rec }}</li>
            </ul>
          </div>
        </div>
      </template>

      <!-- 广告诊断分析 -->
      <template v-else-if="contentType === 'ad_diagnosis' && adData">
        <div class="ad-diagnosis">
          <!-- 综合评分卡片 -->
          <div class="diagnosis-score-card" :class="`grade-${(adData.grade || 'F').toLowerCase()}`">
            <div class="score-main">
              <span class="score-label">广告健康评分</span>
              <span class="score-value">{{ adData.overall_score ?? 0 }}/100</span>
              <span class="grade-badge">等级: {{ adData.grade || 'F' }}</span>
            </div>
          </div>

          <!-- 核心指标 -->
          <div class="ad-metrics" v-if="adData.metrics?.length">
            <h4 class="section-title">📊 核心指标</h4>
            <div class="metrics-grid">
              <div
                v-for="(metric, idx) in adData.metrics"
                :key="idx"
                :class="['metric-item', `status-${metric.status}`]"
              >
                <span class="metric-name">{{ metric.name }}</span>
                <span class="metric-value">{{ metric.value }}{{ metric.unit }}</span>
                <span class="metric-benchmark">基准: {{ metric.benchmark }}{{ metric.unit }}</span>
                <span class="metric-status-icon">{{ metric.status === 'good' ? '✅' : '⚠️' }}</span>
              </div>
            </div>
          </div>

          <!-- Campaign 健康度表格 -->
          <div class="campaign-table" v-if="adData.campaigns?.length">
            <h4 class="section-title">🎯 Campaign 健康度</h4>
            <a-table
              :dataSource="adData.campaigns.map((c, i) => ({ ...c, key: i }))"
              size="small"
              :pagination="false"
              :scroll="{ y: 200 }"
            >
              <a-table-column title="Campaign" dataIndex="campaign_name" :ellipsis="true" />
              <a-table-column title="类型" dataIndex="campaign_type" width="55" align="center" />
              <a-table-column title="花费" dataIndex="spend" width="65" align="right">
                <template #default="{ text }">${{ Number(text).toFixed(0) }}</template>
              </a-table-column>
              <a-table-column title="ACoS" dataIndex="acos" width="60" align="center">
                <template #default="{ text }">
                  <a-tag :color="Number(text) > 30 ? 'red' : Number(text) > 20 ? 'orange' : 'green'">
                    {{ Number(text).toFixed(1) }}%
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="RoAS" dataIndex="roas" width="60" align="right" />
              <a-table-column title="健康分" dataIndex="health_score" width="70" align="center">
                <template #default="{ text }">
                  <a-progress
                    :percent="Number(text)"
                    :show-info="false"
                    :stroke-color="Number(text) >= 70 ? '#52c41a' : Number(text) >= 50 ? '#faad14' : '#ff4d4f'"
                    size="small"
                  />
                </template>
              </a-table-column>
            </a-table>
          </div>

          <!-- 问题列表 -->
          <div class="issues-list" v-if="adData.top_issues?.length">
            <h4 class="section-title">⚠️ 主要问题</h4>
            <a-collapse ghost>
              <a-collapse-panel v-for="(issue, idx) in adData.top_issues.slice(0, 5)" :key="idx" :header="issue.title">
                <p>{{ issue.description }}</p>
                <a-tag :color="issue.priority === 'high' ? 'red' : 'orange'" size="small">
                  {{ issue.priority === 'high' ? '高优先级' : '中优先级' }}
                </a-tag>
              </a-collapse-panel>
            </a-collapse>
          </div>

          <!-- 建议 -->
          <div class="recommendations" v-if="adData.recommendations?.length">
            <h4 class="section-title">💡 优化建议</h4>
            <ul class="rec-list">
              <li v-for="(rec, idx) in adData.recommendations.slice(0, 6)" :key="idx">{{ rec }}</li>
            </ul>
          </div>
        </div>
      </template>

      <!-- Listing 预览 -->
      <template v-else-if="contentType === 'listing' && listingData">
        <div class="listing-preview">
          <!-- SEO 评分卡片 -->
          <div class="seo-score-card" v-if="listingData.seo_score">
            <div class="score-header">
              <span class="score-label">SEO 综合评分</span>
              <span :class="['score-value', getScoreClass(listingData.seo_score.overall_score)]">
                {{ listingData.seo_score.overall_score }}/100
              </span>
            </div>
            <a-progress
              :percent="listingData.seo_score.overall_score"
              :stroke-color="getProgressColor(listingData.seo_score.overall_score)"
              :show-info="false"
            />
            <div class="score-breakdown">
              <span>标题: {{ listingData.seo_score.title_score }}</span>
              <span>五点: {{ listingData.seo_score.bullet_score }}</span>
              <span>描述: {{ listingData.seo_score.description_score }}</span>
              <span>关键词: {{ listingData.seo_score.keywords_score }}</span>
            </div>
          </div>

          <!-- 标题区域 -->
          <div class="listing-section" v-if="listingData.title">
            <h4 class="section-title">📝 标题 (Title)</h4>
            <div class="title-content">{{ listingData.title.title }}</div>
            <div class="title-meta">
              <a-tag color="blue">{{ listingData.title.character_count }} 字符</a-tag>
              <a-tag color="green">SEO: {{ listingData.title.seo_score }}</a-tag>
            </div>
          </div>

          <!-- 五点描述区域 -->
          <div class="listing-section" v-if="listingData.bullet_points?.bullets">
            <h4 class="section-title">📋 五点描述 (Bullet Points)</h4>
            <div class="bullets-list">
              <div
                v-for="bullet in listingData.bullet_points.bullets"
                :key="bullet.bullet_id"
                class="bullet-item"
              >
                <div class="bullet-header">{{ bullet.title }}</div>
                <div class="bullet-content">{{ bullet.content }}</div>
              </div>
            </div>
          </div>

          <!-- 产品描述区域 -->
          <div class="listing-section" v-if="listingData.description">
            <h4 class="section-title">📄 产品描述 (Description)</h4>
            <div class="description-content">{{ listingData.description.plain_text?.slice(0, 500) }}...</div>
          </div>

          <!-- 后台关键词区域 -->
          <div class="listing-section" v-if="listingData.search_terms">
            <h4 class="section-title">🔑 后台关键词 (Search Terms)</h4>
            <div class="keywords-content">
              <a-tag v-for="(term, idx) in listingData.search_terms.terms.slice(0, 15)" :key="idx">
                {{ term }}
              </a-tag>
            </div>
            <div class="keywords-meta">
              <a-tag :color="listingData.search_terms.is_valid ? 'success' : 'error'">
                {{ listingData.search_terms.total_bytes }}/250 字节
              </a-tag>
            </div>
          </div>
        </div>
      </template>

      <!-- 订单信息 -->
      <template v-else-if="contentType === 'order_info' && orderData">
        <div class="order-info">
          <h3 class="panel-title">📦 订单详情</h3>

          <div class="order-status-badge" :class="`status-${orderData.status}`">
            {{ orderData.status_text || orderData.status }}
          </div>

          <a-descriptions :column="1" size="small" bordered>
            <a-descriptions-item label="订单号">
              <code>{{ orderData.order_id }}</code>
            </a-descriptions-item>
            <a-descriptions-item label="商品">{{ orderData.product_name }}</a-descriptions-item>
            <a-descriptions-item label="金额">${{ orderData.total }}</a-descriptions-item>
            <a-descriptions-item label="下单时间">{{ orderData.created_at }}</a-descriptions-item>
          </a-descriptions>

          <!-- 物流信息 -->
          <div v-if="orderData.tracking_number" class="tracking-info">
            <h4>🚚 物流信息</h4>
            <a-descriptions :column="1" size="small">
              <a-descriptions-item label="快递单号">
                <code>{{ orderData.tracking_number }}</code>
              </a-descriptions-item>
              <a-descriptions-item label="承运商">{{ orderData.carrier }}</a-descriptions-item>
              <a-descriptions-item label="预计送达">{{ orderData.estimated_delivery }}</a-descriptions-item>
            </a-descriptions>
          </div>
        </div>
      </template>

      <!-- 工单信息 -->
      <template v-else-if="contentType === 'ticket' && ticketData">
        <div class="ticket-info">
          <h3 class="panel-title">🎫 工单详情</h3>

          <div class="ticket-header">
            <span class="ticket-id">{{ ticketData.ticket_id }}</span>
            <a-tag :color="getPriorityColor(ticketData.priority)">{{ ticketData.priority }}</a-tag>
            <a-tag :color="getStatusColor(ticketData.status)">{{ ticketData.status }}</a-tag>
          </div>

          <a-descriptions :column="1" size="small" bordered>
            <a-descriptions-item label="标题">{{ ticketData.subject }}</a-descriptions-item>
            <a-descriptions-item label="分类">{{ ticketData.category }}</a-descriptions-item>
            <a-descriptions-item label="创建时间">{{ ticketData.created_at }}</a-descriptions-item>
            <a-descriptions-item label="SLA 响应时间">{{ ticketData.sla_deadline ? '预计 ' + ticketData.sla_deadline.slice(0, 10) : '-' }}</a-descriptions-item>
          </a-descriptions>

          <div v-if="ticketData.auto_replies?.length" class="auto-replies">
            <h4>💬 自动回复</h4>
            <ul>
              <li v-for="(reply, idx) in ticketData.auto_replies" :key="idx">{{ reply }}</li>
            </ul>
          </div>
        </div>
      </template>

      <!-- 竞品监控仪表盘 -->
      <template v-else-if="contentType === 'competitor_monitor' && competitorData">
        <div class="competitor-monitor">
          <h3 class="panel-title">🔍 竞品监控中心</h3>

          <!-- 监控摘要 -->
          <div class="monitor-summary" v-if="competitorData.summary">
            <div class="summary-grid">
              <div class="summary-item">
                <span class="summary-value">{{ competitorData.summary.competitors_with_price_drops || 0 }}</span>
                <span class="summary-label">近期降价</span>
              </div>
              <div class="summary-item">
                <span class="summary-value">{{ competitorData.summary.competitors_improving_rank || 0 }}</span>
                <span class="summary-label">排名上升</span>
              </div>
              <div class="summary-item">
                <span class="summary-value warning">{{ competitorData.summary.stock_alerts || 0 }}</span>
                <span class="summary-label">库存异常</span>
              </div>
            </div>
          </div>

          <!-- 竞品列表 -->
          <div class="competitor-list" v-if="competitorData.competitors?.length">
            <h4 class="section-title">📊 竞品状态</h4>
            <a-table
              :dataSource="competitorData.competitors.map((c, i) => ({ ...c, key: i }))"
              size="small"
              :pagination="{ pageSize: 5 }"
              :scroll="{ y: 280 }"
            >
              <a-table-column title="品牌" dataIndex="brand" width="80" />
              <a-table-column title="价格" dataIndex="current_price" width="65" align="right">
                <template #default="{ text }">${{ Number(text).toFixed(2) }}</template>
              </a-table-column>
              <a-table-column title="7日变化" dataIndex="price_change_7d" width="70" align="center">
                <template #default="{ text }">
                  <span :class="Number(text) < -5 ? 'price-drop' : Number(text) > 5 ? 'price-rise' : ''">
                    {{ Number(text) > 0 ? '+' : '' }}{{ text }}%
                  </span>
                </template>
              </a-table-column>
              <a-table-column title="BSR" dataIndex="current_bsr" width="60" align="right" />
              <a-table-column title="评论" dataIndex="review_count" width="55" align="right" />
              <a-table-column title="评分" dataIndex="rating" width="50" align="center">
                <template #default="{ text }">⭐{{ text }}</template>
              </a-table-column>
              <a-table-column title="库存" dataIndex="stock_status" width="70" align="center">
                <template #default="{ text }">
                  <a-tag :color="text === 'In Stock' ? 'success' : 'error'" size="small">
                    {{ text === 'In Stock' ? '有货' : '缺货' }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="警报" dataIndex="alerts" width="120">
                <template #default="{ text: alerts }">
                  <a-tooltip v-for="(alert, idx) in (alerts || []).slice(0, 2)" :key="idx" :title="alert">
                    <a-tag color="warning" size="small" style="margin: 1px">⚠️</a-tag>
                  </a-tooltip>
                </template>
              </a-table-column>
            </a-table>
          </div>

          <!-- 单品深度分析 -->
          <div class="single-analysis" v-if="competitorData.product && competitorData.analysis">
            <h4 class="section-title">📈 深度分析</h4>

            <div class="analysis-cards">
              <div class="analysis-card">
                <span class="card-label">价格稳定性</span>
                <span class="card-value" :class="getStabilityClass(competitorData.analysis.price_stability?.stability)">
                  {{ getStabilityText(competitorData.analysis.price_stability?.stability) }}
                </span>
                <span class="card-detail">CV: {{ competitorData.analysis.price_stability?.coefficient_of_variation }}%</span>
              </div>
              <div class="analysis-card">
                <span class="card-label">排名动量</span>
                <span class="card-value" :class="getMomentumClass(competitorData.analysis.ranking_momentum?.momentum)">
                  {{ getMomentumText(competitorData.analysis.ranking_momentum?.momentum) }}
                </span>
                <span class="card-detail">{{ competitorData.analysis.ranking_momentum?.change_percentage }}%</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 市场份额分析 -->
      <template v-else-if="contentType === 'market_share' && marketShareData">
        <div class="market-share">
          <h3 class="panel-title">🌍 市场格局</h3>

          <!-- 品牌份额表格 -->
          <div class="share-table" v-if="marketShareData.competitors?.length">
            <h4 class="section-title">品牌市场份额</h4>
            <a-table
              :dataSource="marketShareData.competitors.map((c, i) => ({ ...c, key: i }))"
              size="small"
              :pagination="false"
            >
              <a-table-column title="品牌" dataIndex="brand_name" />
              <a-table-column title="份额" dataIndex="estimated_market_share" width="65" align="right" sortable>
                <template #default="{ text }">
                  <strong>{{ text }}%</strong>
                </template>
              </a-table-column>
              <a-table-column title="BSR排名" dataIndex="bsr_rank" width="75" align="right" />
              <a-table-column title="月营收估算" dataIndex="revenue_estimate" width="90" align="right">
                <template #default="{ text }">${{ (Number(text) / 1000).toFixed(1) }}K</template>
              </a-table-column>
              <a-table-column title="趋势" dataIndex="trend" width="60" align="center">
                <template #default="{ text }">
                  <span :class="'trend-' + text">
                    {{ text === 'rising' ? '📈' : text === 'declining' ? '📉' : '➡️' }}
                  </span>
                </template>
              </a-table-column>
            </a-table>
          </div>

          <!-- 集中度指标 -->
          <div class="concentration-metrics" v-if="marketShareData.concentration_ratio">
            <h4 class="section-title">市场集中度</h4>
            <div class="metrics-row">
              <div class="metric-box">
                <span class="metric-label">CR4 集中度</span>
                <span class="metric-value">{{ marketShareData.concentration_ratio.CR4 }}%</span>
              </div>
              <div class="metric-box">
                <span class="metric-label">HHI 指数</span>
                <span class="metric-value">{{ marketShareData.concentration_ratio.HHI }}</span>
              </div>
              <div class="metric-box">
                <span class="metric-label">市场类型</span>
                <a-tag :color="getMarketTypeColor(marketShareData.concentration_ratio.market_type)">
                  {{ getMarketTypeText(marketShareData.concentration_ratio.market_type) }}
                </a-tag>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 入侵者检测 -->
      <template v-else-if="contentType === 'intruder_detection' && intruderData">
        <div class="intruder-detection">
          <h3 class="panel-title">🚨 入侵者警报</h3>

          <!-- 威胁概览 -->
          <div class="threat-overview" v-if="intruderData.threat_summary">
            <div class="threat-stats">
              <div class="threat-stat high">
                <span class="threat-count">{{ intruderData.threat_summary.high_threat || 0 }}</span>
                <span class="threat-label">高威胁</span>
              </div>
              <div class="threat-stat medium">
                <span class="threat-count">{{ intruderData.threat_summary.medium_threat || 0 }}</span>
                <span class="threat-label">中威胁</span>
              </div>
              <div class="threat-stat low">
                <span class="threat-count">{{ intruderData.threat_summary.low_threat || 0 }}</span>
                <span class="threat-label">低威胁</span>
              </div>
            </div>
          </div>

          <!-- 新竞争者列表 -->
          <div class="intruder-list" v-if="intruderData.new_competitors?.length">
            <h4 class="section-title">新进入者详情</h4>
            <div
              v-for="(intruder, idx) in intruderData.new_competitors"
              :key="idx"
              :class="['intruder-card', 'threat-' + intruder.threat_level]"
            >
              <div class="intruder-header">
                <span class="intruder-brand">{{ intruder.brand }}</span>
                <a-tag :color="intruder.threat_level === 'high' ? 'red' : intruder.threat_level === 'medium' ? 'orange' : 'green'">
                  {{ intruder.threat_level === 'high' ? '高威胁' : intruder.threat_level === 'medium' ? '中威胁' : '低威胁' }}
                </a-tag>
                <span class="intruder-price">${{ intruder.price }}</span>
              </div>
              <div class="intruder-asin">ASIN: {{ intruder.asin }}</div>
              <div class="intruder-reasons">
                <span v-for="(reason, ridx) in intruder.reasons.slice(0, 3)" :key="ridx" class="reason-tag">
                  {{ reason }}
                </span>
              </div>
              <div v-if="intruder.our_product_affected" class="affected-badge">
                ⚠️ 影响我方产品
              </div>
            </div>
          </div>

          <!-- 应对策略 -->
          <div class="response-strategies" v-if="intruderData.response_strategies?.length">
            <h4 class="section-title">📋 应对策略</h4>
            <div
              v-for="(strategy, idx) in intruderData.response_strategies.slice(0, 3)"
              :key="idx"
              class="strategy-card"
            >
              <div class="strategy-header">
                <a-tag :color="strategy.priority === 'P0' ? 'red' : strategy.priority === 'P1' ? 'orange' : 'blue'">
                  {{ strategy.priority }}
                </a-tag>
                <span class="strategy-target">目标: {{ strategy.target }}</span>
              </div>
              <ul class="strategy-actions">
                <li v-for="(action, aidx) in strategy.actions.slice(0, 2)" :key="aidx">{{ action }}</li>
              </ul>
            </div>
          </div>
        </div>
      </template>

      <!-- AIGC 生成图片 -->
      <template v-else-if="contentType === 'generated_image' && generatedImageData">
        <div class="generated-image-panel">
          <h3 class="panel-title">🎨 AI 生成图片</h3>

          <div class="image-meta">
            <a-descriptions :column="2" size="small" bordered>
              <a-descriptions-item label="图片ID">{{ generatedImageData.image_id }}</a-descriptions-item>
              <a-descriptions-item label="类型">{{ generatedImageData.image_type }}</a-descriptions-item>
              <a-descriptions-item label="风格">{{ generatedImageData.style }}</a-descriptions-item>
              <a-descriptions-item label="描述">{{ generatedImageData.description }}</a-descriptions-item>
            </a-descriptions>
          </div>

          <div class="prompt-box">
            <h4>📋 生成提示词</h4>
            <p class="prompt-text">{{ generatedImageData.prompt }}</p>
          </div>

          <div v-if="generatedImageData.suggested_captions?.length" class="captions-section">
            <h4>💬 推荐标题</h4>
            <ul>
              <li v-for="(cap, idx) in generatedImageData.suggested_captions" :key="idx">{{ cap }}</li>
            </ul>
          </div>

          <div v-if="generatedImageData.usage_tips?.length" class="tips-section">
            <h4>📌 使用建议</h4>
            <ul>
              <li v-for="(tip, idx) in generatedImageData.usage_tips" :key="idx">{{ tip }}</li>
            </ul>
          </div>

          <div v-if="generatedImageData.variation_suggestions?.length" class="variations-section">
            <h4>🔄 变体建议</h4>
            <a-list :data-source="generatedImageData.variation_suggestions" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <a-list-item-meta :title="item.suggestion" :description="'预期 CTR 变化: ' + (item.expected_ctr_change > 0 ? '+' : '') + item.expected_ctr_change + '%'" />
                </a-list-item>
              </template>
            </a-list>
          </div>
        </div>
      </template>

      <!-- 主图分析结果 -->
      <template v-else-if="contentType === 'main_image_analysis' && mainImageAnalysisData">
        <div class="main-image-analysis">
          <h3 class="panel-title">🖼️ 主图质量诊断</h3>

          <div class="score-header">
            <a-progress
              type="dashboard"
              :percent="Math.round(mainImageAnalysisData.overall_score || 0)"
              :width="120"
              :stroke-color="getScoreColor(mainImageAnalysisData.overall_score || 0)"
            />
            <div class="ctr-prediction">
              <span class="label">预估 CTR</span>
              <span class="value">{{ ((mainImageAnalysisData.ctr_prediction || 0) * 100).toFixed(1) }}%</span>
            </div>
          </div>

          <div v-if="mainImageAnalysisData.visual_appeal" class="visual-scores">
            <h4>🎨 视觉评分</h4>
            <div class="score-grid">
              <div
                v-for="(value, key) in mainImageAnalysisData.visual_appeal"
                :key="key"
                class="score-item"
              >
                <span class="score-label">{{ getVisualLabel(key) }}</span>
                <a-progress
                  :percent="Math.round(value)"
                  :show-info="true"
                  size="small"
                  :stroke-color="getScoreColor(value)"
                />
              </div>
            </div>
          </div>

          <div v-if="mainImageAnalysisData.compliance_check" class="compliance-summary">
            <h4>✅ 合规检查</h4>
            <a-badge
              :count="mainImageAnalysisData.compliance_check.issues?.length || 0"
              :offset="[0, 0]"
              :number-style="{ backgroundColor: '#f5222d' }"
            >
              <a-tag color="green">
                {{ mainImageAnalysisData.compliance_check.passed?.length || 0 }}/{{ (mainImageAnalysisData.compliance_check.passed?.length || 0) + (mainImageAnalysisData.compliance_check.issues?.length || 0) }} 通过
              </a-tag>
            </a-badge>
          </div>

          <div v-if="mainImageAnalysisData.improvement_suggestions?.length" class="suggestions">
            <h4>💡 优化建议</h4>
            <ul>
              <li v-for="(s, idx) in mainImageAnalysisData.improvement_suggestions" :key="idx">{{ s }}</li>
            </ul>
          </div>

          <div v-if="mainImageAnalysisData.ab_test_variants?.length" class="ab-variants">
            <h4>🧪 A/B 测试变体</h4>
            <a-radio-group value="" size="small">
              <a-radio-button v-for="(v, idx) in mainImageAnalysisData.ab_test_variants" :key="idx" :value="idx">
                {{ v.variant }} (CTR: {{ ((v.predicted_ctr || 0) * 100).toFixed(1) }}%)
              </a-radio-button>
            </a-radio-group>
          </div>
        </div>
      </template>

      <!-- A+ 内容展示 -->
      <template v-else-if="contentType === 'a_plus_content' && aPlusContentData">
        <div class="aplus-content-panel">
          <h3 class="panel-title">📝 A+/EBC 内容</h3>

          <a-alert
            :message="`共 ${aPlusContentData.total_modules} 个模块 | 预计阅读 ${Math.floor((aPlusContentData.estimated_read_time || 0) / 60)}分${(aPlusContentData.estimated_read_time || 0) % 60}秒`"
            type="info"
            show-icon
            style="margin-bottom: 16px"
          />

          <a-collapse accordion>
            <a-collapse-panel
              v-for="(module, idx) in aPlusContentData.modules"
              :key="idx"
              :header="`模块 ${idx + 1}: ${module.title}`"
            >
              <div class="module-meta">
                <a-space>
                  <a-tag :color="getModuleTypeColor(module.module_type)">{{ module.module_type }}</a-tag>
                  <span>SEO: {{ module.seo_score }}/100</span>
                  <span>~{{ module.character_count }}字</span>
                  <span v-if="module.images_needed > 0">🖼️ {{ module.images_needed }}张图</span>
                </a-space>
              </div>
              <div class="module-content-preview">
                {{ module.content }}
              </div>
            </a-collapse-panel>
          </a-collapse>

          <div v-if="aPlusContentData.optimization_tips?.length" class="optimization-tips">
            <h4>✨ 优化建议</h4>
            <a-list :data-source="aPlusContentData.optimization_tips" size="small">
              <template #renderItem="{ item }">
                <a-list-item>{{ item }}</a-list-item>
              </template>
            </a-list>
          </div>
        </div>
      </template>

      <!-- 品牌故事展示 -->
      <template v-else-if="contentType === 'brand_story' && brandStoryData">
        <div class="brand-story-panel">
          <h3 class="panel-title">🏆 品牌故事</h3>

          <a-card title="品牌定位" size="small" :bordered="false" style="margin-bottom: 12px">
            <p>{{ brandStoryData.brand_positioning }}</p>
          </a-card>

          <a-card title="品牌使命" size="small" :bordered="false" style="margin-bottom: 12px">
            <p>{{ brandStoryData.brand_mission }}</p>
          </a-card>

          <a-row :gutter="12" style="margin-bottom: 12px">
            <a-col :span="12">
              <a-card title="核心价值" size="small" :bordered="false">
                <a-tag v-for="(v, idx) in (brandStoryData.brand_values || []).slice(0, 5)" :key="idx" color="blue" style="margin: 2px">{{ v }}</a-tag>
              </a-card>
            </a-col>
            <a-col :span="12">
              <a-card title="Slogan 建议" size="small" :bordered="false">
                <a-list :data-source="brandStoryData.tagline_options || []" size="small">
                  <template #renderItem="{ item }">
                    <a-list-item>{{ item }}</a-list-item>
                  </template>
                </a-list>
              </a-card>
            </a-col>
          </a-row>

          <a-collapse>
            <a-collapse-panel header="起源故事 📖" key="origin">
              <p>{{ brandStoryData.origin_story }}</p>
            </a-collapse-panel>
            <a-collapse-panel header="完整 About 描述（可用于 Amazon Store）" key="about">
              <p style="white-space: pre-line">{{ brandStoryData.about_brand_text }}</p>
            </a-collapse-panel>
          </a-collapse>
        </div>
      </template>

      <!-- 翻译结果展示 -->
      <template v-else-if="contentType === 'translation'" class="translation-panel">
        <div class="translation-result">
          <h3 class="panel-title">🌍 翻译结果</h3>

          <a-card title="原文" size="small" :bordered="false" style="margin-bottom: 12px; background: #fafafa">
            <p>{{ rawData?.original_text }}</p>
          </a-card>

          <a-card title="译文" size="small" :bordered="false" style="margin-bottom: 12px; background: #e6f7ff">
            <p>{{ rawData?.translated_text }}</p>
          </a-card>

          <a-space style="margin-bottom: 12px">
            <a-tag :color="(rawData as any)?.seo_optimized ? 'green' : 'default'">
              {{ (rawData as any)?.seo_optimized ? '✅ SEO 已优化' : 'SEO 未优化' }}
            </a-tag>
            <a-tag>{{ (rawData as any)?.source_lang }} → {{ (rawData as any)?.target_lang }}</a-tag>
          </a-space>

          <a-tabs size="small">
            <a-tab-pane tab="关键词保留" key="keywords">
              <a-table
                :columns="[{ title: '关键词', dataIndex: 'keyword' }, { title: '位置', dataIndex: 'position' }]"
                :data-source="(rawData as any)?.keyword_inclusion || []"
                size="small"
                :pagination="false"
              />
            </a-tab-pane>
            <a-tab-pane tab="文化注意" key="cultural">
              <a-list :data-source="(rawData as any)?.cultural_notes || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>{{ item }}</a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
            <a-tab-pane tab="替代版本" key="alternatives">
              <a-list :data-source="(rawData as any)?.alternative_versions || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta :title="item.version" :description="item.text" />
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
          </a-tabs>
        </div>
      </template>

      <!-- 合规检查报告 -->
      <template v-else-if="contentType === 'compliance_report' && complianceReportData">
        <div class="compliance-report-panel">
          <h3 class="panel-title">✅ 合规检查报告</h3>

          <div class="status-header">
            <a-badge
              :status="complianceReportData.overall_status === 'pass' ? 'success' : complianceReportData.overall_status === 'warning' ? 'warning' : 'error'"
              :text="complianceReportData.overall_status === 'pass' ? '通过' : complianceReportData.overall_status === 'warning' ? '有警告' : '不通过'"
            />
            <a-progress
              type="circle"
              :percent="Math.round(complianceReportData.score || 0)"
              :width="60"
              :stroke-color="complianceReportData.score >= 80 ? '#52c41a' : complianceReportData.score >= 60 ? '#faad14' : '#f5222d'"
            />
          </div>

          <a-tabs size="small">
            <a-tab-pane :tab="`✅ 通过 (${(complianceReportData.passed_checks || []).length})`" key="passed">
              <a-checkbox-group :value="[]" disabled>
                <a-checkbox
                  v-for="(check, idx) in (complianceReportData.passed_checks || []).slice(0, 10)"
                  :key="idx"
                  :value="check"
                  style="display: block; margin: 4px 0"
                >
                  {{ check }}
                </a-checkbox>
              </a-checkbox-group>
            </a-tab-pane>
            <a-tab-pane :tab="`❌ 问题 (${(complianceReportData.issues || []).length})`" key="issues">
              <a-list :data-source="complianceReportData.issues || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #title>
                        <a-space>
                          <a-tag :color="item.severity === 'critical' ? 'red' : 'orange'">{{ item.issue_type }}</a-tag>
                          <span>{{ item.affected_area }}</span>
                        </a-space>
                      </template>
                      <template #description>
                        <div>{{ item.description }}</div>
                        <div style="color: #1890ff; margin-top: 4px">💡 {{ item.suggestion }}</div>
                      </template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
            <a-tab-pane tab="💡 建议" key="recommendations">
              <a-list :data-source="complianceReportData.recommendations || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>{{ item }}</a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
          </a-tabs>
        </div>
      </template>

      <!-- 视频脚本展示 -->
      <template v-else-if="contentType === 'video_script' && videoScriptData">
        <div class="video-script-panel">
          <h3 class="panel-title">🎬 视频脚本</h3>

          <a-alert
            :message="`${videoScriptData.title} | 总时长: ${videoScriptData.total_duration}s | 平台: ${videoScriptData.target_platform}`"
            type="info"
            show-icon
            style="margin-bottom: 16px"
          />

          <a-timeline mode="left">
            <a-timeline-item
              v-for="(scene, idx) in (videoScriptData.scenes || [])"
              :key="idx"
              :color="idx === 0 ? 'green' : 'blue'"
            >
              <template #dot><span style="font-size: 12px">{{ scene.scene_number }}</span></template>
              <a-card size="small" :bordered="false" style="background: #fafafa">
                <div class="scene-duration"><a-tag color="blue">{{ scene.duration }}s</a-tag></div>
                <div><strong>画面:</strong> {{ scene.visual_description }}</div>
                <div><strong>字幕:</strong> {{ scene.text_overlay }}</div>
                <div><strong>配音:</strong> {{ scene.voiceover }}</div>
                <div><strong>音乐:</strong> {{ scene.background_music }} | <strong>转场:</strong> {{ scene.transition }}</div>
              </a-card>
            </a-timeline-item>
          </a-timeline>

          <a-divider />

          <a-row :gutter="12">
            <a-col :span="8">
              <a-card title="🎯 钩子备选" size="small" :bordered="false">
                <a-list :data-source="videoScriptData.hook_lines || []" size="small">
                  <template #renderItem="{ item }">
                    <a-list-item>{{ item }}</a-list-item>
                  </template>
                </a-list>
              </a-card>
            </a-col>
            <a-col :span="8">
              <a-card title="📢 CTA 建议" size="small" :bordered="false">
                <a-list :data-source="videoScriptData.cta_suggestions || []" size="small">
                  <template #renderItem="{ item }">
                    <a-list-item>{{ item }}</a-list-item>
                  </template>
                </a-list>
              </a-card>
            </a-col>
            <a-col :span="8">
              <a-card title="#️⃣ 话题标签" size="small" :bordered="false">
                <div>
                  <a-tag v-for="(tag, idx) in (videoScriptData.hashtag_recommendations || [])" :key="idx" style="margin: 2px">{{ tag }}</a-tag>
                </div>
              </a-card>
            </a-col>
          </a-row>
        </div>
      </template>

      <!-- 默认：JSON 数据 -->
      <template v-else>
        <pre class="json-block">{{ JSON.stringify(rawData, null, 2) }}</pre>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  AppstoreOutlined,
  LineChartOutlined,
} from '@ant-design/icons-vue'
import MarkdownIt from 'markdown-it'

import { useResultStore } from '@/stores/result'

const resultStore = useResultStore()

// Markdown 渲染器
const md = new MarkdownIt()

// 是否有内容
const hasContent = computed(() => resultStore.hasContent)

// 内容类型（自动识别）
const contentType = computed(() => resultStore.contentType)

// 各类型数据
const tableData = computed(() => resultStore.tableData)
const tableColumns = computed(() => resultStore.tableColumns)
const reportContent = computed(() => resultStore.reportContent)
const imageSrc = computed(() => resultStore.imageSrc)
const codeContent = computed(() => resultStore.codeContent)
const rawData = computed(() => resultStore.rawData)
const listingData = computed(() => resultStore.listingData)
const profitData = computed(() => resultStore.profitData)
const adData = computed(() => resultStore.adData)
const orderData = computed(() => resultStore.orderData)
const ticketData = computed(() => resultStore.ticketData)
const competitorData = computed(() => resultStore.competitorData)
const marketShareData = computed(() => resultStore.marketShareData)
const intruderData = computed(() => resultStore.intruderData)
const generatedImageData = computed(() => resultStore.generatedImageData)
const mainImageAnalysisData = computed(() => resultStore.mainImageAnalysisData)
const aPlusContentData = computed(() => resultStore.aPlusContentData)
const brandStoryData = computed(() => resultStore.brandStoryData)
const translationData = computed(() => resultStore.translationData)
const complianceReportData = computed(() => resultStore.complianceReportData)
const videoScriptData = computed(() => resultStore.videoScriptData)

// SEO 评分颜色辅助函数
const getScoreClass = (score: number) => {
  if (score >= 90) return 'score-excellent'
  if (score >= 80) return 'score-good'
  if (score >= 70) return 'score-average'
  return 'score-poor'
}

const getProgressColor = (score: number) => {
  if (score >= 90) return '#52c41a'
  if (score >= 80) return '#1890ff'
  if (score >= 70) return '#faad14'
  return '#ff4d4f'
}

// 利润分析辅助函数
const getRoiColor = (roi: number | undefined) => {
  if (!roi) return 'default'
  if (roi >= 40) return 'green'
  if (roi >= 20) return 'blue'
  if (roi >= 0) return 'orange'
  return 'red'
}

const getFeeColor = (index: number) => {
  const colors = ['#ff7875', '#ffa940', '#597ef7', '#36cfc9', '#95de64']
  return colors[index % colors.length]
}

// 客服辅助函数
const getPriorityColor = (priority: string) => {
  const map: Record<string, string> = { urgent: 'red', high: 'orange', medium: 'blue', low: 'default' }
  return map[priority] || 'default'
}

const getStatusColor = (status: string) => {
  const map: Record<string, string> = { open: 'processing', in_progress: 'blue', resolved: 'green', closed: 'default' }
  return map[status] || 'default'
}

// AIGC 辅助函数
const getScoreColor = (score: number) => {
  if (score >= 90) return '#52c41a'
  if (score >= 80) return '#1890ff'
  if (score >= 70) return '#faad14'
  return '#f5222d'
}

const getVisualLabel = (key: string) => {
  const map: Record<string, string> = {
    visual_appeal: '视觉吸引力',
    clarity: '清晰度',
    color_quality: '色彩质量',
    composition: '构图',
    brand_presence: '品牌呈现',
  }
  return map[key] || key
}

const getModuleTypeColor = (type: string) => {
  const map: Record<string, string> = {
    standard: 'blue',
    comparison_table: 'green',
    image_banner: 'orange',
    text_table: 'purple',
  }
  return map[type] || 'default'
}

// 竞品监控辅助函数
const getStabilityClass = (stability?: string) => {
  const map: Record<string, string> = { very_stable: 'positive', stable: 'positive', moderate: 'warning', volatile: 'negative' }
  return map[stability || ''] || ''
}

const getStabilityText = (stability?: string) => {
  const map: Record<string, string> = { very_stable: '非常稳定', stable: '稳定', moderate: '中等', volatile: '波动大' }
  return map[stability || ''] || '未知'
}

const getMomentumClass = (momentum?: string) => {
  const map: Record<string, string> = { strong_up: 'positive', up: 'positive', stable: 'neutral', down: 'negative', strong_down: 'negative' }
  return map[momentum || ''] || ''
}

const getMomentumText = (momentum?: string) => {
  const map: Record<string, string> = { strong_up: '强劲上升', up: '上升', stable: '稳定', down: '下降', strong_down: '快速下降' }
  return map[momentum || ''] || '未知'
}

const getMarketTypeColor = (type?: string) => {
  const map: Record<string, string> = { competitive: 'green', moderate_concentration: 'orange', high_concentration: 'red' }
  return map[type || ''] || 'default'
}

const getMarketTypeText = (type?: string) => {
  const map: Record<string, string> = { competitive: '竞争型', moderate_concentration: '中度集中', high_concentration: '高集中度' }
  return map[type || ''] || '未知'
}

// 月度预估表格列
const projectionColumns = [
  { title: '月销量', dataIndex: 'volume', key: 'volume' },
  { title: '总收入', dataIndex: 'revenue', key: 'revenue' },
  { title: '总成本', dataIndex: 'total_cost', key: 'total_cost' },
  { title: '净利润', dataIndex: 'net_profit', key: 'net_profit' },
]

// 渲染 Markdown
const renderMarkdown = (content: string) => {
  return md.render(content)
}

// 清空内容
const handleClear = () => {
  resultStore.clear()
}
</script>

<style scoped>
.smart-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: #fff;
}

.panel-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f0f0f0;
}

.panel-header h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #8c8c8c;
  padding: 24px;
}

.empty-state .hint {
  margin-top: 8px;
  font-size: 13px;
  color: #bfbfbf;
}

/* 内容区域 */
.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* 表格 */
:deep(.ant-table) {
  font-size: 13px;
}

/* 图表占位 */
.chart-placeholder {
  height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: #fafafa;
  border-radius: 8px;
  border: 1px dashed #d9d9d9;
}

.chart-placeholder .hint {
  margin-top: 8px;
  font-size: 12px;
  color: #bfbfbf;
}

/* 报告内容 */
.report-content {
  line-height: 1.8;
  font-size: 14px;
}

.report-content :deep(h1),
.report-content :deep(h2),
.report-content :deep(h3) {
  margin-top: 16px;
  margin-bottom: 8px;
}

/* 代码块 */
.code-block,
.json-block {
  background-color: #f5f5f5;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 12px;
  line-height: 1.6;
}

/* Listing 预览样式 */
.listing-preview {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* SEO 评分卡片 */
.seo-score-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 16px;
  color: #fff;
}

.score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.score-label {
  font-size: 14px;
  opacity: 0.9;
}

.score-value {
  font-size: 24px;
  font-weight: bold;
}

.score-excellent { color: #52c41a; }
.score-good { color: #1890ff; }
.score-average { color: #faad14; }
.score-poor { color: #ff4d4f; }

.score-breakdown {
  display: flex;
  justify-content: space-between;
  margin-top: 12px;
  font-size: 12px;
  opacity: 0.9;
}

/* Listing 各区块 */
.listing-section {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: hidden;
}

.section-title {
  margin: 0;
  padding: 12px 16px;
  background-color: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
}

.title-content {
  padding: 16px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.6;
  color: #262626;
}

.title-meta {
  padding: 0 16px 12px;
  display: flex;
  gap: 8px;
}

/* 五点描述 */
.bullets-list {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bullet-item {
  border-left: 3px solid #1890ff;
  padding-left: 12px;
}

.bullet-header {
  font-weight: bold;
  font-size: 13px;
  color: #262626;
  margin-bottom: 4px;
}

.bullet-content {
  font-size: 13px;
  color: #595959;
  line-height: 1.6;
}

/* 产品描述 */
.description-content {
  padding: 16px;
  font-size: 13px;
  line-height: 1.8;
  color: #595959;
}

/* 关键词 */
.keywords-content {
  padding: 12px 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.keywords-meta {
  padding: 0 16px 12px;
}

/* 利润分析样式 */
.profit-analysis {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.profit-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.kpi-card {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px 12px;
  text-align: center;
  border: 1px solid #f0f0f0;
}

.kpi-label {
  display: block;
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 6px;
}

.kpi-value {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: #262626;
}

.kpi-value-tag {
  font-size: 16px !important;
}

.kpi-profit .kpi-value { color: #52c41a; }
.kpi-profit.negative .kpi-value { color: #ff4d4f; }
.kpi-roi .kpi-value { color: #1890ff; }
.kpi-margin .kpi-value { color: #722ed1; }
.kpi-breakeven .kpi-value { color: #fa8c16; }

.fee-structure,
.monthly-projection,
.sensitivity,
.recommendations {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #f0f0f0;
}

.section-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #262626;
}

.fee-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fee-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.fee-name {
  width: 80px;
  color: #595959;
  flex-shrink: 0;
}

.fee-bar-wrapper {
  flex: 1;
  height: 18px;
  background-color: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
}

.fee-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.fee-amount {
  width: 55px;
  text-align: right;
  font-weight: 500;
}

.fee-percent {
  width: 40px;
  text-align: right;
  color: #8c8c8c;
  font-size: 11px;
}

.sensitivity-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sensitivity-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 6px 0;
  border-bottom: 1px dashed #f0f0f0;
}

.sensitivity-item:last-child {
  border-bottom: none;
}

.sensitivity-value.positive { color: #52c41a; font-weight: 500; }
.sensitivity-value.negative { color: #ff4d4f; font-weight: 500; }

.rec-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 2;
  color: #595959;
}

/* 广告诊断样式 */
.ad-diagnosis {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.diagnosis-score-card {
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  color: #fff;
}

.diagnosis-score-card.grade-a { background: linear-gradient(135deg, #52c41a, #73d13d); }
.diagnosis-score-card.grade-b { background: linear-gradient(135deg, #1890ff, #40a9ff); }
.diagnosis-score-card.grade-c { background: linear-gradient(135deg, #faad14, #ffc53d); }
.diagnosis-score-card.grade-d { background: linear-gradient(135deg, #fa8c16, #ffa940); }
.diagnosis-score-card.grade-f { background: linear-gradient(135deg, #ff4d4f, #ff7875); }

.score-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.score-label { font-size: 14px; opacity: 0.9; }
.score-value { font-size: 36px; font-weight: 700; }
.grade-badge {
  font-size: 16px;
  font-weight: 600;
  background: rgba(255,255,255,0.25);
  padding: 2px 12px;
  border-radius: 10px;
}

.ad-metrics,
.campaign-table,
.issues-list,
.recommendations {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #f0f0f0;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.metric-item {
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
  border-left: 3px solid #d9d9d9;
}

.metric-item.status-good { border-left-color: #52c41a; }
.metric-item.status-warning { border-left-color: #faad14; }
.metric-item.status-critical { border-left-color: #ff4d4f; }

.metric-name { display: block; font-size: 11px; color: #8c8c8c; margin-bottom: 4px; }
.metric-value { display: block; font-size: 18px; font-weight: 600; color: #262626; }
.metric-benchmark { display: block; font-size: 10px; color: #bfbfbf; margin-top: 2px; }
.metric-status-icon { margin-top: 4px; }

/* 订单信息样式 */
.order-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.order-status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
  text-align: center;
}

.order-status-badge.status-delivered { background-color: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.order-status-badge.status-shipped { background-color: #e6f7ff; color: #1890ff; border: 1px solid #91d5ff; }
.order-status-badge.status-processing { background-color: #fff7e6; color: #fa8c16; border: 1px solid #ffd591; }

.tracking-info {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #f0f0f0;
}

.tracking-info h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
}

/* 工单信息样式 */
.ticket-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ticket-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ticket-id {
  font-family: 'Monaco', monospace;
  font-size: 14px;
  font-weight: 600;
  color: #1890ff;
}

.auto-replies {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #f0f0f0;
}

.auto-replies h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
}

.auto-replies ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: #595959;
}

/* 竞品监控样式 */
.competitor-monitor,
.market-share,
.intruder-detection {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.monitor-summary {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #f0f0f0;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.summary-item {
  text-align: center;
  padding: 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #f0f0f0;
}

.summary-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: #1890ff;
}

.summary-value.warning {
  color: #fa8c16;
}

.summary-label {
  display: block;
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
}

.price-drop { color: #52c41a; font-weight: 500; }
.price-rise { color: #ff4d4f; font-weight: 500; }

.analysis-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-top: 10px;
}

.analysis-card {
  background: #fff;
  border-radius: 8px;
  padding: 14px;
  text-align: center;
  border-left: 3px solid #d9d9d9;
}

.card-label {
  display: block;
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 4px;
}

.card-value {
  display: block;
  font-size: 18px;
  font-weight: 600;
}

.card-value.positive { color: #52c41a; }
.card-value.negative { color: #ff4d4f; }
.card-value.neutral { color: #faad14; }

.card-detail {
  display: block;
  font-size: 11px;
  color: #bfbfbf;
  margin-top: 4px;
}

/* 市场份额样式 */
.share-table,
.concentration-metrics {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #f0f0f0;
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 10px;
}

.metric-box {
  background: #fff;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}

.metric-label {
  display: block;
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 4px;
}

.metric-value {
  display: block;
  font-size: 18px;
  font-weight: 600;
  color: #262626;
}

.trend-rising { color: #52c41a; }
.trend-declining { color: #ff4d4f; }

/* 入侵者检测样式 */
.threat-overview {
  background-color: #fff2e8;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #ffbb96;
}

.threat-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.threat-stat {
  text-align: center;
  padding: 12px;
  border-radius: 6px;
}

.threat-stat.high { background: #fff1f0; border: 1px solid #ffa39e; }
.threat-stat.medium { background: #fff7e6; border: 1px solid #ffd591; }
.threat-stat.low { background: #f6ffed; border: 1px solid #b7eb8f; }

.threat-count {
  display: block;
  font-size: 28px;
  font-weight: 700;
}

.threat-stat.high .threat-count { color: #cf1322; }
.threat-stat.medium .threat-count { color: #d46b08; }
.threat-stat.low .threat-count { color: #389e0d; }

.threat-label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-top: 4px;
}

.intruder-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.intruder-card {
  background: #fafafa;
  border-radius: 8px;
  padding: 12px;
  border-left: 4px solid #d9d9d9;
}

.intruder-card.threat-high { border-left-color: #ff4d4f; }
.intruder-card.threat-medium { border-left-color: #faad14; }
.intruder-card.threat-low { border-left-color: #52c41a; }

.intruder-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.intruder-brand {
  font-weight: 600;
  font-size: 14px;
}

.intruder-price {
  margin-left: auto;
  font-weight: 500;
  color: #262626;
}

.intruder-asin {
  font-size: 12px;
  color: #8c8c8c;
  font-family: 'Monaco', monospace;
  margin-bottom: 8px;
}

.intruder-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.reason-tag {
  background: #fff;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: #595959;
  border: 1px solid #f0f0f0;
}

.affected-badge {
  display: inline-block;
  background: #fff1f0;
  color: #cf1322;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.response-strategies {
  background-color: #fafafa;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #f0f0f0;
}

.strategy-card {
  background: #fff;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #f0f0f0;
}

.strategy-card:last-child {
  margin-bottom: 0;
}

.strategy-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.strategy-target {
  font-size: 13px;
  color: #595959;
  font-family: 'Monaco', monospace;
}

.strategy-actions {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  line-height: 1.8;
  color: #595959;
}

/* ====== AIGC 媒体生成样式 ====== */

.generated-image-panel .prompt-box {
  background: #f6f8fa;
  border-radius: 6px;
  padding: 12px;
  margin: 12px 0;
}
.generated-image-panel .prompt-text {
  font-family: 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #333;
  word-break: break-all;
}
.generated-image-panel .captions-section ul,
.generated-image-panel .tips-section ul,
.generated-image-panel .variations-section ul {
  margin: 8px 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
}

.main-image-analysis .score-header {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 20px;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
}
.main-image-analysis .ctr-prediction {
  text-align: center;
}
.main-image-analysis .ctr-prediction .label {
  display: block;
  font-size: 12px;
  color: #888;
}
.main-image-analysis .ctr-prediction .value {
  display: block;
  font-size: 24px;
  font-weight: bold;
  color: #1890ff;
}
.main-image-analysis .visual-scores .score-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 10px;
}
.main-image-analysis .visual-scores .score-item {
  background: #fafafa;
  padding: 8px 12px;
  border-radius: 6px;
}
.main-image-analysis .visual-scores .score-label {
  font-size: 12px;
  color: #666;
  display: block;
  margin-bottom: 4px;
}
.main-image-analysis .suggestions ul,
.main-image-analysis .compliance-summary {
  margin-top: 8px;
}
.main-image-analysis .suggestions ul {
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
}

.aplus-content-panel .module-meta {
  margin-bottom: 8px;
}
.aplus-content-panel .module-content-preview {
  font-size: 13px;
  line-height: 1.7;
  color: #444;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
  padding: 8px;
  background: #fafafa;
  border-radius: 4px;
}

.brand-story-panel .ant-card-body p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #555;
}

.translation-result .ant-card-body p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
}

.compliance-report-panel .status-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px;
  background: #fafafa;
  border-radius: 8px;
}

.video-script-panel .scene-duration {
  margin-bottom: 8px;
}
</style>
