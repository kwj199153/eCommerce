#!/usr/bin/env node
/**
 * 工具仓库页面门禁（第 209 轮）
 *
 * ============================================================================
 * ★ 为什么需要这道门禁（老板原话）
 * ============================================================================
 *   「我需要的工具仓库是与 skill 仓库平级的。界面可以参考 skill 仓库页面
 *    （仓库页面的技能仓库改为技能管理），tab 页面有工具管理（也有过滤器这些，
 *    平铺/列表 tab）、skill 配装、Agent 配装。」
 *
 * ⇒ 这条需求里有**三类**东西会被静默做丢，而且丢了都不会报错：
 *
 *   ① 「平级」是**三处**接线，缺任一即「页面文件躺着但用户进不去」：
 *        侧边栏菜单项 / 渲染分支 / `currentView` 联合类型。
 *      历史上踩过同族缺陷（「后端有端点」≠「前端在用」；「接线了但没渲染」——
 *      零报错零测试红，唯一症状是用户找不到入口）。
 *
 *   ② 「工具管理」要**也有过滤器这些，平铺/列表 tab** —— 这是形态要求，
 *      不是文案要求。只写个标题就交差是最常见的走样。
 *
 *   ③ **不能有第二个真源**。工具由代码定义：
 *        · 归属 Agent 由 `TOOL_CATALOG` 声明（后端判据 A 与真实装配点集合相等）；
 *        · 「这个名字合不合法」的唯一读口是后端 `/tools/usage` 的 `unknownTools`。
 *      前端若自己 `Set(tools.map(...))` 再算一遍差集，就是第二份实现 ——
 *      两份必然有一份先漂移，而症状只是"某个标记时有时无"。
 *      同理：页面上**不许出现任何"新建工具"类写动作**（结构上不存在这件事）。
 *
 *   ④ 「skill 配装」是**唯一**可写的工具绑定面，且它的语义必须如实标注
 *      （提示词引导 ≠ 权限）—— 标注丢了，用户会以为"勾了就等于授权"。
 *
 * ★ 这道门禁只判**形态**（结构 / 接线 / 有无写口），不判文案好坏。
 *   文案类断言是"墓志铭"，改文案就会红；形态断言改文案不会红。
 */

const fs = require('fs')
const path = require('path')

