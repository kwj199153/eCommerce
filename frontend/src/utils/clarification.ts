/**
 * 字段-问答口语化映射
 *
 * 用途：主 Agent 交接 / 工具缺参返回 missing_fields 时，把后端传来的字段
 *      标签（material / "材质" 等）转成用户能直接看懂的提问。
 *
 * 设计：
 * - 后端返回的是 label（中文）或 key（英文），由 LLM 自由生成 → 兜底都做映射
 * - 每个字段有 question 模板（带 {product} 占位可注入产品名）+ examples 给口语化示例
 * - 未在表里的字段原样透传（保持优雅降级，不硬塞提问模板）
 */

export interface ClarificationItem {
  /** 字段 key（如 material / view_angle） */
  key: string
  /** 字段中文标签（如 材质、视角） */
  label: string
  /** 口语化提问（如「水壶什么材质？」） */
  question: string
  /** 给用户的可选示例（口语化短句） */
  examples?: string[]
}

export interface RenderInput {
  /** 字段 key 或中文标签（兼容后端两种形态） */
  fields: string[]
  /** 产品名（从 intent 提取，用于把提问个性化，例如「水壶什么材质？」） */
  productName?: string
}

/** key/中文 → 完整问答模板 */
const FIELD_QUESTIONS: Record<string, { label: string; question: string; examples?: string[] }> = {
  // —— AIGC 生图追问字段 ——
  material: {
    label: '材质',
    question: '{product}是什么材质的？',
    examples: ['不锈钢', '玻璃', '陶瓷', '食品级塑料', '实木'],
  },
  shape: {
    label: '造型',
    question: '{product}是什么造型？',
    examples: ['圆柱形', '方形', '流线型', '经典款', 'mini 小巧款'],
  },
  view_angle: {
    label: '视角',
    question: '{product}想拍哪个角度？',
    examples: ['正面平铺', '45 度斜拍', '俯视', '三视图', '侧面剪影'],
  },
  need_logo: {
    label: '是否需要 logo',
    question: '{product}图片里要不要带上品牌 logo？',
    examples: ['需要', '不用', '可以小一点放在角落'],
  },
  product_detail: {
    label: '产品细节',
    question: '{product}有哪些要重点突出的卖点或细节？',
    examples: ['保温 12 小时', '一键开盖', '防漏设计', '食品级材质'],
  },
  background_rule: {
    label: '背景规则',
    question: '{product}图片背景怎么安排？',
    examples: ['纯白底', '白底但允许柔光阴影', '场景图：厨房台面', '渐变灰'],
  },
  // —— 选品 / 商品分析追问字段（★ 第 215 轮补）——
  //   为什么必须补：这些字段名是**后端 LLM 自己编**的（`handoff_to_agent` 的
  //   missing_fields 没有枚举约束），实测编出过 asin / title / price /
  //   review_count / rating / category。表里没有就落到「未识别字段」兜底，
  //   老板看到一句裸的「请补充「review_count」的信息」（实测事故）。
  asin: {
    label: '商品 ASIN',
    question: '这个商品的 ASIN 是多少？',
    examples: ['商品页链接里 /dp/ 后面那串就是，如 B09V9TXTKK', '直接贴商品链接也行'],
  },
  title: {
    label: '商品标题',
    question: '{product}的商品标题是什么？',
    examples: ['把商品页上的标题整条贴过来'],
  },
  price: {
    label: '售价',
    question: '{product}现在卖多少钱？',
    examples: ['$29.99', '19.9 美元'],
  },
  review_count: {
    label: '评论数',
    question: '{product}大概有多少条评论？',
    examples: ['1200 条', '不多，几十条'],
  },
  rating: {
    label: '评分',
    question: '{product}的评分是多少？',
    examples: ['4.5', '4.2 星'],
  },
  category: {
    label: '类目',
    question: '{product}属于哪个类目？',
    examples: ['Kitchen & Dining', 'Sports & Outdoors'],
  },
  url: {
    label: '商品链接',
    question: '把{product}的商品页链接发我一下？',
    examples: ['https://www.amazon.com/dp/...'],
  },
  // —— Listing 文案追问字段（预留）——
  target_market: {
    label: '目标市场',
    question: '{product}主要卖到哪个市场？',
    examples: ['美国', '欧洲', '日本', '东南亚'],
  },
  target_audience: {
    label: '目标人群',
    question: '{product}主要卖给谁？',
    examples: ['25-35 岁女性', '新手妈妈', '健身爱好者', '送礼场景'],
  },
  keywords: {
    label: '核心关键词',
    question: '想重点打哪几个搜索词？',
    examples: ['water bottle', 'insulated', 'leak proof'],
  },
  brand: {
    label: '品牌名',
    question: '{product}是什么品牌？或者想用什么风格的品牌感？',
    examples: ['我的品牌叫 XXX', '没有品牌，走性价比路线', '走高端质感'],
  },
  tone: {
    label: '文案语气',
    question: '{product}文案想要什么调性？',
    examples: ['专业靠谱', '活泼有趣', '高端轻奢', '口语化'],
  },
}

