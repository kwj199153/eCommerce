<template>
  <div class="pool-panel">
    <!-- 分组过滤 + 批量操作 -->
    <div class="pool-toolbar">
      <div class="grp-filter">
        <button class="gf" :class="{ active: pool.currentGroupId === null }" @click="pool.selectGroup(null)">全部</button>
        <button class="gf" :class="{ active: pool.currentGroupId === '__ungrouped__' }" @click="pool.selectGroup('__ungrouped__')">未分组</button>
        <button
          v-for="g in pool.groups"
          :key="g.id"
          class="gf"
          :class="{ active: pool.currentGroupId === g.id }"
          @click="pool.selectGroup(g.id)"
        >
          <span class="gdot" :style="{ background: g.color }"></span>{{ g.name }}
        </button>
      </div>
      <!-- 归属视图过滤：区分「定向监控(归属某主品/候选项目)」与「游离监控(无归属)」 -->
      <div class="own-filter">
        <button class="of" :class="{ active: pool.currentOwnership === 'all' }" @click="pool.selectOwnership('all')">
          全部 <span class="ocnt">{{ pool.ownershipCount.all }}</span>
        </button>
        <button class="of" :class="{ active: pool.currentOwnership === 'owned' }" @click="pool.selectOwnership('owned')">
          <span class="odot od-own"></span>有归属 <span class="ocnt">{{ pool.ownershipCount.owned }}</span>
        </button>
        <button class="of" :class="{ active: pool.currentOwnership === 'free' }" @click="pool.selectOwnership('free')">
          <span class="odot od-free"></span>游离 <span class="ocnt">{{ pool.ownershipCount.free }}</span>
        </button>
      </div>
      <div class="pool-actions">
        <a-checkbox
          :checked="allFilteredChecked"
          :indeterminate="someFilteredChecked"
          @change="onToggleAll"
        >全选本组</a-checkbox>
        <a-button size="small" :type="pool.selectedAsins.length ? 'primary' : 'default'" @click="onBatchAnalyze">
          分析选中 ({{ pool.selectedAsins.length }})
        </a-button>
        <a-button size="small" :disabled="!pool.selectedAsins.length" @click="onBatchToCandidate">
          <SaveOutlined /> 加入选品库
        </a-button>
        <a-popconfirm title="取消监控并停止定时采集？不影响选品库记录" @confirm="onBatchRemove">
          <a-button size="small" danger :disabled="!pool.selectedAsins.length"><DeleteOutlined />取消监控</a-button>
        </a-popconfirm>
      </div>
    </div>

    <!-- 监控池表格：ASIN 缩略 + 当刻快照 + 勾选 -->
    <a-table
      :data-source="pool.filteredRecords"
      :columns="columns"
      :pagination="false"
      size="small"
      :row-key="(r: MonitorPoolRecord) => r.asin"
      :row-selection="{ selectedRowKeys: pool.selectedAsins, onChange: onSelectChange }"
      :scroll="{ y: '100%' }"
      class="pool-table"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'asin'">
          <div class="asin-cell">
            <img
              v-if="record.main_image"
              class="a-img"
              :src="record.main_image"
              :alt="record.asin"
              loading="lazy"
              @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none'; const fb = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null; if (fb) fb.style.display = 'flex'; }"
            />
            <span class="a-img-fb" :style="{ display: record.main_image ? 'none' : 'flex' }">🛍️</span>
            <div class="a-meta">
              <a class="a-asin" :href="listingUrl(record.asin)" target="_blank" rel="noopener">{{ record.asin }} ↗</a>
              <div class="a-brand">{{ record.brand }} · {{ record.title.slice(0, 28) }}…</div>
            </div>
          </div>
        </template>
        <template v-else-if="column.key === 'own'">
          <template v-if="record.owned_by">
            <a-tag
              class="own-tag"
              :color="record.owned_by.type === 'product' ? 'geekblue' : 'cyan'"
              style="cursor: pointer"
              @click="goOwner(record.owned_by)"
            >
              {{ record.owned_by.type === 'product' ? '📦 产品' : '🧪 候选' }}
              · {{ (record.owned_by.title || record.owned_by.asin).slice(0, 14) }}{{ (record.owned_by.title || '').length > 14 ? '…' : '' }}
            </a-tag>
          </template>
          <span v-else class="own-free">
            <a-tag class="own-free-tag">游离</a-tag>
          </span>
        </template>
        <template v-else-if="column.key === 'group'">
          <a-tag v-for="g in recordGroup(record)" :key="g.id" :color="g.kind === 'store' ? 'green' : g.kind === 'brand' ? 'purple' : 'blue'" style="margin:1px">
            {{ g.name }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'price'">
          <div>
            <div class="mono" :style="{ color: record.price_change_7d < -3 ? 'var(--danger)' : record.price_change_7d > 3 ? 'var(--success)' : 'var(--text-primary)', fontWeight: 500 }">
              ${{ record.latest_price.toFixed(2) }}
            </div>
            <div v-if="record.price_change_7d !== 0" class="mono sub" :class="record.price_change_7d < 0 ? 'down' : 'up'">
              {{ record.price_change_7d > 0 ? '▲' : '▼' }}{{ Math.abs(record.price_change_7d) }}% /7d
            </div>
          </div>
        </template>
        <template v-else-if="column.key === 'bsr'">
          <div>
            <div class="mono">#{{ record.latest_bsr.toLocaleString() }}</div>
            <div v-if="record.bsr_change_7d !== 0" class="mono sub" :class="record.bsr_change_7d < 0 ? 'up' : 'down'">
              {{ record.bsr_change_7d < 0 ? '▲升' : '▼降' }} {{ Math.abs(record.bsr_change_7d) }}
            </div>
          </div>
        </template>
        <template v-else-if="column.key === 'rating'">
          <div>
            <div>★ {{ record.rating.toFixed(1) }}</div>
            <div class="sub">+{{ record.reviews_added_7d }} 评论/7d</div>
          </div>
        </template>
        <template v-else-if="column.key === 'stock'">
          <a-badge
            :status="record.stock_status === 'out_of_stock' ? 'error' : record.stock_status === 'low_stock' ? 'warning' : 'success'"
            :text="record.stock_status === 'out_of_stock' ? '缺货' : record.stock_status === 'low_stock' ? '库存告急' : '在售'"
          />
        </template>
        <template v-else-if="column.key === 'view'">
          <a-space :size="4">
            <a-dropdown>
              <a-button size="small"><EyeOutlined /> 查看 <DownOutlined /></a-button>
              <template #overlay>
                <a-menu @click="(e: any) => onViewMenu(e, record)">
                  <a-menu-item key="price">📉 价格历史</a-menu-item>
                  <a-menu-item key="bsr">📈 BSR 趋势</a-menu-item>
                  <a-menu-item key="review">💬 评论 &amp; 星级</a-menu-item>
                  <a-menu-item key="variation">🧩 变体</a-menu-item>
                  <a-menu-item key="listing">📄 Listing 快照</a-menu-item>
                  <a-menu-item key="inventory">📦 库存/入仓</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
            <a-tooltip :title="inCandidate(record.asin) ? '该 ASIN 已在选品库，前往评估' : '写入选品库，做新品可行性评估'">
              <a-button size="small" type="text" @click="inCandidate(record.asin) ? goCandidateAsin(record.asin) : addToCandidate(record)">
                <SaveOutlined /> {{ inCandidate(record.asin) ? '选品库✓' : '选品' }}
              </a-button>
            </a-tooltip>
          </a-space>
        </template>
      </template>
    </a-table>

    <div v-if="!pool.filteredRecords.length" class="pool-empty">
      <a-empty description="该分组暂无监控 ASIN。点击右上角「添加竞品」建立你的监控池" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { message } from 'ant-design-vue'
import { DeleteOutlined, DownOutlined, EyeOutlined, SaveOutlined } from '@ant-design/icons-vue'
import { useMonitorPoolStore, type MonitorPoolRecord, type MonitorGroup } from '@/stores/monitorPool'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'

const props = defineProps<{ store: ReturnType<typeof useMonitorPoolStore> }>()
const emit = defineEmits<{ (e: 'open-add'): void; (e: 'open-group'): void; (e: 'jump-panel', p: string): void }>()

const pool = props.store
const candStore = useCandidateLibraryStore()

const columns = [
  { title: '竞品 ASIN', key: 'asin', dataIndex: 'asin', width: 210 },
  { title: '归属', key: 'own', width: 170 },
  { title: '分组', key: 'group', width: 120 },
  { title: '当前价', key: 'price', width: 108, align: 'right' },
  { title: 'BSR', key: 'bsr', width: 96, align: 'right' },
  { title: '评分/评论', key: 'rating', width: 120, align: 'center' },
  { title: '库存', key: 'stock', width: 86 },
  { title: '操作', key: 'view', width: 200, align: 'center' },
]

const allFilteredChecked = computed(() =>
  pool.filteredRecords.length > 0 && pool.filteredRecords.every(r => pool.selectedAsins.includes(r.asin))
)
const someFilteredChecked = computed(() => {
  const keys = pool.filteredRecords.map(r => r.asin)
  return keys.some(k => pool.selectedAsins.includes(k)) && !allFilteredChecked.value
})

const onSelectChange = (keys: string[]) => pool.setSelected(keys)

function onToggleAll(e: any) {
  if (e.target.checked) pool.selectAllFiltered()
  else {
    const keys = new Set(pool.filteredRecords.map(r => r.asin))
    pool.setSelected(pool.selectedAsins.filter(a => !keys.has(a)))
  }
}

function recordGroup(r: MonitorPoolRecord): MonitorGroup[] {
  return pool.groups.filter(g => r.group_ids?.includes(g.id))
}

function onBatchAnalyze() {
  if (!pool.selectedAsins.length) {
    message.warning('请先勾选要分析的竞品')
    return
  }
  // 骨架：把圈选集交给某个面板
  emit('jump-panel', 'price')
  message.success(`已圈选 ${pool.selectedAsins.length} 个 ASIN，可在上方各面板查看（本轮为骨架）`)
}

function onBatchRemove() {
  pool.removeRecords(pool.selectedAsins)
  message.success('已取消监控（停止采集，不影响选品库）')
}

// —— 链路3：监控 → 选品库 反向回流 ——

/** 该 ASIN 是否已在选品库 */
function inCandidate(asin: string): boolean {
  return candStore.isAsinInCandidate(asin)
}

/** 单条：监控快照写入选品库 */
async function addToCandidate(record: MonitorPoolRecord) {
  await candStore.ensureLoaded()
  const created = await candStore.addFromMonitorSnapshot({
    asin: record.asin,
    title: record.title,
    brand: record.brand || undefined,
    main_image: record.main_image || undefined,
    price: record.latest_price,
    rating: record.rating,
    review_count: record.review_count,
    bsr: record.latest_bsr,
    bsr_category: record.bsr_category || undefined,
    est_monthly_sales: record.est_monthly_sales,
  })
  if (created) {
    message.success(`「${record.asin}」已加入选品库，可进行可行性评估`)
  } else {
    message.info(`「${record.asin}」已在选品库`)
  }
}

/** 批量：多选监控行 → 选品库 */
async function onBatchToCandidate() {
  if (!pool.selectedAsins.length) {
    message.warning('请先勾选要回流的监控竞品')
    return
  }
  await candStore.ensureLoaded()
  let added = 0
  let existed = 0
  for (const rec of pool.selectedRecords) {
    const created = await candStore.addFromMonitorSnapshot({
      asin: rec.asin,
      title: rec.title,
      brand: rec.brand || undefined,
      main_image: rec.main_image || undefined,
      price: rec.latest_price,
      rating: rec.rating,
      review_count: rec.review_count,
      bsr: rec.latest_bsr,
      bsr_category: rec.bsr_category || undefined,
      est_monthly_sales: rec.est_monthly_sales,
    })
    if (created) added++
    else existed++
  }
  message.success(`已回流 ${added} 个到选品库${existed ? `，${existed} 个已存在` : ''}`)
}

/** 前往选品库视图评估该 ASIN */
function goCandidateAsin(asin: string) {
  // 高亮：切到候选库并保持候选（清空过滤避免找不到）
  candStore.clearAllFilters()
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'candidates' } }))
  message.success(`前往选品库评估 ${asin}`)
}

