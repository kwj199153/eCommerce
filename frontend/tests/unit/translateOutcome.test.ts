/**
 * 翻译四态判定（`utils/translateOutcome.ts`）· 唯一真源
 * ============================================================================
 * 后端这条契约是**四态**，不是布尔：`ok` / `same_lang` / `degraded` / `error`。
 * 压成两态就是本仓反复记录的**三态压两态** —— 空译文既可能是「不需要翻」，
 * 也可能是「翻了但结果是空」，界面无从分辨。
 *
 * 本文件做三件事：
 *   1. 直接测这个纯函数（边界 + 优先级）。四态覆盖**只此一处**：
 *      `selectionTranslate.test.ts` 里一次都没出现 `resolveTranslateOutcome`，
 *      删本文件等于把四态覆盖整块丢掉。
 *   2. 用 **AST** 盯住消费方没有绕开真源、自己读后端字段 ——
 *      判定跟着界面走的话，「同一份响应在不同入口显示成不同话术」
 *      **不会抛任何异常**，只能靠形态门禁钉。
 *   3. 盯住真源文件本身保持**纯叶子**（不 import api），这样它能零成本单测，
 *      也不会被 api 层的 mock 牵着走。
 *
 * 为什么是 AST 而不是字符串匹配：本仓记录过「docstring / 注释里引一句代码
 * ⇒ 字符串判据恒真」。**注释不在 AST 里**，属性访问、import 都在。
 *
 * 环境：`vitest.config.ts` 是 `environment: 'node'`，不装 jsdom ⇒ 这里不挂载组件，
 *      只测纯函数 + 静态形态。界面里的真实渲染由 CDP 探针另测，职责不重叠。
 */
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import {
  TRANSLATE_UNAVAILABLE,
  resolveTranslateOutcome,
  type TranslateResponseLike,
} from '@/utils/translateOutcome'
import type { SelectionTranslation } from '@/api/aigcMedia'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
const read = (rel: string) =>
  readFileSync(path.join(ROOT, rel), 'utf8').replace(/\r\n/g, '\n')

// ===========================================================================
// 一、纯函数：后端响应 → UI 四态
// ===========================================================================

describe('resolveTranslateOutcome —— 四态不许压成两态', () => {
  it('① 正常译文 ⇒ ok，带上语言方向', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: {
        original_text: 'Noise Cancelling Headphones',
        translation: '主动降噪耳机',
        source_lang: 'en',
        target_lang: 'zh',
        degraded: false,
      },
    })
    expect(o.kind).toBe('ok')
    expect(o.translation).toBe('主动降噪耳机')
    expect(o.sourceLang).toBe('en')
    expect(o.targetLang).toBe('zh')
    expect(o.message).toBe('')
  })

  it('② 原文已是目标语言 ⇒ same_lang，**不是失败**（message 必须为空）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: {
        original_text: '这款保温杯',
        translation: '',
        source_lang: 'zh',
        target_lang: 'zh',
        degraded: false,
        same_lang: true,
      },
    })
    expect(o.kind).toBe('same_lang')
    // ★ 「空译文 + 报错」与「空译文 + same_lang」是两回事：前者是故障，后者是「不需要翻」
    expect(o.message).toBe('')
    expect(o.translation).toBe('')
    // 语言方向仍要回带 —— 界面据此显示「已是中文」并给出「译为英文」
    expect(o.targetLang).toBe('zh')
  })

  it('③ 后端降级 ⇒ degraded（**不是** ok，即便回了半截译文）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { translation: '', source_lang: 'en', target_lang: 'zh', degraded: true },
    })
    expect(o.kind).toBe('degraded')
    expect(o.message).toBe(TRANSLATE_UNAVAILABLE)
    expect(o.translation).toBe('')
  })

  it('④ 请求层失败（无响应体 / success=false）⇒ error', () => {
    for (const res of [
      undefined,
      null,
      {},
      { success: false, response: { translation: 'x', degraded: false } },
      { success: true },
      { success: true, response: null },
    ]) {
      const o = resolveTranslateOutcome(res as never)
      expect(o.kind).toBe('error')
      expect(o.message).toBe(TRANSLATE_UNAVAILABLE)
    }
  })

  // ---- 排序与边界：这几条是「三态压两态」最可能的复发点 ----

  it('★ degraded 优先于 same_lang：两者同时为真 ⇒ 判 degraded（不判「已是中文」）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { degraded: true, same_lang: true, translation: '', source_lang: 'zh', target_lang: 'zh' },
    })
    expect(o.kind).toBe('degraded')
  })

  it('★ degraded 优先于半截译文：降级时回了内容也不算 ok（半截译文比空更危险）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { degraded: true, translation: '半截结', source_lang: 'en', target_lang: 'zh' },
    })
    expect(o.kind).toBe('degraded')
    expect(o.translation).toBe('')
  })

  it('★ 纯空白译文不算 ok（否则界面渲染一个空块，与 degraded 不可区分）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { translation: '   \n ', degraded: false, source_lang: 'en', target_lang: 'zh' },
    })
    expect(o.kind).toBe('degraded')
  })

  it('译文首尾空白**原样保留**（后端可能刻意留格式，交给渲染层决定）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { translation: '  x  ', degraded: false, source_lang: 'en', target_lang: 'zh' },
    })
    expect(o.kind).toBe('ok')
    expect(o.translation).toBe('  x  ')
  })

  it('失败时不回带语言方向（否则界面会展示一个失败结果的语言标签）', () => {
    const o = resolveTranslateOutcome({
      success: true,
      response: { degraded: true, source_lang: 'en', target_lang: 'zh' },
    })
    expect(o.sourceLang).toBe('')
    expect(o.targetLang).toBe('')
  })

  it('★ 编译期漂移闸：后端 `SelectionTranslation` 必须能直接喂进本模块的输入类型', () => {
    // 若 `api/aigcMedia.ts` 改了字段（改名 / 改类型）而 `translateOutcome.ts` 没跟上，
    // 下面这行会**编译失败**（vue-tsc / vitest 转换阶段）—— 而不是静默判错。
    const fromApi: SelectionTranslation = {
      original_text: 'Noise Cancelling Headphones',
      translation: '主动降噪耳机',
      source_lang: 'en',
      target_lang: 'zh',
      degraded: false,
    }
    const feed: TranslateResponseLike = fromApi
    expect(resolveTranslateOutcome({ success: true, response: feed }).kind).toBe('ok')
  })
})

