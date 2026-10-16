/**
 * 表单控件内选区：**取值**与**定位**（第 366 轮 · 阶段 B）
 * ============================================================================
 * 为什么这个文件存在：老板下达了一条**放开行为**的指令 ——
 *
 *   「是否有办法划线选择输入框的内容然后弹出译文？」→ 范围选了「全站所有输入框」
 *
 * 改之前 `onMouseUp` 里有一行 `if (isTextField(e.target)) return`，把 input/textarea
 * 整条短路掉。这条短路**不会报错**、不违反类型，唯一症状是「在输入框里划词没反应」。
 * 而且就算删掉它，控件内的 `range.getBoundingClientRect()` 恒为 0×0，
 * 下一行的 `if (!r.width && !r.height) return` 仍然会**静默 return** ——
 * 一个改动有两处静默失败点，所以必须有能分别打红的用例。
 *
 * ★ 本文件的两段职责刻意分开，因为它们能证明的东西**不一样**：
 *
 *   ① `readFieldSelection` —— 纯逻辑（读属性 + 裁切），**可以**用物件桩钉死：
 *      密码必须排除、不支持选区的 type 必须排除、文字必须取自 value.slice。
 *      这是安全相关的一条（密码原文绝不能离开浏览器），必须逐条钉。
 *
 *   ② `rectOfFieldSelection` —— 坐标算术。用**手搓 document 桩**钉两件事：
 *      算术（平移 + 扣滚动）与「镜像节点用完必须摘掉」。
 *      ★ 它**证明不了**真实浏览器里的排版几何 —— 那由 CDP 探针另测
 *      （`scripts/cdp-r366c-textfield-selection.mjs`：真实鼠标拖选 + 浮层真的出现）。
 *      两者职责不重叠，别把这条当成几何回归。
 *
 * ★ 顺带钉住的一条口径容易写错：`readFieldSelection` 返回 `null` 表示
 *   「这里**没有**可读的选区」，而空选区返回 `{ start, end, text: '' }`。
 *   两者混同会让「在密码框里划一下」变成「把浮层收掉」这类**行为级**差异。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import {
  readFieldSelection,
  rectOfFieldSelection,
  isFieldElement,
} from '@/utils/textSelection'

// ---------------------------------------------------------------------------
// ① 取值：readFieldSelection / isFieldElement
// ---------------------------------------------------------------------------

/** 造一个控件桩（只带被测代码真正会碰的字段） */
function field(over: Record<string, unknown> = {}) {
  return {
    nodeType: 1,
    tagName: 'TEXTAREA',
    type: 'textarea',
    value: 'Noise Cancelling Wireless Bluetooth Headphones',
    selectionStart: 0,
    selectionEnd: 28,
    scrollTop: 0,
    scrollLeft: 0,
    ...over,
  } as any
}

describe('表单控件选区 · isFieldElement', () => {
  it('input / textarea 判为控件', () => {
    expect(isFieldElement(field({ tagName: 'INPUT', type: 'text' }))).toBe(true)
    expect(isFieldElement(field({ tagName: 'TEXTAREA' }))).toBe(true)
  })

  it('普通元素 / 空值 / 文本节点 都不是控件', () => {
    expect(isFieldElement({ nodeType: 1, tagName: 'DIV' })).toBe(false)
    expect(isFieldElement({ nodeType: 3, tagName: undefined })).toBe(false)
    expect(isFieldElement(null)).toBe(false)
    expect(isFieldElement(undefined)).toBe(false)
  })
})