/** 归属标签点击：跳到该 ASIN 归属的主品/候选项目所在视图 */
function goOwner(owner: { type: 'product' | 'candidate'; asin: string; title?: string }) {
  const view = owner.type === 'product' ? 'products' : 'candidates'
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view } }))
  message.info(`前往${owner.type === 'product' ? '自有产品库' : '选品库'}查看归属「${owner.title || owner.asin}」`)
}

function onJump(key: string, record: MonitorPoolRecord) {
  if (pool.selectedAsins.indexOf(record.asin) < 0) pool.toggleSelect(record.asin)
  emit('jump-panel', key)
}

function onViewMenu(e: any, record: MonitorPoolRecord) {
  onJump(String(e?.key), record)
}

function listingUrl(asin: string) {
  return `https://www.amazon.com/dp/${asin}`
}
</script>

<style scoped>
.pool-panel { display: flex; flex-direction: column; height: 100%; padding: 12px; gap: 10px; }
.pool-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.grp-filter { display: flex; gap: 6px; flex-wrap: wrap; }
.gf { border: 1px solid var(--border-base); background: var(--bg-elevated); border-radius: 14px; padding: 2px 12px; font-size: 12px; color: var(--text-secondary); cursor: pointer; }
.gf.active { border-color: var(--primary); color: var(--primary); background: var(--info-bg, var(--bg-active-light)); font-weight: 500; }
.gdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.pool-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.own-filter { display: flex; gap: 6px; align-items: center; }
.of { border: 1px solid var(--border-base); background: var(--bg-elevated); border-radius: 6px; padding: 3px 10px; font-size: 12px; color: var(--text-secondary); cursor: pointer; display: inline-flex; align-items: center; gap: 5px; }
.of.active { border-color: var(--purple, var(--purple)); color: var(--purple, var(--purple)); background: var(--purple-bg, var(--purple-bg)); font-weight: 500; }
.ocnt { font-size: 10px; color: var(--text-tertiary); background: var(--bg-hover-light); border-radius: 8px; padding: 0 5px; font-variant-numeric: tabular-nums; }
.of.active .ocnt { background: var(--purple-border, var(--purple-border)); color: var(--purple, var(--purple)); }
.odot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.od-own { background: var(--primary); }
.od-free { background: var(--text-disabled); }
.own-tag { font-size: 11px; white-space: nowrap; }
.own-free-tag { font-size: 11px; color: var(--text-tertiary); background: var(--bg-base); border-color: var(--border-strong); }
.pool-table { flex: 1; }
.pool-empty { flex: 1; display: flex; align-items: center; justify-content: center; }
.asin-cell { display: flex; gap: 8px; align-items: center; }
.a-img { width: 28px; height: 28px; border-radius: 4px; object-fit: cover; border: 1px solid var(--border-base); background: var(--bg-base); flex-shrink: 0; }
.a-img-fb { width: 28px; height: 28px; border-radius: 4px; border: 1px solid var(--border-base); background: var(--bg-base); align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
.a-meta { min-width: 0; }
.a-asin { font-family: monospace; font-size: 12px; font-weight: 600; color: var(--primary); text-decoration: none; }
.a-asin:hover { text-decoration: underline; }
.a-brand { font-size: 11px; color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.mono { font-variant-numeric: tabular-nums; font-size: 13px; }
.sub { font-size: 11px; }
.up { color: var(--success, var(--success)); }
.down { color: var(--danger, var(--danger)); }
</style>
