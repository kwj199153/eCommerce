#!/usr/bin/env node
/**
 * 「新手引导 · 锚点对账」门禁（第 284 轮）
 *
 * ## 为什么需要它
 *
 * 引导机制的高亮目标靠 `data-tour="id"` 与 DOM 关联。这条链有两个方向会坏，
 * 而且**两个方向坏起来都是静默的**：
 *
 *   · 方向 A「注册了没标」：配置表里加了锚点，DOM 上忘了打 ⇒
 *     引导走到那一步时 `querySelector` 返回 null ⇒ 该步被跳过，
 *     界面上看不出「少讲了一块」。
 *   · 方向 B「标了没注册」：DOM 上标了，配置表没登记 ⇒
 *     那个位置**永远不会被讲到**，而它在代码里看起来是「已经做了引导」的。
 *
 * 更麻烦的是它们会互相掩盖：两边都加上再加一个错别字，就成了「两处都对，但对着的是
 * 两个不同的 id」。所以这里做的是**集合相等**级别的对账，任何一侧多一个/少一个都红。
 *
 * ## 为什么连事件也要对账
 *
 * 引导宿主（挂在 App 根）拿不到 Workspace 的局部 ref，两边靠 window 命令事件通信：
 *
 *   TourHost --发--> 'tour:ensure-sidebar' --Workspace 执行--> sidebarCollapsed = false
 *
 * 这是典型的「一个发送点 + 一个接收点」结构 → **发送侧没人接 = 静默无效**，
 * **接收侧没人发 = 死代码**。两者都不会报错，所以一并钉住（判据 ⑤⑥）。
 *
 * ## 判据
 *
 *   ① **L0 自检**：注册表解析出 ≥ 7 个 id；DOM 侧扫到 ≥ 7 处打标
 *      （「先证明选择器选到了东西」，否则后面所有 PASS 都可能是假的）
 *   ② 方向 A：每个注册 id 在 DOM 上**恰好一处**打标（0 处 ⇒ 漏标；≥2 处 ⇒ 重复宣告）
 *   ③ 方向 B：DOM 上出现的每个 id 都已注册
 *   ④ 步骤表 `TOUR_STEPS` 的每个 `anchor` 必须 ∈ 注册集合（不许自造锚点名）
 *   ⑤ 发得出就有人接：`TourHost` 的每个 `prepare` 命令事件都能在对应接收方找到监听
 *      · `tour:ensure-sidebar` / `tour:ensure-right-panel` → `views/Workspace.vue`
 *      · `view-navigate`（既有事件，复用） → `views/Workspace.vue`
 *   ⑥ `tour:replay` 必须「有人发 + 有人听」—— 界面文案向用户承诺了
 *      「随时可以从账户菜单里重看新手引导」，承诺就得成对存在
 *   ⑦ `App.vue` 必须挂 `<TourHost />`，且**只挂一次**（全局唯一宿主）
 *   ⑧ 语音**必须双通道**（克隆优先 + 原生兜底），且缓存键带店铺、降级不许静默
 *
 * ★ 每个 id 找不到就 **FAIL**，不做「跳过」——「拿不到清单 ≠ 清单为空」。
 * ★ 判据一律跑在**剥离注释后**的源码上（本仓铁律：注释里的旧文案会骗过检查）。
 *   剥注释时**保护 `://`**：否则 `https://…` 会把整行当注释吃掉，反而漏掉真代码。
 *
 * ## 反向注入（见 `.workbuddy/probes/r284_tour_anchor_reverse_inject.py`）
 *
 *   · 删掉一处 `data-tour`                          ⇒ ② 红
 *   · 注册表多写一个没打标的 id                      ⇒ ② 红
 *   · 把某个 id 改一个字符                          ⇒ ② + ③ 同红（集合不等）
 *   · 在别的文件里加一处同名的 `data-tour`            ⇒ ② 红（重复宣告）
 *   · TOUR_STEPS 的 anchor 写成未注册的值             ⇒ ④ 红
 *   · 摘掉 Workspace 的 `tour:ensure-sidebar` 监听     ⇒ ⑤ 红
 *   · 删掉 App.vue 里的 `<TourHost />`                ⇒ ⑦ 红
 *   · 摘掉解说层的 `speakVoice(` 调用                  ⇒ ⑧a 红（改回单通道）
 *   · 摘掉解说层的 `new SpeechSynthesisUtterance(`     ⇒ ⑧b 红（改回单通道）
 *   · 把克隆音频缓存键改成只按文案                      ⇒ ⑧c 红（跨店铺串味）
 *   · 摘掉气泡上的 `v-if="channelLabel"`               ⇒ ⑧d 红（降级变静默）
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   TOUR_SRC_ROOT=<副本或空目录>      ⇒ ①~⑥ 红（8 个源文件与扫描面读不到）
 *
 */

