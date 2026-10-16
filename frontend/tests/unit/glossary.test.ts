/**
 * 店铺术语表 · 前端口径契约（第 369 轮 P0）
 * ============================================================================
 * 为什么这个文件必须存在
 * ============================================================================
 * 服务端 `parse_glossary`（`backend/modules/aigc_media/glossary.py`）是**刻意宽松
 * 跳错**的：非法行静默跳过、不抛异常、不注入。这在服务端是对的（用户手打的笔误
 * 不该升级成故障），但它把「你这张表实际被识别成几条」这件事变成了**只有前端能说**。
 * 于是前端有了第二份解析 —— 而第二份解析就是**口径分叉的温床**：
 *
 *     设置页说「已识别 5 条」，后端实际只用了 4 条 ⇒ 用户拿着一张自己以为有效的表，
 *     却怎么都不明白为什么某个词没按他的译法走。
 *
 * 所以下面的断言分两类，各有不可替代的作用：
 *
 *   · **样本向量**（第一节）：**逐条抄自** `backend/tests/test_selection_glossary.py`
 *     的第 66–113 行。抄，是为了让「后端认什么」与「前端认什么」是同一组事实。
 *     改任何一边的样本都必须同步另一边，否则两边会各自绿着漂移。
 *   · **跨语言口径**（`A＝B=C` 的切点、`\u2028` 换行）：这两条是**Python 与 JS 的
 *     语言级差异**造成的隐蔽分叉，后端测试**覆盖不到**（它只测 Python 行为），
 *     只有这里能钉住。
 *
 * 常量层面的对账（`MAX_ENTRIES` / 分隔符 / 字数上限）由
 * `scripts/check-glossary-parity.cjs` 负责（它直接读两端源码 AST）——
 * 那是**另一个**不可替代的面，不是本文件的重复劳动：
 *     只对常量 ⇒ 算法漂了不知道；只对样本 ⇒ 常量漂了不知道。
 *
 * ★ 环境：vitest 是 `environment: 'node'`（见 `vitest.config.ts`），
 *   **没有 `localStorage`**。所以 storage 相关的用例自带一个 Map 桩；
 *   而「无 localStorage 时 `loadGlossary()` 回空串」这条也**必须单独钉住** ——
 *   它正是 `tests/unit/selectionTranslate.test.ts` 那条
 *   `Object.keys(payload) === ['text']` 断言成立的前提。
 */
import { describe, it, expect, afterEach } from 'vitest'
import {
  GLOSSARY_SEPARATORS,
  MAX_GLOSSARY_CHARS,
  MAX_GLOSSARY_ENTRIES,
  clampGlossary,
  glossaryPayload,
  glossaryStorageKey,
  loadGlossary,
  parseGlossary,
  readCurrentShopId,
  saveGlossary,
  summarizeGlossary,
} from '@/utils/glossary'

// ---------------------------------------------------------------------------
// 最小 localStorage 桩（node 环境没有）
// ---------------------------------------------------------------------------

class MemoryStorage {
  private m = new Map<string, string>()
  getItem(k: string): string | null {
    return this.m.has(k) ? (this.m.get(k) as string) : null
  }
  setItem(k: string, v: string): void {
    this.m.set(k, String(v))
  }
  removeItem(k: string): void {
    this.m.delete(k)
  }
  has(k: string): boolean {
    return this.m.has(k)
  }
}

/** 装一个可用的存储 */
function installStorage(): MemoryStorage {
  const s = new MemoryStorage()
  ;(globalThis as any).localStorage = s
  return s
}

/** 装一个「被策略禁用」的存储：读写都抛（隐私模式的真实形态） */
function installBrokenStorage(): void {
  ;(globalThis as any).localStorage = {
    getItem: () => {
      throw new Error('storage disabled')
    },
    setItem: () => {
      throw new Error('storage disabled')
    },
    removeItem: () => {
      throw new Error('storage disabled')
    },
  }
}

