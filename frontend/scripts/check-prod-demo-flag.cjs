#!/usr/bin/env node
/**
 * 生产构建「演示模式」门禁（第 387 轮 · 网站管理员 P0-1）
 *
 * ═══════════════════════════════════════════════════════════════════════
 *  它防的是哪一个「下一次」
 * ═══════════════════════════════════════════════════════════════════════
 * 事故形态（管理员实测，非推测）：
 *   `.env.production` 里 `VITE_DEMO_MODE=true` ⇒ 构建产物里
 *   `import.meta.env.VITE_DEMO_MODE` 被静态替换成 `"true"` ⇒ 前端在**没有
 *   token** 时自动注入 `demo-token` ⇒ 后端 `AUTH_REQUIRED=true` 且
 *   `DEMO_MODE=false`（生产档 `_enforce_production_safety` 强制如此）
 *   ⇒ **每个请求 401**。
 *
 *   界面表现：**页面能开、数据全空**。没有报错弹窗、没有 500、服务端日志
 *   只有一片 401 —— 归因方向会被带到「后端挂了 / 数据库空了」。
 *
 * 为什么必须做成门禁而不是改完了事：
 *   构建期变量是**编译进包**的。有人临时 `VITE_DEMO_MODE=false npm run build`
 *   能救一次部署，但下一次**任何**正常构建（`npm run build`、桌面壳的
 *   `beforeBuildCommand`、CI）都会把 `true` 编回去 —— 而这个「下一次」
 *   不会有人记得。⇒ 判据必须落在**文件**上，且必须在构建链里。
 *
 *   ★ 因此本门禁**刻意不看** `process.env.VITE_DEMO_MODE`：shell 覆盖只能
 *     掩盖问题（构建那一刻是对的，源文件仍然是错的）。要看的是"下次再来
 *     一遍会怎样"。
 *
 * ═══════════════════════════════════════════════════════════════════════
 *  三条判据
 * ═══════════════════════════════════════════════════════════════════════
 *  ① 任何被 Vite 读到的 env 文件都不得把 `VITE_DEMO_MODE` 设为 true。
 *     检查范围按 **Vite 的加载优先级**取全部三份，不是只看 `.env.production`：
 *     `.env.production.local` > `.env.production` > `.env`
 *     只查其中一份的话，往 `.env` 里塞一行就能绕过（且完全合法地生效）。
 *  ② `src/config/demoMode.ts` 的默认必须是 **fail-closed**：
 *     `import.meta.env.VITE_DEMO_MODE === 'true'`。
 *     判据走 AST（不是字符串包含）—— 该文件的注释里本来就写着
 *     `VITE_DEMO_MODE=true` 这类字样，字符串扫描会把注释算进去，
 *     于是"代码是对的、门禁是红的"。
 *  ③ 本门禁必须真的挂在 `package.json` 的 `build` 链里。
 *     一条没进构建链的门禁 = 一条不存在的门禁（本仓反复踩过：条件挂载 /
 *     忘了串进去，跑起来一片绿）。
 *
 * 怎么跑：node scripts/check-prod-demo-flag.cjs
 * 反向注入：ENV_PROD=<临时文件> node scripts/check-prod-demo-flag.cjs   （应 exit 1）
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, rel) => (process.env[env] ? path.resolve(process.env[env]) : path.join(ROOT, ...rel))

// Vite 的加载顺序（后者被前者覆盖）：越高优先级越靠前。
const ENV_FILES = [
  pick('ENV_PROD_LOCAL', ['.env.production.local']),
  pick('ENV_PROD', ['.env.production']),
  pick('ENV_BASE', ['.env']),
]
const DEMO_SRC = pick('DEMO_MODE_SRC', ['src', 'config', 'demoMode.ts'])
const PKG = pick('PACKAGE_JSON', ['package.json'])

const failures = []
const notes = []

function fail(msg) {
  failures.push(msg)
}

/** 极小的 `KEY=VALUE` 解析（够用即可，不引 dotenv：门禁不该有自己的依赖树）。 */
function parseEnv(text) {
  const out = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    let val = line.slice(eq + 1).trim()
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1)
    }
    out[key] = val
  }
  return out
}

