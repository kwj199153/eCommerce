#!/usr/bin/env node
/**
 * 凭据仓库门禁 **v2**（★ 第 119 轮重写；v1 见 git 历史）
 *
 * ═══════════════════════════════════════════════════════════════════════
 *  v1 → v2 到底改了什么
 * ═══════════════════════════════════════════════════════════════════════
 * v1 守的是「localStorage 里那个凭据仓库」：写入点封闭、登出要删、
 * 切换不许撤销。第 119 轮把凭据**整体搬去服务端加密托管**
 * （Fernet + Redis，浏览器只剩 httpOnly Cookie 里的 device_id），
 * 于是前端这一侧的目标从「管好那个仓库」变成了**「证明这里没有仓库」**。
 *
 * v2 的四条不变量：
 *   ① 本机索引里**只有 user_id**：任何位置都读不出、写不进 token；
 *   ② v1 遗留键 `auth_credentials`（里面是**明文** refresh token）
 *      必须被主动清除 —— 只"不再写"不够，旧的明文会一直留到过期；
 *   ③ 前端**不再判断凭据是否有效**：那是服务端的唯一真源
 *      （`core/identity/device_router.py` 逐条复刻了 `/auth/refresh` 的四道门）。
 *      前端若也判一遍，就是两份实现，必然漂移且必有一份测不到；
 *   ④ 老规矩不变：切换**不得撤销**当前账号；撤销只发生在「退出登录」。
 *
 * ═══════════════════════════════════════════════════════════════════════
 *  为什么关键断言必须走 AST 而不是字符串扫描
 * ═══════════════════════════════════════════════════════════════════════
 * 两处**实测**会绊倒字符串扫描的地方（都在本仓真实存在）：
 *   · `config/authVault.ts` 的注释里逐字写着 `` POST /auth/device/forget ``
 *     —— 而门禁要断言「`/auth/device/*` 只被 stores/user.ts 调用」。
 *     字符串扫描会把注释也算成调用点，于是"代码是对的、门禁是红的"。
 *   · 解释"为什么不能 revoke"的注释里必然出现 `revoke` 这个词。
 * TS 的 AST 里**没有注释节点**，从根上免疫。
 *
 * 怎么跑：node scripts/check-auth-vault.cjs
 *
 * 反向注入（证明本门禁不是空跑）：
 *   VAULT_SRC=… USER_SRC=… MENU_SRC=… POLICY_SRC=… node scripts/check-auth-vault.cjs
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, rel) =>
  process.env[env] ? path.resolve(process.env[env]) : path.join(ROOT, ...rel)

const VAULT = pick('VAULT_SRC', ['src', 'config', 'authVault.ts'])
const USER = pick('USER_SRC', ['src', 'stores', 'user.ts'])
const MENU = pick('MENU_SRC', ['src', 'components', 'Sidebar', 'AccountMenu.vue'])
const LOGIN = pick('LOGIN_SRC', ['src', 'views', 'Login.vue'])
const POLICY = pick('POLICY_SRC', ['src', 'api', 'authRefreshPolicy.ts'])
// ★ `SRC_DIR` 让「全仓扫描」类断言也能在**临时副本**上做反向注入 ——
//   不必为了证明门禁会红而往真仓库里塞一行坏代码（第 119 轮加固）。
const SRC = process.env.SRC_DIR ? path.resolve(process.env.SRC_DIR) : path.join(ROOT, 'src')

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

// =====================================================================
// 共用定义
// =====================================================================
/** JWT 形态：header.payload 至少各有一段 base64url（header 必以 eyJ 开头） */
const JWT_RE = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/

/** 索引模块里**绝不允许**出现的标识符片段 */
const BANNED_IDENT_PIECES = ['refresh_token', 'access_token', 'refreshtoken', 'accesstoken']
const BANNED_IDENT_RE = /(password|passwd|pwd)/

/** v1 用过的本地键（明文 refresh token 的所在处） */
const LEGACY_KEY = 'auth_credentials'
/** v2 的索引键 */
const INDEX_KEY = 'auth_remembered_accounts'

const DEVICE_ENDPOINTS = [
  '/auth/device/enroll',
  '/auth/device/accounts',
  '/auth/device/switch',
  '/auth/device/forget',
  '/auth/device/forget-all',
]

// =====================================================================
// 沙箱：把 authVault.ts 真跑起来（vue 用 stub，localStorage 用内存 Map）
// =====================================================================
function makeStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => void m.set(k, String(v)),
    removeItem: (k) => void m.delete(k),
    clear: () => m.clear(),
    _raw: m,
  }
}

/**
 * @param {Record<string,string>} preSeed 载入模块**之前**预置的 localStorage 内容
 *        （用来模拟"升级前用过 v1 的浏览器"）
 */
function loadVault(preSeed) {
  const code = fs.readFileSync(VAULT, 'utf8')
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 },
    fileName: VAULT,
  }).outputText

  const storage = makeStorage()
  if (preSeed) for (const k of Object.keys(preSeed)) storage.setItem(k, preSeed[k])

  const sandbox = {
    module: { exports: {} },
    exports: {},
    localStorage: storage,
    console,
    Date,
    Number,
    JSON,
    Array,
    Object,
    String,
    Set,
    require: (id) => {
      if (id === 'vue') {
        return {
          ref: (v) => ({ value: v }),
          computed: (fn) => ({ get value() { return fn() } }),
          watch: () => {},
        }
      }
      throw new Error('本机索引模块只允许依赖 vue（且仅 ref/computed），却 require 了: ' + id)
    },
  }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename: VAULT })
  return { m: sandbox.module.exports, storage }
}

// =====================================================================
// AST helpers
// =====================================================================
function parseTs(src, name) {
  return ts.createSourceFile(name, src, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS)
}

/** 从 .vue 里抠出 <script> 块（正则只用于**提取**，不用于删替） */
function scriptOfVue(src) {
  const m = String(src).match(/<script[^>]*>([\s\S]*?)<\/script>/)
  return m ? m[1] : ''
}

/**
 * 从 .vue 里抠出 <template> 块。
 *
 * ★★★ 为什么必须单独处理 template（第 118 轮反向注入实测踩到）：
 *   `@click="goLoginPage({ revoke: true })"` 这种写法**不在 `<script>` 里**，
 *   只解析 script 的 AST 门禁对它**完全是瞎的**。凡断言「某个调用只出现在某处」
 *   的门禁，都要问一句：这个调用会不会出现在 template 里？那里 AST 看不见。
 */
function templateOfVue(src) {
  const m = String(src).match(/<template>([\s\S]*)<\/template>/)
  return m ? m[1] : ''
}

/** 把 template 里所有事件绑定的表达式抠出来，拼成一段可解析的 TS */
function templateHandlers(src) {
  const tpl = templateOfVue(src)
  const out = []
  const re = /(?:@[\w.:-]+|v-on:[\w.:-]+)="([^"]*)"/g
  let m
  while ((m = re.exec(tpl))) out.push(m[1])
  return out.join('\n')
}

function walk(node, visit) {
  visit(node)
  ts.forEachChild(node, (c) => walk(c, visit))
}

/** 收集所有函数节点（函数声明 + 箭头函数 / 函数表达式赋给变量） */
function collectFns(sf) {
  const out = {}
  walk(sf, (n) => {
    if (ts.isFunctionDeclaration(n) && n.name) {
      out[n.name.getText(sf)] = n
    } else if (
      ts.isVariableDeclaration(n) &&
      ts.isIdentifier(n.name) &&
      n.initializer &&
      (ts.isArrowFunction(n.initializer) || ts.isFunctionExpression(n.initializer))
    ) {
      out[n.name.getText(sf)] = n.initializer
    }
  })
  return out
}

/** 收集某个节点范围内的所有调用 */
function callsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isCallExpression(n)) {
      out.push({
        callee: n.expression.getText(sf),
        args: n.arguments.map((a) => a.getText(sf)),
        pos: n.getStart(sf),
      })
    }
  })
  return out
}

function allCalls(sf) {
  return callsIn(sf, sf)
}

/** 收集文件里所有字符串字面量 + 标识符名（AST，看不到注释） */
function allNames(sf) {
  const out = []
  walk(sf, (n) => {
    if (ts.isStringLiteral(n)) out.push(n.text)
    else if (ts.isIdentifier(n)) out.push(n.text)
    else if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name)) out.push(n.name.getText(sf))
  })
  return out
}

