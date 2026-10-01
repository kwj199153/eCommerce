#!/usr/bin/env node
/**
 * 技能仓库「平铺 / 列表」两个视图的**字段对等**门禁（★ 第 193 轮）
 *
 * 为什么值得单独一个门禁
 * ====================
 * 老板的原话：「技能仓库改为平铺/列表 tab 按钮」。落地形态是
 * `SkillManager.vue` 的「技能仓库」tab 里加一个视图切换按钮组，两种排版：
 *
 *   平铺 = `.sm-grid` + `.sm-card`（卡片网格，原有形态）
 *   列表 = `.sm-list` + `.sm-row`（一行一项，密度优先）
 *
 * 这两者是**同一份数据（`store.items`）的两套渲染** —— 本仓对这类结构的
 * 结论是明确的：**第二套渲染必然分叉**（skill `screenshot-driven-ui-change`
 * 铁律 7 记着两个实例：大屏那套缺「归档到素材库」、文案两处不一致）。
 * 分叉的形态**全部是静默的**：
 *
 *   · 给 Skill 加一个字段（今天叫 `visibility`，明天可能是别的）只改卡片
 *     ⇒ 列表里那个字段**凭空消失**，不报错、不告警、类型系统也不管
 *     （模板里的属性访问不会因「少写一处」而报错）；
 *   · 列表里漏一个操作按钮 ⇒ 用户在列表视图找不到「删除」，以为功能没了；
 *   · 一侧改了 store 的展示函数（`titleOfAgent` → 别的）⇒ 两处显示的名字不一样。
 *
 * ⇒ 本门禁钉的是**两侧的对等性**，不是代码风格：
 *   A1  两个视图分支都在，且**切片互不越界**（越界会让 A2 恒绿，见下）
 *   A2  两侧引用的 `skill.*` 字段集合**逐项相等**（核心：漏一个就红）
 *   A3  两侧消费的 `store.*` 展示函数集合相等（显示口径不许分叉）
 *   A4  两侧的操作按钮**数量**相等
 *   A5  两侧都呈现「启用于」「配套工具」两个信息块
 *   A6  切换控件存在、且默认视图仍是 `grid`（加控件不该顺手改默认形态）
 *   A7  三个写动作（openEdit / openRevisions / removeSkill）两侧都有
 *      —— 这一条捕获的是「列表里按钮是装饰品 / 干脆没有」
 *
 * ★ 第 195 轮又接了一段 **C. 顶部筛选区版式**（见下）：老板要求「筛选过滤
 *   按钮两行改一行，参考资料库中的页面，删除标签相关内容」。版式和字段对等
 *   一样，属于**会被下一次改动悄悄退回**的需求 —— 改回 `flex-direction:
 *   column`、或把一半控件重新包一层行容器，UI 上只是"又变两行了"，
 *   类型检查与构建**一句都不会响**。C 段用同一条 SRC_ROOT 反向注入钩子。
 *
 * ★ 第 196 轮再接一段 **D. 筛选为空时「直接空」**（见下）：老板要求「筛选为空时
 *   直接空就好了，删除那个页面跳转，重置筛选已经提供了」。它钉的其实不是插画，而是
 *   **层级** —— 筛选栏必须活到判空之外，列表容器自己按筛选结果守卫。
 *
 * ★★ 两条踩过的坑（都写进 B 段自检，别再犯）
 *   · **锚点不能是注释**：第一版拿 `<!-- ---------- 列表 ---------- -->` 当分节锚，
 *     而本门禁的扫描要剥掉 HTML 注释 ⇒ 锚点恒找不到（门禁**自己**假红）。
 *     「剥注释」与「用注释当锚」自相矛盾；注释锚只能用在**不剥注释**的扫描里。
 *   · **切片必须互不越界**：若两个切片都覆盖了整段（例如终点锚写错到文件末尾），
 *     两侧字段集合会**恒等** ⇒ A2 永远绿 —— 这是最坏的一种门禁：它对结论点头。
 *     A1 里那条「列表切片不得含 sm-card」就是为此存在的。
 *
 * 怎么跑
 * ======
 *   node scripts/check-skill-view-parity.cjs            做判定
 *   node scripts/check-skill-view-parity.cjs --report   只打印盘面读数
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**：
 *   SKILL_VIEW_SRC_ROOT=<副本 src 目录>
 * ★ 每条注入之间必须**从真文件重新生成副本**，否则上一条的注入会把下一条判红（假红）。
 *   还必须有一条**基线绿**（副本不改 ⇒ 必须全绿）和一条**对照绿**（只动注释 ⇒ 必须仍全绿）。
 *   参考实现：`.workbuddy/probes/i193_view_parity_inject.py`。
 *
 * ★ 与相邻门禁的分工
 *   · `check-chat-domain-split.cjs` —— 判编排域**结构**有没有退化
 *   · 本门禁 —— 判技能仓库**两套渲染**有没有分叉；它不管业务对不对，
 *     也不管列表长得好不好看（那是实测的事，量密度/溢出由 CDP 探针做）
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.SKILL_VIEW_SRC_ROOT
  ? path.resolve(process.env.SKILL_VIEW_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

const TARGET = 'components/SkillStore/SkillManager.vue'

/**
 * 两个分支的边界锚 —— ★★ 全部是**剥注释后仍然存在**的字面量（见文件头第二条坑）。
 *   grid = [GRID_OPEN, LIST_OPEN)
 *   list = [LIST_OPEN, TPL_END)
 * 中间那段分节注释被剥掉后只剩空白，不影响字段抽取。
 */
