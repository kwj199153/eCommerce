/**
 * 划词翻译 · 「任意选区都自动弹」行为契约（第 361 轮）
 * ============================================================================
 * 为什么这个文件存在：本轮老板下达了一条**改行为**（不是加按钮）的指令 ——
 *
 *   「原有只支持纯英文划线，改为任意词划线都弹窗，识别英文翻译成中文」
 *
 * 改之前，`startSelectionWatcher` 的 `onMouseUp` 里有一段**语言短路**：
 *
 *     if (CJK.test(text)) { if (state.visible) hide(); return }
 *
 * 即「选中中文就静默不弹」。这段短路**不会有任何报错**、也不违反任何类型，
 * 唯一的症状是「用户选中文没反应」—— 一种典型的**静默回归**。
 * 所以这里必须有一条能把「重新加回 CJK 拦截」直接打红的用例，
 * 否则这轮改动就是一个没有牙齿的负资产。
 *
 * ★ 为什么手搓 DOM 桩，而不是装 jsdom：
 *   `vitest.config.ts` 明确写着「等真有组件用例时再加，别预先装」。
 *   而 `startSelectionWatcher` 用到的 DOM 面**极小且稳定**：只有
 *   `document.addEventListener/removeEventListener`、`window.getSelection()`、
 *   `window.addEventListener`，外加事件目标上的 `closest()` / `nodeType` / `tagName`。
 *   这几样手搓的成本远低于引一个 jsdom 依赖，也不改变测试环境（仍是 node）。
 *
 *   ★ 代价（如实登记）：桩的 `getSelection()` 恒返回 rangeCount=1、恒定矩形，
 *     所以它**证明不了真实浏览器里的几何/选区行为**。本文件只钉「读到的文本
 *     是否会被送去翻译」这一条判定；真实浏览器的端到端（含浮层真的弹出）
 *     由 #1300 的 CDP 探针另测。两者职责不重叠。
 *
 * ★ 顺带钉住的既有不变量（都在同一条 `onMouseUp` 上，改坏哪条都该红）：
 *   - 空白 / 无可译字符（纯标点）不弹
 *   - 超过 MAX_CHARS(2000) 不弹
 *   - 用户关了「自动弹」开关 ⇒ 整条自动路径让路
 *   - 事件发生在浮层内部（`data-stl-layer`）不重触发
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ★ 必须在 import 被测模块之前 mock API 层：`translate()` 会真的发请求。
//   vitest 会把 `vi.mock` 提升到所有 import 之前，这里保持声明顺序只为可读性。
vi.mock('@/api/aigcMedia', () => ({
  translateSelection: vi.fn(async () => ({
    success: true,
    response: {
      translation: 'the translated text',
      source_lang: 'zh',
      target_lang: 'en',
      degraded: false,
    },
  })),
}))

import { translateSelection } from '@/api/aigcMedia'
import {
  useSelectionTranslate,
  LAYER_ATTR,
  TRIGGER_ATTR,
} from '@/composables/useSelectionTranslate'
// ★ 阈值不是「顺手抄一个 350」：抄错了这条用例会在**实现改阈值**时静默通过
import { HOVER_DELAY_MS } from '@/utils/hoverTranslate'

/** 模块级单例 —— 全文件共享同一份状态（与生产一致：设置页与浮层共用一个真源） */
const stl = useSelectionTranslate()

const translateMock = vi.mocked(translateSelection)

// ---------------------------------------------------------------------------
// 最小 DOM 桩
// ---------------------------------------------------------------------------

type DomListener = { type: string; fn: (e: any) => void }