/** 同义中英文别名 → 标准 key（兜底 LLM 输出中文标签或英文 key 都能识别） */
const ALIASES: Record<string, string> = {
  // 中文标签 → key
  材质: 'material',
  造型: 'shape',
  视角: 'view_angle',
  是否需要logo: 'need_logo',
  产品细节: 'product_detail',
  背景规则: 'background_rule',
  // 简化别名：长尾描述已在 label 里，不另起 alias（避免 TS 解析长字符串歧义）
  目标市场: 'target_market',
  目标人群: 'target_audience',
  核心关键词: 'keywords',
  品牌名: 'brand',
  文案语气: 'tone',
  // —— 选品 / 商品分析字段（★ 第 215 轮补；LLM 编出来的中文标签也兜住）——
  商品asin: 'asin',
  商品标题: 'title',
  标题: 'title',
  售价: 'price',
  价格: 'price',
  评论数: 'review_count',
  评价数: 'review_count',
  评分: 'rating',
  星级: 'rating',
  类目: 'category',
  分类: 'category',
  商品链接: 'url',
  链接: 'url',
  // 英文 key → key（直通）
  material: 'material',
  shape: 'shape',
  view_angle: 'view_angle',
  need_logo: 'need_logo',
  product_detail: 'product_detail',
  background_rule: 'background_rule',
  target_market: 'target_market',
  target_audience: 'target_audience',
  keywords: 'keywords',
  brand: 'brand',
  asin: 'asin',
  title: 'title',
  price: 'price',
  review_count: 'review_count',
  rating: 'rating',
  category: 'category',
  url: 'url',
  link: 'url',
  tone: 'tone',
}

/**
 * 从 intent（一句话意图描述）里提取产品名。
 *
 * 期望：
 *   - 「帮我生成一张水壶的白底图」→ 「水壶」
 *   - 「生成保温杯的详情页」→ 「保温杯」
 *   - 「为电饭煲做主图」→ 「电饭煲」
 *   - 「做一个 T 恤的信息图」→ 「T 恤」
 *   - 「想给保温杯生成 A+ 内容」→ 「保温杯」
 *   - 「做个瑜伽垫的场景图」→ 「瑜伽垫」
 *
 * 策略：循环剥（动词/量词/方位/任务类型），取首个 2-6 字中文/英文短语。
 */
