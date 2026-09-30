#!/usr/bin/env node
/**
 * 「配套工具候选集」唯一实现门禁（第 255 轮）
 *
 * ============================================================================
 * ★ 为什么需要这道门禁（老板原话）
 * ============================================================================
 *   「工具仓库页「skill 配装」按 Agent 收窄候选集（对齐技能抽屉）」
 *
 * 背景是两道真实存在的分叉（都在界面上看不出来）：
 *
 *   ① **同一个字段两个编辑入口、口径不一致**
 *      字段 `skills.tools` 有两个写入口 —— 技能仓库的**编辑抽屉**、
 *      工具仓库的「skill 配装」tab。前者按已勾选的 Agent **收窄**候选，
 *      后者**平铺全部 8 个 Agent 的工具**。
 *      ⇒ 后者随时能造出「技能引导了该 Agent 手上没有的工具」这种绑定：
 *        运行期调不到（模型被引导去调一个它手上不存在的名字），
 *        而**保存成功、界面无异常、零报错零测试红**。
 *
 *   ② **收窄逻辑被复制成两份实现**
 *      同一段 `if (!selected.has(g.agent)) continue` 写在组件里，
 *      将来改一处不改另一处 ⇒ 又回到 ①。
 *      （本仓已登记的同族判据：同一判定两份实现 ⇒ 至少一份永远测不到。）
 *
 * ★ 本门禁钉的是**形态**，不是文案：
 *     · 收窄判定在全 `src/` 里**恰好一处**，且在 store；
 *     · 两个入口**都消费它**（不留各自的 `v-for="g in store.toolGroups"`）；
 *     · 两个入口**都必须传第二个实参**（已绑定清单）——
 *       只传 Agent 集合会让「已绑定但不在候选里」的项从下拉里消失，
 *       用户一保存就**静默删掉绑定**（判据「拿不到权威清单 ≠ 清单为空」）。
 *
 * ★ 反向注入验证过（见文件末尾 docstring）：把收窄判定复制回组件、
 *   或把任一入口的第二实参删掉、或把 store 的 orphan 兜底组删掉，
 *   本门禁都会转红。
 */

const fs = require('fs')
const path = require('path')

const ROOT = process.env.SKILL_TOOL_OPTIONS_SRC_ROOT || path.join(__dirname, '..', 'src')

const STORE = 'stores/skills.ts'
const DRAWER = 'components/SkillStore/SkillManager.vue'
const REPO = 'components/ToolStore/ToolManager.vue'

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

/** ★ 行尾必须按**锚点**归一化：本仓同一文件里 CRLF / LF 混存 */
function read(rel) {
  const p = path.join(ROOT, rel)
  if (!fs.existsSync(p)) return null
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/** 递归收集 src 下的 .ts / .vue（收窄判定的分布要按**全目录**数，不能只数两个组件） */
function walk(dir, acc) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, acc)
    else if (/\.(ts|vue)$/.test(e.name)) acc.push(p)
  }
  return acc
}

/**
 * 剥离注释后再做**否定型**断言。
 *
 * ★ 本仓已登记的同族缺陷：「判据被自己的注释绊倒」—— 改动点的说明注释里
 *   为了解释"这里不再这么写"往往**原样引用**旧写法，于是 `!regex.test(src)`
 *   这类**否定**断言会被注释命中而判失败（或反过来，正向断言被注释喂饱而假绿）。
 *   剥注释是这道门禁能不能长期活着的关键，不是洁癖。
 */