describe('表单控件选区 · readFieldSelection', () => {
  it('★ 文字取自 value.slice(start, end) —— 这是唯一真源', () => {
    const r = readFieldSelection(field({ selectionStart: 6, selectionEnd: 26 }))
    expect(r).toEqual({ start: 6, end: 26, text: 'Cancelling Wireless ' })
  })

  it('★ password 必须排除 —— 即使它支持选区（selectionStart 是数字）', () => {
    const pw = field({ tagName: 'INPUT', type: 'password', value: 'hunter2!', selectionStart: 0, selectionEnd: 8 })
    // 前置断言：桩上确实「有选区」。否则这条用例会因为桩写错而假绿
    expect(typeof pw.selectionStart).toBe('number')
    expect(readFieldSelection(pw)).toBeNull()
  })

  it('★ 不支持选区的 type 走**运行期判据**（selectionStart 为 null）⇒ null', () => {
    // 实测（probe_input_types.mjs）：email/number/date/time/month/week/color/file/
    // range/checkbox/radio/hidden/submit/button/image/reset 读 selectionStart 都是 null。
    // 这里用「名单外」的一个值再验一次：判据不是抄名单，而是看属性
    for (const type of ['email', 'number', 'date', 'color', 'file', 'range']) {
      expect(readFieldSelection(field({ tagName: 'INPUT', type, selectionStart: null, selectionEnd: null })))
        .toBeNull()
    }
  })

  it('读属性抛异常 ⇒ null（不把异常漏给全局 mouseup 监听）', () => {
    const boom = field()
    Object.defineProperty(boom, 'selectionStart', {
      get() {
        throw new Error('InvalidStateError')
      },
    })
    expect(readFieldSelection(boom)).toBeNull()
  })

  it('start > end / 负数 ⇒ null（脏值不当成选区）', () => {
    expect(readFieldSelection(field({ selectionStart: 10, selectionEnd: 4 }))).toBeNull()
    expect(readFieldSelection(field({ selectionStart: -1, selectionEnd: 4 }))).toBeNull()
  })

  it('越界自动夹到 value.length（不返回超长切片）', () => {
    const v = field().value as string
    const r = readFieldSelection(field({ selectionStart: 100, selectionEnd: 999 }))
    expect(r).toEqual({ start: v.length, end: v.length, text: '' })
    // 反例：start 在界内、end 越界 ⇒ 只夹 end，不把 start 也抹平
    expect(readFieldSelection(field({ selectionStart: 40, selectionEnd: 999 })))
      .toEqual({ start: 40, end: v.length, text: v.slice(40) })
  })

  it('★ 空选区（start === end）返回**对象**而不是 null —— 与「无选区」是两件事', () => {
    const r = readFieldSelection(field({ selectionStart: 5, selectionEnd: 5 }))
    expect(r).toEqual({ start: 5, end: 5, text: '' })
    // 对比：password 那种「真的不该读」才是 null
    expect(readFieldSelection(field({ type: 'password', tagName: 'INPUT' }))).toBeNull()
  })

  it('value 缺失 / 非字符串 ⇒ text 为空串而不是崩', () => {
    const r = readFieldSelection(field({ value: undefined, selectionStart: 0, selectionEnd: 3 }))
    expect(r).toEqual({ start: 0, end: 0, text: '' })
  })

  it('非控件一律 null', () => {
    expect(readFieldSelection({ nodeType: 1, tagName: 'DIV', selectionStart: 0, selectionEnd: 5 })).toBeNull()
    expect(readFieldSelection(null)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// ② 定位：rectOfFieldSelection（手搓 document 桩，只钉算术与清理）
// ---------------------------------------------------------------------------

/**
 * 控件桩：自身 rect + 滚动量。
 * 镜像 div 与 span 的 rect 由桩按顺序发给它们（见 makeDoc）。
 */
function ctrl(over: Record<string, unknown> = {}) {
  return {
    nodeType: 1,
    tagName: 'TEXTAREA',
    type: 'textarea',
    value: 'abcdefghij',
    scrollTop: 0,
    scrollLeft: 0,
    clientWidth: 300,
    getBoundingClientRect: () => ({ top: 95, bottom: 135, left: 25, width: 320, height: 40 }),
    ...over,
  } as any
}

interface DocStub {
  created: number
  appended: number
  removed: number
  doc: any
}

/**
 * 手搓 document：`createElement` 返回的节点依次是
 *   第 1 个 = 镜像 div  → rect {top:90, left:30}
 *   第 2 个 = 选区块 span → rect {top:100, left:50, width:80, height:20}
 */
function makeDoc(): DocStub {
  const st: DocStub = { created: 0, appended: 0, removed: 0, doc: null }
  const body = {
    appendChild(n: any) {
      st.appended++
      n.parentNode = body
    },
    removeChild(n: any) {
      st.removed++
      n.parentNode = null
    },
  }
  st.doc = {
    body,
    createTextNode: (t: string) => ({ nodeType: 3, text: t }),
    createElement: () => {
      const i = st.created++
      const rect =
        i === 0
          ? { top: 90, bottom: 130, left: 30, width: 300, height: 40 }
          : { top: 100, bottom: 120, left: 50, width: 80, height: 20 }
      return {
        style: { setProperty() {}, },
        parentNode: null,
        children: [] as any[],
        appendChild(c: any) {
          this.children.push(c)
        },
        getBoundingClientRect: () => rect,
      }
    },
  }
  return st
}

let stub: DocStub
let savedDoc: any
let savedGcs: any

beforeEach(() => {
  savedDoc = (globalThis as any).document
  savedGcs = (globalThis as any).getComputedStyle
  stub = makeDoc()
  ;(globalThis as any).document = stub.doc
  ;(globalThis as any).getComputedStyle = () => ({
    getPropertyValue: () => '14px',
    width: '300px',
    whiteSpace: 'pre-wrap',
    borderLeftWidth: '1px',
    borderRightWidth: '1px',
    paddingLeft: '8px',
    paddingRight: '8px',
  })
})

afterEach(() => {
  // ★ 还原全局，别把桩泄漏给同文件后面的用例（本仓既有纪律）
  if (savedDoc === undefined) delete (globalThis as any).document
  else (globalThis as any).document = savedDoc
  if (savedGcs === undefined) delete (globalThis as any).getComputedStyle
  else (globalThis as any).getComputedStyle = savedGcs
})

describe('表单控件选区 · rectOfFieldSelection（算术口径）', () => {
  it('★ 平移量 = 控件 rect + (选区块相对镜像的偏移)，即 95+(100-90)=105 / 25+(50-30)=45', () => {
    const r = rectOfFieldSelection(ctrl(), 2, 6)
    expect(r).toEqual({ top: 105, bottom: 125, left: 45, width: 80 })
  })

  it('★ 必须扣掉 scrollTop / scrollLeft（滚过的控件不扣就会飘出去）', () => {
    const r = rectOfFieldSelection(ctrl({ scrollTop: 12, scrollLeft: 7 }), 2, 6)
    expect(r).toEqual({ top: 93, bottom: 113, left: 38, width: 80 })
  })

  it('★ 用完必须把镜像节点摘掉（每次划词都往 body 挂一个 div = DOM 泄漏）', () => {
    rectOfFieldSelection(ctrl(), 0, 3)
    expect(stub.appended).toBe(1)
    expect(stub.removed).toBe(1)
  })

  it('越界 start/end 被夹住，不抛「切片越界」', () => {
    expect(() => rectOfFieldSelection(ctrl(), 999, 1200)).not.toThrow()
    expect(rectOfFieldSelection(ctrl(), 999, 1200)).not.toBeNull()
  })

  it('计算样式读不到 ⇒ null（调用方据此退回元素级锚点）', () => {
    ;(globalThis as any).getComputedStyle = () => {
      throw new Error('not in document')
    }
    expect(rectOfFieldSelection(ctrl(), 0, 3)).toBeNull()
  })

  it('非控件 / 无 document ⇒ null', () => {
    expect(rectOfFieldSelection({ nodeType: 1, tagName: 'DIV' }, 0, 3)).toBeNull()
    delete (globalThis as any).document
    expect(rectOfFieldSelection(ctrl(), 0, 3)).toBeNull()
  })

  it('内部抛异常也不许漏给全局监听（mouseup 上抛异常会打断整个划词链路）', () => {
    const d = makeDoc()
    d.doc.body.appendChild = () => {
      throw new Error('boom')
    }
    ;(globalThis as any).document = d.doc
    expect(rectOfFieldSelection(ctrl(), 0, 3)).toBeNull()
  })
})
