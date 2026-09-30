#!/usr/bin/env node
/**
 * 「提示词增强（星星按钮）」覆盖门禁 —— ★ 第 252 轮
 *
 * 为什么值得单独一个门禁
 * ====================
 * 星星按钮的本质是**一个契约**，不是一个 UI 装饰：
 * 后端 `AIGCAgent.enhance_prompt`（`_ENHANCE_PROMPT_SYSTEM`）承诺三件事 ——
 *   ① 只输出改写后的提示词本身；② **严禁编造未提供的业务事实**；③ 三维度补齐
 *      （任务目标 / 约束条件 / 期望的输出形式）。
 * 于是前端必须做到：
 *   · **唯一实现** —— 把「怎么判能不能点、失败了要不要覆盖」写两遍，两份必然漂移。
 *     最危险的那种漂移是**丢掉 degraded 判定**：后端 LLM 不可用时返回
 *     `degraded=true / enhanced=''`，没有守卫的那一份会**把用户原稿清成空串**。
 *   · **落点可对账** —— 这按钮要被复制到很多输入点。复制到第 7 个的时候，
 *     没人记得前 6 个在哪、也没人知道新加的那个该不该加。
 *     ⇒ 登记表 + 自动发现**两半都要**：只做登记表 ⇒ 新增的不进检查范围；
 *       只做自动发现 ⇒ 没人知道每个落点的业务上下文该写什么。
 *
 * 三个典型翻车方式（本门禁各钉一条）
 * ----------------------------------
 *   E1 **又内联了一份**（复制模板 + SVG 星芒 + 自己调 enhancePrompt）
 *   E2 覆盖赋值丢掉 degraded 守卫 ⇒ 后端降级时清空用户输入
 *   E3 新增了落点却没登记 / 登记了却忘了接（含 context 传错）
 *
 * 怎么跑
 * ======
 *   node scripts/check-prompt-enhance-coverage.cjs            做判定
 *   node scripts/check-prompt-enhance-coverage.cjs --report   只打印盘面读数
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**：`PROMPT_ENHANCE_SRC_ROOT=<副本 src 目录>`
 * ★ 每条注入之间必须从真文件重新生成副本，否则上一条的注入会把下一条判红（假红）。
 *   还必须有一条**基线绿**（副本原样）与一条**对照绿**（只动注释）。
 *
 * ★ 与相邻门禁的分工
 *   · `check-agent-scope-lifecycle.cjs` —— Agent 级共享上下文的生命周期（切 Agent 时的清空/默认态）
 *   · 本门禁 —— 「输入区的辅助能力」的唯一实现与落点覆盖；它不管增强质量好不好
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.PROMPT_ENHANCE_SRC_ROOT
  ? path.resolve(process.env.PROMPT_ENHANCE_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 冻结清单

/** 唯一实现所在文件（相对 SRC_ROOT，正斜杠） */
const COMPONENT = 'components/common/PromptEnhanceButton.vue'

/** 组件内「处理增强」的函数锚点 —— 名字变了本门禁会**显式报错**要求同步 */
const HANDLE_ANCHOR = 'async function handleEnhance()'

/** 覆盖赋值的唯一形态（拿到增强结果后回写） */
const WRITE_BACK_ANCHOR = "emit('update:modelValue'"

/**
 * 落点登记表：**每个**被接入的输入点都要在这里出现。
 *
 * `field` 是该输入点绑定的字段（必须与模板里的 `v-model="<field>"` 逐字相同）；
 * `ctx` 是传给后端的业务上下文（后端把它拼进 LLM 提示词，见 `_ENHANCE_PROMPT_SYSTEM`）。
 * `why` 写给下一个人看：为什么这一处**值得**加（判据：这段文字会不会被当成
 * 「指令 / 规格 / 自然语言需求」送给模型）。
 */
