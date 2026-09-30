<template>
  <div class="rv-config">
    <!-- ====== 顶部：5 个数据视图 Tab 导航（仅大屏模式显示；对话模式由顶部工具栏 5 个工具按钮承担切换） ====== -->
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

    <!-- ====== 全局状态条 ======
         第 167 轮（#725）：此前本组件读的是**内联常量**，结构上不可能失败，
         因此也没有任何失败出口 —— 新店铺的第一眼就是满屏别人家的数字。
         接真源后必须把「未选店铺 / 加载中 / 取数失败」三种状态显式说出来。 -->
    <div v-if="banner" class="rv-banner" :class="banner.kind">
      <span class="rv-banner-text">{{ banner.text }}</span>
      <button v-if="banner.retry" class="rv-retry" @click="reload">重试</button>
    </div>

    <!-- ① 经营概览 -->
    <section v-if="activeTab === 'overview'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">经营概览 <a-tag color="default" class="mini-tag">近 7 天</a-tag></div>
          <div class="pane-sub">全店核心指标 + ASIN 销量排行（数据来自 <code>/review/weekly-report</code> 与 <code>/review/product-performance</code>）</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div v-for="m in metricsOf(weekly)" :key="m.label" class="kpi-card">
          <div class="kpi-label">{{ m.label }}</div>
          <div class="kpi-value" :class="kpiClass(m.status)">{{ formatMetric(m) }}</div>
          <div v-if="m.delta_pct != null" class="kpi-change">
            <span :class="m.delta_pct >= 0 ? 'up' : 'down'">
              {{ m.delta_pct >= 0 ? '▲' : '▼' }} {{ Math.abs(m.delta_pct).toFixed(1) }}% <em>环比</em>
            </span>
          </div>
          <div v-else class="kpi-change"><span class="muted">—</span></div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">每日销量 / 销售额走势</div>
        <UnsupportedNote label="逐日销售序列" />
      </div>

      <div class="two-col flex-block">
        <div class="panel-card">
          <div class="card-head">ASIN 销量排行（近 7 天）</div>
          <div v-if="rankRows.length" class="rank-list">
            <div v-for="(r, i) in rankRows" :key="r.asin" class="rank-row">
              <span class="rank-idx" :class="'idx-' + (i + 1)">{{ i + 1 }}</span>
              <span class="rank-name"><span class="rank-asin">{{ r.asin }}</span></span>
              <span class="rank-orders">{{ r.units }} 件</span>
              <span class="rank-bar-track"><i class="rank-bar" :style="{ width: r.pct + '%', background: rankColor(i) }"></i></span>
              <span class="rank-share">{{ r.pct.toFixed(1) }}%</span>
            </div>
          </div>
          <div v-else class="rv-unsupported"><span class="rv-unsupported-icon">∅</span><span>该店铺在所选周期内没有商品销量记录。</span></div>
        </div>
        <div class="panel-card">
          <div class="card-head">流量占比</div>
          <UnsupportedNote label="自然 / 广告 / 关联流量的拆分口径" />
        </div>
      </div>
    </section>

    <!-- ② 月度数据 -->
    <section v-else-if="activeTab === 'monthly'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">月度数据 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">月 GMV / 净利率 / 退货率 / 广告占比 + 利润口径（数据来自 <code>/review/monthly-review</code>）</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div v-for="m in metricsOf(monthly)" :key="m.label" class="kpi-card">
          <div class="kpi-label">{{ m.label }}</div>
          <div class="kpi-value" :class="kpiClass(m.status)">{{ formatMetric(m) }}</div>
          <div v-if="m.delta_pct != null" class="kpi-change">
            <span :class="m.delta_pct >= 0 ? 'up' : 'down'">
              {{ m.delta_pct >= 0 ? '▲' : '▼' }} {{ Math.abs(m.delta_pct).toFixed(1) }}% <em>环比</em>
            </span>
          </div>
          <div v-else class="kpi-change"><span class="muted">—</span></div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">整月每日销售趋势（GMV）</div>
        <UnsupportedNote label="30 天逐日 GMV 序列" />
      </div>

      <div class="two-col flex-block">
        <div class="panel-card">
          <div class="card-head">周维度对比</div>
          <UnsupportedNote label="按自然周聚合的 GMV 对比" />
        </div>
        <div class="panel-card">
          <div class="card-head">利润汇总（后端可提供项）</div>
          <div class="kv-list">
            <div class="kv-row"><span>销售额</span><span>${{ fmtMoney(sales(monthly)?.revenue) }}</span></div>
            <div class="kv-row"><span>退款</span><span>-{{ fmtMoney(sales(monthly)?.refunds) }}</span></div>
            <div class="kv-row"><span>净收入</span><span>${{ fmtMoney(sales(monthly)?.net_revenue) }}</span></div>
            <div class="kv-row"><span>广告花费</span><span>-{{ fmtMoney(ad(monthly)?.spend) }}</span></div>
            <div class="kv-row total"><span>预估利润</span><span>${{ fmtMoney(sales(monthly)?.estimated_profit) }}</span></div>
          </div>
          <div class="rv-mini-note">采购成本 / FBA 费用 / 仓储的逐项拆分后端不提供，故不列出（旧版本的这几个数字是内联编造的）。</div>
        </div>
      </div>
    </section>

    <!-- ④ 商品表现 -->
    <section v-else-if="activeTab === 'products'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">商品表现 <a-tag color="default" class="mini-tag">近 7 天</a-tag></div>
          <div class="pane-sub">ASIN 级销量 / 销售额 / 利润 / 评分 / BSR / 可售天数（数据来自 <code>/review/product-performance</code>）</div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">ASIN 表现总览</div>
        <div v-if="products.length" class="tbl">
          <div class="tbl-head">
            <span class="c-role">ASIN</span><span class="c-num">销量</span><span class="c-num">销售额</span>
            <span class="c-num">利润</span><span class="c-num">评分</span><span class="c-num">BSR</span>
            <span class="c-num">可售天数</span><span class="c-badge">健康</span>
          </div>
          <div v-for="p in products" :key="p.asin" class="tbl-row">
            <span class="c-role"><span class="rank-asin">{{ p.asin }}</span></span>
            <span class="c-num">{{ p.units }}</span>
            <span class="c-num">${{ fmtMoney(p.revenue) }}</span>
            <span class="c-num" :class="p.profit >= 0 ? 'ok' : 'danger'">${{ fmtMoney(p.profit) }}</span>
            <span class="c-num">{{ p.rating != null ? p.rating.toFixed(1) + '★' : '—' }}</span>
            <span class="c-num">{{ p.bsr_rank != null ? '#' + p.bsr_rank : '—' }}</span>
            <span class="c-num" :class="p.days_supply != null ? bandOf('restockDays', p.days_supply) : ''">{{ p.days_supply != null ? p.days_supply + '天' : '—' }}</span>
            <span class="c-badge"><a-tag :color="healthTag(p.health_status).color">{{ healthTag(p.health_status).label }}</a-tag></span>
          </div>
        </div>
        <div v-else class="rv-unsupported"><span class="rv-unsupported-icon">∅</span><span>该店铺在所选周期内没有商品销量记录。</span></div>
      </div>

      <div class="two-col flex-block">
        <div class="panel-card">
          <div class="card-head">爆款单品销量趋势</div>
          <UnsupportedNote label="单品逐日销量序列" />
        </div>
        <div class="panel-card">
          <div class="card-head">BSR 排名走势（越低越好）</div>
          <UnsupportedNote label="单品逐日 BSR 序列" />
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">评价变动记录</div>
        <UnsupportedNote label="评论增减事件流" />
      </div>
    </section>

    <!-- ⑤ 库存健康度 -->
    <section v-else-if="activeTab === 'inventory'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">库存健康度 <a-tag color="default" class="mini-tag">当前快照</a-tag></div>
          <div class="pane-sub">可售水位 + 在途 + 周转天数 + 风险标签（数据来自 <code>/review/inventory-health</code>）</div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">可售库存水位</div>
        <BarChart
          v-if="inventory.length"
          :groups="[{ name: '可售', color: 'var(--chart-1)', data: inventory.map(i => i.fulfillable) }]"
          :categories="inventory.map(i => i.asin)"
          :legend="false"
        />
        <div v-else class="rv-unsupported"><span class="rv-unsupported-icon">∅</span><span>该店铺没有库存记录。</span></div>
      </div>

      <div class="panel-card">
        <div class="card-head">ASIN 库存明细</div>
        <div v-if="inventory.length" class="tbl">
          <div class="tbl-head">
            <span class="c-role">ASIN / SKU</span><span class="c-num">可售</span><span class="c-num">在途</span>
            <span class="c-num">周转天数</span><span class="c-badge">风险</span>
          </div>
          <div v-for="it in inventory" :key="it.asin" class="tbl-row">
            <span class="c-role">
              <span class="pt-name">
                <span class="rank-asin">{{ it.asin }}</span>
                <span class="rev">{{ it.sku }}</span>
              </span>
            </span>
            <span class="c-num">{{ it.fulfillable }}</span>
            <span class="c-num">{{ it.inbound }}</span>
            <span class="c-num" :class="bandOf('restockDays', it.days_supply)">{{ it.days_supply }}天</span>
            <span class="c-badge"><a-tag :color="healthTag(it.health_status).color">{{ healthTag(it.health_status).label }}</a-tag></span>
          </div>
        </div>
        <div v-else class="rv-unsupported"><span class="rv-unsupported-icon">∅</span><span>该店铺没有库存记录。</span></div>
      </div>
    </section>

    <!-- ⑥ 利润统计 -->
    <section v-else-if="activeTab === 'profit'" class="rv-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">利润统计 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">利润构成 + 分 ASIN 利润（数据来自 <code>/review/profit-audit</code> 与 <code>/review/monthly-review</code> 的 SKU 贡献）</div>
        </div>
      </div>

      <div class="two-col flex-block">
        <div class="panel-card">
          <div class="card-head">利润构成（后端可提供项）</div>
          <div class="kv-list">
            <div class="kv-row"><span>销售额</span><span>${{ fmtMoney(sales(profit)?.revenue) }}</span></div>
            <div class="kv-row"><span>平台佣金（后端按 15% 估）</span><span>-{{ fmtMoney(profit?.details?.commission) }}</span></div>
            <div class="kv-row"><span>广告花费</span><span>-{{ fmtMoney(ad(profit)?.spend) }}</span></div>
            <div class="kv-row"><span>退款</span><span>-{{ fmtMoney(sales(profit)?.refunds) }}</span></div>
            <div class="kv-row total"><span>净利润</span><span>${{ fmtMoney(sales(profit)?.estimated_profit) }}</span></div>
          </div>
          <div class="rv-mini-note">采购成本 / FBA 费用的分项拆分后端不提供，故不列出。</div>
        </div>
        <div class="panel-card">
          <div class="card-head">盈亏分类（按 SKU）</div>
          <div class="cat-blocks">
            <div class="cat-block good"><div class="cat-num">{{ profitCats.good }}</div><div class="cat-label">盈利</div></div>
            <div class="cat-block warn"><div class="cat-num">{{ profitCats.breakEven }}</div><div class="cat-label">保本</div></div>
            <div class="cat-block bad"><div class="cat-num">{{ profitCats.loss }}</div><div class="cat-label">亏损</div></div>
          </div>
          <div class="rv-mini-note">按 SKU 贡献排名的利润正负号统计；共 {{ skuRank.length }} 个 SKU。</div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">分 ASIN 利润明细（近 30 天）</div>
        <div v-if="skuRank.length" class="tbl">
          <div class="tbl-head">
            <span class="c-role">ASIN</span><span class="c-num">销量</span><span class="c-num">销售额</span><span class="c-num">利润</span>
          </div>
          <div v-for="r in skuRank" :key="r.asin" class="tbl-row">
            <span class="c-role"><span class="rank-asin">{{ r.asin }}</span></span>
            <span class="c-num">{{ r.units }}</span>
            <span class="c-num">${{ fmtMoney(r.revenue) }}</span>
            <span class="c-num" :class="r.profit >= 0 ? 'ok' : 'danger'">${{ fmtMoney(r.profit) }}</span>
          </div>
        </div>
        <div v-else class="rv-unsupported"><span class="rv-unsupported-icon">∅</span><span>该店铺在所选周期内没有 SKU 贡献记录。</span></div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { CHART_VARS } from '@/theme/semantic'
