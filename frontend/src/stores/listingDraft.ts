/**
 * Listing 统一工作区草稿（Store）
 *
 * 定位：Listing 优化师右侧「Listing 面板」的单一数据源。
 * 关键词 / 标题 / 五点 / A+ 描述 / SEO 诊断 五个模块共用一份草稿，
 * 支持：① 从当前载入产品预填 ② 单模块或全量 AI 生成填充 ③ 人工编辑 ④ 统一保存回产品库。
 *
 * 说明：草稿只存在于内存（刷新即丢），保存后才写入 productLibrary。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useProductLibraryStore } from './productLibrary'

// ====== 类型定义 ======

/**
 * 关键词行。
 *
 * ★ 三个指标字段可空（`null`），这不是洁癖 —— `null` 的语义是
 *   **「后端没提供这个指标」**，与「指标真的是 0」是两件事：
 *
 *   · `POST /listing/generate/keywords` 回的是 **Search Terms**（后台搜索词：
 *     扁平字符串数组 + 总字节数），**没有** 搜索量 / 竞争度 / 相关度；
 *   · 关键词挖掘那条链（`syncListingDraft` case `keyword-miner` 把工具结果
 *     原样透传）**有**真实指标。
 *
 *   旧写法用 `0 / 'medium' / 80` 兜底 ⇒ 把「未测量」渲染成「搜索量 0、相关度 80」，
 *   那就是编数据。现在统一 `null`，界面渲染 «—»。
 */
export interface KeywordRow {
  id: string
  word: string
  search_volume: number | null
  competition: 'high' | 'medium' | 'low' | null
  relevance: number | null
  selected: boolean
}

export interface BulletRow {
  id: string
  title: string
  content: string
}

export interface APlusModule {
  id: string
  type: 'text' | 'image-text' | 'highlights' | 'comparison'
  heading: string
  content?: string
  paragraphs?: string[]
  items?: Array<{ title: string; desc: string }>
}

export interface SeoCheckItem {
  category: string
  score: number
  status: 'good' | 'warning' | 'bad'
  issues: string[]
  suggestions: string[]
}

