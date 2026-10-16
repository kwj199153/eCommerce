/**
 * 类目体系唯一真源（r310 · 老板抓「蓝海挖掘 cascader 与选品大盘子类目对不上」）。
 *
 * 之前两处各自硬编码：蓝海 cascader 一份（BlueOceanConfig 内联）、
 * 大盘显示名一份（seed 的 category_name + GROUP_NAMES）。slug 虽在 r309 对齐，
 * 显示名粒度仍各走各的：大盘色块显示**三级细分品类**（Coffee Machines），
 * cascader 显示**二级子类目**（Kitchen & Dining）——用户看到的就是两套。
 *
 * 收敛后四件事全部从这一份表派生，结构性杜绝再漂移：
 *   1. 蓝海挖掘 cascader 选项（CATEGORY_TAXONOMY）
 *   2. 选品大盘组标题条名（topLabel）
 *   3. 选品大盘色块名（midLabel，与 cascader 子项 1:1）
 *   4. 大盘 → 蓝海预填校验（isValidCategoryPath，fail-closed）
 *   5. 英文类目名 → 中文显示（CATEGORY_ZH + displayCategory，r365b）
 *      —— 组标题条 / 色块名 / cascader 选项 / tooltip / 抽屉全部从这一份表派生，
 *         杜绝「treemap 中文、短标签英文」这类口径分叉。
 *
 * ★ 三级路径约定：category_path = top/mid/leaf（如 home_kitchen/kitchen_dining/coffee）。
 *   cascader 与大盘色块都停在第两级（赛道粒度 = 蓝海挖掘表单可操作粒度）；
 *   leaf（细分品类）只作 tooltip 上下文展示，等真实三方数据接入后再议是否升第三级。
 */

export interface CategoryOption {
  value: string
  label: string
  children?: CategoryOption[]
}

export const CATEGORY_TAXONOMY: CategoryOption[] = [
  { value: 'home_kitchen', label: 'Home & Kitchen', children: [
    { value: 'kitchen_dining', label: 'Kitchen & Dining' },
    { value: 'home_decor', label: 'Home Decor' },
    { value: 'storage', label: 'Storage & Organization' },
  ]},
  { value: 'electronics', label: 'Electronics', children: [
    { value: 'accessories', label: 'Accessories' },
    { value: 'audio', label: 'Audio' },
    { value: 'camera', label: 'Camera & Photo' },
  ]},
  { value: 'sports', label: 'Sports & Outdoors', children: [
    { value: 'fitness', label: 'Fitness' },
    { value: 'camping', label: 'Camping & Hiking' },
    { value: 'team_sports', label: 'Team Sports' },
  ]},
  { value: 'beauty', label: 'Beauty & Personal Care', children: [
    { value: 'skincare', label: 'Skin Care' },
    { value: 'makeup', label: 'Makeup' },
    { value: 'hair_care', label: 'Hair Care' },
  ]},
  { value: 'toys', label: 'Toys & Games', children: [
    { value: 'educational', label: 'Learning & Education' },
    { value: 'outdoor_play', label: 'Outdoor Play' },
  ]},
  { value: 'pet', label: 'Pet Supplies', children: [
    { value: 'dog_supplies', label: 'Dog Supplies' },
    { value: 'cat_supplies', label: 'Cat Supplies' },
  ]},
]

/** 一级 slug → 显示名；不在体系内返回 undefined（调用方兜底原 slug） */
export function topLabel(top: string): string | undefined {
  return CATEGORY_TAXONOMY.find((t) => t.value === top)?.label
}

/** 二级子类目 slug → 显示名；top/mid 任一不在体系内返回 undefined（fail-closed） */
export function midLabel(top: string, mid: string): string | undefined {
  return CATEGORY_TAXONOMY.find((t) => t.value === top)?.children?.find((c) => c.value === mid)?.label
}

/** (top, mid) 是否可入选（大盘 → 蓝海预填校验用） */
export function isValidCategoryPath(top: string, mid: string): boolean {
  return midLabel(top, mid) !== undefined
}

// ---------------------------------------------------------------------------
// 英文类目名 → 中文（第 365b 轮 · 站内英文就地中文化）
//
// ★ 为什么用「内置术语表」而不是每次调模型：
//   站点类目是**有限枚举**（taxonomy 22 项 + 接入方末级名），术语表零延迟零成本，
//   且译法永不漂移（模型每次可能给出「厨房餐饮 / 厨房与餐饮 / 厨房餐具」三种）。
//   模型只用于**兜底**未收录的第三方新类目，命中后应落库缓存。
//
// ★ 键 = **英文显示名**（不是 slug）：
//   真实链路里 midLabel(slug) 返回的就是英文显示名，seed 的 category_name、
//   agent 产出的平台类目路径也都是英文显示名 ⇒ 统一在这一层收口，避免两套键。
//
// ★ 未收录的处理：**原样返回英文**。不造中文、不留空 —— 漏收录因此「一眼可见」，
//   而不是静默变成空白或半中半英的怪样子（r365b 硬约束）。
// ---------------------------------------------------------------------------

