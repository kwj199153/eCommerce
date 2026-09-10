<template>
  <div class="intel-competitor-pick">
    <!-- 顶部分析对象计数（紧凑行） -->
    <div class="pick-summary">
      <span class="ps-label">分析对象</span>
      <span class="ps-count">
        已选 <b>{{ selectedCount }}</b>
        <span class="ps-sep">/</span>
        {{ pool.totalCount }}
      </span>
    </div>

    <!-- 分组过滤 -->
    <div class="group-filter" v-if="pool.groups.length">
      <div class="gf-label">📁 分组</div>
      <div class="gf-chips">
        <button
          v-for="g in groupChips"
          :key="g.key"
          type="button"
          class="gf-chip"
          :class="{ active: activeFilterKey === g.key }"
          :style="activeFilterKey === g.key ? { borderColor: g.color || '#1890ff', color: g.color || '#1890ff' } : {}"
          @click="setFilter(g.key)"
        >
          <span v-if="g.emoji" class="gf-emoji">{{ g.emoji }}</span>
          {{ g.name }}
          <span class="gf-count">({{ g.count }})</span>
        </button>
      </div>
    </div>

    <!-- 批量操作 -->
    <div class="pick-actions">
      <a-checkbox
        :checked="allChecked"
        :indeterminate="someChecked"
        @change="onToggleAll"
      >全选当前分组</a-checkbox>
      <a-space :size="4">
        <a-button size="small" type="link" :disabled="!pool.totalCount" @click="onPickGroupOrAll('all')">
          全选全部
        </a-button>
        <a-button size="small" type="link" :disabled="!pool.selectedAsins.length" @click="clearAll">
          清空
        </a-button>
      </a-space>
    </div>

    <!-- 分组聚合竞品清单 -->
    <div class="pick-list" v-if="visibleGroupedBuckets.length">
      <div
        v-for="bucket in visibleGroupedBuckets"
        :key="bucket.key"
        class="pick-bucket"
      >
        <!-- 组头 -->
        <div class="bucket-head" @click="toggleGroupAll(bucket)">
          <a-checkbox
            :checked="bucket.allChecked"
            :indeterminate="bucket.someChecked && !bucket.allChecked"
            @click.stop
            @change="toggleGroupAll(bucket)"
          />
          <span class="bucket-emoji" v-if="bucket.emoji">{{ bucket.emoji }}</span>
          <span class="bucket-name">{{ bucket.name }}</span>
          <span class="bucket-counts">
            {{ bucket.selectedInGroup }}/{{ bucket.records.length }}
          </span>
        </div>

        <!-- 组下竞品 -->
        <div class="bucket-rows">
          <div
            v-for="r in bucket.records"
            :key="r.asin"
            class="pick-row"
            :class="{ checked: pool.selectedSet.has(r.asin) }"
            @click="toggle(r.asin)"
          >
            <a-checkbox
              :checked="pool.selectedSet.has(r.asin)"
              @click.stop
              @change="toggle(r.asin)"
            />
            <div class="row-body">
              <div class="row-title">
                <span class="row-asin">{{ r.asin }}</span>
                <span class="row-price mono">${{ r.latest_price.toFixed(2) }}</span>
              </div>
              <div class="row-sub">
                <span class="row-brand">{{ r.brand }}</span>
                <span class="row-bsr">BSR #{{ r.latest_bsr.toLocaleString() }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <a-empty
      v-else
      description="当前分组下暂无竞品"
      :image-style="{ height: '60px' }"
    />

    <!-- 底部提示 -->
    <div class="pick-empty-note" v-if="pool.records.length && !pool.selectedAsins.length">
      <a-tag color="orange">未圈选</a-tag>
      <span>将默认分析全部在池竞品；建议先勾选目标竞品。</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { message } from 'ant-design-vue'
import { useMonitorPoolStore } from '@/stores/monitorPool'

const pool = useMonitorPoolStore()

interface GroupChip {
  key: string               // '__all__' | '__ungrouped__' | group.id
  name: string
  emoji?: string
  color?: string
  count: number
}

interface Bucket {
  key: string               // '__ungrouped__' | group.id
  name: string
  emoji?: string
  color?: string
  records: any[]
  selectedInGroup: number
  allChecked: boolean
  someChecked: boolean
}

const KIND_EMOJI: Record<string, string> = {
  product: '📦',
  store: '🏪',
  brand: '🏷️',
  custom: '🗂️',
}

