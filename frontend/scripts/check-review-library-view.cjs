#!/usr/bin/env node
/**
 * 复盘库（资料库 → 复盘库）**跨端接线**门禁（第 251 轮）
 *
 * ============================================================================
 * ★ 为什么需要它
 * ============================================================================
 * 「新增一个资料库」在本仓是**一处需求、五处接线**，而漏掉任何一处都不会报错：
 *
 *   ① 侧边栏菜单项（`Sidebar/KnowledgeBase.vue` 的 `<a-menu-item key="reviews">`）
 *      —— 漏了：用户根本没有入口；
 *   ② Workspace 渲染分支（`<ReviewLibrary v-else-if="currentView === 'reviews'" />`）
 *      —— 漏了：菜单点得到、内容区空白（零报错）；
 *   ③ Workspace `currentView` 联合类型 —— 漏了：`vue-tsc` 报错，或被静默 cast；
 *   ④ `handleKnowledgeNavigate` 的 cast —— 漏了：菜单点击切不过去；
 *   ⑤ `appActions.ts` 的 `AppView` / `VALID_VIEWS` / `VIEW_LABELS`
 *      —— 漏了：**AI 动作**跳转被静默拒（`return false`），而组件内部走
 *      CustomEvent 是通的 ⇒ 同一条能力两条通道两种结果；
 *   ⑥ 后端 `navigation_tools.py::VIEW_IDS` —— 漏了：LLM 的工具签名里**没有这个
 *      枚举值** ⇒ 老板说「打开复盘库」，主 Agent 答「没有这个视图」。
 *
 * ★ 这六处**必须集合相等**，而不是「包含」。本仓踩过的形态：子序列断言
 *   （`expected ⊆ actual`）在"实际集合更大"时恒真 —— 它给缺陷盖章。
 *   所以下面对能取到全集的两侧做**集合相等**，对取不到全集的做**双向包含**。
 *
 * ★ 顺带钉住本轮**修掉的那处既有漂移**：`competitors`（竞品监控**池**视图）
 *   此前只在前端组件里被跳转（`IntelBoardConfig.vue` 走 CustomEvent），
 *   但**不在 `AppView` / `VALID_VIEWS` / 后端 `VIEW_IDS`** 里 ⇒
 *   AI 动作跳不过去。下面 C2/C3 就是那条判据。
 *
 * ★ 本门禁**只判形态**（接线 / 集合 / 有无真调用），不判文案。
 */

const fs = require('fs')
const path = require('path')

const ROOT = process.env.REVIEW_LIB_SRC_ROOT || path.join(__dirname, '..', 'src')
const REPO = path.join(__dirname, '..', '..')
const BE = path.join(REPO, 'backend')

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

function read(rel, base) {
  const p = path.join(base || ROOT, rel)
  if (!fs.existsSync(p)) return null
  // ★ 行尾归一化必须**真做**：本仓同一文件可 CRLF / LF 混存，
  //   不归一化会让锚点静默失配（症状是"找不到分支"，方向错得很远）。
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}
const uniq = (a) => [...new Set(a)].sort()
const eq = (a, b) => JSON.stringify(uniq(a)) === JSON.stringify(uniq(b))

/**
 * 剥掉三类注释（HTML / 块 / 行），得到**只有代码**的文本。
 *
 * ★★ 为什么每个「代码形态」判据都必须在剥注释之后做（本仓两处实锤，
 *    都是本门禁**反向注入时**才暴露的）：
 *      · `F5` 原来判 `/v-if="$slots\.footer"/` 用的是原文 —— 而外壳文件的
 *        **注释里**就写着「用 `$slots.footer` 判断…」⇒ 把真实属性删掉，
 *        断言照样绿（**注释喂饱了判据**）；
 *      · `F1` 是"不得出现 store_id"的反向判据，不剥注释会**假红**
 *        （页面的注释里恰好写着「本页不传 store_id」这句说明）。
 *    两种方向都会出事，所以统一走本函数。
 */
