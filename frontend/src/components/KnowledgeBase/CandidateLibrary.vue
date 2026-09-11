<template>
  <div class="cand-page">
    <!-- 统计卡片：评审状态机概览 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ store.totalCount }}</div>
        <div class="stat-label">候选总数</div>
      </div>
      <div class="stat-card stat-reviewing">
        <div class="stat-value orange">{{ store.underReviewCount }}</div>
        <div class="stat-label">评审中</div>
      </div>
      <div class="stat-card stat-approved">
        <div class="stat-value green">{{ store.approvedCount }}</div>
        <div class="stat-label">已通过</div>
      </div>
      <div class="stat-card stat-rejected">
        <div class="stat-value gray">{{ store.rejectedCount }}</div>
        <div class="stat-label">已淘汰</div>
      </div>
    </div>

    <!-- 操作栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <a-input-search
          v-model:value="store.searchQuery"
          placeholder="搜索标题、ASIN、品牌..."
          style="width: 260px"
          allow-clear
        >
          <template #prefix><SearchOutlined /></template>
        </a-input-search>
        <a-select
          v-model:value="store.filterReviewStatus"
          style="width: 140px"
          placeholder="全部评审状态"
          allow-clear
        >
          <a-select-option value="pending">草稿 ({{ store.pendingCount }})</a-select-option>
          <a-select-option value="under_review">🔵 评审中 ({{ store.underReviewCount }})</a-select-option>
          <a-select-option value="approved">🟢 已通过 ({{ store.approvedCount }})</a-select-option>
          <a-select-option value="rejected">🔴 已淘汰 ({{ store.rejectedCount }})</a-select-option>
        </a-select>
        <a-select v-model:value="store.sortBy" style="width: 140px">
          <a-select-option value="updated_at">最近更新</a-select-option>
          <a-select-option value="blue_ocean_score">蓝海评分</a-select-option>
          <a-select-option value="roi">ROI</a-select-option>
          <a-select-option value="sales">预估月销</a-select-option>
          <a-select-option value="rating">评分</a-select-option>
          <a-select-option value="price">售价</a-select-option>
        </a-select>
      </div>
      <div class="toolbar-right">
        <a-popconfirm
          v-if="selectedRowKeys.length > 0"
          :title="`确认删除选中的 ${selectedRowKeys.length} 个候选？`"
          @confirm="handleBatchDelete"
        >
          <a-button danger>
            <DeleteOutlined /> 批量删除 ({{ selectedRowKeys.length }})
          </a-button>
        </a-popconfirm>
        <a-button
          v-if="monitorableSelected.length > 0"
          type="primary"
          @click="openAddToMonitor(monitorableSelected)"
        >
          <FundOutlined /> 开启监控 ({{ monitorableSelected.length }})
        </a-button>
        <a-tooltip title="从文件批量导入候选（支持 JSON / CSV / TXT）">
          <a-button @click="showImportModal = true">
            <UploadOutlined /> 导入候选
          </a-button>
        </a-tooltip>
        <a-button type="primary" @click="openAddModal">
          <PlusOutlined /> 新增候选
        </a-button>
      </div>
    </div>

    <!-- 已应用的过滤条件（chip 行，一键清除） -->
    <div v-if="store.hasActiveFilters" class="active-filters">
      <span class="af-label">
        <FilterOutlined /> 已启用过滤 ({{ store.activeFilterCount }})
      </span>

      <!-- 当前分组 -->
      <a-tag
        v-if="store.currentGroupId"
        closable
        @close="store.selectGroup(null)"
        :color="currentGroupColor"
        class="af-chip"
      >
        {{ currentGroupLabel }}
      </a-tag>

      <!-- 评审状态 -->
      <a-tag
        v-if="store.filterReviewStatus && store.filterReviewStatus !== 'all'"
        closable
        @close="store.filterReviewStatus = undefined"
        :color="COLOR_INFO"
        class="af-chip"
      >
        评审：{{ reviewStatusMeta(store.filterReviewStatus as ReviewStatus).label }}
      </a-tag>

      <!-- 商品分类 -->
      <a-tag
        v-if="store.filterCategory && store.filterCategory !== 'all'"
        closable
        @close="store.filterCategory = undefined"
        :color="COLOR_INFO"
        class="af-chip"
      >
        分类：{{ CATEGORY_ICON[store.filterCategory] || '📦' }} {{ CATEGORY_LABEL[store.filterCategory] || store.filterCategory }}
      </a-tag>

      <!-- 搜索词 -->
      <a-tag
        v-if="store.searchQuery.trim()"
        closable
        @close="store.searchQuery = ''"
        :color="COLOR_INFO"
        class="af-chip"
      >
        搜索："{{ store.searchQuery }}"
      </a-tag>

      <!-- 一键清空 -->
      <a-button type="link" size="small" danger @click="store.clearAllFilters()">
        <ClearOutlined /> 清空全部
      </a-button>
    </div>

    <!-- 候选列表表格 -->
    <a-table
      :columns="columns"
      :data-source="store.filteredItems"
      :loading="store.isLoading"
      row-key="id"
      :row-selection="{ selectedRowKeys, onChange: onSelectChange }"
      :pagination="{ pageSize: 12, size: 'small', showTotal: (t: number) => `共 ${t} 个候选` }"
      size="middle"
      :scroll="{ y: 'calc(100vh - 360px)' }"
    >
      <template #bodyCell="{ column, record }">
        <!-- 标题列 -->
        <template v-if="column.key === 'title'">
          <a-popover placement="rightTop" trigger="hover" :overlayStyle="{ width: '320px' }">
            <template #content>
              <div class="hover-preview">
                <img v-if="record.main_image" :src="record.main_image" alt="" class="hp-img" @error="(e: Event) => (e.target as HTMLImageElement).style.display = 'none'" />
                <div class="hp-body">
                  <div class="hp-title">{{ record.title }}</div>
                  <div class="hp-meta">
                    <a-tag color="blue" size="small">{{ record.asin }}</a-tag>
                    <span v-if="record.brand" class="hp-brand">{{ record.brand }}</span>
                    <span v-if="record.sub_category" class="hp-cat">{{ record.sub_category }}</span>
                  </div>
                  <div class="hp-stats">
                    <div class="hp-stat"><span class="hp-label">售价</span><strong>${{ record.price?.toFixed(2) }}</strong></div>
                    <div class="hp-stat"><span class="hp-label">月销</span><strong>{{ record.estimated_monthly_sales || '-' }}</strong></div>
                    <div class="hp-stat"><span class="hp-label">ROI</span><strong :class="{ 'roi-high': record.roi_estimated >= 100 }">{{ record.roi_estimated }}%</strong></div>
                  </div>
                  <div class="hp-score-row">
                    <span class="hp-label">蓝海评分</span>
                    <a-progress :percent="record.blue_ocean_score" :stroke-color="getScoreColor(record.blue_ocean_score)" :show-info="false" size="small" style="flex:1; max-width: 120px;" />
                    <strong :style="{ color: getScoreColor(record.blue_ocean_score), marginLeft: 6 }">{{ record.blue_ocean_score }}</strong>
                  </div>
                  <div v-if="record.selling_points" class="hp-points">
                    <div v-for="(sp, i) in record.selling_points.split(' | ').slice(0, 3)" :key="i" class="hp-point">{{ sp }}</div>
                  </div>
                  <div v-if="record.notes" class="hp-notes">{{ record.notes }}</div>
                </div>
              </div>
            </template>
            <div class="title-cell">
            <img
              v-if="record.main_image"
              class="title-thumb"
              :src="record.main_image"
              alt=""
              loading="lazy"
              @error="onImgError"
            />
            <span v-else class="title-thumb-ph">🖼️</span>
            <div class="title-text-wrap">
              <a-tooltip :title="record.title">
                <span class="title-text">{{ record.title }}</span>
              </a-tooltip>
              <div class="title-sub">
                <a-tag color="blue" size="small">{{ record.asin }}</a-tag>
                <span v-if="record.brand" class="title-brand">{{ record.brand }}</span>
              </div>
            </div>
          </div>
          </a-popover>
        </template>

        <!-- 蓝海评分列 -->
        <template v-else-if="column.key === 'blue_ocean_score'">
          <div class="score-cell">
            <a-progress
              :percent="record.blue_ocean_score"
              :stroke-color="getScoreColor(record.blue_ocean_score)"
              :show-info="false"
              size="small"
            />
            <span class="score-value" :style="{ color: getScoreColor(record.blue_ocean_score) }">
              {{ record.blue_ocean_score }}
            </span>
          </div>
        </template>

        <!-- ROI 列 -->
        <template v-else-if="column.key === 'roi_estimated'">
          <span :class="{ 'roi-high': record.roi_estimated >= 100 }">
            {{ record.roi_estimated }}%
          </span>
        </template>

        <!-- 评审状态列 -->
        <template v-else-if="column.key === 'review_status'">
          <a-tag :color="reviewStatusMeta(record.review_status).color">
            {{ reviewStatusMeta(record.review_status).label }}
          </a-tag>
        </template>

        <!-- 操作列：高频外露「对标竞品」+ 低频收进 ⋮更多下拉（评审状态仅展示、修改入口全部走下拉） -->
        <template v-else-if="column.key === 'action'">
          <div class="row-action-cell">
            <a-button type="link" size="small" class="act-primary" @click="openReviewCompetitors(record)">
              <TeamOutlined /> 对标竞品
            </a-button>
            <a-dropdown :trigger="['click']" overlay-class-name="row-more-menu">
              <a-button type="text" size="small" class="act-more">
                <MoreOutlined />
              </a-button>
              <template #overlay>
                <a-menu @click="(e: any) => handleMenuClick(e, record)">
                  <a-menu-item v-if="record.review_status !== 'approved'" key="approve-menu" :disabled="approvingId === record.id">
                    <CheckOutlined /> 评审通过
                  </a-menu-item>
                  <a-menu-item v-if="record.review_status === 'pending'" key="reviewing">
                    <MinusCircleOutlined /> 标记评审中
                  </a-menu-item>
                  <a-menu-item v-if="record.review_status !== 'rejected'" key="reject" danger>
                    <CloseOutlined /> 标记已淘汰
                  </a-menu-item>
                  <a-menu-item
                    v-if="['under_review', 'approved', 'rejected'].includes(record.review_status)"
                    key="reopen"
                  >
                    <UndoOutlined /> 重新打开为草稿
                  </a-menu-item>
                  <a-menu-divider />
                  <a-menu-item key="delete" danger>
                    <DeleteOutlined /> 删除
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </div>
        </template>
      </template>
    </a-table>

    <!-- 手动录入候选弹窗 -->
    <a-modal
      v-model:open="addModalVisible"
      title="手动录入候选选品"
      :width="560"
      :confirm-loading="adding"
      @ok="handleAddSubmit"
    >
      <a-form layout="vertical">
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="ASIN" required>
              <a-input v-model:value="addForm.asin" placeholder="如 B0XXXXXXX" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="标题" required>
              <a-input v-model:value="addForm.title" placeholder="商品标题" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="售价 (USD)">
              <a-input-number v-model:value="addForm.price" :min="0" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="预估月销">
              <a-input-number v-model:value="addForm.estimated_monthly_sales" :min="0" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="蓝海评分">
              <a-input-number v-model:value="addForm.blue_ocean_score" :min="0" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="ROI 估算 (%)">
              <a-input-number v-model:value="addForm.roi_estimated" :min="0" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="备注">
          <a-textarea v-model:value="addForm.notes" :rows="2" placeholder="选品来源、风险提示等" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 批量导入候选弹窗 -->
    <a-modal
      v-model:open="showImportModal"
      title="批量导入候选"
      width="520px"
      :footer="null"
    >
      <div class="import-area">
        <a-upload-dragger
          :file-list="importFileList"
          :before-upload="handleImportFile"
          :remove="() => { importFileList = []; return true }"
          accept=".json,.csv,.txt"
          :max-count="1"
        >
          <p class="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p class="ant-upload-hint">
            支持 JSON / CSV / TXT 格式<br/>
            JSON：数组，每项含 asin / title / price 等<br/>
            CSV：asin, title, category, price, sales, roi, score<br/>
            TXT：每行 "ASIN /// 标题"
          </p>
        </a-upload-dragger>

        <div v-if="importResult" class="import-result" :class="{ error: importResult.failed > 0 }">
          <a-alert
            :type="importResult.failed > 0 ? 'warning' : 'success'"
            :message="`导入完成：成功 ${importResult.success} 条${importResult.failed > 0 ? `，失败 ${importResult.failed} 条` : ''}`"
          >
            <template v-if="importResult.errors.length" #description>
              <ul class="error-list">
                <li v-for="(err, i) in importResult.errors.slice(0, 5)" :key="i">{{ err }}</li>
                <li v-if="importResult.errors.length > 5">... 还有 {{ importResult.errors.length - 5 }} 条错误</li>
              </ul>
            </template>
          </a-alert>
        </div>
      </div>
    </a-modal>

    <!-- 开启竞品监控弹窗（选品库 → 监控池） -->
    <AddToMonitorModal
      :open="addToMonitorOpen"
      :items="addToMonitorItems"
      @update:open="addToMonitorOpen = $event"
      @added="onMonitorAdded"
    />

    <!-- 评审对标竞品（选品库候选行「对标竞品(评审用)」触发，owner=候选） -->
    <CompetitorManager
      v-model:open="cmpOpen"
      :owner="cmpOwner"
      :owner-type="cmpOwnerType"
      @saved="onCmpSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  SearchOutlined,
  PlusOutlined,
  DeleteOutlined,
  CheckOutlined,
  FilterOutlined,
  ClearOutlined,
  UploadOutlined,
  InboxOutlined,
  FundOutlined,
  TeamOutlined,
  MoreOutlined,
  MinusCircleOutlined,
  CloseOutlined,
  UndoOutlined,
} from '@ant-design/icons-vue'
import { useCandidateLibraryStore, REVIEW_STATUS_MAP, type CandidateItem, type ReviewStatus } from '@/stores/candidateLibrary'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useMonitorPoolStore, type MonitorFromCandidateInput } from '@/stores/monitorPool'
import AddToMonitorModal from '@/components/common/AddToMonitorModal.vue'
import CompetitorManager from '@/components/competitor/CompetitorManager.vue'
import type { CompetitorOwnerType } from '@/stores/competitorPool'
import { COLOR_INFO } from '@/utils/colorSemantics'