import { bandOf } from '@/theme/bands'
import { ref, computed, watch, inject, reactive } from 'vue'
import type { Ref } from 'vue'
// ★ 只留 BarChart：LineChart / DonutChart 的图位全部是「后端不提供该维度」的
//   占位（逐日序列、流量占比、成本结构拆分），旧版本那几张图画的都是内联假数据。
import BarChart from '@/components/charts/BarChart.vue'
import UnsupportedNote from './ReviewUnsupportedNote.vue'
import { useShopStore } from '@/stores/shop'
import {
  REVIEW_FETCHERS,
  type ReviewAdSum,
  type ReviewInventoryItem,
  type ReviewMetric,
  type ReviewProductPerf,
  type ReviewReport,
  type ReviewResponse,
  type ReviewSalesSum,
  type ReviewSkuRank,
  type ReviewToolId,
} from '@/api/review'

const props = defineProps<{ currentToolId?: string }>()
defineEmits<{ (e: 'startAnalysis', params: any): void }>()

// 从 Workspace 注入「对话/大屏」模式：大屏模式才显示顶部 5 个 Tab（对话模式由顶部工具栏工具按钮承担切换）
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

const shopStore = useShopStore()

const DATA_VIEW_TABS = [
  { key: 'overview', label: '经营概览', icon: '📊' },
  { key: 'monthly', label: '月度数据', icon: '📅' },
  { key: 'products', label: '商品表现', icon: '🛒' },
  { key: 'inventory', label: '库存健康', icon: '📦' },
  { key: 'profit', label: '利润统计', icon: '💰' },
]
const TOOL_TAB_MAP: Record<string, string> = {
  'weekly-report': 'overview',
  'monthly-review': 'monthly',
  'product-performance': 'products',
  'inventory-health': 'inventory',
  'profit-audit': 'profit',
}

