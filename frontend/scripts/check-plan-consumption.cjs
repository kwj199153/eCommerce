#!/usr/bin/env node
/**
 * 「计划真的接到界面上了吗」门禁（★ 第 155 轮）
 *
 * 为什么需要它
 * ============
 * 第 148 轮（批 C3）完成了规划器的**全部后端机制**：`plan_tasks` / `update_task`
 * 两个工具、计划落图状态、`OrchestratorResponse.plan` 回传，还配了断言。交付说明里
 * 写着**「子任务状态可在 UI 展示」**。
 *
 * 第 155 轮实测：**并没有**。
 *   · `api/secretary.ts` 的 `SecretaryResponse` **没有声明 `plan` 字段**；
 *   · 编排层**从不读** `res.plan`；
 *   · 全仓**没有任何**计划/待办渲染组件。
 * 而后端那边一切正常（端点回填了 `plan=result.get("plan")`）。
 *
 * 也就是说：**计划出了后端就消失了，界面上一个像素都没有** —— 而当时的门禁
 * 恰好停在断点前一步（只断言"端点回填了字段"）。这与 `/accounts/*` 那次
 * （9 个端点全闲置）、`Settings.vue` 那次（7 处全 404）是**同一个形态**。
 *
 * ⇒ 必须有一条断言，能对「后端有、前端没人用」这件事说不。
 *
 * 五环，逐环钉死
 * ==============
 *   A 后端**真的**在下发：`chat` 端点的响应模型有 `plan` 字段，且端点确实回填了它
 *     （只查字段不看回填 = 字段永远是 None 的死字段）。
 *   B API 类型层**声明**了它：`SecretaryResponse` 有 `plan`，且有对应的类型定义
 *     （没有类型 = 拿到也不认识，TS 会直接把它当 any 丢掉）。
 *   C 编排层**消费**了它：`useChatOrchestrator` 里真的调了 `chatStore.setPlan(...)`，
 *     且 `chatWithSecretary` 的响应确实被喂了进去。
 *   D store**持有**了它：`chatStore` 有三个方法（get/set/clear），且 `setPlan`
 *     保留了三态语义（`undefined` = 不知道 ⇒ 保留旧值）。
 *   E 组件**渲染**了它：`PlanChecklist.vue` 消费 `plan.items` / `.total` / `.completed`，
 *     并且被真实挂载（import + 用在模板里）—— 只 import 不渲染同样是死代码。
 *
 * 怎么跑
 * ======
 *   node scripts/check-plan-consumption.cjs             做判定
 *   node scripts/check-plan-consumption.cjs --report    只打印盘面读数、不判定
 *
 * 反向注入（证明本门禁不是空跑）
 * ==============================
 * 六处源文件都可以用环境变量指向**副本**，于是能在不改工作区的前提下逐环打穿：
 *   PLAN_API_SRC=<副本.ts>  PLAN_ORCH_SRC=<副本.ts>  PLAN_STORE_SRC=<副本.ts>
 *   PLAN_VIEW_SRC=<副本.vue>  PLAN_PANEL_SRC=<副本.vue>  PLAN_ROUTER_SRC=<副本.py>
 * ★ 每条注入之间**必须从真文件重新生成副本**，否则上一条的注入会把下一条判红
 *   （假红）—— 探针 `.workbuddy/probes/r155g_reverse_injection.py` 是参考实现。
 *
 * ★ 边界（诚实说明）：本门禁只判**活代码**（先剥注释再判）。
 *   "把某一段注释掉留着"它看不到 —— 那属于 code review 的事，不是靠字符串断言
 *   能可靠解决的（本仓已被 docstring 骗过多次）。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function pick(envName, ...rel) {
  const v = process.env[envName]
  return v ? path.resolve(v) : path.join(ROOT, ...rel)
}

const API_SRC = pick('PLAN_API_SRC', 'src', 'api', 'secretary.ts')
const ORCH_SRC = pick('PLAN_ORCH_SRC', 'src', 'composables', 'useChatOrchestrator.ts')
const STORE_SRC = pick('PLAN_STORE_SRC', 'src', 'stores', 'chat.ts')
const VIEW_SRC = pick('PLAN_VIEW_SRC', 'src', 'components', 'ChatPanel', 'PlanChecklist.vue')
const PANEL_SRC = pick('PLAN_PANEL_SRC', 'src', 'components', 'ChatPanel', 'index.vue')
const ROUTER_SRC = pick('PLAN_ROUTER_SRC', '..', 'backend', 'modules', 'secretary', 'router.py')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 解析工具

/** 剥注释 + 保留字符串（与 check-memory-reality.cjs 同源，多剥 `<!-- -->`）。 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    const nx = src[i + 1]
    if (ch === '<' && src.startsWith('<!--', i)) {
      const k = src.indexOf('-->', i + 4)
      i = k < 0 ? n : k + 3
      continue
    }
    if (ch === '/' && nx === '*') {
      const k = src.indexOf('*/', i + 2)
      i = k < 0 ? n : k + 2
      continue
    }
    if (ch === '/' && nx === '/') {
      const k = src.indexOf('\n', i)
      i = k < 0 ? n : k
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      const q = ch
      out += ch
      i++
      while (i < n) {
        if (src[i] === '\\') {
          out += src.slice(i, i + 2)
          i += 2
          continue
        }
        out += src[i]
        if (src[i] === q) {
          i++
          break
        }
        i++
      }
      continue
    }
    out += ch
    i++
  }
  return out
}

