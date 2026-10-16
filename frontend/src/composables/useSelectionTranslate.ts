/**
 * 划词翻译（SaaS 内建）
 * ====================
 * 用户选中商品文字（任意语言）→ 就地弹出译文。这是**产品内能力**，不依赖任何浏览器扩展，
 * 所以平台的每个用户开箱可用（扩展那条路只能覆盖「自己装了扩展的浏览器」）。
 *
 * 与「译」按钮共用同一份状态：按钮调 translate(text, anchor) 显式触发，
 * 选区监听自动触发。浮层组件（SelectionTranslateLayer.vue）只负责渲染。
 *
 * 几个刻意的设计（都有代价，别随手改）：
 *
 * 1. **任意语言的选区都自动弹**。原先是「只对非中文选区弹」（理由：选中文多半是在复制），
 *    现按产品要求放开 —— 中文选区同样弹浮层。「怕打扰」由账户设置页的
 *    「自动弹」开关兜底，而不是靠猜用户选的是什么语言。
 *
 *    ★ 方向（第 364 轮改）＝**一律译成中文**（后端 `target_lang` 默认 `zh`）。
 *      原文已是中文时后端**不调模型**、回 `same_lang=true`，这里显示「已是中文」
 *      并给一个「译为英文」按钮 —— **别在浮层里照译一遍**：那正是产品已否掉的旧行为
 *      （老板自用扩展 v1.1.0 把「含汉字就译成英文」判成**反的**）。
 *
 * 2. **有状态、带竞态序号**。用户快速连选两段文字时，先发的慢响应可能后到，
 *    必须丢弃过期结果，否则浮层会显示上一段的译文。
 *
 * 3. **请求静默**。划词是高频操作，不能每选一次就弹一个「翻译完成」的全局提示 ——
 *    api 层已不传任何开关（自第 267 轮起拦截器默认不弹成功提示），
 *    这里也不再需要 `silent`。
 *
 * 4. **自动弹可被用户关掉**（账户设置页 → 交互偏好）。关的是「打扰」，不是「能力」：
 *    三处「译」按钮不受开关影响，仍可显式触发。
 *
 * 5. **本模块被两个懒加载路由共享**（Workspace 的浮层 / 账户设置页的开关），
 *    Rollup 会把它整个归进 Settings chunk，Workspace 反过来静态依赖 Settings chunk，
 *    于是设置页组件在进工作台时就被一并下载（约 6.5 kB gzip）。
 *    别想着用 manualChunks 拆出来 —— 试过，更糟：手写 manualChunks 会让 Rollup
 *    放弃默认的共享依赖分组，vue / antd 全被吸进那个新 chunk，单个 chunk 撑到 1.6 MB。
 *    6.5 kB 的预载换「显式的单一状态源」，比引一个 CustomEvent 隐式契约划算。
 *
 * 6. **表单控件内选字也弹**（第 366 轮放开）。此前 `isTextField` 把 input/textarea
 *    整条短路掉（理由：输入框里选字是「编辑动作」不是「阅读动作」），代价是用户在
 *    **商品标题 / 卖点 / 关键词**这类输入框里选中英文时拿不到任何帮助 —— 而那恰恰是
 *    最需要翻译的地方。现在改成「表单控件走另一条取值通道」：文字取
 *    `selectionStart/End`（唯一真源），坐标走**镜像法**（`utils/textSelection.ts`）。
 *    两条通道的取舍写在那个文件头里 —— 控件内的 range 是挂在 BODY 上的伪 range，
 *    `getBoundingClientRect()` 恒 0×0，硬走正文那条路只会撞上下面那道
 *    `if (!r.width && !r.height) return`，**静默 return**（浮层不出现也不报错）。
 *    「别打扰打字」仍由 `onKeyDown`（按下可见字符即收起）继续兜底。
 *
 * 8. **悬停翻译默认关**（第 370 轮 P1）。鼠标停住 350ms 自动弹译文，只对**含拉丁
 *    字母**的文本块出手。与划词那条路是**互补**关系而不是重复：划词要求用户
 *    「明确选一段」，悬停是「鼠标路过，猜你想看」。所以：
 *    · 开关默认**关**（判据 `=== '1'`，与 autoEnabled 的缺省开相反）；
 *    · 判定全部住在 `utils/hoverTranslate.ts`（纯叶子，可零成本单测），
 *      这里只读 DOM 事实；
 *    · 有选区 / 在浮层内 / 在可编辑元素内**一律不触发** —— 那三种情况下
 *      用户要么已经拿到浮层（划词），要么根本不该被打扰（编辑）。
 *
 * 9. **浮层正文有「双语 / 仅译文」两态**（第 370 轮 P1）。状态住在这里（与开关
 *    同级的模块级 ref），浮层组件只读不写 —— 避免「设置页写一份、浮层自己再存一份」
 *    这种两份真实来源。默认「双语」（可自证，理由见 `readDisplayMode`）。
 *
 * 7. **术语表按「当前店铺」取，且每次调用现读**（第 369 轮 P0）。设置页里用户写的
 *    `原文=译文` 会随请求带给后端，渲染成提示词里的一段硬约束。三个刻意的做法：
 *    · **分店铺**：术语表语义是「**本店**固定译法」（后端渲染的标题就是这个措辞），
 *      两个店铺共用一份必然出现 A 店品牌译法在 B 店全局生效。存储口径住
 *      `utils/glossary.ts`（按 `current_shop_id` 分键）。
 *    · **每次现读**，不在模块加载时读一次缓存：店铺是在侧栏随时能切走的，
 *      缓存下来就会把上一个店的术语表带到下一个店。
 *    · **空表连键都不带**：`glossaryPayload()` 空表返回 `{}` —— 既有断言
 *      「未配术语表时 `Object.keys(payload)` 恰为 `['text']`」正是这条的守卫。
 */

