#!/usr/bin/env node
/**
 * 店秘书「交接追问」门禁（第 215 轮）
 *
 * ## 为什么需要它
 *
 * 老板发了一条 Amazon 商品链接说「这个选品帮我放入选品库」，收到的却是：
 *
 *     好嘞，这事儿交给 选品分析师 处理，他会在自己的对话里跟你确认几个细节…
 *     好的，**add** 这事儿我接住了。开干前再确认几件小事…
 *     • asin：请补充「asin」的信息   （× 5）
 *
 * 三段话**没有一句是 Agent 说的** —— 全是前端模板渲染出来的：
 *   · `replies/secretary.ts` 的交接模板（说成"他（子 Agent）会跟你确认"）
 *   · `clarification.ts` 的兜底问答（`请补充「X」的信息`）
 *   · `useChatEventBridge.ts` 的接管消息（渲染在**子 Agent 的对话区**里）
 *
 * 而 handoff 这条路径**只切页、不续跑**（续跑走 `agent-auto-task`）⇒ 子 Agent
 * 压根没运行。三段模板拼出来的样子与「Agent 真的读了消息后在反问」**完全一样**，
 * 于是老板把产品缺陷读成了「Agent 思考规划不好」。
 *
 * 本门禁钉住订正后的三件事：
 *   ① 接管消息**标明来源**、并明说「子 Agent 还没开始处理这一轮」；
 *   ② 老板**原话**回显到对话区（链接 / ASIN 这类信息不再随交接丢失）；
 *   ③ 退化的 intent（如工具代号 `add`）**不得**被当成产品名渲染。
 *
 * ## 反向注入（每条判据都必须能被证明会转红）
 *
 * * 删掉 `sourceNote` ⇒ ② 红；
 * * 删掉 `还没开始处理这一轮` ⇒ ③ 红；
 * * 删掉 `echo` 回显 ⇒ ④ 红；
 * * 去掉 `isDegenerateIntent(...)` 包裹 ⇒ ⑤ 红；
 * * 把 `isDegenerateIntent` 的判据改成 `return false` ⇒ ⑦ 红；
 * * 把兜底文案改回 `请补充「…」的信息` ⇒ ⑨ 红；
 * * `appActions.ts` 的 detail 去掉 `query` ⇒ ⑩ 红；
 * * 交接文案改回「他会在自己的对话里跟你确认」 ⇒ ⑪ 红。
 *
 * ## 铁律
 *
 * 判据一律在**剥离注释后**的源码上跑 —— 否则「注释里提到某关键词」就能骗过检查
 * （第 213 轮本仓实测过：`check-thinking-trace.cjs` 的 C2 曾因注释假红/假绿）。
 * 另有 `SELFCHECK` 段：每条正则都要在一个**必然不匹配**的样本上给出 false，
 * 防止正则写错成恒真（「没有反例的断言 = 没有断言」）。
 *
 * 用法：node scripts/check-handoff-clarification.cjs   （0 = 通过；1 = 有退化）
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   HANDOFF_FE_ROOT=<副本或空目录>    ⇒ ① …⑨ 全线红（四个源文件读不到）
 *
 */
const fs = require('fs')
const path = require('path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const FE = pick('HANDOFF_FE_ROOT', path.resolve(__dirname, '..'))
/**
 * ★ 第 351 轮 L3-11：读不到源 ⇒ 打印**可读 FAIL** 后退出（不再抛裸异常）。
 * 裸异常只有栈、没有「哪条判据红了」——外部聚合会把「门禁坏了」误当成「真红」。
 * 「拿不到权威清单 ≠ 清单为空」⇒ 红也要红得可读，且绝不放行。
 */
const read = (p) => {
  try {
    return fs.readFileSync(path.join(FE, p), 'utf8')
  } catch (e) {
    console.log(`  FAIL  读不到源文件：${p}`)
    console.log(`        ${e.code || 'ENOENT'} —— 本门禁靠它做判定，拿不到不许放行`)
    process.exit(1)
  }
}

/**
 * 剥离注释：`//` 行注释、块注释、HTML 注释。
 * （这里刻意**不写出块注释的结束符号** —— 写出来会提前终止本注释本身。）
 */
function stripComments(t) {
  return t
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\/[^\n]*/g, '')
}