const fs = require('node:fs')
const path = require('node:path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const ROOT = path.resolve(__dirname, '..')
const SRC = pick('TOUR_SRC_ROOT', path.join(ROOT, 'src'))

const ANCHOR_FILE = path.join(SRC, 'config', 'tourAnchors.ts')
const STEPS_FILE = path.join(SRC, 'config', 'tourSteps.ts')
const HOST_FILE = path.join(SRC, 'components', 'Tour', 'TourHost.vue')
const WS_FILE = path.join(SRC, 'views', 'Workspace.vue')
const APP_FILE = path.join(SRC, 'App.vue')
const MENU_FILE = path.join(SRC, 'components', 'Sidebar', 'AccountMenu.vue')
const NARRATOR_FILE = path.join(SRC, 'composables', 'useTourNarrator.ts')
const TIP_FILE = path.join(SRC, 'components', 'Tour', 'TourTooltip.vue')

const fails = []
function check(ok, name, detail) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : '\n      ⟵ ' + (detail ?? '')}`)
  if (!ok) fails.push(name)
}

// ---------------- 工具 ----------------

/**
 * 剥注释：行注释 + 块注释 + HTML 注释。
 * 保护 `:  //` 这种出现在字符串里的 URL —— 不保护的话 `https://x` 会把整行吃掉，
 * 于是漏掉真代码，产出假的「零命中」。
 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  let inStr = null // ' " ` 之一
  while (i < n) {
    const c = src[i]
    const next = src[i + 1]
    if (inStr) {
      out += c
      if (c === '\\') {
        out += next ?? ''
        i += 2
        continue
      }
      if (c === inStr) inStr = null
      i++
      continue
    }
    if (c === '"' || c === "'" || c === '`') {
      inStr = c
      out += c
      i++
      continue
    }
    if (c === '/' && next === '/') {
      while (i < n && src[i] !== '\n') i++
      continue
    }
    if (c === '/' && next === '*') {
      i += 2
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
      continue
    }
    if (c === '<' && src.slice(i, i + 4) === '<!--') {
      const end = src.indexOf('-->', i)
      i = end === -1 ? n : end + 3
      continue
    }
    out += c
    i++
  }
  return out
}

function walk(dir, exts) {
  const out = []
  const stack = [dir]
  while (stack.length) {
    const d = stack.pop()
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) stack.push(p)
      else if (exts.some((x) => e.name.endsWith(x))) out.push(p)
    }
  }
  return out
}

const rel = (p) => path.relative(ROOT, p).replace(/\\/g, '/')
const read = (p) => (fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null)

// ---------------- L0：源文件都在 ----------------
for (const [p, label] of [
  [ANCHOR_FILE, '锚点注册表'],
  [STEPS_FILE, '步骤规格表'],
  [HOST_FILE, '引导宿主'],
  [WS_FILE, '布局属主'],
  [APP_FILE, '应用根'],
  [MENU_FILE, '账户菜单'],
  [NARRATOR_FILE, '语音解说层'],
  [TIP_FILE, '引导气泡'],
]) {
  check(read(p) !== null, `L0 源文件存在：${label}（${rel(p)}）`, `文件不存在 ⇒ 门禁自己失明`)
}
if (fails.length) {
  console.log('\nRESULT: FAIL —— 源文件缺失，后续判据无从谈起')
  process.exit(1)
}