function code(t) {
  return String(t || '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
}

// ============================================================ 读取
const page = read('components/KnowledgeBase/ReviewLibrary.vue')
const kb = read('components/Sidebar/KnowledgeBase.vue') || ''
const ws = read('views/Workspace.vue') || ''
const actions = read('utils/appActions.ts') || ''
const api = read('api/review.ts') || ''
const card = read('components/ChatPanel/results/conversation/ReviewReportCard.vue') || ''
const shell = read('components/ChatPanel/results/conversation/ConversationCard.vue') || ''

const navPy = read('modules/secretary/navigation_tools.py', BE) || ''
const dbPy = read('modules/review_analyst/db_model.py', BE) || ''
const specPy = read('modules/review_analyst/spec.py', BE) || ''

check(page !== null, 'A0 复盘库页面存在', 'components/KnowledgeBase/ReviewLibrary.vue')

// ============================================================ 规则：抽取
/** 抽一段区间里的 `<a-menu-item key="x">`（区间用**分节标题**界定）。 */
function menuKeysIn(src, fromMarker, toMarker) {
  const a = src.indexOf(fromMarker)
  if (a < 0) return []
  const b = toMarker ? src.indexOf(toMarker, a + 1) : src.length
  const seg = src.slice(a, b < 0 ? src.length : b)
  return [...seg.matchAll(/<a-menu-item\s+key="([a-z_]+)"/g)].map((m) => m[1])
}

const DATA_LIB = menuKeysIn(kb, '资料库</div>', '能力</div>')
const ABILITY = menuKeysIn(kb, '能力</div>', null)

/** 抽 `export type X = ...` / `const X = ...` 之后到下一个顶层声明之前的引号字面量。 */
function literalsAfter(src, anchor) {
  const i = src.indexOf(anchor)
  if (i < 0) return []
  const rest = src.slice(i + anchor.length)
  const stop = rest.search(/\n(?=export |const |function |\/\*\*|\/\*)/)
  const seg = stop < 0 ? rest : rest.slice(0, stop)
  return [...seg.matchAll(/'([a-z_]+)'/g)].map((m) => m[1])
}

const VIEW_UNION_M = /const\s+currentView\s*=\s*ref<([^>]+)>/.exec(ws)
const viewUnion = VIEW_UNION_M
  ? [...VIEW_UNION_M[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1])
  : []

const CAST_M = /currentView\.value\s*=\s*key\s+as\s+([^\n]+)/.exec(ws)
const castKeys = CAST_M ? [...CAST_M[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]) : []

const appViews = literalsAfter(actions, 'export type AppView =')
const validViews = literalsAfter(actions, 'const VALID_VIEWS = new Set<AppView>([')
const LABEL_SEG = actions.slice(actions.indexOf('export const VIEW_LABELS'))
const viewLabels = [
  ...LABEL_SEG.slice(0, LABEL_SEG.indexOf('\n}')).matchAll(/^\s*([a-z_]+):/gm),
].map((m) => m[1])

/** `<Xxx v-if|v-else-if="currentView === 'k'"` —— **渲染分支链**（不是别处的比较）。 */
const renderKeys = [...ws.matchAll(/<[A-Z]\w+\s+v-(?:if|else-if)="currentView === '([a-z_]+)'"/g)].map(
  (m) => m[1]
)

const beViewIds = /VIEW_IDS\s*=\s*\[([\s\S]*?)\]/.exec(navPy)
  ? [.../VIEW_IDS\s*=\s*\[([\s\S]*?)\]/.exec(navPy)[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
  : []

const beViewIdTypes = /ViewId\s*=\s*Literal\[([\s\S]*?)\]/.exec(navPy)
  ? [.../ViewId\s*=\s*Literal\[([\s\S]*?)\]/.exec(navPy)[1].matchAll(/"([a-z_]+)"/g)].map(
      (m) => m[1]
    )
  : []

const beTypes = /REVIEW_REPORT_TYPES[^=]*=\s*\(([\s\S]*?)\)/.exec(dbPy)
  ? [.../REVIEW_REPORT_TYPES[^=]*=\s*\(([\s\S]*?)\)/.exec(dbPy)[1].matchAll(/"([a-z_]+)"/g)].map(
      (m) => m[1]
    )
  : []

// ★ 抽取必须**锚在定义形态上**（`export const REVIEW_REPORT_TITLES = { ... }` 的花括号内）。
//   第一版写成全文 `^\s{2}([a-z_]+): '` —— 结果把 `ReviewCampaign.grade: 'S' | 'B' | 'C'`
//   和 `ReviewInventoryItem.health_status: 'HEALTHY' | ...` 也抽了进来（假红）。
//   与本仓「判据锚点必须取定义形态」同一条。
const TITLES_M = /export\s+const\s+REVIEW_REPORT_TITLES[^{]*\{([\s\S]*?)\n\}/.exec(api)
const feTitles = TITLES_M
  ? [...TITLES_M[1].matchAll(/^\s*([a-z_]+):\s*'/gm)].map((m) => m[1])
  : []

// ============================================================ B 自检（先证明没空跑）
check(DATA_LIB.length >= 7, 'B0 解析出「资料库」分组的菜单 key（≥7）',
  `实际 ${JSON.stringify(DATA_LIB)} —— 解析落空时后面所有集合运算都会变成空集恒真`)
check(ABILITY.length >= 2, 'B0b 解析出「能力」分组的菜单 key（≥2）', JSON.stringify(ABILITY))
check(viewUnion.length >= 9, 'B0c 解析出 Workspace 的 currentView 联合类型（≥9）',
  JSON.stringify(viewUnion))
check(renderKeys.length >= 9, 'B0d 解析出 Workspace 的渲染分支链（≥9）', JSON.stringify(renderKeys))
check(appViews.length >= 8, 'B0e 解析出 appActions 的 AppView（≥8）', JSON.stringify(appViews))
check(validViews.length >= 8, 'B0f 解析出 VALID_VIEWS（≥8）', JSON.stringify(validViews))
check(viewLabels.length >= 8, 'B0g 解析出 VIEW_LABELS 的键（≥8）', JSON.stringify(viewLabels))
check(beViewIds.length >= 7, 'B0h 解析出后端 VIEW_IDS（≥7）', JSON.stringify(beViewIds))
check(beViewIdTypes.length >= 8, 'B0k 解析出后端 ViewId Literal（≥8）', JSON.stringify(beViewIdTypes))
check(feTitles.length === 6, 'B0i 解析出前端 6 个报告类型中文名', JSON.stringify(feTitles))
check(beTypes.length === 6, 'B0j 解析出后端 6 个报告类型', JSON.stringify(beTypes))

// ============================================================ C 五处接线（逐个 key）
const KEY = 'reviews'
check(kb.includes(`<a-menu-item key="${KEY}"`), `C1 侧边栏有 key="${KEY}" 菜单项`,
  '漏了 ⇒ 用户没有入口')
check(/<ReviewLibrary\b/.test(ws), 'C2 Workspace 有 <ReviewLibrary> 渲染分支',
  '漏了 ⇒ 菜单点得到、内容区空白（零报错）')
check(viewUnion.includes(KEY), `C3 currentView 联合类型含 ${KEY}`,
  "漏了 ⇒ vue-tsc 报错，或菜单 key 被静默 cast 成不存在的视图")
check(castKeys.includes(KEY), `C4 导航 cast 含 ${KEY}`,
  '漏了 handleKnowledgeNavigate 的 cast ⇒ 菜单点击切不过去')
check(appViews.includes(KEY), `C5 appActions AppView 含 ${KEY}`,
  '漏了 ⇒ AI 动作跳转进不来（TYPE 层就没有这个值）')
check(validViews.includes(KEY), `C6 VALID_VIEWS 含 ${KEY}`,
  '漏了 ⇒ dispatchAppAction 静默 return false（AI 说已打开、界面没动）')
check(viewLabels.includes(KEY), `C7 VIEW_LABELS 含 ${KEY}`,
  '漏了 ⇒ 回复文案/日志里没有中文名（Record<AppView,string> 会报 tsc 错）')
check(beViewIds.includes(KEY), `C8 后端 VIEW_IDS 含 ${KEY}`,
  '漏了 ⇒ LLM 工具签名里没有这个枚举值，Agent 会答「没有这个视图」')

// ============================================================ D 集合相等（不是子序列）
check(eq([...DATA_LIB, ...ABILITY], viewUnion.filter((k) => k !== 'chat')),
  'D1 侧边栏两组 key == Workspace 视图联合 \\ {chat}（集合相等）',
  `侧边栏=${JSON.stringify(uniq([...DATA_LIB, ...ABILITY]))} 视图=${JSON.stringify(uniq(viewUnion.filter((k) => k !== 'chat')))}`)
check(eq(castKeys, viewUnion.filter((k) => k !== 'chat')),
  'D2 导航 cast == 视图联合 \\ {chat}（集合相等）',
  `cast=${JSON.stringify(uniq(castKeys))}`)
check(eq(renderKeys, viewUnion), 'D3 渲染分支 == 视图联合（双向：无孤儿视图、无孤儿分支）',
  `分支=${JSON.stringify(uniq(renderKeys))} 视图=${JSON.stringify(uniq(viewUnion))}`)
check(eq(appViews.filter((k) => k !== 'chat' && k !== 'monitor'), DATA_LIB),
  'D4 AppView \\ {chat, monitor} == 「资料库」分组 key（集合相等）',
  `AppView=${JSON.stringify(uniq(appViews))} 资料库=${JSON.stringify(uniq(DATA_LIB))}`)
check(eq(beViewIds, appViews.filter((k) => k !== 'chat')),
  'D5 后端 VIEW_IDS == AppView \\ {chat}（集合相等）',
  `后端=${JSON.stringify(uniq(beViewIds))} 前端=${JSON.stringify(uniq(appViews.filter((k) => k !== 'chat')))}`)

check(eq(beViewIds, beViewIdTypes),
  'D8 后端 VIEW_IDS == ViewId Literal（运行时清单 == LLM 工具签名，集合相等）',
  `VIEW_IDS=${JSON.stringify(uniq(beViewIds))} ViewId=${JSON.stringify(uniq(beViewIdTypes))} —— 两者漂移 ⇒ LLM 能产出「跳到差评处置」，而那个视图已经不存在，跳过去是空白且零报错`)
check(eq(validViews, appViews), 'D6 VALID_VIEWS == AppView（集合相等）',
  `VALID=${JSON.stringify(uniq(validViews))}`)
check(eq(viewLabels, appViews), 'D7 VIEW_LABELS 键 == AppView（集合相等）',
  `LABELS=${JSON.stringify(uniq(viewLabels))}`)

// ============================================================ E 唯一真源 + 真后端调用
check(/key="reviews"/.test(specPy),
  'E1 后端 REVIEW_SPEC.key == "reviews"（跨端同一 key）',
  '后端换名 ⇒ 前端点进去是空白页')
check(eq(feTitles, beTypes), 'E2 前端 6 个类型中文名 == 后端 REVIEW_REPORT_TYPES（集合相等）',
  `前端=${JSON.stringify(uniq(feTitles))} 后端=${JSON.stringify(uniq(beTypes))}`)
check(!/const\s+TITLES\s*[:=]/.test(code(card)),
  'E3 会话卡不再自己写一份类型中文名（唯一真源在 api/review.ts）',
  '两处各写一份 ⇒ 同一类型在两个地方叫两个名字，且谁都不报错')
check(/reviewTitleOf/.test(code(card)) && /REVIEW_REPORT_TITLES/.test(code(api)),
  'E4 会话卡从唯一真源取中文名',
  'card 应 import reviewTitleOf / REVIEW_REPORT_TITLES')
check(/listSavedReports\(/.test(code(page)) && /getSavedReport\(/.test(code(page)),
  'E5 页面真的调后端（listSavedReports / getSavedReport）',
  '「后端有端点」≠「前端在用」—— 必须数消费点')
check(!/mock/i.test(code(page)), 'E6 页面不引用任何 mock', '复盘库是真实数据页面')

// ============================================================ F 归属 + 失败路径
// ★ 三类注释都要剥（理由见 `code()`）：这是**反向**判据（"不得出现"），
//   不剥注释会**假红** —— 而本页的注释里恰好写着「本页不传 store_id」这句说明。
const pageCode = code(page)
check(!/store_id|shop_id|X-Shop-ID/.test(pageCode),
  'F1 页面不传 store_id（归属由 request.ts 拦截器注入 X-Shop-ID）',
  `归属只能服务端注入：前端自己算容器 = 后端判据的第二份实现；命中位置 ${pageCode.search(/store_id|shop_id|X-Shop-ID/)}`)
// ★ 用**位置**判「错误态优先于空状态」，不用多行正则猜结构：
//   `<a-alert v-if="error">` 必须出现在 `<a-empty v-else-if="!loading && !items.length">` 之前。
const iErr = page.indexOf('v-if="error"')
const iEmpty = page.indexOf('a-empty')
check(iErr >= 0 && iEmpty >= 0 && iErr < iEmpty,
  'F2 错误态优先于空状态渲染（v-if="error" 在 a-empty 之前）',
  `error@${iErr} empty@${iEmpty} —— 反了就是「读不到」被显示成「你还没归档过」（两种空语义混同）`)
check(/\barchiveState\b/.test(code(card)) && /\barchiveError\b/.test(code(card)),
  'F3 归档入口有失败回写状态（archiveState / archiveError）',
  '失败只弹 toast ⇒ 按钮停在可点状态，老板不知道到底进没进库')
// ★ `\b` 不可省：第一版写成 `/res\.item/`，结果被**页面**里的
//   `res.items`（复数）顶掉 —— `res.item` 是 `res.items` 的**前缀**，
//   于是"归档端做了伪成功防御"这条判据在注入后**照样绿**（反向注入实测）。
//   本仓判据铁律：禁「源码字符串包含」，会被同族更长标识符顶掉。
//   同时钉住"看的是 item.id"而不只是 item 存在。
check(/\bres\.item\b/.test(code(card)) && /\bitem\.id\b/.test(code(card)),
  'F4 归档做了「伪成功」防御（检 item.id 而不是只看没抛错）',
  '后端这三个端点**没有**统一信封（无 success 字段），只判"没抛错"会漏')
check(/\$slots\.footer/.test(code(shell)) && /#footer/.test(code(card)),
  'F5 会话卡外壳提供 footer slot 且归档入口挂在里面',
  '动作区要与正文视觉分隔；没有 footer slot 只能把按钮塞进正文')

// ============================================================ G 导出唯一真源（第 266 轮）
// ★ 为什么钉在本门禁里而不是另开一个：导出的两个入口与「复盘库接线」是同一处
//   需求的两半 —— 复盘库页面的导出按钮就长在本页，而摊平口径是两页共用。
//   本门禁开篇那句「一处需求、五处接线，漏掉任何一处都不会报错」在导出这里同样成立：
//   任一消费点自己再写一份摊平，两份产出的表**内容不一致且没有任何报错**。
const exp = read('utils/reviewExport.ts')
const expCode = code(exp || '')
const cardCode = code(card)
const pageCode2 = code(page)

check(exp !== null && expCode.length > 500, 'G0 摊平唯一真源 utils/reviewExport.ts 存在且非空',
  '文件缺失/解析落空时下面所有判据都会在空串上恒真（空集恒真）')

check(/from\s+'@\/utils\/reviewExport'/.test(cardCode),
  'G1a 会话卡从唯一真源取摊平与格式化',
  "card 应 import '@/utils/reviewExport'")
check(/from\s+'@\/utils\/reviewExport'/.test(pageCode2),
  'G1b 复盘库页面从唯一真源取摊平与格式化',
  "page 应 import '@/utils/reviewExport'")

// ★ 反向判据（"不得出现"）。不剥注释会**假红** —— 两个文件的注释里都写着
//   「共用同一份摊平函数（utils/reviewExport.ts）」这类说明。
check(!/function\s+toTextList\b/.test(cardCode) && !/const\s+HEALTH_CN\b/.test(cardCode) && !/function\s+metricText\b/.test(cardCode),
  'G2a 会话卡不再自带 toTextList / metricText / HEALTH_CN',
  '两处各写一份 ⇒ 同一份复盘从两个入口导出的表不一样，且谁都不报错')
check(!/function\s+toTextList\b/.test(pageCode2) && !/const\s+HEALTH_CN\b/.test(pageCode2) && !/function\s+metricText\b/.test(pageCode2),
  'G2b 复盘库页面不再自带 toTextList / metricText / HEALTH_CN',
  '同上')

// 表头唯一真源 + (b) 口径三列。★ 锚在**定义形态**上（`export const REVIEW_EXPORT_COLUMNS = [...]`），
// 不用全文引号字面量 —— 那会被文件里其它中文串顶掉。
const COL_M = /export\s+const\s+REVIEW_EXPORT_COLUMNS[^=]*=\s*\[([^\]]*)\]/.exec(expCode)
const cols = COL_M ? [...COL_M[1].matchAll(/'([^']+)'/g)].map((m) => m[1]) : []
check(JSON.stringify(cols) === JSON.stringify(['类型', '条目', '数值']),
  'G3 导出表头 == (b) 口径的三列「类型 | 条目 | 数值」',
  `实际 ${JSON.stringify(cols)} —— 口径变了要在代码评审里说，不能静默多/少一列`)

check(/:columns="REVIEW_EXPORT_COLUMNS"/.test(cardCode) && /:columns="REVIEW_EXPORT_COLUMNS"/.test(pageCode2),
  'G4 两个消费点都引用同一份表头常量（没有第二份 columns 字面量）',
  '<ExportModal :columns> 必须指向唯一真源，就地写数组 = 副本')

check(/<ExportModal\b/.test(cardCode) && /<ExportModal\b/.test(pageCode2),
  'G5 两个消费点都真的挂了导出弹窗',
  '只加按钮不挂弹窗 ⇒ 点击无反应（零报错）')

check(/reviewReportToRows\(/.test(cardCode) && /reviewReportToRows\(/.test(pageCode2),
  'G6 两个消费点都调唯一真源的摊平函数',
  '任一处在就地拼行 = 第二份实现')

// 文本条目解析必须兼容 `{content}`：
// 旧实现取 `x?.text ?? x?.title`，遇上 `actions` 的 `{priority, content}` 得空串
// ⇒ 整个「建议动作」被**整行丢掉**。界面看不出来（后端 actions 恒空），
//   只会在导出文件里静默少一块 —— 所以必须由门禁钉住。
// ★ 判据窗口限定在**被测函数体内**（到下一个行首 `}` 为止）：全文件正则会被
//   `pushDetailBlock` 里别处的 content 之类顶掉（本仓「判据窗口须限定在被测块内」）。
const textOfBody = (() => {
  const i = expCode.indexOf('export function textOf(')
  if (i < 0) return ''
  const j = expCode.indexOf('\n}', i)
  return j < 0 ? expCode.slice(i) : expCode.slice(i, j)
})()
check(textOfBody.length > 0 && /\bcontent\b/.test(textOfBody),
  'G7 文本条目解析兼容 `{content}`（旧实现会把 actions 整行丢掉）',
  "textOf 的函数体里必须取 content；只有 text/title 时「建议动作」导出为空")

// ============================================================ 报告
const bad = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.label}`)
  if (!r.ok && r.detail) console.log(`        ↳ ${r.detail}`)
}
console.log('')
if (bad.length) {
  console.log(`复盘库接线门禁失败：${bad.length} / ${results.length}`)
  process.exit(1)
}
console.log(`复盘库接线门禁通过（${results.length} 条形态断言 ✓）`)