// ===========================================================================
// 二、源码级门禁：AST（注释不参与）
// ===========================================================================
//
// 为什么必须钉消费方：判定若跟着界面走，每加一个文本翻译入口就多一份实现，
// 而「同一份后端故障在一处显示成『已是中文』、另一处显示成空框」**不报错**。

function parse(src: string): ts.SourceFile {
  return ts.createSourceFile('probe.ts', src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
}

function walk(node: ts.Node, fn: (n: ts.Node) => void): void {
  fn(node)
  node.forEachChild((c) => walk(c, fn))
}

/** 所有 `a.b` / `a?.b` 里那个 `b`（属性访问的末段名） */
function memberNames(sf: ts.SourceFile): string[] {
  const out: string[] = []
  walk(sf, (n) => {
    if (ts.isPropertyAccessExpression(n) || ts.isPropertyAccessChain(n)) {
      out.push(n.name.text)
    }
  })
  return out
}

/** `import ... from 'mod'` 的 { mod: [符号...] } */
function importsOf(sf: ts.SourceFile): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const st of sf.statements) {
    if (!ts.isImportDeclaration(st)) continue
    const mod = (st.moduleSpecifier as ts.StringLiteral).text
    const names: string[] = []
    const clause = st.importClause
    if (clause?.name) names.push(clause.name.text)
    const bindings = clause?.namedBindings
    if (bindings && ts.isNamedImports(bindings)) {
      for (const el of bindings.elements) names.push(el.name.text)
    }
    out[mod] = [...(out[mod] ?? []), ...names]
  }
  return out
}

const OUTCOME_REL = 'src/utils/translateOutcome.ts'
const COMPOSABLE_REL = 'src/composables/useSelectionTranslate.ts'

describe('useSelectionTranslate.ts —— 消费同一份判定真源', () => {
  const sf = parse(read(COMPOSABLE_REL))

  it('★ 从 `@/utils/translateOutcome` 取判定（真源只有一份）', () => {
    const imports = importsOf(sf)
    expect(imports['@/utils/translateOutcome']).toContain('resolveTranslateOutcome')
  })

  it('★ 不自己读 `d.same_lang` / `d.degraded`（判定已收口）', () => {
    const members = memberNames(sf)
    expect(members).not.toContain('same_lang')
    expect(members).not.toContain('degraded')
    // ★ 只盯**后端原始字段**：`outcome.translation` 是收口后的结果，本来就该读。
    //   （曾经在这里顺手加了 `not.toContain('translation')`，直接把自己判红 ——
    //     判据写宽了会把正确写法一起否掉。）
    expect(memberNames(sf)).not.toContain('original_text')
  })
})

describe('translateOutcome.ts —— 纯叶子真源', () => {
  it('真源文件本身不许 import api（保持纯叶子，可零成本单测）', () => {
    const sfOutcome = parse(read(OUTCOME_REL))
    const imports = importsOf(sfOutcome)
    expect(Object.keys(imports)).not.toContain('@/api/aigcMedia')
    expect(Object.keys(imports).filter((m) => m.startsWith('@/'))).toEqual([])
  })
})
