<template>
  <a-modal
    :open="open"
    :title="`⚔️ 竞品管理 · ${owner?.title?.slice(0, 18) || owner?.asin || ''}`"
    :width="680"
    :footer="null"
    :destroy-on-close="false"
    @cancel="emit('update:open', false)"
  >
    <div class="competitor-manager">
      <!-- 添加来源：三来源 tab 互斥（推荐 / 手动添加 / 从其它复制） -->
      <a-tabs v-model:active-key="addSource" size="small" class="cm-source-tabs">
        <template #rightExtra>
          <span class="pool-hint">{{ enabledCount }} / {{ poolLength }} 已启用</span>
        </template>
        <!-- Tab 1：一键生成相似竞品 -->
        <a-tab-pane key="recommend" tab="⚡ 一键生成相似竞品">
          <div class="tab-pane-body">
            <p class="tab-hint">按主品类目与关键词自动推荐 10-20 个相似 ASIN，一键入池。</p>
            <a-button type="primary" :loading="recommending" @click="doRecommend">
              <ThunderboltOutlined /> 立即生成
            </a-button>
          </div>
        </a-tab-pane>

        <!-- Tab 2：手动添加 ASIN -->
        <a-tab-pane key="manual" tab="✍️ 手动添加 ASIN">
          <div class="tab-pane-body">
            <a-textarea
              v-model:value="manualAsins"
              :rows="2"
              placeholder="粘贴 ASIN，多个用逗号/换行分隔（如 B0XXXX1, B0XXXX2）"
            />
            <div class="tab-pane-actions">
              <a-button size="small" @click="cancelManual">清空</a-button>
              <a-button size="small" type="primary" :loading="addingManual" @click="doAddManual">添加</a-button>
            </div>
          </div>
        </a-tab-pane>

        <!-- Tab 3：从其它产品复制 -->
        <a-tab-pane key="copy" tab="📋 从其它复制">
          <div class="tab-pane-body">
            <a-select
              v-model:value="copySourceOwner"
              show-search
              option-filter-prop="label"
              placeholder="选择要复制的竞品池来源"
              :disabled="copyOptions.length === 0"
              style="width: 100%"
            >
              <a-select-option v-for="o in copyOptions" :key="o.key" :value="o.key" :label="o.label">
                {{ o.label }}
              </a-select-option>
            </a-select>
            <div class="tab-pane-actions">
              <a-button size="small" @click="copySourceOwner = ''">清空</a-button>
              <a-button size="small" type="primary" :disabled="!copySourceOwner" @click="doCopy">复制</a-button>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>

      <!-- 竞品列表 -->
      <div class="pool-list">
        <template v-if="poolList.length">
          <div v-for="c in poolList" :key="c.asin" class="pool-item" :class="{ disabled: !c.enabled }">
            <a-switch
              :checked="c.enabled"
              size="small"
              @change="(v: boolean) => cp.setEnabled(ownerType, owner!.asin, c.asin, v)"
            />
            <img v-if="c.main_image" class="thumb" :src="c.main_image" alt="" @error="onImgError" />
            <span v-else class="thumb-ph">🖼️</span>
            <div class="info">
              <div class="title">{{ c.title || c.asin }}</div>
              <div class="meta">
                <span class="asin">{{ c.asin }}</span>
                <a-tag :color="sourceColor(c.source)" size="small" style="margin-inline-end:0">{{ sourceLabel(c.source) }}</a-tag>
                <span v-if="c.brand" class="brand">{{ c.brand }}</span>
              </div>
            </div>
            <a-button
              type="text"
              size="small"
              class="mon-btn"
              :disabled="ownerType === 'session' && !owner?.asin"
              @click="toggleMonitor(c)"
            >
              {{ mp.isAsinInPool(c.asin) ? '已监控' : '＋监控' }}
            </a-button>
            <a-button type="text" danger size="small" @click="cp.removeRef(ownerType, owner!.asin, c.asin)">
              <DeleteOutlined />
            </a-button>
          </div>
        </template>
        <div v-else class="empty">
          <InboxOutlined style="font-size:28px; color:#d9d9d9" />
          <p>暂无竞品。点「一键生成相似竞品」或手动添加</p>
        </div>
      </div>

      <!-- 底部持久化操作 -->
      <div class="footer-actions">
        <div v-if="ownerType === 'session'" class="mode-switch">
          <a-alert type="info" :show-icon="false" banner style="font-size:12px">
            <template #message>会话临时竞品 · 切换 Agent / 离开对话即清空</template>
          </a-alert>
          <div class="mode-btns">
            <a-button @click="closeSessionOnly">仅本次会话生效</a-button>
            <a-button type="primary" :loading="savingToProduct" @click="saveToCandidateLibrary">
              <SaveOutlined /> 保存至选品库
            </a-button>
          </div>
        </div>
        <div v-else class="mode-switch">
          <a-alert type="success" :show-icon="false" banner style="font-size:12px">
            <template #message>此池绑定主品（已启用竞品将写回 competitor_asins 持久保存）</template>
          </a-alert>
          <div class="mode-btns">
            <a-button type="primary" :loading="savingToProduct" @click="savePersist">保存</a-button>
          </div>
        </div>
      </div>
    </div>

    </a-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  ThunderboltOutlined, DeleteOutlined, InboxOutlined, SaveOutlined,
} from '@ant-design/icons-vue'
import {
  useCompetitorPoolStore,
  type CompetitorOwnerType,
  type CompetitorRef,
} from '@/stores/competitorPool'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import { useMonitorPoolStore } from '@/stores/monitorPool'