const store = useCandidateLibraryStore()
const productStore = useProductLibraryStore()
const monitorPool = useMonitorPoolStore()

// ====== 表格列 ======
const columns = [
  { title: '商品标题', dataIndex: 'title', key: 'title', width: 300 },
  { title: '售价', dataIndex: 'price', key: 'price', width: 76, align: 'right' },
  { title: '预估月销', dataIndex: 'estimated_monthly_sales', key: 'estimated_monthly_sales', width: 86, align: 'right' },
  { title: '评分', dataIndex: 'rating', key: 'rating', width: 64, align: 'right' },
  { title: 'ROI%', dataIndex: 'roi_estimated', key: 'roi_estimated', width: 76, align: 'right' },
  { title: '蓝海评分', dataIndex: 'blue_ocean_score', key: 'blue_ocean_score', width: 116 },
  { title: '评审状态', dataIndex: 'review_status', key: 'review_status', width: 96 },
  { title: '操作', key: 'action', width: 130, fixed: 'right' },
]

// ====== 选择状态 ======
const selectedRowKeys = ref<string[]>([])
const onSelectChange = (keys: string[]) => {
  selectedRowKeys.value = keys
}

// ====== 评审通过 ======
const approvingId = ref<string | null>(null)
async function handleApprove(record: CandidateItem) {
  approvingId.value = record.id
  try {
    await store.approve(record.id)
    // 刷新产品库，让复制过去的产品立即可见
    await productStore.fetchItems()
    message.success(`「${record.title.slice(0, 20)}」已评审通过并复制到自有产品库，候选保留为评估基线`)
  } catch (e) {
    message.error('评审通过失败，请重试')
  } finally {
    approvingId.value = null
  }
}