const fails = []
function check(ok, label, detail) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}`)
  if (!ok) {
    if (detail) console.log(`        ${detail}`)
    fails.push(label)
  }
}

console.log('=== 店秘书交接追问门禁（第 215 轮）===')

const bridge = stripComments(read('src/composables/chat/useChatEventBridge.ts'))
const clar = stripComments(read('src/utils/clarification.ts'))
const actions = stripComments(read('src/utils/appActions.ts'))
const replies = stripComments(read('src/composables/chat/replies/secretary.ts'))

/** 取 `const handleSecretaryHandoff` → `const handleAgentAutoTask` 之间的函数体 */
function sliceBetween(src, aMark, bMark) {
  const a = src.indexOf(aMark)
  if (a < 0) return ''
  const b = src.indexOf(bMark, a)
  return b < 0 ? src.slice(a) : src.slice(a, b)
}

const handoffBody = sliceBetween(bridge, 'const handleSecretaryHandoff', 'const handleAgentAutoTask')
const dispatchBody = (() => {
  const i = actions.indexOf("action.type === 'handoff'")
  return i < 0 ? '' : actions.slice(i, i + 900)
})()
const repliesHandoff = (() => {
  // ★ 必须定位到**派发点**（`action === 'handoff' && agentId`），不能用
  //   `action === 'handoff'` —— 后者第一次出现是 `actionList.some(...)` 那处
  //   （判断"有没有 handoff 动作"），从那里往后 600 字符里当然找不到 `query,`
  //   ⇒ 门禁自己写错、报假红（本门禁首跑实测）。
  const i = replies.indexOf("action === 'handoff' && agentId")
  return i < 0 ? '' : replies.slice(i, i + 600)
})()

// ---------------- 定位 ----------------
check(handoffBody.length > 0, '① 定位到 handleSecretaryHandoff 函数体', '函数被改名/搬走了？')
check(dispatchBody.length > 0, '① 定位到 appActions 的 handoff 分支')
check(repliesHandoff.length > 0, '① 定位到 replies 的 handoff 派发点')

// ---------------- ②③ 来源标注 ----------------
// ★ 判据落在 `takeoverMsg` 的构造块上，**不是**「函数体里出现过这几个字」：
//   后者有一个致命漏洞 —— 只判 `由店秘书转交` 是否出现在函数里，把它的**使用**
//   删掉（`sourceNote` 的定义还在）判据仍然绿 ⇒ 假绿。
//   这正是「机制建好了 ≠ 数据在用」。所以要求标注**真的被拼进要渲染的消息**。
//   （本门禁首版就是这么写的，靠反向注入 J1/K1 才暴露出来。）
const takeoverMsgBlock = (() => {
  const i = handoffBody.indexOf('const takeoverMsg')
  return i < 0 ? '' : handoffBody.slice(i, i + 400)
})()

check(takeoverMsgBlock.length > 0, '① 定位到 takeoverMsg 构造块')
check(/由店秘书转交/.test(takeoverMsgBlock) || /sourceNote/.test(takeoverMsgBlock),
  '② 来源标注被拼进要渲染的消息（有消费点，不只是定义了变量）',
  '只定义 sourceNote 却没拼进消息 ⇒ 老板看不到来源标注，仍会读成子 Agent 在反问')
check(/还没开始处理这一轮/.test(handoffBody), '③ 明说子 Agent 未运行这一轮',
  '只说"转交"不够 —— 必须明说这一轮它还没开始，否则仍像它在问')

// ---------------- ④ 原话回显 ----------------
check(/（店秘书转达）/.test(handoffBody) && /query/.test(handoffBody),
  '④ 老板原话回显到对话区',
  'handoff 只切页不续跑，原话不落地 ⇒ 链接 / ASIN 这类信息永久丢失')

// ---------------- ⑤⑥⑦ 退化 intent ----------------
check(/isDegenerateIntent\s*\(/.test(handoffBody),
  '⑤ 接管处用 isDegenerateIntent 挡退化 intent',
  '不挡 ⇒ 渲染出「好的，**add** 这事儿我接住了」')
check(/export function isDegenerateIntent/.test(clar),
  '⑥ clarification 导出 isDegenerateIntent')
check(clar.includes('^[A-Za-z][A-Za-z0-9_.-]*$'),
  '⑦ isDegenerateIntent 判据 = 纯 ASCII 短串（不误伤中文产品名）',
  '判据被改宽 ⇒ 会把「水壶」这类真产品名也挡掉')

// ---------------- ⑧ 业务字段表 ----------------
const FIELDS = ['asin', 'title', 'price', 'review_count', 'rating', 'category', 'url']
const missingFields = FIELDS.filter(f => !new RegExp(`\\n  ${f}: \\{`).test(clar))
check(missingFields.length === 0, '⑧ 字段表覆盖选品 / 商品分析字段',
  `缺: ${missingFields.join(', ')} —— 缺了就落到「请补充「review_count」的信息」这种裸兜底`)

// ---------------- ⑨ 兜底文案口吻 ----------------
check(!/请补充「/.test(clar), '⑨ 兜底文案不再是「请补充「X」」祈使句',
  '祈使句 + 渲染在子 Agent 对话区 = 冒充 Agent 在追问')
check(/这项还没给我/.test(clar), '⑨ 兜底文案已改陈述式')

// ---------------- ⑩ 事件 detail 带 query ----------------
check(/query\?: string/.test(actions), '⑩ AppAction 的 handoff 声明带 query')
check(/query: action\.query/.test(dispatchBody), '⑩ 交接事件 detail 透传 query',
  '不透传 ⇒ 子 Agent 对话区拿不到原话')

// ---------------- ⑪⑫ 交接文案 + 派发 ----------------
check(!/他会在自己的对话里跟你确认/.test(replies),
  '⑪ 交接文案不再把模板追问说成子 Agent 的行为',
  '那句话把前端模板的追问归给了子 Agent（实测事故的原句）')
check(/我先替你问出来/.test(replies), '⑪ 交接文案已改成店秘书第一人称')
check(/query,/.test(repliesHandoff), '⑫ replies 的 handoff 派发传 query')

// ---------------- 判据自检（防正则恒真）----------------
console.log('  ---- 判据自检 ----')
const SELFCHECK = [
  [/由店秘书转交/, '由系统转交', '② 来源标注'],
  [/还没开始处理这一轮/, '稍后处理', '③ 未运行声明'],
  [/（店秘书转达）/, '（系统转达）', '④ 原话回显'],
  [/isDegenerateIntent\s*\(/, 'extractProductName(', '⑤ 退化 intent 守卫'],
  [/export function isDegenerateIntent/, 'function somethingElse', '⑥ 导出'],
  [/query: action\.query/, 'query: action.intent', '⑩ detail 透传'],
  [/我先替你问出来/, '他会跟你确认', '⑪ 第一人称'],
]
for (const [re, neg, name] of SELFCHECK) {
  check(!re.test(neg), `自检：${name} 判据不是恒真`, `正则在 ${JSON.stringify(neg)} 上也命中了`)
}
// ★ 否定式判据只保证「命中一个含它的样本」= 正则不是恒不匹配；
//   正例由上面的真源码断言负责（首版这里写成 `!re.test(x) && re.test(x)` 恒 false，自检自己红了）。
check(/请补充「/.test('请补充「x」的信息'), '自检：⑨ 正则能命中样本（非恒不匹配）')

console.log('')
if (fails.length) {
  console.log(`RESULT: FAIL（${fails.length} 处）—— 交接追问又会冒充 Agent / 丢原话`)
  process.exit(1)
}
console.log(`RESULT: PASS（交接追问门禁通过：来源标注 · 原话回显 · 退化 intent 守卫 · 字段表 · 兜底口吻 ✓）`)