const GRID_OPEN = '<div v-if="repoView === \'grid\'" class="sm-grid">'
const LIST_OPEN = '<div v-else class="sm-list">'
/** 10 空格缩进的 `</template>`（= `v-else` 兄弟节点的收尾）。
 *  行内 `<template v-if>` 的收尾是 20 空格 ⇒ 不会误命中。 */
const TPL_END = '\n          </template>\n'

/** A5 两个信息块（老板能看见的文案，不是字段名） */
const INFO_BLOCKS = ['启用于', '配套工具']

/** A7 三个写动作（只认函数名，不认调用形态 —— 带参/包箭头函数都算） */
const WRITE_ACTIONS = ['openEdit', 'openRevisions', 'removeSkill']

// ---------------------------------------------------------------- 工具

/** 剥掉 HTML 注释：注释里写 `skill.xxx` 是在解释，不是消费（否则 A2 假红） */
function stripHtmlComments(src) {
  return src.replace(/<!--[\s\S]*?-->/g, '')
}

/**
 * 读目标文件。
 * ★★ 行尾**必须归一化**：本仓可 CRLF / LF 混存，而分支锚点里带着 `\n`
 *   —— 只 decode 不 replace **必失配**，症状是「找不到锚点」，与「字段分叉」
 *   毫无关系，会把人往错方向带。
 *   反向注入（第 193 轮）实测：副本被写成 CRLF 后，连**基线**都报
 *   「找不到列表分支的收尾」—— 门禁自己的脆弱前提被当成代码问题。
 */
/** 只折叠**标签内部**的空白：`<div\n  a="1"\n>` → `<div a="1">`。
 *  ★ 为什么要：自动格式化（F-2 的 `vue/max-attributes-per-line` 等）会把单行开标签
 *    拆成多行，而本文件的分支锚点是**单行字面量** ⇒ 拆行后一律失配。
 *    症状是「找不到锚点」，与「两侧字段分叉」毫无关系，会把人往错方向带。
 *  ★ 只折叠标签内部 ⇒ **标签之外的缩进保留**，靠缩进区分的锚点（如 TPL_END）不受影响。 */
function collapseTagWs(s) {
  return s.replace(/<[^>]*>/g, (t) => t.replace(/\s+/g, ' ').replace(/\s+>$/, '>'))
}

function readTarget() {
  const p = path.join(SRC_ROOT, TARGET)
  if (!fs.existsSync(p)) throw new Error('文件不存在：' + TARGET)
  return collapseTagWs(fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n'))
}

/** 切出两个分支的源码（**先剥注释再切片**；锚点因此不能用注释） */
function splitBranches(src) {
  const code = stripHtmlComments(src)
  const i0 = code.indexOf(GRID_OPEN)
  const i2 = code.indexOf(LIST_OPEN)
  if (i0 < 0) throw new Error(`找不到平铺分支容器（${GRID_OPEN}）`)
  if (i2 < 0 || i2 < i0) throw new Error(`找不到列表分支容器（${LIST_OPEN}）`)
  const i3 = code.indexOf(TPL_END, i2)
  if (i3 < 0) throw new Error(`找不到列表分支的收尾（${JSON.stringify(TPL_END)}）`)
  return { grid: code.slice(i0, i2), list: code.slice(i2, i3) }
}

/** 抽字段名（`skill.foo` ⇒ `foo`），去重排序 */
function fieldsOf(t) {
  return [...new Set((t.match(/skill\.[A-Za-z_$][\w$]*/g) || []).map((s) => s.slice(6)))].sort()
}

/** 抽 store 调用名（`store.foo` ⇒ `foo`），去重排序 */
function storesOf(t) {
  return [...new Set((t.match(/store\.[A-Za-z_$][\w$]*/g) || []).map((s) => s.slice(6)))].sort()
}

function buttonsOf(t) {
  return (t.match(/<a-button/g) || []).length
}

function diff(a, b) {
  const sb = new Set(b)
  const sa = new Set(a)
  return { onlyA: a.filter((x) => !sb.has(x)), onlyB: b.filter((x) => !sa.has(x)) }
}

// ---------------------------------------------------------------- 判定框架

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) }
  catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

