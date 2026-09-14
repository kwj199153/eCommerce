/**
 * 会话结论卡共用的格式化工具
 *
 * 抽出来的原因：4 张卡都要展示「钱 / 数 / 百分比 / 趋势」，
 * 分散实现会让同一份数据在不同卡里显示成不同样子（有的 $29.99、有的 29.99）。
 */

/** 千分位数字；非法值统一显示 — */
export function num(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? v.toLocaleString() : '—'
}

/** 美元金额 */
export function money(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? `$${v.toFixed(2)}` : '—'
}

/** 0-1 的比例 → 百分比整数 */
export function pct(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? `${Math.round(v * 100)}%` : '—'
}

const TREND_LABEL: Record<string, string> = {
  rising: '上升',
  stable: '稳定',
  declining: '下降',
  falling: '下降',
}

/** 趋势英文标识 → 中文（绝不把 rising/stable 这类内部标识示人） */
export function trendLabel(t?: string): string {
  if (!t) return '—'
  return TREND_LABEL[t] || t
}