const selectedCount = computed(() => pool.selectedAsins.length)

const activeFilterKey = computed<string>(() => pool.currentGroupId ?? '__ungrouped__')

/** 当前过滤范围下的记录（用于全选 + 分组聚合） */
const recordsInScope = computed(() => {
  if (activeFilterKey.value === '__all__') return pool.records
  if (activeFilterKey.value === '__ungrouped__') {
    return pool.records.filter(r => !r.group_ids || r.group_ids.length === 0)
  }
  return pool.records.filter(r => r.group_ids?.includes(activeFilterKey.value))
})

const selectedInScope = computed(() =>
  recordsInScope.value.filter(r => pool.selectedSet.has(r.asin))
)

const allChecked = computed(() =>
  recordsInScope.value.length > 0 && selectedInScope.value.length === recordsInScope.value.length
)
const someChecked = computed(() => selectedInScope.value.length > 0 && !allChecked.value)

/** 顶部分组过滤条：全部 + 未分组 + 自定义分组 */
const groupChips = computed<GroupChip[]>(() => {
  const chips: GroupChip[] = []
  const ungroupedCount = pool.records.filter(r => !r.group_ids || r.group_ids.length === 0).length
  // 默认把「未分组」放最前，避免上来就被拉到"全部"
  chips.push({ key: '__ungrouped__', name: '未分组', count: ungroupedCount, emoji: '🪧' })
  if (pool.groups.length) {
    chips.push({ key: '__all__', name: '全部', count: pool.totalCount, emoji: '🗂️' })
  }
  for (const g of pool.groups) {
    const count = pool.records.filter(r => r.group_ids?.includes(g.id)).length
    chips.push({
      key: g.id,
      name: g.name,
      emoji: KIND_EMOJI[g.kind] || '🗂️',
      color: g.color,
      count,
    })
  }
  return chips
})

/** 列表上的分组聚合桶 */
const visibleGroupedBuckets = computed<Bucket[]>(() => {
  if (activeFilterKey.value === '__ungrouped__') {
    const records = recordsInScope.value
    return records.length
      ? [{
          key: '__ungrouped__',
          name: '未分组',
          emoji: '🪧',
          records,
          selectedInGroup: records.filter(r => pool.selectedSet.has(r.asin)).length,
          allChecked: records.length > 0 && records.every(r => pool.selectedSet.has(r.asin)),
          someChecked: records.some(r => pool.selectedSet.has(r.asin)),
        }]
      : []
  }

  if (activeFilterKey.value !== '__all__') {
    const g = pool.groups.find(x => x.id === activeFilterKey.value)
    if (!g) return []
    const records = pool.records.filter(r => r.group_ids?.includes(g.id))
    return [{
      key: g.id,
      name: g.name,
      emoji: KIND_EMOJI[g.kind] || '🗂️',
      color: g.color,
      records,
      selectedInGroup: records.filter(r => pool.selectedSet.has(r.asin)).length,
      allChecked: records.length > 0 && records.every(r => pool.selectedSet.has(r.asin)),
      someChecked: records.some(r => pool.selectedSet.has(r.asin)),
    }]
  }

  // 全部：按分组聚类，未分组的归到「未分组」桶
  const out: Bucket[] = []
  for (const g of pool.groups) {
    const records = pool.records.filter(r => r.group_ids?.includes(g.id))
    if (!records.length) continue
    out.push({
      key: g.id,
      name: g.name,
      emoji: KIND_EMOJI[g.kind] || '🗂️',
      color: g.color,
      records,
      selectedInGroup: records.filter(r => pool.selectedSet.has(r.asin)).length,
      allChecked: records.every(r => pool.selectedSet.has(r.asin)),
      someChecked: records.some(r => pool.selectedSet.has(r.asin)),
    })
  }
  const ungrouped = pool.records.filter(r => !r.group_ids || r.group_ids.length === 0)
  if (ungrouped.length) {
    out.push({
      key: '__ungrouped__',
      name: '未分组',
      emoji: '🪧',
      records: ungrouped,
      selectedInGroup: ungrouped.filter(r => pool.selectedSet.has(r.asin)).length,
      allChecked: ungrouped.every(r => pool.selectedSet.has(r.asin)),
      someChecked: ungrouped.some(r => pool.selectedSet.has(r.asin)),
    })
  }
  return out
})

