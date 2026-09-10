<template>
  <div class="ad-dashboard">
    <!-- 顶部 Tab 导航（仅大屏模式显示） -->
    <div v-if="isDataMode" class="ad-tabs">
      <button
        v-for="tab in AD_TABS"
        :key="tab.key"
        class="ad-tab"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        <span class="ad-tab-icon">{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- ══════════ ① 账户总览 ══════════ -->
    <section v-if="activeTab === 'overview'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">账户总览 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">核心效益指标 + Campaign 健康状态 + 花费/销售趋势 + Top 问题</div>
        </div>
      </div>

      <!-- 综合评分 + KPI -->
      <div class="score-kpi-row">
        <div class="score-card" :class="'grade-' + AD_OVERALL_GRADE">
          <span class="score-val">{{ AD_OVERALL_SCORE }}</span>
          <span class="grade-label">{{ AD_OVERALL_GRADE }}</span>
        </div>
        <div class="kpi-grid flex-1">
          <div v-for="m in AD_METRICS" :key="m.name" class="kpi-card">
            <div class="kpi-label">{{ m.name }}</div>
            <div class="kpi-value" :class="m.status === 'good' ? 'success' : m.status === 'danger' ? 'danger' : 'warning'">
              {{ m.unit === '%' ? m.value.toFixed(1) + '%' : m.unit === '$' ? '$' + m.value.toFixed(2) : m.unit === 'x' ? m.value.toFixed(2) + 'x' : m.value }}
            </div>
            <div class="kpi-change">
              <span :class="m.change_pct >= 0 ? 'up' : 'down'">
                {{ m.change_pct >= 0 ? '▲' : '▼' }} {{ Math.abs(m.change_pct).toFixed(1) }}% <em>环比</em>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 趋势图 -->
      <div class="panel-card chart-card">
        <div class="card-head">每日花费 / 销售额趋势</div>
        <LineChart :series="trendSeries" :labels="AD_DAILY_TREND.labels" :legend="true" />
      </div>

      <!-- 两栏: Campaign 表 + 问题列表 -->
      <div class="two-col">
        <div class="panel-card">
          <div class="card-head">Campaign 健康状态</div>
          <div class="tbl sm">
            <div class="tbl-head">
              <span class="c-role">Campaign</span><span class="c-num">花费</span><span class="c-num">销售</span><span class="c-num">ACoS</span><span class="c-num">RoAS</span><span class="c-badge">状态</span>
            </div>
            <div v-for="c in AD_CAMPAIGNS" :key="c.campaign_name" class="tbl-row">
              <span class="c-role"><a-tag size="small" :color="c.type === 'SP' ? 'blue' : c.type === 'SB' ? 'purple' : 'orange'">{{ c.type }}</a-tag> {{ c.campaign_name }}</span>
              <span class="c-num">${{ c.spend.toLocaleString() }}</span>
              <span class="c-num">${{ c.sales.toLocaleString() }}</span>
              <span class="c-num" :class="c.acos <= 25 ? 'ok' : c.acos <= 35 ? 'warn' : 'danger'">{{ c.acos }}%</span>
              <span class="c-num" :class="c.roas >= 4 ? 'ok' : c.roas >= 2.5 ? 'warn' : 'danger'">{{ c.roas }}x</span>
              <span class="c-badge"><a-tag size="small" :color="c.acos <= 25 ? 'green' : c.acos <= 35 ? 'orange' : 'red'">{{ c.acos <= 25 ? '健康' : c.acos <= 35 ? '关注' : '预警' }}</a-tag></span>
            </div>
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head danger">Top 问题</div>
          <div class="issue-list">
            <div v-for="(issue, idx) in AD_TOP_ISSUES" :key="idx" class="issue-item" :class="'priority-' + issue.priority">
              <span class="issue-rank">{{ idx + 1 }}</span>
              <div class="issue-content">
                <span class="issue-title">{{ issue.title }}</span>
                <span class="issue-desc">{{ issue.description }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════ ② 搜索词分析 ══════════ -->
    <section v-else-if="activeTab === 'searchterms'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">搜索词分析 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">高效词 / 低效词 / 浪费词分类 + 新机会挖掘</div>
        </div>
      </div>

      <!-- 效率分布 -->
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">总搜索词</div><div class="kpi-value">42</div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:#52c41a">高效词</div><div class="kpi-value success">3</div><div class="kpi-change"><span class="up">RoAS ≥ 3.5</span></div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:#faad14">低效词</div><div class="kpi-value warning">2</div><div class="kpi-change"><span class="down">RoAS 2~3</span></div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:#ff4d4f">浪费词</div><div class="kpi-value danger">2</div><div class="kpi-change"><span class="down">零转化</span></div></div>
      </div>

      <!-- 高效词 -->
      <div class="panel-card">
        <div class="card-head ok">高效词（提高预算 / 扩量）</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">搜索词</span><span class="c-num">展示</span><span class="c-num">点击</span><span class="c-num">花费</span><span class="c-num">销售</span><span class="c-num">ACoS</span><span class="c-badge">匹配</span></div>
          <div v-for="t in SEARCH_TERMS.filter(t => t.efficiency === 'high')" :key="t.term" class="tbl-row">
            <span class="c-role">{{ t.term }}</span>
            <span class="c-num">{{ t.impr.toLocaleString() }}</span>
            <span class="c-num">{{ t.clicks }}</span>
            <span class="c-num">${{ t.spend.toFixed(2) }}</span>
            <span class="c-num ok">${{ t.sales.toFixed(2) }}</span>
            <span class="c-num ok">{{ t.acos }}%</span>
            <span class="c-badge"><a-tag size="small" color="blue">{{ t.match_type }}</a-tag></span>
          </div>
        </div>
      </div>

      <!-- 低效 + 浪费词 -->
      <div class="two-col">
        <div class="panel-card">
          <div class="card-head warn">低效词（降低出价 / 改匹配）</div>
          <div class="term-list">
            <div v-for="t in SEARCH_TERMS.filter(t => t.efficiency === 'low')" :key="t.term" class="term-row">
              <span class="term-name">{{ t.term }}</span>
              <span class="term-acos warn">{{ t.acos }}%</span>
              <span class="term-spend">${{ t.spend.toFixed(2) }}</span>
            </div>
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head danger">浪费词（建议否定）</div>
          <div class="term-list">
            <div v-for="t in SEARCH_TERMS.filter(t => t.efficiency === 'waste')" :key="t.term" class="term-row">
              <span class="term-name">{{ t.term }}</span>
              <span class="term-acos danger">∞</span>
              <span class="term-spend danger">${{ t.spend.toFixed(2) }}</span>
            </div>
          </div>
          <div class="waste-total">月浪费: ${{ SEARCH_TERMS.filter(t => t.efficiency === 'waste').reduce((s, t) => s + t.spend, 0).toFixed(2) }}</div>
        </div>
      </div>

      <!-- 建议 -->
      <div class="panel-card">
        <div class="card-head">优化建议</div>
        <ul class="suggestion-list">
          <li v-for="(s, i) in SEARCH_SUGGESTIONS" :key="i">{{ s }}</li>
        </ul>
      </div>
    </section>

    <!-- ══════════ ③ 出价优化 ══════════ -->
    <section v-else-if="activeTab === 'bid'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">出价优化 <a-tag color="default" class="mini-tag">平衡策略</a-tag></div>
          <div class="pane-sub">基于近30天转化的智能出价建议，预计 ACoS {{ fmtPct(BID_SUMMARY.expected_acos_change) }}</div>
        </div>
      </div>

      <!-- 汇总 -->
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">分析关键词</div><div class="kpi-value">{{ BID_SUMMARY.total_keywords }}</div></div>
        <div class="kpi-card"><div class="kpi-label">预算影响</div><div class="kpi-value" :class="BID_SUMMARY.budget_impact >= 0 ? 'danger' : 'success'">${{ BID_SUMMARY.budget_impact >= 0 ? '+' : '' }}{{ BID_SUMMARY.budget_impact.toFixed(2) }}/词</div></div>
        <div class="kpi-card"><div class="kpi-label">预计 ACoS 变化</div><div class="kpi-value success">{{ fmtPct(BID_SUMMARY.expected_acos_change) }}</div></div>
      </div>

      <!-- 出价建议表 -->
      <div class="panel-card">
        <div class="card-head">关键词出价调整</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">关键词</span><span class="c-badge">匹配</span><span class="c-num">当前出价</span><span class="c-num">建议出价</span><span class="c-num">调整</span><span class="c-role">原因</span><span class="c-badge">优先级</span></div>
          <div v-for="b in BID_SUGGESTIONS" :key="b.keyword" class="tbl-row">
            <span class="c-role">{{ b.keyword }}</span>
            <span class="c-badge"><a-tag size="small" color="blue">{{ b.match_type }}</a-tag></span>
            <span class="c-num">${{ b.current_bid.toFixed(2) }}</span>
            <span class="c-num" :class="bidClass(b)">${{ b.suggested_bid.toFixed(2) }}</span>
            <span class="c-num" :class="bidChangeClass(b)">{{ b.bid_change_pct > 0 ? '+' : '' }}{{ b.bid_change_pct }}%</span>
            <span class="c-role reason-text">{{ b.reason }}</span>
            <span class="c-badge"><a-tag size="small" :color="b.priority === 'high' ? 'red' : b.priority === 'medium' ? 'orange' : 'default'">{{ b.priority === 'high' ? '高' : b.priority === 'medium' ? '中' : '低' }}</a-tag></span>
          </div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">策略说明</div>
        <p class="rationale">{{ BID_SUMMARY.rationale }}</p>
      </div>
    </section>

    <!-- ══════════ ④ 竞品广告 ══════════ -->
    <section v-else-if="activeTab === 'competitor'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">竞品广告 <a-tag color="default" class="mini-tag">SOV 分析</a-tag></div>
          <div class="pane-sub">你的 SOV: {{ YOUR_SOV }}% | 市场定位: 利基玩家 | Top 4 竞品广告策略对比</div>
        </div>
      </div>

      <!-- SOV 饼图 + 你的位置 -->
      <div class="two-col">
        <div class="panel-card chart-card">
          <div class="card-head">SOV 占比</div>
          <DonutChart :segments="sovSegments" :center-value="YOUR_SOV + '%'" center-title="你的 SOV" />
        </div>
        <div class="panel-card">
          <div class="card-head">可执行洞察</div>
          <ul class="suggestion-list">
            <li v-for="(insight, i) in COMPETITOR_INSIGHTS" :key="i">{{ insight }}</li>
          </ul>
        </div>
      </div>

      <!-- 竞品详情表 -->
      <div class="panel-card">
        <div class="card-head">竞品广告详情</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">竞品</span><span class="c-num">SOV</span><span class="c-num">重叠词</span><span class="c-num">均位</span><span class="c-num">预估花费</span><span class="c-role">优势</span><span class="c-role">劣势</span></div>
          <div v-for="c in AD_COMPETITORS" :key="c.asin" class="tbl-row">
            <span class="c-role"><strong>{{ c.competitor_name }}</strong><br><span class="rev">{{ c.asin }}</span></span>
            <span class="c-num"><strong>{{ c.share_of_voice }}%</strong></span>
            <span class="c-num">{{ c.overlap_keywords }}</span>
            <span class="c-num">{{ c.avg_position }}</span>
            <span class="c-num">${{ c.estimated_spend }}</span>
            <span class="c-role ok-text">{{ c.strengths.join(' / ') }}</span>
            <span class="c-role warn-text">{{ c.weaknesses.join(' / ') }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════ ⑤ 预算分配 ══════════ -->
    <section v-else-if="activeTab === 'budget'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">预算分配 <a-tag color="default" class="mini-tag">优化方案</a-tag></div>
          <div class="pane-sub">当前 ${{ BUDGET_TOTAL_CURRENT }} → 建议 ${{ BUDGET_TOTAL_SUGGESTED }} | 风险: {{ BUDGET_RISK }}</div>
        </div>
      </div>

      <!-- 汇总 KPI -->
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">当前总预算</div><div class="kpi-value">${{ BUDGET_TOTAL_CURRENT }}</div></div>
        <div class="kpi-card"><div class="kpi-label">建议总预算</div><div class="kpi-value success">${{ BUDGET_TOTAL_SUGGESTED }}</div></div>
        <div class="kpi-card"><div class="kpi-label">预期 RoAS 提升</div><div class="kpi-value success">{{ BUDGET_PROJECTED.expected_roas_increase }}</div></div>
        <div class="kpi-card"><div class="kpi-label">预期 ACoS 下降</div><div class="kpi-value success">{{ BUDGET_PROJECTED.expected_acos_decrease }}</div></div>
      </div>

      <!-- 分配表 -->
      <div class="panel-card">
        <div class="card-head">Campaign 预算分配</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">Campaign</span><span class="c-num">当前</span><span class="c-num">建议</span><span class="c-num">占比</span><span class="c-num">预期 RoAS</span><span class="c-role">理由</span></div>
          <div v-for="a in BUDGET_ALLOCATIONS" :key="a.campaign_name" class="tbl-row">
            <span class="c-role">{{ a.campaign_name }}</span>
            <span class="c-num">${{ a.current_budget }}</span>
            <span class="c-num" :class="budgetClass(a)">${{ a.suggested_budget }}</span>
            <span class="c-num">{{ a.allocation_pct }}%</span>
            <span class="c-num ok">{{ a.expected_roas }}x</span>
            <span class="c-role reason-text">{{ a.reason }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════ ⑥ 异常检测 ══════════ -->
    <section v-else-if="activeTab === 'anomaly'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">异常检测 <a-tag color="red" class="mini-tag">{{ ANOMALY_ALERT_COUNT }} 告警</a-tag></div>
          <div class="pane-sub">{{ ANOMALY_SUMMARY }}</div>
        </div>
      </div>

      <!-- 异常卡片 -->
      <div class="anomaly-list">
        <div v-for="(a, idx) in ANOMALIES" :key="idx" class="anomaly-card" :class="'severity-' + a.severity">
          <div class="anomaly-header">
            <span class="anomaly-type">{{ a.type === 'spend_spike' ? '💰 花费飙升' : a.type === 'conversion_drop' ? '📉 转化下降' : a.type === 'impression_anomaly' ? '👁️ 展示异常' : '📊 CTR 异常' }}</span>
            <a-tag :color="a.severity === 'high' ? 'red' : 'orange'" size="small">{{ a.severity === 'high' ? '高风险' : '中风险' }}</a-tag>
          </div>
          <div class="anomaly-body">
            <div class="anomaly-campaign">{{ a.campaign }}</div>
            <div class="anomaly-metric">
              <span class="metric-label">{{ a.metric }}</span>
              <span class="metric-values">
                <span class="current" :class="a.deviation_pct > 0 ? 'danger' : 'warn'">{{ a.current_value }}{{ a.metric.includes('%') || a.metric === 'CTR' ? '%' : a.metric.includes('$') ? '' : '' }}</span>
                <span class="arrow">→</span>
                <span class="expected">{{ a.expected_value }}{{ a.metric.includes('%') || a.metric === 'CTR' ? '%' : a.metric.includes('$') ? '' : '' }}</span>
                <span class="deviation" :class="a.deviation_pct > 0 ? 'danger' : 'warn'">({{ a.deviation_pct > 0 ? '+' : '' }}{{ a.deviation_pct }}%)</span>
              </span>
            </div>
            <div class="anomaly-cause"><strong>可能原因:</strong> {{ a.possible_cause }}</div>
            <div class="anomaly-action"><strong>建议操作:</strong> <span class="action-text">{{ a.suggested_action }}</span></div>
          </div>
          <div class="anomaly-footer">检测于 {{ a.detected_at }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, type Ref } from 'vue'
import LineChart from '@/components/charts/LineChart.vue'
import DonutChart from '@/components/charts/DonutChart.vue'
import {
  AD_OVERALL_SCORE, AD_OVERALL_GRADE, AD_OVERALL_SUMMARY, AD_METRICS, AD_CAMPAIGNS, AD_TOP_ISSUES, AD_RECOMMENDATIONS,
  SEARCH_TERMS, SEARCH_NEW_OPPORTUNITIES, SEARCH_SUGGESTIONS,
  BID_SUGGESTIONS, BID_SUMMARY,
  AD_COMPETITORS, YOUR_SOV, COMPETITOR_INSIGHTS,
  BUDGET_ALLOCATIONS, BUDGET_TOTAL_CURRENT, BUDGET_TOTAL_SUGGESTED, BUDGET_PROJECTED, BUDGET_RISK,
  ANOMALIES, ANOMALY_SUMMARY, ANOMALY_ALERT_COUNT,
  AD_DAILY_TREND,
  fmtPct,
  type BidSuggestion,
  type BudgetAllocation,
} from '@/mock/adDashboard'

const props = defineProps<{ currentToolId?: string }>()
defineEmits<{ (e: 'startAnalysis', params: any): void }>()

// 从 Workspace 注入「对话/大屏」模式
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ──── Tab 定义 ────
const AD_TABS = [
  { key: 'overview', label: '账户总览', icon: '📊' },
  { key: 'searchterms', label: '搜索词', icon: '🔍' },
  { key: 'bid', label: '出价优化', icon: '💡' },
  { key: 'competitor', label: '竞品广告', icon: '🎯' },
  { key: 'budget', label: '预算分配', icon: '📋' },
  { key: 'anomaly', label: '异常检测', icon: '🔔' },
]

const TOOL_TAB_MAP: Record<string, string> = {
  'ad-diagnosis': 'overview',
  'keyword-report': 'searchterms',
  'bid-suggest': 'bid',
  'competitor-ad': 'competitor',
  'budget-alloc': 'budget',
  'anomaly-detect': 'anomaly',
}
const activeTab = ref<string>(TOOL_TAB_MAP[props.currentToolId || ''] || 'overview')
watch(
  () => props.currentToolId,
  (tid) => { const m = TOOL_TAB_MAP[tid || '']; if (m) activeTab.value = m }
)
function switchTab(key: string) { activeTab.value = key }

// ──── 账户总览派生 ────
const trendSeries = computed(() => [
  { name: '花费', color: '#ff6b6b', data: AD_DAILY_TREND.spend },
  { name: '销售额', color: '#51cf66', data: AD_DAILY_TREND.sales },
])

// ──── 竞品 SOV 派生 ────
const sovSegments = computed(() => [
  ...AD_COMPETITORS.map(c => ({ name: c.competitor_name, value: c.share_of_voice, color: ['#5b8ff9', '#5ad8a6', '#f6bd16', '#e8684a'][AD_COMPETITORS.indexOf(c)] })),
  { name: '你', value: YOUR_SOV, color: '#69c0ff' },
])

// ──── 模板辅助函数（避免在模板内写 > 比较，防止 HTML 解析问题）────
function bidClass(b: BidSuggestion): string { return b.bid_change_pct > 0 ? 'ok' : 'warn' }
function bidChangeClass(b: BidSuggestion): string { return b.bid_change_pct > 0 ? 'up' : 'down' }
function budgetClass(a: BudgetAllocation): string { return a.suggested_budget > a.current_budget ? 'ok' : 'warn' }
</script>

<style scoped>
/* ====== 布局（复用 ReviewConfig 的 CSS 体系）====== */
.ad-dashboard { display: flex; flex-direction: column; gap: 10px; height: 100%; min-height: 0; }

/* Tab */
.ad-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--bg-hover-light); border-radius: 10px; flex-shrink: 0; }
.ad-tab { display: inline-flex; align-items: center; gap: 5px; padding: 8px 13px; border: none; background: transparent; border-radius: 8px; cursor: pointer; font-size: 12.5px; font-weight: 500; white-space: nowrap; color: var(--text-secondary); transition: all .15s; }
.ad-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.ad-tab.active { background: var(--bg-elevated); color: var(--primary); box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.ad-tab-icon { font-size: 14px; }

/* Pane */
.ad-pane { display: flex; flex-direction: column; gap: 10px; flex: 1; min-height: 0; overflow: hidden; }
.ad-pane > .pane-head { flex-shrink: 0; }
.ad-pane > .kpi-grid { flex-shrink: 0; }
.ad-pane > .chart-card { flex: 1.2; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.chart-card > :deep(.chart-root) { flex: 1; min-height: 0; }
.ad-pane > .two-col { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ad-pane > .two-col > .panel-card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }

.pane-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.pane-title { font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px; }
.pane-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; line-height: 1.5; }
.mini-tag { font-size: 10px; margin: 0; }

/* KPI */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
.kpi-grid.flex-1 { flex: 1; }
.kpi-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: 10px; padding: 10px 12px; }
.kpi-label { font-size: 11px; color: var(--text-tertiary); }
.kpi-value { font-size: 17px; font-weight: 700; color: var(--text-primary); margin-top: 2px; }
.kpi-value.warning { color: #faad14; }
.kpi-value.danger { color: #ff4d4f; }
.kpi-value.success { color: #52c41a; }
.kpi-change { font-size: 10px; margin-top: 2px; }
.kpi-change .up { color: #52c41a; }
.kpi-change .down { color: #ff4d4f; }
.kpi-change em { font-style: normal; color: var(--text-disabled); }

/* 评分卡片 */
.score-kpi-row { display: flex; gap: 10px; align-items: stretch; }
.score-card { width: 72px; border-radius: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; flex-shrink: 0; }
.score-card.grade-A { background: linear-gradient(135deg, #52c41a, #73d13d); }
.score-card.grade-B { background: linear-gradient(135deg, #faad14, #ffc53d); }
.score-card.grade-C { background: linear-gradient(135deg, #fa8c16, #ffa940); }
.score-card.grade-D { background: linear-gradient(135deg, #ff4d4f, #ff7875); }
.score-val { font-size: 24px; font-weight: 800; color: #fff; }
.grade-label { font-size: 14px; font-weight: 700; color: rgba(255,255,255,.9); }

/* 卡片 */
.panel-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: 10px; padding: 12px 14px; }
.card-head { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.card-head.ok { color: #52c41a; }
.card-head.warn { color: #faad14; }
.card-head.danger { color: #ff4d4f; }

/* 表格 */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 480px) { .two-col { grid-template-columns: 1fr; } }
.tbl { border: 1px solid var(--border-base); border-radius: 8px; overflow: hidden; font-size: 12px; }
.tbl.sm { font-size: 11.5px; }
.tbl-head, .tbl-row { display: flex; align-items: center; gap: 6px; padding: 7px 10px; }
.tbl-head { background: var(--bg-hover-light); font-size: 11px; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border-base); }
.tbl-row { border-bottom: 1px solid var(--border-base); }
.tbl-row:last-child { border-bottom: none; }
.c-role { flex: 2.2; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.c-num { flex: 1; text-align: right; color: var(--text-primary); white-space: nowrap; }
.c-badge { flex: 0.8; text-align: right; }
.ok, .ok-text { color: #52c41a; }
.warn, .warn-text { color: #faad14; }
.danger, .danger-text { color: #ff4d4f; }
.rev { color: var(--text-tertiary); font-size: 10px; }
.reason-text { font-size: 11px; color: var(--text-secondary); }

/* 问题列表 */
.issue-list { display: flex; flex-direction: column; gap: 8px; }
.issue-item { display: flex; align-items: flex-start; gap: 8px; padding: 8px; border-radius: 8px; border-left: 3px solid; }
.issue-item.priority-high { background: rgba(255,77,79,.06); border-color: #ff4d4f; }
.issue-item.priority-medium { background: rgba(250,173,20,.06); border-color: #faad14; }
.issue-rank { width: 20px; height: 20px; border-radius: 50%; background: var(--bg-hover-light); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.issue-content { flex: 1; min-width: 0; }
.issue-title { display: block; font-size: 12.5px; font-weight: 600; color: var(--text-primary); }
.issue-desc { display: block; font-size: 11px; color: var(--text-secondary); margin-top: 2px; line-height: 1.4; }

/* 搜索词列表 */
.term-list { display: flex; flex-direction: column; gap: 6px; }
.term-row { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 5px 0; border-bottom: 1px dashed var(--border-base); }
.term-row:last-child { border-bottom: none; }
.term-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.term-acos { width: 42px; text-align: right; font-weight: 600; }
.term-spend { width: 70px; text-align: right; color: var(--text-secondary); }
.waste-total { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-base); font-size: 12px; font-weight: 600; color: #ff4d4f; text-align: right; }

/* 建议列表 */
.suggestion-list { margin: 0; padding-left: 18px; font-size: 11.5px; color: var(--text-secondary); line-height: 1.9; }
.suggestion-list li { color: var(--text-primary); }

/* 策略说明 */
.rationale { font-size: 12px; color: var(--text-secondary); line-height: 1.7; margin: 0; }

/* 异常卡片 */
.anomaly-list { display: flex; flex-direction: column; gap: 10px; flex: 1; min-height: 0; overflow-y: auto; }
.anomaly-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: 10px; overflow: hidden; border-left: 3px solid; }
.anomaly-card.severity-high { border-left-color: #ff4d4f; }
.anomaly-card.severity-medium { border-left-color: #faad14; }
.anomaly-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--bg-hover-light); }
.anomaly-type { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.anomaly-body { padding: 10px 14px; }
.anomaly-campaign { font-size: 12px; font-weight: 600; color: var(--primary); margin-bottom: 6px; }
.anomaly-metric { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.metric-label { font-size: 11.5px; color: var(--text-secondary); }
.metric-values { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; }
.metric-values .current { color: #ff4d4f; }
.metric-values .expected { color: #52c41a; }
.metric-values .arrow { color: var(--text-disabled); font-size: 12px; }
.metric-values .deviation { font-size: 11px; font-weight: 600; }
.anomaly-cause, .anomaly-action { font-size: 11.5px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 4px; }
.action-text { color: var(--text-primary); }
.anomaly-footer { padding: 6px 14px; font-size: 10px; color: var(--text-disabled); background: var(--bg-hover-light); border-top: 1px solid var(--border-base); }
</style>