type TabKey = 'overview' | 'monthly' | 'products' | 'inventory' | 'profit'

/**
 * 每个 Tab 需要哪些端点、用哪个周期。
 *
 * ★ 为什么 overview 也拉 `product-performance`：概览要显示「ASIN 销量排行」，
 *   而后端的 `weekly-report` 只给**汇总**（`details.sales` 一个对象），
 *   没有任何 per-ASIN 拆分 —— 唯一能出这张表的端点就是 `product-performance`。
 * ★ 为什么 profit 也拉 `monthly-review`：`profit-audit` 只给全店汇总，
 *   分 ASIN 的 revenue/profit 只有 `monthly-review` 的 `sku_rank` 有。
 *   （这两处都是**实测后端返回**得出的，不是照抄旧 mock 的字段想象。）
 */
const TAB_DEFS: Record<TabKey, { days: number; loads: ReviewToolId[] }> = {
  overview: { days: 7, loads: ['weekly-report', 'product-performance'] },
  monthly: { days: 30, loads: ['monthly-review'] },
  products: { days: 7, loads: ['product-performance'] },
  inventory: { days: 7, loads: ['inventory-health'] },
  profit: { days: 30, loads: ['profit-audit', 'monthly-review'] },
}

// ====== 取数状态 ======
const reports = reactive<Record<string, ReviewReport | null>>({})
const loading = ref(false)
const loadError = ref('')