// ====== 下拉菜单 ======
// ====== 评审对标竞品（评审用对标池，owner=候选） ======
const cmpOpen = ref(false)
const cmpOwner = ref<{ asin: string; title?: string; brand?: string; category?: string; keywords?: string[]; main_image?: string } | null>(null)
const cmpOwnerType = ref<CompetitorOwnerType>('candidate')
/** 打开评审对标：候选已在选品库，绑定 candidate（评审持久对标，作审批材料） */
function openReviewCompetitors(record: CandidateItem) {
  const asin = (record.asin || '').toUpperCase()
  cmpOwner.value = {
    asin,
    title: record.title || asin,
    brand: record.brand || '',
    category: record.category || '',
    keywords: Array.isArray(record.keywords) ? record.keywords : [],
    main_image: record.main_image || '',
  }
  cmpOwnerType.value = 'candidate'
  cmpOpen.value = true
}
function onCmpSaved() {
  // 对标已写入候选 competitor_asins，评估报告生成时可读取
}

function handleMenuClick({ key }: { key: string }, record: CandidateItem) {
  switch (key) {
    case 'cmp-pool':
      openReviewCompetitors(record)
      break
    case 'approve-menu':
      handleApprove(record)
      break
    case 'reviewing':
      store.setReviewStatus(record.id, 'under_review')
      message.success('已标记为评审中')
      break
    case 'reject':
      store.setReviewStatus(record.id, 'rejected', record.review_notes)
      message.success('已标记为已淘汰')
      break
    case 'reopen':
      store.setReviewStatus(record.id, 'pending')
      message.success('已重新打开为草稿')
      break
    case 'delete':
      handleDelete(record)
      break
  }
}