function setFilter(key: string) {
  if (key === '__all__') pool.selectGroup(null)
  else if (key === '__ungrouped__') pool.selectGroup('__ungrouped__')
  else pool.selectGroup(key)
}

function toggle(asin: string) {
  pool.toggleSelect(asin)
}

function onToggleAll(e: any) {
  if (e.target.checked) {
    // 全选当前过滤范围
    const next = new Set(pool.selectedAsins)
    recordsInScope.value.forEach(r => next.add(r.asin))
    pool.setSelected(Array.from(next))
  } else {
    const set = new Set(recordsInScope.value.map(r => r.asin))
    pool.setSelected(pool.selectedAsins.filter(a => !set.has(a)))
  }
}

/** 「全选全部」：覆盖整个监控池，不受当前过滤范围限制 */
function onPickGroupOrAll(kind: 'all') {
  if (kind === 'all') {
    pool.setSelected(pool.records.map(r => r.asin))
    message.success(`已全选全部 ${pool.totalCount} 个竞品`)
  }
}

function toggleGroupAll(bucket: Bucket) {
  const allSelected = bucket.allChecked
  const set = new Set(pool.selectedAsins)
  if (allSelected) {
    bucket.records.forEach(r => set.delete(r.asin))
  } else {
    bucket.records.forEach(r => set.add(r.asin))
  }
  pool.setSelected(Array.from(set))
}

function clearAll() {
  pool.clearSelected()
  message.info('已清空分析对象圈选')
}
</script>

<style scoped>
.intel-competitor-pick { padding: 4px 0; display: flex; flex-direction: column; gap: 12px; }

/* 顶部紧凑计数 */
.pick-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 2px;
  font-size: 12px;
  color: #595959;
}
.pick-summary .ps-label { font-weight: 500; }
.pick-summary .ps-count { color: #262626; font-variant-numeric: tabular-nums; }
.pick-summary .ps-count b { font-size: 13px; color: #0958d9; margin: 0 2px; }
.pick-summary .ps-sep { opacity: 0.6; margin: 0 3px; }

/* 分组过滤 */
.group-filter { display: flex; align-items: flex-start; gap: 8px; }
.gf-label { font-size: 12px; color: #595959; padding-top: 5px; flex-shrink: 0; }
.gf-chips { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
.gf-chip {
  font-size: 11.5px;
  line-height: 1;
  padding: 5px 10px;
  border-radius: 14px;
  border: 1px solid #d9d9d9;
  background: #fff;
  color: #595959;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  transition: all 0.15s ease;
}
.gf-chip:hover { border-color: #40a9ff; color: #1890ff; }
.gf-chip.active { background: #e6f4ff; font-weight: 600; border-width: 1px; }
.gf-emoji { margin-right: 2px; }
.gf-count { font-size: 10px; opacity: 0.75; margin-left: 2px; font-variant-numeric: tabular-nums; }

/* 批量操作 */
.pick-actions { display: flex; align-items: center; justify-content: space-between; padding: 0 2px; }

/* 分组聚合列表 */
.pick-list {
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 2px;
}
.pick-bucket + .pick-bucket { border-top: 1px solid #f0f0f0; }
.bucket-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: #fafafa;
  font-size: 12px;
  font-weight: 600;
  color: #262626;
  cursor: pointer;
  border-radius: 4px;
}
.bucket-head:hover { background: #f0f0f0; }
.bucket-emoji { font-size: 13px; }
.bucket-name { flex: 1; }
.bucket-counts {
  font-size: 11px;
  font-weight: 500;
  color: #8c8c8c;
  font-variant-numeric: tabular-nums;
}

/* 行 */
.bucket-rows { padding: 2px 0; }
.pick-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px 6px 24px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.pick-row + .pick-row { border-top: 1px dashed #f0f0f0; }
.pick-row:hover { background: #f5f7fa; }
.pick-row.checked { background: #e6f4ff; }
.row-body { flex: 1; min-width: 0; }
.row-title { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.row-asin { font-family: monospace; font-size: 12px; font-weight: 600; color: #0958d9; }
.row-price { font-size: 12px; color: #262626; }
.row-sub { display: flex; gap: 10px; margin-top: 2px; font-size: 11px; color: #8c8c8c; }
.mono { font-variant-numeric: tabular-nums; }
.pick-empty-note { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: #8c8c8c; }
</style>
