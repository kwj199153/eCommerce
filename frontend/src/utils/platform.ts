/**
 * 平台判断工具
 *
 * 根据店铺 platform 字段判断所属平台模式，驱动 Listing 优化师
 * 等工具的字段展示与 SEO 校验规则。
 */

/** 平台模式 */
export type PlatformMode = 'amazon' | 'shopee' | 'temu' | 'other'

/** 店铺 platform 完整枚举（与 stores/shop.ts 保持一致） */
export type ShopPlatform =
  | 'amazon_us' | 'amazon_uk' | 'amazon_de' | 'amazon_jp'
  | 'shopee_my' | 'shopee_tw' | 'shopee_ph' | 'shopee_th'
  | 'shopee_sg' | 'shopee_vn' | 'shopee_id' | 'shopee_br'
  | 'temu' | 'temu_us' | 'temu_uk' | 'temu_de'
  | 'tiktok' | 'shopify'

/**
 * 根据平台字符串判断平台模式
 * @param platform 店铺 platform 字段（可能是完整枚举，也可能是 'amazon'/'shopee'/'temu' 简写）
 */
export function getPlatformMode(platform?: string | null): PlatformMode {
  if (!platform) return 'amazon' // 默认亚马逊（未绑定店铺时兜底）
  const p = platform.toLowerCase()
  if (p.startsWith('amazon')) return 'amazon'
  if (p.startsWith('shopee')) return 'shopee'
  if (p.startsWith('temu')) return 'temu'
  return 'other'
}

/**
 * 是否为「简化 Listing」模式（Temu/Shopee：短标题 + 商品详情，无五点）
 */
export function isSimplifiedListingMode(platform?: string | null): boolean {
  const mode = getPlatformMode(platform)
  return mode === 'shopee' || mode === 'temu'
}

/**
 * 是否为「亚马逊」完整模式（标题 / 5点 / Search Term / A+ / SEO 诊断）
 */
export function isAmazonMode(platform?: string | null): boolean {
  return getPlatformMode(platform) === 'amazon'
}

/** 平台模式的中文名 */
export function getPlatformLabel(platform?: string | null): string {
  switch (getPlatformMode(platform)) {
    case 'amazon': return '亚马逊'
    case 'shopee': return 'Shopee'
    case 'temu': return 'Temu'
    default: return '其他平台'
  }
}
