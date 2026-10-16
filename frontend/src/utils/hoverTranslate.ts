/**
 * 悬停翻译的**判定部分** —— 纯叶子（零 DOM、零 vue、零 api 副作用）。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 为什么判定要单独成模块，而不是直接写在监听器里
 * ════════════════════════════════════════════════════════════════════════
 * 悬停翻译的触发条件有 7 条（见 `decideHover`）。写在 `useSelectionTranslate` 的
 * `onMouseOver` 里的话，每一条都只能靠「造一个 DOM 桩 + 移鼠标」来测 ——
 * 而本仓 `vitest.config.ts` 刻意**不装 jsdom**（`environment: 'node'`），
 * DOM 桩能验的只有 `addEventListener` 接没接上，验不了「哪种文本该弹」。
 *
 * 抽成纯函数后：① 7 条规则条条可零成本单测；② 判据只有一份实现
 * （门禁 `check-hover-translate.cjs` 据此断言 `useSelectionTranslate`
 * **必须**从这里 import，而不是自己再写一份）。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 与划词翻译的三处**刻意不同**（都有代价，别顺手改成一样）
 * ════════════════════════════════════════════════════════════════════════
 * ① **必须含拉丁字母**（`LATIN`）。划词是「用户明确选了一段 ⇒ 一律翻」，
 *    悬停是「鼠标路过 ⇒ 猜你想看」，猜错就是**无提示的打扰**。所以只对
 *    「读出英文」这一最明确的信号出手。
 *
 *    ★ 这里**刻意不加「不得含 CJK」的第二道**。看起来更严格，实际是负资产：
 *      · 纯中文/纯日文文本本来就不含拉丁 ⇒ 已被 `LATIN` 挡掉，那道判据恒不做功；
 *      · 而「中英混排」（`Noise Cancelling 主动降噪` 这类真实商品标题形态）
 *        会被它误杀 —— 恰恰是最需要翻译的样本。
 *      少一道恒不做功（却会误杀）的判据，就少一处口径分叉。
 *
 * ② **长度上限只有 200**（划词是 2000）。悬停取的是**整个文本块**而不是用户选的
 *    片段，上限必须小到「一眼能读完」，否则在容器上悬停会把一大段都翻出来。
 *
 * ③ **有选区就不触发**。用户已经用划词那条路拿到了浮层，悬停再弹一次只会打架。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 刻意**不引入** LRU / 翻译结果缓存
 * ════════════════════════════════════════════════════════════════════════
 * 曾计划做「同文本去重缓存」，评估后放弃，理由是缓存会**引入陈旧**：
 * 术语表按店铺存（`utils/glossary.ts`），切换店铺后缓存里的译文就不再适用，
 * 而失效时机（切店 / 改术语表）都在这个纯叶子看不到的地方。
 *
 * 真实需求其实只有一条：「已经弹着同一段文本时别再弹一次」。那条判据住在
 * 状态层（比对 `state.original`），比缓存**更精确**且不会陈旧，见
 * `useSelectionTranslate.onMouseOver`。
 */

/**
 * 鼠标停住多久才算「想翻译」。
 *
 * 350ms 的取舍：短于它，鼠标横扫页面时会沿途乱弹；长于它，用户会以为没反应。
 * 用鼠标「悬停提示」的通行区间（300~500ms）下限附近，偏向不打扰。
 */
export const HOVER_DELAY_MS = 350

/**
 * 悬停可取的最大字数。
 *
 * ★ 与划词的 `MAX_CHARS = 2000` **不是**同一个数，也**不要**合并成一个常量：
 *   两者对应的输入完全不同（用户选区 vs 整个文本块）。合并那天，要么划词
 *   被砍到 200（大量正常选区被拒），要么悬停被放到 2000（在容器上悬停
 *   会翻出一整段）。这正是「同一个数字巧合相同就合并」的经典陷阱。
 */
export const MAX_HOVER_CHARS = 200

/** 含拉丁字母 —— 悬停唯一的触发信号（理由见文件头 ①） */
const LATIN = /[A-Za-z]/

/**
 * 判定输入。**全是「事实」，不含任何 DOM 取值逻辑** ——
 * 「是不是文本块 / 有没有选区 / 在不在浮层里」由调用方在 DOM 侧读出后传进来。
 * 这样本模块才能在 `environment: 'node'` 下被直接单测。
 */
export interface HoverSignals {
  /** 候选文本（通常是某个文本块的 `textContent`） */
  text: string
  /** 事件目标能定位到一个「文本块」祖先（DOM 侧判定，见 useSelectionTranslate） */
  isTextBlock: boolean
  /** 事件发生在翻译浮层内部 */
  insideLayer: boolean
  /** 事件发生在可编辑元素内（input / textarea / contenteditable） */
  insideEditable: boolean
  /** 当前文档存在非空选区 */
  hasSelection: boolean
}

/** 不触发的具体原因。分成具名枚举而不是一个 `false`，是为了单测能逐条钉住。 */
export type HoverRejectReason =
  | 'no-block'
  | 'inside-layer'
  | 'inside-editable'
  | 'has-selection'
  | 'empty'
  | 'too-long'
  | 'no-latin'

export type HoverDecision =
  | { ok: true; text: string }
  | { ok: false; reason: HoverRejectReason }

/**
 * 悬停该不该翻、翻什么 —— **唯一实现**。
 *
 * 判定顺序是刻意的：先排「不该由我管」的场景（浮层内 / 编辑区 / 已有选区），
 * 再看文本本身（空 / 过长 / 不含拉丁）。前者是**结构性的**（无论文本是什么都不该触发），
 * 后者依赖文本内容。顺序反了不会出错，但会让 `reason` 指向次要原因，调试时误导。
 *
 * 文本在这里做**空白归一化**（`textContent` 天然带换行与缩进）。
 * 归一化只此一处 —— 调用方送的原文不要再各自 trim 一遍。
 */
export function decideHover(s: HoverSignals): HoverDecision {
  if (!s.isTextBlock) return { ok: false, reason: 'no-block' }
  if (s.insideLayer) return { ok: false, reason: 'inside-layer' }
  if (s.insideEditable) return { ok: false, reason: 'inside-editable' }
  if (s.hasSelection) return { ok: false, reason: 'has-selection' }

  const text = (s.text || '').replace(/\s+/g, ' ').trim()
  if (!text) return { ok: false, reason: 'empty' }
  if (text.length > MAX_HOVER_CHARS) return { ok: false, reason: 'too-long' }
  if (!LATIN.test(text)) return { ok: false, reason: 'no-latin' }

  return { ok: true, text }
}