const anchorSrc = read(ANCHOR_FILE)
const stepsSrc = read(STEPS_FILE)
const hostSrc = read(HOST_FILE)
const wsSrc = read(WS_FILE)
const appSrc = read(APP_FILE)
const menuSrc = read(MENU_FILE)
const narratorSrc = read(NARRATOR_FILE)
const tipSrc = read(TIP_FILE)

// ---------------- ① L0：两侧都得解析出东西 ----------------
const RE_ANCHOR_BLOCK = /export const TOUR_ANCHOR_IDS = \[([\s\S]*?)\]\s*as const/
const anchorBlock = anchorSrc.match(RE_ANCHOR_BLOCK)
const registered = anchorBlock ? [...anchorBlock[1].matchAll(/'([^']+)'/g)].map((m) => m[1]) : []

check(registered.length >= 7, `①a 注册表解析出 ${registered.length} 个锚点 id（期望 ≥ 7）`,
  '解析不到 ⇒ 下面的「每个 id 都有打标」会因为集合为空而恒真（空集上的全称判断）')

// DOM 侧扫描：排除注册表自己（它是真源，不是打标点）
const SCAN_FILES = walk(SRC, ['.vue', '.ts']).filter((p) => p !== ANCHOR_FILE)
const RE_TAG = /data-tour\s*=\s*"([^"]+)"/g
const sites = new Map() // id -> [{file, line}]
for (const f of SCAN_FILES) {
  const clean = stripComments(read(f))
  for (const m of clean.matchAll(RE_TAG)) {
    const id = m[1]
    if (!sites.has(id)) sites.set(id, [])
    sites.get(id).push({ file: rel(f), line: clean.slice(0, m.index).split('\n').length })
  }
}

const totalSites = [...sites.values()].reduce((a, b) => a + b.length, 0)
check(totalSites >= 7, `①b DOM 侧扫到 ${totalSites} 处 data-tour 打标（期望 ≥ 7）`,
  '扫不到东西 ⇒ 要么注释剥离器把真代码吃掉了，要么正则坏了；放任它会产出假 PASS')

check(registered.length === new Set(registered).size,
  '①c 注册表内部无重复 id',
  `实际 ${registered.length} 项 / 去重后 ${new Set(registered).size} 项`)

// ---------------- ② 方向 A：注册了 ⇒ 恰好一处打标 ----------------
for (const id of registered) {
  const hits = sites.get(id) || []
  check(hits.length === 1, `② 注册锚点 ${id} 在 DOM 上恰好 1 处打标（实际 ${hits.length}）`,
    hits.length === 0
      ? '注册了却没打标 ⇒ 引导走到这一步会被静默跳过（选择器返回 null）'
      : `重复宣告 ⇒ ${hits.map((h) => h.file).join(', ')}，两个同 id 元素会让聚光圈高亮到先出现的那个`)
}

// ---------------- ③ 方向 B：标了 ⇒ 必须已注册 ----------------
for (const [id, hits] of sites) {
  check(registered.includes(id), `③ DOM 上的锚点 ${id} 已登记（${hits[0].file}:${hits[0].line}）`,
    '标了没注册 ⇒ 这个位置永远不会被讲到，而代码看起来像是「已经做了引导」')
}

