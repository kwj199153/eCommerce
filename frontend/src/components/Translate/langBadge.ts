/**
 * 方向徽标：**两条翻译浮层共用一份实现**。
 * ============================================
 * ★ 为什么单独成模块：第 364 轮划词浮层与截屏浮层**各写了一份** `badgeText`，
 *   第 365 轮又要给两者加同一条「含外文 → X」规则 —— 两份实现注定漂移，
 *   而漂移的症状是「同一个后端结果，两个浮层显示不一样的方向」，最难发现。
 *   （第 367 轮截屏浮层退场，但约束不变：任何新浮层都必须从这里取，不许另写一份。）
 *
 * ★ 这里**不做任何语言判定**：只把后端给的两个语言码翻成中文标签。
 *   判定（`detect_lang` / `same_lang`）的唯一真源在后端 —— 前端推算方向 = 第二份实现。
 */

/** 后端会回的语种码 → 界面标签 */
export const LANG_LABEL: Record<string, string> = {
  zh: '中文',
  en: '英文',
  ja: '日文',
  ko: '韩文',
  de: '德文',
  es: '西文',
  fr: '法文',
  it: '意文',
  pt: '葡文',
}

export interface BadgeInput {
  /** 正在请求（划词是「翻译中」；措辞由调用方给） */
  loading: boolean
  /** 加载中的文案 —— 两条链路的措辞不同，由调用方给 */
  loadingText: string
  /** 错误文案（空串 = 无错） */
  error: string
  /** 有没有拿到原文 */
  hasOriginal: boolean
  /** 出错且没有原文时的文案（划词链路不会走到这里，留给「确实没取到原文」的入口） */
  emptyText?: string
  /** 后端 `same_lang`：没翻译，且这不是故障 */
  sameLang: boolean
  sourceLang: string
  targetLang: string
}

export function formatBadge(o: BadgeInput): string {
  if (o.loading) return o.loadingText
  if (o.error) return o.hasOriginal ? '翻译失败' : (o.emptyText ?? '翻译失败')
  // ★ 「已是中文」不是失败、也不是「中文 → 中文」这种自相矛盾的方向
  if (o.sameLang) return `已是${LANG_LABEL[o.sourceLang] || '原文'}`
  const to = LANG_LABEL[o.targetLang] || o.targetLang
  if (!to) return '译文'
  const from = LANG_LABEL[o.sourceLang] || '原文'
  // ★ 第 365 轮：源与目标同名 ⇒ 文本里夹了外文（`detect_lang` 是二值判据，
  //   只能报「主导文字」）。这次确实把外文那部分落成了中文，
  //   但显示「中文 → 中文」会看起来像坏了。
  if (from === to) return `含外文 → ${to}`
  return `${from} → ${to}`
}
