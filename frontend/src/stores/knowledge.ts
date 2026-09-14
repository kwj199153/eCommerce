/**
 * 业务话术库状态管理
 *
 * 多知识库容器架构：每个知识库 = 一个独立话术集合（按店铺/平台隔离）
 * 单库内支持双轨录入：结构化问答（FAQ）+ 文档素材（PDF/MD/Excel）
 *
 * 数据源：后端 PostgreSQL（/api/v1/knowledge-base），唯一权威源。
 *
 * 注意 `faq_count` / `doc_count` 是**后端读时实时统计**的派生值，不是本地算的
 * （本地算就得在增/删/导入/删库每条路径上打补丁同步，漏一处数字就永远对不上）。
 * 本 store 不再有 `refreshKbCounts()`：任何写操作后重拉一次即可。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchKnowledgeBase,
  createKnowledgeBase as apiCreateKnowledgeBase,
  updateKnowledgeBase as apiUpdateKnowledgeBase,
  deleteKnowledgeBase as apiDeleteKnowledgeBase,
  createFaq,
  updateFaq,
  deleteFaq,
  batchCreateFaqs,
  batchDeleteFaqs,
  createKnowledgeDoc,
  fetchKnowledgeDoc,
  deleteKnowledgeDoc,
} from '@/api/knowledge'

// ====== 类型定义 ======

/** 知识库容器（顶层文件夹） */
export interface KnowledgeBase {
  id: string
  name: string                          // 显示名：如「亚马逊US售后库」
  description: string                   // 描述
  icon: string                          // emoji 图标
  type: 'shop' | 'platform' | 'custom'  // 类型
  /**
   * 是否默认库（每个店铺 seed 时各建一个「通用话术库」）。
   *
   * 用显式布尔值而非「id 等于某个字面量」判断：库 id 带店铺后缀
   * （`kb-default-{shop_id}`，单主键表多店铺灌入必须加后缀），
   * 拿字面量比较会静默失效（不报错，只是删除按钮突然都出现了）。
   */
  is_default: boolean
  faq_count: number                     // 话术条数（后端读时统计）
  doc_count: number                     // 文档数（后端读时统计）
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
  /**
   * 文档正文（文本类文件上传时前端读取并提交）。
   *
   * **列表接口不返回**（整篇动辄数千字符），只在两处有值：
   * ① 上传时的响应；② `loadDocContent(id)` 按需拉取后回填。
   * 所以读到 `undefined` 只代表"还没拉"，不等于"没有正文"。
   */
  content?: string
}

export interface FaqCategory {
  key: string
  label: string
  icon: string
  color: string
}

// ====== 内置分类 ======

export const FAQ_CATEGORIES: FaqCategory[] = [
  { key: 'shipping', label: '物流配送', icon: '📦', color: 'var(--primary)' },
  { key: 'return', label: '退换货', icon: '🔄', color: 'var(--warning)' },
  { key: 'product', label: '商品咨询', icon: '📦', color: 'var(--success)' },
  { key: 'payment', label: '支付问题', icon: '💳', color: 'var(--purple)' },
  { key: 'account', label: '账户相关', icon: '👤', color: 'var(--cyan)' },
  { key: 'policy', label: '平台政策', icon: '⚖️', color: 'var(--chart-7)' },
  { key: 'review', label: '差评处理', icon: '💢', color: 'var(--danger)' },
  { key: 'other', label: '其他', icon: '❓', color: '#8c8c8c' },
]

// ====== Store ======

