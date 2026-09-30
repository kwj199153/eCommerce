#!/usr/bin/env node
/**
 * 左侧边栏「分组标题规格唯一真源」+「不出滚轮」的**结构**门禁（第 260 轮）
 *
 * ============================================================================
 * ★ 为什么需要它（老板原话：「3 个红框的高度要统一，左侧边栏不出现滚轮」）
 * ============================================================================
 * 三个分组标题（Agent 群 / 资料库 / 能力）的**盒子高度其实一直是相等的**
 * （CDP 实测都是 34.94px）。看起来不一样高，是因为**上间距**实测为 8 / 18 / 2：
 *
 *   AgentList.vue    `.agent-list   { padding: var(--space-8) 0 }`
 *   KnowledgeBase.vue `.knowledge-base { padding: var(--space-8) 0 }`
 *   + 两处各写了一份**逐字相同**的 `.section-title { padding: 12px 16px 8px }`
 *
 * padding 与 padding 叠加 → 三个标题的留白各不相同；而两处重复定义意味着
 * 「改一处、另一处不动」也是静默的。所以本轮把它们收成**一个**全局真源
 * （`src/styles/sidebar-nav.css`），容器纵向 padding 清零。
 *
 * 同一根因还造成第二个症状：内容自然高 957px > 视口 856px ⇒ 出滚轮，
 * 且 `.account-entry` 被挤出可视区（实测 top=895 > 856）。
 *
 * ★ 本门禁只判**结构**（唯一真源 / 类名被引用 / 不得回退的写法）。
 *   **几何**（三个标题真的等高、真的没溢出、真的不出滚轮）由
 *   `scripts/cdp-sidebar-layout-probe.mjs` 在真实浏览器里判 ——
 *   padding 叠加后的实际像素只有浏览器算得出来，读源码证明不了。
 *
 * ★ 判据口径（本仓纪律）：
 *   · 凡「代码形态」判据一律**先剥三类注释**再做 —— 本文件自己的注释里就写着
 *     `.section-title` / `:deep(.ant-menu-item`，不剥注释就是自己喂饱自己（假绿）。
 *   · 「不得再有 X」用**剥注释后的零出现**判，不用「X 不在某处」这种可绕过的写法。
 *   · 断言「纵向 padding 为 0」时解析 shorthand 的**上/下两个位置**，
 *     而不是匹配 `${'padding: 0 ...'}` 这种字面量（改个变量名就会假红/假绿）。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..', 'src')
const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

function read(rel) {
  const p = path.join(ROOT, rel)
  if (!fs.existsSync(p)) return null
  // 行尾归一化必须**真做**：本仓同一文件可 CRLF / LF 混存（该目录里就有）
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/** 剥掉 HTML 注释、块注释、行注释 —— 返回「只有代码」的文本。 */
function code(src) {
  if (src == null) return ''
  return src
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 取出 CSS 规则体（不含选择器），找不到返回 null。`{` 前必须紧跟空格，避免前缀误配。 */
function ruleBody(css, selector) {
  const i = css.indexOf(selector + ' {')
  if (i < 0) return null
  const j = css.indexOf('}', i)
  if (j < 0) return null
  return css.slice(i + selector.length, j)
}

/** 解析 `padding` shorthand 的 上/下 两个位置（未声明视为 null）。 */
function paddingTB(body) {
  const m = /(?:^|[;{\s])padding:\s*([^;]+);/.exec(body)
  if (!m) return { top: null, bottom: null, raw: null }
  const v = m[1].trim().split(/\s+/)
  const top = v[0]
  const bottom = v.length >= 3 ? v[2] : v[0]
  return { top, bottom, raw: m[1].trim() }
}

const cssRaw = read('styles/sidebar-nav.css')
const mainTs = read('main.ts')
const agentList = read('components/Sidebar/AgentList.vue')
const knowledge = read('components/Sidebar/KnowledgeBase.vue')
const workspace = read('views/Workspace.vue')
const account = read('components/Sidebar/AccountMenu.vue')

const css = code(cssRaw)
const al = code(agentList)
const kb = code(knowledge)
const ws = code(workspace)
const ac = code(account)

// ---------------- S0 自检：先证明没空跑 ----------------
const titleRule = ruleBody(css, '.sidebar-section-title')
const itemRule = ruleBody(css, '.sidebar-nav-menu .ant-menu-item')
check(!!cssRaw, 'S0a 读到 styles/sidebar-nav.css')
check(!!mainTs, 'S0b 读到 main.ts')
check(!!agentList && !!knowledge && !!workspace && !!account, 'S0c 读到四个组件文件')
check(/\.sidebar-section-title/.test(cssRaw) && titleRule != null, 'S0d 能从 css 抽出 .sidebar-section-title 规则体')
check(/\.sidebar-nav-menu \.ant-menu-item/.test(cssRaw) && itemRule != null, 'S0e 能从 css 抽出 .sidebar-nav-menu .ant-menu-item 规则体')
check(/<a-layout-sider/.test(ws), 'S0f 能从 Workspace 找到 <a-layout-sider>（模板块提取的前提）')

// ---------------- S1 唯一真源被装载 ----------------
check(!!mainTs && /import\s+'\.\/styles\/sidebar-nav\.css'/.test(mainTs), 'S1 main.ts 装载了 styles/sidebar-nav.css')

// ---------------- S2 分组标题规格 ----------------
const tPad = titleRule ? paddingTB(titleRule) : { top: null, bottom: null, raw: null }
check(!!titleRule && /(?:^|[;{\s])height:\s*32px/.test(titleRule), 'S2a 标题声明了固定 height（三个分组才可能等高）', titleRule && titleRule.trim().slice(0, 80))
check(!!titleRule && /(?:^|[;{\s])margin-top:/.test(titleRule), 'S2b 标题的上间距由**它自己**声明（不是靠容器 padding 叠出来的）')
check(tPad.top === '0' && tPad.bottom === '0', 'S2c 标题**纵向 padding 为 0**（否则会与 margin-top 叠加，重回 8/18/2）', tPad.raw)

// ---------------- S3 菜单项规格 ----------------
const hM = itemRule && /(?:^|[;{\s])height:\s*(\d+)px/.exec(itemRule)
const lM = itemRule && /(?:^|[;{\s])line-height:\s*(\d+)px/.exec(itemRule)
check(!!hM && !!lM && hM[1] === lM[1], 'S3 菜单项 height 与 line-height 同值（不同值会让文字不居中）', itemRule && itemRule.trim().slice(0, 60))
check(/\.sidebar-nav-menu \.ant-menu-item:last-child/.test(cssRaw), 'S3b 最后一项清零底边距（否则下一分组的上间距多 1px）')

// ---------------- S4 组件里不得再有第二份样式定义 ----------------
check(!/\.section-title/.test(al), 'S4a AgentList.vue 已无旧的 .section-title（重复定义退役）')
check(!/\.section-title/.test(kb), 'S4b KnowledgeBase.vue 已无旧的 .section-title（重复定义退役）')
check(!/:deep\(\.ant-menu-item/.test(al), 'S4c AgentList.vue 不再自己写 :deep(.ant-menu-item)（收口到全局真源）')
check(!/:deep\(\.ant-menu-item/.test(kb), 'S4d KnowledgeBase.vue 不再自己写 :deep(.ant-menu-item)（收口到全局真源）')

// ---------------- S5 容器纵向 padding 必须为 0 ----------------
function containerPad(rel, src, cls) {
  const i = src.indexOf('.' + cls + ' {')
  if (i < 0) return { found: false }
  const j = src.indexOf('}', i)
  const body = src.slice(i, j)
  return { found: true, ...paddingTB(body), body: body.trim().slice(0, 70) }
}
const alPad = containerPad('components/Sidebar/AgentList.vue', al, 'agent-list')
const kbPad = containerPad('components/Sidebar/KnowledgeBase.vue', kb, 'knowledge-base')
check(alPad.found && alPad.top === '0' && alPad.bottom === '0', 'S5a .agent-list 纵向 padding 为 0', alPad.body || '(找不到规则)')
check(kbPad.found && kbPad.top === '0' && kbPad.bottom === '0', 'S5b .knowledge-base 纵向 padding 为 0', kbPad.body || '(找不到规则)')

// ---------------- S6 类名被真的引用 ----------------
const titleUses = (al.match(/class="sidebar-section-title"/g) || []).length
  + (kb.match(/class="sidebar-section-title"/g) || []).length
const menuUses = (al.match(/class="sidebar-nav-menu"/g) || []).length
  + (kb.match(/class="sidebar-nav-menu"/g) || []).length
check(titleUses === 3, 'S6a 恰好 3 处分组标题用了 .sidebar-section-title（1 + 2）', titleUses)
check(menuUses === 3, 'S6b 恰好 3 处分节菜单用了 .sidebar-nav-menu（1 + 2）', menuUses)
check(/\.knowledge-base/.test(kb), 'S6c `.knowledge-base` 类名保留（另一个 CDP 探针依赖它定位侧边栏）')

// ---------------- S7 侧边栏不出滚轮 ----------------
const sidebarRule = ruleBody(ws, '.sidebar')
check(!!sidebarRule && /scrollbar-width:\s*none/.test(sidebarRule), 'S7a .sidebar 声明 scrollbar-width: none', sidebarRule && sidebarRule.trim().slice(-60))
check(/\.sidebar::\-webkit\-scrollbar/.test(ws), 'S7b 存在 .sidebar::-webkit-scrollbar 规则（覆盖旧内核）')

// ---------------- S8 侧边栏块内不再有叠加分隔线 ----------------
const siderStart = ws.indexOf('<a-layout-sider')
const siderEnd = ws.indexOf('</a-layout-sider>', siderStart)
const siderBlock = siderStart >= 0 && siderEnd > siderStart ? ws.slice(siderStart, siderEnd) : ''
check(siderBlock.length > 0 && siderBlock.includes('SidebarAccountMenu'), 'S8a 成功切出左侧边栏模板块（含账户入口）')
check(!/<a-divider/.test(siderBlock), 'S8b 左侧边栏块内没有 <a-divider>（账户入口自带 border-top，分隔线只会白占 17px）')

// ---------------- S9 账户入口粘底（含前置条件） ----------------
const accRule = ruleBody(ac, '.account-entry')
check(!!accRule && /position:\s*sticky/.test(accRule) && /bottom:\s*0/.test(accRule), 'S9a .account-entry 粘底（position: sticky + bottom: 0）')
check(!!accRule && /background-color:/.test(accRule), 'S9b .account-entry 有背景色（否则滚上来的菜单项会透出来）')
const childRule = ruleBody(ws, ':deep(.ant-layout-sider-children)')
check(!!childRule && /min-height:\s*100%/.test(childRule), 'S9c sider-children 保留 min-height: 100%（内容短时才把账户入口推到底）')
// ★ 这里**刻意没有**「不得写死 height: 100%」那条断言 —— 曾经写过，被实测否掉：
//   856 / 768 两档下把这个盒子的 height: 100% 去掉前后，computed height 都是 768px、
//   账户入口位置逐像素相同（.ant-layout-sider 自己是 flex 容器，盒子被拉伸定高）。
//   写一条永远测不出差别的断言等于给「信仰」盖章 —— 删掉，并在源码里留证。

// ---------------- S10 npm 脚本登记 ----------------
const pkg = (() => {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')) } catch { return null }
})()
check(!!pkg && /cdp-sidebar-layout-probe\.mjs/.test(String(pkg.scripts?.['check:sidebar-geometry'] || '')), 'S10 package.json 登记了 check:sidebar-geometry（几何探针入口）')
check(!!pkg && /check-sidebar-layout\.cjs/.test(String(pkg.scripts?.build || '')), 'S11 本门禁已接入 npm run build 链')

// ---------------- 汇总 ----------------
const failed = results.filter(r => !r.ok)
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.label}${r.ok ? '' : '  ⟵ ' + JSON.stringify(r.detail)}`)
}
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
if (failed.length) {
  console.log('红：' + failed.map(r => r.label.split(' ')[0]).join(', '))
  process.exit(1)
}
console.log('侧边栏结构门禁通过（标题规格唯一真源 · 容器零纵向 padding · 类名被引用 · 不出滚轮 · 账户入口粘底 ✓）')
