/**
 * 表单控件（`<input>` / `<textarea>`）内选区的**读取**与**定位** —— 全站划词的唯一真源。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 为什么不能沿用「普通网页文字」那一套（三条都是**真机实测**，不是推断）
 * ════════════════════════════════════════════════════════════════════════
 * 探针 `.workbuddy/probes/r366/probe_textfield_selection.mjs`（headless=new
 * 与有头 Chrome 153 各跑一次，结论一致）：
 *
 *   ① 控件内选区的 `window.getSelection().getRangeAt(0)` 是一个**挂在 BODY 上的
 *      伪 range** —— 它的 `containerNode` 是 `BODY#1`，`getBoundingClientRect()`
 *      **恒为 0×0**：
 *        textarea  → container BODY#1, rect {t:0,l:0,w:0,h:0}
 *        input     → container BODY#1, rect {t:0,l:0,w:0,h:0}
 *        contenteditable → container #text#3, rect {t:252,l:63,w:175,h:14}  ← 真 range
 *      ⇒ 靠 range 的 rect 定位浮层**必然失败**。而且调用方（useSelectionTranslate）
 *      有一道 `if (!r || (!r.width && !r.height)) return`，会把它变成**静默 return**：
 *      浮层不出现、不报错、控制台干干净净 —— 「改了没生效」的隐蔽来源。
 *
 *   ② 选区文字的唯一真源是 `el.selectionStart / el.selectionEnd`。
 *      `window.getSelection().toString()` 在 Chrome 153 上**恰好**也能拿到值，
 *      但它依赖的是上面那个伪 range 的实现细节，跨版本/跨浏览器不保证 —— 不可依赖。
 *
 *   ③ 坐标必须**自己算**（镜像法）。见 `rectOfFieldSelection`。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 哪些控件该被排除：**不许硬编码类型名单**
 * ════════════════════════════════════════════════════════════════════════
 * 探针 `.workbuddy/probes/r366/probe_input_types.mjs` 逐类型实测（读 selectionStart /
 * 写 setSelectionRange / 读回，捕获异常）：
 *
 *   支持选区：text / search / url / tel / **password**
 *   不支持  ：email / number / date / time / datetime-local / month / week /
 *             color / file / range / checkbox / radio / hidden / submit /
 *             button / image / reset   —— 读 `selectionStart` 返回 **null**
 *             （写 `setSelectionRange` 才抛 InvalidStateError）
 *
 * ⇒ 排除规则用**运行期判据**（`typeof selectionStart !== 'number'`），
 *   而不是抄一份类型名单：名单会漏、会随浏览器版本过期，而判据不会。
 *
 * ⇒ **唯一必须显式排除的是 `password`** —— 它*支持*选区，运行期判据放行它，
 *   而把密码原文发去翻译后端是绝对不能发生的事。这一条只能靠类型判断，
 *   所以它单独列在最前面（`NEVER_READ_TYPE`）。
 *
 * ★ 本模块是**纯叶子**：零 vue import、零 api import、零副作用。
 *   原因有二：① 可被单测直接调用；② `useSelectionTranslate` 被两个懒加载路由
 *   共享，叶子挂在那里会把它一起拖进 chunk 图。
 */

/** 控件内选区：三个字段都是调用方真正需要的（`text` 已按值裁好） */
export interface FieldSelection {
  /** `el.selectionStart`（已夹到 [0, value.length]） */
  start: number
  /** `el.selectionEnd`（已夹到 [start, value.length]） */
  end: number
  /** **唯一真源**下取到的选区文字（`value.slice(start, end)`） */
  text: string
}

/**
 * 选区锚点（视口坐标）。
 *
 * ★ 与 `useSelectionTranslate.ts` 的 `TranslateAnchor` **同形** —— 刻意如此：
 *   调用方拿到它就能直接喂给 `translate(text, anchor)`，零适配层。
 *   两处形状若漂移，`check-selection-field-rule.cjs` 会红。
 */
export interface SelectionRect {
  top: number
  bottom: number
  left: number
  width: number
}