/** 只要字符串字面量（含模板串的无插值片段） */
function allStringLiterals(sf) {
  const out = []
  walk(sf, (n) => {
    if (ts.isStringLiteral(n)) out.push(n.text)
    else if (ts.isNoSubstitutionTemplateLiteral(n)) out.push(n.text)
  })
  return out
}

/** 递归收集 src 下的源码文件 */
function collectSrcFiles(dir) {
  const out = []
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) out.push(...collectSrcFiles(p))
    else if (/\.(ts|tsx|vue|js|mjs|cjs)$/.test(e.name)) out.push(p)
  }
  return out
}

function parseAnyFile(file) {
  const raw = fs.readFileSync(file, 'utf8')
  const code = file.endsWith('.vue') ? scriptOfVue(raw) : raw
  if (!code.trim()) return null
  return parseTs(code, file)
}

// =====================================================================
// 第一部分 · 行为真值表（跑的是真源码，不是复刻）
// =====================================================================
check('行为 · 模块加载即清掉 v1 遗留的明文凭据键', () => {
  const { storage } = loadVault({
    [LEGACY_KEY]: JSON.stringify([
      { user_id: 'u-old', email: 'o@b.c', refresh_token: 'eyJhbGciOiJIUzI1NiJ9.PLAINTEXT_LEAK', saved_at: '2026-09-01' },
    ]),
  })
  assert(
    storage.getItem(LEGACY_KEY) === null,
    LEGACY_KEY + ' 必须被**主动删除** —— 只"不再写"是不够的：升级前用过的人，'
    + 'localStorage 里那串明文会一直留到过期（7 天），期间它照样能被抄走并用；'
    + '而用户看不到任何提示，也不知道要手动清'
  )
})

check('行为 · 遗留键名常量与 v1 逐字一致（写错就等于没清）', () => {
  const { m } = loadVault()
  assert(Array.isArray(m.AUTH_VAULT_LEGACY_KEYS), 'AUTH_VAULT_LEGACY_KEYS 必须是数组')
  assert(
    m.AUTH_VAULT_LEGACY_KEYS.includes(LEGACY_KEY),
    'v1 用的键名就是 ' + LEGACY_KEY + '；常量写错＝那条明文永远清不掉。实测: '
    + JSON.stringify(m.AUTH_VAULT_LEGACY_KEYS)
  )
})

check('行为 · 索引键名固定（改名会让已记住的账号静默失联）', () => {
  const { m } = loadVault()
  assert(
    m.AUTH_VAULT_STORAGE_KEY === INDEX_KEY,
    '索引键应为 ' + INDEX_KEY + '，实测 ' + String(m.AUTH_VAULT_STORAGE_KEY)
  )
})

check('行为 · v1 形状脏数据不得被继承（对象元素里带着凭据）', () => {
  const { storage } = loadVault({
    [INDEX_KEY]: JSON.stringify([
      { user_id: 'u-dirty', email: 'd@b.c', refresh_token: 'eyJhbGciOiJIUzI1NiJ9.SHOULD_NOT_SURVIVE' },
      'u-clean',
    ]),
  })
  const raw = storage.getItem(INDEX_KEY) || ''
  assert(
    raw.indexOf('refresh_token') === -1 && raw.indexOf('SHOULD_NOT_SURVIVE') === -1,
    'v1 的索引元素是对象、里面带着凭据；新代码必须**整体丢弃**这类元素，'
    + '而不是"尽力解析出 user_id"—— 留下它的任何一部分，都会让'
    + '「本模块不持有凭据」这条不变量出现例外。实测落盘内容: ' + raw
  )
  assert(
    JSON.stringify(JSON.parse(raw)) === JSON.stringify(['u-clean']),
    '只有字符串元素该被保留，实测: ' + raw
  )
})

check('行为 · 索引只存 user_id，且写不出任何 token 形态串', () => {
  const { m, storage } = loadVault()
  m.setRemembered(['u-a', 'u-b'])
  const raw = storage.getItem(INDEX_KEY) || ''
  assert(JSON.stringify(JSON.parse(raw)) === JSON.stringify(['u-a', 'u-b']), '落盘形状应为纯 string[]，实测 ' + raw)
  for (const bad of BANNED_IDENT_PIECES.concat(['eyJ'])) {
    assert(raw.toLowerCase().indexOf(bad) === -1, '索引内容里出现了 ' + bad + '：' + raw)
  }
  assert(!JWT_RE.test(raw), '索引内容里出现了 JWT 形态串：' + raw)
})

check('行为 · setRemembered 只接受 string（对象 / null 一律丢弃）', () => {
  const { m, storage } = loadVault()
  m.setRemembered(['u1', { user_id: 'u2', refresh_token: 'eyJx.SECRET' }, null, '  u3  '])
  const raw = storage.getItem(INDEX_KEY) || ''
  assert(JSON.stringify(JSON.parse(raw)) === JSON.stringify(['u1', 'u3']),
    '非字符串元素必须丢弃、空白要去掉，实测: ' + raw)
  assert(raw.indexOf('SECRET') === -1, '对象元素里的凭据不得漏进索引: ' + raw)
})

check('行为 · 增 / 查 / 删 / 清 与计数一致', () => {
  const { m } = loadVault()
  m.setRemembered(['u1', 'u2'])
  assert(m.rememberedAccountCount.value === 2, '计数应为 2，实测 ' + m.rememberedAccountCount.value)
  assert(m.isRemembered('u1') === true, '按 id 应命中')
  assert(m.isRemembered('nope') === false, '未记住的必须为 false（fail-closed）')
  assert(m.isRemembered(null) === false, '空值必须为 false —— 否则「免密」标记会错亮')
  assert(m.isRemembered(undefined) === false, 'undefined 必须为 false')
  m.forgetRemembered('u1')
  assert(m.isRemembered('u1') === false, 'forgetRemembered 必须真的删掉')
  assert(m.rememberedAccountCount.value === 1, '不该误删别人')
  m.clearRemembered()
  assert(m.rememberedAccountCount.value === 0, 'clearRemembered 必须清空')
})

check('行为 · 重名 id 去重（脏数据不该撑大计数）', () => {
  const { m } = loadVault()
  m.setRemembered(['u1', 'u1', 'u2'])
  assert(m.rememberedAccountCount.value === 2, '重复 id 必须去重，实测 ' + m.rememberedAccountCount.value)
})

// =====================================================================
// 第二部分 · AST 形态断言
// =====================================================================
const VAULT_SRC = fs.readFileSync(VAULT, 'utf8')
const USER_SRC = fs.readFileSync(USER, 'utf8')
const MENU_SRC = fs.readFileSync(MENU, 'utf8')
const POLICY_SRC = fs.readFileSync(POLICY, 'utf8')

const vaultSf = parseTs(VAULT_SRC, 'authVault.ts')
const userSf = parseTs(USER_SRC, 'user.ts')
const menuSf = parseTs(scriptOfVue(MENU_SRC), 'AccountMenu.vue')
// ★ template 里的 @click 表达式也要解析（见 templateOfVue 的注释）
const menuTplSf = parseTs(templateHandlers(MENU_SRC), 'AccountMenu.template.ts')
const policySf = parseTs(POLICY_SRC, 'authRefreshPolicy.ts')

check('AST · 索引模块里绝不出现 token / 密码标识符', () => {
  const names = allNames(vaultSf).map((s) => String(s).toLowerCase())
  const hits = names.filter(
    (s) => BANNED_IDENT_PIECES.some((b) => s.includes(b)) || BANNED_IDENT_RE.test(s)
  )
  assert(hits.length === 0,
    '本机索引模块里出现了凭据/密码相关标识符：' + JSON.stringify(hits)
    + ' —— 这个模块的契约就是「一个凭据都不存」。密码一旦落盘，改密也不能止损')
})

check('AST · 索引模块里不得出现 JWT 形态的字符串字面量', () => {
  const hits = allStringLiterals(vaultSf).filter((s) => JWT_RE.test(s))
  assert(hits.length === 0, '索引模块里内嵌了 JWT 形态串：' + JSON.stringify(hits))
})

check('AST · 索引模块零网络（既防循环依赖，也防悄悄外发）', () => {
  const calls = allCalls(vaultSf).map((c) => c.callee)
  const banned = ['fetch', 'axios', 'XMLHttpRequest', 'WebSocket', 'sendBeacon', 'post', 'get']
  const hits = calls.filter((c) => banned.includes(c))
  assert(hits.length === 0,
    '本机索引模块出现了网络调用：' + JSON.stringify(hits)
    + ' —— 它必须零依赖：`api/request.ts` 已经 import 了 `stores/user`，'
    + '本模块若 import request 就会构成 user → authVault → request → user 的循环依赖')
})

