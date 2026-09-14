/**
 * 平台规则库状态管理
 *
 * 管理各跨境电商平台（Amazon / Shopee / TikTok Shop / TEMU 等）的运营规则、
 * 政策条款、合规要求。支持按平台筛选、搜索、分类。
 * 数据源：后端 PostgreSQL（/api/v1/platform-rules），唯一权威源。
 *
 * 职责边界：**查重逻辑刻意留在前端**。`checkDuplicate` 同时被「AI 拆分预标注」和
 * 「用户勾选时的 Layer 3 终检」复用，搬到后端就会变成两份实现、迟早分叉。
 * 后端只负责「提取 + 持久化」，去重判断是交互态的事。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchPlatformRules,
  createPlatformRule,
  updatePlatformRule,
  deletePlatformRule,
  batchCreatePlatformRules,
  aiSplitPlatformRules,
  createPlatformRuleDoc,
  fetchPlatformRuleDoc,
  deletePlatformRuleDoc,
} from '@/api/platformRules'

// ====== 类型定义 ======

export interface PlatformRule {
  id: string
  platform: string          // 平台标识：amazon / shopee / tiktok / temu / lazada ...
  category: string          // 规则分类：listing / policy / compliance / payment / logistics / review / ad
  title: string             // 规则标题
  content: string           // 规则正文
  effective_date: string    // 生效日期（YYYY-MM-DD）
  expiry_date?: string      // 失效日期（YYYY-MM-DD），空=永不过期
  /** 状态：auto=根据日期自动计算，active/upcoming/expired=手动覆盖 */
  status: 'auto' | 'active' | 'upcoming' | 'expired'
  tags: string[]
  source?: string           // 来源链接（外部 URL）
  source_doc_id?: string    // 关联的来源文档 ID（本地文档库）
  created_at: string
  updated_at: string
}

/** 平台规则文档素材（RAG 补充资料） */
export interface PlatformRuleDoc {
  id: string
  platform: string
  filename: string
  file_type: 'pdf' | 'md' | 'excel' | 'txt' | 'other'
  size: number              // bytes
  uploaded_at: string
  description: string
  /** 文档正文内容（上传时提取 / 用户粘贴；PDF 为 OCR/文本抽取结果） */
  content?: string
}

// ====== AI 拆分去重 ======

/** 去重状态 */
export type DupStatus = 'new' | 'duplicate' | 'update'

/** AI 拆分待确认规则（带去重标注） */
export interface PendingRuleWithDup extends Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'> {
  _dupStatus: DupStatus
  _matchedRuleId?: string    /** 命中的已有规则 ID（duplicate/update 时有值） */
  _similarityScore?: number   /** 相似度分数 0-1 */
  _diffSummary?: string       /** 差异摘要（update 时：如 "字符限制从200→150"）*/
}

/** 去重配置 */
const DUP_CONFIG = {
  /** 关键词重叠率阈值（> 此值视为疑似重复） */
  keywordOverlapThreshold: 0.55,
  /** 高相似度阈值（> 此值直接判定为 duplicate） */
  highSimilarityThreshold: 0.75,
  /** 版本更新检测：同平台+同分类+标题相似，但 content 中数值/日期不同 */
  numericDiffPattern: /(\d+)\s*[-–—~～]\s*(\d+)/g,
} as const

// ====== 平台配置 ======

export const PLATFORMS: { key: string; label: string; icon: string; color: string }[] = [
  { key: 'amazon', label: 'Amazon', icon: '📦', color: '#ff9900' },
  { key: 'shopee', label: 'Shopee', icon: '🛍️', color: '#ee4d2d' },
  { key: 'tiktok', label: 'TikTok Shop', icon: '🎵', color: '#000000' },
  { key: 'temu', label: 'TEMU', icon: '🧺', color: '#fb7701' },
  { key: 'lazada', label: 'Lazada', icon: '🌏', color: '#0f146d' },
]

// ====== 规则分类 ======

