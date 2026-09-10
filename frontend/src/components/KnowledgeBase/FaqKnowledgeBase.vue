<template>
  <div class="kb-page">
    <!-- ====== 知识库容器标签栏 ====== -->
    <div class="kb-tabs-bar">
      <div class="tabs-left">
        <div
          v-for="kb in store.knowledgeBases"
          :key="kb.id"
          class="kb-tab"
          :class="{ active: store.currentKbId === kb.id }"
          @click="store.switchKnowledgeBase(kb.id)"
        >
          <span class="tab-icon">{{ kb.icon }}</span>
          <span class="tab-name">{{ kb.name }}</span>
          <span class="tab-count">{{ kb.faq_count }}</span>
          <!-- 删除按钮（非默认库可删） -->
          <a-popconfirm
            v-if="kb.id !== 'kb-default'"
            title="删除此话术库？其下所有话术和文档将被清除。"
            @confirm="handleDeleteKb(kb.id)"
          >
            <button class="tab-close" @click.stop>×</button>
          </a-popconfirm>
        </div>
        <!-- 新建库按钮 -->
        <button class="kb-tab kb-tab-add" @click="showCreateKbModal = true">
          <PlusOutlined />
        </button>
      </div>
      <div class="tabs-right">
        <a-tooltip title="管理文档素材（PDF / MD / Excel）">
          <a-button size="small" @click="showDocPanel = !showDocPanel">
            <FileTextOutlined /> 文档 {{ showDocPanel ? '收起' : '管理' }}
            <a-badge v-if="store.currentDocs.length" :count="store.currentDocs.length" :offset="[-4, 0]" />
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- ====== 文档素材面板（可折叠） ====== -->
    <div v-show="showDocPanel" class="doc-panel">
      <div class="doc-panel-header">
        <span class="doc-panel-title"><FileTextOutlined /> RAG 补充文档（{{ store.currentKbId === 'kb-default' ? '通用' : store.currentKnowledgeBase?.name }}）</span>
        <a-space>
          <a-upload
            :show-file-list="false"
            accept=".pdf,.md,.txt,.xlsx,.xls,.csv"
            :before-upload="handleDocUpload"
          >
            <a-button size="small" type="link"><UploadOutlined /> 上传文档</a-button>
          </a-upload>
        </a-space>
      </div>
      <div v-if="store.currentDocs.length" class="doc-list">
        <div v-for="doc in store.currentDocs" :key="doc.id" class="doc-item">
          <div class="doc-info">
            <span class="doc-icon">{{ getDocIcon(doc.file_type) }}</span>
            <span class="doc-name">{{ doc.filename }}</span>
            <span class="doc-size">{{ formatSize(doc.size) }}</span>
            <span v-if="doc.description" class="doc-desc">— {{ doc.description }}</span>
          </div>
          <a-popconfirm title="删除此文档？" @confirm="store.deleteDoc(doc.id)">
            <a-button type="text" size="small" danger><DeleteOutlined /></a-button>
          </a-popconfirm>
        </div>
      </div>
      <a-empty v-else description="暂无补充文档，上传 PDF/MD/Excel 作为 RAG 检索素材" :image-style="{ height: '40px' }" />
    </div>

    <!-- ====== 顶部操作栏 ====== -->
    <div class="page-header">
      <div class="header-left">
        <h3 class="page-title">
          <MessageOutlined /> {{ store.currentKnowledgeBase?.name || '业务话术库' }}
        </h3>
        <span class="count-badge">共 {{ store.totalCount }} 条</span>
        <span class="active-badge">活跃 {{ store.activeCount }}</span>
      </div>
      <div class="header-actions">
        <!-- 导出当前话术库配置（多格式，可选目标文件夹） -->
        <a-tooltip title="导出当前话术库，支持 JSON / Excel / CSV / TXT，可选择保存位置">
          <a-button @click="exportFaqs">
            <ExportOutlined /> 导出
          </a-button>
        </a-tooltip>
        <!-- 文件导入（批量结构化问答） -->
        <a-tooltip title="从文件批量导入话术（支持 JSON / CSV / TXT / Excel）">
          <a-button @click="showImportModal = true">
            <UploadOutlined /> 导入话术
          </a-button>
        </a-tooltip>
        <a-button type="primary" @click="openAddModal">
          <PlusOutlined /> 新增话术
        </a-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <a-input-search
        v-model:value="store.searchQuery"
        placeholder="搜索问题、答案、关键词..."
        style="width: 280px"
        allow-clear
      >
        <template #prefix><SearchOutlined /></template>
      </a-input-search>
      <a-select
        v-model:value="store.filterCategory"
        style="width: 140px"
        placeholder="全部分类"
        allow-clear
      >
        <a-select-option v-for="cat in CATEGORIES" :key="cat.key" :value="cat.key">
          {{ cat.icon }} {{ cat.label }}
          <span v-if="store.categoryStats[cat.key]" class="cat-count">({{ store.categoryStats[cat.key] }})</span>
        </a-select-option>
      </a-select>
      <a-select
        v-model:value="store.filterStatus"
        style="width: 120px"
        placeholder="全部状态"
        allow-clear
      >
        <a-select-option value="active">✅ 活跃</a-select-option>
        <a-select-option value="draft">📝 草稿</a-select-option>
        <a-select-option value="archived">📦 已归档</a-select-option>
      </a-select>
    </div>

    <!-- 话术列表表格 -->
    <a-table
      :columns="columns"
      :data-source="store.filteredItems"
      :loading="store.isLoading"
      row-key="id"
      :pagination="{ pageSize: 15, size: 'small', showTotal: (t: number) => `共 ${t} 条` }"
      size="middle"
      :scroll="{ y: 'calc(100vh - 380px)' }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.dataIndex === 'question'">
          <div class="question-cell">
            <span class="q-text">{{ record.question }}</span>
            <div class="q-keywords" v-if="record.keywords.length">
              <a-tag v-for="kw in record.keywords.slice(0, 3)" :key="kw" size="small">{{ kw }}</a-tag>
            </div>
          </div>
        </template>

        <template v-else-if="column.dataIndex === 'category'">
          <a-tag :color="getCategoryColor(record.category)">
            {{ getCategoryLabel(record.category) }}
          </a-tag>
        </template>

        <template v-else-if="column.dataIndex === 'priority'">
          <a-tag :color="priorityColor(record.priority)">
            {{ priorityLabel(record.priority) }}
          </a-tag>
        </template>

        <template v-else-if="column.dataIndex === 'status'">
          <a-tag :color="record.status === 'active' ? 'success' : record.status === 'draft' ? 'warning' : 'default'">
            {{ statusLabel(record.status) }}
          </a-tag>
        </template>

        <template v-else-if="column.dataIndex === 'usage_count'">
          <span>{{ record.usage_count }} 次</span>
        </template>

        <template v-else-if="column.dataIndex === 'actions'">
          <a-space>
            <a-tooltip title="编辑">
              <a-button type="text" size="small" @click="openEditModal(record)">
                <EditOutlined />
              </a-button>
            </a-tooltip>
            <a-popconfirm title="确定删除此条话术？" @confirm="handleDelete(record.id)">
              <a-tooltip title="删除">
                <a-button type="text" size="small" danger>
                  <DeleteOutlined />
                </a-button>
              </a-tooltip>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <!-- 新增/编辑话术弹窗 -->
    <a-modal
      v-model:open="modalVisible"
      :title="editingId ? '编辑话术' : '新增话术'"
      width="640px"
      @ok="handleSubmit"
      :okLoading="submitting"
      cancelText="取消"
    >
      <a-form :label-col="{ span: 4 }" :wrapper-col="{ span: 19 }">
        <a-form-item label="问题" required>
          <a-textarea v-model:value="form.question" placeholder="客户可能提出的问题..." :rows="2" />
        </a-form-item>
        <a-form-item label="答案" required>
          <a-textarea v-model:value="form.answer" placeholder="标准回答内容..." :rows="4" />
        </a-form-item>
        <a-form-item label="分类">
          <a-select v-model:value="form.category" placeholder="选择分类">
            <a-select-option v-for="cat in CATEGORIES" :key="cat.key" :value="cat.key">
              {{ cat.icon }} {{ cat.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="关键词">
          <a-select
            v-model:value="form.keywords"
            mode="tags"
            placeholder="输入关键词后回车，用于检索匹配"
            style="width: 100%"
          />
        </a-form-item>
        <a-form-item label="优先级">
          <a-radio-group v-model:value="form.priority">
            <a-radio-button value="high">高（优先匹配）</a-radio-button>
            <a-radio-button value="medium">中</a-radio-button>
            <a-radio-button value="low">低</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="状态">
          <a-radio-group v-model:value="form.status">
            <a-radio-button value="active">活跃</a-radio-button>
            <a-radio-button value="draft">草稿</a-radio-button>
            <a-radio-button value="archived">归档</a-radio-button>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 批量导入话术弹窗 -->
    <a-modal
      v-model:open="showImportModal"
      title="批量导入话术"
      width="520px"
      :footer="null"
    >
      <div class="import-area">
        <a-upload-dragger
          :file-list="importFileList"
          :before-upload="handleImportFile"
          :remove="() => { importFileList = []; return true }"
          accept=".json,.csv,.txt,.xlsx,.xls"
          :max-count="1"
        >
          <p class="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p class="ant-upload-hint">
            支持 JSON / CSV / TXT / Excel 格式<br/>
            CSV：question, answer, category, keywords<br/>
            TXT：每行 "问题 /// 答案"<br/>
            Excel：首行为表头，含 question / answer 列
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

    <!-- 新建知识库弹窗 -->
    <a-modal
      v-model:open="showCreateKbModal"
      title="新建话术库"
      width="480px"
      @ok="handleCreateKb"
      :okLoading="creatingKb"
      okText="创建"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="newKbForm.name" placeholder="如：亚马逊US售后库、TikTok差评模板库" />
        </a-form-item>
        <a-form-item label="图标">
          <div class="icon-picker">
            <button
              v-for="icon in KB_ICONS"
              :key="icon"
              class="icon-btn"
              :class="{ active: newKbForm.icon === icon }"
              @click="newKbForm.icon = icon"
            >{{ icon }}</button>
          </div>
        </a-form-item>
        <a-form-item label="类型">
          <a-radio-group v-model:value="newKbForm.type">
            <a-radio-button value="shop">🏪 店铺</a-radio-button>
            <a-radio-button value="platform">🌐 平台</a-radio-button>
            <a-radio-button value="custom">📁 自定义</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newKbForm.description" :rows="2" placeholder="简要描述此话术库的用途..." />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 导出弹窗（多格式 + 可选目标文件夹） -->
    <ExportModal
      v-model:open="exportVisible"
      :title="`导出话术库「${store.currentKnowledgeBase?.name || '业务话术库'}」`"
      unit="话术"
      :count="exportFaqCount"
      :base-name="`${store.currentKnowledgeBase?.name || '话术库'}_${todayStamp()}`"
      :json-data="exportFaqJson"
      :columns="exportFaqColumns"
      :rows="exportFaqRows"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  MessageOutlined,
  PlusOutlined,
  UploadOutlined,
  ExportOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  InboxOutlined,
  FileTextOutlined,
} from '@ant-design/icons-vue'
import { useKnowledgeStore, FAQ_CATEGORIES, type FaqItem } from '@/stores/knowledge'
import { todayStamp } from '@/utils/download'
import ExportModal from '@/components/common/ExportModal.vue'

const store = useKnowledgeStore()
const CATEGORIES = FAQ_CATEGORIES

// 可选图标池
const KB_ICONS = ['📚', '📦', '💬', '⚠️', '🛡️', '🌐', '🏪', '📋', '🎯', '💡', '🔧', '📌']

// ====== 知识库标签栏状态 ======
const showDocPanel = ref(false)
const showCreateKbModal = ref(false)
const creatingKb = ref(false)
const newKbForm = reactive({
  name: '',
  icon: '📚',
  type: 'custom' as 'shop' | 'platform' | 'custom',
  description: '',
})

async function handleCreateKb() {
  if (!newKbForm.name.trim()) {
    message.warning('请输入话术库名称')
    return
  }
  creatingKb.value = true
  try {
    const kb = await store.createKnowledgeBase({
      name: newKbForm.name.trim(),
      icon: newKbForm.icon,
      type: newKbForm.type,
      description: newKbForm.description.trim(),
    })
    store.switchKnowledgeBase(kb.id)
    showCreateKbModal.value = false
    message.success(`已创建「${kb.name}」`)
    // 重置表单
    newKbForm.name = ''
    newKbForm.icon = '📚'
    newKbForm.type = 'custom'
    newKbForm.description = ''
  } finally {
    creatingKb.value = false
  }
}

async function handleDeleteKb(kbId: string) {
  await store.deleteKnowledgeBase(kbId)
  message.success('已删除话术库')
}

// ====== 文档上传 ======
async function handleDocUpload(file: File) {
  await store.uploadDoc(file)
  message.success(`已上传：${file.name}`)
  return false
}

function getDocIcon(type: string): string {
  const map: Record<string, string> = { pdf: '📕', md: '📝', excel: '📊', txt: '📄', other: '📎' }
  return map[type] || '📎'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

// ====== 表格列定义 ======
const columns = [
  { title: '问题', dataIndex: 'question', width: '35%', ellipsis: true },
  {
    title: '分类',
    dataIndex: 'category',
    width: 110,
    filters: CATEGORIES.map(c => ({ text: `${c.icon} ${c.label}`, value: c.key })),
    onFilter: (value: string, record: FaqItem) => record.category === value,
  },
  { title: '优先级', dataIndex: 'priority', width: 100 },
  { title: '状态', dataIndex: 'status', width: 90 },
  { title: '引用', dataIndex: 'usage_count', width: 80, sorter: (a: FaqItem, b: FaqItem) => a.usage_count - b.usage_count },
  { title: '更新时间', dataIndex: 'updated_at', width: 160, sorter: (a: FaqItem, b: FaqItem) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime() },
  { title: '操作', dataIndex: 'actions', width: 100, fixed: 'right' as const },
]

// ====== 新增/编辑弹窗 ======
const modalVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)

const form = reactive({
  question: '',
  answer: '',
  category: 'other',
  keywords: [] as string[],
  priority: 'medium' as 'high' | 'medium' | 'low',
  status: 'active' as 'active' | 'draft' | 'archived',
})

function resetForm() {
  form.question = ''
  form.answer = ''
  form.category = 'other'
  form.keywords = []
  form.priority = 'medium'
  form.status = 'active'
}

function openAddModal() {
  resetForm()
  editingId.value = null
  modalVisible.value = true
}

function openEditModal(record: FaqItem) {
  editingId.value = record.id
  form.question = record.question
  form.answer = record.answer
  form.category = record.category
  form.keywords = [...record.keywords]
  form.priority = record.priority
  form.status = record.status
  modalVisible.value = true
}

async function handleSubmit() {
  if (!form.question.trim() || !form.answer.trim()) {
    message.warning('请填写问题和答案')
    return
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await store.updateItem(editingId.value, { ...form })
      message.success('话术已更新')
    } else {
      await store.addItem({ ...form })
      message.success('话术已添加')
    }
    modalVisible.value = false
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: string) {
  await store.deleteItem(id)
  message.success('已删除')
}

// ====== 文件导入（结构化问答） ======
const showImportModal = ref(false)
const importFileList = ref<any[]>([])
const importResult = ref<{ success: number; failed: number; errors: string[] } | null>(null)

async function handleImportFile(file: File) {
  importFileList.value = [file]
  importResult.value = await store.parseAndImport(file)
  if (importResult.value.success > 0) {
    message.success(`成功导入 ${importResult.value.success} 条话术`)
  }
  return false
}

// ====== 导出（多格式，可选目标文件夹） ======
const exportVisible = ref(false)
const exportFaqRows = ref<(string | number)[][]>([])
const exportFaqJson = ref<unknown>([])
const exportFaqCount = ref(0)

/** 话术导出表格列头 */
const exportFaqColumns = ['分类', '问题', '答案', '关键词', '优先级', '状态']

/** 打开导出弹窗：准备当前话术库的 JSON + 表格数据 */
function exportFaqs() {
  const data = store.currentItems.map(({ id, kb_id, created_at, updated_at, usage_count, ...faq }) => faq)
  exportFaqJson.value = data
  exportFaqCount.value = data.length

  exportFaqRows.value = store.currentItems.map(f => [
    getCategoryLabel(f.category),
    f.question,
    f.answer,
    f.keywords.join(', '),
    priorityLabel(f.priority),
    statusLabel(f.status),
  ])
  exportVisible.value = true
}

// ====== 辅助函数 ======
function getCategoryColor(key: string): string {
  return CATEGORIES.find(c => c.key === key)?.color || 'var(--text-tertiary)'
}
function getCategoryLabel(key: string): string {
  return CATEGORIES.find(c => c.key === key)?.label || key
}
function priorityColor(p: string): string {
  return p === 'high' ? 'red' : p === 'medium' ? 'orange' : 'default'
}
function priorityLabel(p: string): string {
  return p === 'high' ? '高' : p === 'medium' ? '中' : '低'
}
function statusLabel(s: string): string {
  return s === 'active' ? '活跃' : s === 'draft' ? '草稿' : '归档'
}

onMounted(() => {
  store.fetchItems()
})
</script>

<style scoped>
.kb-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 24px;
  overflow: hidden;
}