export function extractProductName(intent: string): string | undefined {
  if (!intent) return undefined
  let s = intent.trim()

  const NOISE = [
    // 前缀（动词 + 介词）
    /^(帮我|我想|请|麻烦|麻烦你|给我|要|想|我要|能不能|麻烦帮|求|来一)/,
    // 量词/方位/的
    /^[(一张|一个|一款|那个|这个|那个|那|这)]/,
    /(一张|一个|一款|那个|这个|的|一下|吧|啊|呢)$/,
    // 动作
    /(生成|做|拍|画|设计|弄|出|搞)/g,
    // 任务类型（白底图/主图/A+）
    /(白底图|主图|场景图|信息图|视频|脚本|图片|A\+ ?内容|EBC|详情页|素材|文案|广告|对比图|包装图|尺码图|短片|缩略图|listing)/gi,
  ]

  // 反复剥直到不再变化（最坏 5 次）
  for (let i = 0; i < 5; i++) {
    const before = s
    for (const re of NOISE) s = s.replace(re, '')
    if (s === before) break
  }
  s = s.trim()

  // 取首个 2-6 字中文块 或 含空格的英文短语
  const m = s.match(/([一-龥]{2,6}|[A-Za-z][A-Za-z0-9 \-]{1,11})/)
  if (m && m[1]) {
    let cand = m[1].trim()
    // 兜底剥：候选里残留的介词/量词（"为电饭煲"→"电饭煲"，"给保温杯"→"保温杯"，"张水壶"→"水壶"）
    cand = cand.replace(/^(为|给|的|这|那|一|张|个|款|是|有)/, '')
    if (cand.length >= 2 && /[一-龥A-Za-z]/.test(cand)) return cand
  }
  return undefined
}

/**
 * `intent` 是不是「退化的意图标签」—— 例如后端只给了工具代号 `add`。
 *
 * ★ 为什么需要：`handleSecretaryHandoff` 会拿 intent 提取产品名去做个性化提问。
 *   当 intent 恰好是一个动作代号（`add` / `generate` / `save`）时，
 *   `extractProductName` 会把它当成产品名，渲染出「好的，**add** 这事儿我接住了」
 *   —— 实测老板就是这样收到一条荒谬文案的（他发的是商品链接）。
 * ★ 判据刻意保守：只挡「**纯 ASCII 字母构成、无空格、不带中文**」的短串。
 *   中文产品名 / 带空格的英文短语（`water bottle`）/ 完整句子一律照旧通过。
 */
export function isDegenerateIntent(intent?: string): boolean {
  if (!intent) return true
  const s = intent.trim()
  if (!s) return true
  if (s.length > 24) return false
  return /^[A-Za-z][A-Za-z0-9_.-]*$/.test(s)
}

/**
 * 渲染接管语 + 追问列表（口语化、含产品名）
 */
export function renderClarification(input: RenderInput): { greeting: string; questions: ClarificationItem[] } {
  const product = input.productName || '这个产品'
  const seen = new Set<string>()
  const questions: ClarificationItem[] = []

  for (const raw of input.fields || []) {
    const trimmed = (raw || '').trim()
    if (!trimmed) continue
    const key = ALIASES[trimmed] || ALIASES[trimmed.toLowerCase()] || trimmed
    if (seen.has(key)) continue
    seen.add(key)

    const tmpl = FIELD_QUESTIONS[key]
    if (tmpl) {
      questions.push({
        key,
        label: tmpl.label,
        question: tmpl.question.replace(/\{product\}/g, product),
        examples: tmpl.examples,
      })
    } else {
      // 未识别字段：原样展示。
      // ★ 第 215 轮改口吻：原文案是「请补充「X」的信息」—— 那是一句**像 Agent 在
      //   追问的祈使句**，而这条路径上的问题其实是**前端模板**生成的（子 Agent 压根
      //   没运行，见 useChatEventBridge 的 handleSecretaryHandoff）。改成陈述式，
      //   配合调用方的来源标注，避免"模板冒充 Agent"。
      questions.push({
        key: trimmed,
        label: trimmed,
        question: `${trimmed}：这项还没给我`,
      })
    }
  }

  // 招呼语（根据是否给到产品名/字段数微调）
  let greeting: string
  if (questions.length === 0) {
    greeting = `好的，我准备好了。${product}的需求我大致了解了，请告诉我你最想做的是什么。`
  } else if (product !== '这个产品') {
    greeting = `好的，**${product}** 这事儿我接住了。开干前再确认几件小事，你挑能说的告诉我，剩下的我自己补默认就行。`
  } else {
    greeting = `好嘞，需求我大致清楚了。开干前再确认几件小事，你挑能说的告诉我就行。`
  }

  return { greeting, questions }
}