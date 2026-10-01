#!/usr/bin/env node
/**
 * 第 221 轮 · 四条真后端回复链「失败路径」端到端行为门禁（前端）
 *
 * 它保护什么
 * ==========
 * 「流式失败 → 非流式也失败」之后，用户必须看到**一句真实的失败原因**，而不是：
 *   · 两条互相矛盾的说明 —— `streamSSE` 抛错前会先调一次 `onError`，
 *     若那个 handler 里也 append，就会与降级 catch 的说明叠成两条（第 219 轮老板报的形态）；
 *   · 「（对话失败，请重试）」这种零信息量兜底 —— 配额耗尽（429）与网络抖动在界面上
 *     完全同形，用户只能反复重试；
 *   · 或者最糟的：穿透到通用兜底再补一句「⚠️ X 这次没有返回结果」甚至
 *     「正在为您分析…」—— **伪装成成功的失败**。
 *
 * 为什么不是「查字符串」门禁
 * ========================
 * 上面三件事都发生在**四个模块接力**之后（回复链 → `streamSSE` → 降级链 → `fallback`），
 * 任何单文件字符串断言都抓不住它。所以本门禁把 `replies/**` 与
 * `composables/chat/chatFailure.ts` 的**真文件**装进一个最小 pinia/api 打桩环境，
 * 跑真的 `runAgentReply()`，然后数消息、看文案。
 *
 * 覆盖面（第 221 轮扩）
 * ====================
 * 上一轮只有选品一条链。老板拍板「一并修」后，同款缺陷在 Listing / 广告 / 客服
 * 三条链上一起修掉 ⇒ 门禁改名并扩成**四条链 × 五个场景**。名字必须跟着覆盖面走，
 * 否则它只是一句墓志铭（名字说只保选品，下一个人就真的只改选品）。
 *
 * ★ 第 241 轮再扩一个**反向**场景：**用户主动取消**（「停止生成」按钮）。
 *   它必须与"失败"走**相反**的处理 —— 不写失败文案、不发非流式重试、不穿透兜底、
 *   不留空气泡。取消是最容易被误当失败的一类输入（`streamSSE` 抛的一样是个异常），
 *   所以判据并入本门禁：这里已经装好了真链 + 真 `streamSSE` 判定，再加一档只需改桩的
 *   mode，比另起一个新门禁更不容易腐烂（新门禁要重抄一遍打桩环境）。
 *
 * 反向注入（证明不是空跑）
 * ======================
 *   PROD_CHAT_FAILURE=<副本>        PROD_PRODUCT_RESEARCH=<副本>
 *   PROD_LISTING=<副本>             PROD_AD_ANALYSIS=<副本>
 *   PROD_CUSTOMER_SERVICE=<副本>    PROD_FALLBACK=<副本>   PKG_JSON=<副本>
 *   PROD_STREAM=<副本>              PROD_STREAM_CANCEL=<副本>   ← 第 241 轮（取消功能的地基）
 *   PROD_REPLIES_DIR=<副本目录>     ← P5/P6 的扫描面（整树指向副本，否则这两条判据
 *                                     的注入会打在真文件上、看着"绿"其实没被打中）
 *   PROD_REPLIES_INDEX=<副本>       ← L 组（第 249 轮）点名任务边界
 *   PROD_AGENT_SHORTCUTS=<副本>     ← L7/L9 的调用点扫描面
 *   PROD_SHELL=<副本>              ← L10：壳的透传面（第 250 轮）
 *   PROD_PANEL=<副本>              ← L10：chip 的渲染面（.vue）
 *   ★ L11（第 251 轮建 / 第 257 轮扩到三 Agent）复用的靶子 ——
 *     `PROD_AGENT_SHORTCUTS`（产地 · 三态 · 两份 Agent 名单 · 两类 label · 文案派生）
 *     · `PROD_SHELL`（透传）· `PROD_PRODUCT_RESEARCH`（选品两条请求路径）
 *     · `PROD_LISTING`（Listing 两条请求路径，★ 第 257 轮新增的靶子面）
 *   ★ 每条注入之间必须从真文件重新生成副本；并保留一条**基线绿**与一条**对照绿**
 *     （只动注释）—— 否则「红」到底是注入打中了、还是副本本身不完整，读数上分不出来。
 *   参考实现：`.workbuddy/probes/r257_context_target_inject.cjs`（第 257 轮，
 *   1 基线绿 + 1 对照绿 + 9 条注入 = 11 条读数，逐条对账）。
 *   ★ 这台架**抓到过本条判据自己的洞**：台账 I4（把 `label` 裸词硬编码进模板串）
 *     第一次跑是**绿的** —— 因为 label 唯一性当时按 `'工作商品'`（带引号）数，
 *     而模板串里是裸词。已补「数裸词」那一段；不留证据的判据不算判据。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const CHAT = path.join(SRC, 'composables', 'chat')
const REPLIES = path.join(CHAT, 'replies')

/** 可注入路径（反向注入用副本；默认真文件）。 */
function pick(env, rel) {
  return process.env[env] ? path.resolve(process.env[env]) : path.join(SRC, ...rel)
}

const P_CHAT_FAILURE = pick('PROD_CHAT_FAILURE', ['composables', 'chat', 'chatFailure.ts'])
const P_PRODUCT = pick('PROD_PRODUCT_RESEARCH', ['composables', 'chat', 'replies', 'productResearch.ts'])
const P_LISTING = pick('PROD_LISTING', ['composables', 'chat', 'replies', 'listing.ts'])
const P_AD = pick('PROD_AD_ANALYSIS', ['composables', 'chat', 'replies', 'adAnalysis.ts'])
const P_CS = pick('PROD_CUSTOMER_SERVICE', ['composables', 'chat', 'replies', 'customerService.ts'])
const P_FALLBACK = pick('PROD_FALLBACK', ['composables', 'chat', 'replies', 'fallback.ts'])
// ★ 第 241 轮新增的两个靶子（取消功能的两块地基）：
//   · 中止语义与取消判定在 `api/stream.ts`；
//   · 取消收口在 `composables/chat/streamCancel.ts`。
//   反向注入要能单独替换它们，否则 G 组那段「真行为」判据没法证明自己会红。
const P_STREAM = pick('PROD_STREAM', ['api', 'stream.ts'])
/**
 * ★ P5/P6 的扫描面。默认就是真目录；反向注入时整树指向副本。
 *   为什么必须可注入：这两条判据扫的是「所有回复链」，若只看真目录，
 *   注入打在副本上时它们**永远不会红** —— 那就成了"没被反向注入验证过的门禁"。
 */
const REPLIES_DIR = process.env.PROD_REPLIES_DIR
  ? path.resolve(process.env.PROD_REPLIES_DIR)
  : REPLIES
const P_CANCEL = pick('PROD_STREAM_CANCEL', ['composables', 'chat', 'streamCancel.ts'])
// ★ 第 249 轮（L 组）：点名任务边界的两份被测文件
const P_REPLIES_INDEX = pick('PROD_REPLIES_INDEX', ['composables', 'chat', 'replies', 'index.ts'])
const P_AGENT_SHORTCUTS = pick('PROD_AGENT_SHORTCUTS', ['composables', 'chat', 'useAgentShortcuts.ts'])
// ★ 第 250 轮（L10）：点名可见 chip 的**上下游**两份被测文件。
//   必须可注入 —— 否则反向注入改副本、判据扫真文件 ⇒ 永远照旧绿（本文件头注同源纪律）。
const P_SHELL = pick('PROD_SHELL', ['composables', 'useChatOrchestrator.ts'])
const P_PANEL = pick('PROD_PANEL', ['components', 'ChatPanel', 'index.vue'])
// ★ 第 292 轮：`customerService.ts` 的订单追踪渲染收归 `utils/orderTracking.ts`
//   ⇒ 被测模块的**读集变了**，台架必须跟着复制。不补桩时 `loadTs` 直接抛，
//   而 `buildEnv` 是**四条链一起**装环境 ⇒ 一处缺桩会把 4 条链 × 8 个场景
//   共 31 条判据一起打红（看着像门禁坏了，其实是在尽职报「新依赖未打桩」）。
const P_ORDER_TRACKING = pick('PROD_ORDER_TRACKING', ['utils', 'orderTracking.ts'])
/**
 * L7/L8 的**扫描面**根目录。
 *
 * ★ 必须可注入：这两条判据是「全仓数调用点」，若写死在真 `src` 上，
 *   反向注入改的是副本、扫描的是真文件 ⇒ 判据**照旧绿**，看上去"注入没抓到"、
 *   实际是**判据的长度不覆盖被测对象**（本文件头注里 P5/P6 那条同源判据）。
 */
const L_SCAN_ROOT = process.env.PROD_SRC_DIR ? path.resolve(process.env.PROD_SRC_DIR) : SRC
const PKG_JSON = process.env.PKG_JSON ? path.resolve(process.env.PKG_JSON) : path.join(ROOT, 'package.json')

let ts
try {
  ts = require(path.join(ROOT, 'node_modules', 'typescript'))
} catch (e) {
  console.error('找不到 typescript（需要 frontend/node_modules/typescript）')
  process.exit(2)
}

// ---------------------------------------------------------------- 常量

const SESSION_ID = 'sess-221'
const SKILL = 'listing-seo'
const STREAM_OK_TEXT = '蓝海品类 A 的毛利率最高'
const PARTIAL_TEXT = '已经吐出来的半句'
const FAIL_MSG = '请求失败 (429) {"detail":"API 调用次数不足，剩余 0 次"}'
const RETRY_DETAIL = 'API 调用次数不足，剩余 0 次'

/** 违禁措辞：一个**已经失败**的分支不许同时说自己在分析。 */
const LIES = ['正在为您分析', '收到：「']

/** 通用兜底的到达标记（到达即说明本分支**没有**终止）。 */
const FALLBACK_MARKS = ['这次没有返回结果', '对话能力尚未接入']

