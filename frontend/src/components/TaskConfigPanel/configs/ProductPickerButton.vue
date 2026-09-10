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
          style="margin-bottom: 8px"
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
                <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: #1890ff; font-size: 12px" />
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
                  <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: #1890ff; font-size: 12px" />
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
                  <CheckCircleFilled v-if="isSelected(p)" class="item-check" style="color: #1890ff; font-size: 12px" />
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
  gap: 2px;
  color: #8c8c8c;
  flex-shrink: 0;
  padding: 2px 4px !important;
  border-radius: 4px;
  transition: all 0.2s;
}

.picker-btn:hover {
  color: #1890ff;
  background: #e6f7ff;
}

.picker-btn.has-value {
  color: #1890ff;
}

.btn-label {
  font-size: 11px;
}

.product-picker {
  /* 容器 */
}

.product-list {
  max-height: 320px;
  overflow-y: auto;
}

.product-item {
  padding: 8px 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.product-item:hover {
  background: #f5f5f5;
}

.product-item.selected {
  background: #e6f7ff;
  border-color: #91d5ff;
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
  border: 1px solid #f0f0f0;
  flex-shrink: 0;
  background: #fafafa;
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
  background: #fafafa;
  border: 1px solid #f0f0f0;
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
  color: #262626;
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
  justify-content: space-between;
}

.item-asin {
  font-size: 10px;
  color: #8c8c8c;
  font-family: 'SF Mono', Monaco, monospace;
}

.empty-hint {
  text-align: center;
  padding: 20px 0;
  color: #bfbfbf;
  font-size: 12px;
}

/* 分组过滤 chips */
.group-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #f0f0f0;
}

.group-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: #595959;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.group-chip:hover {
  border-color: #d9d9d9;
  color: #262626;
}

.group-chip.active {
  color: #1890ff;
  background: #e6f7ff;
  border-color: #91d5ff;
}

.group-color-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.group-section {
  margin-bottom: 10px;
}

.group-section:last-child {
  margin-bottom: 0;
}

.group-section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  font-size: 11px;
  color: #595959;
  font-weight: 600;
  background: #fafafa;
  border-radius: 4px;
  margin-bottom: 4px;
}

.group-section-name {
  flex: 1;
}

.group-section-count {
  font-size: 10px;
  color: #8c8c8c;
  font-weight: normal;
}
</style>