afterEach(() => {
  // ★ 必须删干净：本文件里有多条用例依赖「没有 localStorage」这条前提，
  //   而 vitest 同一文件内的用例共享同一份全局。
  delete (globalThis as any).localStorage
})

// ===========================================================================
// 一 · 解析口径（样本逐条对齐 backend/tests/test_selection_glossary.py）
// ===========================================================================

describe('术语表解析 · 与后端同一个口径', () => {
  it('基本行：`原文=译文`，每行一条', () => {
    // 对齐后端 test_parse_basic_lines
    expect(parseGlossary('Noise Cancelling=主动降噪\nWaterproof=防水')).toEqual([
      { source: 'Noise Cancelling', target: '主动降噪' },
      { source: 'Waterproof', target: '防水' },
    ])
  })

  it('全角 `＝` 也认（中文输入法下很容易打出来）', () => {
    // 对齐后端 test_parse_accepts_fullwidth_separator
    expect(parseGlossary('Gift Box＝礼盒装')).toEqual([
      { source: 'Gift Box', target: '礼盒装' },
    ])
  })

  it('空行与 `#` 注释行跳过（注释可用来分组标注）', () => {
    // 对齐后端 test_parse_skips_blank_and_comment_lines
    const raw = [
      '# 品牌名',
      '',
      'Noise Cancelling=主动降噪',
      '   ',
      '# 品类',
      'Gift Box=礼盒装',
    ].join('\n')
    expect(parseGlossary(raw)).toEqual([
      { source: 'Noise Cancelling', target: '主动降噪' },
      { source: 'Gift Box', target: '礼盒装' },
    ])
  })

  it('残行跳过且**不抛异常**（宽松跳错：用户的笔误不该升级成故障）', () => {
    // 对齐后端 test_parse_skips_malformed_lines_without_raising 的 5 个参数化样本
    const badSamples = ['没有等号的一行', '=只有译文', '只有原文=', '= ', '  =  ']
    for (const bad of badSamples) {
      expect(() => parseGlossary(bad)).not.toThrow()
      expect(parseGlossary(bad), `样本 ${JSON.stringify(bad)} 应当被跳过`).toEqual([])
    }
  })

  it('同名前取**首次**出现（用户把新写法写在上面覆盖下面误留的旧行）', () => {
    // 对齐后端 test_parse_keeps_first_occurrence_on_duplicate
    expect(parseGlossary('Earbuds=耳机\nEarbuds=耳塞\n')).toEqual([
      { source: 'Earbuds', target: '耳机' },
    ])
  })

  it('★ 只按**第一个**分隔符切（`Note=A=B` ⇒ 译文里保留 `A=B`）', () => {
    // 对齐后端 test_parse_splits_on_first_separator_only
    expect(parseGlossary('Note=A=B')).toEqual([{ source: 'Note', target: 'A=B' }])
  })

  it('★★ 分隔符的尝试顺序＝先半角后全角（`A＝B=C` 的切点是**那个半角** `=`）', () => {
    // ★ 这条钉的是**跨语言口径**，不是某一边的实现细节：
    //   后端是 `for sep in ("=", "＝")` —— 命中即 break，所以位置更靠前的全角 `＝`
    //   反而**不是**切点。JS 这边必须同序（GLOSSARY_SEPARATORS 的顺序即优先级）。
    //   「优化」成「取最先出现的分隔符」会让这里红 —— 那正是静默分叉的形态。
    expect(GLOSSARY_SEPARATORS[0]).toBe('=')
    expect(parseGlossary('A＝B=C')).toEqual([{ source: 'A＝B', target: 'C' }])
  })

  it('条数上限 100（防呆：贴错一份大 CSV 会让每次划词都多烧 token）', () => {
    // 对齐后端 test_parse_caps_entry_count
    const raw = Array.from({ length: MAX_GLOSSARY_ENTRIES + 50 }, (_, i) => `k${i}=v${i}`).join('\n')
    const entries = parseGlossary(raw)
    expect(entries).toHaveLength(MAX_GLOSSARY_ENTRIES)
    expect(entries[0]).toEqual({ source: 'k0', target: 'v0' })
    expect(entries[entries.length - 1]).toEqual({
      source: `k${MAX_GLOSSARY_ENTRIES - 1}`,
      target: `v${MAX_GLOSSARY_ENTRIES - 1}`,
    })
  })

  it('空输入一律得到空表（含 null / undefined —— 这是个会收到缺省值的入口）', () => {
    // 对齐后端 test_parse_empty_input_yields_nothing
    for (const empty of ['', '   ', '\n\n', null, undefined]) {
      expect(parseGlossary(empty as any), `样本 ${JSON.stringify(empty)}`).toEqual([])
    }
  })

  it('★ 换行符口径复刻 Python `str.splitlines()`，不只是 `\\n`', () => {
    // ★ 这条是**语言级差异**造出来的隐蔽分叉，后端测试覆盖不到：
    //   Python 的 splitlines 认 9 种行分隔符，JS 的 split('\n') 只认 \n。
    //   用户从 Word / Excel / 网页粘贴文本时 `\u2028`（LINE SEPARATOR）是真实存在的，
    //   不对齐就会出现「前端算 1 条、后端算 2 条」。
    for (const brk of ['\u2028', '\u2029', '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x85']) {
      const raw = `A=甲${brk}B=乙`
      expect(parseGlossary(raw), `分隔符 U+${brk.codePointAt(0)!.toString(16)}`).toEqual([
        { source: 'A', target: '甲' },
        { source: 'B', target: '乙' },
      ])
    }
    // `\r\n` 在 JS 侧会切出一个空元素，但空行本来就被跳过 ⇒ 结果集等价
    expect(parseGlossary('A=甲\r\nB=乙\r')).toEqual([
      { source: 'A', target: '甲' },
      { source: 'B', target: '乙' },
    ])
  })
})