// ---------------------------------------------------------------- 盘面读数

const SRC = readTarget()
let branches = null
let splitErr = null
try { branches = splitBranches(SRC) } catch (e) { splitErr = e.message }

console.log('技能仓库「平铺 / 列表」字段对等门禁 —— 盘面读数')
console.log(`  src 根      ${path.relative(ROOT, SRC_ROOT) || '.'}`)
console.log(`  目标        ${TARGET}`)
if (branches) {
  console.log(`  平铺分支    ${branches.grid.length} B，字段 ${fieldsOf(branches.grid).length} 个，按钮 ${buttonsOf(branches.grid)} 个`)
  console.log(`  列表分支    ${branches.list.length} B，字段 ${fieldsOf(branches.list).length} 个，按钮 ${buttonsOf(branches.list)} 个`)
  const d = diff(fieldsOf(branches.grid), fieldsOf(branches.list))
  console.log(`  字段差集    仅平铺 ${JSON.stringify(d.onlyA)}，仅列表 ${JSON.stringify(d.onlyB)}`)
} else {
  console.log(`  分支切分    失败：${splitErr}`)
}
console.log('')

if (REPORT_ONLY) {
  if (branches) {
    console.log('  平铺字段 =', JSON.stringify(fieldsOf(branches.grid)))
    console.log('  列表字段 =', JSON.stringify(fieldsOf(branches.list)))
    console.log('  平铺 store =', JSON.stringify(storesOf(branches.grid)))
    console.log('  列表 store =', JSON.stringify(storesOf(branches.list)))
  }
  process.exit(0)
}

// ==================== A. 对等性 ====================

check('A1 两个视图分支都在，且切片互不越界', () => {
  assert(!splitErr, `分支切分失败：${splitErr}`)
  assert(branches.grid.includes('class="sm-card"'), '平铺分支里没有卡片类名 sm-card')
  assert(branches.list.includes('class="sm-row"'), '列表分支里没有行类名 sm-row')
  // ★★ 切片越界会让 A2 恒绿（两个集合都等于整段的集合）—— 这一条专门钉它
  assert(!branches.list.includes('class="sm-card"'),
    '列表切片里出现了卡片类名 sm-card ⇒ 切片越界（终点锚没落在正确位置）。' +
    '此时两侧字段集合会**恒等**，A2 永远绿 —— 门禁会对着结论点头，比红更坏。')
  assert(!branches.grid.includes('class="sm-row"'), '平铺切片里出现了行类名 sm-row ⇒ 起点/终点锚交叉了')
})

check('A2 两侧引用的 skill 字段集合逐项相等（核心）', () => {
  const gf = fieldsOf(branches.grid)
  const lf = fieldsOf(branches.list)
  assert(gf.length > 0, '平铺分支里一个 skill 字段都没抽到 —— 扫描器空跑，先修门禁自己')
  const d = diff(gf, lf)
  assert(d.onlyA.length === 0 && d.onlyB.length === 0,
    `两侧字段不一致。\n        仅平铺有：${d.onlyA.join(', ') || '无'}\n        仅列表有：${d.onlyB.join(', ') || '无'}\n` +
    `        平铺 = ${JSON.stringify(gf)}\n        列表 = ${JSON.stringify(lf)}\n` +
    '这两个视图是**同一份数据的两套渲染**：给 Skill 加字段时只改一处 ⇒ ' +
    '那个字段在另一个视图里**静默消失**（模板里少写一处属性访问，不报错也不告警）。' +
    '请让两侧逐项对等，或明确说明「为什么这个字段只该出现在某一种形态里」。')
})

check('A3 两侧消费的 store 展示函数集合相等（显示口径不许分叉）', () => {
  const gs = storesOf(branches.grid)
  const ls = storesOf(branches.list)
  const d = diff(gs, ls)
  assert(d.onlyA.length === 0 && d.onlyB.length === 0,
    `两侧 store 调用不一致。仅平铺：${d.onlyA.join(', ') || '无'}；仅列表：${d.onlyB.join(', ') || '无'}。` +
    '展示口径（工具/Agent 的中文名、审批色标）必须同源，否则两个视图显示的名字不一样。')
})