function handleDelete(record: CandidateItem) {
  store.deleteItem(record.id)
  message.success('候选已删除')
}

async function handleBatchDelete() {
  await store.batchDelete(selectedRowKeys.value)
  selectedRowKeys.value = []
  message.success('批量删除完成')
}

// ====== 开启监控（链路2：选品库 → 监控池） ======
const addToMonitorOpen = ref(false)
const addToMonitorItems = ref<MonitorFromCandidateInput[]>([])

/** 候选 → 监控静态快照（复用原有字段，不重新录入） */
function candidateToMonitor(r: CandidateItem): MonitorFromCandidateInput {
  return {
    asin: r.asin,
    title: r.title,
    brand: r.brand || undefined,
    main_image: r.main_image || undefined,
    latest_price: r.price || undefined,
    latest_bsr: r.bsr ?? undefined,
    rating: r.rating || undefined,
    review_count: r.review_count || undefined,
    est_monthly_sales: r.estimated_monthly_sales || undefined,
    bsr_category: r.bsr_category || undefined,
    source_candidate_id: r.id,
  }
}

/** 该 ASIN 是否已在监控池（按钮态） */
function isMonitored(asin: string): boolean {
  return monitorPool.isAsinInPool(asin)
}

/** 已勾选且尚未入监控池的候选（批量按钮 scope） */
const monitorableSelected = computed(() =>
  selectedRowKeys.value
    .map(id => store.items.find(i => i.id === id))
    .filter((i): i is CandidateItem => !!i && !monitorPool.isAsinInPool(i.asin))
)

