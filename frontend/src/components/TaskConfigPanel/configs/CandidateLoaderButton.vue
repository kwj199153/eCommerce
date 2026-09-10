<template>
  <a-popover
    v-model:open="popoverVisible"
    trigger="click"
    placement="bottomLeft"
    :overlayStyle="{ width: '380px', maxHeight: '460px' }"
  >
    <template #content>
      <div class="cand-loader">
        <div class="loader-header">
          <span class="loader-title">🗂️ 载入选品</span>
          <span class="loader-desc">选择后，市场可行性 / 上架建议 将针对该候选评估</span>
        </div>

        <!-- 搜索 -->
        <a-input
          v-model:value="searchText"
          placeholder="搜索标题或 ASIN..."
          size="small"
          allow-clear
          style="margin-bottom: 8px"
        >
          <template #prefix><SearchOutlined style="color: var(--text-disabled)" /></template>
        </a-input>

        <!-- 当前已选 -->
        <div v-if="modelValue" class="current-selected">
          <div class="current-label">当前评估对象</div>
          <div class="current-card" @click="handleReselect(modelValue)">
            <span class="current-title">{{ modelValue.title }}</span>
            <span class="current-asin">{{ modelValue.asin }}</span>
            <a-button type="text" size="small" danger @click.stop="handleClear">
              <CloseOutlined />
            </a-button>
          </div>
        </div>

        <!-- 候选列表 -->
        <div class="cand-list">
          <div
            v-for="c in displayedCands"
            :key="c.asin"
            class="cand-item"
            :class="{ selected: modelValue?.asin === c.asin }"
            @click="handleSelect(c)"
          >
            <div class="item-main">
              <a-popover
                v-if="c.main_image"
                placement="right"
                :mouseEnterDelay="0.3"
                overlayClassName="product-thumb-popover"
              >
                <template #content>
                  <img :src="c.main_image" alt="" class="item-thumb-large" />
                </template>
                <img class="item-thumb" :src="c.main_image" alt="" loading="lazy" @error="onImgError" @click.stop />
              </a-popover>
              <span class="item-thumb-ph" v-else>🖼️</span>
              <span class="item-title">{{ c.title }}</span>
              <span class="item-price">${{ c.price }}</span>
            </div>
            <div class="item-meta">
              <span class="item-badges">
                <span v-if="c.blue_ocean_score > 0" class="score-badge">蓝海 {{ c.blue_ocean_score }}</span>
                <span v-if="c.roi_estimated > 0" class="roi-badge">ROI {{ c.roi_estimated }}%</span>
                <span class="status-chip" :style="{ color: statusColor(c.review_status) }">{{ statusLabel(c.review_status) }}</span>
              </span>
              <span class="item-asin">{{ c.asin }}</span>
              <CheckCircleFilled v-if="modelValue?.asin === c.asin" class="item-check" />
            </div>
          </div>
          <div v-if="displayedCands.length === 0" class="empty-hint">
            暂无候选，先到选品库 / 蓝海挖掘添加
          </div>
        </div>
      </div>
    </template>

    <a-button
      type="primary"
      size="small"
      :class="['loader-btn', { loaded: !!modelValue }]"
    >
      <template #icon>
        <FolderOpenOutlined />
      </template>
      {{ modelValue ? modelValue.title?.slice(0, 6) + '..' : '载入选品' }}
    </a-button>
  </a-popover>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SearchOutlined, FolderOpenOutlined, CloseOutlined, CheckCircleFilled } from '@ant-design/icons-vue'
import { useCandidateLibraryStore, REVIEW_STATUS_MAP, type CandidateItem } from '@/stores/candidateLibrary'

const props = withDefaults(defineProps<{
  modelValue?: CandidateItem | null
}>(), {
  modelValue: null,
})

const emit = defineEmits<{
  (e: 'update:modelValue', cand: CandidateItem): void
  (e: 'select', cand: CandidateItem | null): void
}>()

const candStore = useCandidateLibraryStore()
const popoverVisible = ref(false)
const searchText = ref('')

// 首次打开前确保候选已加载
watch(popoverVisible, (open) => {
  if (open && !candStore.items.length) {
    candStore.ensureLoaded?.()
  }
})