check('AST · 索引模块只 import vue（零别家）', () => {
  const mods = []
  ts.forEachChild(vaultSf, (n) => {
    if (ts.isImportDeclaration(n)) mods.push(n.moduleSpecifier.text)
  })
  assert(JSON.stringify(mods) === JSON.stringify(['vue']),
    '索引模块的 import 应恰好是 [\'vue\']，实测 ' + JSON.stringify(mods))
})

check('AST · v1 的凭据仓库 API 已从全仓剔除', () => {
  const dead = [
    'saveCredential', 'getCredential', 'getCredentialByEmail', 'hasCredential',
    'dropCredential', 'clearAllCredentials', 'adoptCredential',
    'storedCredentialCount', 'isExpired',
    'CREDENTIAL_TTL_DAYS', 'MAX_STORED_CREDENTIALS',
  ]
  const files = collectSrcFiles(SRC)
  const hits = []
  for (const f of files) {
    const sf = parseAnyFile(f)
    if (!sf) continue
    walk(sf, (n) => {
      if (ts.isIdentifier(n) && dead.includes(n.getText(sf))) {
        hits.push(path.relative(ROOT, f) + ' :: ' + n.getText(sf))
      }
    })
  }
  assert(hits.length === 0,
    'v1 的凭据仓库 API 仍有引用：' + JSON.stringify(hits)
    + ' —— 残留一个就等于「本机还会存凭据」。'
    + '★ 本断言走 AST：这些名字在解释性注释里会被逐字引用，字符串扫描会假红')
  assert(files.length > 50, '扫描到的源文件数异常（' + files.length + '），门禁可能没扫到东西')
})

check('AST · /auth/device/* 的调用点封闭在 stores/user.ts', () => {
  const files = collectSrcFiles(SRC)
  const allow = [path.resolve(USER), path.resolve(POLICY)]
  const hits = []
  for (const f of files) {
    if (allow.includes(path.resolve(f))) continue
    const sf = parseAnyFile(f)
    if (!sf) continue
    for (const lit of allStringLiterals(sf)) {
      if (lit.indexOf('/auth/device/') !== -1) hits.push(path.relative(ROOT, f) + ' :: ' + lit)
    }
  }
  assert(hits.length === 0,
    '在 user.ts / authRefreshPolicy.ts 之外发现了 /auth/device/* 字面量：' + JSON.stringify(hits)
    + ' —— 网络调用必须收在 store 一层，组件里直接发会让「本机免密」出现多份实现')
})

check('AST · /auth/device/* 必须在 401 拦截器的豁免清单里', () => {
  const lits = allStringLiterals(policySf)
  const missing = DEVICE_ENDPOINTS.filter((ep) => !lits.includes(ep))
  assert(missing.length === 0,
    '401 刷新豁免清单缺: ' + JSON.stringify(missing)
    + ' —— 这些端点的 401 是**业务结论**（「这枚凭据失效了」），不是「该刷新当前会话」的信号。'
    + '不豁免会走出「切换失败 → 拿当前账号 refresh → 重试 switch → 仍 401」，'
    + '还可能把用户**正常**的当前会话搅乱')
})

// =====================================================================
// 第三部分 · 成对不变量
// =====================================================================
check('AST · switchToAccount 不得 revoke，且必须走 store 的免密通道', () => {
  const fns = collectFns(menuSf)
  assert(!!fns.switchToAccount, '找不到 switchToAccount')
  const calls = callsIn(menuSf, fns.switchToAccount)
  const revoked = calls.filter((c) => c.callee.includes('goLoginPage') && c.args.join(',').includes('revoke'))
  assert(revoked.length === 0,
    'switchToAccount 不得 revoke —— 撤销了当前凭据，「切回来」就又要输密码，与免密直接冲突')

  const viaStore = calls.filter((c) => c.callee === 'userStore.switchToAccount')
  assert(viaStore.length === 1,
    'switchToAccount 必须**恰好一次**走 userStore.switchToAccount，实测 ' + viaStore.length
    + ' —— 前端不得自己判断凭据是否有效：那是服务端的唯一真源，'
    + '前端再判一遍就是两份实现，必然漂移且必有一份测不到')

  const stale = calls.filter((c) => c.callee === 'forgetRemembered')
  assert(stale.length >= 1,
    'switchToAccount 的失败分支必须去掉本地「免密」标记，否则它会在列表里一直顶着标记骗人')
})

check('AST · 移除账号 / 清空记录：服务端与本地必须成对删', () => {
  const fns = collectFns(menuSf)

  assert(!!fns.removeKnown, '找不到 removeKnown')
  const rc = callsIn(menuSf, fns.removeKnown).map((c) => c.callee)
  assert(rc.includes('userStore.forgetDeviceAccount'),
    'removeKnown 必须让**服务端**忘掉它 —— 只删本地标签＝留一个用户看不见的后门：'
    + '他以为「移除了」，实际点一下还能直接进去')
  assert(rc.includes('forgetRemembered'),
    'removeKnown 必须同时去掉本地标记，否则界面会一直显示「免密」')

  assert(!!fns.clearKnown, '找不到 clearKnown')
  const cc = callsIn(menuSf, fns.clearKnown).map((c) => c.callee)
  assert(cc.includes('userStore.forgetDeviceAll'),
    'clearKnown 必须清**服务端** —— 这是用户手里唯一能把本机免密一次清干净的入口')
  assert(cc.includes('clearRemembered'),
    'clearKnown 必须清本地索引')
})

check('AST · clearKnown 必须处理「服务端没清掉」—— 不许假装成功', () => {
  const fn = collectFns(menuSf).clearKnown
  assert(!!fn, '找不到 clearKnown')
  const src = fn.getText(menuSf)
  const ifStmt = findIfByCondition(menuSf, fn, (t) => t.replace(/\s+/g, '').includes('!cleared'))
  assert(!!ifStmt,
    'clearKnown 必须显式判 `!cleared` 走失败分支：服务端没清掉，'
    + '用户却以为凭据已经没了（可能因此把电脑借给别人）—— 典型的静默假成功')
  let hasReturn = false
  walk(ifStmt.thenStatement, (n) => {
    if (ts.isReturnStatement(n)) hasReturn = true
  })
  assert(hasReturn, '失败分支必须 `return`，不能继续往下清本地标记 —— 那会让界面与服务端状态错位')
  const calls = callsIn(menuSf, fn)
  const err = calls.find((c) => c.callee === 'message.error')
  assert(!!err, '失败分支必须提示用户（message.error）')
  const clearPos = calls.find((c) => c.callee === 'clearRemembered')
  assert(!!clearPos, '找不到 clearRemembered 调用')
  assert(err.pos < clearPos.pos, '顺序应为「先判失败并告知、再清本地」')
  assert(/await\s+userStore\.forgetDeviceAll/.test(src),
    'forgetDeviceAll 必须 await —— 不等结果就无法知道服务端到底清没清掉')
})

check('AST · 清空 / 移除：本地标记在服务端之后变更（先权威、后缓存）', () => {
  const fns = collectFns(menuSf)
  for (const name of ['removeKnown', 'clearKnown']) {
    const calls = callsIn(menuSf, fns[name])
    const server = calls.find((c) => /forgetDevice(Account|All)/.test(c.callee))
    const local = calls.find((c) => /^(forgetRemembered|clearRemembered)$/.test(c.callee))
    assert(!!server && !!local, name + ' 必须同时有服务端与本地两处调用')
    assert(server.pos < local.pos,
      name + '：应先调服务端再改本地标记。反过来的话，服务端失败而本地已清 ⇒ '
      + '界面显示「没记住」，可那枚凭据还躺在 Redis 里，只是用户再也看不见它了 —— 比不删更糟')
  }
})