import { reactive, ref } from 'vue'
import { translateSelection } from '@/api/aigcMedia'
import { resolveTranslateOutcome } from '@/utils/translateOutcome'
import {
  isFieldElement,
  readFieldSelection,
  rectOfFieldSelection,
} from '@/utils/textSelection'
// ★ 术语表（第 369 轮 P0）：解析/存取的唯一真源。空表时 `glossaryPayload()` 返回 `{}`，
//   所以「要不要带这个字段」的判定只有一处，不在这里写 if。
import { glossaryPayload, readCurrentShopId } from '@/utils/glossary'
// ★ 悬停翻译（第 370 轮 P1）：**判定全在纯叶子里**，这里只负责读 DOM 事实 + 接线。
//   门禁 check-hover-translate.cjs 断言本文件必须从这里取判定 —— 不得自写第二份。
import { HOVER_DELAY_MS, MAX_HOVER_CHARS, decideHover, type HoverSignals } from '@/utils/hoverTranslate'

export interface TranslateAnchor {
  top: number
  bottom: number
  left: number
  width: number
}

interface SelectionTranslateState {
  visible: boolean
  loading: boolean
  original: string
  translation: string
  /** ★ 原文已经是目标语言（后端 `same_lang`）⇒ 没翻译，且这**不是**故障 */
  sameLang: boolean
  sourceLang: string
  targetLang: string
  error: string
  anchor: TranslateAnchor | null
}

const MAX_CHARS = 2000
const MEANINGFUL = /[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff]/

/** 浮层根节点的标记属性。监听器据此判断事件是否发生在浮层内部。 */
export const LAYER_ATTR = 'data-stl-layer'

/**
 * 「译」按钮的标记属性。
 *
 * 按钮不是浮层，但必须被当成**组件自己的一部分**：否则点按钮时，
 * 文档级的 mouseup 会顺手把当前选区也翻一次，和按钮要翻的文本打架。
 * 标上这个属性后，选区监听会跳过它。
 */
