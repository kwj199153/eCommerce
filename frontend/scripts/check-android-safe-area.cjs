#!/usr/bin/env node
/**
 * Android 安全区门禁（零依赖 · 只读源码 · 不起服务 · 不需要真机）
 * ============================================================================
 * 为什么需要它
 * ============================================================================
 * 第 384 轮真机（MRX-AL09 · 横屏 2560×1600 · density 2.5）实测：
 *
 *   系统状态栏 `ITYPE_STATUS_BAR frame=[0,0][2560,80]` ⇒ **80 物理 px = 32 CSS px**；
 *   工作台顶部折叠按钮中心在 **y=72px** ⇒ 整个按钮落在状态栏带内，
 *   `adb shell input tap` 会被系统直接吃掉（点不开侧栏）。**每个 agent 的对话区顶部
 *   都有这一条 header**，所以是「所有 agent 一起重叠」，不是某页的偶发。
 *
 * 根因不是 CSS 写错：`styles/safe-area.css` 的消费端早就写好了（`.workspace-container`
 * 与 `.login-container` 都 `padding-top: var(--sat)`），但 **`--sat` 恒为 `0px`** ——
 * 因为整个链路里**没人给它赋过值**。值必须由壳推：`MainActivity.kt` 的
 * `onWebViewCreate` → `addDocumentStartJavaScript` 注入 `__ECOM_APPLY_INSETS__`。
 * （`env(safe-area-inset-*)` 在 Android WebView 里恒为 `0px`，不是可选方案。）
 *
 * ★★★ 这类缺陷为什么必须有静态门禁 —— 三个"永远不报错"的叠加：
 *   1. `gen/` 目录**被 .gitignore 忽略** ⇒ 补丁物不在版本库里，
 *      `tauri android init` 一跑就把 `MainActivity.kt` 覆盖回模板，**git status 干净**；
 *   2. CSS 变量**没有默认值也能跑**（`var(--sat)` 解析失败就是 initial），
 *      页面照常渲染，只是内容顶到状态栏底下；
 *   3. 桌面端 / Web 端**不经过 MainActivity** ⇒ 所有浏览器里的检查都绿。
 *   ⇒ 唯一能提前发现的时机，就是"构建前读一眼这两个文件的形态对得上"。
 *
 * 判据设计口径（照本仓既有铁律）
 * ============================================================================
 *   · **一律剥注释**再判：Kotlin 与 CSS 里都写了大量"为什么"的注释，
 *     里面故意留着 `--sat` / `__ECOM_APPLY_INSETS__` 这些串（含本文件头）。
 *     不剥 ⇒ 判据恒真 ⇒ 空跑。
 *   · **两边对账，不只判存在**：A4 从 `safe-area.css` 里**现取**实际被消费的
 *     变量名集合，与 Kotlin `setProperty` 的集合**双向比对**。
 *     只判"Kotlin 里有 --sat"防不住"CSS 改用 --safe-top、Kotlin 还推 --sat"
 *     这种**改名型**静默失效（页面不报错，只是不让位）。
 *   · **环境缺失判 SKIP 不判 FAIL**：`gen/android` 被 gitignore，
 *     别人 clone 后没有它 ⇒ 整组 Android 判据 SKIP（并**打印原因**），
 *     前端侧 A6/A7 仍照跑。
 *   · 每条判据都做过反向注入（见 `.workbuddy/probes/mutate-android-safe-area.cjs`）。
 *
 * 对照真源：eEducation `MainActivity.kt` 第 489 轮（同一套形态，同机实测过）。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const SRC = {
  mainActivity: pick(
    'ANDROID_MAIN_ACTIVITY_SRC',
    path.join(
      ROOT,
      '..',
      'desktop',
      'src-tauri',
      'gen',
      'android',
      'app',
      'src',
      'main',
      'java',
      'cn',
      'shopbutler',
      'desktop',
      'MainActivity.kt',
    ),
  ),
  safeAreaCss: pick(
    'SAFE_AREA_CSS_SRC',
    path.join(ROOT, 'src', 'styles', 'safe-area.css'),
  ),
  mainTs: pick('MAIN_TS_SRC', path.join(ROOT, 'src', 'main.ts')),
}

const read = (p) => fs.readFileSync(p, 'utf8')
const exists = (p) => fs.existsSync(p)

/**
 * 剥注释（判据铁律：注释会骗过字符串判据）。
 * ★ 顺序有关：先 `<!-- -->`（Vue/HTML），再块注释，最后行注释。
 * ★ 行注释的正则带 `[^:]` 前置守卫，否则会吃掉 `https://` 与 `http://`。
 * ★ Kotlin 的三引号模板串里若出现 `//` 会被误剥 —— 本文件判的串里没有斜杠，安全。
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 取 `--sat` 形态的 CSS 变量名，返回去重数组（保留出现顺序） */
function cssVarsUsedBy(src) {
  const out = []
  const re = /var\(\s*(--s[a-z]{2})\b/g
  let m
  while ((m = re.exec(src))) if (!out.includes(m[1])) out.push(m[1])
  return out
}

/* ------------------------------------------------------------------ 期望值 */
/**
 * 消费端必须覆盖的两个根容器。
 * ★ 为什么是这两个：登录页是**独立于工作台**的另一棵树（不在 `.workspace-container`
 *   里面），只给工作台让位 ⇒ 登录页顶部仍被状态栏压住（登录按钮 / 品牌标题都在那）。
 *   eEducation 同样两处都写。
 */
const REQUIRED_CONSUMERS = [
  { name: '.workspace-container', re: /\.workspace-container\s*\{[^}]*padding-top:\s*var\(--sat\)/ },
  { name: '.login-container', re: /\.login-container\s*\{[^}]*padding-top:\s*var\(--sat\)/ },
]

/* ------------------------------------------------------------------ 执行 */
let failed = 0
let skipped = 0
const results = []
function check(id, desc, ok, detail) {
  results.push({ id, desc, ok, detail })
  if (!ok) failed++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${id.padEnd(4)} ${desc}`)
  if (!ok && detail !== undefined) {
    console.log(`        ↳ ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
  }
}
function skip(id, desc, why) {
  skipped++
  console.log(`  SKIP  ${id.padEnd(4)} ${desc}`)
  console.log(`        ↳ ${why}`)
}