/* ====== 知识库标签栏 ====== */
.kb-tabs-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-shrink: 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-base);
}

.tabs-left {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.kb-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  transition: all 0.2s;
  user-select: none;
}

.kb-tab:hover {
  background: var(--info-bg);
  border-color: var(--info-border);
  color: var(--primary);
}

.kb-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  box-shadow: 0 2px 6px rgba(24, 144, 255, 0.3);
}

.tab-icon { font-size: 14px; }
.tab-name { font-weight: 500; }

.tab-count {
  font-size: 11px;
  background: rgba(255,255,255,0.3);
  padding: 1px 6px;
  border-radius: 8px;
}
.kb-tab:not(.active) .tab-count {
  background: var(--border-base);
  color: var(--text-tertiary);
}

.tab-close {
  margin-left: 2px;
  background: none;
  border: none;
  color: inherit;
  opacity: 0.5;
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
  padding: 0 2px;
}
.tab-close:hover { opacity: 1; color: var(--danger) !important; }
.kb-tab.active .tab-close:hover { color: #fff !important; }

.kb-tab-add {
  width: 30px;
  min-width: 30px;
  justify-content: center;
  padding: 5px 8px;
  border-style: dashed;
  color: var(--text-tertiary);
}
.kb-tab-add:hover {
  color: var(--primary);
  border-color: var(--primary);
  background: transparent;
}

.tabs-right {
  flex-shrink: 0;
}

/* ====== 文档面板 ====== */
.doc-panel {
  background: var(--bg-sidebar);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.doc-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.doc-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.doc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  background: var(--bg-elevated);
  border-radius: 4px;
  font-size: 12px;
}

.doc-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.doc-icon { font-size: 15px; }
.doc-name {
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-size { color: var(--text-tertiary); font-size: 11px; white-space: nowrap; }
.doc-desc { color: var(--text-tertiary); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ====== 页面头部 ====== */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  font-size: 17px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.count-badge {
  font-size: 13px;
  color: var(--text-tertiary);
  background: var(--bg-hover-light);
  padding: 2px 10px;
  border-radius: 10px;
}

.active-badge {
  font-size: 13px;
  color: var(--success);
  background: var(--success-bg);
  padding: 2px 10px;
  border-radius: 10px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.cat-count {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-left: 4px;
}

.question-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.q-text {
  font-weight: 500;
  color: var(--text-primary);
}

.q-keywords {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.import-area {
  padding: 8px 0;
}

.import-result {
  margin-top: 16px;
}

.error-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--danger);
  font-size: 12px;
}

/* 图标选择器 */
.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.icon-btn {
  width: 36px;
  height: 36px;
  font-size: 18px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-elevated);
  cursor: pointer;
  transition: all 0.15s;
}
.icon-btn:hover { border-color: var(--primary); }
.icon-btn.active {
  border-color: var(--primary);
  background: var(--info-bg);
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
}

:deep(.ant-table) {
  flex: 1;
  overflow: hidden;
}

:deep(.ant-table-container) {
  height: 100%;
}

:deep(.ant-table-body) {
  overflow-y: auto !important;
}
</style>
