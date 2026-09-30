#!/usr/bin/env node
/**
 * 思考过程展示门禁（第 210 轮）
 *
 * ============================================================================
 * ★ 为什么需要这道门禁（老板原话）
 * ============================================================================
 *   「现在给agent增加一个思考过程的展示，目前只是转圈显示几秒钟，
 *    然后有结果出结果（过程折叠掉）」
 *
 * 这句话里藏着**三类会静默丢失**的东西 —— 丢了都不报错、不红、不异常：
 *
 *   ① **过程断链**：后端逐条发 `event: step`，前端要经「解析 → 合并 → 装配
 *      → 渲染」四跳才到屏幕。任何一跳漏了，症状都不是报错，而是
 *      「转圈几秒 → 直接出结果」—— 也就是**老板抱怨的那个现状**。
 *      四跳里最容易漏的是**第 4 跳（每条回复链各接一次 `onStep`）**：
 *      它有 5 个平行副本，新加一条链路时没人会想起来。
 *
 *   ② **合并键用错**：后端对一次工具调用发**两条**事件（开始 + 结束），
 *      靠 `id`(run_id) 合成一行。若退化成无脑 `push`，界面一次调用显示两行、
 *      且第一行永远停在「正在」—— 看起来像卡死。这个退化**不报错**。
 *
 *   ③ **兜底转圈不退场**：轨迹出现后若还叠一个 `a-spin`，就是"该退场的地方
 *      没退场"，用户看到两套反馈各占一块。
 *
 * ★ 本门禁只判**形态**（接线 / 顺序 / 结构），不判文案。
 *   文案类断言是"墓志铭"：改文案就红，改结构反而不红，方向正好相反。
 *
 * ★ 反向注入靶子（本门禁必须能被这些改动**转红**，否则等于没有门禁）：
 *   I1 删掉 `stream.ts` 的 `step` 分发分支        → A2
 *   I2 把 `chat.ts` 的 `push` 挪到 dedupe 之前     → B1
 *   I3 某条回复链删掉 `onStep`                     → C1
 *   I3' 某条回复链自己写轨迹（如 `msg.thinkingSteps.push(…)`）→ C2
 *       对照：只在**注释**里提到 `thinkingSteps` 必须**保持绿**（否则是假红）
 *   I4 `ChatPanel` 的转圈去掉 `!hasLiveTrace`      → D4
 *   I5 `ThinkingTrace` 的默认开合不再跟随 loading   → E1
 *   I7 `ThinkingTrace` 去掉 `s.tool !== s.title`     → E6
 *   I8 `stream.ts` 删掉 `preview` 分发分支          → F2a/F2b
 *   I9 店秘书链路的 `onDelta` 改回 `appendToLastMessage` → F5
 *      （预览与正文会在屏上拼两遍，且**零报错**）
 *   I10 `secretary.ts` 去掉 `onPreview` 接线        → F4
 *   对照（必须保持全绿）：把任意一句注释改几个字。
 *
 * ★★ 第 238 轮加的 F 组：`event: preview`（模型 token 实时下发）。
 *   为什么它必须进本门禁：老板抱怨的「14.7 秒零输出」根因就是**没接这一跳**。
 *   探针 238d 实测真图会发 10~11 条 token 事件 —— **管子是通的**，
 *   而"通了但没人取"在界面上**没有任何报错**，只是空窗十几秒。
 *   形态上它与 `step` 同构（解析 → 回调 → 收口三跳），故并进本门禁。
 */

const fs = require('fs')
const path = require('path')