check('A4 两侧的操作按钮数量相等', () => {
  const gb = buttonsOf(branches.grid)
  const lb = buttonsOf(branches.list)
  assert(gb === lb,
    `平铺 ${gb} 个 <a-button>，列表 ${lb} 个。` +
    '少的那一侧会表现为「某个动作在这个视图里没有入口」，用户只会觉得功能没了。')
  assert(gb > 0, '两侧都没有按钮 —— 扫描器大概率抽错了区间')
})

check('A5 两侧都呈现「启用于」「配套工具」两个信息块', () => {
  const missing = []
  for (const label of INFO_BLOCKS) {
    if (!branches.grid.includes(label)) missing.push(`平铺缺「${label}」`)
    if (!branches.list.includes(label)) missing.push(`列表缺「${label}」`)
  }
  assert(missing.length === 0,
    missing.join('；') + '。这两个信息块是用户在列表里判断「这个技能对谁生效、带哪些工具」的依据。')
})

check("A6 切换控件存在，且默认视图仍是 'grid'", () => {
  assert(/v-model:value="repoView"/.test(SRC), '视图切换控件不见了（v-model:value="repoView"）')
  assert(/<a-radio-button\s+value="grid">/.test(SRC) && /<a-radio-button\s+value="list">/.test(SRC),
    '切换控件必须同时有 grid / list 两个取值（少一个 = 另一种形态进不去）')
  const m = SRC.match(/const repoView = ref<[^>]*>\(\s*([^)]*)\)/)
  assert(m, 'repoView 的声明没找到')
  assert(/'grid'/.test(m[1]),
    `repoView 默认值是 ${m[1].trim()}，应为 'grid'。` +
    '加一个切换控件不该顺手改掉用户现在看到的默认形态（老板看到的是平铺）。')
})

check('A7 三个写动作（编辑 / 版本 / 删除）两侧都在', () => {
  const missing = []
  for (const fn of WRITE_ACTIONS) {
    if (!branches.grid.includes(fn)) missing.push(`平铺缺 ${fn}`)
    if (!branches.list.includes(fn)) missing.push(`列表缺 ${fn}`)
  }
  assert(missing.length === 0,
    missing.join('；') + '。' +
    '缺的那一侧，按钮要么不存在、要么是个没有绑定的装饰品 —— 两者都是静默的。')
})

// ==================== B. 自检（证明上面的提取器不是空跑）====================

check('B1 自检（正向）：字段/ store 提取器认得出属性访问', () => {
  const t = '<span>{{ skill.title }}</span><a-tag v-if="skill.isDemo">{{ store.titleOfTool(skill.name) }}</a-tag>'
  assert(fieldsOf(t).join(',') === 'isDemo,name,title', `字段提取器读数 ${JSON.stringify(fieldsOf(t))}`)
  assert(storesOf(t).join(',') === 'titleOfTool', `store 提取器读数 ${JSON.stringify(storesOf(t))}`)
  assert(buttonsOf('<a-button></a-button><a-button></a-button>') === 2, '按钮计数器失配')
})

check('B2 自检（反向）：注释里写的 skill.xxx 不算消费（否则 A2 会假红）', () => {
  const commented = '<!-- 解释用：这里曾经用 skill.legacyField 渲染 --><span>{{ skill.title }}</span>'
  const got = fieldsOf(stripHtmlComments(commented))
  assert(got.join(',') === 'title',
    `剥 HTML 注释没生效 —— 读数 ${JSON.stringify(got)}，注释里的字段名会让 A2 假红`)
})

check('B3 自检（反向）：两套渲染真的分叉时，A2 的差集判据必须抓得到', () => {
  // ★ 样例字段名用 `visibility`（中性名），**不要**用 `tags`：后者已在第 195 轮
  //   随「自定义标签」概念整体退役，留在样例里会让人以为它还是活字段。
  const grid = '<div v-if="repoView === \'grid\'" class="sm-grid">{{ skill.title }}{{ skill.visibility }}</div>'
  const list = '<div v-else class="sm-list">{{ skill.title }}</div>'
  const d = diff(fieldsOf(grid), fieldsOf(list))
  assert(d.onlyA.join(',') === 'visibility',
    `差集判据没认出缺失字段 —— 读数 ${JSON.stringify(d)}。` +
    'A2 的全部价值就在于「少一个就红」，它自己必须先被证明认得出来。')
})