/**
 * 唯一被**显式**排除的 input 类型。
 *
 * 它支持选区（`selectionStart` 是数字），所以运行期判据抓不住它；
 * 而「用户在某处输入的密码被送去第三方翻译接口」是不可接受的，
 * 哪怕用户是主动划选的 —— 划选密码框几乎只发生在「想复制密码」的场景，
 * 那不是请求翻译的意思表示。
 */
const NEVER_READ_TYPE = 'password'

/** 元素是 `<input>` 或 `<textarea>`（节点类型先判，避免 Text/Comment 上读 tagName） */
export function isFieldElement(el: unknown): el is HTMLInputElement | HTMLTextAreaElement {
  const e = el as Element | null
  if (!e || (e as Element).nodeType !== 1) return false
  const tag = (e as Element).tagName
  return tag === 'INPUT' || tag === 'TEXTAREA'
}

/**
 * 读控件内的选区。
 *
 * @returns 不是表单控件 / 被排除（password）/ 该类型不支持选区 / 读过程抛异常
 *          ⇒ `null`；否则返回 `{ start, end, text }`（**空选区也返回**，
 *          由调用方按自己的口径决定「空串算不算要翻」）。
 *
 * ★ 语义要点：`null` = 「这里**没有**可读的选区」，不是「选区为空」。
 *   调用方用前者决定「换个取值方式」，用后者决定「收起浮层」。
 */
export function readFieldSelection(
  el: unknown,
): FieldSelection | null {
  if (!isFieldElement(el)) return null
  if ((el as HTMLInputElement).type === NEVER_READ_TYPE) return null

  let start: number | null
  let end: number | null
  try {
    start = el.selectionStart
    end = el.selectionEnd
  } catch {
    // 某些宿主（jsdom 旧版 / 自定义元素）读属性就会抛，按「不可读」处理
    return null
  }
  // ★ 运行期判据：不支持选区的 type 在这里返回 null（见文件头第 ③ 条）
  if (typeof start !== 'number' || typeof end !== 'number') return null
  if (start < 0 || end < start) return null

  const value = typeof el.value === 'string' ? el.value : ''
  const s = Math.min(start, value.length)
  const e = Math.min(end, value.length)
  return { start: s, end: e, text: value.slice(s, e) }
}

/**
 * 需要从控件复制到镜像 div 上的计算样式。
 *
 * 少一项就会出现「镜像里的换行位置与控件里不一致 ⇒ 坐标整体偏移」——
 * 这类偏差不报错，只让浮层落在一个**看起来奇怪但对不上**的位置。
 */
const MIRROR_PROPS = [
  'font-family',
  'font-size',
  'font-weight',
  'font-style',
  'font-variant',
  'font-stretch',
  'line-height',
  'letter-spacing',
  'word-spacing',
  'text-transform',
  'text-indent',
  'text-align',
  'direction',
  'tab-size',
  'text-rendering',
  'padding-top',
  'padding-right',
  'padding-bottom',
  'padding-left',
  'border-top-width',
  'border-right-width',
  'border-bottom-width',
  'border-left-width',
] as const

