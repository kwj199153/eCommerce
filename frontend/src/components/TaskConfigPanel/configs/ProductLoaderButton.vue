<template>
  <a-popover
    v-model:open="popoverVisible"
    trigger="click"
    placement="bottomLeft"
    :overlayStyle="{ width: '380px', maxHeight: '460px' }"
  >
    <template #content>
      <div class="product-loader">
        <div class="loader-header">
          <span class="loader-title">📦 载入产品</span>
          <span class="loader-desc">选择后，当前 Agent 所有工具共享该商品上下文</span>
        </div>

        <!-- 搜索 -->
        <a-input
          v-model:value="searchText"
          placeholder="搜索商品名称或 ASIN..."
          size="small"
          allow-clear
          style="margin-bottom: 8px"
        >
          <template #prefix><SearchOutlined style="color: var(--text-disabled)" /></template>
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

        <!-- 当前已选 -->
        <div v-if="modelValue" class="current-selected">
          <div class="current-label">当前工作商品</div>
          <div class="current-card" @click="handleReselect(modelValue)">
            <span class="current-title">{{ modelValue.title }}</span>
            <span class="current-asin">{{ modelValue.asin }}</span>
            <a-button type="text" size="small" danger @click.stop="handleClear">
              <CloseOutlined />
            </a-button>
          </div>
        </div>

        <!-- 商品列表（按分组聚合展示） -->
        <div class="product-list">
          <template v-if="activeGroupId">
            <!-- 单分组视图：直接列商品 -->
            <div
              v-for="p in displayedProducts"
              :key="p.id"
              class="product-item"
              :class="{ selected: modelValue?.id === p.id }"
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
                <span v-if="p.spec_value" class="item-var">{{ p.spec_value }}</span>
                <span class="item-price">${{ p.price }}</span>
              </div>
              <div class="item-meta">
                <span class="item-asin">{{ p.asin }}</span>
                <CheckCircleFilled v-if="modelValue?.id === p.id" class="item-check" />
              </div>
            </div>
          </template>
          <template v-else>
            <!-- 全部视图：按分组聚合 -->
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
                v-for="p in groupProducts[g.id]"
                :key="p.id"
                class="product-item"
                :class="{ selected: modelValue?.id === p.id }"
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
                  <span v-if="p.spec_value" class="item-var">{{ p.spec_value }}</span>
                  <span class="item-price">${{ p.price }}</span>
                </div>
                <div class="item-meta">
                  <span class="item-asin">{{ p.asin }}</span>
                  <CheckCircleFilled v-if="modelValue?.id === p.id" class="item-check" />
                </div>
              </div>
            </div>
            <!-- 未分组商品（兜底） -->
            <div v-if="ungroupedProducts.length > 0" class="group-section">
              <div class="group-section-header">
                <FolderOpenOutlined style="color: var(--text-disabled)" />
                <span class="group-section-name">未分组</span>
                <span class="group-section-count">{{ ungroupedProducts.length }} 个</span>
              </div>
              <div
                v-for="p in ungroupedProducts"
                :key="p.id"
                class="product-item"
                :class="{ selected: modelValue?.id === p.id }"
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
                  <span v-if="p.spec_value" class="item-var">{{ p.spec_value }}</span>
                  <span class="item-price">${{ p.price }}</span>
                </div>
                <div class="item-meta">
                  <span class="item-asin">{{ p.asin }}</span>
                  <CheckCircleFilled v-if="modelValue?.id === p.id" class="item-check" />
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
      type="primary"
      size="small"
      :class="['loader-btn', { loaded: !!modelValue }]"
    >
      <template #icon>
        <ShopOutlined />
      </template>
      {{ modelValue ? modelValue.title?.slice(0, 6) + '..' : '载入产品' }}
    </a-button>
  </a-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { SearchOutlined, ShopOutlined, CloseOutlined, CheckCircleFilled, FolderOpenOutlined } from '@ant-design/icons-vue'
import { useProductLibraryStore, type ProductItem } from '@/stores/productLibrary'

const props = withDefaults(defineProps<{
  modelValue?: ProductItem | null
}>(), {
  modelValue: null,
})

const emit = defineEmits<{
  (e: 'update:modelValue', product: ProductItem): void
  (e: 'select', product: ProductItem): void
}>()

const library = useProductLibraryStore()
const popoverVisible = ref(false)
const searchText = ref('')
const activeGroupId = ref<string | null>(null)

/** 可载入的商品（排除SPU：SPU无 ASIN、无前台文案，不可编辑 Listing） */
const loadableProducts = computed(() =>
  library.items.filter(p => !p.is_spu)
)

/** 搜索 + 分组过滤后的商品列表 */
const displayedProducts = computed(() => {
  let list = loadableProducts.value
  // 分组过滤
  if (activeGroupId.value) {
    list = list.filter(p => p.groups?.includes(activeGroupId.value!))
  }
  // 搜索过滤
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(p =>
      p.title?.toLowerCase().includes(q) ||
      p.asin?.toLowerCase().includes(q)
    )
  }
  return list
})

/** 未分组的商品（仅在"全部"视图下展示） */
const ungroupedProducts = computed(() => {
  if (activeGroupId.value) return []
  let list = loadableProducts.value.filter(p => !p.groups || p.groups.length === 0)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(p =>
      p.title?.toLowerCase().includes(q) ||
      p.asin?.toLowerCase().includes(q)
    )
  }
  return list
})

/** 分组视图（全部视图下按分组聚合，过滤掉SPU） */
const groupProducts = computed(() => {
  const map: Record<string, ProductItem[]> = {}
  for (const g of library.groups) {
    map[g.id] = loadableProducts.value.filter(p => p.groups?.includes(g.id))
  }
  return map
})

function handleSelect(product: ProductItem) {
  emit('update:modelValue', product)
  emit('select', product)
  popoverVisible.value = false
  searchText.value = ''
  activeGroupId.value = null
}

function handleReselect(product: ProductItem) {
  // 点击已选卡片时不做任何事（相当于确认）
}

function handleClear() {
  emit('update:modelValue', null as any)
  emit('select', null as any)
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

.product-loader {
  /* 容器 */
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

/* 商品列表 */
.product-list {
  max-height: 300px;
  overflow-y: auto;
}

/* 分组过滤 chips */
.group-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--border-base);
}

.group-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-base);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.group-chip:hover {
  border-color: var(--border-base);
  color: var(--text-primary);
}

.group-chip.active {
  color: #1890ff;
  background: var(--info-bg, #e6f7ff);
  border-color: var(--info-border, #91d5ff);
}

.group-color-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* 全部视图下的分组段落 */
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
  color: var(--text-secondary);
  font-weight: 600;
  background: var(--bg-base);
  border-radius: 4px;
  margin-bottom: 4px;
}

.group-section-name {
  flex: 1;
}

.group-section-count {
  font-size: 10px;
  color: var(--text-tertiary);
  font-weight: normal;
}

.product-item {
  padding: 8px 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.product-item:hover {
  background: var(--bg-base);
}

.product-item.selected {
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

.item-var {
  font-size: 10px;
  font-weight: 600;
  color: var(--purple);
  background: var(--purple-bg);
  border: 1px solid var(--purple-border);
  border-radius: 4px;
  padding: 0 4px;
  flex-shrink: 0;
  margin-right: 4px;
}

.item-price {
  font-size: 12px;
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
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: 'SF Mono', Monaco, monospace;
}

.item-check {
  color: var(--success);
  font-size: 12px;
}

.empty-hint {
  text-align: center;
  padding: 20px 0;
  color: var(--text-disabled);
  font-size: 12px;
}
</style>