export const TRIGGER_ATTR = 'data-stl-trigger'

/** 事件目标是否属于本组件（浮层内部 或 任一「译」按钮） */
const OWN_SELECTOR = `[${LAYER_ATTR}],[${TRIGGER_ATTR}]`

const state = reactive<SelectionTranslateState>({
  visible: false,
  loading: false,
  original: '',
  translation: '',
  sameLang: false,
  sourceLang: '',
  targetLang: '',
  error: '',
  anchor: null,
})

// ---------------------------------------------------------------------------
// 自动弹开关（账户设置页写入，选区监听读取）
// ---------------------------------------------------------------------------

/** 持久化 key。纯前端偏好，不落后端 —— 换设备不会同步，这是刻意的。 */
const AUTO_KEY = 'selection_translate_auto'

/** 读开关。缺省为「开」：自动弹才是产品主推的默认体验。 */
function readAutoEnabled(): boolean {
  try {
    return localStorage.getItem(AUTO_KEY) !== '0'
  } catch {
    // localStorage 不可用（隐私模式 / 被策略禁用）时按默认放行，
    // 不能因为「存不了偏好」就顺手把功能废掉
    return true
  }
}

/**
 * 「选中文字后自动弹翻译」。
 *
 * 模块级单例 —— 设置页和浮层组件 import 的是同一份，改完立即生效，不需要保存按钮。
 */
export const autoEnabled = ref(readAutoEnabled())

/** 持久化 key。与 autoEnabled 同口径：纯前端偏好，不落后端（换设备不同步，刻意）。 */
const HOVER_KEY = 'selection_translate_hover'

/**
 * 读「悬停翻译」开关。
 *
 * ★★ 缺省为**关** —— 与上面 `readAutoEnabled()` 的 `!=='0'`（缺省开）**方向相反**。
 *    这不是笔误：划词是用户**明确选了**一段，悬停只是「鼠标路过」，属于额外的打扰，
 *    产品默认不给。⇒ 判据必须是 `=== '1'`（用户显式开过才为真）。
 *    别为了「统一风格」把它改成 `!== '0'` —— 那会让全站用户默认被悬停打扰。
 */
function readHoverEnabled(): boolean {
  try {
    return localStorage.getItem(HOVER_KEY) === '1'
  } catch {
    // 存不了偏好时按「关」处理：这是安全方向（不打扰），与 autoEnabled 的
    // 「读不到就放行」是相反的取舍 —— 因为两者的默认值本来就相反。
    return false
  }
}

/** 「鼠标停在文字上自动弹译文」。默认关，理由见 readHoverEnabled。 */
export const hoverEnabled = ref(readHoverEnabled())

/** 切换悬停开关。关掉的瞬间把待触发的定时器一起取消（否则关完还会弹一个）。 */
export function setHoverEnabled(v: boolean) {
  hoverEnabled.value = v
  try {
    localStorage.setItem(HOVER_KEY, v ? '1' : '0')
  } catch {
    // 存不进就只在本次会话内生效，不阻断交互
  }
  if (!v) clearHoverTimer()
}

/** 浮层正文的显示方式：双语（原文+译文）或仅译文 */
export type TranslateDisplayMode = 'bilingual' | 'target'

const DISPLAY_KEY = 'selection_translate_display'

/**
 * 读显示方式。缺省「双语」。
 *
 * 缺省不选「仅译文」的理由：译文单独出现时用户无法与原文对照，第一眼会怀疑
 * 「是不是翻错了 / 是不是滚到了别处」；双语是**可自证**的那个默认。
 */
function readDisplayMode(): TranslateDisplayMode {
  try {
    return localStorage.getItem(DISPLAY_KEY) === 'target' ? 'target' : 'bilingual'
  } catch {
    return 'bilingual'
  }
}

/** 浮层组件直接读这个 ref 决定渲不渲染原文区。 */
export const displayMode = ref<TranslateDisplayMode>(readDisplayMode())