// ===========================================================================
// 二 · 预览读数（把后端**刻意静默**的跳错在前端可见化）
// ===========================================================================

describe('术语表读数 · 把静默的跳错显式化', () => {
  it('正常表：declared 与 entries 相等，skipped 为 0', () => {
    const s = summarizeGlossary('A=甲\nB=乙\n# 注释不算')
    expect(s.entries).toHaveLength(2)
    expect(s.declared).toBe(2)
    expect(s.skipped).toBe(0)
    expect(s.capped).toBe(false)
    expect(s.oversize).toBe(false)
  })

  it('★ 有坏行 ⇒ skipped 如实上报（这是用户唯一的反馈渠道）', () => {
    const s = summarizeGlossary('A=甲\n这行没等号\nB=乙\n=只有译文')
    expect(s.entries).toHaveLength(2)
    expect(s.declared).toBe(4)
    expect(s.skipped).toBe(2)
  })

  it('重复原文也算「未生效」（用户需要知道它没被采用）', () => {
    const s = summarizeGlossary('Earbuds=耳机\nEarbuds=耳塞')
    expect(s.entries).toHaveLength(1)
    expect(s.declared).toBe(2)
    expect(s.skipped).toBe(1)
  })

  it('★ 触条数上限 ⇒ capped 为真（后面的行会被忽略，必须显式告知）', () => {
    const many = Array.from({ length: MAX_GLOSSARY_ENTRIES + 10 }, (_, i) => `k${i}=v${i}`).join('\n')
    expect(summarizeGlossary(many).capped).toBe(true)
  })

  it('★ 有效条目不足上限时，即使总行数超上限也**不算** capped（不是「行多就触顶」）', () => {
    // 200 行里一半是坏行 ⇒ 有效 100 条内的边界：这里刻意造 90 条有效 + 60 行坏行
    const raw = [
      ...Array.from({ length: 90 }, (_, i) => `k${i}=v${i}`),
      ...Array.from({ length: 60 }, () => '这行没等号'),
    ].join('\n')
    const s = summarizeGlossary(raw)
    expect(s.entries).toHaveLength(90)
    expect(s.capped).toBe(false) // 没取满 100 ⇒ 没有行因上限被丢
    expect(s.skipped).toBe(60)
  })

  it('超字数 ⇒ oversize 为真（超限部分不会随请求发出）', () => {
    expect(summarizeGlossary('A=甲').oversize).toBe(false)
    expect(summarizeGlossary('x'.repeat(MAX_GLOSSARY_CHARS + 1)).oversize).toBe(true)
  })
})

