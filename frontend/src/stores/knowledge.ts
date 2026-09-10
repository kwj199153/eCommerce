/**
 * 业务话术库状态管理
 *
 * 多知识库容器架构：每个知识库 = 一个独立话术集合（按店铺/平台隔离）
 * 单库内支持双轨录入：结构化问答（FAQ）+ 文档素材（PDF/MD/Excel）
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ====== 类型定义 ======

/** 知识库容器（顶层文件夹） */
export interface KnowledgeBase {
  id: string
  name: string                          // 显示名：如「亚马逊US售后库」
  description: string                   // 描述
  icon: string                          // emoji 图标
  type: 'shop' | 'platform' | 'custom'  // 类型
  faq_count: number                     // 话术条数（冗余，便于展示）
  doc_count: number                     // 文档数（冗余）
  created_at: string
  updated_at: string
}

/** 结构化话术条目 */
export interface FaqItem {
  id: string
  kb_id: string                        // 所属知识库 ID
  question: string
  answer: string
  category: string
  keywords: string[]
  priority: 'high' | 'medium' | 'low'
  status: 'active' | 'draft' | 'archived'
  usage_count: number
  created_at: string
  updated_at: string
}

/** 文档素材（RAG 补充资料） */
export interface KnowledgeDoc {
  id: string
  kb_id: string                        // 所属知识库 ID
  filename: string
  file_type: 'pdf' | 'md' | 'excel' | 'txt' | 'other'
  size: number                         // bytes
  uploaded_at: string
  description: string                  // 用户备注
}

export interface FaqCategory {
  key: string
  label: string
  icon: string
  color: string
}

// ====== 内置分类 ======

export const FAQ_CATEGORIES: FaqCategory[] = [
  { key: 'shipping', label: '物流配送', icon: '📦', color: '#1890ff' },
  { key: 'return', label: '退换货', icon: '🔄', color: '#faad14' },
  { key: 'product', label: '商品咨询', icon: '📦', color: '#52c41a' },
  { key: 'payment', label: '支付问题', icon: '💳', color: '#722ed1' },
  { key: 'account', label: '账户相关', icon: '👤', color: '#13c2c2' },
  { key: 'policy', label: '平台政策', icon: '⚖️', color: '#eb2f96' },
  { key: 'review', label: '差评处理', icon: '💢', color: '#f5222d' },
  { key: 'other', label: '其他', icon: '❓', color: '#8c8c8c' },
]

// ====== 默认知识库容器 ======

export const DEFAULT_KNOWLEDGE_BASES: KnowledgeBase[] = [
  {
    id: 'kb-default',
    name: '通用话术库',
    description: '默认通用问答，适用于全场景',
    icon: '📚',
    type: 'custom',
    faq_count: 6,
    doc_count: 0,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
  },
]

// ====== Mock 数据 ======

