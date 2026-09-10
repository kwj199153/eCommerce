<template>
  <div class="competitor-config">
    <!-- 入口3：维护当前载入主品(选品)的竞品池，供本次对比直接带出 -->
    <div class="pool-entry">
      <div class="pool-entry-main">
        <a-button size="small" @click="openPoolManager">
          <TeamOutlined /> 维护对标竞品池
        </a-button>
        <span class="pool-entry-hint">
          {{ loadedOwner?.obj?.title ? `当前主角：${loadedOwner.obj.title.slice(0, 12)}` : '先载入主品/选品，可在此维护其竞品集' }}
        </span>
      </div>
    </div>

    <!-- 本次对比竞品 = 当前主品竞品池中已启用的竞品（只读） -->
    <div class="form-group">
      <label>本次对比竞品（自动取自主品竞品池 · 最多 5 个）</label>
      <template v-if="poolEnabledList.length">
        <div class="compare-source-list">
          <div v-for="c in poolEnabledList" :key="c.asin" class="compare-source-item">
            <img v-if="c.main_image" class="thumb" :src="c.main_image" alt="" @error="onImgError" />
            <span v-else class="thumb-ph">🖼️</span>
            <div class="info">
              <div class="title">{{ c.title || c.asin }}</div>
              <div class="meta">
                <span class="asin">{{ c.asin }}</span>
                <a-tag color="blue" size="small" style="margin-inline-end:0">对标</a-tag>
              </div>
            </div>
          </div>
          <div v-if="poolEnabledList.length > compareLimit" class="overflow-hint">
            池内已启用 {{ poolEnabledList.length }} 个，一次仅对比前 {{ compareLimit }} 个
          </div>
        </div>
      </template>
      <div v-else class="compare-empty">
        <InboxOutlined style="font-size:22px; color:#d9d9d9" />
        <p v-if="loadedOwner">该主品暂无启用的对标竞品。点上方「维护对标竞品池」先添加</p>
        <p v-else>请先「载入选品 / 载入产品」选定主品，再维护它的对标竞品池</p>
      </div>
    </div>

    <div class="form-group">
      <label>对比维度</label>
      <a-checkbox-group v-model:value="form.dimensions" style="width: 100%">
        <div class="checkbox-row">
          <a-checkbox value="price">价格定位</a-checkbox>
          <a-checkbox value="rating">评分评论</a-checkbox>
        </div>
        <div class="checkbox-row">
          <a-checkbox value="listing">Listing质量</a-checkbox>
          <a-checkbox value="bsr">BSR排名</a-checkbox>
        </div>
        <div class="checkbox-row">
          <a-checkbox value="swot">SWOT分析</a-checkbox>
          <a-checkbox value="positioning">市场定位</a-checkbox>
        </div>
      </a-checkbox-group>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button type="primary" block @click="handleSubmit" :loading="loading" :disabled="poolEnabledList.length < 2">
        <SearchOutlined /> 开始对比分析（{{ poolEnabledList.length }} 个竞品）
      </a-button>
    </div>

    <!-- 竞品池管理（入口3） -->
    <CompetitorManager
      v-model:open="cmOpen"
      :owner="cmOwner"
      :owner-type="cmOwnerType"
      @saved="onPoolSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, inject, type Ref } from 'vue'