interface Harness {
  /**
   * 派发一次 document mouseup。
   * @param text   普通选区路径下「当前选区内容」（= window.getSelection()）
   * @param target 事件目标
   * @param winSel 覆盖 window.getSelection() 的返回值；缺省等于 `text`。
   *               ★ 表单控件分支**不该**读它，给个不同的值正是为了把这一点打红。
   */
  mouseup: (text: string, target?: any, winSel?: string) => void
  /** 派发一次 document keydown */
  keydown: (key: string) => void
  /** 派发一次 document selectionchange */
  selectionchange: () => void
  /** 设 `document.activeElement`（表单控件分支要看它决定收不收浮层） */
  setActive: (el: any) => void
  /** 只改 window.getSelection() 的返回值，不派发任何事件 */
  setWinSel: (text: string) => void
  /** 派发一次 document mouseover（悬停路径） */
  mouseover: (target: any, relatedTarget?: any) => void
  /** 派发一次 document mouseout（relatedTarget 用来验「移入后代不算离开」） */
  mouseout: (target: any, relatedTarget?: any) => void
  /** 当前挂在 document 上的监听器类型集合（用来验证 teardown 干净） */
  docTypes: () => string[]
  /** 当前挂在 window 上的监听器类型集合（与 document 分开数） */
  winTypes: () => string[]
}

/** 造一个普通元素作为事件目标（非输入框、非浮层内部） */
const plainTarget = () => ({ nodeType: 1, tagName: 'DIV', closest: () => null })

/**
 * 造一个**文本块**目标（悬停路径的候选）。
 *
 * ★ 三个字段是必须的，缺一个相关用例就假绿：
 *   `textContent`（悬停判定的取值真源）、`isContentEditable`（可编辑排除）、
 *   `getBoundingClientRect`（`anchorOf` 在计时器回调里会调它，缺了就抛）。
 *   `contains` 默认返回 false（= 鼠标移出）；验「移入后代」的用例会覆盖它。
 */
const textBlock = (text: string, over: Record<string, unknown> = {}) => ({
  nodeType: 1,
  tagName: 'P',
  textContent: text,
  parentElement: null,
  isContentEditable: false,
  closest: () => null,
  contains: () => false,
  getBoundingClientRect: () => ({ top: 100, bottom: 120, left: 30, width: 300 }),
  ...over,
})

/** 造一个「浮层内部的元素」——`closest` 返回自身，命中 OWN_SELECTOR */
const layerTarget = () => ({ nodeType: 1, tagName: 'DIV', closest: (sel: string) => ({ sel }) })

/**
 * 造一个**表单控件**目标（input / textarea）。
 *
 * ★ 三个字段是必须的，缺一个就会让本文件的用例**假绿**：
 *   `value` + `selectionStart/End`（表单控件分支的唯一真源）、
 *   `getBoundingClientRect`（镜像法在 node 环境返回 null ⇒ 会走 anchorOf 兜底）。
 */
const fieldTarget = (over: Record<string, unknown> = {}) =>
  ({
    nodeType: 1,
    tagName: 'TEXTAREA',
    type: 'textarea',
    closest: () => null,
    value: 'Noise Cancelling Wireless Bluetooth Headphones',
    selectionStart: 0,
    // "Noise Cancelling Wireless" = 前 25 个字符（5+1+10+1+8）
    selectionEnd: 25,
    scrollTop: 0,
    scrollLeft: 0,
    getBoundingClientRect: () => ({ top: 100, bottom: 120, left: 30, width: 300 }),
    ...over,
  }) as any

