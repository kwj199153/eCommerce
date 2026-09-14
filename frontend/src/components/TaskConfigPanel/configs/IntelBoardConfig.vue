<template>
  <!--
    竞品监控大屏（右侧边栏）
    ========================
    原「竞品监控工作台」是 Workspace 左侧导航下的独立整页视图；现搬入竞品监控员的
    右侧边栏，视觉骨架对齐运营复盘大屏（ReviewConfig）：胶囊 Tab → pane-head 说明
    → KPI 卡网格 → 卡片容器。

    数据源是唯一一份 `monitorPool`：六个追踪视角读的都是「监控池已圈选」的 ASIN，
    所以换 Tab 不会换数据，只是换视角 —— 这是本工作台的核心主张。
  -->
  <div class="ib-config">
    <!-- 胶囊 Tab。窄边栏（对话模式）下不渲染，避免挤成一坨没法点 -->
    <div v-if="isDataMode" class="ib-tabs">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        class="ib-tab"
        :class="{ active: activeTab === t.key }"
        @click="activeTab = t.key"
      >
        <span class="ib-tab-icon">{{ t.icon }}</span>{{ t.name }}
      </button>
    </div>

    <!-- 告警条：全池提醒聚合，跨面板常驻 -->
    <div v-if="alertList.length" class="ib-alert-bar">
      <span class="ib-alert-title">🔔 今日需关注</span>
      <a-tag v-for="(a, i) in alertList" :key="i" :color="a.color">{{ a.text }}</a-tag>
    </div>

    <!-- ================= 监控池 ================= -->
    <section v-if="activeTab === 'pool'" class="ib-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">
            🗂️ 监控池
            <a-tag color="default" class="mini-tag">{{ pool.totalCount }} 个 ASIN</a-tag>
          </div>
          <div class="pane-sub">勾选要分析的竞品，右侧六个视角共用这一份数据；增删与分组到「资料库 → 竞品监控池」</div>
        </div>
        <a-button size="small" @click="goToLibrary"><FolderOpenOutlined /> 资料库</a-button>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">在池竞品</div>
          <div class="kpi-value">{{ pool.totalCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">已圈选</div>
          <div class="kpi-value" :class="{ success: selectedCount > 0 }">{{ selectedCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">分组</div>
          <div class="kpi-value soft">{{ pool.groups.length }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">待关注</div>
          <div class="kpi-value" :class="{ danger: alertTotal > 0 }">{{ alertTotal }}</div>
        </div>
      </div>

      <div class="panel-card grow-card">
        <div class="card-head">
          竞品清单
          <a-button size="small" type="link" :disabled="!pool.totalCount" @click="pool.setSelected(pool.records.map(r => r.asin))">
            全选
          </a-button>
          <a-button size="small" type="link" :disabled="!selectedCount" @click="pool.clearSelected()">
            清空
          </a-button>
        </div>
        <div class="pool-list">
          <label
            v-for="r in pool.records"
            :key="r.asin"
            class="pool-row"
            :class="{ checked: pool.selectedSet.has(r.asin) }"
          >
            <a-checkbox
              :checked="pool.selectedSet.has(r.asin)"
              @change="pool.toggleSelect(r.asin)"
            />
            <span class="pr-main">
              <span class="pr-asin">{{ r.asin }}</span>
              <span class="pr-brand">{{ r.brand }}</span>
            </span>
            <span class="pr-price">${{ r.latest_price.toFixed(2) }}</span>
            <span class="pr-delta" :class="r.price_change_7d < 0 ? 'down' : r.price_change_7d > 0 ? 'up' : 'muted'">
              {{ r.price_change_7d > 0 ? '+' : '' }}{{ r.price_change_7d }}%
            </span>
            <span class="pr-stock" :class="stockClass(r.stock_status)">{{ stockLabel(r.stock_status) }}</span>
          </label>
          <a-empty
            v-if="!pool.records.length"
            description="监控池还是空的，先添加一个竞品 ASIN"
            :image-style="{ height: '52px' }"
          />
        </div>
      </div>
    </section>

    <!-- ================= 价格历史 ================= -->
    <section v-else-if="activeTab === 'price'" class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">📉 价格历史 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
        <div class="pane-sub">圈选竞品的每日价格曲线，'auto' 基线避免 $20→$22 的小波动被压成直线</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">均价</div>
          <div class="kpi-value">${{ avgPrice.toFixed(2) }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">最大降幅</div>
          <div class="kpi-value" :class="minDelta < 0 ? 'danger' : ''">{{ minDelta }}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">涨价中</div>
          <div class="kpi-value" :class="riseCount > 0 ? 'warning' : ''">{{ riseCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">有促销</div>
          <div class="kpi-value soft">{{ dealCount }}</div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">价格走势（最多同时画 5 条）</div>
        <LineChart
          v-if="priceSeries.length"
          :series="priceSeries"
          :labels="chartLabels"
          baseline="auto"
        />
        <div v-else class="chart-empty">先在「监控池」勾选竞品</div>
      </div>

      <div class="panel-card scroll-card">
        <div class="card-head">当前价 / 7 日变化</div>
        <div
          v-for="r in chartRecords"
          :key="r.asin"
          class="kv-row"
        >
          <span>{{ r.asin }} <em class="row-brand">{{ r.brand }}</em></span>
          <span>
            ${{ r.latest_price.toFixed(2) }}
            <b :class="r.price_change_7d < 0 ? 'down' : 'up'">{{ r.price_change_7d > 0 ? '+' : '' }}{{ r.price_change_7d }}%</b>
          </span>
        </div>
      </div>
    </section>

    <!-- ================= BSR 趋势 ================= -->
    <section v-else-if="activeTab === 'bsr'" class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">📈 BSR 趋势 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
        <div class="pane-sub">类目排名走势 —— 排名是逆序量，数值下降代表上升</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">最佳排名</div>
          <div class="kpi-value">#{{ bestBsr.toLocaleString() }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">排名上升</div>
          <div class="kpi-value" :class="bsrUpCount > 0 ? 'success' : ''">{{ bsrUpCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">排名下滑</div>
          <div class="kpi-value" :class="bsrDownCount > 0 ? 'danger' : ''">{{ bsrDownCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">平均 BSR</div>
          <div class="kpi-value soft">#{{ Math.round(avgBsr).toLocaleString() }}</div>
        </div>
      </div>

      <div class="panel-card chart-card">
        <div class="card-head">BSR 走势（最多同时画 5 条）</div>
        <LineChart
          v-if="bsrSeries.length"
          :series="bsrSeries"
          :labels="chartLabels"
          baseline="auto"
        />
        <div v-else class="chart-empty">先在「监控池」勾选竞品</div>
      </div>
    </section>

    <!-- ================= 评论 & 星级 ================= -->
    <section v-else-if="activeTab === 'review'" class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">💬 评论 &amp; 星级</div>
        <div class="pane-sub">近 7 天新增评论与差评预警，用来判断竞品口碑是否在恶化</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">平均评分</div>
          <div class="kpi-value">★ {{ avgRating.toFixed(1) }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">7 日新增</div>
          <div class="kpi-value soft">+{{ reviewsAdded7d }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">有差评</div>
          <div class="kpi-value" :class="negativeCount > 0 ? 'danger' : ''">{{ negativeCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">累计评论</div>
          <div class="kpi-value soft">{{ totalReviewCount.toLocaleString() }}</div>
        </div>
      </div>

      <div class="panel-card scroll-card">
        <div class="card-head">逐竞品明细</div>
        <div v-for="r in chartRecords" :key="r.asin" class="blk-row">
          <div class="blk-head">
            <span class="blk-asin">{{ r.asin }}</span>
            <span class="blk-meta">★ {{ r.rating.toFixed(1) }} · {{ r.review_count.toLocaleString() }} 条 · 7 日 +{{ r.reviews_added_7d }}</span>
          </div>
          <div v-if="recentNegatives(r).length" class="neg-list">
            <div v-for="(e, i) in recentNegatives(r)" :key="i" class="neg-item">
              🔴 {{ e.date }} 新增差评：{{ e.snippet }}
            </div>
          </div>
          <div v-else class="neg-none">近 7 天无差评预警</div>
        </div>
      </div>
    </section>

    <!-- ================= 变体 ================= -->
    <section v-else-if="activeTab === 'variation'" class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">🧩 变体</div>
        <div class="pane-sub">竞品在卖的颜色/规格组合，缺货的子 SKU 往往是对手的软肋</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">变体总数</div>
          <div class="kpi-value">{{ totalVariations }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">平均变体</div>
          <div class="kpi-value soft">{{ avgVariations.toFixed(1) }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">缺货子体</div>
          <div class="kpi-value" :class="outOfStockVars > 0 ? 'danger' : ''">{{ outOfStockVars }}</div>
        </div>
      </div>

      <div class="panel-card scroll-card">
        <div class="card-head">逐竞品变体</div>
        <div v-for="r in chartRecords" :key="r.asin" class="blk-row">
          <div class="blk-head">
            <span class="blk-asin">{{ r.asin }}</span>
            <span class="blk-meta">{{ r.variations.length }} 个变体</span>
          </div>
          <div class="var-chips">
            <span
              v-for="v in r.variations"
              :key="v.child_asin"
              class="var-chip"
              :class="v.in_stock ? 'ok' : 'out'"
              :title="v.child_asin"
            >
              {{ v.color }} ${{ v.price.toFixed(2) }}{{ v.in_stock ? '' : ' (缺)' }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================= Listing 快照 ================= -->
    <section v-else-if="activeTab === 'listing'" class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">📄 Listing 快照</div>
        <div class="pane-sub">竞品近期改动过的字段 —— 对手改标题/改主图通常意味着要打新品或换卖点</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">改动条数</div>
          <div class="kpi-value">{{ totalListingChanges }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">活跃竞品</div>
          <div class="kpi-value soft">{{ changedRecords }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">最近改动</div>
          <div class="kpi-value soft">{{ latestChangeDate || '—' }}</div>
        </div>
      </div>

      <div class="panel-card scroll-card">
        <div class="card-head">改动日志</div>
        <div v-for="r in chartRecords" :key="r.asin" class="blk-row">
          <div class="blk-head">
            <span class="blk-asin">{{ r.asin }}</span>
            <span class="blk-meta">{{ r.listing_changes.length }} 条改动</span>
          </div>
          <div v-for="c in r.listing_changes" :key="c.id" class="lc-row">
            <span class="lc-field">{{ c.field_name }}</span>
            <span class="lc-date">{{ c.changed_at }}</span>
            <span class="lc-prev">{{ c.new_preview }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================= 库存 / 入仓 ================= -->
    <section v-else class="ib-pane">
      <div class="pane-head">
        <div class="pane-title">📦 库存 / 入仓</div>
        <div class="pane-sub">竞品断货窗口就是我方抢排名的窗口</div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">在售</div>
          <div class="kpi-value success">{{ inStockCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">库存告急</div>
          <div class="kpi-value" :class="lowStockCount > 0 ? 'warning' : ''">{{ lowStockCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">已断货</div>
          <div class="kpi-value" :class="outStockCount > 0 ? 'danger' : ''">{{ outStockCount }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">月销估算</div>
          <div class="kpi-value soft">{{ estMonthlySales.toLocaleString() }}</div>
        </div>
      </div>

      <div class="panel-card scroll-card">
        <div class="card-head">逐竞品库存</div>
        <div v-for="r in chartRecords" :key="r.asin" class="kv-row">
          <span>{{ r.asin }} <em class="row-brand">{{ r.brand }}</em></span>
          <span>
            <b :class="stockClass(r.stock_status)">{{ stockLabel(r.stock_status) }}</b>
            · {{ r.estimated_units_remaining === null ? '已断货' : r.estimated_units_remaining.toLocaleString() + ' 件' }}
          </span>
        </div>
      </div>
    </section>

  </div>
</template>

<script setup lang="ts">
import { CHART_VARS } from '@/theme/semantic'
import { ref, computed, inject, onMounted, type Ref } from 'vue'
import { FolderOpenOutlined } from '@ant-design/icons-vue'
import LineChart from '@/components/charts/LineChart.vue'
import { useMonitorPoolStore, type MonitorPoolRecord } from '@/stores/monitorPool'

const props = defineProps<{ currentToolId?: string }>()

/** 「对话 / 大屏」模式由 Workspace provide，与 ReviewConfig / AdDashboardConfig 同一份 */
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

const pool = useMonitorPoolStore()

// 监控池是后端权威源：正常路径已由 Workspace 的店铺 watcher 拉过，这里兜底
onMounted(() => { pool.ensureLoaded() })

const TABS = [
  { key: 'pool', icon: '🗂️', name: '监控池' },
  { key: 'price', icon: '📉', name: '价格' },
  { key: 'bsr', icon: '📈', name: 'BSR' },
  { key: 'review', icon: '💬', name: '评论' },
  { key: 'variation', icon: '🧩', name: '变体' },
  { key: 'listing', icon: '📄', name: 'Listing' },
  { key: 'inventory', icon: '📦', name: '库存' },
] as const

// 「监控仪表盘」工具与大屏是同一件事，落点就是默认面板；窄边栏下也只留这一屏
const TOOL_TAB_MAP: Record<string, string> = { 'monitor-dashboard': 'pool' }
const activeTab = ref<string>(TOOL_TAB_MAP[props.currentToolId || ''] || 'pool')

// ---------------------------------------------------------------------------
// 派生数据
// ---------------------------------------------------------------------------

/** 图表与明细统一取「已圈选」，未圈选时退化为全池（否则进来看不到任何东西） */
const focusRecords = computed<MonitorPoolRecord[]>(() =>
  pool.selectedAsins.length
    ? pool.records.filter(r => pool.selectedSet.has(r.asin))
    : pool.records
)

/** 折线最多画 5 条：再多颜色和量纲都会糊在一起 */
const CHART_COLORS = CHART_VARS
const chartRecords = computed(() => focusRecords.value.slice(0, 5))

const chartLabels = computed(() =>
  (chartRecords.value[0]?.price_history || []).map(p => p.date.slice(5))
)
const priceSeries = computed(() =>
  chartRecords.value.map((r, i) => ({
    name: r.asin,
    color: CHART_COLORS[i % CHART_COLORS.length],
    data: r.price_history.map(p => p.price),
  }))
)
const bsrSeries = computed(() =>
  chartRecords.value.map((r, i) => ({
    name: r.asin,
    color: CHART_COLORS[i % CHART_COLORS.length],
    data: r.bsr_history.map(b => b.bsr),
  }))
)

const selectedCount = computed(() => pool.selectedAsins.length)

// —— 告警 ——
const alertList = computed(() => {
  const s = pool.alertStats
  const list: Array<{ text: string; color: string }> = []
  if (s.negative) list.push({ text: `${s.negative} 个近 7 天有差评`, color: 'red' })
  if (s.price_drop) list.push({ text: `${s.price_drop} 个价格骤降 >5%`, color: 'orange' })
  if (s.low_stock) list.push({ text: `${s.low_stock} 个库存告急/缺货`, color: 'volcano' })
  return list
})
const alertTotal = computed(() => {
  const s = pool.alertStats
  return s.negative + s.price_drop + s.low_stock
})

// —— 价格面板 ——
const avgPrice = computed(() =>
  focusRecords.value.length
    ? focusRecords.value.reduce((s, r) => s + r.latest_price, 0) / focusRecords.value.length
    : 0
)
const minDelta = computed(() =>
  focusRecords.value.length ? Math.min(...focusRecords.value.map(r => r.price_change_7d)) : 0
)
const riseCount = computed(() => focusRecords.value.filter(r => r.price_change_7d > 0).length)
const dealCount = computed(() =>
  focusRecords.value.filter(r => {
    const last7 = r.price_history.slice(-7)
    return last7.some(p => p.coupon || p.deal_type)
  }).length
)

// —— BSR 面板 ——
const bestBsr = computed(() =>
  focusRecords.value.length ? Math.min(...focusRecords.value.map(r => r.latest_bsr)) : 0
)
const avgBsr = computed(() =>
  focusRecords.value.length
    ? focusRecords.value.reduce((s, r) => s + r.latest_bsr, 0) / focusRecords.value.length
    : 0
)
/** BSR 数值变小 = 排名上升 */
const bsrUpCount = computed(() => focusRecords.value.filter(r => r.bsr_change_7d < 0).length)
const bsrDownCount = computed(() => focusRecords.value.filter(r => r.bsr_change_7d > 0).length)

// —— 评论面板 ——
const avgRating = computed(() =>
  focusRecords.value.length
    ? focusRecords.value.reduce((s, r) => s + r.rating, 0) / focusRecords.value.length
    : 0
)
const reviewsAdded7d = computed(() => focusRecords.value.reduce((s, r) => s + r.reviews_added_7d, 0))
/**
 * 记录里没有 has_negative_7d 字段（store 里那个同名变量是构数时的局部变量，没落到 record），
 * 按与 store.alertStats 完全相同的口径现算，避免两处口径漂移。
 */
const hasNegative7d = (r: MonitorPoolRecord) => r.review_events.slice(-7).some(e => e.negative)
const negativeCount = computed(() => focusRecords.value.filter(hasNegative7d).length)
const totalReviewCount = computed(() => focusRecords.value.reduce((s, r) => s + r.review_count, 0))
const recentNegatives = (r: MonitorPoolRecord) =>
  r.review_events.filter(e => e.negative).slice(-2)

// —— 变体面板 ——
const totalVariations = computed(() => focusRecords.value.reduce((s, r) => s + r.variations.length, 0))
const avgVariations = computed(() =>
  focusRecords.value.length ? totalVariations.value / focusRecords.value.length : 0
)
const outOfStockVars = computed(() =>
  focusRecords.value.reduce((s, r) => s + r.variations.filter(v => !v.in_stock).length, 0)
)

// —— Listing 面板 ——
const totalListingChanges = computed(() =>
  focusRecords.value.reduce((s, r) => s + r.listing_changes.length, 0)
)
const changedRecords = computed(() => focusRecords.value.filter(r => r.listing_changes.length).length)
const latestChangeDate = computed(() => {
  const dates = focusRecords.value.flatMap(r => r.listing_changes.map(c => c.changed_at))
  return dates.length ? dates.sort().slice(-1)[0] : ''
})

// —— 库存面板 ——
const inStockCount = computed(() => focusRecords.value.filter(r => r.stock_status === 'in_stock').length)
const lowStockCount = computed(() => focusRecords.value.filter(r => r.stock_status === 'low_stock').length)
const outStockCount = computed(() => focusRecords.value.filter(r => r.stock_status === 'out_of_stock').length)
const estMonthlySales = computed(() =>
  focusRecords.value.reduce((s, r) => s + r.est_monthly_sales, 0)
)

function stockLabel(s: MonitorPoolRecord['stock_status']) {
  return s === 'out_of_stock' ? '缺货' : s === 'low_stock' ? '告急' : '在售'
}
function stockClass(s: MonitorPoolRecord['stock_status']) {
  return s === 'out_of_stock' ? 'down' : s === 'low_stock' ? 'warn' : 'up'
}

// ---------------------------------------------------------------------------
// 增删 / 分组已移交「资料库 → 竞品监控池」：库页是全屏，放得下表格与批量操作。
// 大屏只保留「本次圈选 + 六视角快看」，两个门不做同一件事。
// ---------------------------------------------------------------------------
function goToLibrary() {
  // 与既有导航机制一致：Workspace 监听 'view-navigate' 后走 handleKnowledgeNavigate
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'competitors' } }))
}
</script>

<style scoped>
/* 骨架与 ReviewConfig 对齐：flex 纵向 + pane 内部按需滚动，绝不撑破右栏 */
.ib-config {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  height: 100%;
  min-height: 0;
}

/* ===== Tab 胶囊条 ===== */
.ib-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--bg-hover-light);
  border-radius: var(--radius-10);
  flex-shrink: 0;
}
.ib-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6) var(--space-10);
  border: none;
  background: transparent;
  border-radius: var(--radius-8);
  cursor: pointer;
  font-size: var(--font-size-12);
  font-weight: 500;
  white-space: nowrap;
  color: var(--text-secondary);
  transition: all 0.15s;
}
.ib-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.ib-tab.active {
  background: var(--bg-elevated);
  color: var(--primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  font-weight: 600;
}
.ib-tab-icon { font-size: var(--font-size-13); }

/* ===== 告警条 ===== */
.ib-alert-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  border-radius: var(--radius-8);
  padding: var(--space-6) var(--space-10);
  flex-shrink: 0;
}
.ib-alert-title { font-size: var(--font-size-12); font-weight: 600; color: var(--warning); margin-right: var(--space-2); }

/* ===== Pane ===== */
.ib-pane { display: flex; flex-direction: column; gap: var(--space-10); flex: 1; min-height: 0; overflow: hidden; }
.ib-pane > .pane-head { flex-shrink: 0; }
.ib-pane > .kpi-grid { flex-shrink: 0; }
.ib-pane > .chart-card { flex: 1; min-height: 140px; display: flex; flex-direction: column; overflow: hidden; }
.ib-pane > .scroll-card { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow-y: auto; }
.chart-card > :deep(.chart-root) { flex: 1; min-height: 0; }

.pane-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-8); }
.pane-title { font-size: var(--font-size-15); font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: var(--space-6); }
.pane-sub { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); line-height: 1.5; }
.mini-tag { font-size: var(--font-size-10); margin: 0; }

/* ===== KPI 卡 ===== */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: var(--space-8); }
.kpi-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-9) var(--space-11);
}
.kpi-label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.kpi-value { font-size: var(--font-size-16); font-weight: 700; color: var(--text-primary); margin-top: var(--space-2); }
.kpi-value.soft { font-size: var(--font-size-14); }
.kpi-value.warning { color: var(--warning); }
.kpi-value.danger { color: var(--danger); }
.kpi-value.success { color: var(--success); }

/* ===== 卡片容器 ===== */
.panel-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-11) var(--space-13);
  min-height: 0;
}
.grow-card { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.card-head {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-8);
  display: flex;
  align-items: center;
  gap: var(--space-6);
  flex-shrink: 0;
}
.card-head :deep(.ant-btn-link) { padding: 0 var(--space-4); height: auto; font-size: var(--font-size-12); }
.chart-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

/* ===== 监控池紧凑清单（528 宽放不下宽表，改成行式） ===== */
.pool-list { flex: 1; min-height: 0; overflow-y: auto; }
.pool-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: 7px var(--space-8);
  border-radius: var(--radius-6);
  cursor: pointer;
  font-size: var(--font-size-12);
  transition: background 0.15s;
}
.pool-row + .pool-row { border-top: 1px dashed var(--border-base); }
.pool-row:hover { background: var(--bg-hover-light); }
.pool-row.checked { background: var(--bg-active-light); }
.pr-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pr-asin { font-family: monospace; font-size: var(--font-size-12); font-weight: 600; color: var(--primary); }
.pr-brand { font-size: var(--font-size-10-5); color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-price { font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
.pr-delta { width: 52px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pr-delta.up, .up { color: var(--danger); }
.pr-delta.down, .down { color: var(--success); }
.pr-delta.muted, .muted { color: var(--text-disabled); }
.pr-stock { width: 40px; text-align: right; font-size: var(--font-size-11); white-space: nowrap; }
.pr-stock.up { color: var(--success); }
.pr-stock.warn { color: var(--warning); }
.pr-stock.down { color: var(--danger); }

/* ===== KV 行 ===== */
.kv-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-2);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  border-bottom: 1px dashed var(--border-base);
}
.kv-row:last-child { border-bottom: none; }
.kv-row span:last-child { color: var(--text-primary); font-weight: 600; }
.row-brand { font-style: normal; font-size: var(--font-size-10-5); color: var(--text-tertiary); }

/* ===== 逐竞品块 ===== */
.blk-row { padding: var(--space-8) 0; border-bottom: 1px dashed var(--border-base); }
.blk-row:last-child { border-bottom: none; }
.blk-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-8); }
.blk-asin { font-family: monospace; font-size: var(--font-size-12); font-weight: 600; color: var(--primary); }
.blk-meta { font-size: var(--font-size-11); color: var(--text-tertiary); }

.neg-list { margin-top: var(--space-6); display: flex; flex-direction: column; gap: var(--space-4); }
.neg-item {
  font-size: var(--font-size-11-5);
  line-height: 1.5;
  color: var(--text-secondary);
  background: var(--warning-bg);
  border-radius: var(--radius-6);
  padding: var(--space-4) var(--space-8);
}
.neg-none { margin-top: var(--space-6); font-size: var(--font-size-11-5); color: var(--text-disabled); }

.var-chips { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-top: var(--space-6); }
.var-chip {
  font-size: var(--font-size-11);
  padding: var(--space-2) var(--space-8);
  border-radius: var(--radius-10);
  border: 1px solid var(--border-base);
  background: var(--bg-hover-light);
  color: var(--text-secondary);
}
.var-chip.ok { border-color: var(--success-border); background: var(--success-bg); color: var(--success); }
.var-chip.out { border-color: var(--danger); color: var(--danger); }

.lc-row { display: flex; align-items: baseline; gap: var(--space-8); font-size: var(--font-size-11-5); padding: var(--space-3) 0; }
.lc-field { flex-shrink: 0; color: var(--primary); font-weight: 600; }
.lc-date { flex-shrink: 0; color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.lc-prev { flex: 1; min-width: 0; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
