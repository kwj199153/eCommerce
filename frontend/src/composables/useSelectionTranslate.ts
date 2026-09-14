/**
 * 划词翻译（SaaS 内建）
 * ====================
 * 用户选中英文商品文字 → 就地弹出译文。这是**产品内能力**，不依赖任何浏览器扩展，
 * 所以平台的每个用户开箱可用（扩展那条路只能覆盖「自己装了扩展的浏览器」）。
 *
 * 与「译」按钮共用同一份状态：按钮调 translate(text, anchor) 显式触发，
 * 选区监听自动触发。浮层组件（SelectionTranslateLayer.vue）只负责渲染。
 *
 * 几个刻意的设计（都有代价，别随手改）：
 *
 * 1. **只对非中文的选区自动弹**。用户在 SaaS 里选中文多半是在复制文案，
 *    不是要翻译；每次选中都弹会非常烦。中文 → 英文这种反向需求走「译」按钮显式触发。
 *
 * 2. **有状态、带竞态序号**。用户快速连选两段文字时，先发的慢响应可能后到，
 *    必须丢弃过期结果，否则浮层会显示上一段的译文。
 *
 * 3. **请求静默**（api 层已传 `silent: true`）。划词是高频操作，
 *    不能每选一次就弹一个「翻译完成」的全局提示。
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
 */

import { reactive, ref } from 'vue'
import { translateSelection } from '@/api/aigcMedia'

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
  sourceLang: string
  targetLang: string
  error: string
  anchor: TranslateAnchor | null
}

const MAX_CHARS = 2000
const MEANINGFUL = /[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff]/
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff]/

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

let seq = 0
let suppressHide = false

export function useSelectionTranslate() {
  return {
    state,
    autoEnabled,
    translate,
    hide,
    setAutoEnabled,
    anchorOf,
    translateFromEvent,
    setSuppressHide,
    startSelectionWatcher,
  }
}

/** 收起浮层。递增 seq 让在途响应失效，避免「关了又被迟到结果顶开」。 */
export function hide() {
  seq++
  state.visible = false
  state.loading = false
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

/** 取元素的视口矩形，作为浮层锚点（「译」按钮用） */
export function anchorOf(el: HTMLElement | null | undefined): TranslateAnchor | null {
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
 * @param text   待翻译文本
 * @param anchor 浮层锚点（视口坐标）；为空时浮层会落在视口底部居中
 */
export async function translate(text: string, anchor: TranslateAnchor | null) {
  const t = (text || '').trim()
  if (!t) return

  const mySeq = ++seq
  state.visible = true
  state.loading = true
  state.original = t
  state.translation = ''
  state.error = ''
  state.sourceLang = ''
  state.targetLang = ''
  state.anchor = anchor

  try {
    const res = await translateSelection({ text: t })
    if (mySeq !== seq) return // 已经翻别的了 / 已关闭，丢弃这次结果

    const d = res?.response
    if (res?.success && d && !d.degraded && d.translation) {
      state.translation = d.translation
      state.sourceLang = d.source_lang
      state.targetLang = d.target_lang
    } else {
      // 后端在 LLM 不可用时返回 degraded 且译文为空 —— 不编造译文，这里如实告知
      state.error = '翻译服务暂不可用，请稍后重试'
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
    if (isTextField(e.target)) return // 输入框里选字是要编辑，不是要阅读

    const sel = window.getSelection()
    const text = sel ? sel.toString().trim() : ''
    if (!text || text.length > MAX_CHARS || !MEANINGFUL.test(text)) {
      if (state.visible) hide()
      return
    }
    // 选中文多半是在复制，不自动弹（反向需求走「译」按钮）
    if (CJK.test(text)) {
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

  document.addEventListener('mouseup', onMouseUp, true)
  document.addEventListener('mousedown', onMouseDown, true)
  document.addEventListener('keydown', onKeyDown, true)
  document.addEventListener('selectionchange', onSelectionChange)
  window.addEventListener('wheel', onWheel, { passive: true, capture: true })
  window.addEventListener('resize', onResize)

  teardown = () => {
    document.removeEventListener('mouseup', onMouseUp, true)
    document.removeEventListener('mousedown', onMouseDown, true)
    document.removeEventListener('keydown', onKeyDown, true)
    document.removeEventListener('selectionchange', onSelectionChange)
    window.removeEventListener('wheel', onWheel, { capture: true })
    window.removeEventListener('resize', onResize)
    installed = false
    teardown = null
  }
  return teardown
}

/** 输入型控件（含 Ant Design 的输入框）里选字不算划词。 */
function isTextField(target: EventTarget | null): boolean {
  const el = target as Element | null
  if (!el || (el as Element).nodeType !== 1) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return true
  // contenteditable 不挡：不少站点正文就是 contenteditable；真打字时 onKeyDown 会收起浮层
  return false
}
