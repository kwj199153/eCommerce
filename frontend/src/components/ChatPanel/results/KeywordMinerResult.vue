<template>
  <div class="keyword-miner-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">🔑</span>
        <div>
          <h3>关键词挖掘结果</h3>
          <p class="subtitle">共挖掘 {{ keywordRows.length }} 个候选关键词 · 基于「{{ resultData.seed_keywords?.join('、') || '种子词' }}」</p>
        </div>
      </div>
      <div class="header-actions">
        <!-- 产品库模式：把挖掘词合并进当前产品的核心关键词 -->
        <a-button
          v-if="sourceMode === 'product' && productId"
          type="primary"
          size="small"
          @click="handleSaveToProduct"
          :loading="saving"
        >
          <SaveOutlined /> 应用到当前产品 Listing
        </a-button>
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 统计概览 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">候选词</div>
      </div>
      <div class="stat-card stat-low">
        <div class="stat-value">{{ stats.lowCompetition }}</div>
        <div class="stat-label">低竞争高相关</div>
      </div>
      <div class="stat-card stat-good">
        <div class="stat-value">{{ stats.recommended }}</div>
        <div class="stat-label">推荐投放</div>
      </div>
      <div class="stat-card stat-avg">
        <div class="stat-value">{{ stats.avgRelevance }}</div>
        <div class="stat-label">平均相关度</div>
      </div>
    </div>

    <!-- 关键词表格（词条可编辑） -->
    <div class="table-toolbar">
      <a-space>
        <a-button size="small" type="dashed" @click="addRow">
          <PlusOutlined /> 新增候选词
        </a-button>
        <a-button size="small" type="text" @click="resetRows" :disabled="!isRowsEdited" title="还原为 AI 挖掘原值">
          <UndoOutlined /> 还原
        </a-button>
        <span class="edit-hint"><EditOutlined /> 关键词文本可直接修改，指标（搜索量/竞争度/出价/相关性）由 AI 给出，保持只读</span>
      </a-space>
    </div>

    <div class="table-wrap">
      <a-table
        :data-source="sortedRows"
        :columns="columns"
        :pagination="{ pageSize: 8, size: 'small' }"
        size="small"
        :scroll="{ y: 320 }"
        :row-key="(record: any) => record.__rid"
        :row-selection="rowSelection"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'keyword'">
            <a-input
              v-model:value="record.keyword"
              size="small"
              class="kw-input"
              @click.stop
            />
            <span v-if="record.source === 'competitor'" class="kw-badge comp">竞品</span>
            <span v-else-if="record.source === 'seed_expand'" class="kw-badge expand">种子扩展</span>
            <span v-else-if="record.source === 'long_tail'" class="kw-badge tail">长尾</span>
            <span v-else class="kw-badge manual">自填</span>
          </template>
          <template v-else-if="column.key === 'search_volume'">
            <span class="vol">{{ (record.search_volume ?? 0).toLocaleString?.() || record.search_volume }}</span>
          </template>
          <template v-else-if="column.key === 'competition'">
            <a-tag :color="compColor(record.competition)">{{ compLabel(record.competition) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'bid'">
            <span>${{ Number(record.suggested_bid || 0).toFixed(2) }}</span>
          </template>
          <template v-else-if="column.key === 'relevance'">
            <a-progress :percent="record.relevance" :stroke-color="relevanceColor(record.relevance)" :show-info="false" size="small" style="width: 90px" />
            <span class="rel-val">{{ record.relevance }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="text" size="small" danger @click="removeRow(record)">
              <DeleteOutlined />
            </a-button>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 推荐词云/摘要 -->
    <div class="summary-box" v-if="resultData.summary">
      <div class="summary-body" v-html="md.render(resultData.summary)"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  CloseOutlined, SaveOutlined, PlusOutlined, DeleteOutlined,
  UndoOutlined, EditOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import MarkdownIt from 'markdown-it'
import { useProductLibraryStore } from '@/stores/productLibrary'

const props = defineProps<{
  data: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const md = new MarkdownIt()
const productStore = useProductLibraryStore()
const saving = ref(false)
const selectedRids = ref<string[]>([])

const sourceMode = computed(() => props.data?._source || 'manual')
const productId = computed(() => props.data?.product_id)

const resultData = props.data || {}

// 从 AI 原值提取关键词列表（任意结构）
const rawList = computed(() => {
  if (Array.isArray(resultData.keywords)) return resultData.keywords
  // 兼容 executeKeywordMiner 其它结构
  if (Array.isArray(resultData.items)) return resultData.items
  return []
})

// ====== 响应式可编辑行 ======
let ridSeq = 0
const keywordRows = ref<any[]>([])
function seedRows() {
  const seed = rawList.value.map((k: any) => {
    // keyword 既可能是对象也可能是字符串
    const obj = typeof k === 'string' ? { keyword: k } : (k || {})
    return {
      __rid: `k${++ridSeq}`,
      source: obj.source || 'manual',
      keyword: obj.keyword || obj.word || '',
      search_volume: obj.search_volume ?? 0,
      competition: obj.competition || 'medium',
      suggested_bid: obj.suggested_bid ?? 0,
      relevance: obj.relevance ?? 60,
    }
  })
  keywordRows.value = seed
}
watch(() => props.data, () => seedRows(), { immediate: true })

// 排序展示（按相关度降序），但不改变底层行对象引用以便 v-model
const sortedRows = computed(() =>
  [...keywordRows.value].sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
)

const isRowsEdited = computed(() => {
  const seed = rawList.value.map((k: any) => (typeof k === 'string' ? k : (k.keyword || k.word || '')))
  if (seed.length !== keywordRows.value.length) return true
  return keywordRows.value.some((r, i) => r.keyword !== seed[i])
})
const resetRows = () => seedRows()

const addRow = () => {
  keywordRows.value.push({
    __rid: `k${++ridSeq}`,
    source: 'manual',
    keyword: '',
    search_volume: 0,
    competition: 'medium',
    suggested_bid: 0,
    relevance: 60,
  })
}
const removeRow = (record: any) => {
  keywordRows.value = keywordRows.value.filter(r => r.__rid !== record.__rid)
}

// 统计（基于当前行）
const stats = computed(() => {
  const rows = keywordRows.value
  return {
    total: rows.length,
    lowCompetition: rows.filter(k => k.competition === 'low' && k.relevance >= 85).length,
    recommended: rows.filter(k => k.relevance >= 90 && k.competition !== 'high').length,
    avgRelevance: rows.length ? Math.round(rows.reduce((s, k) => s + (k.relevance || 0), 0) / rows.length) : 0,
  }
})

const columns = [
  { title: '关键词（可编辑）', key: 'keyword', ellipsis: false },
  { title: '月搜索量', key: 'search_volume', width: 120 },
  { title: '竞争度', key: 'competition', width: 100 },
  { title: '建议出价', key: 'bid', width: 120 },
  { title: '相关性', key: 'relevance', width: 150 },
  { title: '操作', key: 'action', width: 48 },
]

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRids.value,
  onChange: (keys: any[]) => { selectedRids.value = keys as string[] },
}))

const compColor = (c: string) => ({ low: 'green', medium: 'orange', high: 'red' }[c] || 'default')
const compLabel = (c: string) => ({ low: '低', medium: '中', high: '高' }[c] || c)
const relevanceColor = (r: number) => (r >= 90 ? '#52c41a' : r >= 75 ? '#faad14' : '#ff4d4f')

// ====== 应用到当前产品 Listing（合并挖掘词进 product.keywords）======
const handleSaveToProduct = async () => {
  if (!productId.value) return
  // 收集有效关键词（非空去重）
  const valid = keywordRows.value
    .map((r: any) => String(r.keyword || '').trim())
    .filter(Boolean)
  if (!valid.length) return message.warning('没有可应用的候选关键词')

  // 命中勾选行（若有勾选则只用勾选的那几条，否则用全部高相关）
  let pickTexts: string[]
  if (selectedRids.value.length) {
    const ridSet = new Set(selectedRids.value)
    pickTexts = keywordRows.value.filter(r => ridSet.has(r.__rid)).map((r: any) => String(r.keyword || '').trim()).filter(Boolean)
  } else {
    pickTexts = valid
  }
  if (!pickTexts.length) return message.info('没有可应用的候选关键词')

  saving.value = true
  try {
    const p = productStore.items.find((i: any) => i.id === productId.value)
    const existing = new Set((p?.keywords || []).map((k: string) => k.toLowerCase()))
    const merged = (p?.keywords || []).slice()
    const added: string[] = []
    pickTexts.forEach(kw => {
      if (!existing.has(kw.toLowerCase())) {
        merged.push(kw)
        existing.add(kw.toLowerCase())
        added.push(kw)
      }
    })
    if (!added.length) return message.info('所选关键词均已在产品核心关键词中，无需重复添加')

    await productStore.updateItem(productId.value, { keywords: merged })
    message.success(`已合并 ${added.length} 个关键词到当前产品（累计 ${merged.length} 个）`)
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.keyword-miner-result { background: var(--bg-elevated); border-radius: 8px; overflow: hidden; }

.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px; border-bottom: 1px solid #f0f0f0;
  background: linear-gradient(135deg, #36cfc9 0%, #13c2c2 100%);
  color: #fff;
}
.header-info { display: flex; align-items: center; gap: 12px; }
.result-icon { font-size: 26px; }
.header-info h3 { margin: 0; font-size: 16px; color: #fff; }
.subtitle { margin: 2px 0 0; font-size: 12px; opacity: 0.9; }
.header-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.header-actions :deep(.ant-btn) { background: rgba(255,255,255,.95); }
.header-actions :deep(.ant-btn-primary) { background: #1890ff; }

.stats-row { display: flex; gap: 10px; padding: 12px 20px; flex-wrap: wrap; }
.stat-card { flex: 1; min-width: 100px; background: #f7f9fc; border-radius: 6px; padding: 8px 12px; text-align: center; }
.stat-value { font-size: 18px; font-weight: 700; }
.stat-card.stat-low .stat-value { color: #52c41a; }
.stat-card.stat-good .stat-value { color: #1890ff; }
.stat-card.stat-avg .stat-value { color: #722ed1; }
.stat-label { font-size: 12px; color: var(--text-tertiary); }

.table-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 20px 8px; flex-wrap: wrap; gap: 6px;
}
.edit-hint { font-size: 12px; color: var(--text-tertiary); }

.table-wrap { padding: 0 20px 12px; }
.kw-input { border: 1px dashed #d9d9d9 !important; border-radius: 4px; font-weight: 500; color: #1a1a1a; width: 100%; }
.kw-input:focus { border: 1px solid #13c2c2 !important; box-shadow: 0 0 0 2px rgba(19, 194, 194, 0.1); }
.kw-badge { font-size: 11px; padding: 0 5px; border-radius: 3px; margin-left: 6px; }
.kw-badge.comp { background: var(--bg-elevated)1f0; color: #cf1322; }
.kw-badge.expand { background: #f0f5ff; color: #2f54eb; }
.kw-badge.tail { background: #f6ffed; color: #389e0d; }
.kw-badge.manual { background: var(--bg-hover-light); color: var(--text-secondary); }
.rel-val { margin-left: 6px; font-size: 12px; font-weight: 600; }

.summary-box { margin: 0 20px 16px; background: #f7f9fc; border-radius: 6px; padding: 12px 16px; font-size: 13px; }
.summary-body :deep(p) { margin: 0 0 4px; }
</style>
