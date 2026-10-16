/**
 * 店铺术语表（前端侧）—— 解析 / 预览 / 按店铺存取
 * ================================================
 * 配套后端 `backend/modules/aigc_media/glossary.py`（第 369 轮 P0）。后端负责
 * 「原始文本 → 提示词段」；前端负责两件后端**看不到**的事：
 *
 *   ① **预览**：后端解析是**宽松跳错**的（非法行静默跳过、不报错、不注入）。
 *      这在服务端是优点（用户的笔误不该升级成故障），但对设置页就是隐患 ——
 *      用户打错一行，界面上看不出任何异常，只有「划词结果里那个词没按我的译法走」。
 *      所以必须有一处把「你这张表实际会被识别成几条」如实算出来给用户看。
 *   ② **按店铺存取**：术语表语义是「**本店**固定译法」（后端渲染的标题就是这个措辞），
 *      所以必须按 `shop_id` 分键 —— 两个店铺共用一份会出现 A 店品牌译法在 B 店全局生效。
 *
 * ★★ 本模块的解析口径必须与后端 `parse_glossary` **逐字一致**，否则症状是
 *    「设置页说识别 5 条、后端实际只用了 4 条」—— 一处用户可见的口径分叉。
 *    对齐是靠**同一组样本向量**（见 `tests/unit/glossary.test.ts`，样本逐条抄自
 *    `backend/tests/test_selection_glossary.py`）+ `scripts/check-glossary-parity.cjs`
 *    的常量对账两半合起来保证的，缺一不可：
 *      · 只对常量 ⇒ 算法漂了不知道（例如把「取首次」改成「取末次」）；
 *      · 只对样本 ⇒ 常量漂了不知道（例如后端把上限从 100 调到 200）。
 *
 * ★ 三条容易写错、且写错了不会有任何报错的地方：
 *
 *   1. **换行符口径**。Python 的 `str.splitlines()` 认 **9 种**行分隔符
 *      （`\n` `\r` `\r\n` `\v` `\f` `\x1c` `\x1d` `\x1e` `\x85` `\u2028` `\u2029`），
 *      而 JS 的 `split('\n')` 只认 `\n`。用户从 Word / Excel / 网页粘贴文本时
 *      `\u2028`（LINE SEPARATOR）是真实存在的，此时前端会把两行算成一行
 *      （且那一行里有两个 `=`，解析出的译文是怪东西）、后端算成两行 ⇒ 计数对不上。
 *      ⇒ 这里的 `LINE_BREAK` 正则刻意复刻 Python 的分隔符集合。
 *      `\r\n` 在 JS 侧会切出一个空元素，但空行本来就被跳过 ⇒ 结果集等价。
 *
 *   2. **分隔符的尝试顺序**。后端是 `for sep in ("=", "＝")` —— **先试半角**，
 *      命中就 break。所以 `A＝B=C` 的切点是**后面那个半角 `=`**（切成 `A＝B` / `C`），
 *      而不是位置更靠前的全角 `＝`。照抄这个顺序（本文件同序），别"优化"成
 *      「取最先出现的分隔符」—— 那是一种静默的口径分叉。
 *
 *   3. **`idx > 0` 而不是 `idx >= 0`**。即行首就是分隔符的行（`=foo`）算**残行**。
 *      写成 `>= 0` 会让 `=foo` 解析出空原文，渲染成 `-  → foo` 污染提示词。
 *
 * ★ 本模块是**纯叶子**：不 import vue / api / axios（与 `utils/translateOutcome.ts`
 *   同范式），因此能被零成本单测 —— 这在 node 环境下尤其重要：`localStorage`
 *   在 node 里是 **undefined**，所有访问都必须自带 try/catch 兜底（见下方 storage 段）。
 */

/** 一条术语：`原文 → 译文`。字段名对齐后端 `(source, target)` 元组的语义。 */
export interface GlossaryEntry {
  source: string
  target: string
}

/**
 * 单次注入的术语条数上限。
 *
 * ★ 必须与后端 `glossary.py` 的 `MAX_ENTRIES` 相等（`check-glossary-parity.cjs` 对账）。
 *   设置页是一个自由文本域，贴错一份大 CSV 进来会让**每次划词**都多烧一大段 token，
 *   而划词的核心价值恰恰是「快」。
 */
export const MAX_GLOSSARY_ENTRIES = 100

/**
 * 请求体里术语表文本的字符上限 —— 对齐后端 `SelectionTranslateRequest.glossary`
 * 的 `max_length=4000`（同样由 `check-glossary-parity.cjs` 从 schema 源码对账）。
 *
 * ★ 为什么前端也要知道这个数：超限时后端是 **422**，而划词是**静默操作** ——
 *   用户只会看到「翻译失败」，归因完全错方向（去查网络、去重试，而真正的原因是
 *   自己的术语表太长）。⇒ 传输前按完整行裁到上限内（`clampGlossary`），
 *   同时设置页把「超限」显式亮出来。**存储无损、传输有界**。
 */