console.log('=== Android 安全区（edge-to-edge inset 下发） ===')

const hasGen = exists(SRC.mainActivity)
const ktRaw = hasGen ? read(SRC.mainActivity) : ''
const kt = stripComments(ktRaw)

if (!hasGen) {
  for (const id of ['A1', 'A2', 'A3', 'A4', 'A5']) {
    skip(id, '壳侧 inset 下发', 'desktop/src-tauri/gen/ 未生成（被 gitignore）⇒ 本机未跑过 tauri android init')
  }
} else {
  /* A1 —— 补丁本体在：注入函数 + 调用处。
     ★ 判据写法：`window.__ECOM_APPLY_INSETS__ = function` 是**定义**，
       `__ECOM_APPLY_INSETS__&&` 是**调用**。两处都要有 ——
       只定义不调用 = 函数常驻但永不赋值，页面照样 --sat: 0（**静默无效**）。 */
  const hasDefine = /window\.__ECOM_APPLY_INSETS__\s*=\s*function/.test(kt)
  // ★ 调用形态是 `__X__&&window.__X__(` —— 中间那个 `window.` 不能写死成可选，
  //   但也不能漏（第一版就是漏了它，判据自己报了个假红）。
  const hasCall = /__ECOM_APPLY_INSETS__\s*&&\s*(?:window\.)?__ECOM_APPLY_INSETS__\s*\(/.test(kt)
  check(
    'A1',
    'MainActivity 有 inset bridge（定义 + 调用两处齐全）',
    hasDefine && hasCall,
    `define=${hasDefine} call=${hasCall}（只定义不调用 ⇒ 变量永远拿不到值）`,
  )

  /* A2 —— 挂在 WebView 创建回调上，而不是 onCreate。
     ★ onCreate 里拿不到 WebView 实例（Tauri 的 TauriActivity 在 super.onCreate 之后才建）；
       写在那里等于没有。 */
  const onWebViewCreate = /override\s+fun\s+onWebViewCreate\s*\(/.test(kt)
  const installsThere = /onWebViewCreate[\s\S]{0,600}installInsetBridge\s*\(/.test(kt)
  check(
    'A2',
    'bridge 挂在 onWebViewCreate 上（那里才拿得到 WebView）',
    onWebViewCreate && installsThere,
    `override=${onWebViewCreate} 调用点在回调内=${installsThere}`,
  )

  /* A3 —— 每个新文档都注入（导航后不丢）。
     ★ 只写 `evaluateJavascript` ⇒ 首次文档有效、页面一跳就没了；
       而 Tauri 的 SPA 在登录成功后会真导航一次（`/` 换 origin 或 reload），
       症状是"首页好了，进工作台又压状态栏"。 */
  const docStart = /addDocumentStartJavaScript\s*\(/.test(kt)
  const hasFallback = /WebViewFeature\.isFeatureSupported[\s\S]{0,200}evaluateJavascript/.test(kt)
  check(
    'A3',
    '用 addDocumentStartJavaScript（每文档注入）+ 老 WebView 有降级分支',
    docStart && hasFallback,
    `docStart=${docStart} fallback=${hasFallback}`,
  )

  /* A4 —— ★★ 跨文件对账：CSS 实际消费的变量 ↔ Kotlin 实际推送的变量。
     ★ 这一条是本门禁的核心：它防的是**改名型**静默失效。 */
  const cssRaw = exists(SRC.safeAreaCss) ? read(SRC.safeAreaCss) : ''
  const cssVars = cssVarsUsedBy(stripComments(cssRaw))
  const pushed = []
  {
    const re = /setProperty\(\s*'(--s[a-z]{2})'/g
    let m
    while ((m = re.exec(kt))) if (!pushed.includes(m[1])) pushed.push(m[1])
  }
  const missing = cssVars.filter((v) => !pushed.includes(v))
  const unused = pushed.filter((v) => !cssVars.includes(v))
  check(
    'A4',
    'CSS 消费的变量集合 ＝ Kotlin 推送的变量集合（双向）',
    cssVars.length > 0 && missing.length === 0 && unused.length === 0,
    {
      css_consumes: cssVars,
      kotlin_pushes: pushed,
      css有但没推: missing,
      kotlin推了但没人用: unused,
    },
  )

  /* A5 —— 物理像素 → CSS px 必须除以 density。
     ★ 忘了除就是 2.5 倍留白（本机 density 2.5），"看起来只是有点大"，
       没有绝对值可比 ⇒ 极难归因。 */
  const divides = /bars?\.top\s*\/\s*d\b|\$\{top\s*\/\s*d\}/.test(kt)
  const hasDensity = /displayMetrics\.density/.test(kt)
  check(
    'A5',
    'inset 按 displayMetrics.density 换算成 CSS px',
    divides && hasDensity,
    `density=${hasDensity} 除法=${divides}`,
  )
}

/* A6 —— CSS 被入口导入（否则整份文件是死代码，`--sat` 根本没规则消费） */
const mainTs = exists(SRC.mainTs) ? stripComments(read(SRC.mainTs)) : ''
check(
  'A6',
  'main.ts 导入了 styles/safe-area.css',
  /import\s+['"][^'"]*safe-area\.css['"]/.test(mainTs),
  '没有 import ⇒ 下面所有 var(--sat) 都不存在，页面照旧顶到状态栏',
)

/* A7 —— 两个根容器都真的消费（防"删了某一段"） */
{
  const css = stripComments(exists(SRC.safeAreaCss) ? read(SRC.safeAreaCss) : '')
  const lost = REQUIRED_CONSUMERS.filter((c) => !c.re.test(css)).map((c) => c.name)
  check(
    'A7',
    '工作台 / 登录页两个根容器都有 padding-top: var(--sat)',
    css.length > 0 && lost.length === 0,
    `缺：${lost.join(' / ') || '(无)'}`,
  )
}

/* ------------------------------------------------------------------ 汇总 */
console.log()
const pass = results.filter((r) => r.ok).length
const tail = skipped ? `（另有 ${skipped} 条 SKIP）` : ''
console.log(`=== 汇总：${pass} PASS / ${failed} FAIL${tail} ===`)
if (failed) {
  console.log(
    'RESULT: FAIL —— 壳的 inset 下发与页面的安全区消费对不上。\n' +
      '        典型原因：`tauri android init` 把 MainActivity.kt 覆盖回模板（gen/ 被 gitignore，\n' +
      '        git status 看不出来）⇒ 按 desktop/README.md「Android 安全区补丁」一节重打。',
  )
  process.exit(1)
}
console.log('RESULT: OK')