function mount(): Harness {
  const docListeners: DomListener[] = []
  const winListeners: DomListener[] = []
  let selected = ''
  const rect = { top: 10, bottom: 20, left: 5, width: 100 }

  const documentStub: any = {
    // ★ `activeElement` 必须有：`onSelectionChange` 用「焦点是不是落在表单控件里」
    //   决定要不要收浮层。缺了它，那条判据在桩上恒为 false ⇒ 相关用例假绿。
    activeElement: null,
    addEventListener: (type: string, fn: (e: any) => void) => {
      docListeners.push({ type, fn })
    },
    removeEventListener: (type: string, fn: (e: any) => void) => {
      const i = docListeners.findIndex((l) => l.type === type && l.fn === fn)
      if (i >= 0) docListeners.splice(i, 1)
    },
  }
  const windowStub = {
    addEventListener: (type: string, fn: (e: any) => void) => {
      winListeners.push({ type, fn })
    },
    removeEventListener: (type: string, fn: (e: any) => void) => {
      const i = winListeners.findIndex((l) => l.type === type && l.fn === fn)
      if (i >= 0) winListeners.splice(i, 1)
    },
    getSelection: () => ({
      toString: () => selected,
      rangeCount: 1,
      getRangeAt: () => ({ getBoundingClientRect: () => rect }),
    }),
  }

  ;(globalThis as any).document = documentStub
  ;(globalThis as any).window = windowStub

  teardown = stl.startSelectionWatcher()

  const fire = (type: string, evt: any) =>
    docListeners.filter((l) => l.type === type).forEach((l) => l.fn(evt))

  return {
    mouseup: (text, target = plainTarget(), winSel) => {
      selected = winSel === undefined ? text : winSel
      fire('mouseup', { target })
    },
    keydown: (key) => fire('keydown', { target: plainTarget(), key }),
    selectionchange: () => fire('selectionchange', {}),
    setActive: (el) => {
      documentStub.activeElement = el
    },
    setWinSel: (text) => {
      selected = text
    },
    mouseover: (target, relatedTarget = null) => fire('mouseover', { target, relatedTarget }),
    mouseout: (target, relatedTarget = null) => fire('mouseout', { target, relatedTarget }),
    docTypes: () => docListeners.map((l) => l.type),
    winTypes: () => winListeners.map((l) => l.type),
  }
}

let teardown: (() => void) | null = null

afterEach(() => {
  // ★ 必须在替换下一轮的 globalThis.document 之前 teardown ——
  //   teardown 内部调的是 `document.removeEventListener`，解析的是**当时**的全局。
  //   先换全局再 teardown 会把监听器从新桩上摘（摘不到），旧桩监听器泄漏到下一轮。
  teardown?.()
  teardown = null
})

beforeEach(() => {
  translateMock.mockClear()
  stl.setAutoEnabled(true)
  stl.hide()
})

// ---------------------------------------------------------------------------
// ★ 核心：语言不再构成「弹不弹」的判据
// ---------------------------------------------------------------------------

describe('划词翻译 · 选区自动弹（★ 任意语言）', () => {
  it('★★ 选中「中文」也弹窗 —— 本轮改动的核心（重加 CJK 短路即红）', () => {
    const h = mount()
    h.mouseup('这款保温杯的容量是多少')

    // 改回 `if (CJK.test(text)) return` 会让这里变成 0 次调用
    expect(translateMock).toHaveBeenCalledTimes(1)
    expect(translateMock.mock.calls[0][0]).toMatchObject({ text: '这款保温杯的容量是多少' })
    // 浮层已开（translate 同步置位，不等 await）
    expect(stl.state.visible).toBe(true)
    expect(stl.state.original).toBe('这款保温杯的容量是多少')
  })

  it('中英混排也弹（区里夹一个英文型号，不该被当成中文拦掉）', () => {
    const h = mount()
    h.mouseup('SONY WH-1000XM5 主动降噪耳机')
    expect(translateMock).toHaveBeenCalledTimes(1)
    expect(stl.state.visible).toBe(true)
  })

  it('纯英文仍照弹（回归：放开语言限制不能把原有能力弄丢）', () => {
    const h = mount()
    h.mouseup('noise cancelling headphones')
    expect(translateMock).toHaveBeenCalledTimes(1)
    expect(stl.state.visible).toBe(true)
  })

  it('★ 方向交给后端 auto —— 前端不自己判源语言（否则就是第二份实现）', () => {
    const h = mount()
    h.mouseup('保温杯')
    // 只传 text，不带 target_lang：方向由后端 _detect_lang 决定
    expect(translateMock.mock.calls[0][0]).toEqual({ text: '保温杯' })
    expect(Object.keys(translateMock.mock.calls[0][0] as object)).toEqual(['text'])
  })
})

// ---------------------------------------------------------------------------
// 既有不变量（同一条 onMouseUp 上，改坏即红）
// ---------------------------------------------------------------------------