check('AST · 退出登录：先忘本机免密，再调 /auth/logout（顺序不变量）', () => {
  const fns = collectFns(userSf)
  assert(!!fns.logout, '找不到 logout')
  const calls = callsIn(userSf, fns.logout)
  const forget = calls.find((c) => c.callee === 'forgetDeviceAccount')
  const logout = calls.find((c) => c.callee === 'post' && c.args.join(',').includes('/auth/logout'))
  assert(!!forget,
    'logout 必须调 forgetDeviceAccount —— 不调的话「退出登录」名不副实：'
    + '那枚凭据还在服务端躺着，下次点一下又能直接进来')
  assert(!!logout, 'logout 必须仍然调 /auth/logout —— 只清本地不叫登出')
  assert(forget.pos < logout.pos,
    '★★★ forgetDeviceAccount 必须在 /auth/logout **之前**：logout 会把 jti 写进黑名单，'
    + '之后再拿这枚 access token 调 forget 会 401 ⇒ 结果是'
    + '「已经退出登录，但这个账号在本机仍然免密」（第 119 轮实测踩到）')
  assert(logout.args.join(',').includes('refresh_token'),
    '登出必须带上 refresh_token：只撤 access 的话，refresh 还能换出全新的 access')
})

check('AST · logout 只删本账号，不许清空整台设备', () => {
  const fn = collectFns(userSf).logout
  assert(!!fn, '找不到 logout')
  const calls = callsIn(userSf, fn).map((c) => c.callee)
  assert(!calls.includes('forgetDeviceAll'),
    'logout 不该清空整台设备 —— 退出的是"这个"账号，彻底清干净由「清空记录」承担'
    + '（判据：语义要精确，别顺手多删）')
})

check('AST · 免密登记是 fire-and-forget（不得拖垮登录）', () => {
  let voided = 0
  let awaited = 0
  walk(userSf, (n) => {
    if (ts.isVoidExpression(n) && /^enrollDevice/.test(n.expression.getText(userSf))) voided++
    if (ts.isAwaitExpression(n) && /^enrollDevice/.test(n.expression.getText(userSf))) awaited++
  })
  assert(voided >= 3,
    'enrollDevice 应至少 3 处 `void` 调用（登录成功 / 刷新成功 / 改密换发），实测 ' + voided)
  assert(awaited === 0,
    '★ 不得 await enrollDevice —— 登录此刻已经成功，免密登记失败不该让它看起来失败')
})

check('AST · 免密失败要留日志（不许静默）', () => {
  const fns = collectFns(userSf)
  const fn = fns.enrollDevice
  assert(!!fn, '找不到 enrollDevice')
  const src = fn.getText(userSf)
  assert(/console\.(warn|error)/.test(src),
    'enrollDevice 的 catch 必须留日志：不弹提示是对的（用户此刻并不在做切换动作），'
    + '但完全无声会让「免密为什么没生效」无从排查')
})

check('成对 · 撤销仍然只发生在「退出登录」这一条路', () => {
  // ★ script 与 template **都要看**：@click 里的表达式不在 <script> 里，
  //   只看 script 的 AST 对模板是瞎的（第 118 轮反向注入 R9 实测踩到）
  const calls = [...allCalls(menuSf), ...allCalls(menuTplSf)]
    .filter((c) => c.callee.includes('goLoginPage'))
  // 自证「两个来源都看见了」——否则「一处都没找到」也会让下一条断言看似成立
  assert(calls.length >= 2,
    'goLoginPage 在 script 与 template 里都应被扫到，实测 ' + calls.length + ' 处')
  const revoked = calls.filter((c) => c.args.join(',').includes('revoke'))
  assert(revoked.length === 1,
    'AccountMenu 里 revoke 应恰好 1 处（handleLogout），实测 ' + revoked.length
    + ' —— 多出来的那些会把「切换/登录其它账号」也变成撤销，白丢免密')
})

// =====================================================================
//  ★ 第 120 轮新增：老板实测反馈「切换账号还是要重新输入密码」引出的五条
//
//  实测结论（探针打真实服务，不靠推断）：后端链路完好 ——
//  switch 对**本机记住过的**账号回 200「已切换」，对**没记住的**回 401
//  「本机未记住该账号的登录状态，请输入密码登录」；Set-Cookie 能穿过 Vite 代理
//  到浏览器；同一设备记住两个账号后，两个方向都免密成功。
//
//  ⇒ 真正的缺口是**界面从没告诉用户「输这一次，以后就免密了」**，
//    于是他把「首次需密码」读成了「每次都要密码」。
//  下面五条把这个缺口的两半都钉住：语义（不许把失败当空）+ 呈现（必须解释清楚）。
// =====================================================================

check('AST · 读清单失败时不得清空索引（「拿不到」≠「为空」）', () => {
  const fn = collectFns(userSf).fetchRememberedAccounts
  assert(!!fn, '找不到 fetchRememberedAccounts')
  const calls = callsIn(userSf, fn)
  // 目标形态：setRemembered() 或 setRemembered([]) —— 两者都是「把索引清空」
  const clearing = calls.filter(
    (c) => c.callee === 'setRemembered' && /^\s*(\[\s*\])?\s*$/.test(c.args.join(','))
  )
  assert(clearing.length === 0,
    'fetchRememberedAccounts 失败时不得 setRemembered([]) —— access token 恰好过期或后端抖一下，'
    + '索引就会被整体清空，界面立刻把所有账号渲染成「需密码」，而服务端一条都没丢。'
    + '实测命中 ' + clearing.length + ' 处')
  const writes = calls.filter((c) => c.callee === 'setRemembered')
  assert(writes.length >= 1,
    '成功路径仍必须用服务端权威清单覆盖本地（setRemembered(ids)）—— '
    + '不许为了「不清空」把正常写入也一起删掉')
})

check('AST · 索引模块必须提供只读出口（失败分支要靠它保留旧值）', () => {
  assert(!!collectFns(vaultSf).getRemembered,
    'authVault.ts 必须导出 getRemembered()：调用方在请求失败时要保留旧值，就得先读得到旧值；'
    + '而直接把内部 ref 暴露出去会让调用方绕过 persist()（内存变了、盘没变，刷新即回退）')
})

check('AST · 免密反馈只给「用户主动登录」这一条路', () => {
  const fns = collectFns(userSf)
  const seen = []
  for (const name of ['setAuthData', 'refreshTokenAction', 'applyTokenPair']) {
    const fn = fns[name]
    if (!fn) continue
    for (const c of callsIn(userSf, fn)) {
      if (c.callee !== 'enrollDevice') continue
      seen.push(name)
      const args = c.args.join(',').trim()
      if (name === 'setAuthData') {
        assert(args === 'true',
          'setAuthData 必须调 enrollDevice(true)：用户刚用密码登录完，'
          + '正是该告诉他「已记住、下次免密」的唯一时刻（实测 args=' + JSON.stringify(args) + '）')
      } else {
        assert(args === '',
          name + ' 里的 enrollDevice 不得带参数 —— 它跑在 access token 过期的**后台刷新**路径上，'
          + '弹提示会在用户毫不知情时反复刷屏（实测 args=' + JSON.stringify(args) + '）')
      }
    }
  }
  assert(seen.length >= 3,
    '三处 enrollDevice 调用点都应被扫描到，实测 ' + seen.length
    + ' 处 —— 少扫到一处就可能存在漏网的提示路径')
})

check('模板 · 切换列表必须让「免密 / 需密码」两类账号一眼可分', () => {
  const tpl = templateOfVue(MENU_SRC)
  assert(tpl.includes('sp-freed'), '模板里缺少「免密」徽标')
  assert(tpl.includes('sp-first'),
    '模板里缺少「需密码」徽标 —— 原来未免密的账号**什么都不显示**，'
    + '用户于是以为列表里每个账号都能免密，点下去才发现要输密码，而界面上毫无解释')
  assert(/首次|需密码/.test(tpl), '模板必须出现「需密码」或「首次」字样，让这条路径可被解释')
})

check('文案 · 「需密码」必须说明「只需这一次，之后免密」', () => {
  const fn = collectFns(menuSf).switchTitle
  assert(!!fn, '找不到 switchTitle')
  const src = fn.getText(menuSf)
  assert(/首次/.test(src),
    'switchTitle 必须点明「首次」—— 原文案只写「（需要输入密码）」，读起来像每次都输；'
    + '这正是老板「现在切换账号还是要重新输入密码」这句反馈背后的误解来源')
  assert(/即可免密|之后/.test(src), 'switchTitle 必须说明这一次之后会变成免密，否则用户不知道这次输密码的价值')
})

