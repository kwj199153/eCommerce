#!/usr/bin/env node
/**
 * 账号安全前端接线门禁（★ 台账 #1155）
 *
 * ============================================================================
 * 为什么值得单独一个门禁
 * ============================================================================
 * 这次修的缺陷有一个极难被发现的形状：**链路两端都各自正确**。
 *
 *   后端 `core/identity/email_tokens.py::_link("/reset-password", raw)`
 *     ⇒ 邮件正文里的按钮指向 `{PUBLIC_SITE_URL}/reset-password?token=…`
 *   前端 `router/index.ts`
 *     ⇒ 只有 6 条路由，**没有 /reset-password**
 *
 * 结果：用户点开邮件是**空白页**。而这条缺陷——
 *   · `vite build` 不报（前端不知道后端在发什么链接）
 *   · `pytest` 不报（后端不知道前端有哪些路由）
 *   · `vue-tsc` 不报（两边都是合法字符串）
 *   · 单测不报（没有任何一个测试同时看到这两侧）
 * 这正是"必须在**跨文件**维度上钉一条不变量"的典型场景。
 *
 * 本门禁守五条：
 *   ① **邮件链接 ⊆ 前端路由** —— 后端发出去的每个 path，前端必须有页面接
 *      （这条就是本次缺陷的直接判据）
 *   ② **前端 API 路径 ⊆ 后端真实端点** —— 防另一种断链：前端在调一个不存在的 URL
 *      （本仓已有前科：`/users/change-password` 写错成 404 断链）
 *   ③ 两条落地页必须 `requiresAuth: false` 且组件文件真实存在
 *   ④「忘记密码」入口真的会调 API（不是画在页面上的装饰）
 *   ⑤ 注销按钮真的接了线，且文案不再写「其他设备」（后端语义是**含本机**）
 *
 * ★ 为什么用 AST 而不是字符串匹配（第 ③ ⑤ 条）：
 *   本次改动在代码注释里**逐字引用**了旧文案与旧按钮
 *   （"退出所有其他设备" / "本文件此前只有 6 条路由"），
 *   纯字符串扫描会被自己的注释骗到，出现「代码已经改对、门禁反而变红」的假红。
 *
 * 怎么跑：node scripts/check-auth-frontend-wiring.cjs
 *
 * 反向注入（证明本门禁不是空跑）——每个源都可用环境变量改指向副本：
 *   EMAIL_TOKENS_SRC=<副本>   ⇒ 从 email_tokens.py 删掉一条 _link(...)
 *                                ⇒ 「邮件链接 ⊆ 路由」必须变红
 *   ROUTER_SRC=<副本>         ⇒ 把某条落地页的 requiresAuth 改回 true
 *                                ⇒ 第 ③ 条必须变红
 *   SETTINGS_SRC=<副本>       ⇒ 把 handleLogoutAll 改成不调 logoutAll
 *                                ⇒ 第 ⑤ 条必须变红
 *   AUTH_API_SRC=<副本>       ⇒ 把某个 URL 改成一个不存在的端点
 *                                ⇒ 第 ② 条必须变红
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const REPO = path.resolve(ROOT, '..')

const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const EMAIL_TOKENS = pick(
  'EMAIL_TOKENS_SRC',
  path.join(REPO, 'backend', 'core', 'identity', 'email_tokens.py')
)
const SECURITY_ROUTER = pick(
  'SECURITY_ROUTER_SRC',
  path.join(REPO, 'backend', 'core', 'identity', 'security_router.py')
)
const ROUTER = pick('ROUTER_SRC', path.join(ROOT, 'src', 'router', 'index.ts'))
const AUTH_API = pick('AUTH_API_SRC', path.join(ROOT, 'src', 'api', 'auth.ts'))
const LOGIN_VUE = pick('LOGIN_SRC', path.join(ROOT, 'src', 'views', 'Login.vue'))
const SETTINGS_VUE = pick(
  'SETTINGS_SRC',
  path.join(ROOT, 'src', 'views', 'Settings.vue')
)
const POLICY = pick(
  'AUTH_POLICY_SRC',
  path.join(ROOT, 'src', 'api', 'authRefreshPolicy.ts')
)

const ts = require(path.join(ROOT, 'node_modules', 'typescript'))

const results = []
function check(name, fn) {
  try {
    fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
function read(p) {
  return fs.readFileSync(p, 'utf8')
}

// ============================================================
// 抽取（不解析完整语法，只要"声明层"的路径串）
// ============================================================

/** 后端 `_link("/reset-password", raw)` ⇒ ['/reset-password', ...] */
function emailLinkPaths() {
  const body = read(EMAIL_TOKENS)
  return [...body.matchAll(/_link\(\s*"([^"]+)"/g)].map((m) => m[1])
}

/** 后端 `@router.post("/verify-email", ...)` ⇒ ['/verify-email', ...]（补上 /auth 前缀） */
function backendEndpoints() {
  const body = read(SECURITY_ROUTER)
  return [...body.matchAll(/@router\.(?:get|post|put|patch|delete)\(\s*"([^"]+)"/g)].map(
    (m) => '/auth' + m[1]
  )
}

/** 前端 `post<X>('/auth/forgot-password', ...)` ⇒ ['/auth/forgot-password', ...] */
function frontendAuthPaths() {
  const body = read(AUTH_API)
  return [
    ...body.matchAll(/\b(?:get|post|put|patch|del)<[^>]*>\(\s*'([^']+)'/g),
  ].map((m) => m[1])
}

// ============================================================
// AST：读 router/index.ts 的路由表
// ============================================================
function parse(file, kind) {
  return ts.createSourceFile(
    file,
    read(file),
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    kind || ts.ScriptKind.TS
  )
}
function collect(sf, pred) {
  const hits = []
  ;(function walk(node) {
    if (pred(node)) hits.push(node)
    ts.forEachChild(node, walk)
  })(sf)
  return hits
}

function routerRecords() {
  const sf = parse(ROUTER)
  const decl = collect(
    sf,
    (n) => ts.isVariableDeclaration(n) && n.name.getText(sf) === 'routes'
  )[0]
  assert(!!decl, 'router/index.ts 里找不到 `routes` 声明')
  let init = decl.initializer
  while (init && (ts.isAsExpression(init) || ts.isSatisfiesExpression(init))) {
    init = init.expression
  }
  assert(ts.isArrayLiteralExpression(init), '`routes` 不是数组字面量')
  return init.elements.filter(ts.isObjectLiteralExpression).map((o) => {
    const props = {}
    for (const p of o.properties) {
      if (ts.isPropertyAssignment(p)) props[p.name.getText(sf)] = p.initializer
    }
    const str = (n) => (n && ts.isStringLiteral(n) ? n.text : null)
    let requiresAuth = null
    if (props.meta && ts.isObjectLiteralExpression(props.meta)) {
      for (const p of props.meta.properties) {
        if (
          ts.isPropertyAssignment(p) &&
          p.name.getText(sf) === 'requiresAuth'
        ) {
          requiresAuth = p.initializer.kind !== ts.SyntaxKind.FalseKeyword
        }
      }
    }
    return {
      path: str(props.path),
      name: str(props.name),
      component: props.component ? props.component.getText(sf) : null,
      requiresAuth,
    }
  })
}

const EMAIL_PATHS = emailLinkPaths()
const BACKEND_EPS = backendEndpoints()
const FRONTEND_PATHS = frontendAuthPaths()
const RECORDS = routerRecords()
const ROUTE_PATHS = RECORDS.map((r) => r.path).filter(Boolean)

// ============================================================
// [1] 自检：防「什么都没抽到 ⇒ 永远通过」
// ============================================================
console.log('=== 账号安全前端接线门禁 ===')
console.log(
  `邮件链接 ${EMAIL_PATHS.length} 条 | 后端端点 ${BACKEND_EPS.length} 个 | ` +
    `前端 API 路径 ${FRONTEND_PATHS.length} 条 | 路由 ${ROUTE_PATHS.length} 条`
)
console.log()
console.log('[1] 抽取器自检（防空跑）')

check('自检① email_tokens.py 至少抽出 2 条邮件链接', () => {
  assert(
    EMAIL_PATHS.length >= 2,
    `只抽出 ${EMAIL_PATHS.length} 条 —— 抽取器失效或 _link 改了写法`
  )
})
check('自检② security_router.py 至少抽出 5 个端点', () => {
  assert(
    BACKEND_EPS.length >= 5,
    `只抽出 ${BACKEND_EPS.length} 个 —— 抽取器失效或装饰器改了写法`
  )
})
check('自检③ api/auth.ts 至少抽出 5 条路径', () => {
  assert(
    FRONTEND_PATHS.length >= 5,
    `只抽出 ${FRONTEND_PATHS.length} 条 —— 抽取器失效或 post<...> 写法变了`
  )
})
check('自检④ router 至少抽出 8 条路由（含本次两条落地页）', () => {
  assert(
    ROUTE_PATHS.length >= 8,
    `只抽出 ${ROUTE_PATHS.length} 条 —— AST 走空了`
  )
})

// ============================================================
// [2] 核心不变量：邮件链接 ⊆ 前端路由
// ============================================================
console.log()
console.log('[2] 邮件链接 ⊆ 前端路由（本次缺陷的直接判据）')

check('邮件里发出的每个链接，前端都有页面接 ★★★', () => {
  const missing = EMAIL_PATHS.filter((p) => !ROUTE_PATHS.includes(p))
  assert(
    missing.length === 0,
    `后端在往 ${missing.join(', ')} 发链接，但 router/index.ts 里没有这些路由 ` +
      `⇒ 用户点开邮件是空白页（既有路由：${ROUTE_PATHS.join(', ')}）`
  )
})

check('两条落地页都必须 requiresAuth: false ★', () => {
  for (const p of EMAIL_PATHS) {
    const rec = RECORDS.find((r) => r.path === p)
    assert(!!rec, `${p} 没有对应路由记录`)
    assert(
      rec.requiresAuth === false,
      `${p} 的 requiresAuth 不是 false —— 点邮件的人很可能**根本没登录** ` +
        `（忘记密码本身就是"登不上才用"的功能），要求登录会把他弹去登录页，` +
        `而他此刻恰恰进不去`
    )
  }
})

check('落地页的组件文件真实存在', () => {
  for (const p of EMAIL_PATHS) {
    const rec = RECORDS.find((r) => r.path === p)
    const m = (rec.component || '').match(/import\(\s*['"]@\/([^'"]+)['"]/)
    assert(!!m, `${p} 的 component 不是 import('@/...') 形式`)
    const file = path.join(ROOT, 'src', m[1])
    assert(fs.existsSync(file), `${p} 指向的 ${m[1]} 不存在`)
  }
})

// ============================================================
// [3] 前端 API 路径 ⊆ 后端真实端点
// ============================================================
console.log()
console.log('[3] api/auth.ts 的 URL ⊆ security_router.py 的真实端点')

check('前端调用的每个 /auth/* 都真实存在 ★', () => {
  const unknown = FRONTEND_PATHS.filter((p) => !BACKEND_EPS.includes(p))
  assert(
    unknown.length === 0,
    `${unknown.join(', ')} 在后端不存在 ⇒ 又是 /users/change-password 那种 404 断链`
  )
})

check('五个端点一个都不能少（忘记/重置/验证/重发/登出全部）', () => {
  for (const ep of [
    '/auth/forgot-password',
    '/auth/reset-password',
    '/auth/verify-email',
    '/auth/verify-email/resend',
    '/auth/logout-all',
  ]) {
    assert(
      FRONTEND_PATHS.includes(ep),
      `api/auth.ts 缺 ${ep}（既有：${FRONTEND_PATHS.join(', ')}）`
    )
  }
})

// ============================================================
// [4] 入口真的会调 API（不是画在页面上的装饰）
// ============================================================
console.log()
console.log('[4] 入口接线（不是装饰品）')

check('Login.vue 真的调用 forgotPassword ★', () => {
  const body = read(LOGIN_VUE)
  assert(
    /import\s*\{[^}]*\bforgotPassword\b[^}]*\}\s*from\s*'@\/api\/auth'/.test(body),
    'Login.vue 没有从 @/api/auth 导入 forgotPassword'
  )
  const calls = [...body.matchAll(/\bforgotPassword\s*\(/g)].length
  assert(calls >= 1, 'Login.vue 导入了 forgotPassword 但从未调用')
})

check('Login.vue 的「忘记密码」入口在模板里存在', () => {
  const body = read(LOGIN_VUE)
  assert(body.includes('class="forgot-link"'), '找不到 class="forgot-link" 的入口按钮')
  assert(
    /@click="openForgot"/.test(body),
    '忘记密码按钮没有绑定 openForgot —— 点下去不会有任何反应'
  )
})

check('Settings.vue 的注销按钮真的接了线 ★', () => {
  const body = read(SETTINGS_VUE)
  assert(
    /import\s*\{[^}]*\blogoutAll\b[^}]*\}\s*from\s*'@\/api\/auth'/.test(body),
    'Settings.vue 没有从 @/api/auth 导入 logoutAll'
  )
  const calls = [...body.matchAll(/\blogoutAll\s*\(/g)].length
  assert(
    calls >= 1,
    'Settings.vue 导入了 logoutAll 但从未调用 —— 这会让那颗 danger 按钮' +
      '重新变回"点下去什么都不发生"的装饰品'
  )
  assert(
    /@confirm="handleLogoutAll"/.test(body),
    '注销按钮没有绑定 @confirm="handleLogoutAll"'
  )
})

