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

export interface KeywordRow {
  id: string
  word: string
  search_volume: number
  competition: 'high' | 'medium' | 'low'
  relevance: number
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

    keywords.value = (p.keywords || []).map((w: string) => ({
      id: uid('kw'),
      word: w,
      search_volume: 0,
      competition: 'medium' as const,
      relevance: 80,
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
    if (Array.isArray(raw.sections)) {
      return raw.sections.map((s: any) => ({
        id: uid('ap'),
        type: 'text' as const,
        heading: s.heading || '',
        content: s.content || '',
      }))
    }
    return []
  }

  function normalizeModule(m: any): APlusModule {
    return {
      id: uid('ap'),
      type: m.type || 'text',
      heading: m.heading || '',
      content: m.content || '',
      paragraphs: m.paragraphs ? [...m.paragraphs] : undefined,
      items: m.items ? m.items.map((i: any) => ({ title: i.title || '', desc: i.desc || '' })) : undefined,
    }
  }

  // ====== 各模块写入（生成/编辑共用）======
  function setKeywords(rows: Array<Partial<KeywordRow>>) {
    keywords.value = rows.map(r => ({
      id: uid('kw'),
      word: r.word || '',
      search_volume: r.search_volume ?? 0,
      competition: (r.competition as any) || 'medium',
      relevance: r.relevance ?? 80,
      selected: r.selected ?? true,
    }))
  }

  function addKeyword(word = '') {
    keywords.value.push({
      id: uid('kw'),
      word,
      search_volume: 0,
      competition: 'low',
      relevance: 70,
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
  }

  return {
    // state
    productId, productName, brand, sellingPoints, category, site, sourceMode,
    asin, variationValue,
    keywords, title, titleVariants, bullets, aplusModules, seoChecks, seoScore,
    // computed
    moduleFilled, filledCount,
    // actions
    loadFromProduct, setKeywords, addKeyword, removeKeyword,
    setTitle, setBullets, addBullet, removeBullet,
    setAPlus, addAPlusModule, removeAPlusModule,
    setSeo, saveToProduct, reset,
  }
})
