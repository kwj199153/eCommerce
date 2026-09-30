<template>
  <div class="mi-config" :class="{ 'data-mode': isDataMode }">
    <!-- ====== 全局状态条：加载中 / 取数失败 ======
         真源诚实：演示账号看 mock 快照、真实账号无数据时显式空态 fail-closed（不编假大盘）。
         第 314 轮：取消「演示数据」黄条（白占热力图一整行）——
         标注并未丢失，改由 KPI「数据真源」项黄字 + title 完整说明承载。 -->
    <div v-if="banner" class="mi-banner" :class="banner.kind">
      <span class="mi-banner-text">{{ banner.text }}</span>
      <button v-if="banner.retry" class="mi-retry" @click="reload">重试</button>
    </div>

    <!-- ====== KPI 概览（类目数 / 覆盖站点 / 数据真源） ======
         第 314 轮：改横排紧凑条（label 与 value 同行，整卡 ≈33px）。
         原竖向大卡一张近百像素、内容只有一行，白吃掉热力图的垂直空间。
         完整文案挂 title：「数据真源」项仍以黄字标注演示数据，语义不丢。 -->
    <div class="kpi-grid">
      <div class="kpi-card" title="覆盖类目数">
        <span class="kpi-label">覆盖类目</span>
        <span class="kpi-value">{{ totalCategories }}</span>
      </div>
      <div class="kpi-card" :title="sites.join(' / ') || '暂无覆盖站点'">
        <span class="kpi-label">覆盖站点</span>
        <span class="kpi-value soft">{{ sites.join(' / ') || '—' }}</span>
      </div>
      <div
        class="kpi-card"
        :title="degraded ? '当前为演示 mock 数据，非真实第三方市场数据，仅用于功能演示。' : sourceLabel"
      >
        <span class="kpi-label">数据真源</span>
        <span class="kpi-value" :class="degraded ? 'warning' : 'success'">
          {{ degraded ? '演示数据' : sourceLabel }}
        </span>
      </div>
    </div>

    <!-- ====== Treemap 主体（面积=搜索热度，颜色=蓝海评分） ======
         第 306 轮：自制 squarify SVG → ECharts treemap（老板拍板「换 ECharts」）。
         点色块 = 跳蓝海挖掘 + 预填类目（色块是「类目」粒度，不是产品，
         所以点它该去「选品后深挖产品」的蓝海挖掘，而不是把类目塞进产品池）。
         第 312 轮：大屏模式左右分栏 —— 左 Treemap、右六维度明细（点色块联动）。
         第 314 轮：分栏下沉进 .mi-body，热力图吃满剩余宽度（原来 55%+45%+gap 溢出
         ⇒ flex-wrap 把明细踹到第二行，热力图右侧白空一半）。 -->
    <div class="mi-body">
    <div class="mi-treemap-card">
      <div class="card-head">
        <span>品类大盘 · 面积=搜索热度 / 颜色=蓝海评分</span>
        <span class="card-sub">点击色块跳蓝海挖掘并预填类目</span>
      </div>

      <div class="mi-treemap-body">
        <!-- 空态：真实账号无数据（fail-closed，不编假数） -->
        <div v-if="!nodes.length" class="mi-empty">
          <span class="mi-empty-icon">🗺️</span>
          <p class="mi-empty-title">暂无市场洞察数据</p>
          <p class="mi-empty-sub">请先接入第三方类目数据源，或切换到演示账号查看示例。</p>
        </div>

        <!-- Treemap（ECharts） -->
        <div v-else class="mi-map">
          <EChartsTreemap
            :cells="treemapCells"
            title="选品市场洞察大盘"
            @cell-click="onCellClick"
          />
        </div>
      </div>
    </div>

    <!-- ====== 六维度明细（点选色块后展示）======
         大屏模式下移到右栏，与 Treemap 左右分栏；对话模式仍在 Treemap 下方。 -->
    <div v-if="selected && !isDataMode" class="mi-detail">
      <div class="card-head">
        <span>📊 {{ selected.name }} · {{ selected.site }}</span>
        <span class="card-sub">{{ selected.snapshot_date }}</span>
      </div>
      <div class="mi-detail-grid">
        <div class="mi-metric">
          <div class="mi-metric-label">蓝海评分</div>
          <div class="mi-metric-value" :class="scoreClass(selected.blue_ocean_score)">{{ selected.blue_ocean_score }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">月搜索量</div>
          <div class="mi-metric-value">{{ fmtK(selected.search_volume) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">搜索增长率</div>
          <div class="mi-metric-value" :class="selected.search_growth >= 0 ? 'up' : 'down'">
            {{ selected.search_growth >= 0 ? '+' : '' }}{{ selected.search_growth }}%
          </div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">价格带</div>
          <div class="mi-metric-value soft">${{ selected.price_min }} ~ ${{ selected.price_max }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">卖家数</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.seller_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">新卖家(近3月)</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.new_seller_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">在售 ASIN</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.listing_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">价格趋势</div>
          <div class="mi-metric-value soft">{{ trendLabel(selected.price_trend) }}</div>
        </div>
      </div>
    </div>

    <!-- 大屏模式：右栏六维度明细（与 Treemap 左右分栏，点色块联动更新） -->
    <div v-else-if="isDataMode" class="mi-detail mi-detail--split">
      <div class="card-head">
        <span>📊 {{ selected ? selected.name + ' · ' + selected.site : '六维度明细' }}</span>
        <span class="card-sub">{{ selected ? selected.snapshot_date : '点击左侧色块查看详情' }}</span>
      </div>
      <div v-if="selected" class="mi-detail-grid">
        <div class="mi-metric">
          <div class="mi-metric-label">蓝海评分</div>
          <div class="mi-metric-value" :class="scoreClass(selected.blue_ocean_score)">{{ selected.blue_ocean_score }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">月搜索量</div>
          <div class="mi-metric-value">{{ fmtK(selected.search_volume) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">搜索增长率</div>
          <div class="mi-metric-value" :class="selected.search_growth >= 0 ? 'up' : 'down'">
            {{ selected.search_growth >= 0 ? '+' : '' }}{{ selected.search_growth }}%
          </div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">价格带</div>
          <div class="mi-metric-value soft">${{ selected.price_min }} ~ ${{ selected.price_max }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">卖家数</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.seller_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">新卖家(近3月)</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.new_seller_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">在售 ASIN</div>
          <div class="mi-metric-value soft">{{ fmtK(selected.listing_count) }}</div>
        </div>
        <div class="mi-metric">
          <div class="mi-metric-label">价格趋势</div>
          <div class="mi-metric-value soft">{{ trendLabel(selected.price_trend) }}</div>
        </div>
      </div>
      <div v-else class="mi-empty">
        <span class="mi-empty-icon">📊</span>
        <p class="mi-empty-sub">点击左侧品类色块，右侧展示该品类的六维度明细。</p>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, type Ref } from 'vue'
import { getMarketInsightTreemap } from '@/api/productResearch'
import EChartsTreemap from '@/components/charts/EChartsTreemap.vue'
import { getToolDefinition, type ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import { topLabel, midLabel } from '@/config/categoryTaxonomy'

/**
 * 选品市场洞察大盘云图（第 305 轮 · 蓝海挖掘大盘云图）
 *
 * 「选品前市场洞察」六维度大盘：品类分布 / 价格带 / 竞争密度 / 搜索热度 /
 * 卖家分布 / 趋势。数据源 `GET /product-research/market-insight/treemap`
 * （market_snapshots 表，站点 × 类目 × 日期快照）。
 *
 * ★ 真源诚实（对齐老板「mock 只给演示账号、不脏真实账号」）：
 *   · 演示账号 → mock 快照 + degraded=true ⇒ KPI「数据真源」项黄字标注
 *     （r314 起不再用顶部黄条，见下方 banner 说明）；
 *   · 真实账号 → 空态 + degraded=false ⇒ 显式空态 + 引导文案，不编假大盘。
 *
 * ★ 工具级双模式：面板直调 api（不经 toolExecutors 注册表），
 *   由 Workspace 的 isMarketInsightTool 判定挂「对话/大屏」切换。
 *
 * ★ 点色块语义（第 306 轮老板拍板）：色块是**类目**粒度，候选池是**产品**粒度，
 *   点类目直接进产品池是张冠李戴。正确闭环是「大盘看赛道 → 蓝海挖掘深挖产品」：
 *   点色块 → 切到蓝海挖掘工具 + 把类目 slug 预填进表单，用户再细化价格/竞争条件去挖产品。
 */

interface TreemapNode {
  name: string
  value: number
  category_path: string
  site: string
  listing_count: number
  price_min: number
  price_max: number
  price_median: number
  seller_count: number
  search_volume: number
  new_seller_count: number
  search_growth: number
  price_trend: string
  blue_ocean_score: number
  snapshot_date: string
}

const nodes = ref<TreemapNode[]>([])
const totalCategories = ref(0)
const degraded = ref(false)
const source = ref('')
const message = ref('')
const loading = ref(false)
const loadError = ref('')
const selectedKey = ref<string>('')

// 大屏/对话模式：读 Workspace 注入的 reviewMode（第 312 轮对齐 AIGC 双模式）。
// 大屏模式下「左 Treemap 右六维度明细」左右分栏；对话模式 Treemap 在上、明细在下。
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

const sites = computed(() => [...new Set(nodes.value.map((n) => n.site))])
const sourceLabel = computed(() => (source.value === 'empty' ? '暂无数据' : source.value === 'third_party' ? '第三方数据' : '演示数据'))

// 第 314 轮：不再产出 warning 条 —— 黄条横占一整行，热力图是主角。
// 「演示数据」标注整体下移到 KPI「数据真源」项（黄字 + title 完整说明），信息不丢。
const banner = computed(() => {
  if (loading.value) return { kind: 'info', text: '正在加载市场洞察数据…', retry: false }
  if (loadError.value) return { kind: 'error', text: loadError.value, retry: true }
  return null
})

const selected = computed(() => nodes.value.find((n) => `${n.site}|${n.category_path}` === selectedKey.value) ?? null)

async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    const resp = await getMarketInsightTreemap()
    const data = resp?.data ?? resp ?? {}
    nodes.value = Array.isArray(data.nodes) ? data.nodes : []
    totalCategories.value = data.total_categories ?? nodes.value.length
    degraded.value = !!data.degraded
    source.value = data.source ?? ''
    message.value = data.message ?? ''
    // 默认选中的类目 = 右侧六维度明细的落脚点。
    // ★ 顺序依赖是**契约**：后端保证 nodes 按 blue_ocean_score 降序
    //   （唯一真源 = backend/modules/product_research/spec.py 的 default_sort）
    //   ⇒ nodes[0] 就是「最值得进的类目」。改后端排序会**静默**改掉这里的默认选中项。
    if (nodes.value.length && !selectedKey.value) {
      const first = nodes.value[0]
      selectedKey.value = `${first.site}|${first.category_path}`
    }
  } catch (e: any) {
    loadError.value = e?.message || '加载市场洞察数据失败，请稍后重试。'
    nodes.value = []
  } finally {
    loading.value = false
  }
}

onMounted(reload)

// ---------------------------------------------------------------------------
// 跳蓝海挖掘 + 预填类目（第 306 轮）
// 色块 = 类目粒度，点它 = 切到蓝海挖掘工具 + 把类目 slug 预填进表单。
// ---------------------------------------------------------------------------

// 从 Workspace 注入「设置当前工具」（切到 blue-ocean）与「预填蓝海类目」通道。
// 预填通道在 TaskConfigPanel 层 provide，蓝海表单 inject，避免跨层耦合。
const setSelectedTool = inject<(tool: ToolDefinition | null) => void>('setSelectedTool', () => {})
const prefillBlueOcean = inject<(payload: { categoryPath: string; categoryName: string; site: string }) => void>(
  'prefillBlueOcean',
  () => {}
)

/** 蓝海评分 → 语义色（红蓝双色，参考股票云图：蓝=蓝海机会大，红=红海拥挤）。
 *  ★ 传语义 key 而非 var(--x)：ECharts 画在 canvas 上不认 CSS 变量，
 *    真实 hex 由 EChartsTreemap 的 palette 按当前主题解析（r307 灰块根因）。 */
function scoreColor(score: number): 'blue' | 'red' {
  return score >= 60 ? 'blue' : 'red'
}

/** nodes → ECharts treemap cells（面积=搜索热度，颜色=蓝海评分，label=二级子类目·站点 + score；三级细分品类进 tooltip） */
interface TreemapCell {
  key: string
  name: string
  value: number
  score: number
  color: 'blue' | 'red'
  extra: string
  /** 一级类目显示名（Home & Kitchen 等），EChartsTreemap 按它聚合成组 */
  group: string
}

// 站点 slug → 叶子 label 缩写：同类目跨站点同名（Coffee Machines 在 US/UK 各一块），
// 不带站点标识分不清（r309）
const SITE_TAGS: Record<string, string> = {
  amazon_us: 'US',
  amazon_uk: 'UK',
  amazon_de: 'DE',
  amazon_jp: 'JP',
  shopee_sg: 'SG',
}

const treemapCells = computed<TreemapCell[]>(() =>
  nodes.value.map((n) => {
    // 色块名 = 二级子类目显示名（与蓝海 cascader 子项 1:1，真源 config/categoryTaxonomy，r310）；
    // 三级细分品类（Coffee Machines 等）降级进 tooltip；映射不到时兜底叶子名
    const parts = n.category_path.split('/')
    const top = parts[0] ?? ''
    const mid = parts[1] ?? ''
    const midName = midLabel(top, mid) ?? n.name
    return {
      key: `${n.site}|${n.category_path}`,
      name: `${midName} · ${SITE_TAGS[n.site] ?? n.site}`,
      value: n.search_volume || 1,
      score: n.blue_ocean_score,
      color: scoreColor(n.blue_ocean_score),
      extra: `细分品类 ${n.name} · 月搜索 ${fmtK(n.search_volume)} · 价格 $${n.price_min}~$${n.price_max} · 卖家 ${fmtK(n.seller_count)}`,
      group: topLabel(top) ?? top,
    }
  })
)

/** 点色块 → 跳蓝海挖掘 + 预填类目（不再把类目塞进产品粒度的候选池） */
function onCellClick(key: string) {
  selectedKey.value = key
  const node = nodes.value.find((n) => `${n.site}|${n.category_path}` === key)
  if (!node) return
  const parts = node.category_path.split('/')
  prefillBlueOcean({
    categoryPath: node.category_path,
    // 预填提示名与 cascader 选中项一致（二级子类目），映射不到兜底叶子名
    categoryName: midLabel(parts[0] ?? '', parts[1] ?? '') ?? node.name,
    site: node.site,
  })
  const tool = getToolDefinition('product-research', 'blue-ocean')
  if (tool) setSelectedTool(tool)
}

function fmtK(v: number): string {
  const a = Math.abs(v)
  if (a >= 1000000) return (v / 1000000).toFixed(1) + 'M'
  if (a >= 1000) return (v / 1000).toFixed(1) + 'k'
  return String(Math.round(v))
}

function scoreClass(score: number): string {
  return score >= 60 ? 'primary' : 'danger'
}

function trendLabel(t: string): string {
  return t === 'rising' ? '↑ 上涨' : t === 'falling' ? '↓ 下跌' : '→ 平稳'
}
</script>

<style scoped>
.mi-config {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  height: 100%;
  min-height: 0;
}
/* 大屏模式：分栏交给 .mi-body（banner / KPI 仍是顶部整行的兄弟节点）。
   ★ 第 314 轮修 bug：原先把 55% / 45% 直接摊在 .mi-config 上，加上 gap
     必然 > 100% ⇒ flex-wrap 把明细踹到第二行，又被 flex-grow 拉成整行宽
     ⇒ 热力图只剩 55%、右侧白空一半（老板截图里的错位就是这个）。 */
.mi-config.data-mode .mi-body {
  flex-direction: row;
}
/* 热力图：吃满剩余宽度 = 主要区域；可收缩，不被内容撑爆 */
.mi-config.data-mode .mi-treemap-card {
  flex: 1 1 auto;
  min-width: 0;
}
/* 明细：定宽侧栏（窄屏可退到 220px），不参与抢宽度 */
.mi-config.data-mode .mi-detail--split {
  flex: 0 1 340px;
  min-width: 220px;
}

/* 状态条 */
.mi-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-10);
  border-radius: var(--radius-8);
  font-size: var(--font-size-12);
  flex-shrink: 0;
}
.mi-banner.info { background: var(--bg-hover-light); color: var(--text-secondary); border: 1px solid var(--border-base); }
.mi-banner.error { background: var(--danger-bg, #fff1f0); color: var(--danger); border: 1px solid var(--danger-border, #ffccc7); }
.mi-banner.warning { background: var(--warning-bg); color: var(--warning); border: 1px solid var(--warning-border); }
.mi-retry {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: var(--font-size-12);
  font-weight: 600;
  text-decoration: underline;
  flex-shrink: 0;
}

/* KPI 卡：横排紧凑条（第 314 轮）
   原竖向大卡 label 上 / value 下，一张近百像素却只有一行内容，
   白白吃掉热力图的垂直空间 ⇒ 改同行排布，整卡高 ≈33px。 */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-8); flex-shrink: 0; }
.kpi-card {
  display: flex;
  align-items: baseline;
  gap: var(--space-8);
  min-width: 0;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  padding: var(--space-6) var(--space-10);
}
.kpi-label { font-size: var(--font-size-11); color: var(--text-tertiary); flex-shrink: 0; }
.kpi-value {
  font-size: var(--font-size-14);
  font-weight: 700;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kpi-value.soft { font-size: var(--font-size-12); font-weight: 500; }
.kpi-value.warning { color: var(--warning); }
.kpi-value.success { color: var(--success); }

/* 主体区（Treemap + 明细）：对话模式纵向堆叠，大屏模式横向分栏 */
.mi-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

/* Treemap 卡片 */
.mi-treemap-card {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-11) var(--space-13);
  overflow: hidden;
}
.mi-treemap-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-6);
  flex-shrink: 0;
}
.card-sub { font-size: var(--font-size-11); font-weight: 400; color: var(--text-tertiary); }

.mi-map { flex: 1; min-height: 180px; position: relative; }

/* 空态 */
.mi-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  color: var(--text-tertiary);
  text-align: center;
}
.mi-empty-icon { font-size: var(--font-size-32); }
.mi-empty-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-secondary); margin: 0; }
.mi-empty-sub { font-size: var(--font-size-12); margin: 0; max-width: 280px; line-height: 1.6; }

/* 六维度明细：第 314 轮压缩垂直留白（原 padding 11/13 + 每格上下 4px，空得比内容多） */
.mi-detail {
  flex-shrink: 0;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-8) var(--space-12);
}
/* 大屏模式：明细做右栏定宽侧栏（宽度由上面 .mi-config.data-mode 的 flex 规则给） */
.mi-detail--split {
  min-height: 0;
  overflow-y: auto;
}
.mi-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: var(--space-6) var(--space-10); }
/* 大屏侧栏窄 ⇒ 固定两列（auto-fit 会排出三列，把数字挤成窄条） */
.mi-config.data-mode .mi-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.mi-metric { padding: 0; }
.mi-metric-label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.mi-metric-value { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-top: var(--space-2); }
.mi-metric-value.soft { font-size: var(--font-size-12); font-weight: 500; }
.mi-metric-value.up { color: var(--danger); }
.mi-metric-value.down { color: var(--success); }
.mi-metric-value.success { color: var(--success); }
.mi-metric-value.primary { color: var(--primary); }
.mi-metric-value.warning { color: var(--warning); }
.mi-metric-value.danger { color: var(--danger); }
</style>