export const RULE_CATEGORIES: { key: string; label: string; icon: string }[] = [
  { key: 'listing', label: 'Listing 规则', icon: '📝' },
  { key: 'policy', label: '平台政策', icon: '⚖️' },
  { key: 'compliance', label: '合规要求', icon: '🛡️' },
  { key: 'payment', label: '支付结算', icon: '💳' },
  { key: 'logistics', label: '物流仓储', icon: '🚚' },
  { key: 'review', label: '评价管理', icon: '⭐' },
  { key: 'ad', label: '广告投放', icon: '📢' },
]

// ====== 状态自动计算引擎 ======

/**
 * 根据生效日期 + 失效日期 自动判定规则状态
 *
 * 判定逻辑：
 *   effective_date > 今天 → upcoming（即将生效）
 *   effective_date <= 今天 && (expiry_date 为空 || expiry_date > 今天) → active（生效中）
 *   expiry_date <= 今天 → expired（已失效）
 */
export function computeStatus(
  effectiveDate: string,
  expiryDate?: string,
): 'active' | 'upcoming' | 'expired' {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const eff = new Date(effectiveDate + 'T00:00:00')
  const exp = expiryDate ? new Date(expiryDate + 'T00:00:00') : null

  if (eff > today) return 'upcoming'
  if (exp && exp <= today) return 'expired'
  return 'active'
}

/** 获取规则的实际显示状态（手动覆盖优先，否则自动计算） */
export function getResolvedStatus(rule: PlatformRule): 'active' | 'upcoming' | 'expired' {
  if (rule.status !== 'auto') return rule.status
  return computeStatus(rule.effective_date, rule.expiry_date)
}