/**
 * 算出控件内选区的视口矩形 —— **镜像法**。
 *
 * 原理：把控件的排版环境（字体/行高/内边距/边框/换行规则）复制到一个
 * `visibility: hidden` 的绝对定位 div 上，把值拆成
 * `前文 + <span>选区</span> + 后文` 铺进去，量 `<span>` 的矩形，
 * 再平移到控件的坐标系上（并扣掉 `scrollTop/scrollLeft`）。
 *
 * ★ 可行性已与**第二独立实现**对账（`.workbuddy/probes/r366/probe_textfield_anchor.mjs`）：
 *   用 canvas `measureText` 算首行水平偏移，两者差 **1.00px**；
 *   textarea 跨行选区 y 从 51 → 71（行高 20）正确跳行。
 *   ⇒ 「自己跟自己比」不算证据，这里是两个实现互校。
 *
 * ★ 尺寸口径（踩过的一处坑，写清楚免得被"简化"掉）：
 *   - 镜像 `box-sizing: border-box`，宽度取 `el.clientWidth + 左右边框`
 *     —— `clientWidth` 已排除边框与滚动条，于是镜像的**内容宽**恰好等于
 *     控件真实可排版的宽度（含滚动条补偿），换行位置才对得上。
 *   - 不复制 `box-sizing`（强制 border-box）而用 `offsetWidth`：控件若是
 *     content-box，两者会差一个 padding，坐标整体偏移。统一口径更稳。
 *   - 输入框强制 `white-space: pre`：`<input>` 的文字**不换行**，用
 *     `pre-wrap` 会让超长值的后半段落进第二行，得到完全错误的 y。
 *
 * @returns 算不出来（非控件 / 无 document / 异常）⇒ `null`，调用方退回
 *          `anchorOf(el)`。**刻意不在这里静默返回一个 0×0 的矩形**：
 *          那正是本项目记录过的「静默 return，看起来像没生效」形态。
 */
export function rectOfFieldSelection(
  el: unknown,
  start: number,
  end: number,
): SelectionRect | null {
  if (!isFieldElement(el)) return null
  if (
    typeof document === 'undefined' ||
    !document.body ||
    typeof document.createElement !== 'function' ||
    typeof document.createTextNode !== 'function'
  ) {
    return null
  }

  const value = typeof el.value === 'string' ? el.value : ''
  const s = Math.max(0, Math.min(start, value.length))
  const e = Math.max(s, Math.min(end, value.length))

  const isInput = el.tagName === 'INPUT'
  let mirror: HTMLDivElement | null = null
  try {
    const cs = getComputedStyle(el)

    mirror = document.createElement('div')
    for (const p of MIRROR_PROPS) {
      mirror.style.setProperty(p, cs.getPropertyValue(p))
    }
    // 让边框宽度真正生效（默认 border-style 是 none，宽度会被忽略）
    mirror.style.borderStyle = 'solid'
    mirror.style.borderColor = 'transparent'
    mirror.style.boxSizing = 'border-box'
    mirror.style.width = `${el.clientWidth + px(cs.borderLeftWidth) + px(cs.borderRightWidth)}px`
    mirror.style.height = 'auto'
    mirror.style.maxHeight = 'none'
    mirror.style.position = 'absolute'
    mirror.style.top = '0'
    mirror.style.left = '0'
    mirror.style.visibility = 'hidden'
    mirror.style.pointerEvents = 'none'
    mirror.style.overflow = 'visible'
    if (isInput) {
      // ★ `<input>` 永不换行；用 pre-wrap 会让超长值错误折行
      mirror.style.whiteSpace = 'pre'
      mirror.style.overflowWrap = 'normal'
      mirror.style.wordBreak = 'normal'
    } else {
      mirror.style.whiteSpace = cs.whiteSpace || 'pre-wrap'
    }

    mirror.appendChild(document.createTextNode(value.slice(0, s)))
    const span = document.createElement('span')
    // 空选区也要有个可量的盒子（零宽空格），否则 rect 恒 0
    span.textContent = value.slice(s, e) || '\u200b'
    mirror.appendChild(span)
    mirror.appendChild(document.createTextNode(value.slice(e)))

    document.body.appendChild(mirror)

    const sr = span.getBoundingClientRect()
    const mr = mirror.getBoundingClientRect()
    const tr = el.getBoundingClientRect()

    const top = tr.top + (sr.top - mr.top) - el.scrollTop
    const left = tr.left + (sr.left - mr.left) - el.scrollLeft
    return { top, bottom: top + sr.height, left, width: sr.width }
  } catch {
    // 计算样式读不到 / 选中元素已脱离文档 —— 交给调用方退回元素级锚点
    return null
  } finally {
    if (mirror && mirror.parentNode) mirror.parentNode.removeChild(mirror)
  }
}

/** `"8px"` → `8`；解析不出来按 0（不该因为一个怪异值就把坐标算崩） */
function px(v: string): number {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}