/** 搜索过滤后的候选列表（按最近更新排序） */
const displayedCands = computed(() => {
  let list = [...candStore.items]
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(c =>
      c.title?.toLowerCase().includes(q) ||
      c.asin?.toLowerCase().includes(q) ||
      c.sku?.toLowerCase().includes(q)
    )
  }
  list.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
  return list
})

function handleSelect(cand: CandidateItem) {
  emit('update:modelValue', cand)
  emit('select', cand)
  popoverVisible.value = false
  searchText.value = ''
}

function handleReselect(_cand: CandidateItem) {
  // 点击已选卡片不做任何事
}

function handleClear() {
  emit('update:modelValue', null as any)
  emit('select', null)
}

function statusLabel(s?: string) {
  if (!s) return ''
  return REVIEW_STATUS_MAP[s as keyof typeof REVIEW_STATUS_MAP]?.label || s
}
function statusColor(s?: string) {
  if (!s) return '#8c8c8c'
  return REVIEW_STATUS_MAP[s as keyof typeof REVIEW_STATUS_MAP]?.color === 'green'
    ? '#52c41a'
    : REVIEW_STATUS_MAP[s as keyof typeof REVIEW_STATUS_MAP]?.color === 'orange'
      ? '#fa8c16'
      : REVIEW_STATUS_MAP[s as keyof typeof REVIEW_STATUS_MAP]?.color === 'red' || s === 'rejected'
        ? '#ff4d4f'
        : '#8c8c8c'
}

/** 图片加载失败隐藏破图 */
function onImgError(e: Event) {
  ;(e.target as HTMLImageElement).style.display = 'none'
}
</script>

<style scoped>
.loader-btn {
  border-radius: 14px;
  font-size: 11px;
  margin-left: 10px;
  flex-shrink: 0;
  height: 26px;
  line-height: 24px;
  padding: 0 10px;
}

.loader-btn.loaded {
  background: #52c41a;
  border-color: #52c41a;
}

.loader-header {
  margin-bottom: 10px;
}

.loader-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.loader-desc {
  display: block;
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* 当前已选 */
.current-selected {
  margin-bottom: 10px;
}

.current-label {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.current-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: linear-gradient(135deg, var(--success-bg) 0%, var(--info-bg) 100%);
  border: 1px solid var(--success-border, #b7eb8f);
  border-radius: 6px;
  cursor: pointer;
}

.current-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.current-asin {
  font-size: 9px;
  color: var(--text-tertiary);
  font-family: 'SF Mono', Monaco, monospace;
}

/* 候选列表 */
.cand-list {
  max-height: 300px;
  overflow-y: auto;
}

.cand-item {
  padding: 8px 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.cand-item:hover {
  background: var(--bg-base);
}

.cand-item.selected {
  background: var(--success-bg, #f6ffed);
  border-color: var(--success-border, #b7eb8f);
}

.item-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.item-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--border-base);
  flex-shrink: 0;
  background: var(--bg-base);
}

.item-thumb-ph {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  border-radius: 4px;
  background: var(--bg-base);
  border: 1px solid var(--border-base);
}

.item-thumb-large {
  display: block;
  width: 240px;
  height: 240px;
  object-fit: cover;
  border-radius: 4px;
}

.item-title {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.item-price {
  font-size: 12px;
  font-weight: 600;
  color: #1890ff;
  flex-shrink: 0;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 44px;
}

.item-badges {
  display: inline-flex;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.score-badge {
  font-size: 10px;
  color: #722ed1;
  background: var(--purple-bg, #f9f0ff);
  border: 1px solid var(--purple-border, #efdbff);
  padding: 0 4px;
  border-radius: 4px;
  white-space: nowrap;
}

.roi-badge {
  font-size: 10px;
  color: #389e0d;
  background: var(--success-bg, #f6ffed);
  border: 1px solid var(--success-border, #d9f7be);
  padding: 0 4px;
  border-radius: 4px;
  white-space: nowrap;
}

.status-chip {
  font-size: 10px;
  white-space: nowrap;
}

.item-asin {
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: 'SF Mono', Monaco, monospace;
}

.item-check {
  color: #52c41a;
  font-size: 12px;
}

.empty-hint {
  text-align: center;
  padding: 20px 0;
  color: var(--text-disabled);
  font-size: 12px;
}
</style>
