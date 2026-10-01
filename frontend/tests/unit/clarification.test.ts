/**
 * `utils/clarification.ts` 行为契约（第 356 轮 · 前端单测第二批）
 * ============================================================================
 * 为什么挑它：这个模块的 docstring 里记着**两条真实的界面事故**，而两条
 * 修复都只体现为「一段文案 / 一个正则」，**没有任何东西拦着它被改回去**：
 *
 *   ① 事故一：后端 LLM 自己编字段名（`missing_fields` 没有枚举约束），
 *      编出过 `review_count` ⇒ 表里没有 ⇒ 界面显示一句裸的
 *      「请补充「review_count」的信息」（老板实测收到过）。
 *      ⇒ 修法是补 `ALIASES` + `FIELD_QUESTIONS`（**数据表**，容易被顺手删）。
 *
 *   ② 事故二：`intent` 恰好是动作代号 `add` 时，`extractProductName` 把它
 *      当产品名 ⇒ 渲染出「好的，**add** 这事儿我接住了」（老板发的是商品链接）。
 *      ⇒ 修法是 `isDegenerateIntent` 那一条保守正则（**删掉即静默复发**）。
 *
 *   ③ 未识别字段的文案改成了**陈述式**（`X：这项还没给我`）而不是祈使句
 *      （`请补充「X」的信息`）—— 因为这条路径的提问其实是**前端模板**生成的
 *      （子 Agent 压根没跑），祈使句会让「模板冒充 Agent」。改回祈使句
 *      不会红任何既有门禁。
 *
 * ⇒ 本文件把这三条变成断言。它们防的都是**静默退化**：不抛错、不红门禁，
 *   只是老板某天又收到一条荒谬文案。
 */
import { describe, it, expect } from 'vitest'
import { extractProductName, isDegenerateIntent, renderClarification } from '@/utils/clarification'

describe('clarification · extractProductName（正则剥壳，易漂移）', () => {
  // ★ 这些是文件 docstring **明写的期望**（不是我从实现反推的）——
  //   实跑若不符，说明文档与实现已经不一致，那本身就是要报的问题。
  it.each([
    ['帮我生成一张水壶的白底图', '水壶'],
    ['生成保温杯的详情页', '保温杯'],
    ['为电饭煲做主图', '电饭煲'],
    ['想给保温杯生成 A+ 内容', '保温杯'],
    ['做个瑜伽垫的场景图', '瑜伽垫'],
  ])('「%s」⇒「%s」', (intent, want) => {
    expect(extractProductName(intent)).toBe(want)
  })

  it('空串 / undefined ⇒ undefined（不返回空串，调用方据此判「没提取到」）', () => {
    expect(extractProductName('')).toBeUndefined()
    // @ts-expect-error 故意传 undefined：签名是 string，但运行时入参可能来自可选字段
    expect(extractProductName(undefined)).toBeUndefined()
  })

  it('纯噪声句（剥完什么都不剩）⇒ undefined', () => {
    expect(extractProductName('帮我生成一个')).toBeUndefined()
  })
})

describe('clarification · isDegenerateIntent（★ 实测事故的守卫）', () => {
  it('★★ 纯 ASCII 动作代号 ⇒ true —— 这条防的是「好的，add 这事儿我接住了」', () => {
    // 删掉 `isDegenerateIntent` 的调用（在 handleSecretaryHandoff 那侧）或把
    // 正则放宽，这条会红。它是老板实测收到荒谬文案之后补的。
    expect(isDegenerateIntent('add')).toBe(true)
    expect(isDegenerateIntent('generate')).toBe(true)
    expect(isDegenerateIntent('save')).toBe(true)
  })

  it('带下划线 / 点 / 连字符的代号也算退化（`^[A-Za-z][A-Za-z0-9_.-]*$`）', () => {
    expect(isDegenerateIntent('add_item')).toBe(true)
    expect(isDegenerateIntent('v1.2.3')).toBe(true)
    expect(isDegenerateIntent('a-b-c')).toBe(true)
  })

  it('空 / 空白 / undefined ⇒ true（视同退化，不拿它做产品名）', () => {
    expect(isDegenerateIntent('')).toBe(true)
    expect(isDegenerateIntent('   ')).toBe(true)
    expect(isDegenerateIntent(undefined)).toBe(true)
  })

  it('★ 带空格的英文短语 ⇒ false（`water bottle` 是合法产品名，不能被误伤）', () => {
    expect(isDegenerateIntent('water bottle')).toBe(false)
    expect(isDegenerateIntent('My Product')).toBe(false)
  })

  it('★ 中文产品名 ⇒ false', () => {
    expect(isDegenerateIntent('水壶')).toBe(false)
    expect(isDegenerateIntent('保温杯')).toBe(false)
  })

  it('★ 长度边界：≤24 且纯 ASCII ⇒ true；25 及以上 ⇒ false（长串更可能是句子）', () => {
    expect(isDegenerateIntent('a'.repeat(24))).toBe(true)
    expect(isDegenerateIntent('a'.repeat(25))).toBe(false)
  })
})