let seq = 0
const uid = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`

export const useListingDraftStore = defineStore('listingDraft', () => {
  const productLibrary = useProductLibraryStore()

  // ====== 产品上下文 ======
  const productId = ref<string>('')
  const productName = ref('')
  const brand = ref('')
  const sellingPoints = ref('')
  const category = ref('')
  const site = ref('com')
  const sourceMode = ref<'product' | 'manual'>('manual')
  const asin = ref('')             // 载入产品的 ASIN（SKU 为真实 ASIN，SPU 为空）
  const variationValue = ref('')   // 载入 SKU 时的规格值（如「红色」「M」）

  // ====== 五个模块草稿 ======
  const keywords = ref<KeywordRow[]>([])
  const title = ref('')
  const titleVariants = ref<string[]>([])
  const bullets = ref<BulletRow[]>([])
  const aplusModules = ref<APlusModule[]>([])
  const seoChecks = ref<SeoCheckItem[]>([])
  const seoScore = ref<number | null>(null)

  // ====== 自定义 prompt（第 273 轮：全局 + 局部覆盖）======
  // 全局指令：作用于四模块的默认兜底；局部 customPrompt 非空则覆盖全局对应部分。
  const globalInstruction = ref('')
  // 局部指令：四个模块各自的覆盖项。空串 = 未覆盖，走全局。
  const keywordPrompt = ref('')
  const titlePrompt = ref('')
  const bulletPrompt = ref('')
  const aplusPrompt = ref('')

  /** 解析某模块最终生效的 prompt：局部优先，否则全局；均空 ⇒ undefined（走默认） */
  function resolvePrompt(local: string): string | undefined {
    const v = (local ?? '').trim()
    if (v) return v
    const g = globalInstruction.value.trim()
    return g || undefined
  }

  // 各模块是否已有内容（用于 Tab 角标 / 生成按钮状态）
  const moduleFilled = computed(() => ({
    keywords: keywords.value.length > 0,
    title: !!title.value.trim(),
    bullets: bullets.value.some(b => b.title.trim() || b.content.trim()),
    aplus: aplusModules.value.some(m => m.heading.trim() || m.content?.trim()),
    seo: seoChecks.value.length > 0,
  }))

  const filledCount = computed(() => Object.values(moduleFilled.value).filter(Boolean).length)

  // ====== 从产品库载入（预填）======
  function loadFromProduct(p: any) {
    if (!p) return
    productId.value = p.id || ''
    productName.value = p.title || ''
    brand.value = p.brand || ''
    category.value = p.category || ''
    sellingPoints.value = p.selling_points || ''
    site.value = p.site === 'Amazon US' ? 'com' : (p.site || 'com')
    sourceMode.value = 'product'
    asin.value = p.asin || ''
    variationValue.value = p.spec_value || ''

    // 产品库里只存了词本身，一个指标都没有 ⇒ 一律 null（不用 0 / 80 冒充）
    keywords.value = (p.keywords || []).map((w: string) => ({
      id: uid('kw'),
      word: w,
      search_volume: null,
      competition: null,
      relevance: null,
      selected: true,
    }))
    title.value = p.generated_title || p.title || ''
    bullets.value = (p.generated_bullets || []).map((b: any) => ({
      id: uid('bl'),
      title: b.title || '',
      content: b.content || '',
    }))
    aplusModules.value = normalizeAPlus(p.generated_a_plus)
    seoChecks.value = []
    seoScore.value = p.seo_score ?? null
  }

  /** A+ 兼容多种历史结构（modules[] / description.sections[] / 纯文本） */
  function normalizeAPlus(raw: any): APlusModule[] {
    if (!raw) return []
    if (Array.isArray(raw)) return raw.map(normalizeModule)
    if (Array.isArray(raw.modules)) return raw.modules.map(normalizeModule)
    // 走 normalizeModule：后端 sections 是 `{type: 'intro'|'features'|'scenarios', content}`，
    // 旧写法硬编 `type:'text'` + 只认 `s.heading` ⇒ 后端段落全部 heading 为空。
    if (Array.isArray(raw.sections)) return raw.sections.map(normalizeModule)
    return []
  }

  /** A+ 的**版式**类型（决定用哪个编辑控件渲染） */
  const A_PLUS_LAYOUTS = ['text', 'image-text', 'highlights', 'comparison']

  /**
   * 后端 `ProductDescription.sections[*].type` 是**语义**枚举，不是版式。
   * 实测取值 `intro` / `features` / `scenarios`，item 只有 `{type, content}` 两个键。
   *
   * ★ 这两个 "type" 同名不同义。不映射的后果不是「显示得难看」，而是
   *   `AplusSection` 的三个 `v-if`（text / image-text / highlights）**全不命中**
   *   ⇒ 正文一个字都不渲染，只剩一个空的标题输入框。
   *   小标题用后端给的那个枚举做中文标签，正文仍是 verbatim 的 `content`。
   */
  const SECTION_TYPE_LABEL: Record<string, string> = {
    intro: '产品简介',
    features: '核心卖点详解',
    scenarios: '使用场景',
  }

  function normalizeModule(m: any): APlusModule {
    const rawType = String(m?.type || '')
    const isLayout = A_PLUS_LAYOUTS.includes(rawType)
    return {
      id: uid('ap'),
      type: (isLayout ? rawType : 'text') as APlusModule['type'],
      // 后端语义 type → 中文小标题；认不出的类型不硬编，留空
      heading: m.heading || (isLayout ? '' : SECTION_TYPE_LABEL[rawType] || ''),
      content: m.content || '',
      paragraphs: m.paragraphs ? [...m.paragraphs] : undefined,
      items: m.items ? m.items.map((i: any) => ({ title: i.title || '', desc: i.desc || '' })) : undefined,
    }
  }

  // ====== 各模块写入（生成/编辑共用）======
  /**
   * 写入关键词行（**唯一写入点**，两个生产者的键在这里对账）。
   *
   * ★ 两个生产者用的键不同：
   *   · Listing 工作区自己生成 → `word`
   *   · 关键词挖掘（`syncListingDraft` 把工具结果原样透传）→ `keyword`
   *   只认 `word` 会让挖掘结果变成 N 行**空关键词**（实测就是如此）。
   * ★ 指标缺省一律 `null`（未提供），不拿 0 / 'medium' / 80 兜底。
   */
  function setKeywords(rows: Array<Partial<KeywordRow> & { keyword?: string }>) {
    keywords.value = rows.map(r => ({
      id: uid('kw'),
      word: String(r.word ?? r.keyword ?? '').trim(),
      search_volume: r.search_volume ?? null,
      competition: (r.competition as KeywordRow['competition']) ?? null,
      relevance: r.relevance ?? null,
      selected: r.selected ?? true,
    }))
  }

  function addKeyword(word = '') {
    // 手工新增的行**没有任何来源** ⇒ 指标全 null
    keywords.value.push({
      id: uid('kw'),
      word,
      search_volume: null,
      competition: null,
      relevance: null,
      selected: true,
    })
  }

  function removeKeyword(id: string) {
    keywords.value = keywords.value.filter(k => k.id !== id)
  }

  function setTitle(main: string, variants: string[] = []) {
    title.value = main
    titleVariants.value = variants
  }

  function setBullets(rows: Array<{ title?: string; content?: string }>) {
    bullets.value = rows.map(b => ({
      id: uid('bl'),
      title: b.title || '',
      content: b.content || '',
    }))
  }

  function addBullet() {
    bullets.value.push({ id: uid('bl'), title: '', content: '' })
  }

  function removeBullet(id: string) {
    bullets.value = bullets.value.filter(b => b.id !== id)
  }

  function setAPlus(modules: any[]) {
    aplusModules.value = modules.map(normalizeModule)
  }

  function addAPlusModule(type: APlusModule['type'] = 'text') {
    aplusModules.value.push({
      id: uid('ap'),
      type,
      heading: '',
      content: type === 'text' ? '' : undefined,
      paragraphs: type === 'image-text' ? [''] : undefined,
      items: type === 'highlights' ? [{ title: '', desc: '' }] : undefined,
    })
  }

  function removeAPlusModule(id: string) {
    aplusModules.value = aplusModules.value.filter(m => m.id !== id)
  }

  function setSeo(checks: SeoCheckItem[], score?: number) {
    seoChecks.value = checks
    seoScore.value = score ?? Math.round(checks.reduce((s, c) => s + c.score, 0) / (checks.length || 1))
  }

  // ====== 统一保存回产品库 ======
  async function saveToProduct(): Promise<{ ok: boolean; msg: string }> {
    if (!productId.value) return { ok: false, msg: '未载入产品，请先从顶部「载入产品」选择' }
    const payload: any = {
      generated_title: title.value,
      generated_bullets: bullets.value
        .filter(b => b.title.trim() || b.content.trim())
        .map(b => ({ title: b.title, content: b.content })),
      generated_a_plus: { modules: aplusModules.value },
      seo_score: seoScore.value ?? undefined,
      generated_at: new Date().toISOString(),
    }
    // 关键：整段包 try/catch，任何失败都以 { ok:false } 返回。
    // 否则异常会以未处理的 rejection 冒到调用方，用户看到的只是「点了没反应」。
    try {
      const r = await productLibrary.updateListing(productId.value, payload)
      if (r && r.synced === false) {
        return { ok: false, msg: `草稿已更新，但后端保存失败：${r.error || '未知错误'}` }
      }
      // 关键词单独走 updateItem（合并去重，避免覆盖产品原有关键词）
      const picked = keywords.value.filter(k => k.selected && k.word.trim()).map(k => k.word.trim())
      if (picked.length) {
        const cur = productLibrary.items.find(i => i.id === productId.value)
        const merged = Array.from(new Set([...(cur?.keywords || []), ...picked]))
        await productLibrary.updateItem(productId.value, { keywords: merged })
      }
    } catch (e: any) {
      console.error('[ListingDraft] 保存到产品库失败', e)
      return { ok: false, msg: `保存失败：${e?.message || '未知错误'}` }
    }
    return { ok: true, msg: `已保存到「${productName.value || productId.value}」` }
  }

  // ====== 清空 ======
  function reset() {
    productId.value = ''
    productName.value = ''
    brand.value = ''
    sellingPoints.value = ''
    category.value = ''
    site.value = 'com'
    sourceMode.value = 'manual'
    asin.value = ''
    variationValue.value = ''
    keywords.value = []
    title.value = ''
    titleVariants.value = []
    bullets.value = []
    aplusModules.value = []
    seoChecks.value = []
    seoScore.value = null
    globalInstruction.value = ''
    keywordPrompt.value = ''
    titlePrompt.value = ''
    bulletPrompt.value = ''
    aplusPrompt.value = ''
  }

  return {
    // state
    productId, productName, brand, sellingPoints, category, site, sourceMode,
    asin, variationValue,
    keywords, title, titleVariants, bullets, aplusModules, seoChecks, seoScore,
    globalInstruction, keywordPrompt, titlePrompt, bulletPrompt, aplusPrompt,
    // computed
    moduleFilled, filledCount,
    // actions
    loadFromProduct, setKeywords, addKeyword, removeKeyword,
    setTitle, setBullets, addBullet, removeBullet,
    setAPlus, addAPlusModule, removeAPlusModule,
    setSeo, saveToProduct, reset, resolvePrompt,
  }
})
