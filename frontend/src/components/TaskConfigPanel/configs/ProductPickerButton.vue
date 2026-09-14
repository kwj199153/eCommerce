<template>
  <a-popover
    v-model:open="popoverVisible"
    trigger="click"
    placement="bottomRight"
    :overlayStyle="{ width: '360px', maxHeight: '440px' }"
  >
    <template #content>
      <div class="product-picker">
        <!-- 搜索 -->
        <a-input
          v-model:value="searchText"
          placeholder="搜索商品名称或 ASIN..."
          size="small"
          allow-clear
          style="margin-bottom: var(--space-8)"
        >
          <template #prefix><SearchOutlined style="color: #bfbfbf" /></template>
        </a-input>

        <!-- 分组过滤 chips -->
        <div v-if="library.groups.length > 0" class="group-chips">
          <span
            class="group-chip"
            :class="{ active: !activeGroupId }"
            @click="activeGroupId = null"
          >
            <FolderOpenOutlined /> 全部 ({{ library.totalCount }})
          </span>
          <span
            v-for="g in library.groups"
            :key="g.id"
            class="group-chip"
            :class="{ active: activeGroupId === g.id }"
            @click="activeGroupId = g.id"
          >
            <span class="group-color-dot" :style="{ background: g.color }"></span>
            {{ g.name }} ({{ library.groupProductCount[g.id] || 0 }})
          </span>
        </div>

        <!-- 商品列表（按分组聚合展示） -->
        <div class="product-list">
          <template v-if="activeGroupId">
            <div
              v-for="p in displayedProducts"
              :key="p.asin"
              class="product-item"
              :class="{ selected: isSelected(p) }"
              @click="handleSelect(p)"
            >
              <div class="item-main">
                <a-popover
                  v-if="p.main_image"
                  placement="right"
                  :mouseEnterDelay="0.3"
                  overlayClassName="product-thumb-popover"
                >
                  <template #content>
                    <img :src="p.main_image" alt="" class="item-thumb-large" />
                  </template>
                  <img class="item-thumb" :src="p.main_image" alt="" loading="lazy" @error="onImgError" @click.stop />
                </a-popover>
                <span class="item-thumb-ph" v-else>🖼️</span>
                <span class="item-title">{{ p.title }}</span>
                <span class="item-price">${{ p.price }}</span>
              </div>
              <div class="item-meta">
                <span class="item-asin">{{ p.asin }}</span>
                <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: var(--primary); font-size: 12px" />
              </div>
            </div>
          </template>
          <template v-else>
            <div
              v-for="g in library.groups"
              :key="g.id"
              class="group-section"
            >
              <div class="group-section-header">
                <span class="group-color-dot" :style="{ background: g.color }"></span>
                <span class="group-section-name">{{ g.name }}</span>
                <span class="group-section-count">{{ library.groupProductCount[g.id] || 0 }} 个</span>
              </div>
              <div
                v-for="p in library.getProductsByGroup(g.id)"
                :key="p.asin"
                class="product-item"
                :class="{ selected: isSelected(p) }"
                @click="handleSelect(p)"
              >
                <div class="item-main">
                  <a-popover
                    v-if="p.main_image"
                    placement="right"
                    :mouseEnterDelay="0.3"
                    overlayClassName="product-thumb-popover"
                  >
                    <template #content>
                      <img :src="p.main_image" alt="" class="item-thumb-large" />
                    </template>
                    <img class="item-thumb" :src="p.main_image" alt="" loading="lazy" @error="onImgError" />
                  </a-popover>
                  <span class="item-thumb-ph" v-else>🖼️</span>
                  <span class="item-title">{{ p.title }}</span>
                  <span class="item-price">${{ p.price }}</span>
                </div>
                <div class="item-meta">
                  <span class="item-asin">{{ p.asin }}</span>
                  <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: var(--primary); font-size: 12px" />
                </div>
              </div>
            </div>
            <div v-if="ungroupedProducts.length > 0" class="group-section">
              <div class="group-section-header">
                <FolderOpenOutlined style="color: #bfbfbf" />
                <span class="group-section-name">未分组</span>
                <span class="group-section-count">{{ ungroupedProducts.length }} 个</span>
              </div>
              <div
                v-for="p in ungroupedProducts"
                :key="p.asin"
                class="product-item"
                :class="{ selected: isSelected(p) }"
                @click="handleSelect(p)"
              >
                <div class="item-main">
                  <a-popover
                    v-if="p.main_image"
                    placement="right"
                    :mouseEnterDelay="0.3"
                    overlayClassName="product-thumb-popover"
                  >
                    <template #content>
                      <img :src="p.main_image" alt="" class="item-thumb-large" />
                    </template>
                    <img class="item-thumb" :src="p.main_image" alt="" loading="lazy" @error="onImgError" />
                  </a-popover>
                  <span class="item-thumb-ph" v-else>🖼️</span>
                  <span class="item-title">{{ p.title }}</span>
                  <span class="item-price">${{ p.price }}</span>
                </div>
                <div class="item-meta">
                  <span class="item-asin">{{ p.asin }}</span>
                  <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: var(--primary); font-size: 12px" />
                </div>
              </div>
            </div>
          </template>
          <div v-if="displayedProducts.length === 0 && ungroupedProducts.length === 0" class="empty-hint">
            无匹配商品
          </div>
        </div>
      </div>
    </template>

    <a-button
      type="text"
      size="small"
      :class="['picker-btn', { 'has-value': !!modelValue }]"
      :title="modelValue ? `已选: ${modelValue.title?.slice(0, 20)}` : '从产品库选择'"
    >
      <FolderOpenOutlined />
      <span v-if="showLabel" class="btn-label">选择</span>
    </a-button>
  </a-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { SearchOutlined, FolderOpenOutlined, CheckCircleFilled } from '@ant-design/icons-vue'