check('B4 自检（正向）：切片器能把两个分支切干净，且不越界', () => {
  const sample = [
    `<div v-if="repoView === 'grid'" class="sm-grid"><div class="sm-card">{{ skill.title }}</div></div>`,
    '<div v-else class="sm-list"><div class="sm-row">{{ skill.title }}{{ skill.tools }}</div></div>',
    '          </template>',
    '          </a-spin>',
  ].join('\n')
  const b = splitBranches(sample)
  assert(b.grid.includes('sm-card') && !b.grid.includes('sm-list'), '平铺切片越界了')
  assert(b.list.includes('sm-row') && !b.list.includes('sm-card'),
    '列表切片越界了 —— 端点锚 TPL_END 没落在 v-else 兄弟节点的收尾上')
  assert(fieldsOf(b.grid).join(',') === 'title', `平铺切片字段读数 ${JSON.stringify(fieldsOf(b.grid))}`)
  assert(fieldsOf(b.list).join(',') === 'title,tools', `列表切片字段读数 ${JSON.stringify(fieldsOf(b.list))}`)
})

check('B5 自检（正向）：CRLF 文件也能被正确切分（行尾归一化生效）', () => {
  const lf = [
    `<div v-if="repoView === 'grid'" class="sm-grid"><div class="sm-card">{{ skill.title }}</div></div>`,
    '<div v-else class="sm-list"><div class="sm-row">{{ skill.title }}</div></div>',
    '          </template>',
    '          </a-spin>',
  ].join('\n')
  // readTarget() 的那一步：\r\n -> \n
  const norm = (s) => s.replace(/\r\n/g, '\n')   // = readTarget() 的那一步
  const a = splitBranches(lf)
  const b = splitBranches(norm(lf.replace(/\n/g, '\r\n')))
  assert(a.grid === b.grid && a.list === b.list,
    'CRLF 归一化没生效 —— 锚点会失配，症状是「找不到列表分支的收尾」（把行尾问题伪装成分叉问题）')
})

// ==================== C. 顶部筛选区版式（★ 第 195 轮）====================
//
// 老板原文：「筛选过滤按钮**两行改一行**，参考资料库中的页面（删标签相关内容）」。
//
// 为什么「两行改一行」也值得一条门禁
// ================================
// 这是**版式需求**，而版式最容易在下一次改动里悄悄退回，且**全程静默**：
//   · 为了塞下第 9 个控件，把 `.sm-filters` 改回 `flex-direction: column`
//     ⇒ 又变竖排多行；
//   · 嫌控件太多，把一半重新包一层 `.sm-filter-row`
//     ⇒ 结构上又是一行（一行行容器，不是一行控件）；
//   · 把「已筛选 N 项」从按钮上摘下来、另起一个 badge 行
//     ⇒ 视觉上又冒出第二行。
// 这三种退化**没有一种会让 vue-tsc 或 vite build 报错** ⇒ 必须用形态判据钉住。
//
// ★★ 判据的取向：只钉**结构**（有没有第二层行容器 / 方向是不是 column），
//   不断言像素宽度。像素属于 CDP 实测的范畴，形态门禁只管「是不是一行」。
//   把两者混在一起，会让这条门禁在换主题/换字体时假红。

/** 筛选区容器与它的收尾（后面紧跟视图切换栏 `.sm-toolbar`） */
const FILTER_OPEN = '<div class="sm-filters">'
const FILTER_END = '<div class="sm-toolbar">'

/** 老板要压掉的那个「第二行」的旧结构类名 —— 不许回来 */
const DEAD_ROW_CLASS = 'sm-filter-row'
/** 旧的行内 badge —— 「已筛选 N 项」已改挂在「重置筛选」按钮上 */
const DEAD_BADGE_CLASS = 'sm-filter-badge'
/** 随「自定义标签」概念一起退役的卡片 chip 类名 */
const DEAD_TAG_CHIP = 'sm-chip-tag'

/** 单行筛选区里应有的控件（按 v-model / 动作签名识别，不依赖控件在 CSS 里的宽度） */
const FILTER_CONTROLS = [
  ['搜索框', '<a-input-search'],
  ['Agent 下拉', 'v-model:value="store.filterAgent"'],
  ['类型下拉', 'v-model:value="store.filterKind"'],
  ['状态下拉', 'v-model:value="store.filterStatus"'],
  ['排序下拉', 'v-model:value="store.sortBy"'],
  ['仅看收藏', 'v-model:checked="store.onlyFavorites"'],
  ['按 Agent 分组', 'v-model:checked="store.groupByAgent"'],
  ['重置按钮', 'store.resetFilters()'],
]

/** 切出筛选区（起点锚 -> 视图切换栏）；失败**抛错**而不是返回空串（空串会让 C2 恒绿） */
function splitFilterRow(src) {
  const i = src.indexOf(FILTER_OPEN)
  if (i < 0) throw new Error(`找不到筛选区容器（${FILTER_OPEN}）`)
  const j = src.indexOf(FILTER_END, i)
  if (j < 0 || j <= i) throw new Error(`找不到筛选区的收尾（${FILTER_END}），或两个锚点交叉了`)
  return src.slice(i, j)
}

