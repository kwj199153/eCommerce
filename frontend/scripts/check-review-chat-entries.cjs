#!/usr/bin/env node
/**
 * 「差评 → 对话」入口收敛门禁（★ 第 298 轮）
 *
 * 为什么值得单独一个门禁
 * ======================
 * 老板第 298 轮报了两件事，一件是缺口、一件是漂移：
 *   · 缺口：`💬 在对话里处置这条` 只长在**抽屉**里，`【处置台账】列表没有按钮`
 *     —— 台账行 / 差评卡片都得点开抽屉才看得见那个出口；
 *   · 漂移：兜底文案（`useAgentShortcuts.ts`）里点名的按钮名，与抽屉里**实装的**
 *     文案曾经不一致（文案说「差评处置」，抽屉却叫另一个名）—— 用户照着提示去找，
 *     找不到那个字。
 * 这两件事的共同点是：**同一个事实有两处表达**（一个出口 / 一个按钮名），
 * 而两处之间没有任何东西盯着。本门禁就是那个盯着的东西。
 *
 * 钉住的四条（每条都能被一处改动静默打坏）
 * ----------------------------------------
 *   R1 出口唯一      —— `window.dispatchEvent` 在 `ReviewDeskConfig.vue` 里恰好 1 处。
 *                      多一处 ⇒ 「谁在生产这个事件」有两份实现，第三个入口加进来时必漏一处。
 *   R2 入口都走出囗  —— 模板里能数出几个入口（`rd-act-chat` / `rd-item-chat` /
 *                      `@click="sendToChat"`），脚本里就得有几个出口调用点
 *                      （`emitReviewToChat(` 调用数 = 总出现数 − 1 处定义）。
 *                      **两个数必须相等**：新加入口而忘了接出口 ⇒ 立刻红。
 *   R3 送的是差评 id —— 台账行必须 `toDetailView(d.review, d.review_id)`。
 *                      写成 `d.id`（**处置** id）不报错、不崩溃，只会把 Agent 的结论
 *                      **静默**打到另一条差评上 —— 这是本仓最难靠人发现的一类缺陷。
 *   R4 两个行入口在 —— 台账 `td.rd-table-act` 与差评卡片 `.rd-item-top` 各有一个
 *                      💬 按钮，且都必须带 `@click.stop`（不带 ⇒ 行自身的 click 一起触发）。
 *   R5 文案对账      —— 抽屉里实装的按钮字面，必须逐字出现在兜底提示文案里；
 *                      面板名（「差评处置」）也必须逐字出现在那里。文案与实装不许漂移。
 *   R6 术语归零      —— `ReviewDeskConfig.vue` 里 `差评处理` 出现 0 次；
 *                      抽屉 `:title` 走「差评处置」。术语统一是可回归的，必须有人守。
 *   R8 【bug1】      —— `handleReviewToChat` 清空 `currentSelectedTool` **必须被 `if (needSwitch)` 挡住**。
 *                      无条件清空 ⇒ 工具级宽看板（差评台账）的 `hasWideBoard` 一起变假，
 *                      大屏模式 / 顶栏切换器 / 右栏宽度 / 台账面板**同时**消失。
 *   R9 【bug2】      —— 取消入口**逐层**对账（契约 / 提供 / 注入 / 转发 / 动作 / 模板）。
 *                      只查一层就全绿，正是「方案写了 N 条通道、落地只做 1 条」的形态。
 *   R9b【bug2】      —— `scopeTargetLoaded` 必须**派生自** `contextTarget`（判据与请求体同源）。
 *   R10 自检（反向） —— 剥注释与计数口径真的生效（防假绿）。
 *
 * 怎么跑
 * ======
 *   node scripts/check-review-chat-entries.cjs            做判定
 *   node scripts/check-review-chat-entries.cjs --report    只打印盘面读数
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**：
 *   REVIEW_CHAT_SRC_ROOT=<副本 src 目录>
 * ★ 每条注入之间必须**从真文件重新生成副本**，否则上一条的注入会把下一条判红（假红）。
 * ★ 必须有基线绿（副本不改 ⇒ 全绿）与对照绿（只动注释 / 只改无关文件 ⇒ 仍全绿）。
 *   参考实现：`.workbuddy/probes/` 下第 298 轮的注入台架。
 *
 * ★ 与相邻门禁的分工
 *   · `check-agent-scope-lifecycle.cjs` —— 判 `workingReview` 的**清空**（生命周期）
 *   · `check-chat-failure-path.cjs`     —— 判三条作用对象的**名单**与请求体
 *   · 本门禁 —— 判「差评 → 对话」这条链的**入口几何 + 出口唯一 + 文案对账**；
 *              它不管后端注入，也不管生命周期。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.REVIEW_CHAT_SRC_ROOT
  ? path.resolve(process.env.REVIEW_CHAT_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 读集（全文枚举）
// ★ 这里是**全部**被读的文件，不许有隐含的第七个：
//   · ReviewDeskConfig.vue —— 入口与出口都住在这里
//   · Workspace.vue        —— 唯一的消费侧（`addEventListener` + 写 `workingReview`）
//                            ＋ R8 的「工具清空有没有被挡住」＋ R9 的三个 `provide('clear*')`
//   · useAgentShortcuts.ts —— 兜底文案里点名按钮 / 面板名 ＋ R9 的取消分派
//   · ChatPanel/index.vue  —— R9：上下文条上的 × （`inject('clear*')` + 按钮 + 模板）
//   · useChatOrchestrator.ts —— R9：编排层要把三个取消写口转出去
//   · chat/types.ts        —— R9：契约层（三个可选写口）
const F_RD = 'components/TaskConfigPanel/configs/ReviewDeskConfig.vue'
const F_WS = 'views/Workspace.vue'
const F_UAS = 'composables/chat/useAgentShortcuts.ts'
const F_CP = 'components/ChatPanel/index.vue'
const F_ORCH = 'composables/useChatOrchestrator.ts'
const F_TYPES = 'composables/chat/types.ts'

// ---------------------------------------------------------------- 常量（唯一真源口径）
const EVENT_NAME = 'review-send-to-chat'
const EXIT_FN = 'emitReviewToChat'
const PANEL_NAME = '差评处置'
const OLD_TERM = '差评处理'
/** 抽屉右上角那个按钮的字面（R5 用它去对账，**不写第二份**） */
const BTN_LITERAL = '在对话里处置这条'
/** 入口的模板锚点 —— 数入口就靠这三样 */
const ENTRY_MARKERS = ['class="rd-act-chat"', 'class="rd-item-chat"', '@click="sendToChat"']

