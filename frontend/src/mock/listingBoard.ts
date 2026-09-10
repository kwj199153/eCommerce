/**
 * Listing 统一工作区 —— 生成用 mock 数据
 *
 * 与 reviewDashboard.ts 同类定位：为「Listing 面板」提供一次性可生成的完整文案，
 * 所有内容基于同一个产品名/卖点推导，保证关键词→标题→五点→A+ 之间自洽。
 * 接入真实 LLM 后，由后端返回同结构数据即可零改动替换。
 */

export interface BoardGenContext {
  productName: string
  brand: string
  sellingPoints: string
  category: string
  site: string
}

// ====== 关键词模块 ======
export function genKeywords(ctx: BoardGenContext) {
  const base = ctx.productName || 'Portable Coffee Grinder'
  const words = base.split(/\s+/).filter(Boolean)
  const core = words.slice(0, 3).join(' ').toLowerCase() || 'portable coffee grinder'
  const rows = [
    { word: core, search_volume: 45200, competition: 'high', relevance: 96 },
    { word: `${core} for travel`, search_volume: 18400, competition: 'medium', relevance: 92 },
    { word: `manual ${core}`, search_volume: 32100, competition: 'medium', relevance: 90 },
    { word: `${core} with ceramic burr`, search_volume: 12600, competition: 'low', relevance: 88 },
    { word: `hand ${core}`, search_volume: 21800, competition: 'medium', relevance: 86 },
    { word: `${core} adjustable coarseness`, search_volume: 9400, competition: 'low', relevance: 84 },
    { word: `compact ${core}`, search_volume: 7600, competition: 'low', relevance: 80 },
    { word: `${core} gift set`, search_volume: 5200, competition: 'low', relevance: 74 },
  ]
  // 用户填的核心卖点拆词补齐长尾
  const extra = (ctx.sellingPoints || '')
    .split(/[|，,、\n]/)
    .map(s => s.trim())
    .filter(Boolean)
    .slice(0, 4)
    .map((s, i) => ({
      word: `${core} ${s.toLowerCase()}`,
      search_volume: 3800 - i * 400,
      competition: 'low' as const,
      relevance: 72 - i * 2,
    }))
  const all = [...rows, ...extra] as Array<{ word: string; search_volume: number; competition: 'high' | 'medium' | 'low'; relevance: number }>
  return all.map(r => ({ ...r, selected: r.relevance >= 80 }))
}

// ====== 标题模块 ======
export function genTitle(ctx: BoardGenContext) {
  const name = ctx.productName || 'Portable Coffee Grinder'
  const brand = ctx.brand || 'BrewMaster'
  const main = [
    `${name} with Ceramic Burrs`,
    'Manual Hand Coffee Bean Grinder Adjustable Coarseness',
    'Portable Compact for Travel Camping Office Home Kitchen',
  ].join(', ')
  const variants = [
    `Premium ${name}, Stainless Steel Manual Coffee Grinder with Conical Burr Mill, Quiet Operation & Easy Clean`,
    `${name} Professional, Hand Crank Coffee Mill with Precision Engineering, No Battery Needed, Eco-Friendly`,
    `Manual ${name} Portable Mini, Ceramic Burr Coffee Bean Grinder Fine to Coarse Setting, Travel-Friendly`,
    `${name} with Brush & Storage Bag, Ergonomic Hand Coffee Grinder Anti-Slip Base, Gift Box Included`,
  ]
  return { main: (brand ? `${brand} ` : '') + main, variants }
}

// ====== 五点模块 ======
export function genBullets(ctx: BoardGenContext) {
  const name = ctx.productName || 'Coffee Grinder'
  return [
    {
      title: 'PREMIUM CERAMIC BURRS',
      content: `${name} features high-density ceramic conical burrs that deliver consistent grind size every time. Unlike metal burrs that overheat and alter flavor, our ceramic burrs stay cool, preserving essential oils and aroma for a richer taste.`,
    },
    {
      title: 'ADJUSTABLE COARSENESS SETTINGS',
      content: 'Customize your grind from ultra-fine for espresso to coarse for French press with 15+ precision settings. The intuitive dial mechanism lets you find the perfect texture for ANY brewing method — AeroPress, pour-over, drip or cold brew.',
    },
    {
      title: 'PORTABLE & TRAVEL-FRIENDLY',
      content: 'Compact size (5.2 x 3.1 inches) fits perfectly in your backpack or suitcase. No batteries, no cords — just pure manual grinding anywhere you go. Ideal for camping, hiking, office use or small kitchens.',
    },
    {
      title: 'BUILT TO LAST',
      content: 'Crafted from food-grade 304 stainless steel with a reinforced ergonomic handle. The transparent chamber holds up to 40g of beans (4 cups), and the anti-slip silicone base keeps it stable. Backed by a 5-year warranty.',
    },
    {
      title: 'COMPLETE PACKAGE',
      content: 'Includes a cleaning brush, storage pouch and user manual. 24/7 customer support, presented in premium gift-ready packaging — an excellent gift for coffee lovers.',
    },
  ]
}

