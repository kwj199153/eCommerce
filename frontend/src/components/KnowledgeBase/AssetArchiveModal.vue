<template>
  <a-modal
    v-model:open="visible"
    title="归档到营销素材库"
    width="720px"
    okText="确认归档"
    cancelText="取消"
    :okLoading="submitting"
    @ok="handleConfirm"
  >
    <!-- 说明 -->
    <a-alert
      type="info"
      show-icon
      message="确认后素材将保存到「资料库 → 营销素材库」，可在素材库中统一分组管理"
      style="margin-bottom: 12px"
    />

    <div v-if="candidates.length" class="amc-body">
      <!-- 可归档素材列表（勾选） -->
      <div class="amc-section">
        <div class="amc-section-head">
          <span class="amc-section-title">选择要归档的素材</span>
          <a-checkbox
            :checked="allChecked"
            :indeterminate="someChecked"
            @change="toggleAll"
          >全选</a-checkbox>
        </div>
        <div class="amc-grid">
          <div
            v-for="(c, i) in candidates"
            :key="i"
            class="amc-item"
            :class="{ selected: form.checked[i] && !isDisabled(i), archived: isDisabled(i) }"
            @click="!isDisabled(i) && toggleOne(i)"
          >
            <img :src="c.url" alt="" loading="lazy" @error="onImgError" />
            <div class="amc-item-overlay">
              <CheckOutlined v-if="form.checked[i]" />
              <CheckCircleFilled v-else-if="isDisabled(i)" class="archived-icon" />
            </div>
            <span v-if="c.kind === 'video'" class="amc-video-badge">🎥</span>
            <span class="amc-item-label">{{ isDisabled(i) ? '已归档' : c.name }}</span>
          </div>
        </div>
      </div>

      <!-- 归档设置 -->
      <a-form layout="vertical" class="amc-form">
        <div class="amc-form-row">
          <a-form-item label="归档到分组" class="flex-1">
            <a-select
              v-model:value="form.groupIds"
              mode="multiple"
              placeholder="选择分组（可多选，留空归入未分组）"
              style="width: 100%"
              allow-clear
              :options="groupOptions"
            />
            <!-- 内联新建分组（保持弹窗紧凑） -->
            <div v-if="!inlineCreateOpen" class="amc-add-group">
              <a-button type="link" size="small" @click="openInlineCreate">
                <PlusOutlined /> 新建分组
              </a-button>
            </div>
            <div v-else class="amc-inline-create">
              <a-input
                v-model:value="inlineCreate.name"
                placeholder="分组名称，如 Q4 主图素材"
                size="small"
                @pressEnter="submitInlineCreate"
              />
              <div class="amc-color-row">
                <span
                  v-for="c in ASSET_GROUP_COLORS"
                  :key="c"
                  class="amc-color-swatch"
                  :class="{ active: inlineCreate.color === c }"
                  :style="{ background: c }"
                  @click="inlineCreate.color = c"
                ></span>
              </div>
              <a-space :size="6">
                <a-button size="small" type="primary" @click="submitInlineCreate">创建并选中</a-button>
                <a-button size="small" @click="cancelInlineCreate">取消</a-button>
              </a-space>
            </div>
          </a-form-item>
          <a-form-item label="绑定产品" class="flex-1">
            <a-select
              v-model:value="form.productId"
              placeholder="选择绑定产品（可选）"
              style="width: 100%"
              allow-clear
              show-search
              option-filter-prop="label"
              :options="productOptions"
              @change="onProductChange"
            />
          </a-form-item>
        </div>
        <a-form-item v-if="productLocked" label="">
          <a-tag color="blue">已绑定：{{ productLocked }}</a-tag>
        </a-form-item>
      </a-form>
    </div>
    <a-empty v-else description="没有可归档的素材" />
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import { CheckOutlined, CheckCircleFilled, PlusOutlined } from '@ant-design/icons-vue'
import { useAssetLibraryStore, ASSET_GROUP_COLORS } from '@/stores/assetLibrary'
import { useProductLibraryStore } from '@/stores/productLibrary'

export interface ArchiveCandidate {
  url: string
  name: string
  kind: 'image' | 'video'
  category: string           // 对应 ASSET_CATEGORIES key
  videoUrl?: string
  prompt?: string
  tags?: string[]
  source?: string
  productId?: string         // 预绑定产品（来自生成时的 working product）
  productName?: string
  asin?: string
}

const props = defineProps<{
  open: boolean
  candidates: ArchiveCandidate[]
  lockedProductName?: string | null   // 生成结果绑定到的工作商品名（显示用）
  archivedUrls?: string[]             // 已归档的 url（用于禁用防重复）
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'archived', items: ArchiveCandidate[]): void
}>()

const assetStore = useAssetLibraryStore()
const productStore = useProductLibraryStore()

const visible = computed({
  get: () => props.open,
  set: (v) => emit('update:open', v),
})

const submitting = ref(false)

const form = reactive({
  checked: [] as boolean[],
  groupIds: [] as string[],
  productId: undefined as string | undefined,
})

// ====== 内联新建分组 ======
const inlineCreateOpen = ref(false)
const inlineCreate = reactive({
  name: '',
  color: ASSET_GROUP_COLORS[0],
})

