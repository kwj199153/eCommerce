/**
 * `blueOceanSecondary.ts` —— 从 `BlueOceanResult.vue` 外移的悬浮次要指标逻辑（r371h）
 * ==============================================================================
 * 外移的直接原因是宿主撞了体量棘轮 R2（见该模块文件头）。但外移带来的**副产物**
 * 是这些逻辑第一次变成**可直接断言的纯函数** —— 本文件就是把它用起来：
 * 外移而不补测，等于「搬了个地方继续没人守」。
 *
 * 钉住三件行为等价性（宿主重构前后必须一致）：
 *   1. 四项的**顺序**（界面靠它排版）；
 *   2. 缺字段**不编造**（`-` 而不是 `0` —— `0` 是合法观测值，不能当「没数据」的替身）；
 *   3. 变体阈值与评分配色档位的**闭区间边界**。
 */

import { describe, expect, it } from 'vitest'
import {
  ratingClass,
  secondaryMetrics,
  type SecondaryItem,
} from '@/components/ChatPanel/results/blueOceanSecondary'

/** 把返回项按 label 摊平，便于按语义断言（不依赖数组下标） */
function byLabel(record: any): Record<string, SecondaryItem> {
  return Object.fromEntries(secondaryMetrics(record).map((it) => [it.label, it]))
}

describe('ratingClass —— 综合评分跳色（星级 / 蓝海分通用）', () => {
  it('4.2 是 good 的闭区间下界', () => {
    expect(ratingClass(4.2)).toBe('good')
    expect(ratingClass(5)).toBe('good')
  })

  it('刚好低于 4.2 就掉出 good', () => {
    expect(ratingClass(4.19)).toBe('')
  })

  it('3.8 ~ 4.19 是中性档（空类名，不是 good 也不是 warn）', () => {
    expect(ratingClass(3.8)).toBe('')
    expect(ratingClass(4.0)).toBe('')
  })

  it('刚好低于 3.8 进 warn', () => {
    expect(ratingClass(3.79)).toBe('warn')
  })

  it('★ 0 分是 warn，不是 good —— 0 是合法观测值', () => {
    expect(ratingClass(0)).toBe('warn')
  })
})

describe('secondaryMetrics —— 四项顺序与取值', () => {
  it('★ 顺序固定为 星级 / 变体 / BSR / 评论（界面按此排版）', () => {
    expect(secondaryMetrics({}).map((it) => it.label)).toEqual(['星级', '变体', 'BSR', '评论'])
  })

  it('★ 不含「类目」—— 那一项由宿主渲染（见 blueOceanSecondary.ts 文件头）', () => {
    expect(secondaryMetrics({}).some((it) => it.label === '类目')).toBe(false)
  })

  it('★ 缺字段一律给「-」，不编造 0（0 会被界面读成「真实读数」）', () => {
    const m = byLabel({})
    expect(m['星级'].value).toBe('★ -')
    expect(m['BSR'].value).toBe('#-')
    expect(m['评论'].value).toBe('-')
  })

  it('★ 变体缺字段默认 1 个（不是 0 个）', () => {
    expect(byLabel({})['变体'].value).toBe('1 个')
  })

  it('有值时走千分位（期望值现算，不手写 —— 与实现同口径）', () => {
    const m = byLabel({ rating: 4.5, bsr_rank: 1234, review_count: 5678 })
    expect(m['星级'].value).toBe('★ 4.5')
    expect(m['BSR'].value).toBe(`#${(1234).toLocaleString()}`)
    expect(m['评论'].value).toBe((5678).toLocaleString())
  })

  it('评分配色接到对应项上（cls 出现在「星级」一项）', () => {
    expect(byLabel({ rating: 4.5 })['星级'].cls).toBe('good')
    expect(byLabel({ rating: 3.0 })['星级'].cls).toBe('warn')
  })

  it('变体数 <= 3 走 variation-few，>= 4 走 variation-many', () => {
    expect(byLabel({ variation_count: 3 })['变体'].cls).toBe('variation-few')
    expect(byLabel({ variation_count: 4 })['变体'].cls).toBe('variation-many')
  })

  it('BSR / 评论不挂 cls（无配色语义）', () => {
    const m = byLabel({ bsr_rank: 100, review_count: 9 })
    expect(m['BSR'].cls).toBeUndefined()
    expect(m['评论'].cls).toBeUndefined()
  })

  it('★ 返回的是新数组：调用方 push 不会污染下一次调用', () => {
    const a = secondaryMetrics({})
    a.push({ label: '污染', value: 'x' })
    expect(secondaryMetrics({}).length).toBe(4)
  })
})