const props = defineProps<{
  open: boolean
  owner: { asin: string; title?: string; brand?: string; category?: string; keywords?: string[]; main_image?: string } | null
  ownerType?: CompetitorOwnerType
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'saved', ownerAsin: string, ownerType: CompetitorOwnerType): void
}>()

const cp = useCompetitorPoolStore()
const prodStore = useProductLibraryStore()
const candStore = useCandidateLibraryStore()
const mp = useMonitorPoolStore()

// 预加载候选/产品库，供复制来源与推荐
watch(() => props.open, (o) => {
  if (!o) return
  if (!candStore.items.length) candStore.fetchItems().catch(() => {})
  if (!prodStore.items.length) prodStore.fetchItems().catch(() => {})
})

const ownerType = computed<CompetitorOwnerType>(() => props.ownerType || 'session')
/** 模板可访问的 owner 别名 */
const owner = computed(() => props.owner)
const ownerKey = computed(() => props.owner ? props.owner.asin : '')

const poolList = computed<CompetitorRef[]>(() =>
  ownerKey.value ? cp.poolCompetitors(ownerType.value, ownerKey.value) : []
)
const poolLength = computed(() => poolList.value.length)
const enabledCount = computed(() => cp.enabledCount(ownerType.value, ownerKey.value))

// ===== 自动推荐 =====
const recommending = ref(false)
async function doRecommend() {
  if (!props.owner) return
  recommending.value = true
  try {
    const added = await cp.recommendSimilar(ownerType.value, props.owner.asin, {
      title: props.owner.title,
      category: props.owner.category,
      keywords: props.owner.keywords,
      count: 12,
    })
    if (added.length) message.success(`已推荐 ${added.length} 个相似竞品，可删除不相关项`)
    else message.info('未找到更多相似竞品')
  } finally {
    recommending.value = false
  }
}

// ===== 添加来源 Tab 切换（三来源互斥：recommend / manual / copy）=====
type AddSource = 'recommend' | 'manual' | 'copy'
const addSource = ref<AddSource>('recommend')