function openInlineCreate() {
  inlineCreate.name = ''
  inlineCreate.color = ASSET_GROUP_COLORS[(assetStore.groups.length + 1) % ASSET_GROUP_COLORS.length]
  inlineCreateOpen.value = true
}
function cancelInlineCreate() {
  inlineCreateOpen.value = false
}
function submitInlineCreate() {
  const name = inlineCreate.name.trim()
  if (!name) {
    message.warning('请输入分组名称')
    return
  }
  const group = assetStore.createGroup({ name, color: inlineCreate.color })
  // 自动选中该分组（去重）
  if (!form.groupIds.includes(group.id)) {
    form.groupIds = [...form.groupIds, group.id]
  }
  message.success(`分组「${group.name}」已创建并选中`)
  inlineCreateOpen.value = false
}

// 打开时重置
watch(() => props.open, (open) => {
  if (open) {
    form.checked = props.candidates.map((_, i) => isDisabled(i) ? false : true)
    form.groupIds = []
    form.productId = props.candidates[0]?.productId || undefined
  }
})

const groupOptions = computed(() =>
  assetStore.groups.map(g => ({ label: g.name, value: g.id }))
)

const productOptions = computed(() =>
  productStore.items.map(p => ({
    value: p.id,
    label: `${p.asin || p.sku} · ${p.title.slice(0, 24)}`,
  }))
)

function isDisabled(idx: number): boolean {
  return (props.archivedUrls || []).includes(props.candidates[idx]?.url)
}

const activeCount = computed(() =>
  props.candidates.reduce((n, _, i) => n + (isDisabled(i) ? 0 : 1), 0)
)
const allChecked = computed(() =>
  activeCount.value > 0 && props.candidates.every((_, i) => isDisabled(i) || form.checked[i])
)
const someChecked = computed(() =>
  !allChecked.value && props.candidates.some((_, i) => !isDisabled(i) && form.checked[i])
)

const productLocked = computed(() => props.lockedProductName || null)

function toggleAll(e: any) {
  const val = !!e.target.checked
  form.checked = props.candidates.map((_, i) => isDisabled(i) ? false : val)
}

function toggleOne(idx: number) {
  if (isDisabled(idx)) return
  form.checked[idx] = !form.checked[idx]
}

function onProductChange() {
  // 无额外逻辑，productId 已同步
}

async function handleConfirm() {
  const selected = props.candidates.filter((_, i) => form.checked[i] && !isDisabled(i))
  if (selected.length === 0) {
    message.warning('请至少选择 1 个素材')
    return
  }
  submitting.value = true
  try {
    // 绑定产品快照
    const bound = productStore.items.find(p => p.id === form.productId)
    selected.forEach(c => {
      assetStore.addItem({
        name: c.name,
        kind: c.kind,
        category: c.category,
        url: c.url,
        videoUrl: c.videoUrl,
        prompt: c.prompt,
        tags: c.tags || [],
        source: c.source || 'aigc',
        groups: [...form.groupIds],
        productId: bound?.id || c.productId,
        productName: bound?.title || c.productName,
        asin: bound?.asin || c.asin,
        notes: '',
      })
    })
    const count = selected.length
    message.success(`已归档 ${count} 个素材到营销素材库`)
    visible.value = false
    emit('archived', selected)
  } finally {
    submitting.value = false
  }
}

function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.opacity = '0.3'
  el.style.background = 'var(--bg-sidebar)'
}
</script>

<style scoped>
.amc-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.amc-section {
  margin-bottom: 4px;
}

.amc-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.amc-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.amc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
  padding: 2px;
}

.amc-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: 8px;
  overflow: hidden;
  border: 2px solid transparent;
  cursor: pointer;
  transition: border-color 0.15s;
}

.amc-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.amc-item:hover {
  border-color: var(--info-border);
}

.amc-item.selected {
  border-color: var(--primary);
}

.amc-item.archived {
  border-color: var(--border-strong);
  opacity: 0.6;
  cursor: not-allowed;
}

.amc-item-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(24, 144, 255, 0.25);
  color: #fff;
  font-size: 22px;
  opacity: 0;
  transition: opacity 0.15s;
}

.amc-item.selected .amc-item-overlay {
  opacity: 1;
}

.archived-icon {
  color: var(--success);
  font-size: 26px;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 50%;
}

.amc-item.archived .amc-item-overlay {
  opacity: 1;
  background: rgba(0, 0, 0, 0.15);
}

.amc-video-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  font-size: 14px;
}

.amc-item-label {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 2px 6px;
  font-size: 10px;
  color: #fff;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.amc-form {
  margin-top: 6px;
}

.amc-form-row {
  display: flex;
  gap: 12px;
}

.flex-1 {
  flex: 1;
}

/* 内联新建分组 */
.amc-add-group {
  margin-top: 2px;
}

.amc-add-group :deep(.ant-btn) {
  padding-left: 0;
  font-size: 12px;
}

.amc-inline-create {
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  background: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.amc-color-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.amc-color-swatch {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.15s;
}

.amc-color-swatch.active {
  border-color: var(--text-primary);
  transform: scale(1.15);
}
</style>