describe('划词翻译 · 不弹的情形（放开语言限制 ≠ 什么都不拦）', () => {
  it('空白选区不弹', () => {
    const h = mount()
    h.mouseup('   \n  ')
    expect(translateMock).not.toHaveBeenCalled()
    expect(stl.state.visible).toBe(false)
  })

  it('纯标点 / 无一字可译 ⇒ 不弹（MEANINGFUL 仍生效）', () => {
    const h = mount()
    h.mouseup('—— ，、 ！？ ……')
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('数字单独选中不弹？—— 不，数字算可译内容（防误加「必须含字母」的过滤）', () => {
    // 这条是**反向断言**：MEANINGFUL 里含 0-9，所以纯数字应当弹。
    // 若有人为了「更聪明」而把判据收窄成「必须含字母/汉字」，这里会红。
    const h = mount()
    h.mouseup('128')
    expect(translateMock).toHaveBeenCalledTimes(1)
  })

  it(`超过 MAX_CHARS(2000) 不弹`, () => {
    const h = mount()
    h.mouseup('a'.repeat(2001))
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('恰好 2000 字符 ⇒ 弹（边界是 >2000 才拦，别写成 >=）', () => {
    const h = mount()
    h.mouseup('a'.repeat(2000))
    expect(translateMock).toHaveBeenCalledTimes(1)
  })

  it('★ 用户关了「自动弹」⇒ 整条自动路径让路', () => {
    const h = mount()
    stl.setAutoEnabled(false)
    h.mouseup('这款保温杯')
    expect(translateMock).not.toHaveBeenCalled()
    expect(stl.state.visible).toBe(false)
  })

  it('★ 在浮层内部选词 ⇒ 不重触发（防止浮层里复制译文又弹一层）', () => {
    const h = mount()
    h.mouseup('some text inside the layer', layerTarget())
    expect(translateMock).not.toHaveBeenCalled()
  })

  // ★ 第 366 轮：原来这里有一条 `输入框里选字不算划词，不弹`，已被产品决策**反转**
  //   （老板要求「划线选择输入框的内容然后弹出译文」，范围＝全站所有输入框）。
  //   ★ 旧断言**整条删除**，而不是改成 `not.toHaveBeenCalled()` 的反向版：
  //     门禁只该钉住**当前**形态，被反转的旧断言留在原地就成了负资产。
  //   新形态的用例见本文件末尾「表单控件（input / textarea）内划词」一节。
})

// ---------------------------------------------------------------------------
// 监听器生命周期（本地契约，不涉及 DOM 细节）
// ---------------------------------------------------------------------------

describe('划词翻译 · 监听器注册与卸载', () => {
  it('装齐 6 类 document 监听（含第 370 轮新增的 mouseover/mouseout）', () => {
    const h = mount()
    // ★ 第 370 轮 P1 往 document 上加了鼠标悬停那一对。集合判据是**刻意**的：
    //   多挂一类而没人摘，会在这里当场红（比「数个数」精确）。
    expect(new Set(h.docTypes())).toEqual(
      new Set(['mouseup', 'mousedown', 'keydown', 'selectionchange', 'mouseover', 'mouseout']),
    )
  })

  it('window 上仍是 wheel/resize 两类（悬停没有往 window 上加东西）', () => {
    const h = mount()
    expect(new Set(h.winTypes())).toEqual(new Set(['wheel', 'resize']))
  })

  it('teardown 之后不再响应（登出/切视图不该留副作用）', () => {
    const h = mount()
    teardown?.()
    teardown = null
    h.mouseup('这款保温杯')
    expect(translateMock).not.toHaveBeenCalled()
    expect(h.docTypes()).toEqual([])
  })

  it('重复 mount 不叠加监听（单例 install 守卫）', () => {
    const h1 = mount()
    const types1 = h1.docTypes().length
    // 单例：第二次调用直接返回既有 teardown，不会往**新**桩上再挂一遍
    const again = stl.startSelectionWatcher()
    expect(again).toBe(teardown)
    expect(h1.docTypes().length).toBe(types1)
  })
})

// ---------------------------------------------------------------------------
// 生产/消费属性标记（浮层与「译」按钮靠它们互认）
// ---------------------------------------------------------------------------

describe('划词翻译 · 组件自身标记', () => {
  it('两个属性名是稳定契约（浮层与「译」按钮的互认依据）', () => {
    expect(LAYER_ATTR).toBe('data-stl-layer')
    expect(TRIGGER_ATTR).toBe('data-stl-trigger')
  })
})

// ---------------------------------------------------------------------------
// ★ 原文已是目标语言（后端 same_lang）
//   既不是失败，也不是「中文 → 中文」的空译文框 —— 第三种态不许被压成前两种
// ---------------------------------------------------------------------------

describe('划词翻译 · 原文已是中文（后端 same_lang）', () => {
  const sameLangResponse = {
    success: true,
    response: {
      original_text: '这个 listing',
      translation: '',
      source_lang: 'zh',
      target_lang: 'zh',
      degraded: false,
      same_lang: true,
    },
  }

  it('★ 后端回 same_lang ⇒ 标记 sameLang，且**不**当成失败（error 必须为空）', async () => {
    translateMock.mockResolvedValueOnce(sameLangResponse)
    const h = mount()
    h.mouseup('这个 listing')

    await vi.waitFor(() => expect(stl.state.loading).toBe(false))
    expect(stl.state.sameLang).toBe(true)
    expect(stl.state.translation).toBe('')
    // ★ 「空译文 + 报错」与「空译文 + same_lang」是两回事：前者是故障，后者是「不需要翻」
    expect(stl.state.error).toBe('')
  })

  it('★ 非 same_lang 的正常译文 ⇒ sameLang 必须回到 false（别把上一轮的状态漏过来）', async () => {
    translateMock.mockResolvedValueOnce(sameLangResponse)
    const h = mount()
    h.mouseup('这个 listing')
    await vi.waitFor(() => expect(stl.state.sameLang).toBe(true))

    translateMock.mockResolvedValueOnce({
      success: true,
      response: {
        original_text: 'Noise Cancelling Headphones',
        translation: '主动降噪耳机',
        source_lang: 'en',
        target_lang: 'zh',
        degraded: false,
      },
    })
    await stl.translate('Noise Cancelling Headphones', null)

    expect(stl.state.sameLang).toBe(false)
    expect(stl.state.translation).toBe('主动降噪耳机')
  })

  it('★ 「译为英文」= 显式带 target_lang（不带就换不了方向，会被后端原样挡回）', async () => {
    translateMock.mockResolvedValueOnce(sameLangResponse)
    const h = mount()
    h.mouseup('这个 listing')
    await vi.waitFor(() => expect(stl.state.sameLang).toBe(true))

    translateMock.mockResolvedValueOnce({
      success: true,
      response: {
        original_text: '这个 listing',
        translation: 'This listing',
        source_lang: 'zh',
        target_lang: 'en',
        degraded: false,
      },
    })
    await stl.retranslate('en')

    expect(translateMock.mock.calls[1][0]).toEqual({ text: '这个 listing', target_lang: 'en' })
    expect(stl.state.sameLang).toBe(false)
    expect(stl.state.translation).toBe('This listing')
  })
})

// ===========================================================================
// ★ 第 366 轮新增：表单控件（input / textarea）内划词
//
// 老板原话：「是否有办法划线选择输入框的内容然后弹出译文？」→ 范围＝全站所有输入框
//
// 改之前这里有一条 `if (isTextField(e.target)) return` 整条短路。**只删掉它不够** ——
// 控件内的 `range.getBoundingClientRect()` 恒为 0×0，紧接着那行
// `if (!r || (!r.width && !r.height)) return` 会**静默 return**。
// 一个改动两处静默失败点 ⇒ 下面每一条都对着其中一个点。
//
// ★ 本节点钉不住的东西（如实登记，别当成几何回归）：
//   真实浏览器里「镜像法算出的坐标对不对」由 CDP 探针另测
//   （`scripts/cdp-r366c-textfield-selection.mjs`：真实鼠标拖选 + 浮层真的出现 + 锚点落在控件内）。
//   本文件只钉「读哪一份文字 / 哪些不读 / 收不收浮层」这三类**判定**。
// ===========================================================================

describe('划词翻译 · 表单控件（input / textarea）内划词', () => {
  it('★★ 输入框里选字也弹 —— 本轮放开的正是这一条（重加 isTextField 短路即红）', () => {
    const h = mount()
    h.mouseup('', fieldTarget())

    expect(translateMock).toHaveBeenCalledTimes(1)
    // 首尾空白会被 trim（与正文选区同口径）
    expect(translateMock.mock.calls[0][0]).toEqual({ text: 'Noise Cancelling Wireless' })
    expect(stl.state.visible).toBe(true)
  })

  it('★ 文字取自 selectionStart/End，**不是** window.getSelection()（第二真源要红）', () => {
    const h = mount()
    // 刻意让两处给出**不同**的值：控件说 A，window 选区说 B
    h.mouseup('SOMETHING ELSE ENTIRELY', fieldTarget(), 'SOMETHING ELSE ENTIRELY')

    expect(translateMock).toHaveBeenCalledTimes(1)
    expect((translateMock.mock.calls[0][0] as any).text).toBe('Noise Cancelling Wireless')
    expect((translateMock.mock.calls[0][0] as any).text).not.toBe('SOMETHING ELSE ENTIRELY')
  })

  it('★ 锚点落在控件上（镜像法在 node 环境取不到 ⇒ 必须兜底到控件自身，不许「拿不到坐标就不弹」）', () => {
    const h = mount()
    h.mouseup('', fieldTarget())
    expect(stl.state.anchor).toEqual({ top: 100, bottom: 120, left: 30, width: 300 })
  })

  it('★ password 框里选字不弹 —— 绝不把密码送到翻译后端（哪怕用户是主动划选的）', () => {
    const h = mount()
    h.mouseup('', fieldTarget({ tagName: 'INPUT', type: 'password', value: 'hunter2!' }))
    expect(translateMock).not.toHaveBeenCalled()
    expect(stl.state.visible).toBe(false)
  })

  it('★ 不支持选区的 input 类型（selectionStart 为 null）不弹', () => {
    const h = mount()
    for (const type of ['email', 'number', 'date', 'color', 'file', 'range', 'checkbox']) {
      h.mouseup('', fieldTarget({ tagName: 'INPUT', type, selectionStart: null, selectionEnd: null }))
    }
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('空白 / 超长 / 无字符可译 ⇒ 与正文选区同一口径（都不弹）', () => {
    const h = mount()
    h.mouseup('', fieldTarget({ value: '      ', selectionStart: 0, selectionEnd: 6 }))
    h.mouseup('', fieldTarget({ value: '—— ，、 ！？', selectionStart: 0, selectionEnd: 7 }))
    h.mouseup('', fieldTarget({ value: 'a'.repeat(2001), selectionStart: 0, selectionEnd: 2001 }))
    expect(translateMock).not.toHaveBeenCalled()

    // 恰好 2000 字符仍要弹（边界是 >2000 才拦，别写成 >=）
    h.mouseup('', fieldTarget({ value: 'a'.repeat(2000), selectionStart: 0, selectionEnd: 2000 }))
    expect(translateMock).toHaveBeenCalledTimes(1)
  })

  it('用户关了「自动弹」⇒ 输入框这条路也让路（开关的语义是「打扰」，不是「能力」）', () => {
    const h = mount()
    stl.setAutoEnabled(false)
    h.mouseup('', fieldTarget())
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 焦点在控件里时 selectionchange 不得把刚划好的词收掉（否则「划词只见闪一下」）', () => {
    const h = mount()
    h.mouseup('', fieldTarget())
    expect(stl.state.visible).toBe(true)

    const ta = fieldTarget()
    h.setActive(ta)
    // 控件内的选区**不**体现在 window.getSelection() 上 ⇒ 此刻它读到空串
    h.setWinSel('')
    h.selectionchange()
    expect(stl.state.visible).toBe(true)
  })

  it('对照：焦点不在控件里 ⇒ selectionchange 判空仍然收浮层（原有行为不许被削弱）', () => {
    const h = mount()
    h.mouseup('这款保温杯')
    expect(stl.state.visible).toBe(true)

    h.setActive(null)
    h.setWinSel('')
    h.selectionchange()
    expect(stl.state.visible).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 悬停翻译（第 370 轮 P1）—— 开关缺省为关
// ---------------------------------------------------------------------------

/**
 * ★ 这三条用 `vi.resetModules()` + 动态 import **重新加载模块**，而不是读
 *   `stl.hoverEnabled.value` —— 后者只说明「此刻的值」，证明不了「缺省值」。
 *   而「缺省为关」正是本轮最重要的安全属性（产品默认不给打扰），必须钉在
 *   **模块初始化**那一刻：`readHoverEnabled()` 的判据必须是 `=== '1'`。
 *
 *   node 环境本来就没有 localStorage（catch 分支）,那是「隐私模式/被策略禁用」的
 *   同一路径；这里再显式桩三种取值，把判据的三个方向都钉住。
 */
describe('划词翻译 · 悬停开关缺省为关（判据 === "1"，与自动弹的缺省开相反）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const loadWith = async (stored: string | null) => {
    vi.resetModules()
    vi.stubGlobal('localStorage', {
      getItem: () => stored,
      setItem: () => {},
      removeItem: () => {},
    })
    return import('@/composables/useSelectionTranslate')
  }

  it('★ 没有这个键 ⇒ false（缺省关：鼠标路过就弹是打扰，产品默认不给）', async () => {
    const mod = await loadWith(null)
    expect(mod.hoverEnabled.value).toBe(false)
  })

  it('★ 存的是 "0" ⇒ false（防把判据写成 `!== "0"` —— 那会让显式关掉反而不生效）', async () => {
    const mod = await loadWith('0')
    expect(mod.hoverEnabled.value).toBe(false)
  })

  it('★ 只有显式存过 "1" ⇒ true', async () => {
    const mod = await loadWith('1')
    expect(mod.hoverEnabled.value).toBe(true)
  })

  it('对照：自动弹的方向相反 —— 没有这个键时它是**开**的', async () => {
    const mod = await loadWith(null)
    expect(mod.autoEnabled.value).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 悬停触发（打开开关后）
// ---------------------------------------------------------------------------

describe('划词翻译 · 悬停触发', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    stl.setHoverEnabled(true)
  })

  afterEach(() => {
    stl.setHoverEnabled(false) // 不污染其它 describe
    vi.useRealTimers()
  })

  it('停满阈值 ⇒ 翻一次，且只传 text（方向仍归后端判，前端不自己定）', () => {
    const h = mount()
    h.mouseover(textBlock('Noise Cancelling Headphones'))
    expect(translateMock).not.toHaveBeenCalled() // 还没到点

    vi.advanceTimersByTime(HOVER_DELAY_MS)

    expect(translateMock).toHaveBeenCalledTimes(1)
    expect(translateMock.mock.calls[0][0]).toEqual({ text: 'Noise Cancelling Headphones' })
    expect(Object.keys(translateMock.mock.calls[0][0] as object)).toEqual(['text'])
  })

  it('★ 阈值差 1ms 就移开 ⇒ 一次都不翻（这是「不打扰」的全部意义）', () => {
    const h = mount()
    const el = textBlock('Noise Cancelling Headphones')
    h.mouseover(el)
    vi.advanceTimersByTime(HOVER_DELAY_MS - 1)
    h.mouseout(el)
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 鼠标在本块的后代之间移动 ⇒ 不重置计时（否则永远等不满阈值）', () => {
    const h = mount()
    const child = { nodeType: 1, tagName: 'B' }
    const el = textBlock('Noise Cancelling Headphones', {
      // 桩：child 是本块的后代 ⇒ onMouseOut 必须据此判定「没真的离开」
      contains: (n: unknown) => n === child,
    })
    h.mouseover(el)
    vi.advanceTimersByTime(HOVER_DELAY_MS - 50)
    h.mouseout(el, child) // 移入自己的后代：不算离开
    vi.advanceTimersByTime(100)
    expect(translateMock).toHaveBeenCalledTimes(1)
  })

  it('关掉开关 ⇒ 悬停整条让路', () => {
    stl.setHoverEnabled(false)
    const h = mount()
    h.mouseover(textBlock('Noise Cancelling Headphones'))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 关掉开关会取消**已经排队**的那一个（否则「刚关掉又弹一个」）', () => {
    const h = mount()
    h.mouseover(textBlock('Noise Cancelling Headphones'))
    stl.setHoverEnabled(false)
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 已有选区 ⇒ 不悬停触发（用户已经拿到浮层了，别再打扰）', () => {
    const h = mount()
    h.setWinSel('already selected text')
    h.mouseover(textBlock('Noise Cancelling Headphones'))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 浮层内部 ⇒ 不触发（鼠标移到译文上不该再弹一层）', () => {
    const h = mount()
    h.mouseover(textBlock('Noise Cancelling Headphones', { closest: (sel: string) => ({ sel }) }))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 表单控件内 ⇒ 不触发（悬停翻译会和打字打架）', () => {
    const h = mount()
    h.mouseover(fieldTarget())
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ contenteditable 内 ⇒ 不触发（它有真 range，划词能用，但悬停不该碰）', () => {
    const h = mount()
    h.mouseover(textBlock('Noise Cancelling Headphones', { isContentEditable: true }))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('纯中文文本块 ⇒ 不触发（不含拉丁字母，方向本来就是译成中文）', () => {
    const h = mount()
    h.mouseover(textBlock('这款保温杯的容量是多少毫升'))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 中英混排 ⇒ 触发（别为了「更严格」把这条真实商品标题形态误杀）', () => {
    const h = mount()
    h.mouseover(textBlock('SONY WH-1000XM5 主动降噪耳机'))
    vi.advanceTimersByTime(HOVER_DELAY_MS)
    expect(translateMock).toHaveBeenCalledTimes(1)
  })

  it('超过悬停上限的字块 ⇒ 不触发（上限比划词的 2000 小得多）', () => {
    const h = mount()
    h.mouseover(textBlock('a'.repeat(201)))
    vi.advanceTimersByTime(HOVER_DELAY_MS * 3)
    expect(translateMock).not.toHaveBeenCalled()
  })

  it('★ 浮层已经显示着同一段文本 ⇒ 不重弹（这就是「同文本去重」，不需要 LRU 缓存）', () => {
    const h = mount()
    // 先用划词那条路把浮层打开，原文就是待悬停的这段
    h.mouseup('Noise Cancelling Headphones')
    expect(translateMock).toHaveBeenCalledTimes(1)
    translateMock.mockClear()

    h.setWinSel('') // 清掉选区，否则会被 has-selection 挡掉（挡掉就证不了去重）
    h.mouseover(textBlock('Noise Cancelling Headphones'))
    vi.advanceTimersByTime(HOVER_DELAY_MS)

    expect(translateMock).not.toHaveBeenCalled()
    expect(stl.state.original).toBe('Noise Cancelling Headphones')
  })

  it('对照：浮层显示的是**别的**文本 ⇒ 悬停照常触发（去重只对同文本生效）', () => {
    const h = mount()
    h.mouseup('something else entirely')
    translateMock.mockClear()
    h.setWinSel('')

    h.mouseover(textBlock('Noise Cancelling Headphones'))
    vi.advanceTimersByTime(HOVER_DELAY_MS)
    expect(translateMock).toHaveBeenCalledTimes(1)
  })
})

// ---------------------------------------------------------------------------
// 显示模式（双语 / 仅译文）与开关落本机
// ---------------------------------------------------------------------------

describe('划词翻译 · 显示模式与偏好落本机', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    stl.setDisplayMode('bilingual')
  })

  it('缺省是「双语」（可自证：只有译文时用户无法核对翻没翻错）', () => {
    expect(stl.displayMode.value).toBe('bilingual')
  })

  it('★ 必须走 setter 才落本机 —— 直接改 ref 会「设置页记得、下次进来忘了」', () => {
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem,
      removeItem: () => {},
    })
    stl.setDisplayMode('target')
    expect(stl.displayMode.value).toBe('target')
    expect(setItem).toHaveBeenCalledWith('selection_translate_display', 'target')
  })

  it('悬停开关同样走 setter 落本机', () => {
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem,
      removeItem: () => {},
    })
    stl.setHoverEnabled(true)
    expect(setItem).toHaveBeenCalledWith('selection_translate_hover', '1')
    stl.setHoverEnabled(false)
    expect(setItem).toHaveBeenLastCalledWith('selection_translate_hover', '0')
  })
})