const SITES = [
  { file: 'components/ChatPanel/index.vue', field: 'inputMessage', ctx: 'ecommerce',
    why: '对话框草稿：整段就是给 Agent 的任务描述' },
  { file: 'components/TaskConfigPanel/configs/StaticAssetConfig.vue', field: 'form.extraPrompt', ctx: 'aigc-image',
    why: '静态素材「完整提示词」：填写后**全权覆盖**参数配置，直接送给出图模型' },
  { file: 'components/TaskConfigPanel/configs/VideoGeneratorConfig.vue', field: 'form.extraPrompt', ctx: 'aigc-video',
    why: '视频生成「额外指令」：拼进视频生成要求' },
  { file: 'components/TaskConfigPanel/configs/VideoScriptConfig.vue', field: 'form.extraScriptPrompt', ctx: 'video-script',
    why: '带货脚本「额外要求」：写脚本的硬约束' },
  { file: 'components/SkillStore/SkillManager.vue', field: 'form.content', ctx: 'skill-authoring',
    why: '技能正文：模型照着执行的**规格**（补齐适用条件/步骤/输出格式/红线）' },
  // ★ 第 252 轮曾在此留过一条「⚠️ 明确**不**登记 IntelAnalysisConfig.vue」的说明：
  //   那时该面板还在，只是**不可达**（四个 intel-* id 没有任何 UI 路径能写进
  //   `currentSelectedTool`），所以不给不可达面板挂按钮。
  // ★★ 第 255 轮（#918）：该面板与其 6 个同族配置面板**已随 12 个不可达工具一并删除**
  //   ⇒ 上面那条"不登记"说明随之失效（说明本身也成了悬空引用，故一并收口）。
  //   本清单的完整性由 A 组正向对照钉住：登记项必须真实存在、且真的挂了按钮。
]

// ---------------------------------------------------------------- 读取与工具

function readSrc(rel) {
  // ★ 行尾归一化：本仓 CRLF / LF 混存 ⇒ 不归一化会让锚点静默 0 命中
  return fs.readFileSync(path.join(SRC_ROOT, rel), 'utf8').replace(/\r\n/g, '\n')
}

/** 递归收集所有 .vue（相对路径用正斜杠，与登记表口径一致） */
function walkVue(dir, base = dir) {
  const out = []
  if (!fs.existsSync(dir)) return out
  for (const name of fs.readdirSync(dir)) {
    const abs = path.join(dir, name)
    const st = fs.statSync(abs)
    if (st.isDirectory()) out.push(...walkVue(abs, base))
    else if (name.endsWith('.vue')) {
      out.push(path.relative(base, abs).split(path.sep).join('/'))
    }
  }
  return out
}

/**
 * 剥注释：JS 的行注释 / 块注释 **加上** Vue 模板的 `<!-- -->`。
 *
 * ★ 模板注释必须剥：本门禁判的「有没有用这个组件」，靠的就是模板里的标签。
 *   漏剥 ⇒ 把注释掉的用法算成在用（假绿），而注释掉一处落点正是最常见的「临时下线」手法。
 */
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
    if (c === '<' && src.startsWith('<!--', i)) {
      i += 4
      while (i < n && !src.startsWith('-->', i)) i++
      i += 3
      continue
    }
    out += c
    i++
  }
  return out
}

/**
 * 取从 `startIdx` 起第一个 `{` 到**匹配** `}` 的整块。
 * ★ 不用「往后截 N 字符」的窗口写法：窗口一旦不够，判据会**静默假绿**。
 */
function balancedBlock(src, startIdx) {
  const i0 = src.indexOf('{', startIdx)
  if (i0 < 0) return ''
  let depth = 0
  for (let i = i0; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}') {
      depth--
      if (depth === 0) return src.slice(i0, i + 1)
    }
  }
  return ''
}

function countOf(hay, needle) {
  if (!needle) return 0
  return hay.split(needle).length - 1
}

/**
 * 落点双向对账（**判定函数与数据分离** ⇒ 第 4 组可以用假数据自检）。
 * @param {{rel:string, text:string}[]} files 已剥注释的文件内容
 * @param {{file:string, field:string, ctx?:string}[]} sites 登记表
 */