/** 标识符是否作为**独立词**出现（避免 `secretaryPlan` 命中 `plan`）。 */
function hasWord(src, word) {
  return new RegExp('(?<![\\w$.])' + word + '(?![\\w$])').test(src)
}

/** 调用形态 `name(`（排除成员访问 `x.name(`）。 */
function isCalled(src, name) {
  return new RegExp('(?<![\\w$.])' + name + '\\s*\\(').test(src)
}

/** `.name(` 或 `?.name(` 的成员访问。 */
function isMemberCalled(src, name) {
  return new RegExp('[.?]\\s*' + name + '\\s*\\(').test(src)
}

/** 抽出 `function NAME(` / `async function NAME(` / `const NAME = (`... 的函数/箭头体。 */
function extractBody(src, name) {
  const patterns = [
    new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\(', 'g'),
    new RegExp('const\\s+' + name + '\\s*=\\s*(?:async\\s*)?\\(', 'g'),
  ]
  for (const re of patterns) {
    const m = re.exec(src)
    if (!m) continue
    // 从匹配处往后找第一个 '{'，做花括号配对（字符串感知）
    let i = m.index + m[0].length
    while (i < src.length && src[i] !== '{') i++
    if (i >= src.length) continue
    let depth = 0
    const start = i
    while (i < src.length) {
      const ch = src[i]
      if (ch === "'" || ch === '"' || ch === '`') {
        const q = ch
        i++
        while (i < src.length) {
          if (src[i] === '\\') {
            i += 2
            continue
          }
          if (src[i] === q) {
            i++
            break
          }
          i++
        }
        continue
      }
      if (ch === '{') depth++
      else if (ch === '}') {
        depth--
        if (depth === 0) return src.slice(start, i + 1)
      }
      i++
    }
  }
  return null
}

// ---------------------------------------------------------------- 读盘

const rawApi = fs.readFileSync(API_SRC, 'utf8')
const rawOrch = fs.readFileSync(ORCH_SRC, 'utf8')
const rawStore = fs.readFileSync(STORE_SRC, 'utf8')
const rawView = fs.readFileSync(VIEW_SRC, 'utf8')
const rawPanel = fs.readFileSync(PANEL_SRC, 'utf8')
const rawRouter = fs.readFileSync(ROUTER_SRC, 'utf8')

const api = stripComments(rawApi)
const orch = stripComments(rawOrch)
const store = stripComments(rawStore)
const view = stripComments(rawView)
const panel = stripComments(rawPanel)

/** 抽出 `header` 之后第一个配对 `{...}` 块（interface / 对象字面量都适用）。 */
function extractBlock(src, header) {
  const i = src.indexOf(header)
  if (i < 0) return null
  const open = src.indexOf('{', i)
  if (open < 0) return null
  let depth = 0
  for (let j = open; j < src.length; j++) {
    const ch = src[j]
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) return src.slice(open, j + 1)
    }
  }
  return null
}

