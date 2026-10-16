/**
 * 悬停翻译 · 判定规则（第 370 轮 P1）
 * ============================================================================
 * 为什么这个文件是**纯函数测试**而不是 DOM 测试：
 * 悬停的触发条件有 7 条，全在 `decideHover` 里。判定抽成纯叶子之后，
 * 这 7 条可以在 `environment: 'node'` 下**逐条零成本钉住** ——
 * 而如果判定写在 `onMouseOver` 里，就只能靠「造 DOM 桩 + 移鼠标」来间接验，
 * 验得了「接没接上」，验不了「哪种文本该弹」。
 *
 * ★ 本文件刻意钉住的两条**容易被改错**的设计决定：
 *   ① 「只对含拉丁字母的文本出手」**不得**被加固成「且不含 CJK」——
 *      那道判据对纯中文恒不做功（已被 LATIN 挡掉），却会误杀中英混排
 *      （`Noise Cancelling 主动降噪` 这类真实商品标题）⇒ 负资产。
 *   ② 长度上限是 **200** 而不是划词的 2000，两者**不许合并成一个常量**。
 */
import { describe, it, expect } from 'vitest'
import { HOVER_DELAY_MS, MAX_HOVER_CHARS, decideHover } from '@/utils/hoverTranslate'

/** 全部条件都满足的基线（每条用例只改它关心的那一项） */
const base = {
  text: 'Noise Cancelling Headphones',
  isTextBlock: true,
  insideLayer: false,
  insideEditable: false,
  hasSelection: false,
}

const decide = (over: Record<string, unknown> = {}) => decideHover({ ...base, ...over })
/** 只取拒绝原因（通过时返回 null），让断言读起来是「因为什么被拒」 */
const reasonOf = (over: Record<string, unknown> = {}) => {
  const d = decide(over)
  return d.ok ? null : d.reason
}

describe('悬停翻译 · 两个常量', () => {
  it('停留阈值在一个「不打扰也不迟钝」的区间（改到 5 秒 = 没反应；改到 0 = 满屏乱弹）', () => {
    expect(HOVER_DELAY_MS).toBeGreaterThanOrEqual(200)
    expect(HOVER_DELAY_MS).toBeLessThanOrEqual(800)
  })

  it(`上限是 ${MAX_HOVER_CHARS}，且**必须小于**划词的 2000 —— 两个数不许合并`, () => {
    expect(MAX_HOVER_CHARS).toBe(200)
    // ★ 合并那天，要么划词被砍到 200（大量正常选区被拒），
    //   要么悬停放到 2000（在容器上悬停会翻出一整段）
    expect(MAX_HOVER_CHARS).toBeLessThan(2000)
  })
})

describe('悬停翻译 · 放行的一条', () => {
  it('含拉丁字母的文本块 ⇒ 放行，且返回归一化后的文本', () => {
    const d = decide()
    expect(d.ok).toBe(true)
    if (d.ok) expect(d.text).toBe('Noise Cancelling Headphones')
  })
})

describe('悬停翻译 · 三条结构性排除（与「文本是什么」无关）', () => {
  it('找不到合适的文本块 ⇒ no-block', () => {
    expect(reasonOf({ isTextBlock: false })).toBe('no-block')
  })

  it('事件发生在浮层内部 ⇒ inside-layer（否则鼠标移到译文上就再弹一层）', () => {
    expect(reasonOf({ insideLayer: true })).toBe('inside-layer')
  })

  it('事件发生在可编辑元素内 ⇒ inside-editable（悬停翻译会和打字打架）', () => {
    expect(reasonOf({ insideEditable: true })).toBe('inside-editable')
  })

  it('★ 已有选区 ⇒ has-selection（用户已经用划词那条路拿到浮层了，别再打扰）', () => {
    expect(reasonOf({ hasSelection: true })).toBe('has-selection')
  })

  it('结构性排除**优先于**文本判据 —— reason 必须指向首要原因，否则调试时误导', () => {
    // 同时「有选区」且「文本是纯中文」：应先报 has-selection
    expect(reasonOf({ hasSelection: true, text: '保温杯' })).toBe('has-selection')
    // 同时「在浮层内」且「文本为空」：应先报 inside-layer
    expect(reasonOf({ insideLayer: true, text: '   ' })).toBe('inside-layer')
  })
})

describe('悬停翻译 · 文本本身的判据', () => {
  it('空 / 纯空白 ⇒ empty', () => {
    expect(reasonOf({ text: '' })).toBe('empty')
    expect(reasonOf({ text: '   \n\t ' })).toBe('empty')
  })

  it('超过上限 ⇒ too-long', () => {
    expect(reasonOf({ text: 'a'.repeat(MAX_HOVER_CHARS + 1) })).toBe('too-long')
  })

  it(`★ 恰好 ${MAX_HOVER_CHARS} 字 ⇒ 放行（边界是 > 上限才拦，别写成 >=）`, () => {
    expect(reasonOf({ text: 'a'.repeat(MAX_HOVER_CHARS) })).toBeNull()
  })

  it('不含拉丁字母 ⇒ no-latin（纯中文 / 日文 / 韩文 / 数字 / 标点都走这条）', () => {
    expect(reasonOf({ text: '这款保温杯的容量是多少' })).toBe('no-latin')
    expect(reasonOf({ text: 'ノイズキャンセリングヘッドホン' })).toBe('no-latin')
    expect(reasonOf({ text: '노이즈 캔슬링 헤드폰' })).toBe('no-latin')
    expect(reasonOf({ text: '12345 —— ！？' })).toBe('no-latin')
  })

  it('★ 中英混排 ⇒ 放行（这是「刻意不加『不得含 CJK』第二道」的理由）', () => {
    // 加了那道判据，这条真实商品标题形态会被误杀 —— 而它恰恰最需要翻译
    expect(reasonOf({ text: 'SONY WH-1000XM5 主动降噪耳机' })).toBeNull()
    expect(reasonOf({ text: 'Noise Cancelling 主动降噪' })).toBeNull()
  })
})

describe('悬停翻译 · 空白归一化', () => {
  it('把换行 / 连续空格压成单空格，并去掉首尾', () => {
    const d = decide({ text: '  Noise\n  Cancelling\tHeadphones \n' })
    expect(d.ok).toBe(true)
    if (d.ok) expect(d.text).toBe('Noise Cancelling Headphones')
  })

  it('★ 长度按**归一化后**算：压掉空白可能把一个超长块救回来', () => {
    // 原始 200 个 'a' + 1 空格 + 100 个空格 + 'a'；归一化后 = 200 个 a + 空格 + a = 202 > 200
    const raw = 'a'.repeat(200) + ' ' + '  '.repeat(50) + 'a'
    expect(reasonOf({ text: raw })).toBe('too-long')
    // 而 198 个 a + 三个空格 + a：归一化后 = 198 + 1 + 1 = 恰好 200 ⇒ 放行
    // （199 个就不行了：归一化后是 201。这条边界是实测的，不是手算的。）
    const raw2 = 'a'.repeat(198) + '   ' + 'a'
    expect(reasonOf({ text: raw2 })).toBeNull()
  })
})