function auditSites(files, sites) {
  const byRel = new Map(files.map((f) => [f.rel, f.text]))
  const missingInFile = []
  for (const s of sites) {
    const t = byRel.get(s.file)
    if (t === undefined) { missingInFile.push(`${s.file} —— 登记了但文件不在扫描树里`); continue }
    if (!t.includes('<PromptEnhanceButton')) { missingInFile.push(`${s.file} —— 登记了但模板里没有 <PromptEnhanceButton`); continue }
    if (!t.includes(`v-model="${s.field}"`)) { missingInFile.push(`${s.file} —— 按钮没绑到登记的字段 ${s.field}`); continue }
    if (s.ctx && !t.includes(`context="${s.ctx}"`)) missingInFile.push(`${s.file} —— 业务上下文没传成 ${s.ctx}`)
  }
  const registered = new Set(sites.map((s) => s.file))
  const unregisteredFiles = files
    .filter((f) => f.text.includes('<PromptEnhanceButton') && !registered.has(f.rel))
    .map((f) => f.rel)
  return { missingInFile, unregisteredFiles }
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

// ---------------------------------------------------------------- 读盘面

const vueRels = walkVue(SRC_ROOT)
const vueFiles = vueRels.map((rel) => ({ rel, text: stripComments(readSrc(rel)) }))

const componentRel = COMPONENT
const componentExists = vueRels.includes(componentRel)
const componentRaw = componentExists ? readSrc(componentRel) : ''
const componentText = componentExists ? stripComments(componentRaw) : ''

// ---------------------------------------------------------------- E0 基线自检
// 先证明「读到了、认得出」—— 否则后面所有判据都可能在全空文本上跑成「全绿」

check('E0 基线：组件与登记表都读到了（防扫描根写错导致全空跑）', () => {
  assert(componentExists, `扫描根 ${SRC_ROOT} 下找不到 ${COMPONENT} —— 路径或扫描根不对`)
  assert(componentRaw.length > 800, `${COMPONENT} 只有 ${componentRaw.length} B —— 不像是完整组件`)
  assert(SITES.length >= 2, `登记表只有 ${SITES.length} 条 —— 至少应有对话框 + 一个表单落点`)
  const consumers = vueFiles.filter((f) => f.text.includes('<PromptEnhanceButton')).length
  assert(consumers >= 2, `扫描树里只有 ${consumers} 个文件用了 <PromptEnhanceButton —— 扫描根可疑`)
})

// ---------------------------------------------------------------- E1 唯一实现

check('E1 提示词增强只有一份实现：调用与星芒图标都只允许出现在公共组件里', () => {
  const callers = vueFiles.filter((f) => countOf(f.text, 'enhancePrompt(') > 0).map((f) => f.rel)
  assert(callers.length === 1 && callers[0] === componentRel,
    `调用 enhancePrompt(...) 的文件有 ${JSON.stringify(callers)}（要求恰好只有 ${componentRel}）—— ` +
    '又内联了一份实现；两份必然漂移，且丢掉 degraded 守卫的那一份会把用户原稿清空')
  const sparks = vueFiles.filter((f) => countOf(f.text, 'class="sparkle-icon"') > 0).map((f) => f.rel)
  assert(sparks.length === 1 && sparks[0] === componentRel,
    `内联 SVG 星芒出现在 ${JSON.stringify(sparks)}（要求恰好只有 ${componentRel}）—— ` +
    '模板也被复制了 ⇒ 样式与三态 tooltip 会各改各的')
})

// ---------------------------------------------------------------- E2 降级不覆盖

check('E2 降级不覆盖：拿到增强结果前的 degraded 守卫必须还在', () => {
  const at = componentText.indexOf(HANDLE_ANCHOR)
  assert(at >= 0,
    `${COMPONENT} 里找不到 \`${HANDLE_ANCHOR}\` —— 函数被改名了？` +
    '请同步本门禁的 HANDLE_ANCHOR（不许在这里放宽成「找不到就算过」）')
  const body = balancedBlock(componentText, at)
  assert(body.length > 80, `\`${HANDLE_ANCHOR}\` 的函数体只解析出 ${body.length} 字符 —— 括号平衡器失效`)
  const iDeg = body.indexOf('degraded')
  const iWrite = body.indexOf(WRITE_BACK_ANCHOR)
  assert(iDeg >= 0,
    '函数体里没有 degraded 判定 ⇒ 后端 LLM 不可用时（degraded=true / enhanced=""）' +
    '会把用户原稿覆盖成空串')
  assert(iWrite >= 0, `函数体里没有 ${WRITE_BACK_ANCHOR} —— 增强了却回写不出去？`)
  assert(iDeg < iWrite,
    'degraded 判定排在覆盖赋值**之后** ⇒ 等于没有守卫（顺序错了判据也就没了）')
  assert(body.includes('message.warning'),
    '失败路径没有 message.warning ⇒ 用户只看到「点了没反应」')
  assert(body.includes('catch'),
    '① 没有 try/catch ⇒ 网络异常会被静默吞掉（既不提示也不回写）')
})

// ---------------------------------------------------------------- E3 落点对账

check('E3 落点双向对账：登记的必须接了（字段 + context），接了的必须登记', () => {
  const { missingInFile, unregisteredFiles } = auditSites(vueFiles, SITES)
  assert(missingInFile.length === 0,
    '以下登记落点没接上：\n      ' + missingInFile.join('\n      '))
  assert(unregisteredFiles.length === 0,
    `以下文件用了 <PromptEnhanceButton 却没登记进 SITES：${JSON.stringify(unregisteredFiles)}\n` +
    '      ⇒ 它不会有「该不该加」的复核，也没人会知道它的 context 传了什么')
})

// ---------------------------------------------------------------- E4 自检（反向）

check('E4 自检（反向）：剥注释生效 + 对账函数两半都能报出来', () => {
  const fake = stripComments('<template>\n<!-- <PromptEnhanceButton v-model="x" /> -->\n</template>')
  assert(!fake.includes('<PromptEnhanceButton'),
    '剥模板注释没生效 ⇒ 注释掉的落点会被算成「接了」= 最危险的假绿')

  // 登记了但没接（字段对不上）
  const r1 = auditSites(
    [{ rel: 'a.vue', text: '<PromptEnhanceButton v-model="other" context="c" />' }],
    [{ file: 'a.vue', field: 'x', ctx: 'c' }])
  assert(r1.missingInFile.length === 1 && r1.unregisteredFiles.length === 0,
    '对账函数认不出「登记了但没接」⇒ E3 会假绿')

  // 接了但没登记
  const r2 = auditSites(
    [{ rel: 'a.vue', text: '<PromptEnhanceButton v-model="x" />' },
     { rel: 'b.vue', text: '<PromptEnhanceButton v-model="y" />' }],
    [{ file: 'a.vue', field: 'x' }])
  assert(r2.unregisteredFiles.length === 1 && r2.unregisteredFiles[0] === 'b.vue'
    && r2.missingInFile.length === 0,
    '对账函数认不出「接了但没登记」⇒ 新增落点会静默溜过')

  // context 传错（这是最容易写错、后果最隐蔽的一处：后端把它拼进 LLM 提示词）
  const r3 = auditSites(
    [{ rel: 'a.vue', text: '<PromptEnhanceButton v-model="x" context="wrong" />' }],
    [{ file: 'a.vue', field: 'x', ctx: 'right' }])
  assert(r3.missingInFile.length === 1, '对账函数认不出「context 传错」⇒ 业务域串味没人发现')
})

// ---------------------------------------------------------------- 盘面 / 汇总

if (REPORT_ONLY) {
  console.log(`扫描根：${SRC_ROOT}`)
  console.log(`扫描到 .vue：${vueRels.length} 个`)
  console.log(`唯一实现：${COMPONENT}（${componentRaw.length} B）`)
  console.log(`落点登记表：${SITES.length} 条`)
  for (const s of SITES) console.log(`  · ${s.file}  v-model="${s.field}"  context="${s.ctx}"`)
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
console.log('提示词增强成立（唯一实现 · 降级不覆盖 · 落点双向对账 ✓）')