// =====================================================================
//  ★ 第 122 轮：「记住登录状态」勾选框
//
//  老板原话：「无需这个提示，是否增加一个记住密码按钮」
//
//  ★ 为什么做成**勾选框**而不是真的"记住密码"：
//    本项目不保存密码 —— 服务端加密托管的是 refresh token（第 119 轮：
//    `core/security/credentials.py` 的 Fernet + `core/auth/device_vault.py`）。
//    叫「记住密码」会承诺一件没做的事，正是项目明令禁止的命名承诺型偏差。
//    这个控件的真实价值是：把「登录即记住」从**没点就发生的事**变成
//    用户可见、可撤销的选择（本项目既有判据：不接受没点就发生的事）。
//
//  ★ 它同时**替代**了第 120 轮那条解释性说明条（老板要求去掉），
//    所以原来那条「Login.vue 必须包含 switch-hint」的断言被**整条删除**。
//    门禁只该钉住**当前**形态：需求变了，旧断言就从资产变成负资产
//    （本项目判据：门禁是墓志铭，不是产前检查）。
//
//  ★ 六条断言覆盖「契约 → 消费 → 撤销 → 打通 → 清场」全链：
//    只查模板会放过「勾选框是装饰」，只查 store 会放过「值根本没传进去」。
// =====================================================================

const LOGIN_SRC = fs.readFileSync(LOGIN, 'utf8')
const loginSf = parseTs(scriptOfVue(LOGIN_SRC), LOGIN)
const loginTpl = templateOfVue(LOGIN_SRC)

check('AST · 登录凭据类型必须有「是否记住」这个输入', () => {
  let iface = null
  walk(userSf, (n) => {
    if (!iface && ts.isInterfaceDeclaration(n) && n.name.getText(userSf) === 'LoginCredentials') {
      iface = n
    }
  })
  assert(!!iface, '找不到 LoginCredentials 接口')
  const prop = iface.members.find((m) => m.name && m.name.getText(userSf) === 'remember')
  assert(!!prop,
    'LoginCredentials 必须声明 remember —— 否则登录页的勾选框无处可传，'
    + '只能靠一个隐式全局量，而那种"传参"没有任何类型约束能拦住它被删掉')
  assert(/boolean/.test(prop.getText(userSf)),
    'remember 必须是 boolean，实测 ' + prop.getText(userSf).replace(/\s+/g, ' '))
  assert(!!prop.questionToken,
    'remember 必须是**可选**的（`remember?:`）—— 必填会打断所有既有的 login({email,password}) 调用点')
})

check('AST · setAuthData 的「记住」参数必须默认 true', () => {
  const fn = collectFns(userSf).setAuthData
  assert(!!fn, '找不到 setAuthData')
  assert(fn.parameters.length >= 2,
    'setAuthData 必须接受第二个参数（要不要记住），实测 ' + fn.parameters.length + ' 个')
  const txt = fn.parameters[1].getText(userSf)
  assert(/=\s*true/.test(txt),
    '第二个参数必须**默认 true**（实测 ' + txt + '）—— 否则 register() 那条路'
    + '（不传第二参）会静默变成「注册完不记住」，而刚注册的用户恰恰是马上要常用的人')
})

check('AST · 免密登记必须由 remember 控制（不得无条件执行）', () => {
  const fn = collectFns(userSf).setAuthData
  assert(!!fn, '找不到 setAuthData')
  const guard = findIfByCondition(userSf, fn, (t) => /remember/.test(t))
  assert(!!guard,
    'setAuthData 里必须存在以 remember 为条件的 if —— 没有它，勾选框就是个纯装饰：'
    + '用户取消勾选后凭据照样会被交给服务端托管')
  const inThen = callsIn(userSf, guard.thenStatement)
    .filter((c) => c.callee === 'enrollDevice' && c.args.join(',').trim() === 'true')
  assert(inThen.length === 1,
    'enrollDevice(true) 必须落在 if (remember) 的 then 分支里、且恰好一处，实测 '
    + inThen.length + ' —— 落在 if 外面等于条件白写；落两处则必有一处绕过判断')
})

check('AST · 取消勾选必须「撤销」，而不是什么都不做', () => {
  const fn = collectFns(userSf).setAuthData
  const guard = findIfByCondition(userSf, fn, (t) => /remember/.test(t))
  assert(guard && guard.elseStatement,
    'if (remember) 必须带 else 分支 —— 只写 then = 取消勾选时「什么都不做」，'
    + '而该账号此前可能已被记住过，于是用户取消勾选后再去切换**依然免密**')
  const callees = callsIn(userSf, guard.elseStatement).map((c) => c.callee)
  assert(callees.includes('forgetDeviceAccount'),
    'else 分支必须调 forgetDeviceAccount（服务端删）—— 取消勾选 = 撤销，不是「这次不新增」。'
    + '实测分支里的调用：' + JSON.stringify(callees))
  assert(callees.includes('forgetRemembered'),
    'else 分支必须同时调 forgetRemembered（本地标记）—— 否则界面会继续显示「免密」骗人')
  assert(callees.indexOf('forgetRemembered') < callees.indexOf('forgetDeviceAccount'),
    '顺序必须是「先清本地、再删服务端」：反过来的话，服务端删失败时界面会显示「免密」'
    + '而点下去失败；按这个顺序最坏只是多输一次密码（安全的失败方向）')
})

check('模板 · 登录页的勾选框必须真的传到 login()', () => {
  const boxes = startTagsWith(loginTpl, 'a-checkbox', 'rememberDevice')
  assert(boxes.length === 1,
    '登录页应恰好有一个绑定 rememberDevice 的勾选框，实测 ' + boxes.length)
  assert(/v-model:checked="rememberDevice"/.test(boxes[0]),
    '勾选框必须双向绑定 rememberDevice，实测标签：' + boxes[0].replace(/\s+/g, ' '))

  // ★ 两半都要：有勾选框 ≠ 值被用了。只查模板会放过「勾选框是装饰」。
  const args = []
  walk(loginSf, (n) => {
    if (
      ts.isCallExpression(n) &&
      /(^|\.)login$/.test(n.expression.getText(loginSf)) &&
      n.arguments.length &&
      ts.isObjectLiteralExpression(n.arguments[0])
    ) {
      args.push(n.arguments[0])
    }
  })
  assert(args.length >= 1, '找不到 userStore.login({...}) 的调用点')
  const props = []
  for (const o of args) for (const p of o.properties) props.push(p.getText(loginSf).replace(/\s+/g, ' '))
  assert(
    props.some((t) => /^remember\s*:\s*rememberDevice\.value$/.test(t)),
    'login() 的实参里必须有 `remember: rememberDevice.value`，实测属性：' + JSON.stringify(props)
    + ' —— 少了它，勾选框点了也不影响任何行为'
  )
})

check('模板 · 登录页不得再有那条解释性提示条', () => {
  assert(!LOGIN_SRC.includes('switch-hint'),
    'Login.vue 不该再有那段说明条 —— 老板明确要求「无需这个提示」（第 122 轮）')
  assert(!LOGIN_SRC.includes('switchedEmail'),
    'Login.vue 不该再保留「本次是从切换账号跳来的」这个只用于渲染提示条的中间态')
  assert(LOGIN_SRC.includes('rememberDevice'),
    '删提示条的同时必须留下替代物（勾选框），否则用户就回到「被悄悄记住」——'
    + '正是本项目判据「不接受没点就发生的事」所禁止的')
})

// =====================================================================
//  ★ 第 121 轮新增：两个「切换账号」入口必须**互斥**
//
//  老板原话：「左侧边栏右下角已有图标，取消用户头像下拉列表中的【切换账号】」
//
//  CDP 真实浏览器实测（`.workbuddy/probes/_r121dom.mjs`，改前/改后各跑一次）：
//    展开态 260px → 下拉里有「切换账号」＋ 行内图标也在   ⇒ 同一个动作两个入口
//    折叠态  80px → 行内图标**不渲染**（32px 头像 + 22px 按钮放不下，实测 false）
//  ⇒ 只删菜单项 = 折叠态零入口（本项目反复防过的「提示要登录可是没有入口」）；
//     只留菜单项 = 老板看到的那个重复。
//     唯一自洽的形态是**互补**：任一时刻恰好一个可见。
//
//  ★ 断言必须**限定到目标那一个起始标签**：
//    全文件搜裸条件会撞上「退出登录」—— 它本来**就该**是裸的（只在真登录时显示）。
//    第 121 轮第一版探针正是把这条期望值写错，报了一个假 BAD。
// =====================================================================

/** 取模板里所有命中 marker 的起始标签（本项目属性值内不含 '>'） */
function startTagsWith(tpl, tagName, marker) {
  const re = new RegExp('<' + tagName + '[\\s\\S]*?>', 'g')
  return (String(tpl).match(re) || []).filter((t) => t.includes(marker))
}