// ---------------------------------------------------------------- 工具

/** 只折叠**标签内部**的空白：`<div\n  a="1"\n>` → `<div a="1">`。
 *  ★ 为什么要：自动格式化（F-2 的 `vue/max-attributes-per-line` 等）会把单行开标签
 *    拆成多行，而本文件的分支锚点是**单行字面量** ⇒ 拆行后一律失配。
 *    症状是「找不到锚点」，与「两侧字段分叉」毫无关系，会把人往错方向带。
 *  ★ 只折叠标签内部 ⇒ **标签之外的缩进保留**，靠缩进区分的锚点（如 TPL_END）不受影响。 */
function collapseTagWs(s) {
  return s.replace(/<[^>]*>/g, (t) => t.replace(/\s+/g, ' ').replace(/\s+>$/, '>'))
}

function readSrc(rel) {
  const p = path.join(SRC_ROOT, rel)
  if (!fs.existsSync(p)) return null
  const txt = fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
  // ★ 折叠只对 .vue 生效：.ts 里的 `<T>` 泛型跨行折叠不值得冒险（判据面越小越稳）。
  return rel.endsWith('.vue') ? collapseTagWs(txt) : txt
}

/** 剥注释（字符串内的 `//` 不能误伤；与 `check-agent-scope-lifecycle.cjs` 同构） */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  let quote = null
  while (i < n) {
    const c = src[i]
    const nxt = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += nxt || ''; i += 2; continue }
      if (c === quote) quote = null
      i++
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i++; continue }
    if (c === '/' && nxt === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '/' && nxt === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue }
    out += c
    i++
  }
  return out
}

/** 统计子串出现次数（用 split 而不是正则，避免特殊字符要转义） */
function countOf(hay, needle) {
  if (!needle) return 0
  return hay.split(needle).length - 1
}

/** 取从 `fromIdx` 起第一个 `open` 到**匹配** `close` 的整块（含两端）。
 *  ★ 认字符串与模板串，否则对象字面量 / CSS 里的括号会把深度算飞。 */