check('注销按钮的文案不得再写「其他设备」★', () => {
  const body = read(SETTINGS_VUE)
  // 只查模板段，避免被注释里"逐字引用旧文案"的那段骗到
  const m = body.match(/<template>([\s\S]*?)<\/template>\s*\n\s*<script/)
  assert(!!m, '找不到 Settings.vue 的 <template> 段')
  const banned = '退出所有其他设备'
  assert(
    !m[1].includes(banned),
    `模板里仍有「${banned}」—— 后端 /auth/logout-all 走 token_version += 1，` +
      `**本机这枚 token 也会失效**。按这句话理解，用户会以为"本机不受影响"，` +
      `结果下一个请求就被踢出去，看起来像"莫名其妙掉线"`
  )
})

// ============================================================
// [5] 401 刷新豁免清单要覆盖新的认证入口
// ============================================================
console.log()
console.log('[5] 401 刷新豁免清单')

check('三个新的认证入口已列入 NO_REFRESH_ENDPOINTS ★', () => {
  const sf = parse(POLICY)
  const decl = collect(
    sf,
    (n) => ts.isVariableDeclaration(n) && n.name.getText(sf) === 'NO_REFRESH_ENDPOINTS'
  )[0]
  assert(!!decl, 'policy 里找不到 NO_REFRESH_ENDPOINTS')
  let init = decl.initializer
  if (ts.isAsExpression(init)) init = init.expression
  const vals = init.elements.filter(ts.isStringLiteral).map((e) => e.text)
  for (const ep of [
    '/auth/forgot-password',
    '/auth/reset-password',
    '/auth/verify-email',
  ]) {
    assert(
      vals.includes(ep),
      `${ep} 未豁免 —— 它的 401 是业务结论（token 无效/过期），` +
        `不是"当前会话该刷新了"的信号（既有：${vals.join(', ')}）`
    )
  }
})

// ===== 输出 =====
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n账号安全前端接线门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  '账号安全前端接线门禁通过（邮件链接有落地页 · API 路径真实存在 · 入口非装饰 ✓）'
)