/** ① 三份 env 文件逐一检查 */
function checkEnvFiles() {
  let scanned = 0
  for (const file of ENV_FILES) {
    if (!fs.existsSync(file)) continue
    scanned += 1
    const rel = path.relative(ROOT, file) || file
    const env = parseEnv(fs.readFileSync(file, 'utf8'))
    if (!('VITE_DEMO_MODE' in env)) {
      // 未设置 = 关闭（fail-closed），合法。只记一条便于排查的说明。
      notes.push(`${rel}: 未设置 VITE_DEMO_MODE（按 fail-closed 视为关闭）`)
      continue
    }
    if (String(env.VITE_DEMO_MODE).toLowerCase() === 'true') {
      fail(
        `${rel}: VITE_DEMO_MODE=true —— 生产构建会注入 demo-token，` +
          `后端 AUTH_REQUIRED=true 时全站 401（现象：页面能开、数据全空）。` +
          `请改为 false 或删掉该行。`,
      )
    }
  }
  if (scanned === 0) {
    // 一个 env 文件都没有：默认关闭，合法；但要说出来（否则"没扫到"会被读成"通过"）。
    notes.push('未找到任何 .env* 文件（默认关闭，合法）')
  }
}

/** ② demoMode.ts 的默认必须 fail-closed —— 走 AST，免疫注释 */
function checkFailClosedDefault() {
  if (!fs.existsSync(DEMO_SRC)) {
    fail(`找不到 ${path.relative(ROOT, DEMO_SRC)} —— 演示模式的唯一真源不见了，判据无法落地`)
    return
  }
  let ts
  try {
    ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  } catch {
    fail('缺少 typescript 依赖，无法做 AST 判据（不允许退化成字符串扫描）')
    return
  }
  const src = fs.readFileSync(DEMO_SRC, 'utf8')
  const sf = ts.createSourceFile(DEMO_SRC, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)

  const norm = (s) => s.replace(/\s+/g, ' ').trim()
  let found = null
  const visit = (node) => {
    if (
      ts.isVariableDeclaration(node) &&
      node.name &&
      node.name.getText(sf) === 'DEMO_MODE' &&
      node.initializer
    ) {
      found = norm(node.initializer.getText(sf))
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)

  if (found === null) {
    fail('demoMode.ts 里找不到 `DEMO_MODE` 的初始化表达式（判据无法落地，不许静默放过）')
    return
  }
  // 唯一的合法形态：显式与字符串 'true' 比较 ⇒ 未设置/其它值一律关闭。
  const EXPECT = "import.meta.env.VITE_DEMO_MODE === 'true'"
  if (found !== EXPECT) {
    fail(
      `DEMO_MODE 的默认不再是 fail-closed：\n` +
        `      实际 = ${found}\n` +
        `      期望 = ${EXPECT}\n` +
        `    「未设置即演示模式」会让漏配一个环境变量就把鉴权整个旁路掉（且无任何报错）。`,
    )
  }
}

/** ③ 门禁必须真的在 build 链里 */
function checkWiredIntoBuild() {
  if (!fs.existsSync(PKG)) {
    fail('找不到 package.json，无法确认本门禁是否被串进构建链')
    return
  }
  let pkg
  try {
    pkg = JSON.parse(fs.readFileSync(PKG, 'utf8'))
  } catch (e) {
    fail(`package.json 解析失败：${e.message}`)
    return
  }
  const build = (pkg.scripts && pkg.scripts.build) || ''
  if (!build.includes('check-prod-demo-flag.cjs')) {
    fail(
      'scripts.build 里没有 check-prod-demo-flag.cjs —— ' +
        '没进构建链的门禁等于不存在（构建不会因它变红）。',
    )
  }
}

function main() {
  checkEnvFiles()
  checkFailClosedDefault()
  checkWiredIntoBuild()

  for (const n of notes) console.log(`  · ${n}`)

  if (failures.length) {
    console.error('\n✗ 生产构建演示模式门禁未通过：\n')
    for (const f of failures) console.error(`  - ${f}`)
    console.error(
      '\n  背景：构建期变量是**编译进包**的。改完必须**重建产物**才生效；' +
        '只改源码/只重启后端都不会改变产物里的那个值。\n',
    )
    process.exit(1)
  }
  console.log('✓ 生产构建演示模式门禁通过（env 文件未开启 demo、默认 fail-closed、已挂在 build 链上）')
}

main()