// ===== 手动添加 =====
const manualAsins = ref('')
const addingManual = ref(false)
function cancelManual() {
  manualAsins.value = ''
}
async function doAddManual() {
  if (!props.owner) return
  const list = manualAsins.value.split(/[\s,，;；]+/).map(s => s.trim()).filter(s => /^[A-Z0-9]{8,12}$/i.test(s))
  if (!list.length) { message.warning('未识别到有效 ASIN'); return }
  addingManual.value = true
  try {
    const n = await cp.addManual(ownerType.value, props.owner.asin, {
      ownerTitle: props.owner.title,
      asins: list,
    })
    if (n) message.success(`已添加 ${n} 个竞品`)
    else message.warning('无新增（可能已存在或超上限 20）')
    cancelManual()
  } finally { addingManual.value = false }
}

// ===== 复制 =====
const copySourceOwner = ref('')
const copyOptions = computed(() => {
  const items = [
    ...prodStore.items.map(p => ({ asin: p.asin, title: p.title, type: 'product' })),
    ...candStore.items.map(c => ({ asin: c.asin, title: c.title, type: 'candidate' })),
  ]
  return items
    .filter(i => i.asin !== props.owner?.asin)
    .map(i => ({ key: `${i.type}|${i.asin}`, label: `${i.title.slice(0, 22)} (${i.asin})` }))
})
function doCopy() {
  if (!props.owner || !copySourceOwner.value) return
  const [stype, sasin] = copySourceOwner.value.split('|')
  const srcPool = cp.getPool(stype as CompetitorOwnerType, sasin)
  if (!srcPool || !srcPool.competitors.length) { message.info('该产品暂无竞品池'); addSource.value = 'recommend'; return }
  const n = cp.copyFromPool(ownerType.value, props.owner.asin, {
    targetTitle: props.owner.title,
    sourceOwnerType: stype as CompetitorOwnerType,
    sourceAsin: sasin,
  })
  message.success(`已复制 ${n} 个竞品`)
  copySourceOwner.value = ''
  addSource.value = 'recommend'
  copySourceOwner.value = ''
}

// ===== 持久化 =====
const savingToProduct = ref(false)

/** 模式A：仅会话 —— 直接把当前池留在 session 层，关弹窗即可（session 池本就只存内存） */
function closeSessionOnly() {
  message.success('竞品已保留（仅本次会话）')
  emit('update:open', false)
}

/** 模式B（从会话候选）「保存至选品库」：确保候选已入 candidateLibrary → 把会话池提升为候选 owner 并持久化 */
async function saveToCandidateLibrary() {
  if (!props.owner) return
  savingToProduct.value = true
  try {
    // 1) 若候选库里还没有该 asin，先建一条候选记录
    if (!candStore.items.some(c => c.asin === props.owner!.asin)) {
      await candStore.addItem({
        asin: props.owner.asin,
        sku: `SKU-CAND-${props.owner.asin}`,
        title: props.owner.title || props.owner.asin,
        brand: props.owner.brand || '',
        category: props.owner.category || 'other',
        sub_category: '',
        price: 0,
        currency: 'USD',
        estimated_monthly_sales: 0,
        review_count: 0,
        rating: 0,
        bsr: null,
        roi_estimated: 0,
        margin: 0,
        blue_ocean_score: 0,
        overall_listing_score: 0,
        main_image: props.owner.main_image || '',
        source: 'blue_ocean',
        review_status: 'pending',
        review_notes: '',
        reviewed_at: null,
        reviewed_by: null,
        monitor_data: null,
        last_monitored_at: null,
        shop_id: '',
        tags: ['竞品管理'],
        notes: '从候选竞品维护保存至选品库',
        groups: [],
      })
    }
    // 2) 把本次会话池提升为候选 owner，并持久化已启用竞品
    cp.adoptSessionToOwner(props.owner.asin, 'candidate', props.owner.asin, props.owner.title)
    const asins = await cp.persistToOwner('candidate', props.owner.asin)
    if (asins === null) { message.error('保存失败：未能写入选品库记录'); return }
    message.success(`已保存 ${asins.length} 个对标竞品至选品库`)
    emit('saved', props.owner.asin, 'candidate')
    emit('update:open', false)
  } finally { savingToProduct.value = false }
}