check('模板 · 切换账号的两个入口必须互斥（展开态只有行内图标）', () => {
  const tpl = templateOfVue(MENU_SRC)
  const sw = startTagsWith(tpl, 'a-menu-item', 'key="switch"')
  assert(sw.length === 1,
    '模板里应恰好有一个 key="switch" 的菜单项，实测 ' + sw.length
    + ' —— 0 个则折叠态没有入口，2 个则菜单里出现重复项（老板投诉的正是这个）')
  const swTag = sw[0]
  const pops = startTagsWith(tpl, 'a-popover', 'switchOpen')
  assert(pops.length === 1, '模板里应恰好有一个绑定 switchOpen 的浮层，实测 ' + pops.length)
  const popTag = pops[0]

  assert(/v-if="isRealLogin && sidebarCollapsed"/.test(swTag),
    '下拉里的「切换账号」必须绑定「真登录 且 已折叠」 —— 展开态下行内图标就在'
    + '用户名右边，下拉里再来一项就是同一动作的第二个入口。实测标签：'
    + swTag.replace(/\s+/g, ' '))

  assert(!/v-if="[^"]*!sidebarCollapsed/.test(swTag),
    '菜单项不得带「未折叠」条件 —— 那会让它在展开态也出现，重复项就回来了')

  assert(/v-if="isRealLogin && !sidebarCollapsed"/.test(popTag),
    '行内切换图标必须绑定「未折叠」：侧栏折叠后只有 80px，'
    + '32px 头像 + 22px 按钮放不下（CDP 实测行内图标在折叠态不存在）')

  // ★ 互补性：恰好一个条件带否定 ⇒ 任一时刻恰好一个入口
  const negated = [swTag, popTag].filter((t) => /v-if="[^"]*!sidebarCollapsed/.test(t)).length
  assert(negated === 1,
    '两个入口必须互补（恰好一个带「未折叠」条件），实测 ' + negated
    + ' 个 —— 两边都不带 ⇒ 展开态重复；两边都带 ⇒ 折叠态无入口（死路）')
})

check('模板 · 折叠态的切换入口必须仍能到达登录页', () => {
  const tpl = templateOfVue(MENU_SRC)
  const sw = startTagsWith(tpl, 'a-menu-item', 'key="switch"')
  const pops = startTagsWith(tpl, 'a-popover', 'switchOpen')
  assert(sw.length === 1 && pops.length === 1,
    '两个入口必须都在（一个负责展开态、一个负责折叠态），实测 '
    + sw.length + ' / ' + pops.length
    + ' —— 少任何一个，都会有一半的侧栏宽度下切不了账号')
  assert(sw[0].includes('goLoginPage'),
    '折叠态的菜单项必须仍能到达登录页（goLoginPage），否则它只是个装饰')
})


// =====================================================================
//  ★ 第 123 轮新增：登录页的「最近登录」必须**尝试免密**，不能只填邮箱
//
//  老板原话：「已经勾选记住密码了，可是选择最近的登录账号，每次登录还是
//             要重新输密码，只是登录完后切换账号这个功能正常」
//
//  根因（代码级，不是推断）：pickAccount 只做 `loginForm.email = a.email`，
//  用户随后必然走 /auth/login —— 那是**密码验证**那条路，
//  无论本机有没有记住都绕不开密码。
//  ⇒ 「记住登录状态，下次免密切换」这句承诺在这一格上根本不成立：
//     用户点了「最近登录」，拿到的是一个"还得自己输"的空表单。
//
//  可行性已用**真服务**实测（.workbuddy/probes/_r123probe.py）：
//    无 Authorization + 有 device cookie → **200 已切换**
//    无 cookie                            → 401「本机没有记住任何登录状态」
//    有 cookie 但该账号没被记住            → 401「本机未记住该账号的登录状态」
//  （switch 不要求真身份是第 119 轮的刻意设计：它正是为「当前身份已不可用」
//    这个场景准备的，靠 httpOnly Cookie 认"这台机器"。）
//
//  ★ 四条断言覆盖「调用 → 降级 → 防重入 → 反馈」，缺一条就是一个真缺口：
//    只查「调了 switch」会放过「失败后没降级」——用户点了没反应，比原来更糟；
//    只查降级会放过「没有闸门」——并发两次 switch 时，
//      两次响应的到达顺序不保证，会出现「点的是 A，进去的是 B」。
// =====================================================================

check('AST · 点选「最近登录」必须尝试免密（且走 store 的唯一通道）', () => {
  const fn = collectFns(loginSf).pickAccount
  assert(!!fn, '找不到 pickAccount')

  assert(/^async\s/.test(fn.getText(loginSf).trim()),
    'pickAccount 必须是 async —— 免密是一次网络往返，同步函数只能"发出去就不管"，'
    + '而它的成败恰恰决定了要不要降级为填邮箱')

  const calls = callsIn(loginSf, fn)
  const viaStore = calls.filter((c) => c.callee === 'userStore.switchToAccount')
  assert(viaStore.length === 1,
    'pickAccount 必须**恰好一次**走 userStore.switchToAccount，实测 ' + viaStore.length
    + ' —— 0 次 = 点选根本没尝试免密（老板投诉的正是这个）；'
    + '2 次 = 重复实现。前端不得自己判断凭据有效性：那是服务端的唯一真源')
  assert(viaStore[0].args.join(',').trim() === 'a.id',
    '必须传**历史条目自己的** id（a.id），实测 ' + viaStore[0].args.join(',')
    + ' —— 传别的值会切错账号，而界面上完全看不出来')
})

check('AST · 免密失败必须降级为「填邮箱 + 说明为何还要输密码」', () => {
  const fn = collectFns(loginSf).pickAccount
  assert(!!fn, '找不到 pickAccount')

  // ① 必须仍把邮箱填进去 —— 这是降级后用户唯一能继续往下走的状态
  assert(fn.getText(loginSf).includes('loginForm.email = a.email'),
    'pickAccount 必须仍把邮箱填进表单 —— 免密失败后用户至少不用再敲一遍邮箱，'
    + '否则"降级"两个字就是空的：他点了一下，什么也没得到')

  // ② 必须有一个以 switch 结果为准的分支（成功直接进 + 失败继续留在登录页）
  const guard = findIfByCondition(loginSf, fn, (t) => /switched/.test(t))
  assert(!!guard,
    'pickAccount 里必须存在以 switch 结果为条件的 if —— 没有它，'
    + '免密失败后代码会继续往下走，把「切换失败」当成「切换成功」')

  // ③ 失败分支必须解释原因。含糊地说「免密失败」等于让用户自己猜，
  //    而他会猜成"功能是坏的"（老板这一轮就是这么理解的）。
  const infos = callsIn(loginSf, fn).filter((c) => /^message\.(info|warn|error)$/.test(c.callee))
  assert(infos.length >= 1,
    'pickAccount 必须给出**失败原因**（message.info/warn/error 之一），实测 ' + infos.length
    + ' —— 静默降级会让用户以为"点了没反应"')
  const said = infos.map((c) => c.args.join('')).join(' | ')
  assert(said.indexOf('密码') !== -1,
    '提示文案必须点明「还要输一次密码」这件事，实测文案: ' + said
    + ' —— 用户此刻唯一的问题是"那我为什么还要输"，不回答它等于没说')
})

check('AST · 切换中必须防重入（并发两次 switch 会出现「点 A 进 B」）', () => {
  const fn = collectFns(loginSf).pickAccount
  assert(!!fn, '找不到 pickAccount')

  let gate = null
  walk(fn, (n) => {
    if (
      !gate &&
      ts.isIfStatement(n) &&
      /switchingId\s*\.\s*value/.test(n.expression.getText(loginSf)) &&
      n.thenStatement &&
      ts.isReturnStatement(n.thenStatement)
    ) {
      gate = n
    }
  })
  assert(!!gate,
    'pickAccount 必须有「已有一次切换在飞就直接返回」的闸门（if (switchingId.value) return）'
    + ' —— 少了它，连点两下会发出两次 switch，两次响应到达顺序不保证，'
    + '可能出现「点的是 A，进去的是 B」，而界面上完全看不出来')

  // 闸门必须在**填邮箱之前**：否则连点会把表单里的邮箱改掉，留下一个
  // 与最终登录身份不一致的输入框。
  const body = fn.body
  const stmts = body && ts.isBlock(body) ? body.statements : []
  assert(stmts.length > 0 && stmts[0] === gate,
    '防重入闸门必须是函数体**第一条**语句 —— 排在填邮箱之后就晚了：'
    + '连点时表单已被改写，用户会看到一个与真正切过去的账号不同的邮箱')
})