/** 切出 `.sm-filters` 的主 CSS 规则体（到第一个 `}` 为止） */
function filterRowCss(src) {
  const i = src.indexOf('.sm-filters {')
  if (i < 0) throw new Error('找不到 .sm-filters 的 CSS 规则')
  const j = src.indexOf('}', i)
  if (j < 0) throw new Error('.sm-filters 的 CSS 规则没有收尾 `}`')
  return src.slice(i, j)
}

/** C1 的纯判据：这段切片是不是「只有一层行容器」 */
const isSingleRowStructure = (slice) => !slice.includes(DEAD_ROW_CLASS)
/** C3 的纯判据：这段 CSS 是不是「横向单行」 */
const isRowDirection = (css) => !/flex-direction:\s*column/.test(css)

let filterRow = null
let filterRowErr = null
try { filterRow = splitFilterRow(SRC) } catch (e) { filterRowErr = e.message }

check('C1 筛选区**只有一层**容器（旧的两行结构不许回来）', () => {
  assert(!filterRowErr, `筛选区切分失败：${filterRowErr}`)
  assert(isSingleRowStructure(filterRow),
    `筛选区里出现了 ${DEAD_ROW_CLASS}（嵌套的行包裹）⇒ 结构上又是一行行容器，不是一行控件。` +
    '第 195 轮把它的两层包裹整个拆掉、控件直接排在 .sm-filters 里；加回来就是退回旧形态。')
  assert(!SRC.includes(DEAD_ROW_CLASS), `全文件里仍存在 ${DEAD_ROW_CLASS} —— 旧结构没清干净`)
})

check('C2 筛选区里的控件一个不少（压成一行时最容易掉控件）', () => {
  assert(!filterRowErr, `筛选区切分失败：${filterRowErr}`)
  const missing = FILTER_CONTROLS.filter(([, sig]) => !filterRow.includes(sig)).map(([n]) => n)
  assert(missing.length === 0,
    `筛选区里找不到：${missing.join('、')}。` +
    '把两行压成一行时，最典型的副作用就是**顺手丢掉一个控件** —— ' +
    '而 UI 上它只是"不见了"：不报错、不告警、类型系统也不管。')
})

check('C3 筛选区 CSS 是**单行** flex（不许 flex-direction: column）', () => {
  const css = filterRowCss(SRC)
  assert(/display:\s*flex/.test(css), '.sm-filters 不是 flex 容器 —— 控件的排列不再受控')
  assert(isRowDirection(css),
    '.sm-filters 被改成了 flex-direction: column ⇒ 又变回**竖排多行**。' +
    '老板的要求是「两行改一行」，横向排列是硬要求（默认 row，不需要显式写）。')
})

check('C4 保留 flex-wrap: wrap 作为窄屏兜底（宁可换行也不要横向溢出）', () => {
  const css = filterRowCss(SRC)
  assert(/flex-wrap:\s*wrap/.test(css),
    '.sm-filters 少了 flex-wrap: wrap。' +
    '一行是**主态**（宽屏下全部控件在同一行）；窄屏时宁可换行，也不能横向溢出把内容推出屏幕。' +
    '去掉 wrap 的后果是窄屏上控件被压扁/溢出，而宽屏上看起来一切正常。')
})

check('C5 第二行与标签相关的旧类名都已清掉', () => {
  const dead = [DEAD_BADGE_CLASS, DEAD_TAG_CHIP].filter((c) => SRC.includes(c))
  assert(dead.length === 0,
    `仍存在已退役的类名：${dead.join('、')}。` +
    '前者是老板要压掉的第二行（计数已挂到「重置筛选」按钮上）；' +
    '后者随「自定义标签」概念一并退役。')
  assert(!/<a-badge/.test(filterRow),
    '筛选区里出现了独立的 <a-badge> —— 「已筛选 N 项」应是重置按钮的一部分，不是第二个视觉行')
})

// ---- B6 自检（反向）：把 C 段的判据喂回「两行」形态，必须转红 ----

check('B6 自检（反向）：两行形态的样例必须被 C1/C3 的判据判红', () => {
  const twoRow = [
    '<div class="sm-filters">',
    '  <div class="sm-filter-row"><a-input-search /></div>',
    '  <div class="sm-filter-row"><a-select /></div>',
    '</div>',
    '<div class="sm-toolbar"><a-radio-group /></div>',
  ].join('\n')
  const slice = splitFilterRow(twoRow)
  assert(!isSingleRowStructure(slice),
    'C1 的判据对"嵌套行包裹"无感 —— 空跑，两行回来了也不会红')

  const colCss = '.sm-filters {\n  display: flex;\n  flex-direction: column;\n}'
  assert(!isRowDirection(colCss), 'C3 的判据认不出竖排 —— 空跑，column 回来了也不会红')
  const rowCss = '.sm-filters {\n  display: flex;\n  flex-wrap: wrap;\n}'
  assert(isRowDirection(rowCss), 'C3 的判据对"已经是一行"的样例误报 ⇒ 会假红')
})