/** 对 product/candidate owner：直接把已启用 asins 写回对应记录 */
async function savePersist() {
  if (!props.owner) return
  savingToProduct.value = true
  try {
    const asins = await cp.persistToOwner(ownerType.value as 'product' | 'candidate', props.owner.asin)
    if (asins === null) {
      message.error('未找到匹配的主品记录，无法持久化（请先保存主品再维护竞品）')
      return
    }
    message.success(`已保存 ${asins.length} 个对标竞品`)
    emit('saved', props.owner.asin, ownerType.value as 'product' | 'candidate')
    emit('update:open', false)
  } finally { savingToProduct.value = false }
}

// ===== UI helpers =====
const sourceLabel = (s: CompetitorRef['source']) => s === 'auto' ? '推荐' : s === 'manual' ? '手动' : '复制'
const sourceColor = (s: CompetitorRef['source']) => s === 'auto' ? 'geekblue' : s === 'manual' ? 'gold' : 'purple'

/** 竞品行「＋监控」：把该对标竞品纳入统一监控池，归属当前主品项目（定向监控） */
function toggleMonitor(c: CompetitorRef) {
  if (!props.owner) return
  if (mp.isAsinInPool(c.asin)) {
    message.info(`${c.asin} 已在监控池（竞品监控页可查看走势）`)
    return
  }
  // 归属：product/candidate 直接绑定；session（候选草稿）按候选归属（该 asin 将成为候选）
  const ownType = ownerType.value === 'session' ? 'candidate' : ownerType.value
  mp.addFromCompetitor({
    asin: c.asin,
    title: c.title,
    brand: c.brand,
    main_image: c.main_image,
    category: props.owner.category,
    ownedBy: {
      type: (ownType === 'product' ? 'product' : 'candidate') as 'product' | 'candidate',
      asin: props.owner.asin,
      title: props.owner.title,
    },
  })
  message.success(`已将 ${c.asin} 加入监控池（归属「${props.owner.title || props.owner.asin}」）`)
}

function onImgError(e: Event) { ;(e.target as HTMLImageElement).style.display = 'none' }
</script>

<style scoped>
.competitor-manager { display: flex; flex-direction: column; gap: 12px; }
.pool-hint { font-size: 12px; color: #8c8c8c; }
.cm-source-tabs { margin-top: -4px; }
.tab-pane-body { padding: 12px 4px 4px; display: flex; flex-direction: column; gap: 10px; }
.tab-pane-actions { display: flex; justify-content: flex-end; gap: 8px; }
.tab-hint { margin: 0; font-size: 12px; color: #8c8c8c; }
.pool-list { display: flex; flex-direction: column; gap: 6px; max-height: 320px; overflow-y: auto; }
.pool-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px;
  border: 1px solid #f0f0f0; border-radius: 6px; background: #fff;
}
.pool-item.disabled { opacity: 0.55; }
.thumb { width: 36px; height: 36px; object-fit: cover; border-radius: 4px; border: 1px solid #f0f0f0; background: #fafafa; }
.thumb-ph { width: 36px; height: 36px; flex-shrink: 0; display:flex; align-items:center; justify-content:center; border-radius:4px; background:#fafafa; border:1px solid #f0f0f0; }
.info { flex: 1; min-width: 0; }
.title { font-size: 12px; color: #262626; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.asin { font-size: 10px; color: #8c8c8c; font-family: 'SF Mono', Monaco, monospace; }
.brand { font-size: 10px; color: #bfbfbf; }
.mon-btn { font-size: 11px; color: #1890ff; padding: 0 4px; white-space: nowrap; }
.empty { text-align: center; padding: 28px 0; color: #8c8c8c; }
.footer-actions { border-top: 1px solid #f0f0f0; padding-top: 12px; }
.mode-btns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
</style>