import { useProductLibraryStore, type ProductItem } from '@/stores/productLibrary'

const props = withDefaults(defineProps<{
  modelValue?: ProductItem | null
  showLabel?: boolean
  /** 过滤函数，返回 false 的商品不显示 */
  filter?: (p: ProductItem) => boolean
}>(), {
  modelValue: null,
  showLabel: false,
  filter: undefined,
})

const emit = defineEmits<{
  (e: 'update:modelValue', product: ProductItem): void
  (e: 'select', product: ProductItem): void
}>()

const library = useProductLibraryStore()
const popoverVisible = ref(false)
const searchText = ref('')
const activeGroupId = ref<string | null>(null)

const displayedProducts = computed(() => {
  let list = library.items
  if (activeGroupId.value) {
    list = list.filter(p => p.groups?.includes(activeGroupId.value!))
  }
  if (props.filter) {
    list = list.filter(props.filter)
  }
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(p =>
      p.title?.toLowerCase().includes(q) ||
      p.asin?.toLowerCase().includes(q)
    )
  }
  return list
})

const ungroupedProducts = computed(() => {
  if (activeGroupId.value) return []
  let list = library.items.filter(p => !p.groups || p.groups.length === 0)
  if (props.filter) {
    list = list.filter(props.filter)
  }
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(p =>
      p.title?.toLowerCase().includes(q) ||
      p.asin?.toLowerCase().includes(q)
    )
  }
  return list
})

function isSelected(p: ProductItem): boolean {
  return props.modelValue?.asin === p.asin
}

function handleSelect(product: ProductItem) {
  emit('update:modelValue', product)
  emit('select', product)
  popoverVisible.value = false
  searchText.value = ''
  activeGroupId.value = null
}

/** 图片加载失败隐藏破图 */
function onImgError(e: Event) {
  ;(e.target as HTMLImageElement).style.display = 'none'
}
</script>

<style scoped>
.picker-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-tertiary);
  flex-shrink: 0;
  padding: var(--space-2) var(--space-4) !important;
  border-radius: var(--radius-4);
  transition: all 0.2s;
}

.picker-btn:hover {
  color: var(--primary);
  background: var(--info-bg);
}

.picker-btn.has-value {
  color: var(--primary);
}

.btn-label {
  font-size: var(--font-size-11);
}

.product-picker {
  /* 容器 */
}

.product-list {
  max-height: 320px;
  overflow-y: auto;
}

.product-item {
  padding: var(--space-8) var(--space-6);
  border-radius: var(--radius-6);
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.product-item:hover {
  background: var(--bg-hover-light);
}

.product-item.selected {
  background: var(--info-bg);
  border-color: var(--info-border);
}

.item-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-2);
}

.item-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: var(--radius-4);
  border: 1px solid var(--border-base);
  flex-shrink: 0;
  background: var(--bg-sidebar);
}

.item-thumb-ph {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-16);
  border-radius: var(--radius-4);
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
}

.item-thumb-large {
  display: block;
  width: 240px;
  height: 240px;
  object-fit: cover;
  border-radius: var(--radius-4);
}

.item-title {
  font-size: var(--font-size-12);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.item-price {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--primary);
  flex-shrink: 0;
}

.item-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.item-asin {
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
  font-family: 'SF Mono', Monaco, monospace;
}

.empty-hint {
  text-align: center;
  padding: var(--space-20) 0;
  color: var(--text-disabled);
  font-size: var(--font-size-12);
}

/* 分组过滤 chips */
.group-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
  padding-bottom: var(--space-8);
  border-bottom: 1px dashed var(--border-base);
}

.group-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-8);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.group-chip:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.group-chip.active {
  color: var(--primary);
  background: var(--info-bg);
  border-color: var(--info-border);
}

.group-color-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-circle);
  flex-shrink: 0;
}

.group-section {
  margin-bottom: var(--space-10);
}

.group-section:last-child {
  margin-bottom: 0;
}

.group-section-header {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-4) var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  font-weight: 600;
  background: var(--bg-sidebar);
  border-radius: var(--radius-4);
  margin-bottom: var(--space-4);
}

.group-section-name {
  flex: 1;
}

.group-section-count {
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
  font-weight: normal;
}
</style>