export const MAX_GLOSSARY_CHARS = 4000

/**
 * 行分隔符 —— 刻意复刻 Python `str.splitlines()` 的集合，不是 `split('\n')`。
 * 理由见文件头第 1 条（用户粘贴的文本里 `\u2028` 是真实存在的）。
 */
const LINE_BREAK = /[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/

/**
 * `原文=译文` 的分隔符。半角与全角都认 —— 中文输入法下 `＝` 很容易打出来。
 * ★ 顺序即优先级（先半角），与后端 `_SEPARATORS` 同序。
 */
export const GLOSSARY_SEPARATORS: readonly string[] = ['=', '＝']

/** 注释行前缀。用于分组标注，如 `# 品牌名`。 */
const COMMENT_PREFIX = '#'

/**
 * 把设置页文本解析成术语条目。
 *
 * 格式（与老板自用划词翻译扩展的术语表口径一致）：
 *
 * ```
 * # 注释行（以 # 开头，可用来分组标注，不算条目也不报错）
 * Noise Cancelling=主动降噪
 * Gift Box＝礼盒装
 * ```
 *
 * 跳错规则（**与后端逐字一致**，改这里前先读后端 `parse_glossary` 的 docstring）：
 *   · 空行 / `#` 开头的行：跳过
 *   · 行首即分隔符（`=foo`）：残行，跳过
 *   · 原文或译文为空（`foo=` / `= `）：残行，跳过
 *   · 同名词：**取首次出现**（用户把新写法写在上面覆盖下面误留的旧行，是更常见的用法）
 *   · 达 `MAX_GLOSSARY_ENTRIES` 条即停止（**不是**报错）
 */
export function parseGlossary(raw: string | null | undefined): GlossaryEntry[] {
  const entries: GlossaryEntry[] = []
  const seen = new Set<string>()
  for (const line of String(raw ?? '').split(LINE_BREAK)) {
    const body = line.trim()
    if (!body || body.startsWith(COMMENT_PREFIX)) continue
    for (const sep of GLOSSARY_SEPARATORS) {
      const idx = body.indexOf(sep)
      // ★ idx > 0：行首就是分隔符 ⇒ 残行。写成 >= 0 会让 `=foo` 产出空原文。
      if (idx > 0) {
        const source = body.slice(0, idx).trim()
        const target = body.slice(idx + sep.length).trim()
        if (source && target && !seen.has(source)) {
          seen.add(source)
          entries.push({ source, target })
        }
        break
      }
    }
    if (entries.length >= MAX_GLOSSARY_ENTRIES) break
  }
  return entries
}

/** 术语表的**客观读数**（刻意返回事实而非文案：文案属设置页，改文案不该动判据）。 */
export interface GlossarySummary {
  /** 实际会被注入提示词的条目（= 后端会用的那一批） */
  entries: GlossaryEntry[]
  /** 用户「写了几条」的直觉口径：非空、非注释的行数 */
  declared: number
  /** 没生效的行数（格式残缺或与前面的同名词重复） */
  skipped: number
  /** 是否触到条数上限 —— 触顶时后面的行会被忽略，必须显式告知 */
  capped: boolean
  /** 是否超出字符上限 —— 超限部分**不会**随请求发出（后端会 422，故传输前裁掉） */
  oversize: boolean
}

/**
 * 统计术语表读数，供设置页预览区显示。
 *
 * `skipped` / `capped` 两个字段存在的唯一理由：把后端**刻意静默**的跳错行为
 * 在前端**可见化**。少了它们，用户打错一行不会有任何反馈。
 */
export function summarizeGlossary(raw: string | null | undefined): GlossarySummary {
  const text = String(raw ?? '')
  const entries = parseGlossary(text)

  let declared = 0
  for (const line of text.split(LINE_BREAK)) {
    const body = line.trim()
    if (body && !body.startsWith(COMMENT_PREFIX)) declared++
  }

  return {
    entries,
    declared,
    skipped: Math.max(0, declared - entries.length),
    // 触顶 = 已经取满，且还有没被处理的非空行（declared 含坏行，所以不能用 declared > MAX 单独判）
    capped: entries.length >= MAX_GLOSSARY_ENTRIES && declared > MAX_GLOSSARY_ENTRIES,
    oversize: text.length > MAX_GLOSSARY_CHARS,
  }
}

/**
 * 按**完整行**裁到字符上限内，保证返回值 `length <= MAX_GLOSSARY_CHARS`。
 *
 * ★ 为什么不是 `slice(0, MAX)`：那会把最后一行**拦腰截断**，截出半条术语 ——
 *   例如 `Noise Cancelling=主动降` 会变成一条看起来合法的术语，静默给出错译法。
 *   按行裁至多丢掉整条（用户看得见少了什么）。
 *
 * ★ 这是**防御**，不是权威校验：权威校验在后端 schema。前端裁一次的目的是
 *   让划词这条静默路径不会因为「术语表太长」而整体失败（用户无从归因）。
 */
export function clampGlossary(raw: string | null | undefined): string {
  const text = String(raw ?? '')
  if (text.length <= MAX_GLOSSARY_CHARS) return text

  const kept: string[] = []
  let len = 0
  for (const line of text.split(LINE_BREAK)) {
    const add = kept.length ? line.length + 1 : line.length // +1 = 补回的 \n
    if (len + add > MAX_GLOSSARY_CHARS) break
    kept.push(line)
    len += add
  }
  // 首行本身就超长 ⇒ 空表 ⇒ 不注入（此时设置页的 oversize 提示已经在亮了）
  return kept.join('\n')
}

// ---------------------------------------------------------------------------
// 按店铺存取（localStorage）
// ---------------------------------------------------------------------------

/** 键前缀。带 `::` 分隔，便于「列出所有店铺的术语表」这类排查（含后缀匹配）。 */
const STORAGE_PREFIX = 'translate_glossary::'

/** 还没选中店铺时的退化键。**不**退回全局共用键 —— 那会让两个店铺互相污染。 */
const NO_SHOP_KEY = '__no_shop__'

/**
 * 读当前店铺 ID。
 *
 * ★ 为什么直读 localStorage 而不是 import `stores/shop.ts`：本模块要守住「纯叶子」
 *   （见文件头）—— 引 store 会把 pinia 拖进来，纯函数单测就得建 pinia 实例。
 *   口径与 `api/request.ts` 的私有 `getShopId()` 完全一致（同一个 key、同样 try/catch）。
 *   那份之所以不共享：它是 `request.ts` 的私有函数，导出它会把这个纯叶子拖进 axios 依赖链。
 */
export function readCurrentShopId(): string {
  try {
    return localStorage.getItem('current_shop_id') || ''
  } catch {
    // localStorage 不可用（node 测试环境 / 隐私模式 / 被策略禁用）
    return ''
  }
}

/** 某店铺的存储键（导出以便设置页的排查/清理入口复用同一份口径）。 */
export function glossaryStorageKey(shopId?: string | null): string {
  return STORAGE_PREFIX + (shopId || NO_SHOP_KEY)
}

/**
 * 读术语表原文。读不到 / 存储不可用一律返回**空串**（= 不注入术语段）。
 *
 * ★ 方向是刻意的：术语表是「锦上添花」的偏好，不是权威清单。读失败时让翻译
 *   照常工作（只是不带本店译法），而不是把一次可用的翻译整体废掉。
 *   —— 这与本仓「拿不到权威清单 ≠ 清单为空」那条判据不冲突：那条说的是
 *   **业务数据**（拿不到就该保留旧值/显式报错），这里读的是**本机偏好**，
 *   且退化后的行为是「什么都没配过」，不会误导用户当成业务事实。
 */
export function loadGlossary(shopId?: string | null): string {
  try {
    return localStorage.getItem(glossaryStorageKey(shopId)) || ''
  } catch {
    return ''
  }
}

/**
 * 写术语表原文。返回**是否真的存进本机** —— 设置页据此给反馈。
 *
 * ★ 为什么必须返回布尔：这是用户在设置页的显式操作。写失败（存储被禁用）却
 *   回一句「已保存」，下次进来术语表没了 —— 典型的**静默丢失**。
 * ★ 内容为空 ⇒ **删键**而不是存空串：键不存在与空串语义相同，但不积累垃圾键。
 */
export function saveGlossary(shopId: string | null | undefined, raw: string): boolean {
  try {
    const key = glossaryStorageKey(shopId)
    const text = String(raw ?? '')
    if (text.trim()) localStorage.setItem(key, text)
    else localStorage.removeItem(key)
    return true
  } catch {
    return false
  }
}

/**
 * 构造要**并入请求体**的术语表字段。
 *
 * ★ 契约：空表 ⇒ 返回 `{}`（**连键都不带**）。两个理由，缺一都不行：
 *   ① 语义上「不带键」= 「本店没配术语表」= 后端 `glossary=""` 默认值，
 *      提示词与术语表上线前**逐字相同**（后端契约 1）；
 *   ② 形态上保持既有请求体不变 —— `tests/unit/selectionTranslate.test.ts` 有一条
 *      `Object.keys(payload) === ['text']` 的既有断言，多带一个空串键就会红。
 *      （这条断言本身就是「不该发的别发」的守卫，别去改它。）
 */
export function glossaryPayload(shopId?: string | null): { glossary?: string } {
  const raw = clampGlossary(loadGlossary(shopId))
  return raw.trim() ? { glossary: raw } : {}
}