export const usePlatformRulesStore = defineStore('platformRules', () => {
  const items = ref<PlatformRule[]>([])
  const docs = ref<PlatformRuleDoc[]>([])
  const isLoading = ref(false)

  // 过滤状态（初始 undefined，避免 a-select allow-clear 清空后被误判）
  const searchQuery = ref('')
  const filterPlatform = ref<string | undefined>(undefined)
  const filterCategory = ref<string | undefined>(undefined)
  const filterStatus = ref<string | undefined>(undefined)

  // ====== Getters ======

  /** 带解析后状态的规则列表（供表格展示用） */
  const itemsWithResolvedStatus = computed(() =>
    items.value.map(item => ({
      ...item,
      _resolvedStatus: getResolvedStatus(item),
    })),
  )

  const filteredItems = computed(() => {
    let result = items.value

    if (filterPlatform.value && filterPlatform.value !== 'all') {
      result = result.filter(item => item.platform === filterPlatform.value)
    }
    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    if (filterStatus.value && filterStatus.value !== 'all') {
      // 按解析后的实际状态过滤（而非原始 status 字段）
      result = result.filter(item => getResolvedStatus(item) === filterStatus.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.title.toLowerCase().includes(q) ||
        item.content.toLowerCase().includes(q) ||
        item.tags.some(t => t.toLowerCase().includes(q))
      )
    }

    // 按生效日期倒序
    return [...result].sort((a, b) => b.effective_date.localeCompare(a.effective_date))
  })

  const totalCount = computed(() => items.value.length)
  const platformCount = computed(() => new Set(items.value.map(i => i.platform)).size)

  /** 按解析后状态统计各状态数量 */
  const statusCounts = computed(() => {
    const counts = { active: 0, upcoming: 0, expired: 0 }
    for (const item of items.value) {
      counts[getResolvedStatus(item)]++
    }
    return counts
  })

  /** 根据 ID 查找文档 */
  function getDocById(docId: string): PlatformRuleDoc | undefined {
    return docs.value.find(d => d.id === docId)
  }

  /** 当前是否启用了任何过滤条件 */
  const hasActiveFilters = computed(() =>
    Boolean(searchQuery.value.trim()) ||
    (filterPlatform.value && filterPlatform.value !== 'all') ||
    (filterCategory.value && filterCategory.value !== 'all') ||
    (filterStatus.value && filterStatus.value !== 'all')
  )

  /** 当前已应用的过滤条件数 */
  const activeFilterCount = computed(() => {
    let n = 0
    if (searchQuery.value.trim()) n++
    if (filterPlatform.value && filterPlatform.value !== 'all') n++
    if (filterCategory.value && filterCategory.value !== 'all') n++
    if (filterStatus.value && filterStatus.value !== 'all') n++
    return n
  })

  // ====== 加载 / 重置 ======

  let ensured = false

  /**
   * 拉取规则 + 文档（一次请求）。
   *
   * 失败时**不清空本地数据** —— 网络抖动不该让用户看到"规则库被清空了"。
   * 首屏 items/docs 本来就是 `[]`；切店铺的场景由 `resetForShopSwitch()` 负责清。
   */
  async function fetchItems() {
    ensured = true
    isLoading.value = true
    try {
      const res = await fetchPlatformRules()
      items.value = res.items || []
      docs.value = res.docs || []
    } catch (e) {
      console.warn('[PlatformRules] 拉取规则库失败', e)
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
   * 过滤条件一并回到默认，否则新店铺会顶着上一个店铺的筛选条件显示。
   */
  function resetForShopSwitch() {
    items.value = []
    docs.value = []
    clearAllFilters()
    ensured = false
  }

  // ====== Actions ======

  async function addItem(data: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>): Promise<PlatformRule> {
    const created = await createPlatformRule(data)
    items.value.unshift(created)
    return created
  }

  async function updateItem(id: string, data: Partial<Omit<PlatformRule, 'id' | 'created_at'>>): Promise<void> {
    const updated = await updatePlatformRule(id, data)
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) items.value[index] = updated
  }

  async function deleteItem(id: string): Promise<void> {
    await deletePlatformRule(id)
    items.value = items.value.filter(i => i.id !== id)
  }

  function clearAllFilters() {
    searchQuery.value = ''
    filterPlatform.value = undefined
    filterCategory.value = undefined
    filterStatus.value = undefined
  }

  // ====== 文档素材 Actions ======

  /**
   * 上传规则文档（RAG 补充素材）。
   *
   * 文本类文件顺带读取正文（txt/md/csv/json 直接读，超 1MB 跳过），
   * PDF / Excel 浏览器端无法抽取 → 正文留空。列表点开预览会显示
   * 「暂无原文内容」，AI 拆分也会明确提示需要正文（而不是编造规则）。
   */
  async function uploadDoc(file: File, platform: string = 'amazon', description: string = ''): Promise<PlatformRuleDoc> {
    const ext = file.name.split('.').pop()?.toLowerCase() || 'other'
    const fileTypeMap: Record<string, PlatformRuleDoc['file_type']> = {
      pdf: 'pdf', md: 'md', txt: 'txt',
      xlsx: 'excel', xls: 'excel', csv: 'excel',
    }
    const TEXT_EXTS = new Set(['txt', 'md', 'csv', 'json'])
    let content: string | undefined
    if (TEXT_EXTS.has(ext) && file.size <= 1024 * 1024) {
      try { content = await file.text() } catch { content = undefined }
    }

    const created = await createPlatformRuleDoc({
      platform,
      filename: file.name,
      file_type: fileTypeMap[ext] || 'other',
      size: file.size,
      description,
      content,
    })
    docs.value.push(created)
    return created
  }

  /**
   * 按 id 取单篇文档正文并回填本地。
   *
   * 列表接口刻意不返回 content（正文动辄数千字符），预览面板打开时才拉这一条。
   */
  async function loadDocContent(docId: string): Promise<PlatformRuleDoc | undefined> {
    try {
      const full = await fetchPlatformRuleDoc(docId)
      const idx = docs.value.findIndex(d => d.id === docId)
      if (idx !== -1) docs.value[idx] = full
      return full
    } catch (e) {
      console.warn('[PlatformRules] 拉取文档正文失败', e)
      return undefined
    }
  }

  /** 删除文档 */
  async function deleteDoc(docId: string): Promise<void> {
    await deletePlatformRuleDoc(docId)
    docs.value = docs.value.filter(d => d.id !== docId)
  }

  /**
   * 批量导入规则（JSON / CSV / TXT）
   * JSON：数组，每项含 platform/category/title/content
   * CSV：platform, category, title, content
   * TXT：每行 "标题 /// 内容"
   */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const text = await file.text()
    const imported: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>[] = []
    const errors: string[] = []
    const ext = file.name.split('.').pop()?.toLowerCase()

    const today = new Date().toISOString().slice(0, 10)

    try {
      if (ext === 'json') {
        const json = JSON.parse(text)
        const arr = Array.isArray(json) ? json : [json]
        for (const row of arr) {
          if (row.title && row.content) {
            imported.push({
              platform: row.platform || 'amazon',
              category: row.category || 'policy',
              title: String(row.title),
              content: String(row.content),
              effective_date: row.effective_date || today,
              status: row.status || 'auto',
              tags: row.tags ? (Array.isArray(row.tags) ? row.tags : [row.tags]) : [],
              source: row.source || '',
            })
          } else {
            errors.push(`缺少 title 或 content 字段: ${JSON.stringify(row).slice(0, 80)}`)
          }
        }
      } else if (ext === 'csv') {
        const lines = text.split('\n').filter(l => l.trim())
        const startIdx = lines[0].toLowerCase().includes('title') ? 1 : 0
        for (let i = startIdx; i < lines.length; i++) {
          const cols = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''))
          if (cols.length >= 2 && cols[0] && cols[1]) {
            imported.push({
              platform: cols[2] || 'amazon',
              category: cols[3] || 'policy',
              title: cols[0],
              content: cols[1],
              effective_date: today,
              status: 'auto',
              tags: [],
              source: '',
            })
          } else if (lines[i].trim()) {
            errors.push(`第 ${i + 1} 行格式错误`)
          }
        }
      } else if (ext === 'txt') {
        const lines = text.split('\n').filter(l => l.trim())
        for (const line of lines) {
          let title = '', content = ''
          if (line.includes('///')) {
            const parts = line.split('///')
            title = parts[0].trim()
            content = parts.slice(1).join('///').trim()
          } else if (line.includes('|')) {
            const parts = line.split('|')
            title = parts[0].trim()
            content = parts.slice(1).join('|').trim()
          }
          if (title && content) {
            imported.push({
              platform: 'amazon',
              category: 'policy',
              title,
              content,
              effective_date: today,
              status: 'auto',
              tags: [],
              source: '',
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

      // 一次批量提交（不是循环单条 POST）。本地已过滤缺字段行，后端仍会再校验一遍
      // 并返回 `skipped` —— 若 skipped > 0 说明本地校验漏了，据实告知而不是报"全部成功"。
      const res = await batchCreatePlatformRules(imported)
      items.value.unshift(...(res.items || []))
      const skipped = res.skipped || 0
      if (skipped > 0) errors.push(`${skipped} 条因缺少必填字段被服务端跳过`)

      return { success: res.added || 0, failed: errors.length, errors }
    } catch (e) {
      return { success: 0, failed: 1, errors: [`导入失败: ${e instanceof Error ? e.message : String(e)}`] }
    }
  }

  /**
   * ====== 去重引擎（三层校验之 Layer 1 + Layer 3 共用） ======
   *
   * 对单条待入库规则与现有规则库做查重
   * 策略：
   *   1. 先按 platform + category 过滤（同平台同分类才可能重复）
   *   2. 关键词提取 + 重叠率计算（中英文分词）
   *   3. 数值/日期 diff 检测 → 判定为「版本更新」而非「重复」
   */

  /** 简易中文分词：按非词字符切分 + 过滤停用词 */
  function extractKeywords(text: string): Set<string> {
    const stopWords = new Set([
      '的', '了', '在', '是', '和', '与', '或', '等', '及', '对',
      '从', '到', '被', '把', '让', '给', '为', '以', '可', '需',
      '应', '将', '已', '此', '该', '其', '它', '之', '所', '不',
      'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
      'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
      'and', 'or', 'not', 'must', 'should', 'may', 'can', 'will',
      '产品', '商品', '规则', '要求', '规定', '需要', '包括', '包含',
    ])
    // 提取中文词汇（2字以上连续中文）+ 英文单词 + 数字+单位组合
    const tokens = text
      .toLowerCase()
      .replace(/[^\u4e00-\u9fa5a-z0-9%°]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length >= 2 && !stopWords.has(t))
    return new Set(tokens)
  }

  /** 计算两个关键词集合的 Jaccard 相似度 */
  function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
    if (a.size === 0 || b.size === 0) return 0
    let intersection = 0
    for (const word of a) {
      if (b.has(word)) intersection++
    }
    return intersection / (a.size + b.size - intersection)
  }

  /** 从文本中提取数值范围，用于版本更新检测 */
  function extractNumericPatterns(text: string): string[] {
    const matches: string[] = []
    let m: RegExpExecArray | null
    const re = /(\d+(?:\.\d+)?)\s*[%°个天小时分钟字节KBMBGB]?(?:\s*[-–—~～]\s*(\d+(?:\.\d+)?))?/g
    while ((m = re.exec(text)) !== null) {
      matches.push(m[0])
    }
    return matches
  }

  /**
   * 核心查重函数：对比一条新规则与已有规则库
   * @returns 去重状态 + 匹配到的规则信息
   */
  function checkDuplicate(
    newRule: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>,
  ): { status: DupStatus; matchedRule?: PlatformRule; similarity: number; diffSummary?: string } {
    // 同平台 + 同分类的候选规则
    const candidates = items.value.filter(
      r => r.platform === newRule.platform && r.category === newRule.category,
    )

    if (candidates.length === 0) {
      return { status: 'new', similarity: 0 }
    }

    const newKeywords = extractKeywords(newRule.title + ' ' + newRule.content)
    let bestMatch: PlatformRule | undefined
    let bestSim = 0

    for (const candidate of candidates) {
      const candKeywords = extractKeywords(candidate.title + ' ' + candidate.content)
      const sim = jaccardSimilarity(newKeywords, candKeywords)
      if (sim > bestSim) {
        bestSim = sim
        bestMatch = candidate
      }
    }

    // 高相似度 → 检测是否为版本更新（数值/日期变化）
    if (bestSim >= DUP_CONFIG.keywordOverlapThreshold && bestMatch) {
      const newNumerics = extractNumericPatterns(newRule.content)
      const oldNumerics = extractNumericPatterns(bestMatch.content)

      // 有数值但数值不同 → 版本更新
      const hasNumericDiff =
        newNumerics.length > 0 &&
        oldNumerics.length > 0 &&
        !newNumerics.every(n => oldNumerics.includes(n))

      if (hasNumericDiff || bestSim >= DUP_CONFIG.highSimilarityThreshold) {
        if (hasNumericDiff) {
          // 找出具体差异
          const diffParts: string[] = []
          for (const nn of newNumerics) {
            if (!oldNumerics.includes(nn)) {
              diffParts.push(nn)
            }
          }
          return {
            status: 'update',
            matchedRule: bestMatch,
            similarity: bestSim,
            diffSummary: diffParts.length > 0 ? `参数变更: ${diffParts.join(', ')}` : '内容有数值/日期更新',
          }
        }
        return {
          status: 'duplicate',
          matchedRule: bestMatch,
          similarity: bestSim,
        }
      }
    }

    // 低相似度 → 全新规则
    return { status: 'new', similarity: bestSim }
  }

  /**
   * AI 拆分文档 → 提取结构化规则（带去重标注，待人工确认）
   *
   * 流程：
   *   1. 后端从库里取文档正文，调 LLM 提取 N 条规则（前端不持有正文）
   *   2. 对每条规则执行 Layer 1 预查重（checkDuplicate）
   *   3. 标注 _dupStatus / _matchedRuleId / _similarityScore / _diffSummary
   *   4. 返回带标注的结果，由 Vue 弹窗展示
   *
   * `degraded=true`（LLM 不可用 / 文档无正文 / 未提取到）时**抛错**，由 UI 提示原因。
   * 旧实现是前端用写死的 templateMap 冒充 AI 提取 —— 会产出文档里根本没有的
   * 「FCC/CE 认证」之类的规则，比"提取失败"有害得多，故彻底删除。
   */
  async function aiSplitFromDoc(
    docId: string,
    options?: { onProgress?: (msg: string) => void },
  ): Promise<{ extracted: number; rules: PendingRuleWithDup[] }> {
    const doc = docs.value.find(d => d.id === docId)
    if (!doc) throw new Error(`文档不存在: ${docId}`)

    options?.onProgress?.(`正在分析文档「${doc.filename}」...`)

    const res = await aiSplitPlatformRules(docId)

    if (res.degraded) {
      throw new Error(res.reason || 'AI 拆分暂不可用')
    }

    options?.onProgress?.('正在与现有规则库比对查重...')

    // Layer 1：逐条预查重，标注去重状态
    const annotatedRules: PendingRuleWithDup[] = (res.rules || []).map((rule) => {
      const dupResult = checkDuplicate(rule)
      return {
        ...rule,
        _dupStatus: dupResult.status,
        _matchedRuleId: dupResult.matchedRule?.id,
        _similarityScore: dupResult.similarity,
        _diffSummary: dupResult.diffSummary,
      }
    })

    if (annotatedRules.length === 0) {
      throw new Error('AI 未能从该文档中提取出可用于入库的规则，请检查文档内容')
    }

    const summary = annotatedRules.reduce(
      (acc, r) => { acc[r._dupStatus]++; return acc },
      { new: 0, duplicate: 0, update: 0 } as Record<DupStatus, number>,
    )

    options?.onProgress?.(
      `完成！提取 ${annotatedRules.length} 条（全新 ${summary.new} / 重复 ${summary.duplicate} / 更新 ${summary.update}），请确认后添加`,
    )

    return { extracted: annotatedRules.length, rules: annotatedRules }
  }

  /**
   * Layer 3：提交前的最终防重校验
   * 对用户勾选的规则再做一次检查，对仍为 duplicate 的弹出警告
   * @returns { ok, warnings, toAdd }
   */
  function prePersistCheck(
    rules: PendingRuleWithDup[],
  ): { ok: boolean; warnings: string[]; safeRules: PendingRuleWithDup[] } {
    const warnings: string[] = []
    const safeRules: PendingRuleWithDup[] = []

    for (const rule of rules) {
      // 重新跑一次查重（防止用户确认期间有人新增了类似规则）
      const freshCheck = checkDuplicate(rule)

      if (freshCheck.status === 'duplicate' && freshCheck.similarity >= DUP_CONFIG.highSimilarityThreshold) {
        const matchedTitle = freshCheck.matchedRule?.title || '未知规则'
        warnings.push(`「${rule.title}」与已有规则「${matchedTitle}」高度相似（${(freshCheck.similarity * 100).toFixed(0)}%）`)
        // 仍然放入 safeRules（允许用户强制添加），但标记上警告
        safeRules.push({ ...rule, _dupStatus: 'duplicate', _matchedRuleId: freshCheck.matchedRule?.id })
      } else if (freshCheck.status === 'update') {
        // 版本更新 → 正常放行，后续由调用方决定是否覆盖旧版
        safeRules.push({ ...rule, _dupStatus: 'update', _matchedRuleId: freshCheck.matchedRule?.id })
      } else {
        safeRules.push(rule)
      }
    }

    return { ok: warnings.length === 0, warnings, safeRules }
  }

  /** 用新规则覆盖旧版本（版本管理） */
  async function replaceOldVersion(oldRuleId: string, newRuleData: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>): Promise<void> {
    // 将旧规则标记为 expired（保留历史记录，不作物理删除）
    const oldRule = items.value.find(r => r.id === oldRuleId)
    if (oldRule) {
      await updateItem(oldRule.id, { status: 'expired', tags: [...oldRule.tags, '已作废-版本更新'] })
    }
    // 新规则作为 active 入库
    await addItem(newRuleData)
  }

  return {
    // State
    items,
    docs,
    isLoading,
    searchQuery,
    filterPlatform,
    filterCategory,
    filterStatus,

    // Getters
    filteredItems,
    itemsWithResolvedStatus,
    totalCount,
    platformCount,
    statusCounts,
    hasActiveFilters,
    activeFilterCount,
    getDocById,

    // Actions
    fetchItems,
    ensureLoaded,
    resetForShopSwitch,
    addItem,
    updateItem,
    deleteItem,
    clearAllFilters,
    uploadDoc,
    loadDocContent,
    deleteDoc,
    parseAndImport,
    aiSplitFromDoc,
    prePersistCheck,
    replaceOldVersion,
  }
})