const activeTab = ref<TabKey>((TOOL_TAB_MAP[props.currentToolId || ''] as TabKey) || 'overview')
watch(
  () => props.currentToolId,
  (tid) => { const m = TOOL_TAB_MAP[tid || '']; if (m) activeTab.value = m as TabKey }
)

const noShop = computed(() => !shopStore.currentShopId)

const banner = computed<{ kind: string; text: string; retry: boolean } | null>(() => {
  if (noShop.value) {
    return {
      kind: 'warn',
      text: '尚未选择店铺 —— 复盘数据一律按店铺维度取数，请先在界面左上角选择一个店铺。',
      retry: false,
    }
  }
  if (loadError.value) return { kind: 'error', text: loadError.value, retry: true }
  if (loading.value) return { kind: 'info', text: '正在加载复盘数据…', retry: false }
  return null
})

async function loadTab(tab: TabKey) {
  if (noShop.value) return
  const def = TAB_DEFS[tab]
  const missing = def.loads.filter((id) => !reports[id])
  if (!missing.length) return
  loading.value = true
  loadError.value = ''
  try {
    const results: ReviewResponse[] = await Promise.all(
      missing.map((id) => REVIEW_FETCHERS[id](def.days))
    )
    results.forEach((res, i) => {
      const id = missing[i]
      if (res?.success && res.data) {
        reports[id] = res.data
      } else {
        // 200 但 success=false：**不许**当成「没数据所以空着」——
        // 那是本仓「降级路径禁用全 0 兜底」的同一类错误：假数据冒充实测。
        //
        // ★ 不读 `res.message`（第 268 轮 B 档）：信封里的 `message` 是**成功回执**
        //   （「周报已生成」），不是失败原因。拿它当报错，红条上会写「周报已生成」
        //   这种自相矛盾的话。这 6 个端点走 router 的 `_report` ⇒ 恒 `success=True`，
        //   失败一律 4xx/5xx（走下面的 catch）⇒ 真走到这里就说明契约破了，必须说出来。
        loadError.value = '后端返回了失败标记（success=false），但未提供报告数据。'
      }
    })
  } catch (e: any) {
    const status = e?.response?.status
    loadError.value =
      e?.response?.data?.detail ||
      (status === 403
        ? '当前账号无权访问该店铺的复盘数据，请切换店铺后重试。'
        : '复盘数据加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function reload() {
  Object.keys(reports).forEach((k) => { reports[k] = null })
  void loadTab(activeTab.value)
}

watch(activeTab, (t) => { void loadTab(t) })

// ★ 换店铺必须**清缓存**：否则会把上一个店铺的复盘数字继续显示在新店铺名下
//   —— 那是跨租户串数据，比「没数据」严重得多（本仓「上下文不变量按写入点收口」那条）。
watch(
  () => shopStore.currentShopId,
  (id) => {
    if (!id) return
    Object.keys(reports).forEach((k) => { reports[k] = null })
    loadError.value = ''
    void loadTab(activeTab.value)
  },
  { immediate: true }
)

function switchTab(key: string) {
  activeTab.value = key as TabKey
}

// ====== 报告 / 明细取用 ======
const weekly = computed(() => reports['weekly-report'] ?? null)
const monthly = computed(() => reports['monthly-review'] ?? null)
const prods = computed(() => reports['product-performance'] ?? null)
const profit = computed(() => reports['profit-audit'] ?? null)

const inventory = computed<ReviewInventoryItem[]>(
  () => (reports['inventory-health']?.details?.items ?? []) as ReviewInventoryItem[]
)
const products = computed<ReviewProductPerf[]>(
  () => (prods.value?.details?.products ?? []) as ReviewProductPerf[]
)
const skuRank = computed<ReviewSkuRank[]>(
  () => (monthly.value?.details?.sku_rank ?? []) as ReviewSkuRank[]
)

function metricsOf(rep: ReviewReport | null): ReviewMetric[] {
  return rep?.metrics ?? []
}
function sales(rep: ReviewReport | null): ReviewSalesSum | undefined {
  return rep?.details?.sales as ReviewSalesSum | undefined
}
function ad(rep: ReviewReport | null): ReviewAdSum | undefined {
  return rep?.details?.ad as ReviewAdSum | undefined
}

// ====== 格式化 ======
function fmtMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return Math.round(v).toLocaleString()
}
function formatMetric(m: ReviewMetric): string {
  if (m.unit === 'USD') return '$' + fmtMoney(m.value)
  if (m.unit === '%') return m.value + '%'
  const num = Number.isInteger(m.value) ? m.value.toLocaleString() : m.value.toFixed(2)
  return num + (m.unit || '')
}
function kpiClass(status?: string): string {
  if (status === 'good') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'critical') return 'danger'
  return ''
}
const HEALTH_TAG: Record<string, { color: string; label: string }> = {
  HEALTHY: { color: 'green', label: '健康' },
  WARNING: { color: 'orange', label: '预警' },
  CRITICAL: { color: 'red', label: '断货风险' },
  STAGNANT: { color: 'default', label: '滞销' },
  UNKNOWN: { color: 'default', label: '未知' },
}
function healthTag(status: string): { color: string; label: string } {
  return HEALTH_TAG[status] || HEALTH_TAG.UNKNOWN
}