export function setDisplayMode(m: TranslateDisplayMode) {
  displayMode.value = m
  try {
    localStorage.setItem(DISPLAY_KEY, m)
  } catch {
    // 存不进就只在本次会话内生效
  }
}

let seq = 0
let suppressHide = false

/**
 * 「已是中文」时的一键改译：沿用同一段原文，**显式**换一个目标语言。
 *
 * ★ 必须显式带 `target_lang` —— 不带就等于没换方向（后端默认还是中文），
 *   会被同语言短路原样挡回来。
 */
export async function retranslate(targetLang: string) {
  return translate(state.original, state.anchor, targetLang)
}

export function useSelectionTranslate() {
  return {
    state,
    autoEnabled,
    translate,
    retranslate,
    hide,
    setAutoEnabled,
    anchorOf,
    translateFromEvent,
    setSuppressHide,
    startSelectionWatcher,
    hoverEnabled,
    setHoverEnabled,
    displayMode,
    setDisplayMode,
  }
}

/** 收起浮层。递增 seq 让在途响应失效，避免「关了又被迟到结果顶开」。 */
export function hide() {
  seq++
  state.visible = false
  state.loading = false
  // ★ 待触发的悬停也一起取消：否则「手动收起浮层」之后 350ms，那个悬停
  //   还会把浮层顶回来 —— 症状是「关不掉」。
  clearHoverTimer()
}

/**
 * 切换「自动弹」开关。开关只影响选区监听，不影响按钮显式触发。
 */
export function setAutoEnabled(v: boolean) {
  autoEnabled.value = v
  try {
    localStorage.setItem(AUTO_KEY, v ? '1' : '0')
  } catch {
    // 存不进就只在本次会话内生效，不阻断交互
  }
  if (!v) hide() // 关掉的瞬间，把已经开着的那一个也收掉
}

/** 浮层内部交互期间抑制「选区变化即关闭」，否则点按钮会顺手把浮层关掉。 */
export function setSuppressHide(v: boolean) {
  suppressHide = v
}

/**
 * 取元素的视口矩形，作为浮层锚点（「译」按钮 / 悬停文本块用）。
 *
 * 参数类型是 `Element` 而不是 `HTMLElement`：悬停那条路拿到的是「最近的文本块
 * 祖先」，声明为 `Element`（`parentElement` 的返回类型）。两者都只用到
 * `getBoundingClientRect()`，收窄到 `HTMLElement` 会平白要求一处运行时断言。
 */
export function anchorOf(el: Element | null | undefined): TranslateAnchor | null {
  if (!el) return null
  const r = el.getBoundingClientRect()
  return { top: r.top, bottom: r.bottom, left: r.left, width: r.width }
}

/**
 * 「译」按钮的统一入口：以按钮自身为锚点，把浮层弹在它旁边。
 *
 * 用 currentTarget 而不是 target —— 按钮里可能有内部元素（图标），
 * target 会指到内层，锚点就偏了。
 */
export function translateFromEvent(text: string, e: MouseEvent) {
  return translate(text, anchorOf(e.currentTarget as HTMLElement | null))
}

/**
 * 发起翻译并展示浮层。
 * @param text       待翻译文本
 * @param anchor     浮层锚点（视口坐标）；为空时浮层会落在视口底部居中
 * @param targetLang 仅在**用户显式要求**时传（「已是中文 → 译为英文」那条通道）。
 *                   ★ 默认调用连键都不带：方向判据只住后端一处，
 *                     传 `undefined` 会污染 `Object.keys(payload)` 这类既有契约。
 */
