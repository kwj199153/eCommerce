/**
 * 分组 / 标签默认色板（**持久化用**）
 *
 * ⚠️ 与 `--chart-*` 的分工（别混用）：
 *   · `--chart-*`（`presets.ts`）= **展示色**，随主题明暗切换 —— 图表序列、KPI 装饰用；
 *   · 本文件 = **用户数据**，分组/标签创建时写进数据库，**不随主题变**
 *     （用户挑了红色分组，切深色不该变成别的红）。
 *
 * 因此这里**必须保持 hex 字面量，不能换成 `var()`** —— 否则会把 CSS 表达式写进数据库。
 *
 * 收敛目的：原先 4 个 store（productLibrary / assetLibrary / candidateLibrary / monitorPool）
 * 各写一份 8 色数组，**且互不一致**（monitorPool 的第 4 色是紫、末色是红，其余是红/橙）。
 * 现在「改默认配色」只需改这里一处。
 */

export const GROUP_PALETTE: readonly string[] = [
  '#1890ff', // 蓝
  '#52c41a', // 绿
  '#faad14', // 金
  '#ff4d4f', // 红
  '#722ed1', // 紫
  '#13c2c2', // 青
  '#eb2f96', // 品红
  '#fa8c16', // 橙
]

/** 取第 i 个分组色（0-based，越界循环 —— 分组数不定时不会出现空色） */
export function groupColor(i: number): string {
  const n = GROUP_PALETTE.length
  return GROUP_PALETTE[((i % n) + n) % n]
}