const ROOT = process.env.TOOL_REPO_SRC_ROOT || path.join(__dirname, '..', 'src')
const page = read('components/ToolStore/ToolManager.vue')
const sidebar = read('components/Sidebar/KnowledgeBase.vue')
const workspace = read('views/Workspace.vue')
const skillPage = read('components/SkillStore/SkillManager.vue')

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}
function read(rel) {
  const p = path.join(ROOT, rel)
  if (!fs.existsSync(p)) return null
  // ★ 行尾必须归一化：本仓同一文件可 CRLF / LF 混存，
  //   不归一化会让锚点静默失配（症状是"找不到分支收尾"，方向错得很远）。
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

// ---------------------------------------------------------------- 前置
check(page !== null, 'A0 工具仓库页面存在', 'components/ToolStore/ToolManager.vue')

if (page === null) {
  report()
  process.exit(1)
}

// ---------------------------------------------------------------- A 平级接线（三处）
check(
  /<a-menu-item key="tools">/.test(sidebar || ''),
  'A1 侧边栏有「工具仓库」菜单项',
  'Sidebar/KnowledgeBase.vue 里缺 key="tools" 的 a-menu-item ⇒ 用户没有入口'
)
check(
  /<ToolManager\b/.test(workspace || ''),
  'A2 Workspace 有 ToolManager 渲染分支',
  'Workspace.vue 里缺 <ToolManager .../> ⇒ 菜单点得到但内容区空白'
)
check(
  /currentView\s*=\s*ref<[^>]*'tools'[^>]*>/.test(workspace || ''),
  'A3 currentView 联合类型含 tools',
  "缺 'tools' ⇒ vue-tsc 会红，或菜单 key 被静默 cast 成不存在的视图"
)
check(
  /key as[^\n]*'tools'/.test(workspace || ''),
  'A4 导航 cast 含 tools',
  'handleKnowledgeNavigate 的 cast 缺 tools ⇒ 菜单点击切不过去'
)

// ---------------------------------------------------------------- B 三个 tab
const TABS = ['工具管理', 'skill 配装', 'Agent 配装']
for (const t of TABS) {
  check(
    new RegExp(`tab="${t}"`).test(page),
    `B tab 存在：${t}`,
    `ToolManager.vue 缺少 tab="${t}"`
  )
}

// ---------------------------------------------------------------- C 工具管理 tab 的形态
check(
  /store\.toolSearchQuery/.test(page),
  'C1 工具管理有搜索框（绑 store）',
  '筛选状态必须住 store —— 放组件本地 ref 会在切 tab 后清空，用户以为"筛选不管用"'
)
check(
  /store\.filterToolAgent/.test(page) && /store\.filterToolEffect/.test(page),
  'C2 工具管理有 Agent / 副作用两个下拉',
  '缺其一 ⇒ 筛选栏不完整'
)
check(
  /store\.resetToolFilters/.test(page),
  'C3 有「重置筛选」入口',
  '筛空时用户需要有逃生口'
)
check(
  /view === 'grid'/.test(page) && /view === 'list'/.test(page),
  'C4 平铺 / 列表双视图对等',
  '两个视图必须都在模板里有块（只留一个 = 视图切换是摆设）'
)
check(
  /view-switch/.test(page),
  'C5 复用项目既有的 view-switch 控件',
  '同项目同类页面的既有范式，不另造控件'
)

// ---------------------------------------------------------------- D 零写口（工具不可新建）
//
// ★ 自检先行：**必须证明扫描真的扫到了东西**。抽不到任何按钮文本时，
//   「没有写动作」会退化成「空集 == 空集」式的恒真。
//   本仓铁律：判据要先证明自己不是在空跑。
// ★ 第一版写成 `[^>]*>[^<]*（(新建|创建…)`（要求动词后紧跟**全角括号**），
//   反向注入 `<a-button>新建工具</a-button>` 时**没转红** —— 判据太窄 = 形同虚设。
//   改成「抽出按钮的可见文本，看有没有创建类动词」，与括号/标点无关。
const WRITE_VERB = /(新建|创建|新增|添加|导入|删除|上线|下线)/
const btnTexts = [
  ...page.matchAll(/<(a-button|a-upload|a-popconfirm)\b[^>]*>([\s\S]*?)<\/\1>/g),
]
  .map((m) => m[2].replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim())
  .filter(Boolean)

check(
  btnTexts.length > 0,
  'D0 抽到了可复盘的按钮文本（否则 D1 会变成空集恒真）',
  '一个按钮文本都没抽到 ⇒ D1 无论页面写成什么样都会绿'
)
const writeBtns = btnTexts.filter((t) => WRITE_VERB.test(t))
check(
  writeBtns.length === 0,
  'D1 页面上没有任何「新建/创建/删除工具」类写动作',
  '工具由代码定义（TOOL_CATALOG 是手写静态表，没有 tools 表 / ORM 实体 / 归属列）' +
    '⇒ 结构上不存在"新建工具"。命中：' +
    JSON.stringify(writeBtns)
)
check(
  !/post\(\s*['"`]\/tools/.test(page) && !/createTool|deleteTool/.test(page),
  'D2 没有指向工具写端点的调用',
  '后端刻意没有 POST/PUT/DELETE /tools —— 前端若调它，是"以为有"'
)

// ---------------------------------------------------------------- E 唯一写口 + 如实标注
check(
  /store\.saveSkillTools\(/.test(page),
  'E1 skill 配装走 store.saveSkillTools（唯一写口）',
  '唯一可写的工具绑定面是 PUT /skills/{id}/tools'
)
check(
  /不是权限|提示词/.test(page),
  'E2 如实标注「这是提示词引导、不是权限」',
  'skill.tools 在运行期既不授予也不限制任何工具（build_skill_tools 恒只返回 load_skill）'
)
check(
  /canWrite/.test(page),
  'E3 写动作受 canWrite 守卫',
  '拿不到凭据就禁用（方向选择：误禁只多一次点击，误放行会改到数据）'
)

// ---------------------------------------------------------------- F 不许有第二个真源
check(
  !/new Set\(\s*store\.tools\.map/.test(page) && !/tools\.some\(\s*\(?t\)?\s*=>/.test(page),
  'F1 「工具名合不合法」不在前端自己算',
  '必须读后端 /tools/usage 的 unknownTools；前端自己建 Set 做差集 = 第二份实现'
)
check(
  /store\.unknownTools/.test(page),
  'F2 未注册工具名取自后端 unknownTools',
  '与 usage 同一次遍历的三个投影之一，前端不得重算'
)

// ---------------------------------------------------------------- G 不许重复入口
check(
  !/key="tools"/.test(skillPage || ''),
  'G1 SkillManager 里不再有工具 tab',
  '第 209 轮工具仓库已升为平级页面；这里再放一个 = 两个入口两种形态，必然漂移'
)

// ---------------------------------------------------------------- H 判据两侧同时在位（第 255 轮）
//
// ★ 老板本轮原话：「真正在用的判据是「确定性可算」vs「需要判断」这条分别写在
//   我截图红框位置」—— 即**两个页面的横幅各自写清自己那一半**。
//
// ★ 为什么这不是"墓志铭"（本仓对文案断言的既有顾虑）：
//   断言的是**判据本身的两个词**（`确定性` / `需要判断`）与**互指关系**，
//   不是某一句完整文案。改措辞不会红；**把判据从任一侧删掉会红** ——
//   而"判据丢失"正是这条需求会静默失效的方式（横幅少一行，谁也不会发现）。
//   ★ 与 E2 同族：E2 钉的是「如实标注语义」，H 钉的是「如实标注分层判据」。
/**
 * ★ 只在**横幅元素内部**断言，不全文 grep。
 *   踩过的坑（本组注入 ③ 实测）：`/Skill 仓库/` 全文匹配会被**文件头注释**
 *   喂饱（ToolManager 的 docstring 里就写着「Skill 仓库页 = …」）⇒
 *   把横幅里的互指删掉，断言照样绿 —— 判据被注释绊倒，与"注释里的旧串"同族。
 */
function bannerOf(src, cls) {
  if (!src) return ''
  const a = src.indexOf(`class="${cls}"`)
  if (a < 0) return ''
  const rest = src.slice(a)
  const end = rest.search(/<\/(span|p)>/)
  return end < 0 ? rest : rest.slice(0, end)
}
const toolBanner = bannerOf(page, 'tm-head-sub')
const skillBanner = bannerOf(skillPage, 'sm-sub')

check(
  toolBanner.length > 0 && skillBanner.length > 0,
  'H0 两侧横幅元素都解析到了（否则 H1-H3 会空跑/恒真）',
  '解析不出横幅 ⇒ 后面的判据无论页面写成什么样都会通过'
)
check(
  toolBanner.includes('确定可计算 → 工具'),
  'H1 工具仓库横幅写明「确定可计算 → 工具」',
  '横幅缺这条判据 ⇒ 用户看不出工具与技能的边界，只会以为"工具是另一种技能"'
)
check(
  skillBanner.includes('有取舍、需人判 → 技能'),
  'H2 Skill 仓库横幅写明「有取舍、需人判 → 技能」',
  '横幅缺这条判据 ⇒ 同上，且这一半只写在一侧等于只有半个判据'
)
check(
  !/能确定性算出来的做成工具|需要判断（有方法、要取舍）的做成技能/.test(toolBanner + skillBanner),
  'H3 旧长判据文案已退役，不得回归（第 256 轮老板要求改短）',
  '旧长文案回归 ⇒ 介绍重新变长；老板明确要求「改为」短句，留着等于需求回退'
)
check(
  /key="repo"\s+tab="快捷卡片管理"/.test(skillPage || ''),
  'H4 Skill 仓库 repo tab 名为「快捷卡片管理」且 key 未变',
  'key 是 `repo`（第 255 轮只改名、不改 key：多处门禁按 key 切片，改 key 是无收益的破坏性重命名）'
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
    console.log(`工具仓库页面门禁失败：${bad.length} / ${results.length}`)
    process.exit(1)
  }
  console.log(`工具仓库页面门禁通过（${results.length} 条形态断言 ✓）`)
}
