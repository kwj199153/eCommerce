/**
 * `utils/platform.ts` 行为契约（第 355 轮 · #1282）
 * ============================================================================
 * 这个模块决定「Listing 优化师等工具展示哪些字段、按哪套 SEO 规则校验」，
 * 一旦判定错，界面会**静默**给出另一套平台的字段（不报错、不是空白）。
 * 两条最容易改歪、且改歪后没有任何门禁会吭声的点：
 *
 *   ① **前缀匹配而非包含匹配** —— `getPlatformMode` 用的是 `startsWith`。
 *      改成 `includes` 后，`'non_amazon'` 这类值会被判成亚马逊，
 *      而所有「正常值」的用例都还是绿的（所以这里专门配了判别性断言）。
 *   ② **空值兜底是「亚马逊」** —— 未绑定店铺时走完整亚马逊模式（含五点 / A+ / SEO）。
 *      这是刻意的产品决策，不是遗漏；但它意味着 `isAmazonMode(undefined) === true`。
 */
import { describe, it, expect } from 'vitest'
import {
  getPlatformLabel,
  getPlatformMode,
  isAmazonMode,
  isSimplifiedListingMode,
} from '@/utils/platform'

describe('platform · getPlatformMode 平台判定', () => {
  it('空值兜底为亚马逊（未绑定店铺时按完整亚马逊模式走）', () => {
    expect(getPlatformMode(undefined)).toBe('amazon')
    expect(getPlatformMode(null)).toBe('amazon')
    expect(getPlatformMode('')).toBe('amazon')
  })

  it('亚马逊全枚举（国家后缀）都归 amazon', () => {
    for (const p of ['amazon_us', 'amazon_uk', 'amazon_de', 'amazon_jp']) {
      expect(getPlatformMode(p), p).toBe('amazon')
    }
  })

  it('Shopee 全枚举都归 shopee', () => {
    for (const p of ['shopee_my', 'shopee_tw', 'shopee_ph', 'shopee_th', 'shopee_sg', 'shopee_vn', 'shopee_id', 'shopee_br']) {
      expect(getPlatformMode(p), p).toBe('shopee')
    }
  })

  it('Temu 全枚举都归 temu', () => {
    for (const p of ['temu', 'temu_us', 'temu_uk', 'temu_de']) {
      expect(getPlatformMode(p), p).toBe('temu')
    }
  })

  it('简写形态（不带国家后缀）同样能判定', () => {
    expect(getPlatformMode('amazon')).toBe('amazon')
    expect(getPlatformMode('shopee')).toBe('shopee')
    expect(getPlatformMode('temu')).toBe('temu')
  })

  it('大小写不敏感', () => {
    expect(getPlatformMode('Amazon_US')).toBe('amazon')
    expect(getPlatformMode('SHOPEE_MY')).toBe('shopee')
    expect(getPlatformMode('TeMu')).toBe('temu')
  })

  it('TikTok / Shopify 落到 other（不是 amazon）', () => {
    expect(getPlatformMode('tiktok')).toBe('other')
    expect(getPlatformMode('shopify')).toBe('other')
  })

  it('★ 前缀匹配：字符串**包含**但**不以**平台名开头 ⇒ other', () => {
    // ★ 判别性断言：把 `startsWith` 改成 `includes`，这条会红而其他用例照绿
    expect(getPlatformMode('non_amazon')).toBe('other')
    expect(getPlatformMode('my_shopee_store')).toBe('other')
    expect(getPlatformMode('x_temu')).toBe('other')
  })
})

describe('platform · isSimplifiedListingMode（短标题 + 详情，无五点）', () => {
  it('Shopee / Temu 是简化模式', () => {
    expect(isSimplifiedListingMode('shopee_my')).toBe(true)
    expect(isSimplifiedListingMode('temu_us')).toBe(true)
  })

  it('亚马逊不是简化模式（要走标题 / 五点 / Search Term / A+ / SEO）', () => {
    expect(isSimplifiedListingMode('amazon_us')).toBe(false)
    expect(isSimplifiedListingMode(undefined)).toBe(false) // 空值兜底 amazon ⇒ 完整模式
  })

  it('其他平台不是简化模式', () => {
    expect(isSimplifiedListingMode('tiktok')).toBe(false)
    expect(isSimplifiedListingMode('shopify')).toBe(false)
  })
})

describe('platform · isAmazonMode', () => {
  it('亚马逊为真', () => {
    expect(isAmazonMode('amazon_us')).toBe(true)
    expect(isAmazonMode('amazon')).toBe(true)
  })

  it('★ 空值也为真 —— 与 getPlatformMode 的兜底一致（这是刻意的，不是笔误）', () => {
    expect(isAmazonMode(undefined)).toBe(true)
    expect(isAmazonMode(null)).toBe(true)
  })

  it('Shopee / Temu / 其他为假', () => {
    expect(isAmazonMode('shopee_my')).toBe(false)
    expect(isAmazonMode('temu')).toBe(false)
    expect(isAmazonMode('tiktok')).toBe(false)
  })

  it('与 getPlatformMode 保持同源（不是第二份判定实现）', () => {
    for (const p of ['amazon_uk', 'shopee_tw', 'temu', 'shopify', undefined, null, '']) {
      expect(isAmazonMode(p), String(p)).toBe(getPlatformMode(p) === 'amazon')
      expect(isSimplifiedListingMode(p), String(p)).toBe(
        getPlatformMode(p) === 'shopee' || getPlatformMode(p) === 'temu',
      )
    }
  })
})

describe('platform · getPlatformLabel', () => {
  it('四种模式各有中文名，other 兜底为「其他平台」', () => {
    expect(getPlatformLabel('amazon_us')).toBe('亚马逊')
    expect(getPlatformLabel('shopee_th')).toBe('Shopee')
    expect(getPlatformLabel('temu_us')).toBe('Temu')
    expect(getPlatformLabel('tiktok')).toBe('其他平台')
    expect(getPlatformLabel(undefined)).toBe('亚马逊')
  })
})