function stripComments(src, ext) {
  let s = src
  if (ext === '.vue') s = s.replace(/<!--[\s\S]*?-->/g, '')
  s = s.replace(/\/\*[\s\S]*?\*\//g, '')
  s = s.replace(/^[ \t]*\/\/.*$/gm, '')
  return s
}

const storeSrc = read(STORE)
const drawerSrc = read(DRAWER)
const repoSrc = read(REPO)

// ---------------------------------------------------------------- 前置
check(storeSrc !== null, 'A0 store 文件存在', STORE)
check(drawerSrc !== null, 'A0 技能仓库页存在', DRAWER)
check(repoSrc !== null, 'A0 工具仓库页存在', REPO)

if (storeSrc === null || drawerSrc === null || repoSrc === null) {
  report()
  process.exit(1)
}

// ---------------------------------------------------------------- A 唯一实现落在 store
check(
  /function\s+toolOptionsFor\s*\(/.test(storeSrc),
  'A1 store 定义 toolOptionsFor',
  `${STORE} 里没有 function toolOptionsFor ⇒ 收窄逻辑还在组件里`
)
check(
  /^\s{2,}toolOptionsFor,\s*$/m.test(storeSrc),
  'A2 store 导出 toolOptionsFor',
  '定义在但没写进 setup 的 return ⇒ 组件拿不到（未导出的符号在运行期是 undefined）'
)

// ★ 收窄判定在全 src 里**恰好一处**，且必须在 store：
//   数 > 1 = 有第二份实现（将来必然漂移）；数 == 0 = 收窄被整体删掉了。
const NARROW_RE = /selected\.has\(\s*g\.agent\s*\)/
const allFiles = walk(ROOT, [])
const narrowHits = []
for (const f of allFiles) {
  const t = fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n')
  const n = (t.match(NARROW_RE) || []).length
  if (n) narrowHits.push({ f: path.relative(ROOT, f).replace(/\\/g, '/'), n })
}
const narrowTotal = narrowHits.reduce((s, h) => s + h.n, 0)
check(
  narrowTotal === 1,
  'A3 收窄判定全仓恰好 1 处',
  `命中 ${narrowTotal} 处：${JSON.stringify(narrowHits)} —— ` +
    `>1 = 出现第二份实现（两份必然漂移）；0 = 收窄被删（平铺全部 Agent）`
)
check(
  narrowHits.length === 1 && narrowHits[0].f === STORE,
  'A4 收窄判定住在 store',
  `唯一命中在 ${narrowHits[0] && narrowHits[0].f}，应在 ${STORE}`
)

// ★ 组标题格式（`Agent 中文名 · agent_name`）与兜底组文案也只允许一处实现
const TITLE_RE = /\$\{\s*g\.agentTitle\s*\}\s*·\s*\$\{\s*g\.agent\s*\}/
const ORPHAN_LABEL_RE = /已绑定（不属于上面勾选的 Agent/
function countAcrossSrc(re) {
  let n = 0
  const where = []
  for (const f of allFiles) {
    const t = fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n')
    const c = (t.match(re) || []).length
    if (c) {
      n += c
      where.push(path.relative(ROOT, f).replace(/\\/g, '/'))
    }
  }
  return { n, where }
}
const titleHits = countAcrossSrc(TITLE_RE)
check(
  titleHits.n === 1 && titleHits.where[0] === STORE,
  'A5 组标题格式唯一实现',
  `命中 ${titleHits.n} 处 ${JSON.stringify(titleHits.where)}（应在 ${STORE}）—— ` +
    `标题格式复制出去 ⇒ 两个入口显示不一致`
)
const orphanHits = countAcrossSrc(ORPHAN_LABEL_RE)
check(
  orphanHits.n === 1 && orphanHits.where[0] === STORE,
  'A6 「已绑定」兜底组唯一实现',
  `命中 ${orphanHits.n} 处 ${JSON.stringify(orphanHits.where)}（应在 ${STORE}）`
)
check(
  /orphan:\s*true/.test(storeSrc),
  'A7 store 有 orphan 分组标记',
  '缺 orphan 标记 ⇒ 消费方没法把「已绑定但不在候选里」与「属于该 Agent」区分开'
)

// ---------------------------------------------------------------- B 两个入口都消费它
function consumer(src, rel, name, marker) {
  const bare = stripComments(src, rel.endsWith('.vue') ? '.vue' : '.ts')
  check(
    new RegExp(`toolOptionsFor\\(`).test(bare),
    `B ${name} 消费 toolOptionsFor`,
    `${rel} 里没有调用 toolOptionsFor ⇒ 它仍在用自己的候选集口径`
  )
  check(
    !/v-for="g in store\.toolGroups"/.test(bare) &&
      !/for\s*\(const g of store\.toolGroups\)/.test(bare),
    `B ${name} 不再自行平铺 store.toolGroups`,
    `${rel} 里出现对 store.toolGroups 的迭代 ⇒ 第二份候选集口径（平铺 = 不收窄）`
  )
  check(
    new RegExp(marker).test(bare),
    `B ${name} 接线到位`,
    `${rel} 缺少接线标记 ${marker}`
  )
}
consumer(drawerSrc, DRAWER, '技能抽屉', 'store\\.toolOptionsFor\\(form\\.enabledAgents,\\s*form\\.tools\\)')
consumer(repoSrc, REPO, 'skill 配装', 'store\\.toolOptionsFor\\(s\\.enabledAgents')

// ---------------------------------------------------------------- C 两个入口都传第二个实参
// ★ 只传 Agent 集合 ⇒ 已绑定但不在候选里的项从下拉里消失 ⇒ 一保存静默删掉绑定。
const CALL_RE = /toolOptionsFor\(([^)]*)\)/g
const calls = []
let m
while ((m = CALL_RE.exec(drawerSrc + '\n' + repoSrc)) !== null) {
  calls.push(m[1])
}
check(
  calls.length >= 2,
  'C1 找到两个入口的调用点',
  `只解析出 ${calls.length} 个调用点 —— 门禁的分母错了，后面两条断言会变空跑`
)
const badArity = calls.filter((a) => a.split(',').length < 2)
check(
  badArity.length === 0,
  'C2 两个入口都传了「已绑定清单」',
  `这些调用点少一个实参：${JSON.stringify(badArity)} —— ` +
    `缺第二个实参 ⇒ 已绑定项不在候选里 ⇒ 保存时被静默删除`
)

// ---------------------------------------------------------------- D 「skill 配装」的选择器用 options
check(
  /:options="toolOptionsOf\(s\)"/.test(repoSrc),
  'D1 skill 配装选择器走 options',
  'ToolManager.vue 的 skill 配装 <a-select> 没用 :options="toolOptionsOf(s)"'
)
check(
  /toolPlaceholderOf\(s\)/.test(repoSrc),
  'D2 空候选时说明原因',
  '缺 toolPlaceholderOf ⇒ 「未对任何 Agent 生效」与「没配工具」显示同一句话，用户看不出该去哪改'
)

// ---------------------------------------------------------------- E 正向对照
// ★ ToolManager 的「Agent 配装」tab 另有一处 `store.toolGroups.find(...)`，
//   用途是**列出某 Agent 手上的工具**（数据源 = 代码声明），与候选集无关。
//   这条断言防的是将来"一刀切删干净"把那个用途也带走。
check(
  /store\.toolGroups\.find\(/.test(repoSrc),
  'E0 正向对照：Agent 配装 tab 仍能列出 Agent 手上工具',
  'ToolManager.vue 缺 store.toolGroups.find ⇒ 「Agent 配装」tab 的数据源被误删（本页要显示的正是代码声明的那份）'
)
check(
  /function\s+toolOptionsOf\(\s*s:\s*Skill\s*\)/.test(repoSrc),
  'E1 正向对照：消费点入参仍是技能实体',
  'ToolManager.vue 的 toolOptionsOf 入参形态变了 ⇒ 传入的 Agent 集合/已绑定清单来源不明（本页要传的正是这条技能的 s.enabledAgents / s.tools）'
)

report()

function report() {
  const bad = results.filter((r) => !r.ok)
  for (const r of results) {
    if (r.ok) console.log(`  ok   ${r.label}`)
    else console.log(`  FAIL ${r.label}\n       → ${r.detail}`)
  }
  console.log('')
  console.log(
    `check-skill-tool-options-parity: ${results.length - bad.length}/${results.length} 通过`
  )
  if (bad.length) {
    console.log(`EXIT=1（${bad.length} 条失败）`)
    process.exit(1)
  }
  console.log('EXIT=0')
  process.exit(0)
}

/* ============================================================================
 * 反向注入验证记录（每次改本文件后必须重做）
 * ----------------------------------------------------------------------------
 * 注入 1：把收窄判定复制回技能抽屉（`if (!selectedSet.has(g.agent)) continue`）
 *   ⇒ A3 命中 2 处 → 红（「出现第二份实现」）
 * 注入 2：把「skill 配装」的 `:options="toolOptionsOf(s)"` 换回
 *         `<a-select-opt-group v-for="g in store.toolGroups">` 平铺
 *   ⇒ B「不再自行平铺」+ D1 同时红
 * 注入 3：把抽屉的调用改成只传一个实参 `toolOptionsFor(form.enabledAgents)`
 *   ⇒ C2 红（「少一个实参 ⇒ 保存时静默删除绑定」）
 * 注入 4：删掉 store 里的 orphan 分组（只留候选组）
 *   ⇒ A6 / A7 红
 * 注入 5：从 store 的 return 里删掉 `toolOptionsFor,`
 *   ⇒ A2 红（未导出）
 * ★ 判据：每条注入都必须让**至少一条**断言转红，且红的条数可解释；
 *   若某条注入全绿 ⇒ 本门禁是空的，不是代码对了。
 * ========================================================================== */