function balancedDelims(src, fromIdx, open, close) {
  const i0 = src.indexOf(open, fromIdx)
  if (i0 < 0) return ''
  let depth = 0
  let quote = null
  for (let i = i0; i < src.length; i++) {
    const c = src[i]
    if (quote) {
      if (c === '\\') { i++; continue }
      if (c === quote) quote = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue }
    if (c === open) depth++
    else if (c === close) {
      depth--
      if (depth === 0) return src.slice(i0, i + 1)
    }
  }
  return ''
}

/** 取 `function <name>(...) {...}` 的函数体（含花括号）。找不到返回 ''。 */
function fnBody(src, name) {
  const idx = src.indexOf(`function ${name}(`)
  if (idx < 0) return ''
  return balancedDelims(src, idx, '{', '}')
}

/**
 * 取 `openTag` 到其后第一个 `closeTag` 的整块。
 * ★ 必须给定**完整的开标签**（含标签名）：`class="rd-table-act"` 在文件里出现两次
 *   （`<th class="rd-table-act">` 表头 + `<td class="rd-table-act">` 数据格），
 *   只按 class 找第一个会取到**空表头**，判据就永远绿 —— 典型的假绿。
 */
function blockOf(src, openTag, closeTag) {
  const i = src.indexOf(openTag)
  if (i < 0) return ''
  const j = src.indexOf(closeTag, i + openTag.length)
  return j < 0 ? '' : src.slice(i, j + closeTag.length)
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

// ---------------------------------------------------------------- 读盘面

const rawRd = readSrc(F_RD)
const rawWs = readSrc(F_WS)
const rawUas = readSrc(F_UAS)
const rawCp = readSrc(F_CP)
const rawOrch = readSrc(F_ORCH)
const rawTypes = readSrc(F_TYPES)

const rd = rawRd === null ? null : stripComments(rawRd)
const ws = rawWs === null ? null : stripComments(rawWs)
const uas = rawUas === null ? null : stripComments(rawUas)
const cp = rawCp === null ? null : stripComments(rawCp)
const orch = rawOrch === null ? null : stripComments(rawOrch)
const types = rawTypes === null ? null : stripComments(rawTypes)

// ---------------------------------------------------------------- R0 自检（读集与锚点）

check('R0 读集与锚点自检（文件都在 + 数入口的那三样锚点都真在）', () => {
  for (const [rel, src] of [[F_RD, rawRd], [F_WS, rawWs], [F_UAS, rawUas],
    [F_CP, rawCp], [F_ORCH, rawOrch], [F_TYPES, rawTypes]]) {
    assert(src !== null, `读不到 ${rel} —— 扫描根=${SRC_ROOT}。门禁不许在缺文件时静默全绿`)
    assert(src.length > 500, `${rel} 只有 ${src.length} B，不像真文件 —— 锚点会空跑`)
  }
  for (const m of ENTRY_MARKERS) {
    assert(rawRd.includes(m),
      `ReviewDeskConfig.vue 里找不到入口锚点 ${m} —— 要么入口被删了（那 R2 的入口数会 < 3），` +
      '要么锚点没跟上新写法（那 R2 会**静默**少算一个入口）。两种情况都必须在这里判红。')
  }
  assert(rawRd.includes(`<a-button v-if="detailView" size="small" :disabled="!detailView.id" @click="sendToChat">`),
    '抽屉 #extra 里那个按钮的 `@click="sendToChat"` 形态变了 —— R2 的入口计数会漏掉它')
})

// ---------------------------------------------------------------- R1 出口唯一

check('R1 出口唯一：`window.dispatchEvent` 在 ReviewDeskConfig.vue 里恰好 1 处', () => {
  const n = countOf(rd, 'window.dispatchEvent(')
  assert(n === 1,
    `实测 ${n} 处。` +
    (n === 0
      ? '一处都没有 ⇒ 三个入口全部发不出事件，「在对话里处置这条」是死的。'
      : '多于 1 处 ⇒ 「谁在生产这个事件」有了第二份实现：加第 4 个入口时必然漏改一处，' +
        '而漏掉的那处不报错、只是默默不带对象。'))
  const ev = countOf(rd, `new CustomEvent('${EVENT_NAME}'`)
  assert(ev === 1, `\`new CustomEvent('${EVENT_NAME}')\` 实测 ${ev} 处（要求 1）`)
})

// ---------------------------------------------------------------- R2 入口数 == 出口调用数

check(`R2 每个入口都必须走唯一出口 \`${EXIT_FN}\`（入口数 == 调用点数）`, () => {
  const entries = countOf(rd, ENTRY_MARKERS[0]) + countOf(rd, ENTRY_MARKERS[1])
    + countOf(rd, ENTRY_MARKERS[2])
  assert(entries >= 3,
    `模板里只数出 ${entries} 个入口（要求 ≥3：抽屉 #extra / 台账行 / 差评卡片）。` +
    '缺口就是这样静默回来的 —— 老板第 298 轮报的正是「列表行没有按钮」。')

  const total = countOf(rd, `${EXIT_FN}(`)
  const calls = total - 1          // 减去 `function emitReviewToChat(` 这一处定义
  assert(total >= 1, `找不到 \`${EXIT_FN}(\` —— 出口函数被删了`)
  assert(calls === entries,
    `入口 ${entries} 个，但 \`${EXIT_FN}(\` 调用点只有 ${calls} 个 —— 有一个入口**没接出口**。\n` +
    `        要么它自己 dispatchEvent（那 R1 会红），要么它什么都没发（点了没反应）。`)

  // 三个入口函数必须真的存在且都调出口
  for (const [fn, why] of [
    ['sendToChat', '抽屉 #extra'],
    ['sendRowToChat', '台账行'],
    ['sendItemToChat', '差评卡片'],
  ]) {
    const body = fnBody(rd, fn)
    assert(body !== '', `找不到 \`function ${fn}()\` 的函数体（${why}的入口没了？）`)
    assert(body.includes(`${EXIT_FN}(`),
      `\`${fn}\`（${why}）没有调用 \`${EXIT_FN}(...)\` ⇒ 它绕过了唯一出口`)
  }
})

// ---------------------------------------------------------------- R3 送的是差评 id

check('R3 台账行送的是 `review_id`，不是处置 id（`d.id`）', () => {
  assert(rd.includes('toDetailView(d.review, d.review_id)'),
    '台账行没有用 `toDetailView(d.review, d.review_id)` 归一 ⇒ 送出去的对象不是唯一归一形状')
  // ★ 唯一真源口径：`Disposition` 同时有 `id`（处置 id）与 `review_id`（差评 id）。
  const wrong = /toDetailView\(\s*d\s*\.\s*review\s*,\s*d\s*\.\s*id\s*\)/.test(rd)
  assert(!wrong,
    '台账行写成 `toDetailView(d.review, d.id)` —— `d.id` 是**处置** id，不是差评 id。\n' +
    '        取错不报错：Agent 会把这条差评的结论**静默**打到另一条差评上。')
  assert(rd.includes('toDetailView(r, r.id)'),
    '差评卡片没有用 `toDetailView(r, r.id)`（差评列表的行 id 就是 `review_id`）')
})

// ---------------------------------------------------------------- R4 两个行入口在

check('R4 台账行与差评卡片各有一个 💬 入口，且都带 `@click.stop`', () => {
  const ledger = blockOf(rd, '<td class="rd-table-act">', '</td>')
  assert(ledger !== '', '找不到台账末列（`td.rd-table-act`）')
  assert(ledger.includes('class="rd-act-chat"'),
    '台账行的操作列里没有 💬 按钮 —— 老板第 298 轮报的缺口（「【处置台账】列表没有按钮」）回来了')
  assert(ledger.includes('@click.stop="sendRowToChat(d)"'),
    '台账行的 💬 按钮没有 `@click.stop`（或没接 `sendRowToChat`）⇒ 点它会**同时**开抽屉')

  const card = blockOf(rd, '<div class="rd-item-top">', '</div>')
  assert(card !== '', '找不到差评卡片的顶栏（`.rd-item-top`）')
  assert(card.includes('class="rd-item-chat"'),
    '差评卡片上没有 💬 按钮 ⇒ 只能点开抽屉才看得见那个出口')
  assert(card.includes('@click.stop="sendItemToChat(r)"'),
    '差评卡片的 💬 按钮没有 `@click.stop`（或没接 `sendItemToChat`）⇒ 点它会同时开抽屉')
})

// ---------------------------------------------------------------- R5 事件名双向 + 文案对账

check('R5 事件名双向：生产者 / 消费者都在，且消费侧写的是同一个名字', () => {
  assert(countOf(rd, `'${EVENT_NAME}'`) >= 1, `生产者侧没有事件名 \`${EVENT_NAME}\``)
  assert(ws.includes(`addEventListener('${EVENT_NAME}'`),
    `Workspace.vue 没有 \`addEventListener('${EVENT_NAME}')\` ⇒ 事件发出去没人接（点了没反应）`)
  assert(ws.includes('handleReviewToChat'),
    'Workspace.vue 里找不到 `handleReviewToChat` —— 监听器的落地函数不见了')
  assert(countOf(ws, `'${EVENT_NAME}'`) >= 1,
    `Workspace.vue 里没有字面量 \`${EVENT_NAME}\`（事件名必须两处一致，不许只改一边）`)
})

check('R5b 文案对账：兜底提示里的按钮名 / 面板名与实装逐字一致', () => {
  assert(rawRd.includes(BTN_LITERAL),
    `ReviewDeskConfig.vue 里找不到按钮字面「${BTN_LITERAL}」 —— 抽屉入口没了？`)
  assert(uas.includes(`【${BTN_LITERAL}】`),
    `useAgentShortcuts.ts 的兜底文案里没有「【${BTN_LITERAL}】」。\n` +
    '        文案点名的按钮名必须与实装逐字一致 —— 否则用户照着提示去找，找不到那个字。')
  assert(uas.includes(`「${PANEL_NAME}」`),
    `useAgentShortcuts.ts 里没有「${PANEL_NAME}」这个面板名 —— 文案说的抽屉名与实装漂移了`)
})

// ---------------------------------------------------------------- R6 术语归零

check(`R6 术语归零：ReviewDeskConfig.vue 里「${OLD_TERM}」0 次，且抽屉标题走「${PANEL_NAME}」`, () => {
  const n = countOf(rawRd, OLD_TERM)
  assert(n === 0,
    `还有 ${n} 处「${OLD_TERM}」。第 298 轮已定：业务面统一用「${PANEL_NAME}」这一族词，` +
    `「${OLD_TERM}」退役（泛动词如「待处理 / 人工处理 / 升级处理」不在此列，不受本判据管）`)
  assert(rawRd.includes('`差评处置 · ${detailView.title || detailView.id}`'),
    '抽屉 :title 没有走「差评处置 · <差评标题>」形态')
})

// ---------------------------------------------------------------- R8【bug1】工具清空必须有条件
//
//   老板第 298 轮 bug1 原话：「点击【差评台账】列表的【带进对话】按钮，大屏模式直接没了」。
//   根因（真机实测）：`hasWideBoard = isWideBoardAgent || isReviewDeskTool`，而
//   `isReviewDeskTool` 判的是 `currentSelectedTool?.id === 'review-desk'` —— **工具级**。
//   `handleReviewToChat` 原本**无条件**清空 `currentSelectedTool` ⇒ 点下去那一刻
//   `hasWideBoard` 变假：顶栏切换器消失、根节点 `review-data-mode` 类消失、
//   右栏从"吃满剩余宽度"缩回 340、连台账面板本身都被清空。
//   真机前→后：`{dataMode:true,switchN:2,siderW:1004,rdRoot:true}` →
//              `{dataMode:false,switchN:0,siderW:340,rdRoot:false}`
//
//   ⇒ 钉住的形态：清空动作必须**被条件挡住**（只在真要换 Agent 时清）。
//     这是一条**否定式形态判据**（判"有没有守卫"），所以下面每一步都得先自证前提，
//     否则窗口取不到时会**恒真**（本仓「判据 needle 不存在 ⇒ 取反后恒真＝空跑」）。

check('R8 【bug1】`handleReviewToChat` 清空 `currentSelectedTool` 必须被条件挡住', () => {
  const idx = ws.indexOf('const handleReviewToChat = (e: Event) => {')
  assert(idx >= 0, '找不到 `handleReviewToChat` 的定义 —— 本判据的窗口取不到（会空跑），必须判红')
  const body = balancedDelims(ws, idx, '{', '}')
  assert(body !== '', '取不到 `handleReviewToChat` 的函数体（括号不平衡 / 形态变了）')
  const CLEAR = 'currentSelectedTool.value = null'
  const n = countOf(body, CLEAR)
  assert(n >= 1,
    `函数体里找不到 \`${CLEAR}\` —— 形态变了。本判据的 needle 不存在时取反会**恒真**，` +
    '所以这里必须判红而不是放过。')
  assert(n === 1, `清空动作有 ${n} 处（要求 1）—— 多出来的那处多半不受守卫保护`)
  const at = body.indexOf(CLEAR)
  const head = body.slice(0, at)
  assert(head.includes('if ('),
    '清空 `currentSelectedTool` 前面没有 `if (` 守卫 ⇒ 无条件清空。\n' +
    '        后果：工具级宽看板（差评台账）的 `hasWideBoard` 一起变假 —— ' +
    '大屏模式、顶栏切换器、右栏宽度、台账面板会**同时**消失。\n' +
    '        （这是老板第 298 轮 bug1 的原样复发。）')
  // 守卫必须真的与「换 Agent」这个条件挂钩（防写个 `if (true)` 糊弄过去）
  assert(/if \(needSwitch\)/.test(head),
    '守卫不是 `if (needSwitch)`（`needSwitch` = 目标 Agent 与当前 Agent 不同）——\n' +
    '        本处的语义是"只在真要换 Agent 时才清"，换个条件就不是这个意思了')
})

// ---------------------------------------------------------------- R9【bug2】取消链路逐层对账
//
//   老板第 298 轮 bug2 原话：「上下文被某条处置差评填入后，你没有给取消按钮」。
//   形态：`Workspace.vue` 的 `provide` 一直是**成对**给的（`set*` / `clear*`），
//   而 `clear*` 那半边**没有任何消费方** ⇒ 对象载得进来、出不去；
//   唯一出口是"切走 Agent 再切回来"，而那个办法用户想不到。
//
//   ★ 这是一条**跨层**判据：契约层 → 提供层 → 组件注入层 → 编排转发层 → 动作层 → 模板层。
//     只查其中一层就全绿（比如只查 ChatPanel 有按钮）＝ 本仓「方案写了 N 条通道、
//     落地只做 1 条＝执行缩水」。所以下面**逐层**各钉一笔。

/** 三种「载入型」作用对象 —— 与 `useAgentShortcuts` 的三支分支一一对应 */
const SCOPE_KINDS = ['Candidate', 'Product', 'Review']

check('R9 【bug2】取消入口逐层对账（契约 / 提供 / 注入 / 转发 / 动作 / 模板，六层都要在）', () => {
  const missing = []
  const need = (hay, needle, n, desc) => {
    const got = countOf(hay, needle)
    if (got !== n) missing.push(`${desc}：期望 ${n} 处 \`${needle}\`，实测 ${got}`)
  }
  for (const k of SCOPE_KINDS) {
    // ① 契约层：types.ts 里那个可选写口
    need(types, `clearWorking${k}?: () => void`, 1, `${F_TYPES} 契约层`)
    // ② 提供层：Workspace 的 provide（与 set* 成对）
    need(ws, `provide('clearWorking${k}'`, 1, `${F_WS} 提供层`)
    need(ws, `provide('setWorking${k}'`, 1, `${F_WS} 提供层（set 半边，防只删了 clear）`)
    // ③ 组件注入层：ChatPanel 真的 inject 了
    need(cp, `inject<() => void>('clearWorking${k}'`, 1, `${F_CP} 注入层`)
    // ④ 动作层：短路分派里真的调了
    need(uas, `clearWorking${k}()`, 1, `${F_UAS} 动作层`)
  }
  assert(missing.length === 0,
    '取消链路缺层（对象载得进来、出不去）：\n        · ' + missing.join('\n        · '))

  // ⑤ 转发层：编排层必须把它转出去（否则组件拿不到）
  //   ★ 逐键各查一次（不许写成"含这一整串"）：键在返回对象里是**一行一个**
  //     （`extractReturnKeys` 就靠这个口径），串在一起的写法在真文件里不存在。
  need(orch, 'scopeTargetLoaded,', 2, `${F_ORCH} 转发层（解构 + 返回各一处）`)
  need(orch, 'clearScopeTarget,', 2, `${F_ORCH} 转发层（解构 + 返回各一处）`)
  // ⑥ 模板层：按钮真的画在上下文条上，且与"有没有对象"同源
  need(cp, 'class="iab-scope-clear"', 1, `${F_CP} 模板层`)
  need(cp, 'v-if="scopeTargetLoaded"', 1, `${F_CP} 模板层（显示条件）`)
  const tag = blockOf(cp, '<a-tag v-if="skillCards.length" :color="agentScopeColor" class="iab-scope-float">', '</a-tag>')
  assert(tag.includes('iab-scope-clear'),
    '取消按钮不在上下文条 `.iab-scope-float` 里 —— 老板要的是"这条对象的取消入口"，' +
    '画到别处（比如输入卡片里）就不是"和对象绑在一起"了')
  assert(missing.length === 0, '取消链路缺层：\n        · ' + missing.join('\n        · '))
})

check('R9b 【bug2】取消判据与请求体**同源**（`scopeTargetLoaded` 派生自 `contextTarget`）', () => {
  assert(uas.includes('const scopeTargetLoaded = computed(() => !!contextTarget.value)'),
    '`scopeTargetLoaded` 不是从 `contextTarget` 派生的 —— 那就会出现' +
    '「界面有 ×」与「这轮真会带对象」各说各话（本仓「同一事实两份表达」）。')
  assert(uas.includes('function clearScopeTarget()'),
    '`clearScopeTarget` 的落地函数不见了 —— 按钮点了不会有动作')
  assert(uas.includes('scopeTargetLoaded,'),
    '`useAgentShortcuts` 没有把 `scopeTargetLoaded` 交出去 ⇒ 组件拿不到，按钮永远不显示')
})

// ---------------------------------------------------------------- R7 自检（反向）

check('R10 自检（反向）：剥注释与计数口径真的生效（防假绿）', () => {
  const faked = stripComments(
    `// window.dispatchEvent(new CustomEvent('${EVENT_NAME}', {}))\n/* also fake */`)
  assert(!faked.includes('window.dispatchEvent('),
    '剥注释没生效 —— 注释里那句 dispatchEvent 会让 R1 假红/假绿（这才是最危险的一类）')
  const real = stripComments(`window.dispatchEvent(new CustomEvent('${EVENT_NAME}', {}))`)
  assert(real.includes('window.dispatchEvent('),
    '真代码里的 dispatchEvent 没被认出来 —— R1 会假红')
  assert(countOf('ababab', 'ab') === 3, 'countOf 口径不对')
  const b = balancedDelims('function f() { const a = {x:1}; return a } tail', 0, '{', '}')
  assert(b === '{ const a = {x:1}; return a }', `balancedDelims 嵌套算错：${b}`)
})

// ---------------------------------------------------------------- 盘面 / 汇总

if (REPORT_ONLY) {
  console.log(`扫描根：${SRC_ROOT}`)
  console.log(`ReviewDeskConfig.vue：${rawRd ? rawRd.length : 0} B`)
  console.log(`Workspace.vue：${rawWs ? rawWs.length : 0} B / useAgentShortcuts.ts：${rawUas ? rawUas.length : 0} B`)
  if (rawRd) {
    const entries = ENTRY_MARKERS.reduce((a, m) => a + countOf(rd, m), 0)
    console.log(`入口锚点命中：${entries} 个 —— ${ENTRY_MARKERS.join(' / ')}`)
    console.log(`window.dispatchEvent：${countOf(rd, 'window.dispatchEvent(')} 处`)
    console.log(`emitReviewToChat：${countOf(rd, `${EXIT_FN}(`)} 处（含 1 处定义）`)
    console.log(`「${OLD_TERM}」残留：${countOf(rawRd, OLD_TERM)} 处`)
  }
}

console.log('')
let failed = 0
for (const [name, err] of results) {
  if (err) { failed++; console.log(`FAIL  ${name}\n        ${err}`) }
  else console.log(`PASS  ${name}`)
}
console.log('')
if (failed) {
  console.log(`---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
  process.exit(1)
}
console.log(`---- ${results.length}/${results.length} 通过 ----`)
console.log('「差评 → 对话」入口链成立（出口唯一 · 入口都接出口 · 送差评 id · 文案对账 · 术语统一 ✓）')
console.log('两个老板报过的 bug 也钉住了（R8 大屏模式不被清掉 · R9/R9b 对象可取消 ✓）')