export const CATEGORY_ZH: Record<string, string> = {
  // 一级（组标题条）
  'Home & Kitchen': '家居与厨房',
  'Electronics': '电子产品',
  'Sports & Outdoors': '运动与户外',
  'Beauty & Personal Care': '美妆个护',
  'Toys & Games': '玩具与游戏',
  'Pet Supplies': '宠物用品',
  'Health & Personal Care': '健康与个护',
  'Automotive': '汽车用品',
  // 二级（色块名 / cascader 子项）
  'Kitchen & Dining': '厨房与餐饮',
  'Home Decor': '家居装饰',
  'Storage & Organization': '收纳整理',
  'Accessories': '配件',
  'Audio': '音频设备',
  'Camera & Photo': '摄影摄像',
  'Fitness': '健身器材',
  'Camping & Hiking': '露营徒步',
  'Team Sports': '团队运动',
  'Skin Care': '护肤',
  'Makeup': '彩妆',
  'Hair Care': '美发护发',
  'Learning & Education': '学习与教育',
  'Outdoor Play': '户外玩具',
  'Dog Supplies': '狗狗用品',
  'Cat Supplies': '猫咪用品',
  'Fitness Accessories': '健身配件',
  'Respiratory Aids': '呼吸辅助器具',
  'Interior Accessories': '车内配件',
  // 三级（细分品类：tooltip / 抽屉上下文）
  'Water Bottles': '运动水壶',
  'Coffee Machines': '咖啡机',
  'Phone Stands': '手机支架',
  'Smart Lighting': '智能照明',
  'Kitchen Storage': '厨房收纳',
  'Face Serums': '面部精华',
  'STEM Kits': 'STEM 教具',
  'Dog Chew Toys': '狗狗磨牙玩具',
  'Humidifiers': '加湿器',
  'Cooking Utensils': '烹饪用具',
  'Grow Lights': '植物生长灯',
  'Milk Frothers': '奶泡机',
  'Storage Organizers': '收纳盒',
  'Resistance Bands': '弹力带',
  'Cutting Boards': '砧板',
  'Chargers': '充电器',
  'Nebulizers': '雾化器',
  'Seat Back Organizers': '座椅背收纳袋',
  'Kitchen Scales': '厨房秤',
}

/** 单名翻译；未收录返回 undefined（调用方自行决定兜底） */
export function zhName(en: string): string | undefined {
  return CATEGORY_ZH[en]
}

/**
 * 显示档：窄容器省略英文（treemap 色块、组标题条），宽容器中英对照
 * （cascader / tooltip / 详情抽屉）。
 * ★ 两档共用同一份 CATEGORY_ZH ⇒ 中文名必然一致；差异只在「带不带英文原名」。
 */
export type CategoryDisplayMode = 'narrow' | 'wide'

/** 类目名显示：未收录原样返回英文（一眼可见），已收录按档输出 */
export function displayCategory(en: string, mode: CategoryDisplayMode = 'narrow'): string {
  const zh = CATEGORY_ZH[en]
  if (!zh) return en
  return mode === 'wide' ? `${zh}（${en}）` : zh
}

/** 全角/宽字符判定（CJK、假名、谚文、全角标点、emoji） */
function isWide(cp: number): boolean {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0x303e) ||
    (cp >= 0x3041 && cp <= 0x33ff) ||
    (cp >= 0x3400 && cp <= 0x4dbf) ||
    (cp >= 0x4e00 && cp <= 0x9fff) ||
    (cp >= 0xa000 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe6f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x1f300 && cp <= 0x1f64f) ||
    (cp >= 0x1f900 && cp <= 0x1f9ff) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
  )
}

/**
 * 显示宽度：CJK/全角记 2，其余记 1。
 * ★ 中文化后「字符数」口径失效：`name.length > 22` 会放行 22 个汉字，
 *   而 22 个汉字 ≈ 44 个半角宽 ⇒ treemap 色块必溢出。截断必须按本函数算。
 */
export function displayWidth(s: string): number {
  let w = 0
  for (const ch of s) w += isWide(ch.codePointAt(0) ?? 0) ? 2 : 1
  return w
}

/** 按显示宽度截断（超宽则截到 ≤ maxWidth 并补省略号） */
export function truncateByWidth(s: string, maxWidth: number, ellipsis = '…'): string {
  if (displayWidth(s) <= maxWidth) return s
  const ew = displayWidth(ellipsis)
  let w = 0
  let out = ''
  for (const ch of s) {
    const cw = isWide(ch.codePointAt(0) ?? 0) ? 2 : 1
    if (w + cw + ew > maxWidth) break
    out += ch
    w += cw
  }
  return out + ellipsis
}