check('模板 · 列表在切换中必须禁用并给出条目级反馈', () => {
  const btn = startTagsWith(loginTpl, 'button', 'pickAccount')
  assert(btn.length === 1,
    '模板里应恰好有一个绑定 pickAccount 的按钮，实测 ' + btn.length)
  const tag = btn[0]

  assert(/:disabled="!!switchingId"/.test(tag),
    '条目必须绑定 :disabled="!!switchingId" —— 原生 button 没有 loading 态，'
    + '不禁用的话用户点一下没反应就会继续点。实测标签：' + tag.replace(/\s+/g, ' '))

  assert(/switchingId === a\.id/.test(tag),
    '条目必须有「正在切的是这一条」的判定（switchingId === a.id）—— '
    + '否则禁用后界面毫无变化，用户无从知道点没点上')

  assert(!/:title="`填入/.test(tag),
    '条目的 title 不该再是「填入 xxx」—— 语义已经从"填邮箱"变成"免密登录"，'
    + '文案留在旧语义上就是承诺与实现不符')
})


check('AST · 登录页必须与侧栏**同源**判定「能不能免密」', () => {
  const imports = []
  walk(loginSf, (n) => {
    if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier)
        && n.importClause && n.importClause.namedBindings
        && ts.isNamedImports(n.importClause.namedBindings)) {
      for (const el of n.importClause.namedBindings.elements) {
        imports.push({ src: n.moduleSpecifier.text, name: el.name.getText(loginSf) })
      }
    }
  })
  const fromVault = imports.filter((i) => i.src === '@/config/authVault').map((i) => i.name)
  assert(fromVault.includes('isRemembered'),
    '登录页必须从 @/config/authVault 取 isRemembered（免密清单的前端唯一出口）。实测该模块 import = '
    + JSON.stringify(fromVault)
    + ' —— 缺了它，模板手上就只有账号历史（KnownAccount），'
    + '而账号历史**不含**"本机到底记住没记住"这件事，于是 title 只能无条件写「免密登录」。')
  assert(fromVault.includes('rememberedAccountCount'),
    '必须同时取 rememberedAccountCount —— 它不是用来取数的，而是建立响应式依赖的唯一手段'
    + '（见下一条断言）。实测 = ' + JSON.stringify(fromVault))

  let fn = null
  walk(loginSf, (n) => {
    if (!fn && ts.isFunctionDeclaration(n) && n.name
        && n.name.getText(loginSf) === 'hasCred') fn = n
  })
  assert(!!fn,
    '必须有一个 hasCred(a) 函数 —— 名字刻意与 AccountMenu.vue 一致：'
    + '同一种判定要有同一种消费姿势，否则两个列表上的「免密」含义日后会各自漂移。'
    + '（本项目判据：同一能力两份实现 ⇒ 至少一份永远测不到。）')
  const body = fn.getText(loginSf)
  assert(/void\s+rememberedAccountCount\s*\.\s*value/.test(body),
    'hasCred 体内必须显式读一次 rememberedAccountCount.value（惯用写法 `void …`）—— '
    + 'isRemembered() 读的是模块级 ref，而模板里的**函数调用**不会被 Vue 自动追踪；'
    + '不显式读一下，标记就会停在旧值上（现象：「刚免密进过一次，回到登录页标记却没变」）。'
    + '★ 这一行不是取数：删掉它不报任何错，只会让界面悄悄变旧。实测函数体：'
    + body.replace(/\s+/g, ' ').slice(0, 200))
  assert(/isRemembered\s*\(/.test(body),
    'hasCred 必须转发给 isRemembered —— 不得在登录页自己再判一遍（那是第二份实现），实测：'
    + body.replace(/\s+/g, ' ').slice(0, 200))
})

check('模板 · 登录页条目必须让「免密 / 需密码」一眼可分', () => {
  const btn = startTagsWith(loginTpl, 'button', 'pickAccount')
  assert(btn.length === 1,
    '模板里应恰好有一个绑定 pickAccount 的按钮，实测 ' + btn.length)
  const tag = btn[0]

  // ★ 数「整个条目块」，而不是只数起始标签：badge 是**另一个** span 标签，
  //   它不在 `<button …>` 的属性里。只数 tag 会把"两处判定"误判成一处
  //   —— 这是本门禁自己踩过的坑（假 FAIL，见第 125 轮记录）。
  const bStart = loginTpl.indexOf(tag)
  const bEnd = loginTpl.indexOf('</button>', bStart)
  const block = bEnd > bStart ? loginTpl.slice(bStart, bEnd) : tag
  const uses = (block.match(/hasCred\(a\)/g) || []).length
  assert(uses >= 2,
    '条目必须在**至少两处**按 hasCred(a) 判定（title 提示 + 可见标记）—— '
    + '只写一处的话，要么 tooltip 说谎、要么列表上看不出区别。实测 ' + uses + ' 处：'
    + block.replace(/\s+/g, ' ').slice(0, 300))

  assert(/免密登录/.test(tag) && /尚未记住/.test(tag),
    'title 必须给出**两个**分支：已记住 → 「免密登录」；未记住 → 「尚未记住…需输入一次密码」。'
    + '★ 这正是第 125 轮的修复点：此前 title 无条件写「免密登录」，'
    + '而点下去弹的是「本设备尚未记住」—— 同一个按钮，两句相反的话。实测标签：'
    + tag.replace(/\s+/g, ' ').slice(0, 260))

  const badges = startTagsWith(loginTpl, 'span', 'ra-badge')
  assert(badges.length === 1,
    '模板里应恰好有一个 ra-badge 状态标记，实测 ' + badges.length
    + ' —— 0 个则用户只能靠 hover 或点一下才知道能不能免密；'
    + '2 个则同一条目上出现两个标记')
  const b = badges[0]
  assert(/hasCred\(a\)/.test(b),
    '状态标记必须绑定**同一**判定 hasCred(a)，实测 ' + b.replace(/\s+/g, ' '))
  assert(/'on'\s*:\s*'off'/.test(b),
    '状态标记必须有两个 class 分支（on / off），实测 ' + b.replace(/\s+/g, ' '))
  const at = loginTpl.indexOf('ra-badge')
  const seg = loginTpl.slice(at, at + 420).replace(/\s+/g, ' ')
  assert(/免密/.test(seg) && /需密码/.test(seg),
    '状态标记的两个状态都必须有文案（免密 / 需密码），实测片段 ' + seg.slice(0, 220))
})

check('模板 · 「需密码」的解释不得只挂在两个入口中的一个上', () => {
  assert(/class="ra-note"/.test(loginTpl),
    '登录页必须有那条说明行（ra-note）—— 侧栏「切换账号」列表里**早就有了**'
    + '（AccountMenu.vue 的 sp-note，第 120 轮加），登录页却一直缺。'
    + '★ 后果：用户在登录页看得到「需密码」这个标记，却读不到它是什么意思、'
    + '该怎么办 —— 这正是老板那两句「有时候可以免密登录，有时候不能」'
    + '「目前是只支持免密切换吗」的由来：界面上只有结论，没有依据。'
    + '本条断言防的是"只在一侧补了说明"这种半修。')
  const at = loginTpl.indexOf('class="ra-note"')
  const seg = loginTpl.slice(at, at + 400).replace(/\s+/g, ' ')
  assert(/免密/.test(seg) && /密码登录一次/.test(seg),
    '说明行必须讲清「为什么现在要输密码、输完会怎样」—— 那是用户此刻唯一的问题，'
    + '答不出来他就会认为功能是坏的。实测 ' + seg.slice(0, 220))

  const menuTpl = templateOfVue(MENU_SRC)
  assert(/sp-note/.test(menuTpl),
    '侧栏那一侧的说明（sp-note）也必须仍在 —— 本条是**双向**断言：'
    + '修任何一侧时都不会把另一侧悄悄弄丢。')
})

