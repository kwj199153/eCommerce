/**
 * 方向徽标（两条浮层共用）单元测试
 * =================================
 * `formatBadge` 是**唯一**一份方向文案实现，划词浮层从这里取（第 367 轮截屏浮层退场）。
 * 之所以单独钉住它：这条规则第 365 轮才增了「含外文 → X」一档，
 * 而它一旦在两个浮层各写一份，漂移的症状是「同一个后端结果，两个浮层显示不一样的方向」。
 */

import { describe, expect, it } from 'vitest'
import { LANG_LABEL, formatBadge } from '@/components/Translate/langBadge'

const base = {
  loading: false,
  loadingText: '翻译中',
  error: '',
  hasOriginal: true,
  sameLang: false,
  sourceLang: 'en',
  targetLang: 'zh',
}

describe('formatBadge —— 方向徽标只有一份实现', () => {
  it('正常方向：英文 → 中文', () => {
    expect(formatBadge(base)).toBe('英文 → 中文')
  })

  it('★ same_lang ⇒「已是中文」，不是失败、也不是「中文 → 中文」', () => {
    expect(formatBadge({ ...base, sameLang: true, sourceLang: 'zh', targetLang: 'zh' })).toBe(
      '已是中文',
    )
  })

  it('★ 源与目标同名但**确实翻了**（文本里夹了外文词）⇒ 不显示自相矛盾的「中文 → 中文」', () => {
    expect(formatBadge({ ...base, sourceLang: 'zh', targetLang: 'zh' })).toBe('含外文 → 中文')
  })

  it('加载中的文案由调用方给（划词是「翻译中」）', () => {
    expect(formatBadge({ ...base, loading: true, loadingText: '识别中' })).toBe('识别中')
  })

  it('有原文时出错 = 翻译失败', () => {
    expect(formatBadge({ ...base, error: 'boom' })).toBe('翻译失败')
  })

  it('没原文时出错用调用方文案（由调用方给 emptyText）', () => {
    expect(formatBadge({ ...base, error: 'boom', hasOriginal: false, emptyText: '没认到文字' })).toBe(
      '没认到文字',
    )
  })

  it('未收录的语言码不至于开天窗（源侧退回「原文」，目标侧原样显示）', () => {
    expect(formatBadge({ ...base, targetLang: 'xx' })).toBe('英文 → xx')
    expect(formatBadge({ ...base, sourceLang: 'xx', targetLang: 'zh' })).toBe('原文 → 中文')
  })

  it('label 表覆盖后端会回的语种', () => {
    for (const k of ['zh', 'en', 'ja', 'ko', 'de', 'es', 'fr', 'it', 'pt']) {
      expect(LANG_LABEL[k], k).toBeTruthy()
    }
  })
})