// ==================== D. 筛选为空时「直接空」（★ 第 196 轮）====================
//
// 老板原文：「当筛选为空时候，直接空就好了，你好像做了另外一个页面跳转
// （删除这个跳转，直接空，然后已经提供了重置筛选的功能了）」。
//
// 为什么这不是「删个插画」那么小
// ============================
// 老板看到"像跳转到另一个页面"，根因是**层级**而不是插画：
// 旧形态把**整条筛选栏（连同顶部「重置筛选」）**关在 `v-else` 分支里 ——
// 只有"筛出了东西"才渲染 ⇒ 一筛空，筛选栏整条消失，页面上只剩一个居中的
// 空状态块。于是空状态里那个「清空筛选」按钮成了**唯一**的逃生口：
// 同一个 `resetFilters` 被迫有了两套入口。
// ⇒ 「删除这个跳转」= ① 筛选栏提到判空之外（常驻）
//                       ② 列表区自己按筛选结果守卫（筛空即空）
//
// ★★ 这两条**都不会**让 vue-tsc / vite build 响一声：把筛选栏挪回 v-else、
//   或给列表容器去掉守卫，构建全绿、页面照常，只是"筛空以后又变成另一页了"。
//   ⇒ 必须是形态判据。
//
// ★ 判据取向：只判「筛选栏与列表各自挂在哪个条件上」，不判插画长什么样 ——
//   观感/像素归 CDP 实测，混在一起会让这条门禁在换主题时假红。

/** 剥掉注释后的源码 —— D 段判据专用。
 *  ★★ 必须剥：本段的注释里**引用**了旧文案与旧按钮名（为了说清改了什么），
 *     在原始源码上判「这两个词还在不在」等于把**解释**当成**实现**（假红）。 */
const SRC_NC = stripHtmlComments(SRC)

/** 切出「技能仓库」tab（筛选区与重置入口都只在这一段里数） */
function repoTab(src) {
  const i = src.indexOf('key="repo"')
  const j = src.indexOf('key="wiring"')
  if (i < 0 || j < 0 || j <= i) throw new Error('找不到「技能仓库」/「Agent 装配」两个 tab 的边界')
  return src.slice(i, j)
}

/** 取 idx 所在的**那个标签**（上一个 `<` 到下一个 `>`）——
 *  ★ 不能用「往前 N 个字符」，那会把前一个兄弟元素的 v-if 也算进来（假绿）。 */
function tagAround(src, idx) {
  const s = src.lastIndexOf('<', idx)
  const e = src.indexOf('>', idx)
  if (s < 0 || e < 0) return ''
  return src.slice(s, e + 1)
}

/** D2 的纯判据：筛选栏出现在**第一个** filteredItems 判定之前 ⇒ 它不受筛选结果影响 */
function filtersOutliveEmpty(src) {
  const i = src.indexOf('<div class="sm-filters">')
  const j = src.indexOf('store.filteredItems.length')
  if (i < 0 || j < 0) return false
  return i < j
}

/** D3 的纯判据：列表容器自己带 filteredItems 守卫 */
function listGuardedByFilter(src) {
  const i = src.indexOf('class="sm-groups"')
  if (i < 0) return false
  return /v-if="[^"]*filteredItems\.length/.test(tagAround(src, i))
}

/** 老板明确说"已经提供了"的那个功能 */
const RESET_LABEL = '重置筛选'
/** 旧形态留下的东西 —— 一个都不许回来 */
const DEAD_EMPTY_TEXT = '没有符合当前筛选条件'
const DEAD_EMPTY_BUTTON = '清空筛选'

let repo = null
let repoErr = null
try { repo = repoTab(SRC_NC) } catch (e) { repoErr = e.message }

check('D1 「筛选后为空」不再有自己的空状态块（也没有第二套重置入口）', () => {
  assert(!repoErr, `仓库 tab 切分失败：${repoErr}`)
  assert(!repo.includes(DEAD_EMPTY_TEXT),
    `仓库 tab 里仍有「${DEAD_EMPTY_TEXT}」这个空状态。` +
    '第 196 轮老板要求筛空时**直接空** —— 留着它就会"像跳转到了另一个页面"。' +
    '★ 想加回来请先问：它比顶部那个重置按钮多提供了什么？')
  assert(!repo.includes(DEAD_EMPTY_BUTTON),
    `仓库 tab 里仍有「${DEAD_EMPTY_BUTTON}」按钮 —— 它是「重置筛选」的**第二套入口**。` +
    '同一个动作两个按钮，迟早文案/可见性口径分叉（本仓判据「同一判定两份实现' +
    '⇒ 至少一份永远测不到」的同族形态）。')
})