// ====== 派生 ======
const rankRows = computed(() => {
  const rows = products.value.slice().sort((a, b) => b.units - a.units)
  const total = rows.reduce((a, r) => a + r.units, 0)
  return rows.map((r) => ({
    asin: r.asin,
    units: r.units,
    pct: total ? (r.units / total) * 100 : 0,
  }))
})
function rankColor(i: number): string {
  return CHART_VARS[i % CHART_VARS.length]
}

const profitCats = computed(() => {
  const rows = skuRank.value
  const good = rows.filter((r) => r.profit > 0).length
  const loss = rows.filter((r) => r.profit < 0).length
  return { good, loss, breakEven: rows.length - good - loss }
})
</script>

<style scoped>
/* 整个看板锁定在面板可视高度内：Tab 固定，内容区吃掉剩余空间，不产生页面滚动条 */
.rv-config { display: flex; flex-direction: column; gap: var(--space-10); height: 100%; min-height: 0; }

/* Tab 导航 */
.rv-tabs { display: flex; flex-wrap: wrap; gap: var(--space-4); padding: var(--space-4); background: var(--bg-hover-light); border-radius: var(--radius-10); flex-shrink: 0; }
.rv-tab { display: inline-flex; align-items: center; gap: var(--space-5); padding: var(--space-8) 13px; border: none; background: transparent; border-radius: var(--radius-8); cursor: pointer; font-size: var(--font-size-12-5); font-weight: 500; white-space: nowrap; color: var(--text-secondary); transition: all .15s; }
.rv-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.rv-tab.active { background: var(--bg-elevated); color: var(--primary); box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.rv-tab-icon { font-size: var(--font-size-14); }

/* Pane */
.rv-pane { display: flex; flex-direction: column; gap: var(--space-10); flex: 1; min-height: 0; overflow: hidden; }

/* ====== 一屏自适应：固定块按内容高度，图表块吸收剩余高度 ====== */
.rv-pane > .pane-head { flex-shrink: 0; }
.rv-pane > .kpi-grid { flex-shrink: 0; }
/* 图表卡：吸收剩余高度（图表按容器像素绘制，不会被等比撑大） */
.rv-pane > .chart-card { flex: 1.2; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.chart-card > :deep(.chart-root) { flex: 1; min-height: 0; }
/* 含图表的两栏：同样吸收剩余高度 */
.rv-pane > .two-col.flex-block { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-10); }
.rv-pane > .two-col.flex-block > .panel-card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
/* 纯表格/列表两栏：按内容高度，不抢占图表空间 */
.rv-pane > .two-col:not(.flex-block) { flex-shrink: 0; }
/* 内容超长时只允许「卡片内部」滚动，页面本身不滚 */
.rv-pane .tbl { overflow-y: auto; min-height: 0; }
.rv-pane .rank-list { overflow-y: auto; min-height: 0; }
.pane-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-8); }
.pane-title { font-size: var(--font-size-15); font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: var(--space-6); }
.pane-sub { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); line-height: 1.5; }
.mini-tag { font-size: var(--font-size-10); margin: 0; }