const ROOT = process.env.THINKING_TRACE_SRC_ROOT || path.join(__dirname, '..', 'src')

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}
function read(rel) {
  const p = path.join(ROOT, rel)
  if (!fs.existsSync(p)) return null
  // ★ 行尾必须归一化：本仓同一文件可 CRLF / LF 混存，
  //   不归一化会让锚点静默失配（症状是"找不到分发分支"，方向错得很远）。
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

const stream = read('api/stream.ts')
const chat = read('stores/chat.ts')
const runtime = read('composables/chat/useChatRuntime.ts')
const panel = read('components/ChatPanel/index.vue')
const trace = read('components/ChatPanel/ThinkingTrace.vue')

// ---------------------------------------------------------------- A0 前置
check(
  !!(stream && chat && runtime && panel && trace),
  'A0 五个承载文件都存在',
  '缺文件 ⇒ 下面所有断言都会在 null 上做正则，退化成"空集恒真"。' +
    `实测：stream=${!!stream} chat=${!!chat} runtime=${!!runtime} ` +
    `panel=${!!panel} trace=${!!trace}`
)
if (!stream || !chat || !runtime || !panel || !trace) {
  report()
  process.exit(1)
}

// ================================================================ A 第 1~3 跳
// 事件通路：SSE 帧解析 → onStep 回调。缺任一即"后端在发、前端收不到"。
check(
  /onStep\?\s*:\s*\(/.test(stream),
  'A1 SSEHandlers 声明了 onStep 回调',
  '缺 onStep 声明 ⇒ 事件到了也没有承载口'
)
check(
  /eventType === 'step'/.test(stream),
  'A2a 解析器识别 step 事件',
  "缺少 `eventType === 'step'` 分支 ⇒ 后端的 step 帧被静默丢弃（与 progress 同待遇）"
)
check(
  /handlers\.onStep\?\.\(/.test(stream),
  'A2b step 帧真的回调了 onStep',
  '识别了事件类型但没回调 ⇒ 声明是摆设（典型"接线了但没生效"）'
)
// ★ A3 的判据必须**剥掉注释**且**只取分支体**，不能全文件正则。
//   第一版写成 `!(/fullText\s*\+=[^]*?eventType === 'step'/)`：反向断言从最早的
//   `fullText +=` 一路懒匹配到 step 分支 ⇒ **必然命中**（假红，判据自己在说反话）。
//   而改成看整个文件同样会假红 —— 该分支的注释里恰好写着「它不计入 fullText」。
//   两个方向都被骗过，说明"源码字符串包含"根本不配当形态判据。见本仓铁律。
function stripComments(src) {
  let out = ''
  let q = null
  for (let i = 0; i < src.length; ) {
    const c = src[i]
    if (q) {
      if (c === '\\') { out += c + (src[i + 1] ?? ''); i += 2; continue }
      if (c === q) q = null
      out += c
      i++
      continue
    }
    if (c === '"' || c === "'" || c === '`') { q = c; out += c; i++; continue }
    if (c === '/' && src[i + 1] === '/') { while (i < src.length && src[i] !== '\n') i++; continue }
    if (c === '/' && src[i + 1] === '*') {
      i += 2
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
      continue
    }
    out += c
    i++
  }
  return out
}
function blockAfter(src, anchor) {
  const at = src.indexOf(anchor)
  if (at < 0) return null
  const open = src.indexOf('{', at)
  if (open < 0) return null
  let depth = 0
  for (let j = open; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') { depth--; if (depth === 0) return src.slice(open + 1, j) }
  }
  return null
}

const stepBlock = blockAfter(stripComments(stream), "eventType === 'step'")
check(
  stepBlock !== null,
  'A3a 自检：取到了 step 分支的代码体',
  '取不到分支体 ⇒ A3b 会退化成"空集恒真"（本仓铁律：判据要先证明自己不是在空跑）'
)
check(
  stepBlock !== null && !/fullText/.test(stepBlock),
  'A3b step 分支不碰正文累加',
  'step 若参与 fullText 累加，工具入参/返回会漏进答复正文'
)

// ================================================================ B 合并口径
// ★ 顺序即判据：**先查重再追加**。反过来写（先 push 再查重）在语法上完全合法，
//   但界面上一次工具调用会变成两行、且第一行永远停在「正在」。
const dedupeAt = chat.indexOf('find((s) => s.id === step.id)')
const pushAt = chat.indexOf('last.thinkingSteps.push(step)')
check(
  dedupeAt >= 0,
  'B1a 按 id 查重的分支存在',
  '没有按 id 查重 ⇒ 一次工具调用（后端两条事件）会在界面上显示两行'
)
check(
  dedupeAt >= 0 && pushAt > dedupeAt,
  'B1b 查重发生在追加之前',
  `查重必须排在 push 之前。实测 dedupeAt=${dedupeAt} pushAt=${pushAt}`
    + '（push 在前 = 每步都会多push一条，查重形同虚设）'
)
check(
  /Object\.assign\(same,\s*step\)/.test(chat),
  'B2 结束态用 Object.assign 合并（保留 detail）',
  '后端结束态**不发** detail；若改成整体替换，入参会凭空消失'
)
check(
  /appendThinkingStep/.test(runtime) && /chatStore\.appendThinkingStep\(/.test(runtime),
  'B3 runtime 是唯一写入点（转发给 store）',
  'runtime 若不转发，reply 链上的 onStep 拿到的是个没人接的回调'
)

// ================================================================ C 第 4 跳 · 5 条平行副本
//
// ★ 名单**从源码树派生**，不手写 —— 手写名单会在"下一条链路加进来"时静默过期，
//   而那正是本门禁要防的东西（同一形态：确认清单写死在门禁里 ⇒ 门禁自己腐烂）。
const repliesDir = path.join(ROOT, 'composables', 'chat', 'replies')
const replyFiles = fs.existsSync(repliesDir)
  ? fs.readdirSync(repliesDir).filter((f) => f.endsWith('.ts'))
  : []
const chains = replyFiles.filter((f) => /streamSSE\(/.test(read(`composables/chat/replies/${f}`) || ''))

check(
  chains.length >= 4,
  'C0 自检：抽到了 ≥4 条走 streamSSE 的回复链',
  '一条都没抽到 ⇒ C1 会退化成"空集 == 空集"式的恒真（本仓铁律：判据要先证明自己不是在空跑）。'
    + `实测抽到 ${chains.length} 条：${JSON.stringify(chains)}`
)
const noStep = chains.filter((f) => !/onStep:\s*handleThinkingStep/.test(read(`composables/chat/replies/${f}`) || ''))
check(
  noStep.length === 0,
  'C1 每条流式回复链都接了 onStep',
  `漏接的链路会"转圈几秒 → 直接出结果"（正是老板抱怨的现状），且零报错。漏接：${JSON.stringify(noStep)}`
)
/**
 * ★ C2 的判据在**第 213 轮**改过口径，两个原因：
 *
 *   ① **必须先剥注释**：本仓铁律「判据禁源码字符串包含」—— 店秘书切流式的那个
 *      reply 链里，解释「过程与正文都挂在最后一条消息上」的注释恰好会写出这个
 *      标识符 ⇒ 用**原文本**正则就是**假红**（实测踩到：C2 报了 `["secretary.ts"]`，
 *      而那两处只是注释）。假红比不检查更糟 —— 下一个人会把断言删掉。
 *   ② **收紧成"写"而不是"出现过"**：真正的风险是「两条链路各自维护一份轨迹」
 *      （合并口径漂移）。**读**它（例如把过程原样带到另一条消息上）不构成第二个
 *      真源，**写**才构成。旧正则既把读误判成写，又漏了 `thinkingSteps = []`
 *      这种整体赋值。
 */
const WRITE_STEP_RE =
  /appendThinkingStep\s*\(|thinkingSteps\s*[:=]|thinkingSteps\s*\.\s*(push|splice|unshift)\s*\(/
const chainSideWrite = chains.filter(
  (f) => WRITE_STEP_RE.test(stripComments(read(`composables/chat/replies/${f}`) || ''))
)
check(
  chainSideWrite.length === 0,
  'C2 回复链不许自己写 thinkingSteps（不许有第二个真源）',
  '两条链路各写一份 ⇒ 合并口径必然漂移，且症状只是"某条链路的步骤多一行"。' +
    `命中：${JSON.stringify(chainSideWrite)}`
)
// ★ C2 判据自检：不证明"改宽松之后写还抓得住"，就无法区分「判据变准了」与
//   「判据被改废了」（本仓铁律：判据要先证明自己不是在空跑）。
const C2_SAMPLES = [
  ['写·调用 appendThinkingStep', 'chatStore.appendThinkingStep(step)', true],
  ['写·整体赋值', 'msg.thinkingSteps = []', true],
  ['写·直接 push', 'msg.thinkingSteps.push(step)', true],
  ['读·只是把过程带过去', 'const prev = list.at(-1)?.thinkingSteps', false],
  ['注释·解释过程挂在哪', '// 过程与正文都挂在 thinkingSteps 上', false],
]
const c2miss = C2_SAMPLES.filter(([, code, want]) => WRITE_STEP_RE.test(stripComments(code)) !== want)
check(
  c2miss.length === 0,
  'C2 自检：写形态抓得住 / 读与注释不误判',
  '判据与预期不符：' + JSON.stringify(c2miss.map(([n, , w]) => `${n}（期望${w ? '命中' : '不命中'}）`))
    + ' —— 判据被改废了，C2 会变成恒真'
)

// ================================================================ D 第 5 跳 · 渲染与兜底
check(
  /<ThinkingTrace/.test(panel),
  'D1 ChatPanel 挂载了 ThinkingTrace',
  '组件写了但没挂 ⇒ 过程永远不显示（"接线了但没渲染"）'
)
check(
  /:steps="msg\.thinkingSteps/.test(panel),
  'D2 轨迹取自当前消息（不是全局单例）',
  '轨迹必须住在消息上 —— 住全局单例会跨轮残留，历史消息的折叠态互相污染'
)
check(
  /:loading="isLoading && index === messages\.length - 1"/.test(panel),
  'D3 loading 只认「正在跑的那一条」',
  'loading 若对历史消息也为真，旧轨迹会永远停在「进行中」'
)
check(
  /v-if="isLoading\s*&&\s*!hasLiveTrace"/.test(panel),
  'D4 已有轨迹时转圈退场（保留它只为"第一秒零步骤"兜底）',
  '转圈不退场 ⇒ 轨迹与转圈各占一块（老板原话「目前只是转圈显示几秒钟」，该退场就得退场）'
)
check(
  /const hasLiveTrace = computed\(/.test(panel) && /\?\?|\?\./.test(panel),
  'D5 hasLiveTrace 只认最后一条消息',
  '拿历史消息里的旧轨迹判断，会让转圈在该出现时不出现（那一轮可能压根没有工具调用）'
)

// ================================================================ E 组件自身语义
check(
  /manual\.value \?\? !!props\.loading/.test(trace),
  'E1 默认开合跟随 loading（流光中展开、出结果后折叠）',
  '老板要的是"过程中可见 + 有结果后折叠"两态；默认写死开或写死合都只满足一半'
)
check(
  /manual\.value = null/.test(trace),
  'E2 新一轮开始时清掉上一轮的手动干预',
  '复用消息（v-for key 退化）时手动折叠态会跨轮残留，且零报错'
)
check(
  /s\.status === 'running' && !props\.loading/.test(trace),
  'E3 流光结束后仍 running 的步骤映射成"未完成"',
  '后端只知道"有没有收到 on_tool_end"。触发人工审批而暂停时，照原样渲染「进行中」' +
    '会留一个永远转圈的假象'
)
check(
  /s\.tool/.test(trace),
  'E4 原始工具名必须渲染出来',
  '第 211 轮起 title 是**人话名**（后端注入 resolver 得到），原始英文名反而更重要：' +
    '它是「这一步到底是什么工具」的排查口。界面若只显示标题，降级就不可见了'
)
check(
  /s\.tool && s\.tool !== s\.title/.test(trace),
  'E6 title 与 tool 相同时不重复渲染（工具未登记进目录的形态）',
  '`tool_title()` 对未登记的名字**原样返回**（老数据 / 第三方工具）⇒ 不做这条判断，' +
    '界面会出现两遍同样的名字'
)
check(
  !/#[0-9a-fA-F]{3,8}\b/.test(trace),
  'E5 组件内无硬编码颜色（全走主题变量）',
  '写死 hex ⇒ 深色主题下本组件会变成一块看不清的浅色补丁'
)

// ================================================================ F 预览通道（第 238 轮）
check(
  /onPreview\?\s*:/.test(stream),
  'F1 SSEHandlers 声明了 onPreview 回调',
  '缺声明 ⇒ 后端的 preview 帧到了也没有承载口'
)
check(
  /eventType === 'preview'/.test(stream),
  'F2a 解析器识别 preview 事件',
  "缺少 `eventType === 'preview'` 分支 ⇒ 预览帧被静默丢弃（= 老板抱怨的空窗原样复现）"
)
check(
  /handlers\.onPreview\?\.\(/.test(stream),
  'F2b preview 帧真的回调了 onPreview',
  '识别了事件类型但没回调 ⇒ 声明是摆设（典型"接线了但没生效"）'
)
// ★ F3 与 A3 同形：判据必须**剥注释**且**只取分支体**。
//   全文件正则会被注释骗过（该分支的注释里恰好写着「不累进 fullText」），
//   而懒匹配跨分支又会**必然命中**（假红）。两个方向都被骗过的判据不配当判据。
const previewBlock = blockAfter(stripComments(stream), "eventType === 'preview'")
check(
  previewBlock !== null,
  'F3a 自检：取到了 preview 分支的代码体',
  '取不到分支体 ⇒ F3b 会退化成"空集恒真"（本仓铁律：判据要先证明自己不是在空跑）'
)
check(
  previewBlock !== null && !/fullText/.test(previewBlock),
  'F3b preview 分支不碰正文累加',
  'preview 若参与 fullText 累加，done 与落库都会变成「预览 + 正文」拼两遍，而且零报错'
)
// ★ F3 判据自检：喂合成样本，证明"混进正文"抓得住、"干净"不误报。
function previewBlockOf(code) {
  return blockAfter(stripComments(code), "eventType === 'preview'")
}
const F3_SAMPLES = [
  ['干净·只回调', "} else if (eventType === 'preview') {\n  handlers.onPreview?.(t, s)\n}", false],
  ['违规·累进正文', "} else if (eventType === 'preview') {\n  fullText += t\n}", true],
  ['违规·混进 delta 分支', "} else if (eventType === 'preview') {\n  handlers.onDelta?.(t)\n}", false],
]
const f3miss = F3_SAMPLES.filter(([, code, want]) => {
  const b = previewBlockOf(code)
  return (b !== null && /fullText/.test(b)) !== want
})
check(
  f3miss.length === 0,
  'F3 自检：preview 分支里混进 fullText 抓得住、干净样本不误报',
  '判据与预期不符：' + JSON.stringify(f3miss.map(([n]) => n))
)
// ★ F4/F5：预览是**逐 token** 的，最终正文是**整段**下发的
//   ⇒ 消费方必须"整段替换"，不能"接着往后追加"。
//   追加的后果：屏上 = 预览 + 正文（同一段话两遍），零报错。
const previewChains = chains.filter(
  (f) => /onPreview\s*:/.test(stripComments(read(`composables/chat/replies/${f}`) || ''))
)
check(
  previewChains.includes('secretary.ts'),
  'F4 店秘书链路接了 onPreview',
  '后端**只有店秘书**发 preview（其余 5 家的 token 就是正文，走 delta）。' +
    `漏接 ⇒ 预览通道白做，症状与老板抱怨的"十几秒零输出"一样。实测接了：${JSON.stringify(previewChains)}`
)
const badSink = previewChains.filter((f) => {
  const body = blockAfter(stripComments(read(`composables/chat/replies/${f}`) || ''), 'onDelta:')
  // 取不到 onDelta 体也判违规：那时无法证明它把预览收口了
  return body === null || !/setLastMessageContent/.test(body) || /appendToLastMessage/.test(body)
})
check(
  badSink.length === 0,
  'F5 接了预览的链路必须把正文**整段收口**（不是追加）',
  '预览与正文跑同一条通道，追加 ⇒ 屏上「预览 + 正文」拼两遍（零报错）。' +
    `命中：${JSON.stringify(badSink)}`
)

report()

function report() {
  const bad = results.filter((r) => !r.ok)
  for (const r of results) {
    console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.label}`)
    if (!r.ok && r.detail) console.log(`        ↳ ${r.detail}`)
  }
  console.log('')
  if (bad.length) {
    console.log(`思考过程展示门禁失败：${bad.length} / ${results.length}`)
    process.exit(1)
  }
  console.log(`思考过程展示门禁通过（${results.length} 条形态断言 ✓）`)
}