check('D2 ★ 筛选栏（含「重置筛选」）活在判空之外 ⇒ 筛空时仍然在（这条才是"删跳转"）', () => {
  assert(!repoErr, `仓库 tab 切分失败：${repoErr}`)
  assert(filtersOutliveEmpty(repo),
    '筛选栏没有活在 `filteredItems` 判空之外 —— 它又被关回 v-else 里了。' +
    '此时筛成空会让**整条筛选栏连同「重置筛选」一起消失**：' +
    '用户看到的是一整页只剩空状态，那正是老板说的"像跳转到另一个页面"，' +
    '而空状态里就必须再放一个重置按钮（第二套入口）来救场。')
  assert(repo.includes(RESET_LABEL),
    `筛选栏里找不到「${RESET_LABEL}」—— 老板说的"已经提供了"的那个功能不见了`)
})

check('D3 ★ 列表容器自己按筛选结果守卫 ⇒ 筛空时列表区真的空', () => {
  assert(listGuardedByFilter(repo),
    '.sm-groups 上没有 `v-if="store.filteredItems.length"` 守卫。' +
    '筛成空时它仍会渲染一个空壳，或者被迫退回"另起一个空状态"的老路。' +
    '★ 守卫要挂在**列表容器**上，不能把筛选栏一起包进去（那就变成 D2 的旧形态）。')
})

check('D4 重置入口全页只有**一个**（把「重置筛选」当唯一出口）', () => {
  assert(!repoErr, `仓库 tab 切分失败：${repoErr}`)
  const n = (repo.match(/store\.resetFilters\(\)/g) || []).length
  assert(n === 1,
    `仓库 tab 里有 ${n} 处 store.resetFilters()，期望恰好 1 处。` +
    '多出来的那处一定是又给某个空状态配了"清空筛选"按钮 —— ' +
    '同一个动作两套入口，正是第 196 轮要消掉的东西。')
})

check('D5 「库里真没技能」的空状态**保留**（两种空语义不可合并）', () => {
  assert(repo.includes('!store.items.length'),
    '找不到「库里一条技能都没有」的空状态判断。' +
    '★ 别把它和"筛选为空"一起删掉：库里真没技能时**没有筛选栏可言**，' +
    '用户需要的是"去新建"，而不是面对一页空白 —— 那会让人以为页面坏了。')
})

check('D6 自检（反向）：旧形态样例必须被 D2/D3 判红（否则两条判据都在空跑）', () => {
  // ① 旧形态：筛选栏被关在「筛出东西才有」的分支里
  const nested = [
    '<a-empty v-if="!store.items.length" />',
    '<a-empty v-else-if="!store.filteredItems.length">清空筛选</a-empty>',
    '<template v-else>',
    '  <div class="sm-filters">重置筛选</div>',
    '  <div class="sm-groups"></div>',
    '</template>',
  ].join('\n')
  assert(!filtersOutliveEmpty(nested),
    'D2 的判据对"筛选栏被关在 v-else 里"无感 —— 空跑，旧形态回来了也不会红')

  // ② 筛选栏常驻了，但列表容器忘了守卫
  const unguarded = [
    '<div class="sm-filters">重置筛选</div>',
    '<div class="sm-groups"></div>',
  ].join('\n')
  assert(!listGuardedByFilter(unguarded),
    'D3 的判据对"列表容器没有守卫"无感 —— 空跑')

  // ③ 对照（正向）：修好之后的形态必须**不**被判红（否则门禁自己假红）
  const fixed = [
    '<div class="sm-filters">重置筛选</div>',
    '<div v-if="store.filteredItems.length" class="sm-groups"></div>',
  ].join('\n')
  assert(filtersOutliveEmpty(fixed), 'D2 对已经修好的样例误报 ⇒ 门禁假红的作用与空跑一样糟')
  assert(listGuardedByFilter(fixed), 'D3 对已经修好的样例误报 ⇒ 门禁假红')
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
console.log('技能仓库形态成立（平铺 ≡ 列表：字段 · 展示口径 · 动作 · 信息块 ✓' + ' ／ 顶部筛选区：单层容器 · 横向单行 · 控件齐备 ✓' + ' ／ 筛选为空：筛选栏常驻 · 列表区直接空 · 唯一重置入口 ✓）')