/* KPI 卡片 */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: var(--space-8); }
.kpi-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: var(--radius-10); padding: var(--space-10) var(--space-12); }
.kpi-label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.kpi-value { font-size: var(--font-size-17); font-weight: 700; color: var(--text-primary); margin-top: var(--space-2); }
.kpi-value.warning { color: var(--warning); }
.kpi-value.danger { color: var(--danger); }
.kpi-value.success { color: var(--success); }
.kpi-value.soft { font-size: var(--font-size-15); }
.kpi-change { font-size: var(--font-size-10); margin-top: var(--space-2); }
.kpi-change .up { color: var(--success); }
.kpi-change .down { color: var(--danger); }
.kpi-change em { font-style: normal; color: var(--text-disabled); }
.kpi-change .muted { color: var(--text-disabled); }
.goal-track { height: 6px; border-radius: var(--radius-4); background: var(--bg-hover-light); margin-top: var(--space-6); overflow: hidden; }
.goal-fill { display: block; height: 100%; background: linear-gradient(90deg, #5b8ff9, #5ad8a6); border-radius: var(--radius-4); }

/* 通用卡片 */
.panel-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: var(--radius-10); padding: var(--space-12) var(--space-14); }
.card-head { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-8); }
.card-head.ok { color: var(--success); }
.card-head.danger { color: var(--danger); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-12); }
@media (max-width: 480px) { .two-col { grid-template-columns: 1fr; } }