describe('clarification · renderClarification 的字段识别（★ 防「裸字段名」事故）', () => {
  it('★ 中文标签经 ALIASES 归一到模板（事故一的修法就是补这张表）', () => {
    const { questions } = renderClarification({ fields: ['材质'], productName: '水壶' })
    expect(questions).toHaveLength(1)
    expect(questions[0].key).toBe('material')
    expect(questions[0].label).toBe('材质')
    expect(questions[0].question).toBe('水壶是什么材质的？')
  })

  it('英文 key 直通', () => {
    const { questions } = renderClarification({ fields: ['material'], productName: '水壶' })
    expect(questions[0].question).toBe('水壶是什么材质的？')
  })

  it('大小写混写也能命中（`ALIASES[trimmed.toLowerCase()]` 那一路）', () => {
    const { questions } = renderClarification({ fields: ['MATERIAL'], productName: '水壶' })
    expect(questions[0].key).toBe('material')
  })

  it('★ LLM 编出来的商品分析字段有模板（`review_count` 曾是那条裸文案的元凶）', () => {
    const { questions } = renderClarification({ fields: ['review_count', 'asin', 'rating'] })
    for (const q of questions) expect(q.question).not.toContain('这项还没给我')
    expect(questions.find((q) => q.key === 'review_count')?.label).toBe('评论数')
  })

  it('同义中文标签也能兜住（售价 / 价格 都归 price）', () => {
    expect(renderClarification({ fields: ['售价'] }).questions[0].key).toBe('price')
    expect(renderClarification({ fields: ['价格'] }).questions[0].key).toBe('price')
  })

  it('★ 同一字段多形态出现 ⇒ 只出一条（去重按归一后的 key）', () => {
    // '材质' / 'material' / 'MATERIAL' 三种写法归一后都是 material
    const { questions } = renderClarification({ fields: ['材质', 'material', 'MATERIAL'] })
    expect(questions).toHaveLength(1)
  })

  it('★★ 未识别字段用**陈述式**文案，不是祈使句（防「前端模板冒充 Agent」）', () => {
    const { questions } = renderClarification({ fields: ['totally_unknown'] })
    expect(questions[0].question).toBe('totally_unknown：这项还没给我')
    // 改回旧文案「请补充「X」的信息」会让下面两条红
    expect(questions[0].question).not.toContain('请补充')
    expect(questions[0].question).not.toContain('请')
  })

  it('未识别字段同时走 key 与 label（结果卡据此显示）', () => {
    const { questions } = renderClarification({ fields: ['神秘字段'] })
    expect(questions[0].key).toBe('神秘字段')
    expect(questions[0].label).toBe('神秘字段')
  })

  it('模板自带 examples 会透传（界面用它们做口语化示例）', () => {
    const { questions } = renderClarification({ fields: ['material'] })
    expect(questions[0].examples).toContain('不锈钢')
  })

  it('空白项被跳过（后端字段数组里可能有空串）', () => {
    expect(renderClarification({ fields: ['', '  ', 'material'] }).questions).toHaveLength(1)
  })

  it('fields 整个缺省 ⇒ 不抛错，questions 为空', () => {
    expect(renderClarification({} as never).questions).toEqual([])
  })
})

describe('clarification · renderClarification 的招呼语（三分支）', () => {
  it('没有要追问的字段 ⇒ 「我准备好了」那一支', () => {
    const { greeting } = renderClarification({ fields: [] })
    expect(greeting).toContain('我准备好了')
  })

  it('★ 有产品名 ⇒ 招呼语里加粗产品名（个性化）', () => {
    const { greeting } = renderClarification({ fields: ['material'], productName: '水壶' })
    expect(greeting).toContain('**水壶**')
  })

  it('★ 没给产品名 ⇒ 退回中性招呼语，且问题里用「这个产品」而不是空', () => {
    const { greeting, questions } = renderClarification({ fields: ['material'] })
    expect(greeting).toContain('好嘞')
    expect(questions[0].question).toBe('这个产品是什么材质的？')
  })

  it('★ 产品名恰好是占位符本身 ⇒ 走中性分支（不出现「**这个产品**」加粗）', () => {
    const { greeting } = renderClarification({ fields: ['material'], productName: '这个产品' })
    expect(greeting).toContain('好嘞')
  })
})