// ====== A+ 描述模块 ======
export function genAPlus(ctx: BoardGenContext) {
  const name = ctx.productName || 'Coffee Grinder'
  const brand = ctx.brand || 'BrewMaster'
  return [
    {
      type: 'text' as const,
      heading: `Why Choose ${brand} ${name}?`,
      content: `Every cup starts with the grind. ${name} pairs a precision ceramic burr set with a compact, cord-free body, so you get café-level consistency at home, in the office or on the trail.`,
    },
    {
      type: 'highlights' as const,
      heading: 'Key Features at a Glance',
      items: [
        { title: '15+ Grind Settings', desc: 'Espresso-fine to French press-coarse, dialed in seconds.' },
        { title: 'Ceramic Conical Burrs', desc: 'Cool grinding preserves aroma; lasts 5x longer than blades.' },
        { title: '40g Capacity', desc: 'Grinds up to 4 cups in one fill — no repeated batches.' },
        { title: 'Travel-Ready', desc: '5.2 x 3.1 in, no batteries, includes pouch and brush.' },
      ],
    },
    {
      type: 'image-text' as const,
      heading: 'Designed for Real Kitchens',
      paragraphs: [
        'Top-fill hopper and a transparent chamber make it easy to see exactly how much you have ground.',
        'The anti-slip silicone base keeps the grinder planted on smooth counters during use.',
        'Detachable parts rinse clean in seconds — no hidden corners for old grounds to hide.',
      ],
    },
    {
      type: 'text' as const,
      heading: 'What’s in the Box',
      content: `1 × ${name} · 1 × Cleaning Brush · 1 × Storage Pouch · 1 × User Manual · ${brand} 5-Year Warranty`,
    },
  ]
}

// ====== SEO 诊断模块 ======
export function genSeo(ctx: BoardGenContext) {
  const name = ctx.productName || 'the product'
  return {
    score: 78,
    checks: [
      {
        category: '标题优化',
        score: 84,
        status: 'good' as const,
        issues: ['核心词已前置，品牌名位于开头', '长度 168 字符，处于 150-200 推荐区间'],
        suggestions: ['把最高搜索量词再往前挪 1-2 个位置', '避免同义词重复出现两次以上'],
      },
      {
        category: '五点描述',
        score: 86,
        status: 'good' as const,
        issues: ['5 条均已用【大写关键词】开头', '数字量化卖点充分（15+ settings / 40g / 5-year）'],
        suggestions: ['第 3 条可再补一个使用场景词（camping / office）', '控制在 250 字符内以免移动端截断'],
      },
      {
        category: '搜索词覆盖率',
        score: 68,
        status: 'warning' as const,
        issues: [`${name} 的长尾词覆盖 14/25`, '缺少「gift / travel」场景词'],
        suggestions: ['在后台 Search Terms 补齐未覆盖的长尾词', '在 A+ 正文中自然植入 3-5 个高频词'],
      },
      {
        category: 'A+ Content',
        score: 80,
        status: 'good' as const,
        issues: ['模块结构完整（亮点 / 图文 / 参数）', '缺少对比表格'],
        suggestions: ['增加一张与竞品的对比表，突出差异化', '补充尺寸/材质规格参数表'],
      },
      {
        category: '图片与转化',
        score: 72,
        status: 'warning' as const,
        issues: ['主图为白底，符合规范', '缺少场景图与细节特写图'],
        suggestions: ['补充 2 张使用场景图（卧室/办公室）', '增加一张剖视图展示磨芯结构'],
      },
    ],
  }
}

/** 一次性生成全部模块（面板「一键生成全部」使用） */
export function genAll(ctx: BoardGenContext) {
  return {
    keywords: genKeywords(ctx),
    title: genTitle(ctx),
    bullets: genBullets(ctx),
    aplus: genAPlus(ctx),
    seo: genSeo(ctx),
  }
}