/* ====== 状态条与「后端未提供」占位（第 167 轮 #725 新增） ====== */
.rv-banner { display: flex; align-items: center; gap: var(--space-8); padding: var(--space-8) var(--space-12); border-radius: var(--radius-8); border: 1px solid transparent; font-size: var(--font-size-12); flex-shrink: 0; }
.rv-banner.info { background: var(--bg-hover-light); color: var(--text-secondary); border-color: var(--border-base); }
.rv-banner.warn { background: rgba(250,173,20,.1); color: var(--warning); border-color: rgba(250,173,20,.35); }
.rv-banner.error { background: rgba(255,77,79,.1); color: var(--danger); border-color: rgba(255,77,79,.35); }
.rv-banner-text { flex: 1; min-width: 0; line-height: 1.5; }
.rv-retry { border: 1px solid currentColor; background: transparent; color: inherit; border-radius: var(--radius-8); padding: 2px 10px; font-size: var(--font-size-11); cursor: pointer; white-space: nowrap; }
.rv-unsupported { display: flex; align-items: center; gap: var(--space-6); min-height: 56px; padding: var(--space-12) var(--space-14); border: 1px dashed var(--border-base); border-radius: var(--radius-10); background: var(--bg-hover-light); color: var(--text-tertiary); font-size: var(--font-size-11-5); line-height: 1.6; }
.rv-unsupported-icon { font-size: var(--font-size-15); opacity: .7; }
.rv-mini-note { margin-top: var(--space-8); font-size: var(--font-size-10-5); color: var(--text-tertiary); line-height: 1.6; }