check('AST · 「本机是否记住」不得并进 KnownAccount（两种寿命必须能各自失效）', () => {
  const p = path.join(SRC, 'config', 'knownAccounts.ts')
  assert(fs.existsSync(p),
    '找不到 ' + p + ' —— 反向注入时 SRC_DIR 必须**整树**指向副本（只指文件级会产生假 FAIL）')
  const sf = parseTs(fs.readFileSync(p, 'utf8'), p)
  let iface = null
  walk(sf, (n) => {
    if (!iface && ts.isInterfaceDeclaration(n)
        && n.name.getText(sf) === 'KnownAccount') iface = n
  })
  assert(!!iface, 'knownAccounts.ts 里找不到 KnownAccount 接口')
  const names = iface.members.map((m) => (m.name ? m.name.getText(sf) : '')).filter(Boolean)
  const bad = names.filter((n) => /remember|credential|token|免密/i.test(n))
  assert(bad.length === 0,
    'KnownAccount 里不得出现 remembered / credential / token 之类字段，实测 '
    + JSON.stringify(bad)
    + ' —— 「账号历史」（谁用过这台机器，本机可独立清除）与「免密凭据清单」'
    + '（能不能免密，服务端才是权威）是两种寿命不同、清空入口也不同的数据。'
    + '合并之后，它们再也不可能各自独立失效。')
  assert(names.includes('id') && names.includes('email'),
    'KnownAccount 必须仍有 id / email —— 本条在防"整份被改没"这类假通过。实测 '
    + JSON.stringify(names))
})
check('AST · 免密失败必须把本地标记也去掉（否则界面会一直骗人）', () => {
  let fn = null
  walk(loginSf, (n) => {
    if (!fn && ts.isVariableDeclaration(n) && n.name
        && n.name.getText(loginSf) === 'pickAccount') fn = n
  })
  assert(!!fn, '找不到 pickAccount 的声明')
  const calls = callsIn(loginSf, fn).map((c) => c.callee + '(' + (c.args[0] || '') + ')')
  assert(calls.some((c) => c.startsWith('forgetRemembered(')),
    'pickAccount 的失败分支必须调 forgetRemembered(a.id)。'
    + '少了它，条目上的「免密」会一直挂着骗人：用户点一次失败、标记不变，就再点一次，'
    + '来回几次之后他得到的结论是「这功能时好时坏」—— 而真因是'
    + '「服务端早就没记住它了，只是界面没说」。'
    + '★ 本质是「界面显示的状态落后于真实状态」。实测调用：'
    + JSON.stringify(calls))
  assert(calls.some((c) => c === 'forgetRemembered(a.id)'),
    '必须传**被点的那个**账号的 id（a.id），实测：' + JSON.stringify(calls))

  const menuSf = parseTs(scriptOfVue(MENU_SRC), MENU_SRC)
  assert(allCalls(menuSf).some((c) => c.callee === 'forgetRemembered'),
    '侧栏 AccountMenu 的失败分支也必须**仍有** forgetRemembered —— 本条是双向断言：'
    + '修任何一侧时都不会把另一侧悄悄弄丢。'
    + '（两个入口点的是同一个账号，失败后的处置必须一样。）')
})
// =====================================================================
// 会话上下文（★ P0-1 配套，第 127 轮）
// =====================================================================
//
// 背景：`sessionIdByAgent` 持久化在**全局** localStorage key
// （`secretary_session_ids`），**不带任何用户维度** ⇒ 换账号后在同一个浏览器里，
// 新身份的第一次对话就带着**上一个身份的** session_id 发出去。
//
// 后端 P0-1 修复之后这种请求已经读不到别人的内容了（会判为"没有可用会话"并新建），
// 但前端不该把别人的会话 ID 当自己的发出去 —— 那等于把"归属"整个交给后端兜底，
// 而兜底一旦失效（回滚 / 另开一条通道 / 下一个人重写这段逻辑）就是数据泄露。
//
// ⇒ 会话状态属于「随身份失效的前端上下文」，必须在**唯一**的清理函数里被清掉。
//   这正是 `utils/sessionContext.ts` 头注释那句"还有一批按身份隔离的前端上下文
//   必须一起清"的字面兑现 —— 那句话早就写着，而会话状态一直不在清单里。

const SESSION_CTX = pick('SESSION_CTX_SRC', ['src', 'utils', 'sessionContext.ts'])
const CHAT_STORE = pick('CHAT_STORE_SRC', ['src', 'stores', 'chat.ts'])

//: `resetSessionContext` 是否调用了 chat store 的 `resetSessionState`。
//: 抽成函数，是为了让「反向注入自检」能拿**同一个**判据去喂坏样本（防门禁恒绿）。
function sessionContextClearsChat(sf, fnName) {
  const fn = collectFns(sf)[fnName]
  if (!fn) return false
  return callsIn(sf, fn).some((c) => /(^|\.)resetSessionState$/.test(c.callee))
}

//: chat store 的 `resetSessionState` 是否把**三件套**都清掉：
//: 内存消息（界面上还留着上一个人的气泡）+ sessionId 映射 + 落盘 key。
function chatResetClearsEverything(sf, fnName) {
  const fn = collectFns(sf)[fnName]
  if (!fn) return false
  const body = fn.getText(sf)
  return (
    /messagesByAgent\.value\s*=\s*\{\s*\}/.test(body) &&
    /sessionIdByAgent\.value\s*=\s*\{\s*\}/.test(body) &&
    /localStorage\.removeItem\s*\(\s*SESSION_KEY\s*\)/.test(body)
  )
}

check('AST · 身份切换必须清掉会话状态（sessionId 不得跨身份继承）★', () => {
  const sf = parseTs(fs.readFileSync(SESSION_CTX, 'utf8'), SESSION_CTX)
  assert(
    sessionContextClearsChat(sf, 'resetSessionContext'),
    '`resetSessionContext` 没有调用 `resetSessionState` ⇒ 切换账号 / 登出后，' +
      '`secretary_session_ids`（全局 key，不带用户维度）会被下一个身份继承，' +
      '于是新账号的第一次对话带着上一个账号的 session_id 发出去。'
  )
})

check('AST · chat store 的 resetSessionState 必须清三件套（消息 + sessionId + 落盘）★', () => {
  const sf = parseTs(fs.readFileSync(CHAT_STORE, 'utf8'), CHAT_STORE)
  assert(
    chatResetClearsEverything(sf, 'resetSessionState'),
    '`resetSessionState` 必须同时清 `messagesByAgent`（否则界面上还留着上一个人的' +
      '对话气泡）、`sessionIdByAgent`、以及 `localStorage.removeItem(SESSION_KEY)`' +
      '（只清内存不清落盘，刷新一次就又回来了）。'
  )
})

check('自检 · 上面两条会话清理判据不是恒绿（反向注入）★', () => {
  const badCtx = parseTs(
    'function resetSessionContext() { const a = 1; return a }\n',
    'bad-ctx.ts'
  )
  assert(
    !sessionContextClearsChat(badCtx, 'resetSessionContext'),
    '反向注入漏报：不调 resetSessionState 的清理函数被判成了合规 —— 上一条门禁恒绿。'
  )

  const badChat = parseTs(
    'const resetSessionState = () => { messagesByAgent.value = {} }\n',
    'bad-chat.ts'
  )
  assert(
    !chatResetClearsEverything(badChat, 'resetSessionState'),
    '反向注入漏报：只清内存消息、不清 sessionId 与落盘 key 的实现被判成了合规。'
  )

  const goodChat = parseTs(
    'const resetSessionState = () => { messagesByAgent.value = {};' +
      ' sessionIdByAgent.value = {}; localStorage.removeItem(SESSION_KEY) }\n',
    'good-chat.ts'
  )
  assert(
    chatResetClearsEverything(goodChat, 'resetSessionState'),
    '反向注入误报：三件套都清的正确实现被判成了不合规（判据写得太紧，会误伤）。'
  )
})

// =====================================================================
// 小工具：按条件文本定位 if 语句
// =====================================================================
function findIfByCondition(sf, node, pred) {
  let found = null
  walk(node, (n) => {
    if (!found && ts.isIfStatement(n) && pred(n.expression.getText(sf))) found = n
  })
  return found
}

// =====================================================================
// 汇总
// =====================================================================
const scanned = collectSrcFiles(SRC).length
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log((r.ok ? '  [PASS] ' : '  [FAIL] ') + r.name + (r.ok ? '' : '\n         ' + r.msg))
}
console.log('')
console.log('  扫描源文件 ' + scanned + ' 个；索引模块 ' + path.relative(ROOT, VAULT))
console.log('---- ' + (results.length - failed.length) + '/' + results.length + ' 通过 ----')
process.exit(failed.length ? 1 : 0)