const MOCK_FAQS: FaqItem[] = [
  {
    id: 'faq-001',
    kb_id: 'kb-default',
    question: '订单发货后多久可以收到？',
    answer: '标准配送通常需要 3-7 个工作日。加急配送 1-3 个工作日。具体时间取决于收货地址和物流商。',
    category: 'shipping',
    keywords: ['发货', '配送', '快递', '多久', '几天'],
    priority: 'high',
    status: 'active',
    usage_count: 156,
    created_at: '2026-08-15T10:00:00Z',
    updated_at: '2026-08-20T14:30:00Z',
  },
  {
    id: 'faq-002',
    kb_id: 'kb-default',
    question: '如何申请退货？',
    answer: '收到商品后 30 天内可在「我的订单」中点击「申请退货」，选择退货原因并提交。审核通过后寄回商品，退款将在 3-5 个工作日原路返回。',
    category: 'return',
    keywords: ['退货', '退款', '怎么退', '退换'],
    priority: 'high',
    status: 'active',
    usage_count: 203,
    created_at: '2026-08-10T09:00:00Z',
    updated_at: '2026-08-25T11:00:00Z',
  },
  {
    id: 'faq-003',
    kb_id: 'kb-default',
    question: '商品有质量问题怎么办？',
    answer: '如收到商品存在质量问题，请在签收后 48 小时内联系客服，提供照片证据。我们将安排免费换货或全额退款，运费由我们承担。',
    category: 'product',
    keywords: ['质量', '问题', '损坏', '瑕疵', ' defective'],
    priority: 'high',
    status: 'active',
    usage_count: 89,
    created_at: '2026-08-12T16:00:00Z',
    updated_at: '2026-08-22T10:00:00Z',
  },
  {
    id: 'faq-004',
    kb_id: 'kb-default',
    question: '支持哪些支付方式？',
    answer: '我们支持信用卡（Visa/Mastercard/AE）、PayPal、Apple Pay、Google Pay 以及本地支付方式（根据收货地区自动显示可用选项）。',
    category: 'payment',
    keywords: ['支付', '付款', '信用卡', 'PayPal', '方式'],
    priority: 'medium',
    status: 'active',
    usage_count: 134,
    created_at: '2026-08-08T12:00:00Z',
    updated_at: '2026-08-18T09:00:00Z',
  },
  {
    id: 'faq-005',
    kb_id: 'kb-default',
    question: '如何修改账户信息？',
    answer: '登录后进入「账户设置」，可修改邮箱、手机号、收货地址等信息。修改邮箱和手机需验证原信息。',
    category: 'account',
    keywords: ['账户', '修改', '信息', '密码', '设置'],
    priority: 'medium',
    status: 'active',
    usage_count: 67,
    created_at: '2026-08-05T14:00:00Z',
    updated_at: '2026-08-15T16:00:00Z',
  },
  {
    id: 'faq-006',
    kb_id: 'kb-default',
    question: '可以更改收货地址吗？',
    answer: '订单未发货前可在订单详情页修改地址。已发货订单无法更改，请联系客服尝试拦截。',
    category: 'shipping',
    keywords: ['地址', '收货', '更改', '修改', '配送地址'],
    priority: 'medium',
    status: 'active',
    usage_count: 78,
    created_at: '2026-08-14T11:00:00Z',
    updated_at: '2026-08-20T15:00:00Z',
  },
]

// ====== Store ======