// ---------------------------------------------------------------- TS 装载器

/** ★ 行尾必须先归一化：本仓生产文件是 CRLF。 */
function readTs(p) {
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/**
 * 抽出 `return { … }` 的**对象体**（第 250 轮，L10 用）。
 *
 * ★ 必须取**最后一个** `return {`：壳里 `slot()` 也有一句
 *   `return { get, set: (fn) => {...} }`（单行对象字面量），用 indexOf 会命中它。
 *   （同 `check-chat-domain-split.cjs::extractReturnKeys` 的同一处理。）
 *
 * ★ 为什么不留「标识符在文件里出现过」这种写法：解构行 `= shortcuts` 里也有同名标识符
 *   ⇒ 把 return 里的键删掉，判据**照旧绿**。只有落到 return 对象体里才真正钉住「透传」。
 */
function returnBlock(code) {
  const i = code.lastIndexOf('  return {')
  if (i < 0) return ''
  const seg = code.slice(i + '  return {'.length)
  const j = seg.indexOf('\n  }')
  return j >= 0 ? seg.slice(0, j) : seg
}

/**
 * 取从 `fromIdx` 起第一个 `open` 到**匹配** `close` 的整块（含两端）。第 257 轮 L11 用。
 *
 * ★ 为什么不留「往后截 N 字符」的窗口写法：窗口长度一旦不够，判据会**静默假绿**
 *   —— 被测语句掉在窗口外 ⇒ 门禁看不见 ⇒ 却报通过。括号平衡不依赖长度假设。
 *   （同源判据：`check-agent-scope-lifecycle.cjs::balancedBlock` / `balancedDelims`。）
 * ★ 必须认字符串与模板串，否则 `'（未载入选品）'` 这类文案里的括号会把深度算飞。
 */
function balanced(code, fromIdx, open = '(', close = ')') {
  const i0 = code.indexOf(open, fromIdx)
  if (i0 < 0) return ''
  let depth = 0
  let quote = null
  for (let i = i0; i < code.length; i++) {
    const c = code[i]
    if (quote) {
      if (c === '\\') { i++; continue }
      if (c === quote) quote = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue }
    if (c === open) depth++
    else if (c === close) {
      depth--
      if (depth === 0) return code.slice(i0, i + 1)
    }
  }
  return ''
}

function loadTs(p, registry) {
  const code = ts.transpileModule(readTs(p), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const mod = { exports: {} }
  const req = (spec) => {
    if (Object.prototype.hasOwnProperty.call(registry, spec)) {
      const v = registry[spec]
      return typeof v === 'function' ? v() : v
    }
    throw new Error(`本门禁未打桩的模块：${spec}（新依赖请显式补桩，别让它静默拿到空实现）`)
  }
  // ★ 此处原本挂着 `// eslint-disable-next-line no-new-func`，但 `no-new-func`
  //   **不在 eslint:recommended 里**（也不在任何本仓启用的预设里）⇒ 那条指令从头到尾
  //   都是空转的。第 346 轮接 ESLint 时把「多余的 disable 指令」提为 error，它才现形。
  new Function('require', 'module', 'exports', '__filename', code)(req, mod, mod.exports, p)
  return mod.exports
}

function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const c2 = src[i + 1]
    if (c === '/' && c2 === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue }
    if (c === '`' || c === '"' || c === "'") {
      const q = c
      out += c; i++
      while (i < n && src[i] !== q) { if (src[i] === '\\') { out += src[i]; i++ } if (i < n) { out += src[i]; i++ } }
      out += q; i++; continue
    }
    out += c; i++
  }
  return out
}