/**
 * 从 `startMarker` 起，切到**最先出现的** `endMarkers` 之一（不含）。
 *
 * ★ 为什么不能复用 `extractBlock`：Python 用缩进而不是花括号分层，
 *   找配对 `{}` 那套在这里没有意义（`class X(BaseModel):` 后面根本没有 `{`）。
 *
 * ★ 为什么要「最先出现耍」而不是「给定顺序」：第 155 轮反向注入发现，A1 曾用
 *   `sliceBetween(src, 'class OrchestratorResponse', '\n@router.post')` 切块，而
 *   `class PlanResponse`（`GET /plan` 的信封，**也含 `plan: dict | None`**）
 *   恰好**夹在两者之间** ⇒ 块里混进了第二个 `plan` 字段，
 *   改名 `OrchestratorResponse.plan` 后 A1 **仍然是绿的**（被 PlanResponse 顶上）。
 *   B1 是同一个病（已修）。—— 这正是「没有反向注入就发现不了」的漏洞。
 */
function sliceUntilFirst(src, startMarker, endMarkers) {
  const i = src.indexOf(startMarker)
  if (i < 0) return null
  let end = -1
  for (const m of endMarkers) {
    const k = src.indexOf(m, i + startMarker.length)
    if (k >= 0 && (end < 0 || k < end)) end = k
  }
  return src.slice(i, end < 0 ? src.length : end)
}

// ---------------------------------------------------------------- 盘面读数
//
// ★ B1 必须**限定在 `SecretaryResponse` 的体内**判，不能在整份 api 文件里搜
//   `plan:` —— 本文件里还有一个 `PlanEnvelope { plan: ... }`（是 `GET /plan`
//   读口的信封）。第 155 轮反向注入时发现：不限定的话，把
//   `SecretaryResponse.plan` 删掉后 B1 **仍然是绿的**（被 PlanEnvelope 那份
//   顶上），也就是"一条写了却打不穿的断言"。
const secyBody = extractBlock(api, 'interface SecretaryResponse')
const apiHasPlanField = !!(secyBody && /plan\s*\??\s*:/.test(secyBody))

// ★ A1 是**同一个病**，只是在后端那一侧：本 router 里有两个含 `plan` 字段的
//   响应模型 —— `OrchestratorResponse`（/chat 下发）与 `PlanResponse`（/plan 读口）。
//   `PlanResponse` 就夹在 `OrchestratorResponse` 与第一条 `@router.post` **之间**，
//   所以结束标记必须取「最先出现的 `\nclass ` 或 `\n@router.`」。
//   只给 `\n@router.post` 会把 PlanResponse 一并切进来 ⇒ A1 永远红不了。
const orchRespBlock = sliceUntilFirst(rawRouter, 'class OrchestratorResponse', [
  '\nclass ',
  '\n@router.',
])
const setPlanBody = extractBody(orch, 'setPlan') || extractBody(store, 'setPlan')
const viewTemplate = view.slice(0, view.indexOf('<script'))

console.log('计划消费链路门禁 —— 盘面读数')
console.log(`  api    ${path.relative(ROOT, API_SRC)}`)
console.log(`  orch   ${path.relative(ROOT, ORCH_SRC)}`)
console.log(`  store  ${path.relative(ROOT, STORE_SRC)}`)
console.log(`  view   ${path.relative(ROOT, VIEW_SRC)}`)
console.log(`  panel  ${path.relative(ROOT, PANEL_SRC)}`)
console.log(`  router ${path.relative(ROOT, ROUTER_SRC)}`)
console.log(`  api 声明 plan 字段            : ${apiHasPlanField}`)
console.log(`  api 导出 fetchCurrentPlan     : ${hasWord(api, 'fetchCurrentPlan')}`)
console.log(`  orch 调 chatStore.setPlan(    : ${isMemberCalled(orch, 'setPlan')}`)
console.log(`  orch 有 loadSecretaryPlan     : ${hasWord(orch, 'loadSecretaryPlan')}`)
console.log(`  store 有 setPlan/getPlan      : ${hasWord(store, 'setPlan')} / ${hasWord(store, 'getPlan')}`)
console.log(`  view 渲染 plan.items          : ${hasWord(view, 'items')}`)
console.log(`  panel 挂了 PlanChecklist      : ${hasWord(panel, 'PlanChecklist')}`)
console.log(`  router 有 /plan 端点          : ${/@router\.get\(\s*['"]\/plan['"]/.test(rawRouter)}`)
console.log(
  `  router 回填 plan=             : ${/plan=result\.get\(\s*['"]plan['"]\s*\)/.test(rawRouter)}`,
)

