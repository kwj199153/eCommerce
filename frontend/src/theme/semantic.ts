/**
 * 业务语义色 · JS 出口（semantic.ts）
 *
 * 目标：让「业务含义 → 颜色」只有一个定义处，且 CSS 与 JS 两个运行时读到同一套值。
 * 真源是 `presets.ts`，本模块只是它的 JS 侧视图。
 *
 * ⚠️ 取值律走 **`resolveVars(theme)`** 而不是 `THEME_PRESETS[theme].vars`：
 *    后者对「`basedOn` 差异表」只有差异部分，直读会拿到 `undefined`。
 *
 * ⚠️ 使用原则（能省掉 90% 的 JS 侧改造）：
 *
 * 1. **能用 `'var(--x)'` 字符串就别用 `semanticOf()` 拿真值。**
 *    实测 SVG presentation attribute 与内联 CSS 声明都吃 `var()`
 *    （见 `docs/p7-semantic-layer-plan.md` §2.4），所以图表 series、内联 style、
 *    状态映射这些「最终作为 CSS/SVG 值」的位置，直接写 `SEM.success` 即可 ——
 *    零 JS、随主题自动响应、无需重算。
 *
 * 2. 只有以下三种情况才需要 `semanticOf()` 的 hex 真值：
 *    ① 值参与字符串拼接 / 比较；② 传给 canvas（ECharts / 3D）；③ 需要颜色运算（调亮 / 混合）。
 *
 * 3. **本模块不提供「统一阈值」的评分映射**。项目内各分析卡的评分口径本就不同
 *    （80/60、70/40、75/50…），统一阈值会改变业务判定。调用方自行写阈值判断，
 *    只把色值换成 `SEM.*`。
 */

import { resolveVars, type ThemeName } from './presets'

/**
 * 语义名 → CSS 变量表达式。
 * 可直接用于：内联 `style`、SVG presentation attribute、组件 `color` prop、
 * ECharts 之外的任何「字符串即样式」的位置。
 */
export const SEM = {
  /** 蓝 —— 信息 / 蓝海 / 新品 / 中性信息 */
  primary: 'var(--primary)',
  /** 绿 —— 爆款 / 正常 / 成功 / 良好 */
  success: 'var(--success)',
  /** 橙 —— 预警 / 待处理 / 中等 */
  warning: 'var(--warning)',
  /** 红 —— 风险 / 异常 / 差评 / 删除 */
  danger: 'var(--danger)',
  /** 紫 —— SPU / 规格 / 多维分析（专属，尽量少用） */
  purple: 'var(--purple)',
  /** 青 —— 平台 / 渠道分类 */
  cyan: 'var(--cyan)',
  /** 金 —— 星级 / 领导者 / 排名第一 */
  gold: 'var(--gold)',
  /** 暗红 —— 白底上的风险**文字**（`#ff4d4f` 白底仅 3.3:1 不达标） */
  dangerStrong: 'var(--danger-strong)',
  /** 暗金 —— 白底上的预警**文字** */
  warningStrong: 'var(--warning-strong)',
  /** 暖橙 —— 介于「预警金」与「风险红」之间的那档（用于四档评分的中低档） */
  orangeStrong: 'var(--orange-strong)',
} as const

export type SemanticKey = keyof typeof SEM

/** 语义键 → 变量名（去 `var()` 包裹），供需要拼 CSS 字符串的场景使用 */
export function semVarName(key: SemanticKey): string {
  return SEM[key].slice(4, -1)
}

/**
 * 图表调色板（8 档，多序列区分色）。
 * 用法：`chartVar(i)` 或用 `SEM` 之外的 `--chart-n` 直写。
 */
export const CHART_VARS = [
  'var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)',
  'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)',
] as const

/** 取第 i 个图表色（0-based，越界循环取模 —— 序列数不定时不会出现空色） */
export function chartVar(i: number): string {
  const n = CHART_VARS.length
  return CHART_VARS[((i % n) + n) % n]
}

/** 排名 / 奖牌色：0=金 1=银 2=铜，越界回落中性灰 */
export const RANK_VARS = ['var(--rank-1)', 'var(--rank-2)', 'var(--rank-3)'] as const

export function rankVar(i: number): string {
  return RANK_VARS[i] ?? 'var(--text-tertiary)'
}

/**
 * JS 侧真值出口 —— 与 CSS 变量同源（同读 `resolveVars()`，已展开 `basedOn`）。
 * **仅在需要 hex 真值时使用**（canvas / 字符串拼接 / 颜色运算）。
 */
export function semanticOf(theme: ThemeName): Record<SemanticKey, string> {
  const v = resolveVars(theme)
  return {
    primary: v['--primary'],
    success: v['--success'],
    warning: v['--warning'],
    danger: v['--danger'],
    purple: v['--purple'],
    cyan: v['--cyan'],
    gold: v['--gold'],
    dangerStrong: v['--danger-strong'],
    warningStrong: v['--warning-strong'],
    orangeStrong: v['--orange-strong'],
  }
}

/** 图表调色板的 hex 真值（canvas 场景用） */
export function chartPaletteOf(theme: ThemeName): string[] {
  const v: Record<string, string> = resolveVars(theme)
  return CHART_VARS.map((expr) => v[expr.slice(4, -1)])
}

/**
 * 平台品牌色 —— **不随主题变**（品牌还原度优先）。
 * 浅深两态共用同一组值；如需深色提亮变体，在此单列 `dark` 字段。
 */
export const PLATFORM_COLORS: Record<string, string> = {
  shopee: '#ee4d2d',
  amazon: '#ff9900',
  temu: '#fb7701',
  lazada: '#0f146d',
  tiktok: '#fe2c55',
  walmart: '#0071dc',
  ebay: '#e53238',
  shein: '#000000',
}

/** 平台名 → 品牌色（未命中兜底信息蓝的变量表达式） */
export function platformColor(platform?: string | null): string {
  if (!platform) return SEM.primary
  return PLATFORM_COLORS[platform.toLowerCase()] ?? SEM.primary
}