function extractSpecifiers(code) {
  const out = []
  const re = /(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g
  let m
  while ((m = re.exec(code)) !== null) out.push(m[1])
  return out
}

// ---------------------------------------------------------------- 取消（第 241 轮）

/**
 * ★ 真实的 `api/stream.ts` —— 只为拿到**真的** `StreamCancelledError` 与
 *   `isStreamCancelled`。若让桩自造一套，那就是"自证"：桩说它是取消、桩也认它是取消，
 *   真实实现里漏掉 marker / name 也照样绿。
 *   （它的 `streamSSE` 仍是真实现，G 组会拿它跑真行为。）
 */
const REAL_STREAM = loadTs(P_STREAM, {
  '@/stores/user': () => ({ useUserStore: () => ({ token: '' }) }),
})

/** 当前场景的 state。模块级桩要用它 —— 真实 stream.ts 只装载一次，没法闭包到每个 state。 */
let CUR = null

/**
 * `@/api/stream` 的桩：忠实还原真实 `streamSSE` 的失败语义（**先调 onError、再 throw**），
 * 并补上「取消」这一档 —— 取消时**不调 `onError`**、抛**真实模块**的取消异常。
 * ★ 这两点正是本轮要钉的东西：取消若与失败同形，四条链会把它渲染成故障。
 */
async function stubStreamSSE(url, body, handlers = {}, options = {}) {
  const state = CUR
  state.streamUrls.push(url)
  // ★ 记下「这条链有没有把中断信号交给 streamSSE」—— 不传 ⇒ 停止按钮对它无效，
  //   而界面上完全看不出来（点了没反应）。
  state.signals.push(!!(options && options.signal))

  if (state.mode === 'stream-ok') {
    handlers.onDelta?.(STREAM_OK_TEXT)
    handlers.onDone?.(STREAM_OK_TEXT)
    return STREAM_OK_TEXT
  }
  if (state.mode === 'partial-then-fail') {
    handlers.onDelta?.(PARTIAL_TEXT)
    handlers.onError?.(FAIL_MSG)
    throw new Error(FAIL_MSG)
  }
  if (state.mode === 'cancelled-partial') {
    handlers.onDelta?.(PARTIAL_TEXT)
    throw new REAL_STREAM.StreamCancelledError()
  }
  if (state.mode === 'cancelled') {
    throw new REAL_STREAM.StreamCancelledError()
  }
  handlers.onError?.(FAIL_MSG)
  throw new Error(FAIL_MSG)
}

// ---------------------------------------------------------------- 四条链

/**
 * ★ 每条链的**非流式成功**回包形状逐字取自后端 router（不是猜的）：
 *   · `product_research/router.py::chat`  → `response_model=ChatResponse`，**裸载荷**（无信封）
 *   · `listing_generator/router.py::chat` → `ApiResponse(data=result)` ⇒ 业务字段在 `.data`
 *   · `ad_analysis/router.py::chat`       → `ApiResponse(data={reply, data, display_type, ...})`
 *   · `customer_service/router.py::chat_endpoint` → 同款 `ApiResponse(data={reply, ...})`
 */
const CHAINS = [
  {
    key: 'product-research',
    agent: { id: 'product-research', name: '选品分析师' },
    src: P_PRODUCT,
    url: '/product-research/chat/stream',
    apiModule: '@/api/productResearch',
    nonStreamFn: 'chatWithProductResearcher',
    structuredFns: [],
    label: '选品分析请求',
    prompt: '候选 009 可行吗',
    promptStructured: null,
    expectContextId: true,
    retryOk: () => ({ reply: '（非流式兜底）候选 009 的可行性中等', display_type: 'candidate_feasibility', data: { score: 62 } }),
    retryOkText: '（非流式兜底）候选 009',
    retryOkDisplay: 'candidate_feasibility',
  },
  {
    key: 'listing-generator',
    agent: { id: 'listing-generator', name: 'Listing 优化师' },
    src: P_LISTING,
    url: '/listing/chat/stream',
    apiModule: '@/api/listingGenerator',
    nonStreamFn: 'chatWithListingAgent',
    structuredFns: ['generateListing'],
    label: 'Listing 生成请求',
    prompt: '标题怎么优化更好',
    promptStructured: '生成一个完整的 listing 标题',
    expectContextId: false,
    retryOk: () => ({ success: true, message: 'OK', data: { response: '（非流式兜底）标题建议：突出材质与耐用性', display_type: 'listing_text', data: { seo: 80 } } }),
    retryOkText: '（非流式兜底）标题建议',
    retryOkDisplay: 'listing_text',
  },
  {
    key: 'ad-analysis',
    agent: { id: 'ad-analysis', name: '广告分析师' },
    src: P_AD,
    url: '/ad-analysis/chat/stream',
    apiModule: '@/api/adAnalysis',
    nonStreamFn: 'chatWithAdAnalyst',
    // ★ 第 316 轮：`detectAnomalies` 已随「异常检测」整条退役（老板「广告分析师
    //   删除异常检测、广告预算再平衡」）⇒ 广告侧结构化意图由 3 → 2。
    structuredFns: ['diagnoseAdAccount', 'analyzeSearchTerms'],
    label: '广告分析请求',
    prompt: '看下上周的 ACOS',
    promptStructured: '帮我诊断广告账号',
    expectContextId: false,
    retryOk: () => ({ success: true, message: 'OK', data: { reply: '（非流式兜底）ACOS 环比上升 3 个点', display_type: 'ad_text', data: { acos: 21 } } }),
    retryOkText: '（非流式兜底）ACOS',
    retryOkDisplay: 'ad_text',
  },
  {
    key: 'customer-service',
    agent: { id: 'customer-service', name: '智能客服' },
    src: P_CS,
    url: '/customer-service/chat/stream',
    apiModule: '@/api/customerService',
    nonStreamFn: 'chatWithCustomerService',
    structuredFns: ['trackOrder', 'createTicket'],
    label: '客服请求',
    prompt: '你好，我在用你们的产品',
    promptStructured: '我要创建工单',
    expectContextId: false,
    retryOk: () => ({ success: true, message: '对话处理完成', data: { reply: '（非流式兜底）已为您登记本次咨询', display_type: 'cs_text', data: { ticket: null } } }),
    retryOkText: '（非流式兜底）已为您登记',
    retryOkDisplay: 'cs_text',
  },
]

// ---------------------------------------------------------------- 打桩环境

/** 每次场景重装一次（避免用例之间互相污染）。 */
function buildEnv(chain) {
  const state = {
    mode: 'both-fail',   // both-fail | retry-ok | stream-ok | partial-then-fail
                         // | structured-fail | cancelled | cancelled-partial | structured-cancel
    agent: chain.agent,
    skill: null,
    messages: [],
    streamUrls: [],
    /** 每条链调用 streamSSE 时**有没有传中断信号**（false ⇒ 「停止生成」对它无效） */
    signals: [],
    retryCalls: 0,
    retryBody: null,
    structuredCalls: 0,
    /** 取消纪元（ctx 桩的 `isCancelledSince` 拿它比对；`structured-cancel` 档会推进它） */
    cancelEpoch: 0,
  }
  // ★ 桩是模块级的（真实 stream.ts 只装载一次）⇒ 用 CUR 指到当前场景的 state
  CUR = state

  const chatStore = {
    messages: state.messages,
    activeAgentId: chain.agent.id,
    addMessage(m) {
      state.messages.push({ role: m.role, content: m.content ?? '' })
      const last = state.messages[state.messages.length - 1]
      if (m.displayType !== undefined) last.displayType = m.displayType
      if (m.data !== undefined) last.data = m.data
    },
    appendToLastMessage(d) {
      const last = state.messages[state.messages.length - 1]
      if (last) last.content = (last.content || '') + d
    },
    setLastMessageContent(c) {
      const last = state.messages[state.messages.length - 1]
      if (last) last.content = c
    },
    setLastMessageResult(t, d) {
      const last = state.messages[state.messages.length - 1]
      if (last) { last.displayType = t; last.data = d }
    },
    // ★ 取消收口（`streamCancel.absorbStreamCancel`）要读「当前对话区」的消息列表，
    //   才能把那条空的 assistant 占位气泡收掉。桩缺这两个方法 ⇒ 会以 TypeError
    //   的形式伪装成「链路的错」（本仓铁律：桩的错不许算成业务的错）。
    getMessages(agentId) {
      return agentId === chain.agent.id ? state.messages : []
    },
    removeMessage(index) {
      state.messages.splice(index, 1)
    },
    ensureSessionId() { return SESSION_ID },
  }

  const ctx = {
    inputMessage: { value: '' },
    messageListRef: { value: undefined },
    mainContentRef: { value: undefined },
    intelDays: { value: 7 },
    loadedCandidate: { value: null },
    // ★ 第 251 轮：`replies/productResearch.ts` 会解构 `ctx.contextTarget` 并把
    //   `.value` 放进请求体。桩里缺这个键 ⇒ 每条 product-research 链都在发请求**之前**
    //   抛 `Cannot read properties of undefined (reading 'value')`，症状是 7 条一起红
    //   —— 看起来像"链路全坏"，实际是桩的错（本仓铁律：桩的错不许算成业务的错）。
    //   这里给 `null`（= 本次明确没有对象），与 `loadedCandidate: null` 同态。
    contextTarget: { value: null },
    isLoading: { value: false },
    // —— 生成流生命周期（第 241 轮）——
    isStreaming: { value: false },
    cancelEpoch: { get value() { return state.cancelEpoch } },
    beginStream: () => new AbortController().signal,
    endStream: () => {},
    isCancelledSince: (epoch) => state.cancelEpoch !== epoch,
    loadingStatus: { value: '' },
    currentMode: { value: 'chat' },
    selectedTool: { value: null },
    pendingSkill: { value: null },
    setLoading() {},
    scrollToBottom: async () => {},
    handleAgentMeta() {},
    handleThinkingStep() {},
    setPendingSkill() {},
    // ★ 第 249 轮：`consumePendingSkill`（取出即清空）拆成两半 ——
    //   读取不清空 + 显式清除。桩必须跟着改，否则分派器调 `ctx.peekPendingSkill()`
    //   会拿到 undefined ⇒ 这条门禁自己崩，而崩的原因与被测行为无关。
    peekPendingSkill: () => state.skill,
    clearPendingSkill() {},
    handleSend: async () => {},
    runAgentReply: async () => {},
    ensureCandidateLoaded: async () => {},
  }

  const axiosErr = (status, detail) => {
    const e = new Error(`Request failed with status code ${status}`)
    e.response = { status, data: { detail } }
    return e
  }

  const apiStub = {}
  apiStub[chain.nonStreamFn] = async (body) => {
    state.retryCalls++
    state.retryBody = body
    if (state.mode === 'retry-ok' || state.mode === 'structured-fail') return chain.retryOk()
    throw axiosErr(429, RETRY_DETAIL)
  }
  for (const fn of chain.structuredFns) {
    apiStub[fn] = async () => {
      state.structuredCalls++
      // ★ 「等待结构化结果期间用户点了停止」：axios 拦不住，只能靠取消纪元让结果自我否决
      if (state.mode === 'structured-cancel') {
        state.cancelEpoch++
        return { data: { summary: '（这份结果本不该上屏 —— 用户已停止生成）' } }
      }
      throw axiosErr(500, '后端结构化端点故障')
    }
  }

  const registry = {
    // —— 外部依赖：打桩 ——
    'ant-design-vue': { message: { warning() {}, error() {}, success() {} } },
    // 真实 `api/stream.ts` 的 import（它内部用 useUserStore 取 token）
    '@/stores/user': () => ({ useUserStore: () => ({ token: '' }) }),
    // ★ 这里模拟的是**模块命名空间**（导出 hook 本身），写成 `{ currentAgent }` 的话
    //   生产代码里的 `useAgentStore()` 会 `is not a function`，
    //   而门禁会把桩的错当成业务的错。
    '@/stores/agent': () => ({ useAgentStore: () => ({ currentAgent: state.agent }) }),
    '@/stores/chat': () => ({ useChatStore: () => chatStore }),
    '@/api/stream': {
      // ★ 判定函数与错误类取自**真实** `api/stream.ts`（见 `REAL_STREAM`）；
      //   桩自造一套就是"自证"，真实实现漏了 marker 也照样绿。
      StreamCancelledError: REAL_STREAM.StreamCancelledError,
      isStreamCancelled: REAL_STREAM.isStreamCancelled,
      streamSSE: stubStreamSSE,
    },
    // —— 同域模块：非本次被测的分支用桩 ——
    './secretary': { replySecretary: async () => 'fallthrough' },
    './competitorIntel': {
      replyCompetitorIntel: async () => 'fallthrough',
      // ★ 第 2 跳刻意打桩成「不接手」：若它被走到，就说明第 1 跳**没有终止**
      replyCandidateSnapshot: async () => 'fallthrough',
    },
    './review': { replyReview: async () => 'fallthrough' },
    // ★ 订单渲染真源：用**真文件**（纯函数、无外部依赖）—— 桩一份假的等于让门禁自证
    '@/utils/orderTracking': () => loadTs(P_ORDER_TRACKING, registry),
  }

  // —— 被测对象：全部用真文件 ——
  registry[chain.apiModule] = apiStub
  registry['../chatFailure'] = loadTs(P_CHAT_FAILURE, registry)
  // ★ 取消收口的**真文件**（六条流式链共同消费它；它 import 的 '@/api/stream' 已打桩）
  registry['../streamCancel'] = loadTs(P_CANCEL, registry)
  registry['./productResearch'] = loadTs(P_PRODUCT, registry)
  registry['./listing'] = loadTs(P_LISTING, registry)
  registry['./adAnalysis'] = loadTs(P_AD, registry)
  registry['./customerService'] = loadTs(P_CS, registry)
  registry['./fallback'] = loadTs(P_FALLBACK, registry)
  const { runAgentReply } = loadTs(path.join(REPLIES, 'index.ts'), registry)
  return { state, ctx, runAgentReply }
}

async function scenario(chain, mode, opts = {}) {
  const { state, ctx, runAgentReply } = buildEnv(chain)
  state.mode = mode
  state.skill = opts.skill ?? null
  await runAgentReply(ctx, opts.prompt || chain.prompt)
  return state
}

// ---------------------------------------------------------------- 判定框架

const results = []
async function check(name, fn) {
  try { await fn(); results.push([name, null]) }
  catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }
function allText(state) { return state.messages.map((m) => m.content || '').join('\n---\n') }

function assertNoFallback(state, who) {
  const t = allText(state)
  for (const m of FALLBACK_MARKS) {
    assert(!t.includes(m), `${who} 穿透到了通用兜底（出现「${m}」）⇒ 用户会同时看到两条说明：\n${t}`)
  }
}

console.log('对话回复链失败路径门禁 —— 端到端行为（四条链 × 八个场景 + 技能点名任务边界 L 组 10 条）')
console.log(`  chatFailure.ts       ${path.relative(ROOT, P_CHAT_FAILURE)}`)
for (const c of CHAINS) console.log(`  ${c.key.padEnd(18)} ${path.relative(ROOT, c.src)}`)
console.log('')

// ★ 本文件是 `.cjs`（CommonJS）⇒ **没有顶层 await**，必须包一层 async main
async function main() {
// ---- C0 本门禁必须真的被 `npm run build` 调到（否则它只是死脚本） ----
await check('C0 本门禁已挂进 `npm run build`（死脚本不算门禁）', async () => {
  const pkg = JSON.parse(readTs(PKG_JSON))
  const self = 'scripts/check-chat-failure-path.cjs'
  assert((pkg.scripts?.build || '').includes(self),
    `package.json 的 build 链里没有 ${self} —— 本地跑绿、CI 永远不跑，等于没有门禁`)
  assert(pkg.scripts?.['check:chat-failure'] === `node ${self}`,
    '缺少 check:chat-failure 别名（单独跑不方便时，下一个人就会绕过它）')
  assert(!(pkg.scripts?.build || '').includes('check-product-research-failure.cjs'),
    'build 链里还留着旧门禁名 —— 改名要两边一起改，否则跑的仍是那条只保选品的旧门禁')
})

// ---- C1 自检：四条链都真的被装进了打桩环境（否则下面的用例会「空跑式恒真」） ----
await check('C1 自检：四条链都真的跑起来了（每条都发过 1 次流式请求）', async () => {
  const detail = []
  for (const c of CHAINS) {
    const state = await scenario(c, 'both-fail')
    if (state.streamUrls.length !== 1 || state.streamUrls[0] !== c.url) {
      detail.push(`${c.key}: streamUrls=${JSON.stringify(state.streamUrls)}`)
    }
    if (state.retryCalls !== 1) detail.push(`${c.key}: retryCalls=${state.retryCalls}`)
  }
  assert(detail.length === 0,
    `以下链没有被真的驱动（门禁会退化成空集判空集式的恒真）：\n        ${detail.join('\n        ')}`)
})

// ---- C2 自检（反向）：违禁措辞判据本身必须抓得住旧版伪成功文案 ----
await check('C2 自检（反向）：旧版伪成功文案必须被违禁措辞判据抓住', async () => {
  const OLD = '收到：「目前选品库中哪个最贵」\n\n我是 **选品分析师**，正在为您分析...\n\n> 💡 提示：…'
  const hit = LIES.find((l) => OLD.includes(l))
  assert(hit, '违禁措辞判据自身失效 —— 旧版伪成功文案居然一条都没命中，F1 等于空跑')
})

// ---- D1 自检（反向）：P2/P4 用的说明符提取器必须既抓得住真 import、又不被注释骗过 ----
await check('D1 自检（反向）：说明符提取器抓得住真 import，剥注释后不认注释里的 import', async () => {
  const got = extractSpecifiers(stripComments("import { useChatStore } from '@/stores/chat'\n"))
  assert(got.includes('@/stores/chat'), `真 import 没被认出来（P4 会假绿）：${JSON.stringify(got)}`)
  const none = extractSpecifiers(stripComments("// import { x } from '@/stores/chat'\n/* from '@/api/x' */"))
  assert(none.length === 0, `注释里的 import 被当真了（P4 会假红）：${JSON.stringify(none)}`)
})

// ==================== 逐链：五个场景 ====================

for (const c of CHAINS) {
  const tag = c.key

  // F1 老板报的形态：流式 429 + 非流式 429
  await check(`${tag}/F1 流式与非流式都失败 ⇒ 只 1 条消息 + 真实原因（不穿透兜底）`, async () => {
    const state = await scenario(c, 'both-fail')
    assert(state.messages.length === 1,
      `用户看到 ${state.messages.length} 条 assistant 消息（应为 1）—— 降级链又补了兜底：\n${allText(state)}`)
    const t = state.messages[0].content
    assert(t.includes(RETRY_DETAIL), `真实原因（后端 detail）没上屏：${t}`)
    assert(t.includes('HTTP 429'), `HTTP 状态码没上屏（配额与网络抖动会变得无法区分）：${t}`)
    assert(t.includes(`${c.label}失败`), `文案的业务名不对（应为「${c.label}失败」）：${t}`)
    for (const lie of LIES) assert(!t.includes(lie), `出现违禁措辞「${lie}」：${t}`)
    assert(!t.includes('（对话失败，请重试）'), `又写回了旧版无信息量兜底：${t}`)
    assertNoFallback(state, tag)
  })

  // F2 流式失败但非流式成功
  await check(`${tag}/F2 流式失败 → 非流式成功 ⇒ 用真结果 + 回填 display_type + 带 skill`, async () => {
    const state = await scenario(c, 'retry-ok', { skill: SKILL })
    assert(state.messages.length === 1, `用户看到 ${state.messages.length} 条（应为 1）：\n${allText(state)}`)
    const m = state.messages[0]
    assert(m.content.includes(c.retryOkText), `真结果没上屏：${m.content}`)
    assert(m.displayType === c.retryOkDisplay,
      `降级路径没回填 display_type（实得 ${JSON.stringify(m.displayType)}，应为 '${c.retryOkDisplay}'）` +
      ' ⇒ 结论卡在流式失败时渲染不出来')
    assert(state.retryBody && state.retryBody.skill === SKILL,
      `降级请求体没带上点卡的 skill（后端技能注入会静默丢失）：${JSON.stringify(state.retryBody)}`)
    assert(state.retryBody.message === c.prompt,
      `降级请求体的 message 不对（实得 ${JSON.stringify(state.retryBody.message)}）`)
    if (c.expectContextId) {
      assert(state.retryBody.context_id === SESSION_ID,
        `降级请求体没带会话 ID（多轮上下文会退化成全局共享）：${JSON.stringify(state.retryBody)}`)
    }
  })

  // F3 流式成功
  await check(`${tag}/F3 流式成功 ⇒ 走 delta 正文，不再发起非流式重试`, async () => {
    const state = await scenario(c, 'stream-ok')
    assert(state.messages.length === 1, `用户看到 ${state.messages.length} 条（应为 1）：\n${allText(state)}`)
    assert(state.messages[0].content === STREAM_OK_TEXT, `正文不对：${state.messages[0].content}`)
    assert(state.retryCalls === 0, `流式已成功却仍打了一次非流式（retry=${state.retryCalls}）`)
  })

  // F4 已输出部分正文后流式失败
  await check(`${tag}/F4 已输出部分正文后失败 ⇒ 保留半句，不追加失败文案、不重试`, async () => {
    const state = await scenario(c, 'partial-then-fail')
    assert(state.messages.length === 1, `用户看到 ${state.messages.length} 条（应为 1）：\n${allText(state)}`)
    const t = state.messages[0].content
    assert(t === PARTIAL_TEXT, `已有的半句被改写了（实得 ${JSON.stringify(t)}）`)
    assert(!t.includes('失败'), `在半句正文后面又追加了失败文案：${t}`)
    assert(state.retryCalls === 0, `已有正文却仍发起了非流式重试（retry=${state.retryCalls}）—— 会重复一遍答案`)
  })

  // F5 结构化意图端点失败（只有带结构化端点的三条链有）
  if (c.promptStructured) {
    await check(`${tag}/F5 结构化端点失败 ⇒ 降级到非流式文本对话，不静默落兜底`, async () => {
      const state = await scenario(c, 'structured-fail', { prompt: c.promptStructured })
      assert(state.structuredCalls === 1,
        `结构化端点数不对（实得 ${state.structuredCalls}，应为 1）—— 场景没走到预期分支`)
      assert(state.streamUrls.length === 0,
        `本该走结构化端点，却发了流式请求：${JSON.stringify(state.streamUrls)}`)
      assert(state.messages.length === 1, `用户看到 ${state.messages.length} 条（应为 1）：\n${allText(state)}`)
      assert(state.messages[0].content.includes(c.retryOkText),
        `结构化失败后没有降级到非流式拿真结果：${state.messages[0].content}`)
      assertNoFallback(state, tag)
    })
  }

  // F6 用户主动取消（第 241 轮）：一个字都没吐出来就按了停止
  await check(`${tag}/F6 用户取消（未输出）⇒ 不留空气泡、不写失败文案、不重试`, async () => {
    const state = await scenario(c, 'cancelled')
    assert(state.signals[0] === true,
      '这条链没有把中断信号交给 streamSSE ⇒ 「停止生成」对它无效（点了没反应）')
    assert(state.messages.length === 0,
      `用户按了停止，界面上却留下 ${state.messages.length} 条消息（空占位气泡必须收掉）：\n${allText(state)}`)
    assert(state.retryCalls === 0,
      `取消后仍发起了非流式重试（retry=${state.retryCalls}）—— 答案会被补回来，看着像"停止失灵"`)
    assertNoFallback(state, tag)
  })

  // F7 用户主动取消：已经吐了半句
  await check(`${tag}/F7 用户取消（已吐半句）⇒ 保留半句、不追加失败文案、不重试`, async () => {
    const state = await scenario(c, 'cancelled-partial')
    assert(state.messages.length === 1, `用户看到 ${state.messages.length} 条（应为 1）：\n${allText(state)}`)
    const t = state.messages[0].content
    assert(t === PARTIAL_TEXT, `已有的半句被改写了（实得 ${JSON.stringify(t)}）`)
    assert(!t.includes('失败'),
      `取消后追加了失败文案 —— 用户自己按的停止，不是故障：${t}`)
    assert(state.retryCalls === 0, `取消后仍发起了非流式重试（retry=${state.retryCalls}）`)
    assertNoFallback(state, tag)
  })

  // F8 取消发生在「等待结构化结果」期间（axios 拦不住，只能靠纪元自我否决）
  if (c.promptStructured) {
    await check(`${tag}/F8 等待结构化结果期间取消 ⇒ 晚到的结果不许上屏`, async () => {
      const state = await scenario(c, 'structured-cancel', { prompt: c.promptStructured })
      assert(state.structuredCalls === 1,
        `结构化端点数不对（实得 ${state.structuredCalls}，应为 1）—— 场景没走到预期分支`)
      assert(state.streamUrls.length === 0,
        `本该走结构化端点，却发了流式请求：${JSON.stringify(state.streamUrls)}`)
      assert(state.messages.length === 0,
        `用户已停止，晚到的结构化结果仍被写进对话：\n${allText(state)}`)
    })
  }
}

// ==================== 形态判据（门禁的一部分，不是注释）====================

await check('P1 四条链的 onError 都只记录、不写文案', async () => {
  const bad = []
  for (const c of CHAINS) {
    const code = stripComments(readTs(c.src))
    if (!/onError:\s*\(\)\s*=>\s*\{\s*\}/.test(code)) {
      bad.push(c.key + '（onError 不是空箭头 —— streamSSE 抛错前会先调它，会叠成两条矛盾文案）')
    }
    if (code.includes('流式连接中断')) {
      bad.push(`${c.key}（还留着旧版的「（流式连接中断，已切换普通模式）」文案）`)
    }
  }
  assert(bad.length === 0, `以下链的 onError 仍会写正文：\n        ${bad.join('\n        ')}`)
})

await check('P2 失败文案只有一个实现，且四条链各自恰好消费一次', async () => {
  const impl = stripComments(readTs(P_CHAT_FAILURE))
  const nDesc = (impl.match(/function\s+describeChatFailure\s*\(/g) || []).length
  const nFacts = (impl.match(/function\s+collectHttpFacts\s*\(/g) || []).length
  assert(nDesc === 1, `chatFailure.ts 里 describeChatFailure 定义了 ${nDesc} 次（应为 1）`)
  assert(nFacts === 1, `chatFailure.ts 里 collectHttpFacts 定义了 ${nFacts} 次（应为 1）`)
  const bad = []
  for (const c of CHAINS) {
    const code = stripComments(readTs(c.src))
    const n = (code.match(/describeChatFailure\s*\(/g) || []).length
    if (n !== 1) bad.push(`${c.key} 消费 ${n} 次`)
    if (/function\s+collectHttpFacts\s*\(/.test(code)) bad.push(`${c.key} 又抄了一份 collectHttpFacts`)
  }
  assert(bad.length === 0,
    `失败文案的消费点不唯一：${bad.join('；')}\n` +
    '        「同一判定两份实现 ⇒ 至少一份永远测不到」：这里多一份，那条链的文案就永远没人验证。')
})

await check('P3 四条链都必须有 streamed 早退（部分正文后失败不得追加全文）', async () => {
  const bad = []
  for (const c of CHAINS) {
    const code = stripComments(readTs(c.src))
    if (!/let\s+streamed\s*=\s*false/.test(code)) bad.push(`${c.key}（没有 streamed 标记）`)
    if (!/if\s*\(\s*streamed\s*\)\s*return\s*'handled'/.test(code)) bad.push(`${c.key}（没有 streamed 早退）`)
  }
  assert(bad.length === 0,
    `以下链会在已有正文后再补一遍全文（用户看到重复内容）：\n        ${bad.join('\n        ')}`)
})

await check('P4 chatFailure 必须是纯函数模块（不 import store / api）', async () => {
  const specs = extractSpecifiers(stripComments(readTs(P_CHAT_FAILURE)))
  const bad = specs.filter((s) => s.startsWith('@/') || s.startsWith('.'))
  assert(bad.length === 0,
    `chatFailure.ts import 了 ${JSON.stringify(bad)}。` +
    '        它必须是纯函数模块：一旦它能拿到 store，就会出现第二个「谁来写界面」的实现，' +
    '        而那条路径永远没人测（本仓「同一判定两份实现」的形态）。' +
    '        写回界面那一步留在各分支里 —— 它取决于「当前有没有占位消息」。')
})

// ==================== 真行为：真实 `api/stream.ts` 的中断语义（第 241 轮）====================
//
// ★ 为什么必须跑**真文件**：`streamSSE` 的 abort 处理是本轮功能的地基 ——
//   桩里怎么写都行；真实实现漏了 `signal` 透传、或把 abort 当普通错误抛，
//   功能就是假的，而界面上只表现为「点了停止没反应」。

const ABORT_ERR = () => {
  const e = new Error('The operation was aborted.')
  e.name = 'AbortError'
  return e
}

/** 装一次浏览器全局（`stream.ts` 用 fetch 与 localStorage），返回还原函数。 */
function stubGlobals() {
  const savedFetch = globalThis.fetch
  const savedLS = globalThis.localStorage
  const ls = { getItem: () => null, setItem() {}, removeItem() {} }
  try { globalThis.localStorage = ls } catch { /* 只读属性则忽略 */ }
  return () => {
    globalThis.fetch = savedFetch
    try { globalThis.localStorage = savedLS } catch { /* 同上 */ }
  }
}

/**
 * 跑一次真 `streamSSE`（fetch / reader 桩由调用方现装）。
 * @param alreadyAborted 是否用一个**已经 abort** 的信号（覆盖 `signal.aborted` 那条保险）
 */
async function runRealStream(alreadyAborted) {
  const calls = { onError: 0, onDone: 0 }
  const ctrl = new AbortController()
  if (alreadyAborted) ctrl.abort()
  let thrown = null
  try {
    await REAL_STREAM.streamSSE('/probe', {}, {
      onError: () => { calls.onError++ },
      onDone: () => { calls.onDone++ },
    }, { signal: ctrl.signal })
  } catch (e) { thrown = e }
  return { calls, thrown }
}

await check('G1 真实 streamSSE：中止时抛「可识别的取消」且**不**调 onError（fetch×2 / 读循环）', async () => {
  const restore = stubGlobals()
  try {
    // ① 中止点落在 fetch，且信号**已**中止（走 `signal.aborted` 这条保险）
    globalThis.fetch = async () => { throw ABORT_ERR() }
    const r1 = await runRealStream(true)
    assert(r1.calls.onError === 0,
      'fetch 被中止时仍调了 onError ⇒ 消费方会照写一条失败文案（用户自己按的停止）')
    assert(r1.calls.onDone === 0, '中止时不应触发 onDone（正文没收到）')
    assert(REAL_STREAM.isStreamCancelled(r1.thrown),
      `中止抛出的不是可识别的取消异常（实得 ${r1.thrown && r1.thrown.name}: ${r1.thrown && r1.thrown.message}）`)

    // ② 中止点落在 fetch，信号**未**中止（模拟浏览器收到 abort 时抛 AbortError）
    //    ★ 这一档同时钉住「signal 有没有真的透传给 fetch」：桩在拿不到信号时抛一个
    //      与 abort 无关的普通错误 ⇒ G1 会红。漏传 signal = 点了停止毫无反应。
    globalThis.fetch = async (url, init) => {
      if (!init || !init.signal) throw new Error('fetch 没有收到 signal —— 中止能力没有接线')
      throw ABORT_ERR()
    }
    const r2 = await runRealStream(false)
    assert(r2.calls.onError === 0, '中止时仍调了 onError（第二档）')
    assert(REAL_STREAM.isStreamCancelled(r2.thrown),
      `中止抛出的不是取消异常（第二档，实得 ${r2.thrown && r2.thrown.name}: ${r2.thrown && r2.thrown.message}）`)

    // ③ 中止点落在读循环（fetch 已返回、正文正在流 —— 这是最长的一段窗口）
    globalThis.fetch = async () => ({
      ok: true,
      body: { getReader: () => ({ read: async () => { throw ABORT_ERR() } }) },
    })
    const r3 = await runRealStream(false)
    assert(r3.calls.onError === 0, '读循环被中止时仍调了 onError')
    assert(REAL_STREAM.isStreamCancelled(r3.thrown),
      '读循环中止抛出的不是取消异常 ⇒ 各链的取消短路永远不成立')
  } finally { restore() }
})

await check('G2 反例：普通网络错误**不得**被判成「用户取消」（否则真失败会静默消失）', async () => {
  const restore = stubGlobals()
  try {
    // 信号**没有** abort —— 这是与 G1 的唯一区别
    globalThis.fetch = async () => { throw new Error('socket hang up') }
    const ctrl = new AbortController()
    let thrown = null
    try { await REAL_STREAM.streamSSE('/probe', {}, {}, { signal: ctrl.signal }) } catch (e) { thrown = e }
    assert(thrown, '普通错误被吞掉了（没有继续抛出）')
    assert(!REAL_STREAM.isStreamCancelled(thrown),
      '普通网络错误被判成「用户取消」⇒ 真失败会静默变成「什么都没发生」，比报错更糟')
  } finally { restore() }
})

// ==================== 形态判据 · 取消（第 241 轮）====================

await check('P5 六条流式链都接了取消收口，且各自只消费一次', async () => {
  const files = fs.readdirSync(REPLIES_DIR).filter((f) => f.endsWith('.ts') && f !== 'index.ts')
  const bad = []
  let streamers = 0
  for (const f of files) {
    const code = stripComments(readTs(path.join(REPLIES_DIR, f)))
    if (!/streamSSE\(|streamCompetitorChat\(/.test(code)) continue
    streamers++
    const n = (code.match(/absorbStreamCancel\s*\(/g) || []).length
    if (n !== 1) bad.push(`${f} 消费 ${n} 次`)
  }
  assert(streamers >= 6, `只扫到 ${streamers} 条流式链（应为 6）—— 判据会退化成「空集恒真」`)
  assert(bad.length === 0,
    `以下链的取消收口不唯一：${bad.join('；')}\n` +
    '        漏一条的后果：那条链把「用户取消」渲染成失败文案（甚至重跑一次非流式）。' +
    '        「同一判定两份实现 ⇒ 至少一份永远测不到」在这里反过来用 —— 只留一份实现。')
})

await check('P6 取消判定只有一个实现（链上不得自己判 isStreamCancelled）', async () => {
  const streamCode = stripComments(readTs(P_STREAM))
  assert((streamCode.match(/function\s+isStreamCancelled\s*\(/g) || []).length === 1,
    'api/stream.ts 里 isStreamCancelled 不是恰好定义 1 次')
  const cancelCode = stripComments(readTs(P_CANCEL))
  assert((cancelCode.match(/function\s+absorbStreamCancel\s*\(/g) || []).length === 1,
    'streamCancel.ts 里 absorbStreamCancel 不是恰好定义 1 次')
  const bad = []
  for (const f of fs.readdirSync(REPLIES_DIR).filter((x) => x.endsWith('.ts'))) {
    const code = stripComments(readTs(path.join(REPLIES_DIR, f)))
    if (/isStreamCancelled\s*\(/.test(code)) bad.push(f)
  }
  assert(bad.length === 0,
    `以下链自己判取消（应统一走 absorbStreamCancel）：${bad.join(', ')}`)
})

// ---------------------------------------------------------------- L 组：技能点名的「任务边界」（第 249 轮）
//
// 老板报障（原话）：
//   点「行动计划」卡 → Agent 反问「基于哪份复盘（周报/月度复盘/广告效果复盘）」
//   → 答「基于月报」→ **吐出来的是月度复盘卡** → 「是否有bug，永远无法获得行动计划」
//
// 根因是点名的**生命周期**错了：旧实现「一次发送即消费清空」，而
// `review-action-plan`（行动计划）这类技能的适用条件本身就写着「已经产出了复盘结论」
// ⇒ 第一轮追问、第二轮用户回答。旧语义在第一轮就清掉了点名，于是第二轮：
//   `is_skill_requested()` 变回 false ⇒ 关键词短路重新生效 ⇒
//   用户的**回答**（"基于月报"，必然含被问到的关键词）被当成**新任务指令** ⇒
//   `monthly_review` ⇒ 一张月度复盘卡。**用户按追问回答就必然撞关键词** ——
//   所以这不是概率问题，是结构性不可达。
//
// 修法 = 点名保持到「任务结束」。本组钉两件事：
//   ① **行为**（真跑 `runAgentReply`，不打桩它的判定）：追问轮保留、结果轮清除；
//   ② **形态**：清除只有两个调用点，且分派器那处必须在「产出结果」条件内。
//      ⇒ 少一个条件就退回「一次性」，多一个调用点就退回「永不清理」。
//
// 反向注入：`PROD_REPLIES_INDEX=<副本>` · `PROD_AGENT_SHORTCUTS=<副本>`

const REPLY_AGENT_ID = 'review-analyst'

/** 「结果型」与「追问型」两种回复形状（判据与后端 `display_type` 同口径）。 */
const ASK_REPLY = { displayType: 'text' }                                  // 模型只是在追问
const RESULT_REPLY = { displayType: 'review_report', data: { report_type: 'monthly_review' } }

/** 起一个最小环境：真 `runAgentReply` + 桩 ctx + 桩 chatStore。 */
function lifecycleEnv(opts) {
  const state = {
    skill: opts.skill ?? null,
    cleared: 0,
    messages: [],
    reply: opts.reply,
    omitMessagesByAgent: !!opts.omitMessagesByAgent,
  }
  const chatStub = {
    addMessage(m) {
      state.messages.push({
        role: m.role,
        content: m.content ?? '',
        displayType: m.displayType,
        data: m.data,
      })
    },
  }
  // ★ 不给 `messagesByAgent` 时用来钉「读不到权威清单 ⇒ 保守当作未产出」那一档
  if (!state.omitMessagesByAgent) chatStub.messagesByAgent = { [REPLY_AGENT_ID]: state.messages }

  const ctx = {
    peekPendingSkill: () => state.skill,
    clearPendingSkill: () => { state.cleared++ },
  }
  const registry = {
    // ★ 未打桩的模块由 `loadTs` 直接抛错（不许静默拿到空实现）
    'ant-design-vue': { message: { warning() {}, error() {} } },
    '@/stores/agent': {
      useAgentStore: () => ({ currentAgent: { id: REPLY_AGENT_ID, name: '运营复盘师' } }),
    },
    '@/stores/chat': { useChatStore: () => chatStub },
    './secretary': { replySecretary: async () => 'handled' },
    './productResearch': { replyProductResearch: async () => 'fallthrough' },
    './listing': { replyListing: async () => 'fallthrough' },
    './adAnalysis': { replyAdAnalysis: async () => 'fallthrough' },
    './customerService': { replyCustomerService: async () => 'fallthrough' },
    './competitorIntel': {
      replyCompetitorIntel: async () => 'fallthrough',
      replyCandidateSnapshot: async () => 'fallthrough',
    },
    './fallback': { replyFallback: async () => {} },
    './review': {
      replyReview: async () => {
        state.messages.push(Object.assign({ role: 'assistant', content: '（桩回复）' }, state.reply))
        return 'handled'
      },
    },
  }
  return { state, ctx, registry }
}

async function runLifecycle(opts) {
  const env = lifecycleEnv(opts)
  const { runAgentReply } = loadTs(P_REPLIES_INDEX, env.registry)
  await runAgentReply(env.ctx, '基于月报')
  return env.state
}

/** 递归收集 src 下的 .ts / .vue 文件（形态断言用）。 */
function walkSources(dir, acc) {
  acc = acc || []
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    const st = fs.statSync(p)
    if (st.isDirectory()) walkSources(p, acc)
    else if (/\.(ts|vue)$/.test(name)) acc.push(p)
  }
  return acc
}

await check('L1 点名 + 本轮只是追问（text 且无 data）⇒ 点名必须保留', async () => {
  const s = await runLifecycle({ skill: SKILL, reply: ASK_REPLY })
  assert(s.cleared === 0,
    '追问轮就把点名清掉了 ⇒ 下一轮退化成关键词短路，用户按追问回答必然拿到**另一份报表**（老板报障的形态）')
})

await check('L2 点名 + 本轮产出了结果（报告型 displayType + data）⇒ 点名清除', async () => {
  const s = await runLifecycle({ skill: SKILL, reply: RESULT_REPLY })
  assert(s.cleared === 1,
    `产出结果后没有清点名（cleared=${s.cleared}）⇒ 任务级点名退化成"永不清理"，后续消息会一直带着它`)
})

await check('L3 没点名 ⇒ 任何轮次都不许有清除动作（不许误清用户刚点的名）', async () => {
  const s = await runLifecycle({ skill: null, reply: RESULT_REPLY })
  assert(s.cleared === 0, '无人点名时也调了 clearPendingSkill ⇒ 竞态下会清掉用户新点的名')
})

await check('L4 判据是「非 text 的 displayType」或「有 data」两者取或，不是只认一种', async () => {
  const a = await runLifecycle({ skill: SKILL, reply: { displayType: 'text', data: { x: 1 } } })
  assert(a.cleared === 1, 'displayType=text 但 data 非空时没判成"产出" ⇒ 漏了 data 那一半')
  const b = await runLifecycle({ skill: SKILL, reply: { displayType: 'review_report' } })
  assert(b.cleared === 1, '报告型 displayType 但 data 为空时没判成"产出" ⇒ 漏了 displayType 那一半')
  const c = await runLifecycle({ skill: SKILL, reply: { displayType: 'text' } })
  assert(c.cleared === 0, '严格 text 且无 data 被判成了"产出" ⇒ 追问轮会被误清（L1 形同虚设）')
})

await check('L5 读不到消息列表 ⇒ 按「未产出」处理（保守方向，且不许抛）', async () => {
  const s = await runLifecycle({ skill: SKILL, reply: RESULT_REPLY, omitMessagesByAgent: true })
  assert(s.cleared === 0,
    '拿不到权威清单时判成了"已产出"⇒ 会把点名清掉。两方向代价不对称：多留一轮用户再点一次即可，误清是结构性地拿不到')
})

await check('L6 分派器里的清除**必须在**「产出结果」条件内（形态）', async () => {
  const code = stripComments(readTs(P_REPLIES_INDEX))
  const start = code.indexOf('export async function runAgentReply')
  assert(start >= 0, '找不到 runAgentReply（门禁取错了文件或函数被改名）')
  const fn = code.slice(start)
  const body = fn.slice(0, fn.indexOf('\n}\n'))
  assert(body.length > 0, 'runAgentReply 函数体切片失败（判据会退化成空集恒真）')
  const clearLines = body.split('\n').filter((l) => /clearPendingSkill\s*\(/.test(l))
  assert(clearLines.length === 1,
    `runAgentReply 里 clearPendingSkill 出现 ${clearLines.length} 次（应为 1）：0 次=永不清理，>1 次=有一次是无条件的`)
  assert(/turnProducedResult/.test(clearLines[0]),
    `clearPendingSkill 不在「产出结果」条件内 ⇒ 无条件清 = 退回一次性语义：\n        ${clearLines[0].trim()}`)
  assert(/const\s+skill\s*=\s*ctx\.peekPendingSkill\s*\(/.test(body),
    'runAgentReply 没用 peekPendingSkill() 读点名 ⇒ 若退回 consume 型接口，任务级语义立刻失效')
})

await check('L7 全仓 clearPendingSkill() 的调用点恰好三处（分派器 + 切 Agent + 用户关 chip）', async () => {
  const hits = []
  for (const p of walkSources(L_SCAN_ROOT)) {
    const code = stripComments(readTs(p))
    for (const line of code.split('\n')) {
      // 只认**调用**（`x()`），不认定义（`const x = ...`）与类型声明（`x: () => void`）。
      // ★ 这条过滤是**按行**的：`xxx: () => ctx.clearPendingSkill()` 这种一行式箭头
      //   会被 `!/=>/` 排除 ⇒ **想让门禁数到它，就必须写成花括号体**。
      //   `dismissPendingSkill` 刻意写块体，理由见其 docstring。
      if (/clearPendingSkill\s*\(\s*\)/.test(line)
        && !/=>/.test(line)
        && !/clearPendingSkill\s*[:=]/.test(line)) {
        hits.push(path.relative(L_SCAN_ROOT, p).replace(/\\/g, '/'))
      }
    }
  }
  assert(hits.length === 3,
    `clearPendingSkill() 调用点 ${hits.length} 处（应为 3）：${hits.join(', ')}\n` +
    '        少一处 ⇒ 「产出结果 / 跨 Agent / 用户点 ×」三者有一条拿不掉点名；' +
    '多一处 ⇒ 把「任务级」又改回「一次性」。' +
    '★ 第 250 轮从 2 扩到 3：老板要求给残留窗口一个**可见的撤销 chip**，' +
    '那是**用户显式撤销**，与「产出结果」「切 Agent」两个系统判定不是同一个方向。')
  // ★ 逐文件计数（不是「存在即通过」）—— 两处都在 useAgentShortcuts 里，
  //   只判 includes 的话，其中一处被删掉照样是绿的（本仓「子序列 / 存在性断言恒真」形态）。
  const expect = {
    'composables/chat/replies/index.ts': 1,        // 本轮产出结果 ⇒ 任务结束
    'composables/chat/useAgentShortcuts.ts': 2,    // ① 切 Agent ② chip 的 ×
  }
  for (const [rel, n] of Object.entries(expect)) {
    const got = hits.filter((h) => h === rel).length
    assert(got === n,
      `${rel} 应有 ${n} 个 clearPendingSkill() 调用点，实际 ${got} 个（全部：${hits.join(', ')}）\n` +
      '        useAgentShortcuts 的 2 处 = ① watch(currentBackendAgent) 切 Agent 清；' +
      '② dismissPendingSkill（chip 上的 ×）。')
  }
})

await check('L8 点名读取点全仓唯一（peekPendingSkill() 恰好 1 处）', async () => {
  const hits = []
  for (const p of walkSources(L_SCAN_ROOT)) {
    const code = stripComments(readTs(p))
    for (const line of code.split('\n')) {
      if (/peekPendingSkill\s*\(\s*\)/.test(line) && !/peekPendingSkill\s*[:=]/.test(line)) {
        hits.push(path.relative(L_SCAN_ROOT, p).replace(/\\/g, '/'))
      }
    }
  }
  assert(hits.length === 1 && hits[0].endsWith('replies/index.ts'),
    `点名读取点应**唯一**在回复分派器里，实际：${hits.join(', ') || '(0 处)'}\n` +
    '        多处读取 = 同一判定多份实现（本仓既有形态），必然有一份漏改且不报错。')
})

await check('L9 切换 Agent 会丢弃未完成的点名', async () => {
  const code = stripComments(readTs(P_AGENT_SHORTCUTS))
  assert(/watch\s*\(\s*currentBackendAgent/.test(code),
    'useAgentShortcuts 里没有 watch(currentBackendAgent) ⇒ 点名会跨 Agent 残留')
  const idx = code.indexOf('watch(currentBackendAgent')
  const body = code.slice(idx, idx + 700)
  assert(/ctx\.clearPendingSkill\s*\(\s*\)/.test(body),
    'watch(currentBackendAgent) 里没有清点名 ⇒ 技能名是按 agent_name 生效的，跨 Agent 必然取不到正文')
})

await check('L10 点名残留窗口有**可见 chip** + 显式撤销出口（第 250 轮）', async () => {
  // 四段缺一不可，少任何一段都是「用户看不见点名还生效着 / 看得见但撤不掉」：
  //   ① shortcuts 出 pendingSkillCard（name → 中文 title，查不到退回 name）；
  //   ② shortcuts 出 dismissPendingSkill，且它**真的**清点名；
  //   ③ 装配壳把它俩透传出去（返回契约里加了却没给值 = 界面上永远不出现）；
  //   ④ 组件真的渲染它、且 × 绑到了撤销口。
  const sc = stripComments(readTs(P_AGENT_SHORTCUTS))
  assert(/const\s+pendingSkillCard\s*=\s*computed/.test(sc),
    'useAgentShortcuts 里没有 pendingSkillCard ⇒ chip 没有数据源')
  assert(/pendingSkill\.value/.test(sc),
    'pendingSkillCard 没读 pendingSkill.value ⇒ 拿不到点名，chip 恒空')
  // ★ 窗口必须**限定在 pendingSkillCard 之内**：全文件判 `skillsOfAgent(` 会被
  //   `skillCards` computed 里那一次调用旁路满足（第 250 轮 M8 反向注入实锤的假绿）。
  assert(/const\s+pendingSkillCard[\s\S]{0,700}?skillsOfAgent\s*\(/.test(sc),
    'pendingSkillCard 没回查技能目录 ⇒ 界面上会直接显示 kebab-case 的 name（内部标识泄漏到 UI）')
  assert(/function\s+dismissPendingSkill\s*\(/.test(sc),
    'useAgentShortcuts 里没有 dismissPendingSkill ⇒ chip 没有撤销出口（看得见、撤不掉）')
  const di = sc.indexOf('function dismissPendingSkill')
  assert(/ctx\.clearPendingSkill\s*\(\s*\)/.test(sc.slice(di, di + 500)),
    'dismissPendingSkill 没有真的清点名（改了个本地变量？那用户点了 × 也拿不掉）')

  const shell = stripComments(readTs(P_SHELL))
  const rb = returnBlock(shell)
  assert(rb.length > 0,
    'returnBlock 切片失败 ⇒ 下面两条「透传」判据会退化成空集恒真（先修门禁，别继续读结论）')
  for (const k of ['pendingSkillCard', 'dismissPendingSkill']) {
    assert(new RegExp('^\\s*' + k + '\\s*,\\s*$', 'm').test(rb),
      `装配壳的 return 对象里没有 ${k} ⇒ 组件解构到 undefined` +
      '（返回契约写了但没给值，界面静默无变化 —— 比报错更难归因）')
  }

  // ★ 这里读的是**原始** .vue（含 template）—— 本条的靶子就是"模板里有没有那个元素"。
  //   为免注释蒙混过关，判据把 v-if 与 class **绑在一起**判整个开标签。
  const panel = readTs(P_PANEL)
  // ★ 结尾用 `\s*>`：自动格式化会把 `class="…"` 与 `>` 拆到两行（F-2 第 348 轮实测）。
  assert(/<div\s+v-if="pendingSkillCard"\s+class="pending-skill-chip"\s*>/.test(panel),
    'ChatPanel 没有渲染 pendingSkillCard chip（或 v-if 与 class 不在同一个开标签里）⇒ ' +
    '残留窗口对用户仍然不可见 —— 这恰恰是本条判据存在的全部意义')
  assert(/@click="dismissPendingSkill\(\)"/.test(panel),
    'ChatPanel 的 × 没绑到撤销口 ⇒ 看得见但撤不掉')
  // ★ 落点必须在**输入区**里（而不是动作条 / 消息列表内）：
  //   塞进动作条（`v-if="skillCards.length"`）⇒ 它会随 skillCards 一起静默消失；
  //   塞进消息列表 ⇒ 它会跟着滚动走，"随时可撤销"就没了。
  //   判「在 .input-area 之后」是一个**真边界**（区别于"某个 needle 不存在"式的恒真断言）。
  const chipIdx = panel.indexOf('class="pending-skill-chip"')
  const areaIdx = panel.indexOf('class="input-area"')
  assert(areaIdx >= 0 && chipIdx > areaIdx,
    'chip 不在 .input-area 之内（chipIdx=' + chipIdx + ', areaIdx=' + areaIdx + '）⇒ ' +
    '若在动作条里会随 skillCards 静默消失，若在消息列表里会滚走')
})

await check('L11 「作用对象」全链下发：唯一产地 · 三态 · 四 Agent · 每条链两条路径（第 251 轮建 / 第 257 轮扩 / 第 298 轮补客服）', async () => {
  // 后端第 251 轮加了前置门禁：点名的候选类技能（`candidate-*`）若拿不到「作用对象」，
  // 就直接拒答、**连模型都不叫**。口径是 fail-closed：拿不到权威信息就不假定有对象。
  //
  // 于是前端这条链上缺任一段都不是「少个字段」，而是一个**具体的坏结局**：
  //   ① 产地：shortcuts 的 `contextTarget` computed —— 缺 ⇒ 请求里根本没这个字段；
  //   ② 三态：`undefined`（本 Agent 不参与）/ `null`（明确没有）/ 对象；
  //      缺 `null` ⇒ 后端把「明确没有」读成「客户端没参与」，门禁在那条路径上静默失效
  //      （第 250 轮那个洞的翻版）；
  //   ③ 透传：装配壳 `return` 里要给出它 —— 缺 ⇒ 组件解构到 `undefined` ⇒
  //      **所有**请求都被当成「客户端没参与」，而 fail-closed 会照样拒 ⇒ 有选品也全被拒
  //      （这一档不是「漏」，是「全坏」）；
  //   ④ 两条请求路径都带（流式 + 非流式降级）—— 缺降级那条 ⇒ 一次网络抖动被
  //      转译成「请先载入选品」，把基础设施故障说成用户没操作（归因错方向）。
  //
  // ★★ 第 257 轮（老板报障 + 截图）：Listings / AIGC 的上下文条显示「（无上下文参数）」
  //   —— 而这两个 Agent 同样要先选一个商品才能开工。取证结论：**不是取舍，是疏漏**，
  //   第 251 轮那条链**五层全部**只接了选品一条链路。于是本轮把本条判据扩成：
  //     ⑤ **三 Agent 都参与**：`contextTarget` 的 Agent 名单与两类 label 各只允许一处
  //        （名单漂移 ⇒ 某个 Agent 静默回到「无上下文参数」，而界面上只是少了一行字）；
  //     ⑥ **文案从结构化字段派生**：`contextParamText` 不许直接读 `loadedCandidate` /
  //        `workingProduct` —— 直接读源就是第二份实现，tag 与请求体必然有一天各说各话；
  //     ⑦ **每一条发得出去的链路**都带（选品 / Listing / 客服各两条路径）。
  //        ⚠️ AIGC 目前**没有对话链路**（兜底文案逐字写着「对话能力尚未接入」），
  //        它的字段由上下文条消费、请求体没有落点 —— 所以这里**不列它**，
  //        而不是列一条永远查不到的靶子（那样只会被改成恒真断言）。
  //
  // ★★ 第 298 轮（老板追问 + 拍板 A）：客服**整条通道从来没有接过** ——
  //   第 251 轮建机制时没接，第 257 轮扩到三 Agent 时又漏了它，而它的
  //   差评处置台账里**早就写着**「要跟买家继续拉锯，在对话里直接问」。
  //   缺这条通道的坏结局是具体的：差评应对技能第 0 步
  //   `get_customer_review_context(review_id)` 要一个 id，而此前那个 id
  //   只能从用户消息文本或**会话历史**里来 ⇒ 第 250 轮那个洞原样复现，
  //   只不过这次结论打在**本店的另一条差评**上。
  //   ★ 与之配套：这一轮同时补上了「台账 → 对话」的入口
  //     （`ReviewDeskConfig.vue` 的 `review-send-to-chat`）—— 界面承诺
  //     与实现此后对得上。
  //
  // ★ 本条所有靶子都走可注入路径（shortcuts / 壳 / replies）：否则反向注入改副本、
  //   判据扫真文件 ⇒ 照旧绿（本文件头注里 P5/P6 那条同源纪律）。
  const sc = stripComments(readTs(P_AGENT_SHORTCUTS))
  const decl = sc.indexOf('const contextTarget = computed')
  assert(decl >= 0, 'useAgentShortcuts 里没有 contextTarget computed ⇒ 请求里不会有这个字段')
  // ★ 用括号平衡取整块，不用「往后截 400 字符」（第 257 轮：函数体变长后
  //   末尾那行 `return undefined` 会掉在窗口外 ⇒ 判据静默假绿）。
  const body = balanced(sc, decl)
  assert(body.length > 80,
    `contextTarget 的 computed 块只解析出 ${body.length} 字符 —— 括号平衡器失效，下面几条会退化成空集恒真`)
  assert(/return\s+undefined/.test(body),
    'contextTarget 少了「本 Agent 不参与」那一态（undefined）⇒ 别的 Agent 也会被塞上字段')
  assert(/return\s+null/.test(body),
    'contextTarget 少了「本次明确没有对象」那一态（null）⇒ 后端读成「客户端没参与」，' +
    '门禁在这条路径上静默失效')
  assert(/label\s*:/.test(body),
    'contextTarget 少了「有对象」那一态（没有 label/title/ref）⇒ 门禁永远拿不到对象')

  // ⑤ 参与该机制的 Agent 名单 —— 逐字钉住（名单本身是判据，不是实现细节）
  const cand = /const\s+CANDIDATE_TARGET_AGENT\s*=\s*'([^']+)'/.exec(sc)
  assert(cand && cand[1] === 'product-research',
    `CANDIDATE_TARGET_AGENT 应为 'product-research'，实得 ${cand ? cand[1] : '(未定义)'}`)
  const prodList = /const\s+PRODUCT_TARGET_AGENTS\s*:[^=]*=\s*\[([^\]]*)\]/.exec(sc)
  assert(prodList, '找不到 PRODUCT_TARGET_AGENTS 名单定义 ⇒ 名单漂移无从判定')
  const prodIds = [...prodList[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
  assert(prodIds.join(',') === 'listing-generator,aigc-media',
    `PRODUCT_TARGET_AGENTS 应为 listing-generator + aigc-media，实得 [${prodIds.join(', ')}]`)
  // ★ 第 298 轮：第三支 —— 智能客服（差评应对）。
  const rev = /const\s+REVIEW_TARGET_AGENT\s*=\s*'([^']+)'/.exec(sc)
  assert(rev && rev[1] === 'customer-service',
    `REVIEW_TARGET_AGENT 应为 'customer-service'，实得 ${rev ? rev[1] : '(未定义)'}`)
  assert(
    body.includes('CANDIDATE_TARGET_AGENT') &&
      body.includes('PRODUCT_TARGET_AGENTS') &&
      body.includes('REVIEW_TARGET_AGENT'),
    'contextTarget 没走那三份名单（自己又写了 agent id 字面量）⇒ 名单与判定脱钩：' +
    '改了名单也不生效，而且**看不出来**')

  // 两类 label 全文件各只出现一次（唯一产地：tag 文案与请求体共用同一个词）
  const labels = /const\s+TARGET_LABELS\s*=\s*\{([\s\S]*?)\}\s*as const/.exec(sc)
  assert(labels, '找不到 TARGET_LABELS ⇒ label 字面量散落各处（tag 与请求体迟早各说各话）')
  for (const lit of ["'候选选品'", "'工作商品'", "'处置差评'"]) {
    const n = sc.split(lit).length - 1
    assert(n === 1, `${lit} 在 useAgentShortcuts 里出现 ${n} 次（要求恰好 1：唯一产地）`)
  }
  // ★ 第 257 轮反向注入补的洞（台账 I4）：上面两句的 needle **带引号**，所以
  //   「把 label 直接写进模板串」这种绕开 `TARGET_LABELS` 的写法它数不出来 ——
  //   `` `工作商品：${t.title}` `` 里压根没有 `'工作商品'` 这个子串（裸词不带引号）。
  //   于是再数一遍**裸词**：它必须仍然只出现在 `TARGET_LABELS` 那一处。
  //   （真基线里两个裸词各恰好 1 次 ⇒ 收紧后基线依旧绿；反向注入 I4 逐条对账。）
  for (const word of ['候选选品', '工作商品', '处置差评']) {
    const n = sc.split(word).length - 1
    assert(n === 1,
      `「${word}」在 useAgentShortcuts 里出现 ${n} 次（要求恰好 1）⇒ 有人绕开 TARGET_LABELS 把 ` +
      'label 写到了别处（裸词不带引号，上一句按引号数时看不见它）—— ' +
      'tag 上那行字与请求体里的 label 又成了两份产地，迟早各说各话')
  }

  // ⑥ 上下文条文案必须从结构化字段派生
  const paraIdx = sc.indexOf('function contextParamText')
  assert(paraIdx >= 0, 'useAgentShortcuts 里没有 contextParamText ⇒ 上下文条没有数据源')
  const para = balanced(sc, paraIdx, '{', '}')
  assert(para.length > 100,
    `contextParamText 的块只解析出 ${para.length} 字符 —— 下面的判据会退化成空集恒真`)
  assert(para.includes('contextTarget.value'),
    'contextParamText 没从结构化字段派生 ⇒ 「tag 上写什么」与「请求里带什么」成了两套')
  assert(!/loadedCandidate\.value|workingProduct\.value|workingReview\.value/.test(para),
    'contextParamText 又直接读源 ref 了（`loadedCandidate` / `workingProduct` / `workingReview`）' +
    '⇒ 第二份实现：tag 上写着「未载入」而请求里带着对象（或反之），用户只会相信屏幕上那句话')

  const shell = stripComments(readTs(P_SHELL))
  const rb = returnBlock(shell)
  assert(rb.length > 0,
    'returnBlock 切片失败 ⇒ 下面这条会退化成空集恒真（先修门禁，别继续读结论）')
  assert(/^\s*contextTarget\s*,\s*$/m.test(rb),
    '装配壳的 return 对象里没有 contextTarget ⇒ 组件解构到 undefined ⇒ 所有请求都被当成' +
    '「客户端没参与」，fail-closed 之下**有选品也全被拒**')

  // ⑦ 每一条**发得出去**的链路都要带。
  //    ★ 不数「全文件出现几次」—— 那个口径**看不出"漏了一整条链路"**：
  //      本轮的缺陷正是「Listing 整条没接」，而选品那个文件里照样是 2 处。
  //      改成「逐调用点取参数块、块里必须有 needle」：数据流走到哪就查到哪。
  const REQUEST_PATHS = [
    {
      file: P_PRODUCT,
      who: 'productResearch',
      paths: [
        { call: 'streamSSE(', needle: 'context_target: contextTarget.value', tag: '流式' },
        { call: 'chatWithProductResearcher(', needle: 'context_target: contextTarget.value', tag: '非流式降级' },
      ],
    },
    {
      file: P_LISTING,
      who: 'listing',
      paths: [
        { call: 'streamSSE(', needle: 'context_target: contextTarget.value', tag: '流式' },
        // ★ Listing 的降级路径把值当**参数**传进 `degradeListingText()`，
        //   所以这一处的 needle 是形参名 `target` —— 判据跟着**数据流**走，
        //   不跟着字面量走（否则会逼出一种"为了过门禁而多写一行"的写法）。
        { call: 'chatWithListingAgent(', needle: 'context_target: target', tag: '非流式降级' },
      ],
    },
    {
      file: P_CS,
      who: 'customerService',
      paths: [
        { call: 'streamSSE(', needle: 'context_target: ctx.contextTarget.value', tag: '流式' },
        // ★ 客服的降级路径同样把值当**参数**传进 `degradeCsText()`，
        //   所以这一处的 needle 是形参名 —— 理由与上面 Listing 那条相同。
        { call: 'chatWithCustomerService(', needle: 'context_target: contextTarget', tag: '非流式降级' },
      ],
    },
  ]
  for (const { file, who, paths } of REQUEST_PATHS) {
    const src = stripComments(readTs(file))
    for (const { call, needle, tag } of paths) {
      const i = src.indexOf(call)
      assert(i >= 0, `${who}：找不到调用点 \`${call}\` ⇒ 下面的断言会退化成恒真`)
      const block = balanced(src, i)
      assert(block.length > 40,
        `${who}：\`${call}\` 的参数块只解析出 ${block.length} 字符 —— 解析器失效，先修门禁`)
      assert(block.includes(needle),
        `${who} 的${tag}请求体里没有 \`${needle}\` ⇒ ` +
        (tag === '流式'
          ? '主路径没有对象信息，模型只能从用户消息 / 会话历史里猜"这次针对谁"'
          : '一次网络抖动就把「载入了对象」退化成「猜对象」—— 基础设施故障被说成业务结论'))
    }
  }
})

// ---------------------------------------------------------------- 汇总

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
console.log('四条回复链失败路径 + 主动取消 + 技能点名任务边界成立（真实原因上屏 · 不叠两条 · 不穿透兜底 · 取消不当失败 · 点名跨轮保持到产出结果 ✓）')
}

main().catch((e) => { console.error('门禁自身异常：', e); process.exit(2) })