if (REPORT_ONLY) process.exit(0)

// ---------------------------------------------------------------- 断言

const results = []
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
function check(name, fn) {
  try {
    fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}

// ★ A 后端真的在下发
check('A1 端点响应模型声明了 plan 字段', () => {
  assert(orchRespBlock, '找不到 class OrchestratorResponse —— 若已改名，本组断言会静默失效')
  assert(
    /plan\s*:\s*dict\s*\|\s*None/.test(orchRespBlock) ||
      /plan\s*:\s*Optional\[dict\]/.test(orchRespBlock),
    'OrchestratorResponse 里没有 plan 字段 —— 后端算了半天，没有一个出口把它送出去',
  )
})
check('A2 端点确实回填了 plan（不是永远为 None 的死字段）', () => {
  assert(
    /plan=result\.get\(\s*['"]plan['"]\s*\)/.test(rawRouter),
    '端点没有 plan=result.get("plan") —— 字段声明了却从不赋值，永远是 None',
  )
})
check('A3 有只读读口 GET /plan（让刷新后也能恢复）', () => {
  assert(
    /@router\.get\(\s*['"]\/plan['"]/.test(rawRouter),
    '没有 GET /plan 端点 —— 老板一刷新计划条就空了，只能靠"再随便说一句话"恢复',
  )
})

// ★ B API 类型层声明
check('B1 api 层声明了 plan 字段（SecretaryResponse）', () => {
  assert(secyBody, '找不到 interface SecretaryResponse —— 若已改名，本组断言会静默失效')
  assert(
    apiHasPlanField,
    'SecretaryResponse 没有 plan 字段 —— 拿到响应也不认识它，TS 会当多余的键丢掉',
  )
})
check('B2 api 层有 PlanSummary / PlanTask 类型定义', () => {
  assert(hasWord(api, 'PlanSummary'), '没有 PlanSummary 类型 —— 拿什么约束后端下发的形状？')
  assert(hasWord(api, 'PlanTask'), '没有 PlanTask 类型 —— items 的元素没有形状约束')
})
check('B3 api 层有 fetchCurrentPlan（读口的客户端）', () => {
  assert(hasWord(api, 'fetchCurrentPlan'), '没有 fetchCurrentPlan —— 后端那个读口没人用')
})

// ★ C 编排层消费
check('C1 编排层把响应里的 plan 喂进了 store', () => {
  assert(
    isMemberCalled(orch, 'setPlan'),
    'useChatOrchestrator 里没有 chatStore.setPlan(...) —— 计划拿到手就扔了（这正是第 148 轮的状态）',
  )
  assert(
    /setPlan\(\s*['"]secretary['"]\s*,\s*res\.plan\s*\)/.test(orch),
    '没有把 chatWithSecretary 的 res.plan 喂进 setPlan —— 传了别的值等于没接',
  )
})
check('C2 编排层有刷新恢复入口（监听 activeAgentId 且 immediate）', () => {
  assert(hasWord(orch, 'loadSecretaryPlan'), '没有 loadSecretaryPlan —— 刷新后不会去读口取计划')
  assert(
    /immediate\s*:\s*true/.test(orch),
    '读口没有 immediate 触发 —— 刷新时 activeAgentId 已经是 secretary，只监听变化就永远不触发',
  )
})

// ★ D store 持有（含三态语义）
check('D1 chatStore 有 planByAgent 状态与 get/set/clear', () => {
  assert(hasWord(store, 'planByAgent'), 'chatStore 里没有 planByAgent —— 计划没有落脚点')
  assert(hasWord(store, 'getPlan'), 'chatStore 没有 getPlan')
  assert(hasWord(store, 'setPlan'), 'chatStore 没有 setPlan')
})
check('D2 setPlan 保留三态语义：undefined ⇒ 保留旧值（短路路径不带 plan）', () => {
  assert(setPlanBody, '抽不出 setPlan 的函数体 —— 若已改名，本组断言就静默失效了')
  assert(
    /===\s*undefined/.test(setPlanBody),
    'setPlan 没有区分 undefined —— 店秘书的短路路径（「打开设置」这类根本没走图的请求）'
      + '不带 plan，两态写法会把老板的计划**误清**（后端状态其实好好的）',
  )
})
check('D3 身份切换时清空计划（计划是「你正在做的事」，不是公共状态）', () => {
  const resetBody = extractBody(store, 'resetSessionState')
  assert(resetBody, '抽不出 resetSessionState 的函数体')
  assert(
    hasWord(resetBody, 'planByAgent'),
    'resetSessionState 没有清 planByAgent —— 换账号后新身份会看到上一个身份的计划',
  )
})

// ★ E 组件渲染
//
// ★ E1 为什么查 `.items` 这种**成员访问**形态、而不是一个独立的词：
//   `plan.items` 才是"从后端数据里取字段"的证据；单一个 `items` 词可能来自
//   别处（本组件里就有一个 `plan-items` 的 class 名）。
//   ⚠️ 第 155 轮首跑本门禁时 E1 红过一次，原因是 `hasWord()` 用的是
//   `(?<![\w$.])word(?![\w$])` —— 它**排除成员访问**，而模板里唯一正确的写法
//   恰好是 `plan.total`。断言写得太"像标识符"会把正确实现判红（假 BAD）。
check('E1 PlanChecklist.vue 真的渲染了计划的三个核心字段', () => {
  assert(/\.items\b/.test(viewTemplate), '模板里没有 plan.items —— 计划明细没渲染')
  assert(/\.total\b/.test(viewTemplate), '模板里没有 plan.total —— 总数/进度没渲染')
  assert(/\.completed\b/.test(viewTemplate), '模板里没有 plan.completed —— 进度没渲染')
})
check('E2 completed/total 读后端，不在前端自己数一遍', () => {
  const viewScript = view.slice(view.indexOf('<script'))
  assert(
    !/\bitems\b[\s\S]{0,80}?\.filter\s*\(/.test(viewScript),
    '本组件对 plan.items 做了 filter —— 「完成几项」是后端 plan_summary 算的，'
      + '前端再数一遍就是第二份实现：后端改判据它不会跟着变，'
      + '而界面会安静地显示错的进度',
  )
})
check('E3 未知状态的渲染有兜底（后端加状态时界面不崩）', () => {
  assert(
    /STATUS_VIEW|statusView/i.test(view),
    '没有状态 → 展示的映射表',
  )
  assert(
    /\|\|\s*\{/.test(view) || /fallback/i.test(view),
    '状态映射没有兜底分支 —— 后端新增一个状态会让整条计划渲染崩掉'
      + '（界面上什么都没有、控制台里一个红字）',
  )
})
check('E4 PlanChecklist 被真实挂载（import + 用在模板里）', () => {
  assert(hasWord(panel, 'PlanChecklist'), 'ChatPanel 没有 import PlanChecklist')
  assert(
    /<PlanChecklist[\s\S]*?\/>/.test(panel) || /<PlanChecklist[\s\S]*?<\/PlanChecklist>/.test(panel),
    'ChatPanel 里没有 <PlanChecklist /> —— 只 import 不渲染同样是死代码',
  )
  assert(
    /:plan\s*=\s*/.test(panel),
    '<PlanChecklist /> 没有绑定 :plan —— 组件拿不到数据，渲染出来永远是空',
  )
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n计划消费链路门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `计划消费链路门禁通过（后端下发 ${results.length} 环中的 A 组 ✓ / api 类型 ✓ / 编排消费 ✓ / store 三态 ✓ / 组件渲染 ✓）`,
)
