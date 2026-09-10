<template>
  <div class="rv-config">
    <!-- ====== 顶部：6 个数据视图 Tab 导航（仅大屏模式显示；对话模式由顶部工具栏 6 个工具按钮承担切换） ====== -->
    <div v-if="isDataMode" class="rv-tabs">
      <button
        v-for="tab in DATA_VIEW_TABS"
        :key="tab.key"
        class="rv-tab"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        <span class="rv-tab-icon">{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- ① 经营概览 -->
    <section v-if="activeTab === 'overview'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">经营概览 <a-tag color="default" class="mini-tag">近 7 天</a-tag></div>
          <div class="pane-sub">全店核心指标 + 日趋势 + ASIN 排行 + 流量结构（浏览后点「生成本周周报」让 AI 出文字总结）</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div v-for="k in ovKPIs" :key="k.key" class="kpi-card">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value" :class="k.kind">{{ k.value }}</div>
          <div class="kpi-change">
            <span v-if="k.delta !== undefined" :class="k.delta >= 0 ? 'up' : 'down'">
              {{ k.delta >= 0 ? '▲' : '▼' }} {{ Math.abs(k.delta).toFixed(1) }}% <em>环比</em>
            </span>
            <span v-else class="muted">—</span>
          </div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">每日销量 / 销售额走势</div>
        <LineChart :series="dailyRevenueSeries" :labels="DAY_7" :legend="true" />
      </div>

      <div class="two-col flex-block">
        <div class="panel-card">
          <div class="card-head">ASIN 销量排行</div>
          <div class="rank-list">
            <div v-for="(r, i) in rankRows" :key="r.asin" class="rank-row">
              <span class="rank-idx" :class="'idx-' + (i + 1)">{{ i + 1 }}</span>
              <span class="rank-name">
                <span class="rank-asin">{{ r.asin }}</span>{{ r.name }}
              </span>
              <span class="rank-orders">{{ r.sales }} 单</span>
              <span class="rank-bar-track"><i class="rank-bar" :style="{ width: r.pct + '%', background: rankColor(i) }"></i></span>
              <span class="rank-share">{{ r.pct.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
        <div class="panel-card chart-card">
          <div class="card-head">流量占比</div>
          <DonutChart :segments="TRAFFIC_MIX" :center-value="'100%'" center-title="流量构成" />
        </div>
      </div>
    </section>

    <!-- ② 月度数据 -->
    <section v-else-if="activeTab === 'monthly'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">月度数据 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">目标达成 + 整月趋势 + 周对比 + 利润汇总（浏览后点「生成月度复盘」让 AI 出完整复盘）</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">月 GMV</div><div class="kpi-value">${{ fmtMoney(TOTAL_MONTH_REV) }}</div><div class="kpi-change"><span class="up">▲ 15.2% <em>环比</em></span></div></div>
        <div class="kpi-card"><div class="kpi-label">目标完成率</div><div class="kpi-value">{{ targetRate.toFixed(0) }}%</div><div class="goal-track"><i class="goal-fill" :style="{ width: targetRate + '%' }"></i></div></div>
        <div class="kpi-card"><div class="kpi-label">月订单</div><div class="kpi-value">8,920</div><div class="kpi-change"><span class="up">▲ 11.0% <em>环比</em></span></div></div>
        <div class="kpi-card"><div class="kpi-label">月净利润</div><div class="kpi-value success">${{ fmtMoney(NET_MONTH) }}</div><div class="kpi-change"><span class="up">▲ 9.1% <em>环比</em></span></div></div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">整月每日销售趋势（GMV）</div>
        <LineChart :series="[{ name: '销售额', color: '#5b8ff9', data: MONTH_DAILY_REVENUE }]" :labels="dayTicks(30)" :legend="false" />
      </div>

      <div class="two-col flex-block">
        <div class="panel-card chart-card">
          <div class="card-head">周维度对比</div>
          <BarChart :groups="[{ name: 'GMV', color: '#5ad8a6', data: WEEK_GMV.map(w => w.value) }]" :categories="WEEK_GMV.map(w => w.name)" :legend="false" />
        </div>
        <div class="panel-card">
          <div class="card-head">利润汇总（口径）</div>
          <div class="kv-list">
            <div class="kv-row"><span>销售额</span><span>${{ fmtMoney(TOTAL_MONTH_REV) }}</span></div>
            <div class="kv-row"><span>采购成本</span><span>-{{ fmtMoney(COGS_MONTH) }}</span></div>
            <div class="kv-row"><span>平台佣金</span><span>-{{ fmtMoney(COMMISSION_MONTH) }}</span></div>
            <div class="kv-row"><span>FBA 费用</span><span>-{{ fmtMoney(FBA_MONTH) }}</span></div>
            <div class="kv-row"><span>广告花费</span><span>-{{ fmtMoney(ADSPEND_MONTH) }}</span></div>
            <div class="kv-row"><span>仓储/退货</span><span>-{{ fmtMoney(OTHER_COST) }}</span></div>
            <div class="kv-row total"><span>净利润</span><span>${{ fmtMoney(NET_MONTH) }}</span></div>
            <div class="kv-row total"><span>净利率</span><span>{{ (NET_MONTH / TOTAL_MONTH_REV * 100).toFixed(1) }}%</span></div>
          </div>
        </div>
      </div>
    </section>

    <!-- ③ 广告复盘 -->
    <section v-else-if="activeTab === 'ads'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">广告复盘 <a-tag color="default" class="mini-tag">近 7 天</a-tag></div>
          <div class="pane-sub">整体指标 + SP/SB/SD + 广告组/关键词明细（浏览后点「广告优化」让 AI 出调价/否词文案）</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">广告花费</div><div class="kpi-value">${{ fmtMoney(AD_OVERALL.spend) }}</div></div>
        <div class="kpi-card"><div class="kpi-label">广告销售额</div><div class="kpi-value">${{ fmtMoney(AD_OVERALL.sales) }}</div></div>
        <div class="kpi-card"><div class="kpi-label">ACoS</div><div class="kpi-value warning">{{ AD_OVERALL.acos }}%</div></div>
        <div class="kpi-card"><div class="kpi-label">ROAS</div><div class="kpi-value success">{{ AD_OVERALL.roas }}</div></div>
        <div class="kpi-card"><div class="kpi-label">曝光</div><div class="kpi-value">{{ (AD_OVERALL.imp / 1e6).toFixed(2) }}M</div></div>
        <div class="kpi-card"><div class="kpi-label">CVR</div><div class="kpi-value">{{ AD_OVERALL.cvr }}%</div></div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">SP / SB / SD 花费对比</div>
        <BarChart :groups="[{ name: '花费', color: '#e8684a', data: AD_TYPE.spend }, { name: '销售额', color: '#5b8ff9', data: AD_TYPE.sales }]" :categories="AD_TYPE.labels" :legend="true" />
      </div>

      <div class="panel-card">
        <div class="card-head">广告组表现</div>
        <div class="tbl">
          <div class="tbl-head">
            <span class="c-role">广告组</span><span class="c-num">花费</span><span class="c-num">销售额</span>
            <span class="c-num">ACoS</span><span class="c-num">ROAS</span><span class="c-badge">评级</span>
          </div>
          <div v-for="g in AD_GROUPS" :key="g.id" class="tbl-row">
            <span class="c-role"><a-tag color="blue" class="type-tag">{{ g.type }}</a-tag>{{ g.name }}</span>
            <span class="c-num">${{ fmtMoney(g.spend) }}</span>
            <span class="c-num">${{ fmtMoney(g.sales) }}</span>
            <span class="c-num" :class="g.acos > 33 ? 'danger' : g.acos > 25 ? 'warn' : 'ok'">{{ g.acos.toFixed(1) }}%</span>
            <span class="c-num">{{ g.roas.toFixed(2) }}</span>
            <span class="c-badge"><a-tag :color="g.status === '优' ? 'green' : g.status === '中' ? 'orange' : 'red'">{{ g.status }}</a-tag></span>
          </div>
        </div>
      </div>

      <div class="two-col">
        <div class="panel-card">
          <div class="card-head ok">好词（低 ACoS）</div>
          <div class="tbl sm">
            <div class="tbl-head"><span class="c-role">关键词</span><span class="c-num">ACoS</span><span class="c-num">CVR</span></div>
            <div v-for="k in KEYWORDS_GOOD" :key="k.kw" class="tbl-row">
              <span class="c-role">{{ k.kw }}</span><span class="c-num ok">{{ k.acos.toFixed(1) }}%</span><span class="c-num">{{ k.cvr.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head danger">高花费词（待否）</div>
          <div class="tbl sm">
            <div class="tbl-head"><span class="c-role">关键词</span><span class="c-num">花费</span><span class="c-num">ACoS</span></div>
            <div v-for="k in KEYWORDS_BURN" :key="k.kw" class="tbl-row">
              <span class="c-role">{{ k.kw }}</span><span class="c-num">${{ fmtMoney(k.spend) }}</span><span class="c-num danger">{{ k.acos.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">7 天广告趋势</div>
        <LineChart :series="[{ name: '花费', color: '#e8684a', data: AD_TREND_7.spend }, { name: '广告销售额', color: '#5b8ff9', data: AD_TREND_7.sales }]" :labels="DAY_7" />
      </div>
    </section>

    <!-- ④ 商品表现 -->
    <section v-else-if="activeTab === 'products'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">商品表现 <a-tag color="default" class="mini-tag">纯分析看板</a-tag></div>
          <div class="pane-sub">ASIN 表现总览 + 单品趋势 + 评价变动记录</div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">ASIN 表现总览</div>
        <div class="tbl">
          <div class="tbl-head">
            <span class="c-role">商品</span><span class="c-num">BSR</span><span class="c-num">售价</span>
            <span class="c-num">评分</span><span class="c-num">销量7d</span><span class="c-num">CVR</span>
          </div>
          <div v-for="p in PRODUCT_PERF" :key="p.asin" class="tbl-row">
            <span class="c-role">
              <span class="pt-name"><span class="rank-asin">{{ p.asin }}</span>{{ p.name }}</span>
            </span>
            <span class="c-num">#{{ p.bsr }}</span>
            <span class="c-num">${{ p.price.toFixed(2) }}</span>
            <span class="c-num">{{ p.rating }}<span class="star">★</span><span class="rev"> ({{ p.reviews }})</span></span>
            <span class="c-num">{{ p.sales7 }}</span>
            <span class="c-num" :class="p.cvr < 5 ? 'danger' : 'ok'">{{ p.cvr.toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <div class="two-col flex-block">
        <div class="panel-card chart-card">
          <div class="card-head">爆款单品销量趋势（Smart Plug）</div>
          <LineChart :series="[{ name: '销量', color: '#5b8ff9', data: TOP_ASIN_TREND.sales }]" :labels="DAY_7" :legend="false" />
        </div>
        <div class="panel-card chart-card">
          <div class="card-head">BSR 排名走势（越低越好）</div>
          <LineChart :series="[{ name: 'BSR', color: '#f6bd16', data: TOP_ASIN_TREND.bsr }]" :labels="DAY_7" :legend="false" />
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">评价变动记录</div>
        <div class="rv-log">
          <div v-for="c in REVIEW_CHANGES" :key="c.date + c.note" class="rv-log-row">
            <span class="rv-log-date">{{ c.date }}</span>
            <span class="rv-log-asin">{{ c.asin }}</span>
            <a-tag :color="c.delta >= 0 ? 'green' : 'red'" class="rv-log-delta">{{ c.delta >= 0 ? '+' + c.delta : c.delta }}</a-tag>
            <span class="rv-log-note">{{ c.note }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ⑤ 库存健康度 -->
    <section v-else-if="activeTab === 'inventory'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">库存健康度 <a-tag color="default" class="mini-tag">纯分析看板</a-tag></div>
          <div class="pane-sub">库存水位 + 周转 + 风险标签（断货预警 / 滞销）</div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">可售库存水位</div>
        <BarChart :groups="[{ name: '可售', color: '#5b8ff9', data: INVENTORY_LEVEL.map(i => i.level) }]" :categories="INVENTORY_LEVEL.map(i => i.name)" :legend="false" />
      </div>

      <div class="panel-card">
        <div class="card-head">ASIN 库存明细</div>
        <div class="tbl">
          <div class="tbl-head">
            <span class="c-role">商品</span><span class="c-num">可售</span><span class="c-num">在途</span>
            <span class="c-num">日销</span><span class="c-num">周转天数</span><span class="c-badge">风险</span>
          </div>
          <div v-for="it in INVENTORY" :key="it.asin" class="tbl-row">
            <span class="c-role"><span class="rank-asin">{{ it.asin }}</span>{{ it.name }}</span>
            <span class="c-num">{{ it.fulfillable }}</span>
            <span class="c-num">{{ it.inbound }}</span>
            <span class="c-num">{{ it.daily }}</span>
            <span class="c-num" :class="it.days <= 14 ? 'danger' : it.days <= 30 ? 'warn' : 'ok'">{{ it.days }}天</span>
            <span class="c-badge"><a-tag :color="it.riskColor">{{ it.risk }}</a-tag></span>
          </div>
        </div>
      </div>
    </section>

    <!-- ⑥ 利润统计 -->
    <section v-else-if="activeTab === 'profit'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">利润统计 <a-tag color="default" class="mini-tag">纯分析看板</a-tag></div>
          <div class="pane-sub">分 ASIN 利润明细 + 盈亏分类 + 成本结构</div>
        </div>
      </div>

      <div class="two-col flex-block">
        <div class="panel-card chart-card">
          <div class="card-head">成本结构（全店占比）</div>
          <DonutChart :segments="COST_STRUCTURE" center-title="成本结构" :center-value="'$' + fmtMoney(TOTAL_COST)" />
        </div>
        <div class="panel-card">
          <div class="card-head">盈亏分类</div>
          <div class="cat-blocks">
            <div class="cat-block good"><div class="cat-num">{{ profitCats.good }}</div><div class="cat-label">盈利</div></div>
            <div class="cat-block warn"><div class="cat-num">{{ profitCats.breakEven }}</div><div class="cat-label">保本</div></div>
            <div class="cat-block bad"><div class="cat-num">{{ profitCats.loss }}</div><div class="cat-label">亏损</div></div>
          </div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">分 ASIN 利润明细（近 30 天）</div>
        <div class="tbl">
          <div class="tbl-head">
            <span class="c-role">商品</span><span class="c-num">销量</span><span class="c-num">销售额</span>
            <span class="c-num">采购</span><span class="c-num">佣金</span><span class="c-num">FBA</span>
            <span class="c-num">广告分摊</span><span class="c-num">净利</span>
          </div>
          <div v-for="p in profitRows" :key="p.asin" class="tbl-row">
            <span class="c-role"><span class="rank-asin">{{ p.asin }}</span>{{ p.name }}</span>
            <span class="c-num">{{ p.units }}</span>
            <span class="c-num">${{ fmtMoney(p.rev) }}</span>
            <span class="c-num">-{{ fmtMoney(p.cogs) }}</span>
            <span class="c-num">-{{ fmtMoney(p.comm) }}</span>
            <span class="c-num">-{{ fmtMoney(p.fba) }}</span>
            <span class="c-num">-{{ fmtMoney(p.ad) }}</span>
            <span class="c-num" :class="p.net >= 0 ? 'ok' : 'danger'">${{ fmtMoney(p.net) }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject } from 'vue'
import type { Ref } from 'vue'
import LineChart from '@/components/charts/LineChart.vue'
import BarChart from '@/components/charts/BarChart.vue'
import DonutChart from '@/components/charts/DonutChart.vue'
import {
  REVIEW_ASINS, DAILY_SALES, DAY_7, MONTH_DAILY_REVENUE, WEEK_GMV,
  AD_TREND_7, AD_TYPE, AD_GROUPS, KEYWORDS_GOOD, KEYWORDS_BURN, AD_OVERALL, TRAFFIC_MIX,
  PRODUCT_PERF, TOP_ASIN_TREND, REVIEW_CHANGES,
  INVENTORY, INVENTORY_LEVEL, PROFIT_DETAIL, COST_STRUCTURE, TOTAL_MONTH_REV,
} from '@/mock/reviewDashboard'

const props = defineProps<{ currentToolId?: string }>()
defineEmits<{ (e: 'startAnalysis', params: any): void }>()

// 从 Workspace 注入「对话/大屏」模式：大屏模式才显示顶部 6 个 Tab（对话模式由顶部工具栏工具按钮承担切换）
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

const DATA_VIEW_TABS = [
  { key: 'overview', label: '经营概览', icon: '📊' },
  { key: 'monthly', label: '月度数据', icon: '📅' },
  { key: 'ads', label: '广告复盘', icon: '📈' },
  { key: 'products', label: '商品表现', icon: '🛒' },
  { key: 'inventory', label: '库存健康', icon: '📦' },
  { key: 'profit', label: '利润统计', icon: '💰' },
]
const TOOL_TAB_MAP: Record<string, string> = {
  'weekly-report': 'overview',
  'monthly-review': 'monthly',
  'ad-review': 'ads',
  'product-performance': 'products',
  'inventory-health': 'inventory',
  'profit-audit': 'profit',
}
const activeTab = ref<string>(TOOL_TAB_MAP[props.currentToolId || ''] || 'overview')
watch(
  () => props.currentToolId,
  (tid) => { const m = TOOL_TAB_MAP[tid || '']; if (m) activeTab.value = m }
)
function switchTab(key: string) { activeTab.value = key }

// ====== 工具函数 ======
function fmtMoney(v: number): string { return Math.round(v).toLocaleString() }
function asinOf(code: string) { return REVIEW_ASINS.find((a) => a.asin === code)! }
const sum = (arr: number[]) => arr.reduce((a, b) => a + b, 0)

// ====== 经营概览派生 ======
const ovOrders = computed(() => Object.values(DAILY_SALES).reduce((a, s) => a + sum(s), 0))
const ovGmv = computed(() =>
  Object.entries(DAILY_SALES).reduce((a, [asin, arr]) => a + sum(arr) * asinOf(asin).price, 0)
)
const ovCogs = computed(() =>
  Object.entries(DAILY_SALES).reduce((a, [asin, arr]) => a + sum(arr) * asinOf(asin).unitCost, 0)
)
const ovGross = computed(() =>
  ovGmv.value - ovCogs.value
    - Object.entries(DAILY_SALES).reduce((a, [asin, arr]) => a + sum(arr) * asinOf(asin).price * asinOf(asin).commissionRate, 0)
    - Object.entries(DAILY_SALES).reduce((a, [asin, arr]) => a + sum(arr) * asinOf(asin).fbaFee, 0)
    - AD_OVERALL.spend * (7 / 30)
)
const ovKPIs = computed(() => [
  { key: 'gmv', label: '销售额(GMV)', value: '$' + fmtMoney(ovGmv.value), delta: 12.3 },
  { key: 'orders', label: '订单数', value: ovOrders.value.toLocaleString(), delta: 8.1 },
  { key: 'aov', label: '客单价', value: '$' + (ovGmv.value / ovOrders.value).toFixed(2), delta: 3.9 },
  { key: 'gross', label: '毛利', value: '$' + fmtMoney(ovGross.value), delta: 6.5 },
  { key: 'margin', label: '毛利率', value: (ovGross.value / ovGmv.value * 100).toFixed(1) + '%', delta: -0.8, kind: 'soft' },
])
const dailyRevenueSeries = computed(() => {
  // 每一天：各 ASIN 当日销量 × 售价 累加 = 当日销售额
  const perDay = DAY_7.map((_, i) =>
    Object.entries(DAILY_SALES).reduce((acc, [asin, arr]) => acc + arr[i] * asinOf(asin).price, 0)
  )
  return [{ name: '销售额', color: '#5b8ff9', data: perDay }]
})
const rankRows = computed(() => {
  const rows = Object.entries(DAILY_SALES).map(([asin, arr]) => {
    const s = sum(arr); const rev = s * asinOf(asin).price
    return { asin, name: asinOf(asin).name, sales: s, rev }
  }).sort((a, b) => b.sales - a.sales)
  const total = rows.reduce((a, r) => a + r.sales, 0)
  return rows.map((r) => ({ ...r, pct: (r.sales / total) * 100 }))
})
function rankColor(i: number): string {
  return ['#5b8ff9', '#5ad8a6', '#f6bd16', '#e8684a', '#9270ca'][i] || '#5b8ff9'
}

// ====== 月度派生 ======
const targetRate = 92.4
const COGS_MONTH = 68890
const COMMISSION_MONTH = 34376
const FBA_MONTH = 14308
const ADSPEND_MONTH = 35336
const OTHER_COST = 9420
const NET_MONTH = 49290
function dayTicks(len: number) {
  const out: string[] = []
  for (let i = 0; i < len; i += 5) out.push((i + 1) + '日')
  out.push(len + '日')
  return out
}

// ====== 利润派生 ======
const TOTAL_COST = TOTAL_MONTH_REV - NET_MONTH
const profitRows = computed(() =>
  PROFIT_DETAIL.map((p) => {
    const a = asinOf(p.asin)
    const cogs = p.units * a.unitCost
    const comm = p.rev * a.commissionRate
    const fba = p.units * a.fbaFee
    const net = p.rev - cogs - comm - fba - p.adSpend
    return { asin: p.asin, name: p.name, units: p.units, rev: p.rev, cogs, comm, fba, ad: p.adSpend, net }
  })
)
// ====== 引用（防树摇误判，聚合导出常量）======
const profitCats = computed(() => {
  const good = profitRows.value.filter((r) => r.net > 0).length
  const loss = profitRows.value.filter((r) => r.net < 0).length
  return { good, breakEven: profitRows.value.length - good - loss, loss }
})
</script>

<style scoped>
/* 整个看板锁定在面板可视高度内：Tab 固定，内容区吃掉剩余空间，不产生页面滚动条 */
.rv-config { display: flex; flex-direction: column; gap: 10px; height: 100%; min-height: 0; }

/* Tab 导航 */
.rv-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--bg-hover-light); border-radius: 10px; flex-shrink: 0; }
.rv-tab { display: inline-flex; align-items: center; gap: 5px; padding: 8px 13px; border: none; background: transparent; border-radius: 8px; cursor: pointer; font-size: 12.5px; font-weight: 500; white-space: nowrap; color: var(--text-secondary); transition: all .15s; }
.rv-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.rv-tab.active { background: var(--bg-elevated); color: var(--primary); box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.rv-tab-icon { font-size: 14px; }

/* Pane */
.rv-pane { display: flex; flex-direction: column; gap: 10px; flex: 1; min-height: 0; overflow: hidden; }

/* ====== 一屏自适应：固定块按内容高度，图表块吸收剩余高度 ====== */
.rv-pane > .pane-head { flex-shrink: 0; }
.rv-pane > .kpi-grid { flex-shrink: 0; }
/* 图表卡：吸收剩余高度（图表按容器像素绘制，不会被等比撑大） */
.rv-pane > .chart-card { flex: 1.2; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.chart-card > :deep(.chart-root) { flex: 1; min-height: 0; }
/* 含图表的两栏：同样吸收剩余高度 */
.rv-pane > .two-col.flex-block { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.rv-pane > .two-col.flex-block > .panel-card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
/* 纯表格/列表两栏：按内容高度，不抢占图表空间 */
.rv-pane > .two-col:not(.flex-block) { flex-shrink: 0; }
/* 内容超长时只允许「卡片内部」滚动，页面本身不滚 */
.rv-pane .tbl { overflow-y: auto; min-height: 0; }
.rv-pane .rank-list { overflow-y: auto; min-height: 0; }
.pane-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.pane-title { font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px; }
.pane-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; line-height: 1.5; }
.mini-tag { font-size: 10px; margin: 0; }

/* KPI 卡片 */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
.kpi-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: 10px; padding: 10px 12px; }
.kpi-label { font-size: 11px; color: var(--text-tertiary); }
.kpi-value { font-size: 17px; font-weight: 700; color: var(--text-primary); margin-top: 2px; }
.kpi-value.warning { color: #faad14; }
.kpi-value.danger { color: #ff4d4f; }
.kpi-value.success { color: #52c41a; }
.kpi-value.soft { font-size: 15px; }
.kpi-change { font-size: 10px; margin-top: 2px; }
.kpi-change .up { color: #52c41a; }
.kpi-change .down { color: #ff4d4f; }
.kpi-change em { font-style: normal; color: var(--text-disabled); }
.kpi-change .muted { color: var(--text-disabled); }
.goal-track { height: 6px; border-radius: 4px; background: var(--bg-hover-light); margin-top: 6px; overflow: hidden; }
.goal-fill { display: block; height: 100%; background: linear-gradient(90deg, #5b8ff9, #5ad8a6); border-radius: 4px; }

/* 通用卡片 */
.panel-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: 10px; padding: 12px 14px; }
.card-head { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.card-head.ok { color: #52c41a; }
.card-head.danger { color: #ff4d4f; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 480px) { .two-col { grid-template-columns: 1fr; } }

/* ASIN 排行 */
.rank-list { display: flex; flex-direction: column; gap: 8px; }
.rank-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.rank-idx { width: 18px; height: 18px; border-radius: 50%; background: var(--bg-hover-light); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; }
.rank-idx.idx-1 { background: #ffd666; color: #613400; }
.rank-idx.idx-2 { background: #d9d9d9; color: #595959; }
.rank-idx.idx-3 { background: #ffbb96; color: #612500; }
.rank-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.rank-asin { font-family: monospace; font-size: 9px; color: var(--text-tertiary); margin-right: 4px; }
.rank-orders { color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.rank-bar-track { width: 80px; height: 7px; background: var(--bg-hover-light); border-radius: 4px; overflow: hidden; flex-shrink: 0; }
.rank-bar { display: block; height: 100%; border-radius: 4px; }
.rank-share { width: 38px; text-align: right; font-size: 11px; color: var(--text-secondary); }

/* KV 列表 */
.kv-list { display: flex; flex-direction: column; }
.kv-row { display: flex; justify-content: space-between; padding: 6px 2px; font-size: 12.5px; color: var(--text-secondary); border-bottom: 1px dashed var(--border-base); }
.kv-row:last-child { border-bottom: none; }
.kv-row span:last-child { color: var(--text-primary); font-weight: 600; }
.kv-row.total { font-weight: 700; color: var(--text-primary); padding-top: 8px; border-top: 1px solid var(--border-base); border-bottom: none; }
.kv-row.total span:last-child { color: #52c41a; }

/* 表格 */
.tbl { border: 1px solid var(--border-base); border-radius: 8px; overflow: hidden; font-size: 12px; }
.tbl.sm { font-size: 11.5px; }
.tbl-head, .tbl-row { display: flex; align-items: center; gap: 6px; padding: 7px 10px; }
.tbl-head { background: var(--bg-hover-light); font-size: 11px; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border-base); }
.tbl-row { border-bottom: 1px solid var(--border-base); }
.tbl-row:last-child { border-bottom: none; }
.c-role { flex: 2.2; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); display: flex; align-items: center; gap: 4px; }
.c-num { flex: 1; text-align: right; color: var(--text-primary); white-space: nowrap; }
.c-badge { flex: 0.8; text-align: right; }
.pt-name { display: inline-flex; flex-direction: column; line-height: 1.2; }
.type-tag { font-size: 9px; margin-right: 2px; }
.rev { color: var(--text-tertiary); font-size: 10px; }
.star { color: #faad14; font-size: 11px; margin-left: 2px; }
.ok { color: #52c41a; }
.warn { color: #faad14; }
.danger { color: #ff4d4f; }

/* 评价变动日志 */
.rv-log { display: flex; flex-direction: column; gap: 6px; }
.rv-log-row { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 5px 0; border-bottom: 1px dashed var(--border-base); }
.rv-log-row:last-child { border-bottom: none; }
.rv-log-date { color: var(--text-tertiary); font-size: 11px; font-family: monospace; }
.rv-log-asin { font-family: monospace; font-size: 10px; color: var(--text-secondary); }
.rv-log-delta { margin: 0; }
.rv-log-note { flex: 1; color: var(--text-primary); min-width: 0; }

/* 盈亏分类 */
.cat-blocks { display: flex; gap: 8px; }
.cat-block { flex: 1; border-radius: 10px; padding: 12px 8px; text-align: center; }
.cat-block.good { background: rgba(82, 196, 26, .1); border: 1px solid rgba(82,196,26,.3); }
.cat-block.warn { background: rgba(250,173,20,.1); border: 1px solid rgba(250,173,20,.3); }
.cat-block.bad { background: rgba(255,77,79,.1); border: 1px solid rgba(255,77,79,.3); }
.cat-num { font-size: 22px; font-weight: 700; }
.cat-block.good .cat-num { color: #52c41a; }
.cat-block.warn .cat-num { color: #faad14; }
.cat-block.bad .cat-num { color: #ff4d4f; }
.cat-label { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
</style>