// ---------------- ④ 步骤表的 anchor 必须来自注册表 ----------------
const stepsBlock = stepsSrc.match(/export const TOUR_STEPS[\s\S]*$/)
const stepAnchorList = [...(stepsBlock ? stepsBlock[0].matchAll(/anchor:\s*'([^']+)'/g) : [])].map((m) => m[1])
check(stepAnchorList.length >= 7, `④a 步骤表解析出 ${stepAnchorList.length} 个 anchor（期望 ≥ 7，MVP 一条主线 7 步）`,
  '解析不到 ⇒ ④b 会在空集上恒真')
for (const a of stepAnchorList) {
  check(registered.includes(a), `④b 步骤 anchor '${a}' ∈ 锚点注册表`,
    '步骤自造锚点名 ⇒ 这一步永远找不到目标，且不会被 ②③ 发现')
}

// ---------------- ⑤ 发得出就有人接 ----------------
const PREPARE_EVENT = {
  'ensure-sidebar': 'tour:ensure-sidebar',
  'ensure-right-panel': 'tour:ensure-right-panel',
  'goto-chat': 'view-navigate',
}
const declaredPrepares = [...new Set(
  (stepsBlock ? [...stepsBlock[0].matchAll(/prepare:\s*'([^']+)'/g)] : []).map((m) => m[1]),
)]
check(declaredPrepares.length > 0, `⑤a 步骤表声明了 ${declaredPrepares.length} 种布局准备动作`,
  '一个都没有 ⇒ ⑤b 会在空集上恒真')

for (const p of declaredPrepares) {
  const evt = PREPARE_EVENT[p]
  check(!!evt, `⑤b 准备动作 '${p}' 有已知的事件映射`,
    `未知的 prepare 值 ⇒ TourHost 的 runPrepare 不会为它做任何事（声明了没人执行＝假门禁），
     请先把映射补进 scripts/check-tour-anchors.cjs 的 PREPARE_EVENT`)
  if (!evt) continue
  check(hostSrc.includes(evt), `⑤c TourHost 会发出事件 '${evt}'（prepare: '${p}'）`,
    '宿主没发这个事件 ⇒ 步骤声明的前置准备根本不会发生')
    // ★ 必须钉到 `addEventListener('evt'` 这一**形态**，而不是只要文件里出现过这个字符串：
    //   只判"字符串存在"时，把 mounted 侧的注册摘掉、只留下 removeEventListener 那一行，
    //   门禁照样绿 —— 而事实是命令已经没人执行了。（这条是反向注入抓出来的，见 ⑥）
    const listens = (src, evt) =>
      stripComments(src).includes(`addEventListener('${evt}'`) ||
      stripComments(src).includes(`addEventListener("${evt}"`)
    check(listens(wsSrc, evt), `⑤d Workspace 注册了监听 addEventListener('${evt}')`,
      '发出去没人接 ⇒ 命令是死代码；侧栏不会展开，而引导会以为已经展开了')
}

// ---------------- ⑥ 重播承诺必须成对存在 ----------------
const menuClean = stripComments(menuSrc)
check(menuClean.includes("'tour:replay'") || menuClean.includes('"tour:replay"'),
  '⑥a 账户菜单会发出 tour:replay（界面文案向用户承诺过「随时重看」）',
  '承诺了入口却不存在 ⇒ 用户按引导结束语去菜单里找，找不到（提示要做什么却没给入口）')
const hostClean = stripComments(hostSrc)
// ★ 同样是形态判据：必须真的 `addEventListener('tour:replay'`，
//   判"字符串存在"会让「只留 emits、忘了订阅」这种情况静默过关。
check(hostClean.includes("addEventListener(EVT_REPLAY") ||
      hostClean.includes("addEventListener('tour:replay'"),
  '⑥b TourHost 订阅了 tour:replay',
  '有人发没人听 ⇒ 点了没反应')

// ---------------- ⑦ 全局唯一宿主 ----------------
const appClean = stripComments(appSrc)
const hostMounts = [...appClean.matchAll(/<TourHost\b/g)].length
check(hostMounts === 1, `⑦ App.vue 挂载 <TourHost /> 恰好 1 次（实际 ${hostMounts}）`,
  hostMounts === 0
    ? '没挂 ⇒ 整套引导不会渲染'
    : '挂多次 ⇒ 遮罩与气泡会各画一层，两层 mask 的 id 与 z-index 会互相抢')

// ---------------- ⑧ 语音必须双通道，且降级不许静默 ----------------
//
// ★ 这一组是 r284 补出来的：第一版只做了浏览器原生一条通道，把店里已经 ready 的
//   克隆音色晾在一边。教训是「面向新人的功能，验收者是老板」—— 降级若按最弱目标用户
//   做，老板永远看不到最好的那条路。所以这里钉的是「两条都得在」，不是「哪条更好」。
const narratorClean = stripComments(narratorSrc)
// ★ 形态判据：必须真有**调用**，不是 import 里出现过就算（import 不调 = 没接上）
check(/speakVoice\s*\(/.test(narratorClean), '⑧a 解说层调用了克隆合成 speakVoice()',
  '没有克隆通道 ⇒ 店铺音色永远用不上，语音克隆等于白做，新人听到的是陌生系统音')
// ★ 同理钉到「真的构造了 utterance」这一发声动作，而不是 speechSynthesis 这个字符串
check(narratorClean.includes('new SpeechSynthesisUtterance('),
  '⑧b 解说层保留了浏览器原生兜底（真的构造了 utterance）',
  '没有兜底 ⇒ 新店铺 / 未选店铺 / 合成失败时引导全程哑掉，而引导恰恰是这些人在看')
// 缓存键必须带店铺：同一段文案在不同店铺是**不同的声音**
check(/\$\{shopId\}\|\$\{text\}/.test(narratorClean), '⑧c 克隆音频缓存键含店铺维度',
  '键只按文案 ⇒ 切店铺后复用上一个店合成的音频，界面还写着「你的克隆音色」')
// 降级不许静默：气泡必须把「当前谁在念」显示出来
check(stripComments(tipSrc).includes('channelLabel: string') && tipSrc.includes('v-if="channelLabel"'),
  '⑧d 气泡渲染了 channelLabel（降级时写明是谁在念）',
  '不显示 ⇒ 用户听到陌生嗓门只会以为功能坏了；「静默换声音」是本仓明令禁止的形态')

// ---------------- 判据自检（防恒真 / 恒不匹配）----------------
console.log('  ---- 判据自检 ----')
const SELF = [
  [RE_TAG, '<div data-tour="tour-brand">', 1],
  [RE_TAG, '<div class="x">', 0],
  [RE_TAG, '// <div data-tour="tour-fake">', 1], // 未剥注释前能选到 —— 所以必须剥
  [RE_ANCHOR_BLOCK, 'export const TOUR_ANCHOR_IDS = [\n  \'a\',\n] as const', 1],
  [RE_ANCHOR_BLOCK, 'export const TOUR_ANCHOR_IDS: string[] = []', 0],
]
let selfBad = 0
for (const [re, sample, want] of SELF) {
  const got = [...sample.matchAll(new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g'))].length
  const ok = got === want
  if (!ok) selfBad++
  check(ok, `自检：${JSON.stringify(sample.slice(0, 44))} 命中 ${got} 次（期望 ${want}）`)
}
const stripProbe = stripComments('<!-- data-tour="tour-fake" -->\n<div data-tour="tour-real">')
check(!stripProbe.includes('tour-fake') && stripProbe.includes('tour-real'),
  '自检：HTML 注释里的 data-tour 被剥掉、真标签保留',
  '注释里的旧锚点会骗过判据 ②③，让「集合相等」看起来仍然成立')
const urlProbe = stripComments('const a = "https://x.com/p" // tail')
check(urlProbe.includes('https://x.com/p') && !urlProbe.includes('tail'),
  '自检：剥注释保护 :// 且仍剥得掉行注释',
  '吃掉 URL 会把整行真代码删掉，于是「零命中」可能是假的')
check(selfBad === 0, '自检：全部判据既不是恒真也不是恒不匹配')

console.log('')
if (fails.length) {
  console.log(`RESULT: FAIL（${fails.length} 处）—— 新手引导的锚点/命令已漂移`)
  process.exit(1)
}
console.log(`RESULT: PASS（注册 ${registered.length} / 打标 ${totalSites} 处 / 步骤 ${stepAnchorList.length} / `
  + `准备命令 ${declaredPrepares.length} 组双向有主 / 宿主挂载 1 次）`)