/** 打开"开启监控"弹窗（批量或单条均走此） */
function openAddToMonitor(items: MonitorFromCandidateInput[]) {
  if (!items.length) {
    message.warning('所选候选均已在监控池中')
    return
  }
  addToMonitorItems.value = items
  addToMonitorOpen.value = true
}

/** 监控写入完成回调 */
function onMonitorAdded(payload: { added: number; existing: number; groupId?: string }) {
  if (payload.added > 0) message.success(`已开启 ${payload.added} 个竞品的定时监控`)
  if (payload.existing > 0) message.info(`${payload.existing} 个已在监控池，已跳过`)
}

/** 前往竞品监控视图并圈选该 ASIN */
function goMonitorAsin(asin: string) {
  monitorPool.setSelected([asin])
  monitorPool.selectGroup(null)
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'monitor' } }))
  message.success(`已定位到 ${asin} 的竞品监控`)
}

// ====== 手动录入 ======
const addModalVisible = ref(false)
const adding = ref(false)
const addForm = reactive({
  asin: '',
  title: '',
  price: 0,
  estimated_monthly_sales: 0,
  blue_ocean_score: 0,
  roi_estimated: 0,
  notes: '',
})

function openAddModal() {
  Object.assign(addForm, {
    asin: '', title: '', price: 0, estimated_monthly_sales: 0,
    blue_ocean_score: 0, roi_estimated: 0, notes: '',
  })
  addModalVisible.value = true
}