// ===========================================================================
// 三 · 传输前裁剪（存储无损、传输有界）
// ===========================================================================

describe('术语表裁剪 · 按完整行裁，不截半条', () => {
  it('未超限时**原样**返回（这条很重要：不许顺手 normalize 用户的文本）', () => {
    const raw = 'A=甲\n\n# 注释\nB=乙'
    expect(clampGlossary(raw)).toBe(raw)
  })

  it('超限时结果长度不超过上限', () => {
    const raw = Array.from({ length: 400 }, (_, i) => `key-${i}=译文-${i}`).join('\n')
    expect(raw.length).toBeGreaterThan(MAX_GLOSSARY_CHARS)
    expect(clampGlossary(raw).length).toBeLessThanOrEqual(MAX_GLOSSARY_CHARS)
  })

  it('★ 绝不截出「半条术语」—— 结果的每一行都必须原样出现在原文的行集合里', () => {
    // ★ 这是本裁剪存在的唯一理由：`slice(0, 4000)` 会把 `Noise Cancelling=主动降`
    //   截成一条**看起来合法**的术语，静默给出错译法。按行裁至多丢掉整条。
    const lines = Array.from({ length: 400 }, (_, i) => `key-${i}=译文-${i}`)
    const raw = lines.join('\n')
    const kept = clampGlossary(raw)
    const origin = new Set(lines)
    for (const line of kept.split('\n')) {
      expect(origin.has(line), `被截出的行不在原文里：${JSON.stringify(line)}`).toBe(true)
    }
    // 而且确实裁掉了东西（否则本用例是空跑）
    expect(kept.length).toBeLessThan(raw.length)
  })

  it('首行本身就超长 ⇒ 空串（不注入；此时设置页的 oversize 提示已在亮）', () => {
    expect(clampGlossary('x'.repeat(MAX_GLOSSARY_CHARS + 10))).toBe('')
  })
})

// ===========================================================================
// 四 · 按店铺存取
// ===========================================================================

