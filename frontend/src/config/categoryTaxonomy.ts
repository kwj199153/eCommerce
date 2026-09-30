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