async function handleAddSubmit() {
  if (!addForm.asin.trim() || !addForm.title.trim()) {
    message.warning('请填写 ASIN 和标题')
    return
  }
  adding.value = true
  try {
    await store.addItem({
      asin: addForm.asin.trim(),
      sku: `SKU-CAND-${addForm.asin.trim()}`,
      title: addForm.title.trim(),
      brand: '',
      category: 'other',
      sub_category: '',
      price: addForm.price,
      currency: 'USD',
      estimated_monthly_sales: addForm.estimated_monthly_sales,
      review_count: 0,
      rating: 0,
      bsr: null,
      roi_estimated: addForm.roi_estimated,
      margin: 0,
      blue_ocean_score: addForm.blue_ocean_score,
      main_image: '',
      source: 'manual',
      review_status: 'pending',
      review_notes: '',
      shop_id: '',
      tags: ['手动录入'],
      notes: addForm.notes,
      groups: [],
    })
    addModalVisible.value = false
    message.success('候选已录入选品库')
  } finally {
    adding.value = false
  }
}

// ====== 文件导入（批量候选） ======
const showImportModal = ref(false)
const importFileList = ref<any[]>([])
const importResult = ref<{ success: number; failed: number; errors: string[] } | null>(null)

async function handleImportFile(file: File) {
  importFileList.value = [file]
  importResult.value = await store.parseAndImport(file)
  if (importResult.value.success > 0) {
    message.success(`成功导入 ${importResult.value.success} 条候选`)
  }
  return false
}

// ====== 工具函数 ======
const reviewStatusMeta = (status: string) => {
  return REVIEW_STATUS_MAP[status as ReviewStatus] || { label: status, color: 'default' }
}

// ====== 分类图标 / 文案（候选库） ======
const CATEGORY_ICON: Record<string, string> = {
  home: '🏠', electronics: '💻', beauty: '💄', sports: '⚽',
  fashion: '👕', toys: '🧸', kitchen: '🍳', outdoor: '⛺',
  pet: '🐾', office: '📎', other: '📦',
}
const CATEGORY_LABEL: Record<string, string> = {
  home: '家居', electronics: '电子', beauty: '美妆', sports: '运动',
  fashion: '服饰', toys: '玩具', kitchen: '厨电', outdoor: '户外',
  pet: '宠物', office: '办公', other: '其他',
}