describe('术语表存储 · 按店铺分键', () => {
  it('存储键按 shop_id 分（两个店铺共用一份必然互相污染）', () => {
    const a = glossaryStorageKey('shop_a')
    const b = glossaryStorageKey('shop_b')
    expect(a).not.toBe(b)
    expect(a).toContain('shop_a')
  })

  it('未选店铺时退到专用键，**不是**全局共用键（否则 A 店的术语表会落到所有人头上）', () => {
    const none = glossaryStorageKey(null)
    expect(none).toBe(glossaryStorageKey(undefined))
    expect(none).toBe(glossaryStorageKey(''))
    expect(none).not.toBe(glossaryStorageKey('shop_a'))
  })

  it('存进去能读回来（同一店铺）', () => {
    installStorage()
    expect(saveGlossary('shop_a', 'A=甲')).toBe(true)
    expect(loadGlossary('shop_a')).toBe('A=甲')
  })

  it('★ 不同店铺互不可见（租户隔离的偏好层体现）', () => {
    installStorage()
    saveGlossary('shop_a', 'A=甲')
    saveGlossary('shop_b', 'B=乙')
    expect(loadGlossary('shop_a')).toBe('A=甲')
    expect(loadGlossary('shop_b')).toBe('B=乙')
    expect(loadGlossary('shop_c')).toBe('')
  })

  it('清空内容 ⇒ 删键（不积累空值键）', () => {
    const s = installStorage()
    saveGlossary('shop_a', 'A=甲')
    saveGlossary('shop_a', '   ')
    expect(s.has(glossaryStorageKey('shop_a'))).toBe(false)
    expect(loadGlossary('shop_a')).toBe('')
  })

  it('★ 写失败必须返回 false（否则界面回一句「已保存」而实际丢了）', () => {
    installBrokenStorage()
    expect(saveGlossary('shop_a', 'A=甲')).toBe(false)
    // 空内容走 removeItem 那条分支，同样要如实返回 false
    expect(saveGlossary('shop_a', '')).toBe(false)
  })

  it('存不进不影响读：读口一律回空串，翻译照常工作（只是不带本店译法）', () => {
    installBrokenStorage()
    expect(loadGlossary('shop_a')).toBe('')
  })

  it('★ node 环境（无 localStorage）下读回空串 —— 既有请求体契约成立的前提', () => {
    // 这条与 tests/unit/selectionTranslate.test.ts 的
    // `Object.keys(payload) === ['text']` 是同一件事的两面：
    // 测试环境没有 localStorage ⇒ 这里必须**不抛**，否则那条既有断言会变成报错而不是通过。
    expect((globalThis as any).localStorage).toBeUndefined()
    expect(loadGlossary('shop_a')).toBe('')
    expect(readCurrentShopId()).toBe('')
  })

  it('readCurrentShopId 直读 current_shop_id（与 api/request.ts 的私有 getShopId 同口径）', () => {
    const s = installStorage()
    expect(readCurrentShopId()).toBe('')
    s.setItem('current_shop_id', 'shop_a')
    expect(readCurrentShopId()).toBe('shop_a')
  })
})

// ===========================================================================
// 五 · 请求体字段（空表连键都不带）
// ===========================================================================

describe('术语表请求体 · 空表不带键', () => {
  it('★★ 没配术语表 ⇒ `{}`（连键都没有）', () => {
    installStorage()
    expect(glossaryPayload('shop_a')).toEqual({})
    expect(Object.keys(glossaryPayload('shop_a'))).toEqual([])
  })

  it('★ 只有空白字符的表也视为空表（不把 `\\n\\n` 发过去）', () => {
    installStorage()
    saveGlossary('shop_a', '\n\n   \n')
    expect(glossaryPayload('shop_a')).toEqual({})
  })

  it('配了术语表 ⇒ 带上原文（前端不解析后再回传，避免「原表 / 解析结果」两份表示）', () => {
    installStorage()
    const raw = '# 注释\nNoise Cancelling=主动降噪'
    saveGlossary('shop_a', raw)
    expect(glossaryPayload('shop_a')).toEqual({ glossary: raw })
  })

  it('超字的表会被裁后再发（否则后端 422，而划词是静默操作 ⇒ 用户无从归因）', () => {
    installStorage()
    const raw = Array.from({ length: 400 }, (_, i) => `key-${i}=译文-${i}`).join('\n')
    saveGlossary('shop_a', raw) // 存储无损：本机留着完整原文
    const payload = glossaryPayload('shop_a')
    expect(payload.glossary!.length).toBeLessThanOrEqual(MAX_GLOSSARY_CHARS)
    expect(loadGlossary('shop_a')).toBe(raw)
  })

  it('取值按传入的 shopId 走，不偷读全局（两个店铺各自的请求体不同）', () => {
    installStorage()
    saveGlossary('shop_a', 'A=甲')
    saveGlossary('shop_b', 'B=乙')
    expect(glossaryPayload('shop_a')).toEqual({ glossary: 'A=甲' })
    expect(glossaryPayload('shop_b')).toEqual({ glossary: 'B=乙' })
    expect(glossaryPayload('shop_c')).toEqual({})
  })
})