export async function translate(text: string, anchor: TranslateAnchor | null, targetLang?: string) {
  const t = (text || '').trim()
  if (!t) return

  const mySeq = ++seq
  state.visible = true
  state.loading = true
  state.original = t
  state.translation = ''
  state.sameLang = false
  state.error = ''
  state.sourceLang = ''
  state.targetLang = ''
  state.anchor = anchor

  try {
    const payload: { text: string; target_lang?: string; glossary?: string } = { text: t }
    if (targetLang) payload.target_lang = targetLang
    // ★ 本店术语表（第 369 轮 P0）。`glossaryPayload()` 在「本店没配术语表」时返回 `{}`
    //   ⇒ 键不出现，请求体与术语表上线前逐字一致（后端 `glossary=""` 默认值同效）。
    //   现读而不是缓存：店铺可在侧栏随时切换，缓存会把上一家的术语表带过来。
    Object.assign(payload, glossaryPayload(readCurrentShopId()))
    const res = await translateSelection(payload)
    if (mySeq !== seq) return // 已经翻别的了 / 已关闭，丢弃这次结果

    // ★ 判定收口在 `utils/translateOutcome.ts`（**四态唯一真源**）。
    //   每个翻译入口面对的都是**同一个响应**；各写一份判定，必然出现
    //   「同一份响应在不同入口显示成不同话术」的口径分叉。
    const outcome = resolveTranslateOutcome(res)
    if (outcome.kind === 'same_lang') {
      // ★ 原文已是目标语言 —— 后端**没调模型**。如实显示「已是中文」，
      //   而不是一个空译文框（那是「三态压两态」，看起来像坏了）。
      state.sameLang = true
      state.sourceLang = outcome.sourceLang
      state.targetLang = outcome.targetLang
    } else if (outcome.kind === 'ok') {
      state.translation = outcome.translation
      state.sourceLang = outcome.sourceLang
      state.targetLang = outcome.targetLang
    } else {
      // 后端在 LLM 不可用时返回 degraded 且译文为空 —— 不编造译文，这里如实告知
      state.error = outcome.message
    }
  } catch (e: any) {
    if (mySeq !== seq) return
    state.error = e?.response?.data?.detail || '翻译失败，请稍后重试'
  } finally {
    if (mySeq === seq) state.loading = false
  }
}

let installed = false
let teardown: (() => void) | null = null

// ---------------------------------------------------------------------------
// 悬停翻译的 DOM 侧（只读事实，判定全在 @/utils/hoverTranslate）
// ---------------------------------------------------------------------------

let hoverTimer: ReturnType<typeof setTimeout> | null = null

function clearHoverTimer() {
  if (hoverTimer !== null) {
    clearTimeout(hoverTimer)
    hoverTimer = null
  }
}

/**
 * 向上找「最近的、文本量合适」的祖先，作为悬停候选。
 *
 * ★ 不给层数上限，靠**单调性**自然收敛：祖先的 `textContent` 必然包含后代全部文本
 *   ⇒ 长度只增不减 ⇒ 一旦超过上限，再往上只会更长，直接 break。
 *   （设「最多上溯 N 层」是更差的写法：N 定小了找不到块，定大了会摸到整个容器。）
 *
 * 不用 `getComputedStyle().display` 判块级：多一次强制样式计算，且宿主缺失时
 * 还会抛。文本长度本身就是最贴近需求的判据 —— 悬停要的是「一眼能读完的一块」。
 */
function nearestTextBlock(start: Element | null): { el: Element; text: string } | null {
  let el: Element | null = start
  while (el) {
    const text = (el.textContent || '').trim()
    if (text.length > MAX_HOVER_CHARS) break
    if (text) return { el, text }
    el = el.parentElement
  }
  return null
}

/**
 * 事件目标是不是「可编辑」的。
 *
 * ★ 名字刻意**不叫** `isTextField` —— 那个标识符已被门禁 S2e 判为**退役形态**
 *   （第 366 轮把「输入框整条短路」改成了「走另一条取值通道」，旧名不许复活）。
 *
 * 覆盖两类：① `isFieldElement`（input/textarea，复用控件那条通道的唯一真源）；
 * ② `contenteditable` —— 探针实测它有**真 range**（不是伪 range），所以划词那条路
 * 能用；但悬停时它属于「正在编辑的内容」，悬停翻译会跟输入打架，故排除。
 */