/** 当前分组 chip 颜色与文案 */
const currentGroupColor = computed(() => {
  if (!store.currentGroupId) return 'blue'
  if (store.currentGroupId === '__ungrouped__') return 'default'
  const g = store.groups.find(x => x.id === store.currentGroupId)
  return g?.color || 'blue'
})
const currentGroupLabel = computed(() => {
  if (!store.currentGroupId) return ''
  if (store.currentGroupId === '__ungrouped__') return '未分组'
  const g = store.groups.find(x => x.id === store.currentGroupId)
  return g ? `分组：${g.name}` : '已选分组'
})

const getScoreColor = (score: number): string => {
  if (score >= 70) return 'var(--success)'
  if (score >= 40) return 'var(--warning)'
  return 'var(--danger)'
}

const onImgError = (e: Event) => {
  ;(e.target as HTMLImageElement).style.display = 'none'
}
</script>

<style scoped>
.cand-page {
  padding: 16px;
  background: var(--bg-elevated);
  border-radius: 8px;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 行操作列：高频外露 + ⋮更多下拉收拢（状态修改入口全在更多里） */
.row-action-cell {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}
.row-action-cell .act-primary {
  font-size: 12px;
  padding: 0 6px;
}
.row-action-cell .act-more {
  color: var(--text-secondary);
  border-radius: 4px;
}
.row-action-cell .act-more:hover {
  color: var(--primary);
  background: var(--bg-active-light);
}

/* 统计卡片 */
.stat-cards {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.stat-card {
  flex: 1;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.blue { color: var(--primary); }
.stat-value.orange { color: var(--warning); }
.stat-value.green { color: var(--success); }
.stat-value.gray { color: var(--text-tertiary); }

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ====== 已启用过滤（chip 行） ====== */
.active-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: -8px 0 16px 0;
  padding: 10px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
  border: 1px dashed var(--border-strong);
}

.af-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-right: 4px;
}

.af-chip {
  font-size: 12px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 标题单元格 */
.title-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--border-base);
  flex-shrink: 0;
  background: var(--bg-sidebar);
}

.title-thumb-ph {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  border-radius: 4px;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
}

.title-text-wrap {
  min-width: 0;
}

.title-text {
  display: block;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}

.title-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.title-brand {
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 蓝海评分 */
.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.score-cell .ant-progress {
  flex: 1;
  max-width: 60px;
}

.score-value {
  font-weight: 600;
  min-width: 24px;
  text-align: right;
}

.roi-high {
  color: var(--success);
  font-weight: 600;
}

/* ====== 导入弹窗 ====== */
.import-area {
  padding: 4px 0;
}

.import-result {
  margin-top: 16px;
}

.error-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 12px;
}

/* ====== 悬浮预览卡片 ====== */
.hover-preview {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hp-img {
  width: 100%;
  height: 160px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border-base);
  background: var(--bg-sidebar);
}

.hp-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hp-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hp-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hp-brand { font-size: 12px; color: var(--text-secondary); }
.hp-cat { font-size: 11px; color: var(--text-tertiary); background: var(--bg-hover-light); border-radius: 3px; padding: 1px 6px; }

.hp-stats {
  display: flex;
  gap: 16px;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border-radius: 6px;
}

.hp-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.hp-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.hp-score-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.hp-points {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hp-point {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  padding: 4px 8px;
  background: linear-gradient(135deg, var(--warning-bg), var(--warning-bg));
  border-left: 3px solid var(--warning);
  border-radius: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hp-notes {
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.4;
  padding: 6px 8px;
  background: var(--bg-hover-light);
  border-radius: 4px;
  max-height: 48px;
  overflow: hidden;
}
</style>