export const useKnowledgeStore = defineStore('knowledge', () => {
  // ====== 知识库容器 State ======
  const knowledgeBases = ref<KnowledgeBase[]>([...DEFAULT_KNOWLEDGE_BASES])
  const currentKbId = ref<string>('kb-default')

  // ====== 话术条目 State ======
  const items = ref<FaqItem[]>([...MOCK_FAQS])
  const isLoading = ref(false)
  const searchQuery = ref('')
  // 初始值改为 undefined：避免 a-select allow-clear 清空后被误判为「过滤生效」
  const filterCategory = ref<string | undefined>(undefined)
  const filterStatus = ref<string | undefined>(undefined)

  // ====== 文档素材 State ======
  const docs = ref<KnowledgeDoc[]>([])

  // ====== 知识库容器 Getters ======

  /** 当前选中的知识库 */
  const currentKnowledgeBase = computed(() =>
    knowledgeBases.value.find(kb => kb.id === currentKbId.value) || knowledgeBases.value[0]
  )

  /** 当前库的话术列表（按 kb_id 过滤） */
  const currentItems = computed(() =>
    items.value.filter(item => item.kb_id === currentKbId.value)
  )

  /** 当前库的文档列表 */
  const currentDocs = computed(() =>
    docs.value.filter(doc => doc.kb_id === currentKbId.value)
  )

  // ====== 话术 Getters（在当前库内过滤） ======

  /** 过滤后的列表（搜索 + 分类 + 状态，均在当前库内） */
  const filteredItems = computed(() => {
    let result = currentItems.value

    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    if (filterStatus.value && filterStatus.value !== 'all') {
      result = result.filter(item => item.status === filterStatus.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.question.toLowerCase().includes(q) ||
        item.answer.toLowerCase().includes(q) ||
        item.keywords.some(k => k.toLowerCase().includes(q))
      )
    }

    return result
  })

  /** 统计（基于当前库） */
  const totalCount = computed(() => currentItems.value.length)
  const activeCount = computed(() => currentItems.value.filter(i => i.status === 'active').length)
  const categoryStats = computed(() => {
    const stats: Record<string, number> = {}
    currentItems.value.forEach(item => {
      stats[item.category] = (stats[item.category] || 0) + 1
    })
    return stats
  })

  // ====== 知识库容器 Actions ======

  /** 创建新知识库 */
  async function createKnowledgeBase(data: { name: string; description: string; icon: string; type: KnowledgeBase['type'] }): Promise<KnowledgeBase> {
    const newKb: KnowledgeBase = {
      id: `kb-${Date.now()}`,
      name: data.name,
      description: data.description,
      icon: data.icon,
      type: data.type,
      faq_count: 0,
      doc_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    knowledgeBases.value.push(newKb)
    return newKb
  }

  /** 删除知识库（同时清理其下所有话术和文档） */
  async function deleteKnowledgeBase(kbId: string): Promise<void> {
    items.value = items.value.filter(i => i.kb_id !== kbId)
    docs.value = docs.value.filter(d => d.kb_id !== kbId)
    knowledgeBases.value = knowledgeBases.value.filter(kb => kb.id !== kbId)
    // 如果删除的是当前库，切到第一个
    if (currentKbId.value === kbId && knowledgeBases.value.length > 0) {
      currentKbId.value = knowledgeBases.value[0].id
    }
  }

  /** 切换当前知识库 */
  function switchKnowledgeBase(kbId: string) {
    currentKbId.value = kbId
    // 切换时清空筛选
    searchQuery.value = ''
    filterCategory.value = undefined
    filterStatus.value = undefined
  }

  /** 更新知识库元信息（名称/描述等） */
  async function updateKnowledgeBase(kbId: string, data: Partial<Pick<KnowledgeBase, 'name' | 'description' | 'icon'>>): Promise<void> {
    const kb = knowledgeBases.value.find(k => k.id === kbId)
    if (kb) {
      Object.assign(kb, data, { updated_at: new Date().toISOString() })
    }
  }

  /** 刷新各库的计数缓存 */
  function refreshKbCounts() {
    knowledgeBases.value.forEach(kb => {
      kb.faq_count = items.value.filter(i => i.kb_id === kb.id).length
      kb.doc_count = docs.value.filter(d => d.kb_id === kb.id).length
    })
  }

  // ====== 话术 Actions ======

  /**
   * 加载知识库（Mock：已内置数据）
   */
  async function fetchItems() {
    isLoading.value = true
    try {
      // TODO: 替换为真实 API: get('/knowledge-base/faqs')
      await new Promise(resolve => setTimeout(resolve, 300))
      refreshKbCounts()
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 新增话术（自动关联当前知识库）
   */
  async function addItem(data: Omit<FaqItem, 'id' | 'kb_id' | 'created_at' | 'updated_at' | 'usage_count'>): Promise<FaqItem> {
    const newItem: FaqItem = {
      ...data,
      kb_id: currentKbId.value,
      id: `faq-${Date.now()}`,
      usage_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    items.value.unshift(newItem)
    refreshKbCounts()
    return newItem
  }

  /**
   * 更新话术
   */
  async function updateItem(id: string, data: Partial<Pick<FaqItem, 'question' | 'answer' | 'category' | 'keywords' | 'priority' | 'status'>>): Promise<void> {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = {
        ...items.value[index],
        ...data,
        updated_at: new Date().toISOString(),
      }
    }
  }

  /**
   * 删除话术
   */
  async function deleteItem(id: string): Promise<void> {
    items.value = items.value.filter(i => i.id !== id)
    refreshKbCounts()
  }

  /**
   * 批量删除
   */
  async function batchDelete(ids: string[]): Promise<void> {
    items.value = items.value.filter(i => !ids.includes(i.id))
    refreshKbCounts()
  }

  // ====== 文档素材 Actions ======

  /** 上传文档（RAG 补充素材） */
  async function uploadDoc(file: File, description: string = ''): Promise<KnowledgeDoc> {
    const ext = file.name.split('.').pop()?.toLowerCase() || 'other'
    const fileTypeMap: Record<string, KnowledgeDoc['file_type']> = {
      pdf: 'pdf', md: 'md', txt: 'txt',
      xlsx: 'excel', xls: 'excel', csv: 'excel',
    }
    const newDoc: KnowledgeDoc = {
      id: `doc-${Date.now()}`,
      kb_id: currentKbId.value,
      filename: file.name,
      file_type: fileTypeMap[ext] || 'other',
      size: file.size,
      uploaded_at: new Date().toISOString(),
      description,
    }
    docs.value.push(newDoc)
    refreshKbCounts()
    return newDoc
  }

  /** 删除文档 */
  async function deleteDoc(docId: string): Promise<void> {
    docs.value = docs.value.filter(d => d.id !== docId)
    refreshKbCounts()
  }

  /**
   * 解析导入的文件内容为 FAQ 条目
   * 支持：CSV（question,answer,category 格式） / JSON 数组 / TXT（每行一条 Q&A）
   */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const text = await file.text()
    let imported: Omit<FaqItem, 'id' | 'created_at' | 'updated_at' | 'usage_count'>[] = []
    const errors: string[] = []
    const ext = file.name.split('.').pop()?.toLowerCase()

    try {
      if (ext === 'json') {
        const json = JSON.parse(text)
        const arr = Array.isArray(json) ? json : [json]
        for (const row of arr) {
          if (row.question && row.answer) {
            imported.push({
              question: row.question,
              answer: row.answer,
              category: row.category || 'other',
              keywords: row.keywords ? (Array.isArray(row.keywords) ? row.keywords : [row.keywords]) : [],
              priority: row.priority || 'medium',
              status: 'active',
            })
          } else {
            errors.push(`缺少 question 或 answer 字段: ${JSON.stringify(row).slice(0, 80)}`)
          }
        }
      } else if (ext === 'csv') {
        const lines = text.split('\n').filter(l => l.trim())
        // 跳过 header 行（如果第一行是 header）
        const startIdx = lines[0].toLowerCase().includes('question') ? 1 : 0
        for (let i = startIdx; i < lines.length; i++) {
          const cols = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''))
          if (cols.length >= 2 && cols[0] && cols[1]) {
            imported.push({
              question: cols[0],
              answer: cols[1],
              category: cols[2] || 'other',
              keywords: cols[3] ? cols[3].split(';').map(k => k.trim()) : [],
              priority: 'medium',
              status: 'active',
            })
          } else if (lines[i].trim()) {
            errors.push(`第 ${i + 1} 行格式错误`)
          }
        }
      } else if (ext === 'txt') {
        // TXT: 每行 "Q: 问题 A: 答案" 或 "问题 /// 答案"
        const lines = text.split('\n').filter(l => l.trim())
        for (const line of lines) {
          let q = '', a = ''
          if (line.includes('///')) {
            const parts = line.split('///')
            q = parts[0].trim()
            a = parts.slice(1).join('///').trim()
          } else if (line.includes('|')) {
            const parts = line.split('|')
            q = parts[0].trim()
            a = parts.slice(1).join('|').trim()
          }
          if (q && a) {
            imported.push({
              question: q,
              answer: a,
              category: 'other',
              keywords: [],
              priority: 'medium',
              status: 'active',
            })
          } else if (line.trim()) {
            errors.push(`无法解析: ${line.slice(0, 60)}`)
          }
        }
      } else {
        errors.push(`不支持的文件格式: .${ext}`)
      }

      // 批量入库
      for (const item of imported) {
        await addItem(item)
      }

      return { success: imported.length, failed: errors.length, errors }
    } catch (e) {
      return { success: 0, failed: 1, errors: [`文件解析失败: ${e instanceof Error ? e.message : String(e)}`] }
    }
  }

  return {
    // 知识库容器 State
    knowledgeBases,
    currentKbId,
    currentKnowledgeBase,

    // 话术 State
    items,
    isLoading,
    searchQuery,
    filterCategory,
    filterStatus,

    // 文档 State
    docs,
    currentDocs,

    // 知识库容器 Getters
    currentItems,

    // 话术 Getters
    filteredItems,
    totalCount,
    activeCount,
    categoryStats,

    // 知识库容器 Actions
    createKnowledgeBase,
    deleteKnowledgeBase,
    switchKnowledgeBase,
    updateKnowledgeBase,
    refreshKbCounts,

    // 话术 Actions
    fetchItems,
    addItem,
    updateItem,
    deleteItem,
    batchDelete,
    parseAndImport,

    // 文档 Actions
    uploadDoc,
    deleteDoc,
  }
})