export const useKnowledgeStore = defineStore('knowledge', () => {
  // ====== 知识库容器 State ======
  const knowledgeBases = ref<KnowledgeBase[]>([])
  // 空串 = 尚未选中（首屏拉取后自动落到第一个库，即默认库）
  const currentKbId = ref<string>('')

  // ====== 话术条目 State ======
  const items = ref<FaqItem[]>([])
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

  // ====== 加载 / 重置 ======

  let ensured = false

  /**
   * 拉取容器 + 话术 + 文档（一次请求）。
   *
   * 失败时**不清空本地数据** —— 网络抖动不该让用户看到"话术库被清空了"。
   * 首屏本来就是 `[]`；切店铺的场景由 `resetForShopSwitch()` 负责清。
   */
  async function fetchItems() {
    ensured = true
    isLoading.value = true
    try {
      const res = await fetchKnowledgeBase()
      knowledgeBases.value = res.bases || []
      items.value = res.faqs || []
      docs.value = res.docs || []
      // 当前选中的库可能已被删除 / 尚未选中 → 落到第一个（后端把默认库排在最前）
      if (!knowledgeBases.value.some(kb => kb.id === currentKbId.value)) {
        currentKbId.value = knowledgeBases.value[0]?.id || ''
      }
    } catch (e) {
      console.warn('[Knowledge] 拉取话术库失败', e)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 确保至少拉取过一次。
   *
   * 库页 `onMounted` 调它做兜底：正常路径上 Workspace 的 `watch(currentShopId)`
   * 已经拉过（`ensured` 为 true），这里会直接返回。
   */
  async function ensureLoaded() {
    if (ensured) return
    try { await fetchItems() } catch (e) { /* 忽略 */ }
  }

  /**
   * 切换店铺时重置。
   *
   * 必须同时清 `ensured` —— 它是一次性闭包标记，只清 items 的话
   * `ensureLoaded()` 仍会因 `ensured === true` 提前返回，切店铺后不再拉取。
   */
  function resetForShopSwitch() {
    knowledgeBases.value = []
    items.value = []
    docs.value = []
    currentKbId.value = ''
    searchQuery.value = ''
    filterCategory.value = undefined
    filterStatus.value = undefined
    ensured = false
  }

  // ====== 知识库容器 Actions ======

  /** 创建新知识库（后端生成 id；随后刷新以拿到准确计数） */
  async function createKnowledgeBase(data: { name: string; description: string; icon: string; type: KnowledgeBase['type'] }): Promise<KnowledgeBase> {
    const created = await apiCreateKnowledgeBase(data)
    knowledgeBases.value.push(created)
    return created
  }

  /**
   * 删除知识库（后端**级联删除**其下话术与文档）。
   *
   * 与 monitorPool 的本地 filter 不同：这里必须等后端返回再改本地 ——
   * 后端才是权威，且要拿到 `deleted_faqs` / `deleted_docs` 计数提示用户。
   */
  async function deleteKnowledgeBase(kbId: string): Promise<{ deleted_faqs: number; deleted_docs: number }> {
    const res = await apiDeleteKnowledgeBase(kbId)
    items.value = items.value.filter(i => i.kb_id !== kbId)
    docs.value = docs.value.filter(d => d.kb_id !== kbId)
    knowledgeBases.value = knowledgeBases.value.filter(kb => kb.id !== kbId)
    // 删掉的是当前库 → 落到第一个（后端把默认库排在最前）
    if (currentKbId.value === kbId) {
      currentKbId.value = knowledgeBases.value[0]?.id || ''
    }
    return { deleted_faqs: res.deleted_faqs, deleted_docs: res.deleted_docs }
  }

  /** 切换当前知识库 */
  function switchKnowledgeBase(kbId: string) {
    currentKbId.value = kbId
    // 切换时清空筛选
    searchQuery.value = ''
    filterCategory.value = undefined
    filterStatus.value = undefined
  }

  /** 更新知识库元信息（名称/描述/图标） */
  async function updateKnowledgeBase(kbId: string, data: Partial<Pick<KnowledgeBase, 'name' | 'description' | 'icon'>>): Promise<void> {
    const updated = await apiUpdateKnowledgeBase(kbId, data)
    const idx = knowledgeBases.value.findIndex(k => k.id === kbId)
    if (idx !== -1) knowledgeBases.value[idx] = updated
  }

  // ====== 话术 Actions ======

  /** 写操作后刷新容器计数（计数由后端统计，只能重拉） */
  async function refreshKbCounts() {
    try {
      const bases = await fetchKnowledgeBase()
      // 只更新计数，不动 items / docs（避免把本地刚插入的行回灌覆盖）
      const byId = new Map(bases.bases.map(b => [b.id, b]))
      knowledgeBases.value = knowledgeBases.value.map(kb => byId.get(kb.id) || kb)
    } catch (e) {
      console.warn('[Knowledge] 刷新知识库计数失败', e)
    }
  }

  /**
   * 新增话术（自动关联当前知识库）
   *
   * `kb_id` 必传（后端也强制校验）：它是话术的唯一归属维度，
   * 没归属的条目在前端任何列表里都不可见。
   */
  async function addItem(data: Omit<FaqItem, 'id' | 'kb_id' | 'created_at' | 'updated_at' | 'usage_count'>): Promise<FaqItem> {
    const created = await createFaq({ ...data, kb_id: currentKbId.value })
    items.value.unshift(created)
    await refreshKbCounts()
    return created
  }

  /** 更新话术 */
  async function updateItem(id: string, data: Partial<Pick<FaqItem, 'question' | 'answer' | 'category' | 'keywords' | 'priority' | 'status'>>): Promise<void> {
    const updated = await updateFaq(id, data)
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) items.value[index] = updated
  }

  /** 删除话术 */
  async function deleteItem(id: string): Promise<void> {
    await deleteFaq(id)
    items.value = items.value.filter(i => i.id !== id)
    await refreshKbCounts()
  }

  /** 批量删除（列表勾选删除） */
  async function batchDelete(ids: string[]): Promise<void> {
    if (ids.length === 0) return
    await batchDeleteFaqs(ids)
    items.value = items.value.filter(i => !ids.includes(i.id))
    await refreshKbCounts()
  }

  // ====== 文档素材 Actions ======

  /**
   * 上传文档（RAG 补充素材）。
   *
   * 文本类文件顺带读取正文（txt/md/csv/json 直接读，超 1MB 跳过），
   * PDF / Excel 浏览器端无法抽取 → 正文留空（后端字段允许为空）。
   */
  async function uploadDoc(file: File, description: string = ''): Promise<KnowledgeDoc> {
    const ext = file.name.split('.').pop()?.toLowerCase() || 'other'
    const fileTypeMap: Record<string, KnowledgeDoc['file_type']> = {
      pdf: 'pdf', md: 'md', txt: 'txt',
      xlsx: 'excel', xls: 'excel', csv: 'excel',
    }
    const TEXT_EXTS = new Set(['txt', 'md', 'csv', 'json'])
    let content: string | undefined
    if (TEXT_EXTS.has(ext) && file.size <= 1024 * 1024) {
      try { content = await file.text() } catch { content = undefined }
    }

    const created = await createKnowledgeDoc({
      kb_id: currentKbId.value,
      filename: file.name,
      file_type: fileTypeMap[ext] || 'other',
      size: file.size,
      description,
      content,
    })
    docs.value.push(created)
    await refreshKbCounts()
    return created
  }

  /**
   * 按 id 取单篇文档正文并回填本地。
   *
   * 列表接口刻意不返回 content（整篇数千字符），需要正文时按需拉取。
   */
  async function loadDocContent(docId: string): Promise<KnowledgeDoc | undefined> {
    try {
      const full = await fetchKnowledgeDoc(docId)
      const idx = docs.value.findIndex(d => d.id === docId)
      if (idx !== -1) docs.value[idx] = full
      return full
    } catch (e) {
      console.warn('[Knowledge] 拉取文档正文失败', e)
      return undefined
    }
  }

  /** 删除文档 */
  async function deleteDoc(docId: string): Promise<void> {
    await deleteKnowledgeDoc(docId)
    docs.value = docs.value.filter(d => d.id !== docId)
    await refreshKbCounts()
  }

  /**
   * 解析导入的文件内容为 FAQ 条目
   * 支持：CSV（question,answer,category 格式） / JSON 数组 / TXT（每行一条 Q&A）
   */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const text = await file.text()
    const imported: Omit<FaqItem, 'id' | 'kb_id' | 'created_at' | 'updated_at' | 'usage_count'>[] = []
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

      if (imported.length === 0) {
        return { success: 0, failed: errors.length, errors }
      }

      // 一次批量提交（不是循环单条 POST）。**导入的条目统一归入当前库** ——
      // 文件里没有「归属哪个库」的概念，孤立条目在 UI 里取不到。
      const kbId = currentKbId.value
      const res = await batchCreateFaqs(imported.map(it => ({ ...it, kb_id: kbId })))
      items.value.unshift(...(res.items || []))
      await refreshKbCounts()

      // 后端跳过的不再计入 success，避免"导入成功 N 条"与实际入库不符
      const skipped = res.skipped || 0
      if (skipped > 0) errors.push(`${skipped} 条因缺少必填字段被服务端跳过`)

      return { success: res.added || 0, failed: errors.length, errors }
    } catch (e) {
      return { success: 0, failed: 1, errors: [`导入失败: ${e instanceof Error ? e.message : String(e)}`] }
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
    ensureLoaded,
    resetForShopSwitch,
    addItem,
    updateItem,
    deleteItem,
    batchDelete,
    parseAndImport,

    // 文档 Actions
    uploadDoc,
    loadDocContent,
    deleteDoc,
  }
})