/* ASIN 排行 */
.rank-list { display: flex; flex-direction: column; gap: var(--space-8); }
.rank-row { display: flex; align-items: center; gap: var(--space-8); font-size: var(--font-size-12); }
.rank-idx { width: 18px; height: 18px; border-radius: var(--radius-circle); background: var(--bg-hover-light); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; font-size: var(--font-size-10); font-weight: 700; flex-shrink: 0; }
.rank-idx.idx-1 { background: #ffd666; color: #613400; }
.rank-idx.idx-2 { background: #d9d9d9; color: var(--text-secondary); }
.rank-idx.idx-3 { background: #ffbb96; color: #612500; }
.rank-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.rank-asin { font-family: monospace; font-size: var(--font-size-9); color: var(--text-tertiary); margin-right: var(--space-4); }
.rank-orders { color: var(--text-secondary); font-size: var(--font-size-11); white-space: nowrap; }
.rank-bar-track { width: 80px; height: 7px; background: var(--bg-hover-light); border-radius: var(--radius-4); overflow: hidden; flex-shrink: 0; }
.rank-bar { display: block; height: 100%; border-radius: var(--radius-4); }
.rank-share { width: 38px; text-align: right; font-size: var(--font-size-11); color: var(--text-secondary); }

/* KV 列表 */
.kv-list { display: flex; flex-direction: column; }
.kv-row { display: flex; justify-content: space-between; padding: var(--space-6) var(--space-2); font-size: var(--font-size-12-5); color: var(--text-secondary); border-bottom: 1px dashed var(--border-base); }
.kv-row:last-child { border-bottom: none; }
.kv-row span:last-child { color: var(--text-primary); font-weight: 600; }
.kv-row.total { font-weight: 700; color: var(--text-primary); padding-top: var(--space-8); border-top: 1px solid var(--border-base); border-bottom: none; }
.kv-row.total span:last-child { color: var(--success); }

/* 表格 */
.tbl { border: 1px solid var(--border-base); border-radius: var(--radius-8); overflow: hidden; font-size: var(--font-size-12); }
.tbl.sm { font-size: var(--font-size-11-5); }
.tbl-head, .tbl-row { display: flex; align-items: center; gap: var(--space-6); padding: 7px var(--space-10); }
.tbl-head { background: var(--bg-hover-light); font-size: var(--font-size-11); font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border-base); }
.tbl-row { border-bottom: 1px solid var(--border-base); }
.tbl-row:last-child { border-bottom: none; }
.c-role { flex: 2.2; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); display: flex; align-items: center; gap: var(--space-4); }
.c-num { flex: 1; text-align: right; color: var(--text-primary); white-space: nowrap; }
.c-badge { flex: 0.8; text-align: right; }
.pt-name { display: inline-flex; flex-direction: column; line-height: 1.2; }
.type-tag { font-size: var(--font-size-9); margin-right: var(--space-2); }
.rev { color: var(--text-tertiary); font-size: var(--font-size-10); }
.star { color: var(--warning); font-size: var(--font-size-11); margin-left: var(--space-2); }
.ok { color: var(--success); }
.warn { color: var(--warning); }
.danger { color: var(--danger); }

/* 评价变动日志 */
.rv-log { display: flex; flex-direction: column; gap: var(--space-6); }
.rv-log-row { display: flex; align-items: center; gap: var(--space-8); font-size: var(--font-size-12); padding: var(--space-5) 0; border-bottom: 1px dashed var(--border-base); }
.rv-log-row:last-child { border-bottom: none; }
.rv-log-date { color: var(--text-tertiary); font-size: var(--font-size-11); font-family: monospace; }
.rv-log-asin { font-family: monospace; font-size: var(--font-size-10); color: var(--text-secondary); }
.rv-log-delta { margin: 0; }
.rv-log-note { flex: 1; color: var(--text-primary); min-width: 0; }

/* 盈亏分类 */
.cat-blocks { display: flex; gap: var(--space-8); }
.cat-block { flex: 1; border-radius: var(--radius-10); padding: var(--space-12) var(--space-8); text-align: center; }
.cat-block.good { background: rgba(82, 196, 26, .1); border: 1px solid rgba(82,196,26,.3); }
.cat-block.warn { background: rgba(250,173,20,.1); border: 1px solid rgba(250,173,20,.3); }
.cat-block.bad { background: rgba(255,77,79,.1); border: 1px solid rgba(255,77,79,.3); }
.cat-num { font-size: var(--font-size-22); font-weight: 700; }
.cat-block.good .cat-num { color: var(--success); }
.cat-block.warn .cat-num { color: var(--warning); }
.cat-block.bad .cat-num { color: var(--danger); }
.cat-label { font-size: var(--font-size-11); color: var(--text-secondary); margin-top: var(--space-2); }
</style>