import { SearchOutlined, TeamOutlined, InboxOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import CompetitorManager from '@/components/competitor/CompetitorManager.vue'
import { useCompetitorPoolStore, COMPARE_SELECT_LIMIT, type CompetitorOwnerType } from '@/stores/competitorPool'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const cp = useCompetitorPoolStore()

// ====== 入口3：当前载入的主品/选品（工作上下文） ======
const candStore = useCandidateLibraryStore()
const workingCandidate = inject<Ref<any>>('workingCandidate', ref(null))
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

/** 竞品管理弹窗 */
const cmOpen = ref(false)
const cmOwnerType = ref<CompetitorOwnerType>('session')
const cmOwner = ref<{ asin: string; title?: string; brand?: string; category?: string; keywords?: string[]; main_image?: string } | null>(null)

/** 当前可作为“主角”维护竞品集的对象（优先载入的选品，其次载入的产品） */
const loadedOwner = computed(() => {
  if (workingCandidate?.value) return { type: 'candidate', obj: workingCandidate.value }
  if (workingProduct?.value) return { type: 'product', obj: workingProduct.value }
  return null
})

/** 解析当前主角的 ownerType（与池一致）：产品=product；选品若已在候选库=candidate，否则 session */
const poolOwnerType = computed<CompetitorOwnerType>(() => {
  const o = loadedOwner.value
  if (!o) return 'session'
  if (o.type === 'product') return 'product'
  return candStore.items.some(c => c.asin === o.obj.asin) ? 'candidate' : 'session'
})

/** 一次对比上限 */
const compareLimit = COMPARE_SELECT_LIMIT

/** 当前主品竞品池中已启用的竞品（作为本次对比对象） */
const poolEnabledList = computed(() => {
  const o = loadedOwner.value
  if (!o) return []
  return cp.poolCompetitors(poolOwnerType.value, o.obj.asin).filter(c => c.enabled)
})

/** 若竞品池为空，载入后跟随 loadedOwner 变化兜底清空 cmOwner 状态 */
const ownerAsin = computed(() => loadedOwner.value?.obj?.asin || '')

function openPoolManager() {
  if (!loadedOwner.value) {
    message.info('请先在顶部【载入选品】或【载入产品】选定主品，再维护它的竞品池')
    return
  }
  const o = loadedOwner.value
  cmOwner.value = {
    asin: o.obj.asin,
    title: o.obj.title || o.obj.asin,
    brand: o.obj.brand || '',
    category: o.obj.category || '',
    keywords: Array.isArray(o.obj.keywords) ? o.obj.keywords : [],
    main_image: o.obj.main_image || '',
  }
  cmOwnerType.value = poolOwnerType.value
  cmOpen.value = true
}

/** 池保存后：列表响应式已自动更新，关闭提示即可 */
function onPoolSaved() {
  if (!poolEnabledList.value.length) message.info('该主品暂未启用任何竞品')
}

const defaultForm = () => ({
  dimensions: ['price', 'rating', 'listing', 'swot'] as string[],
})

const form = reactive(defaultForm())

onMounted(() => {
  try {
    const saved = localStorage.getItem('competitor_config')
    if (saved) {
      const parsed = JSON.parse(saved)
      if (Array.isArray(parsed.dimensions) && parsed.dimensions.length) {
        form.dimensions = parsed.dimensions
      }
    }
  } catch (e) {}
})

const handleSubmit = () => {
  if (!loadedOwner.value) {
    message.warning('请先载入主品/选品')
    return
  }
  const list = poolEnabledList.value
  if (list.length < 2) {
    message.warning('该主品至少需要 2 个启用的对标竞品才能对比')
    return
  }
  loading.value = true

  const params = {
    owner: loadedOwner.value.obj,
    validAsins: list.slice(0, compareLimit).map(c => c.asin),
    asins: list.slice(0, compareLimit).map(c => c.asin),
    dimensions: form.dimensions,
    fromPool: true,
  }

  const toSave = { dimensions: form.dimensions }
  localStorage.setItem('competitor_config', JSON.stringify(toSave))

  emit('startAnalysis', params)
  setTimeout(() => (loading.value = false), 500)
}

function onImgError(e: Event) { ;(e.target as HTMLImageElement).style.display = 'none' }
</script>

<style scoped>
.competitor-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pool-entry {
  padding: 8px;
  border: 1px dashed #91d5ff;
  border-radius: 6px;
  background: #e6f7ff;
}
.pool-entry-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pool-entry-hint { font-size: 10px; color: #1890ff; }

.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 4px;
  font-weight: 500;
}

/* 本次对比竞品（只读，来自池） */
.compare-source-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.compare-source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  background: #fafafa;
}
.thumb { width: 32px; height: 32px; object-fit: cover; border-radius: 4px; border: 1px solid #f0f0f0; background: #fff; }
.thumb-ph { width: 32px; height: 32px; flex-shrink: 0; display:flex; align-items:center; justify-content:center; border-radius:4px; background:#f5f5f5; border:1px solid #f0f0f0; font-size:14px; }
.info { flex: 1; min-width: 0; }
.title { font-size: 12px; color: #262626; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.asin { font-size: 10px; color: #8c8c8c; font-family: 'SF Mono', Monaco, monospace; }
.overflow-hint { font-size: 11px; color: #d48806; padding-left: 4px; }
.compare-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px; padding: 18px 8px; border: 1px dashed #f0f0f0; border-radius: 6px; background: #fafafa;
}
.compare-empty p { margin: 0; font-size: 11px; color: #8c8c8c; text-align: center; }

.checkbox-row {
  display: flex;
  gap: 16px;
  margin-bottom: 4px;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}
</style>