function isEditableTarget(t: EventTarget | null): boolean {
  const el = t as (HTMLElement & { isContentEditable?: boolean }) | null
  if (!el || typeof el !== 'object') return false
  if (isFieldElement(el)) return true
  return el.isContentEditable === true
}

/**
 * 装上全局选区监听。返回卸载函数。
 *
 * 由浮层组件在 onMounted 时调用一次（浮层挂在 Workspace 上，登出后自然一起卸载）。
 */
export function startSelectionWatcher(): () => void {
  if (installed && teardown) return teardown
  installed = true

  const inLayer = (target: EventTarget | null): boolean => {
    const el = target as Element | null
    return !!(el && typeof el.closest === 'function' && el.closest(OWN_SELECTOR))
  }

  const onMouseUp = (e: MouseEvent) => {
    if (!autoEnabled.value) return // 用户关了自动弹；「译」按钮仍可显式触发
    if (inLayer(e.target)) return // 在浮层里选词，不重新触发

    // ★ 表单控件（input / textarea）分支 —— 与正文选区**不是同一套取值方式**。
    //   控件内的 range 是挂在 BODY 上的伪 range，rect 恒 0×0；走下面那段会**静默
    //   return**（`!r.width && !r.height`）—— 浮层不出现、不报错、控制台干净。
    //   文字只认 selectionStart/End，坐标只认镜像法。见 utils/textSelection.ts。
    if (isFieldElement(e.target)) {
      const picked = readFieldSelection(e.target)
      // null = 这里**没有**可读的选区（password / 不支持选区的 type）。
      // 与旧的 `isTextField ⇒ return` 同口径：**不收起**已经开着的浮层。
      if (!picked) return

      const fieldText = picked.text.trim()
      if (!fieldText || fieldText.length > MAX_CHARS || !MEANINGFUL.test(fieldText)) {
        if (state.visible) hide()
        return
      }
      // 镜像法算不出（元素脱离文档 / 无 document）就退回元素级锚点，
      // 而不是「拿不到坐标就不弹」—— 那等于把一次可用的翻译静默丢掉。
      const anchor = rectOfFieldSelection(e.target, picked.start, picked.end) || anchorOf(e.target)
      translate(fieldText, anchor)
      return
    }

    const sel = window.getSelection()
    const text = sel ? sel.toString().trim() : ''
    if (!text || text.length > MAX_CHARS || !MEANINGFUL.test(text)) {
      if (state.visible) hide()
      return
    }
    if (!sel || sel.rangeCount === 0) return
    const r = sel.getRangeAt(0).getBoundingClientRect()
    if (!r || (!r.width && !r.height)) return

    translate(text, { top: r.top, bottom: r.bottom, left: r.left, width: r.width })
  }

  const onMouseDown = (e: MouseEvent) => {
    if (inLayer(e.target)) {
      suppressHide = true
      return
    }
    suppressHide = false
    if (state.visible) hide()
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (inLayer(e.target)) {
      if (e.key === 'Escape') hide()
      return
    }
    if (e.key === 'Escape') {
      if (state.visible) hide()
      return
    }
    // 用户开始打字，多半是要替换选区，浮层让路
    if (state.visible && e.key && e.key.length === 1) hide()
  }

  const onSelectionChange = () => {
    if (!state.visible || suppressHide) return
    // ★ 焦点在表单控件里时，`window.getSelection()` 拿不到控件的选区
    //   （或拿到一个空串），用它判空会把「刚在输入框里划好的那个词」**当场收掉**，
    //   症状是「输入框里划词只见闪一下」。控件内一律交给 mouseup 分支判定。
    if (isFieldElement(document.activeElement)) return
    const sel = window.getSelection()
    if (!sel || !sel.toString().trim()) hide()
  }

  const onWheel = (e: WheelEvent) => {
    if (inLayer(e.target)) return // 浮层内部滚动不算页面滚动
    if (state.visible) hide() // 页面滚了，锚点已失效，收掉比飘着更不乱
  }

  const onResize = () => {
    if (state.visible) hide()
  }

  /**
   * 悬停翻译（第 370 轮 P1）—— 默认关，只有用户在设置页显式打开才走这里。
   *
   * 每次 mouseover 都**先清掉上一个待触发**：鼠标在元素间移动时，浏览器会在
   * 同一帧里连发若干 mouseover（进父→进子），不清就会留下好几个定时器一起到点。
   */
  const onMouseOver = (e: MouseEvent) => {
    clearHoverTimer()
    if (!hoverEnabled.value) return

    const el = e.target as Element | null
    const block = nearestTextBlock(el)
    const sel = window.getSelection()

    // ★ 五条事实全部交给纯叶子判（唯一实现）—— 尤其是三条**结构性排除**
    //   （浮层内 / 编辑区内 / 已有选区），它们与「文本是什么」无关，
    //   写在调用方就意味着判据分叉。
    const signals: HoverSignals = {
      text: block ? block.text : '',
      isTextBlock: !!block,
      insideLayer: inLayer(e.target),
      insideEditable: isEditableTarget(e.target),
      hasSelection: !!(sel && sel.toString().trim()),
    }
    const decision = decideHover(signals)
    if (!decision.ok || !block) return

    const text = decision.text
    const anchorEl = block.el
    hoverTimer = setTimeout(() => {
      hoverTimer = null
      // ★ 「同文本去重」的真实需求只有这一条：浮层**已经显示着同一段文本**时别再弹。
      //   比 LRU 缓存更精确，而且不会像缓存那样在「切店铺 / 改术语表」后变陈旧
      //   （取舍写在 utils/hoverTranslate.ts 文件头）。
      if (state.visible && state.original === text) return
      translate(text, anchorOf(anchorEl))
    }, HOVER_DELAY_MS)
  }

  /**
   * 鼠标离开：取消待触发的悬停。
   *
   * ★ 必须自检 `relatedTarget` —— `mouseout` 在**移入自己的后代**时也会触发
   *   （目标=自己，relatedTarget=后代）。无条件取消的话，鼠标在一个有内层
   *   标签的块里挪一下就把计时重置一次，悬停**永远等不满 350ms**。
   */
  const onMouseOut = (e: MouseEvent) => {
    const from = e.target as Element | null
    const to = e.relatedTarget as Node | null
    if (to && from && typeof from.contains === 'function' && from.contains(to)) return
    clearHoverTimer()
  }

  document.addEventListener('mouseup', onMouseUp, true)
  document.addEventListener('mousedown', onMouseDown, true)
  document.addEventListener('keydown', onKeyDown, true)
  document.addEventListener('selectionchange', onSelectionChange)
  // 悬停翻译：用 capture 与上面三个保持一致（不被中途 stopPropagation 挡掉）
  document.addEventListener('mouseover', onMouseOver, true)
  document.addEventListener('mouseout', onMouseOut, true)
  window.addEventListener('wheel', onWheel, { passive: true, capture: true })
  window.addEventListener('resize', onResize)

  teardown = () => {
    document.removeEventListener('mouseup', onMouseUp, true)
    document.removeEventListener('mousedown', onMouseDown, true)
    document.removeEventListener('keydown', onKeyDown, true)
    document.removeEventListener('selectionchange', onSelectionChange)
    document.removeEventListener('mouseover', onMouseOver, true)
    document.removeEventListener('mouseout', onMouseOut, true)
    window.removeEventListener('wheel', onWheel, { capture: true })
    window.removeEventListener('resize', onResize)
    clearHoverTimer()
    installed = false
    teardown = null
  }
  return teardown
}
