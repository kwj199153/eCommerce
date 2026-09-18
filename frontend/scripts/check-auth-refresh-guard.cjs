#!/usr/bin/env node
/**
 * 认证刷新守卫门禁（★ 第 117 轮）
 *
 * 为什么值得单独一个门禁：`api/request.ts` 的 401 分支同时承担三件事 ——
 * 「要不要刷新」「并发下刷几次」「刷新失败往哪走」。这三件事全部**只在异常路径**
 * 生效，正常开发几乎碰不到，所以任何一条被改回去都不会有测试变红，
 * 只会在用户"页面卡住、被踢回登录页"时才暴露。
 *
 * 本门禁守的是四条不变量：
 *   ① 刷新判定**不得按后端文案**（`detail.includes('Token')` 那套必须绝迹）；
 *   ② 判定必须走唯一真源 `shouldAttemptRefresh`，且四个输入一个不能漏；
 *   ③ 认证端点（/auth/refresh 等）必须豁免 —— 这是堵递归刷新的那面墙；
 *   ④ 并发锁与单次重试护栏必须在位。
 *
 * ★ 为什么判定全部走 **AST** 而不是字符串匹配：
 *   修完这个缺陷时，代码注释里会**逐字引用**被禁的那行旧代码
 *   （否则读的人不知道"为什么不能这么写"）。
 *   字符串扫描会被这段注释骗到，出现「代码已经改对、门禁反而变红」的假红。
 *   AST 里根本没有注释节点，从根上免疫。这一条是实测踩出来的，不是预防性设计。
 *
 * 怎么跑：node scripts/check-auth-refresh-guard.cjs
 *
 * 反向注入（证明本门禁不是空跑）：
 *   1) 造一份「去掉认证端点豁免」的 policy 副本 a.ts：
 *        AUTH_POLICY_SRC=a.ts node scripts/check-auth-refresh-guard.cjs
 *      ⇒ 「/auth/refresh ⇒ false」那条必须变红。
 *   2) 造一份「把判定换回猜文案」的 request 副本 b.ts：
 *        REQUEST_SRC=b.ts node scripts/check-auth-refresh-guard.cjs
 *      ⇒ AST 那组必须变红。
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const POLICY = process.env.AUTH_POLICY_SRC
  ? path.resolve(process.env.AUTH_POLICY_SRC)
  : path.join(ROOT, 'src', 'api', 'authRefreshPolicy.ts')
const REQUEST = process.env.REQUEST_SRC
  ? path.resolve(process.env.REQUEST_SRC)
  : path.join(ROOT, 'src', 'api', 'request.ts')
const LOGIN_VUE = process.env.LOGIN_SRC
  ? path.resolve(process.env.LOGIN_SRC)
  : path.join(ROOT, 'src', 'views', 'Login.vue')

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

// ===== 加载被测模块（纯函数，沙箱里直接跑）=====
function loadPolicy() {
  const code = fs.readFileSync(POLICY, 'utf8')
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 },
    fileName: POLICY,
  }).outputText
  const sandbox = {
    module: { exports: {} },
    exports: {},
    // policy 必须是纯函数 + 常量：连 vue / axios 都不该 require
    require: (id) => {
      throw new Error('authRefreshPolicy 必须零运行时依赖，却 require 了: ' + id)
    },
  }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename: POLICY })
  return sandbox.module.exports
}

const P = loadPolicy()

// ===== AST 工具 =====
function parse(file) {
  return ts.createSourceFile(
    file,
    fs.readFileSync(file, 'utf8'),
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    ts.ScriptKind.TS
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

const SF = parse(REQUEST)
const SP = parse(POLICY)
const txt = (n) => n.getText(SF)

// ============================================================
// 第一部分：行为真值表（真跑函数，不看源码）
// ============================================================

const base = { status: 401, url: '/orders', hasRefreshToken: true, alreadyRetried: false }
const cases = [
  ['业务请求 401 + 有 refresh_token ⇒ 必须刷新', { ...base }, true],
  ['认证端点 /auth/refresh ⇒ 绝不刷新（堵递归）★', { ...base, url: '/auth/refresh' }, false],
  ['认证端点 /auth/login ⇒ 绝不刷新', { ...base, url: '/auth/login' }, false],
  ['认证端点 /auth/register ⇒ 绝不刷新', { ...base, url: '/auth/register' }, false],
  ['认证端点 /auth/logout ⇒ 绝不刷新', { ...base, url: '/auth/logout' }, false],
  ['绝对路径 /api/v1/auth/refresh ⇒ 也要豁免', { ...base, url: '/api/v1/auth/refresh' }, false],
  ['带 query 的 /auth/refresh?a=1 ⇒ 也要豁免', { ...base, url: '/auth/refresh?a=1' }, false],
  ['手里没有 refresh_token（演示模式）⇒ 不刷新 ★', { ...base, hasRefreshToken: false }, false],
  ['已经重试过一次仍 401 ⇒ 不再刷新（第二重护栏）★', { ...base, alreadyRetried: true }, false],
  ['非 401（200）⇒ 不刷新', { ...base, status: 200 }, false],
  ['非 401（403）⇒ 不刷新', { ...base, status: 403 }, false],
  ['业务请求带 query 的 401 ⇒ 仍要刷新', { ...base, url: '/orders?page=2' }, true],
]

for (const [name, input, want] of cases) {
  check('真值表 · ' + name, () => {
    const got = P.shouldAttemptRefresh(input)
    assert(got === want, `期望 ${want}，实际 ${got}`)
  })
}

// isAuthEndpoint 自身
check('真值表 · isAuthEndpoint 对空 url / 相似前缀不误判', () => {
  assert(P.isAuthEndpoint(undefined) === false, 'undefined 应为 false')
  assert(P.isAuthEndpoint('') === false, '空串应为 false')
  assert(P.isAuthEndpoint('/auth/refreshx') === false, '/auth/refreshx 不是认证端点')
  assert(P.isAuthEndpoint('/api/v1/auth/refresh') === true, '绝对形式应识别')
  assert(P.isAuthEndpoint('/x/auth/login') === true, '带前缀应识别')
})

check('常量 · 四个认证端点一个都不能少', () => {
  const list = Array.from(P.NO_REFRESH_ENDPOINTS || [])
  for (const ep of ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout']) {
    assert(list.includes(ep), `豁免清单缺 ${ep}（实际：${list.join(', ')}）`)
  }
})

check('常量 · 重试标记名与 request.ts 里用的字面量一致', () => {
  assert(P.AUTH_RETRY_FLAG === '_authRetried', `标记名应为 _authRetried，实际 ${P.AUTH_RETRY_FLAG}`)
})

// ============================================================
// 第二部分：AST 形态断言（守 request.ts 不绕过真源）
// ============================================================

check('AST · request.ts 里不得再按后端文案判定（detail.includes 禁用词）★', () => {
  const BANNED = ['Token', '认证', 'expired', '过期']
  const hits = collect(SF, (n) => {
    if (!ts.isCallExpression(n)) return false
    const callee = n.expression
    if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== 'includes') return false
    return n.arguments.some((a) => ts.isStringLiteral(a) && BANNED.includes(a.text))
  })
  assert(
    hits.length === 0,
    `仍有 ${hits.length} 处按文案判定：` +
      hits.map((h) => `第 ${SF.getLineAndCharacterOfPosition(h.getStart(SF)).line + 1} 行`).join(', ')
  )
})

check('AST · request.ts 必须调用唯一真源 shouldAttemptRefresh', () => {
  const calls = collect(
    SF,
    (n) =>
      ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'shouldAttemptRefresh'
  )
  assert(calls.length === 1, `应恰好 1 处调用，实际 ${calls.length} 处`)
})

check('AST · shouldAttemptRefresh 的四个输入一个都不能漏 ★', () => {
  const call = collect(
    SF,
    (n) =>
      ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'shouldAttemptRefresh'
  )[0]
  assert(!!call, '找不到调用点')
  const arg = call.arguments[0]
  assert(!!arg && ts.isObjectLiteralExpression(arg), '实参必须是对象字面量（显式列出四个事实）')
  const props = {}
  for (const p of arg.properties) {
    // ★ 必须**同时**处理简写属性：调用点写成 `status,`（shorthand）时
    //   节点类型是 ShorthandPropertyAssignment，没有 `.initializer`。
    //   第一版只认 PropertyAssignment，于是把 `status` 误判成"漏传" ——
    //   那是**门禁自己的 bug**，不是代码的 bug。先查根因再改判据，
    //   绝不能因为它变红就去调宽断言。
    if (ts.isPropertyAssignment(p)) {
      props[p.name.getText(SF)] = p.initializer
    } else if (ts.isShorthandPropertyAssignment(p)) {
      props[p.name.getText(SF)] = p.name
    }
  }
  for (const k of ['status', 'url', 'hasRefreshToken', 'alreadyRetried']) {
    assert(!!props[k], `漏传了 ${k} —— 漏 alreadyRetried 会让重试护栏永远失效`)
  }
  // ★ 必须读 store 的 getter，不能图省事直读 localStorage
  const hrt = props.hasRefreshToken.getText(SF)
  assert(
    hrt === 'userStore.hasRefreshToken',
    `hasRefreshToken 必须传 userStore.hasRefreshToken（实际 ${hrt}）—— 直读 localStorage 会让演示模式的 demo 伪凭据去发起注定失败的刷新`
  )
  // ★ 重试标记必须真的从 config 上读
  assert(
    props.alreadyRetried.getText(SF).includes('AUTH_RETRY_FLAG'),
    'alreadyRetried 必须读 config[AUTH_RETRY_FLAG]，否则护栏形同虚设'
  )
})

check('AST · 不得直读 localStorage 拿 refresh_token（应走 store 的内存态）', () => {
  const hits = collect(SF, (n) => {
    if (!ts.isCallExpression(n)) return false
    const callee = n.expression
    return (
      ts.isPropertyAccessExpression(callee) &&
      callee.name.text === 'getItem' &&
      n.arguments.some((a) => ts.isStringLiteral(a) && a.text === 'refresh_token')
    )
  })
  assert(hits.length === 0, `发现 ${hits.length} 处直读 localStorage 的 refresh_token`)
})

check('AST · 并发锁必须在位（变量 + 读 + 释放）★', () => {
  const decl = collect(SF, (n) => ts.isVariableDeclaration(n) && n.name.getText(SF) === 'refreshPromise')
  assert(decl.length === 1, `应有 1 处 refreshPromise 声明，实际 ${decl.length}`)

  // 读：if (refreshPromise) return refreshPromise
  const asGuard = collect(
    SF,
    (n) =>
      ts.isIfStatement(n) &&
      n.expression.getText(SF) === 'refreshPromise' &&
      ts.isReturnStatement(n.thenStatement) &&
      n.thenStatement.expression &&
      n.thenStatement.expression.getText(SF) === 'refreshPromise'
  )
  assert(asGuard.length === 1, '缺少「已有刷新在飞就搭同一班车」的分支（并发锁读端）')

  // 释放：.finally(() => { refreshPromise = null })
  const asRelease = collect(SF, (n) => {
    if (!ts.isCallExpression(n)) return false
    const callee = n.expression
    if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== 'finally') return false
    const cb = n.arguments[0]
    if (!cb || !(ts.isArrowFunction(cb) || ts.isFunctionExpression(cb))) return false
    let found = false
    ;(function w(x) {
      if (
        ts.isBinaryExpression(x) &&
        x.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        x.left.getText(SF) === 'refreshPromise'
      ) {
        found = true
      }
      ts.forEachChild(x, w)
    })(cb.body)
    return found
  })
  assert(asRelease.length === 1, '缺少 finally 里对 refreshPromise 的释放（会让后续刷新永久钉死）')
})

check('AST · 单次重试护栏必须在位（写入 AUTH_RETRY_FLAG）★', () => {
  const writes = collect(
    SF,
    (n) =>
      ts.isBinaryExpression(n) &&
      n.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isElementAccessExpression(n.left) &&
      n.left.argumentExpression.getText(SF) === 'AUTH_RETRY_FLAG'
  )
  assert(writes.length === 1, `应有 1 处 config[AUTH_RETRY_FLAG] = true，实际 ${writes.length} 处`)
  assert(
    writes[0].right.getText(SF) === 'true',
    '重试标记必须置为 true'
  )
})

check('AST · _authRetried 必须在 axios 配置类型里声明（否则 vue-tsc 会红）', () => {
  const sig = collect(SF, (n) => ts.isPropertySignature(n) && n.name.getText(SF) === '_authRetried')
  assert(sig.length === 1, `应恰好 1 处 _authRetried 属性签名，实际 ${sig.length}`)
})

check('AST · 刷新调用必须收口在 refreshOnce 内（全仓只此一处）', () => {
  const calls = collect(SF, (n) => {
    if (!ts.isCallExpression(n)) return false
    const c = n.expression
    return ts.isPropertyAccessExpression(c) && c.name.text === 'refreshToken' && n.arguments.length === 0
  })
  assert(calls.length === 1, `userStore.refreshToken() 应只有 1 处，实际 ${calls.length} 处（多处 = 绕过并发锁）`)
})

check('AST · policy 的豁免清单本身不得为空', () => {
  const decl = collect(
    SP,
    (n) => ts.isVariableDeclaration(n) && n.name.getText(SP) === 'NO_REFRESH_ENDPOINTS'
  )
  assert(decl.length === 1, 'policy 里找不到 NO_REFRESH_ENDPOINTS')
  let init = decl[0].initializer
  if (ts.isAsExpression(init)) init = init.expression
  assert(ts.isArrayLiteralExpression(init), 'NO_REFRESH_ENDPOINTS 必须是数组字面量')
  const vals = init.elements.filter(ts.isStringLiteral).map((e) => e.text)
  assert(vals.length >= 4, `豁免清单至少 4 条，实际 ${vals.length}`)
})

// ============================================================
// 第三部分：成对不变量（防"只改一半"）
//
// ★ 第 117 轮补：认证端点的 401 从会话状态机里**退出来**之后，
//   「谁来解释这类失败」这件事就移交给了调用方。
//   这是一种**成对**关系 —— 只做一半，两种半成品都比原状更糟：
//     · 只短路、不在 Login.vue 补文案 ⇒ 登录失败毫无提示（点一下没反应）
//     · 只在 Login.vue 补文案、不短路 ⇒ 两条提示 + 文案错
//   所以两条断言必须同时在场。
// ============================================================

check('AST · request.ts 必须有「认证端点短路」（401 不再进会话状态机）★', () => {
  const calls = collect(
    SF,
    (n) => ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'isAuthEndpoint'
  )
  assert(
    calls.length >= 1,
    '缺少 isAuthEndpoint 短路 —— 认证端点的 401 会重新被卷进「清状态 + 跳登录」，' +
      '把「密码打错」渲染成「你被踢出去了」'
  )
})

check('AST · Login.vue 的 catch 必须自己给文案（成对不变量）★', () => {
  const v = fs.readFileSync(LOGIN_VUE, 'utf8')
  const m = v.match(/<script[^>]*>([\s\S]*?)<\/script>/)
  assert(!!m, 'Login.vue 里找不到 <script> 块')
  const sf = ts.createSourceFile(LOGIN_VUE, m[1], ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const catches = []
  ;(function w(n) {
    if (ts.isCatchClause(n)) catches.push(n)
    ts.forEachChild(n, w)
  })(sf)
  assert(catches.length >= 2, `登录与注册两处 catch 都应在，实际 ${catches.length}`)
  catches.forEach((c, i) => {
    assert(c.block.statements.length > 0, `第 ${i + 1} 处 catch 是空的 —— 短路之后登录失败将毫无提示`)
    let hasMsg = false
    ;(function w(x) {
      if (
        ts.isCallExpression(x) &&
        ts.isPropertyAccessExpression(x.expression) &&
        x.expression.name.text === 'error' &&
        ts.isIdentifier(x.expression.expression) &&
        x.expression.expression.text === 'message'
      ) {
        hasMsg = true
      }
      ts.forEachChild(x, w)
    })(c.block)
    assert(hasMsg, `第 ${i + 1} 处 catch 必须调用 message.error 把后端 detail 显示出来`)
  })
})

// ===== 输出 =====
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n认证刷新守卫门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log('认证刷新守卫门禁通过（判定不猜文案 · 认证端点豁免 · 并发锁 · 单次护栏 ✓）')
