#!/usr/bin/env node
/**
 * 账号注册表门禁（★ 第 113 轮）
 *
 * 为什么值得单独一个门禁：`config/knownAccounts.ts` 承担一条**安全不变量** ——
 * 「切换账号」的历史里**一个字节的凭据都不能有**。这条不变量很容易在后续
 * 迭代里被无声破坏（最典型的写法：`rememberAccount({ ...authResponse })`，
 * 一行就把 access_token / refresh_token 全带下去了，界面看起来毫无异常）。
 * 类型系统拦不住它（多传字段在 TS 里合法），所以必须有一条**能说不**的断言。
 *
 * 怎么跑：node scripts/check-session-registry.cjs
 *   · 用 devDependency `typescript` 的 transpileModule 把 .ts 转成 CJS；
 *   · 在 `vm` 沙箱里注入假 localStorage 与极简 vue（只用到 `ref`），
 *     所以**不需要** JSDOM / jsdom-global 之类的额外依赖；
 *   · 每个用例都用**全新的沙箱**（本模块有模块级状态，复用会互相污染）。
 *
 * 反向注入（证明本门禁不是空跑）：
 *   KNOWN_ACCOUNTS_SRC=<一个把整个 user 对象摊开写的副本> node scripts/check-session-registry.cjs
 *   —— 此时「安全不变量」那条必须变红。
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const SRC = process.env.KNOWN_ACCOUNTS_SRC
  ? path.resolve(process.env.KNOWN_ACCOUNTS_SRC)
  : path.join(ROOT, 'src', 'config', 'knownAccounts.ts')

/** 与模块内 LS_KEY 保持一致；故意在这里**重复字面量**，这样改错键名会被门禁发现 */
const STORAGE_KEY = 'known_accounts'

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

function makeStorage(initial) {
  const map = new Map()
  if (initial !== undefined) map.set(STORAGE_KEY, initial)
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)) },
    removeItem: (k) => { map.delete(k) },
    clear: () => map.clear(),
  }
}

/** 每个用例一份全新沙箱 */
function loadModule(storage) {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const code = fs.readFileSync(SRC, 'utf8')
  const out = ts.transpileModule(code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2019,
    },
    fileName: SRC,
  }).outputText

  const sandbox = {
    module: { exports: {} },
    exports: {},
    localStorage: storage,
    // 只用到 ref()，给最小实现即可 —— 也顺便证明本模块**不依赖** vue 的运行时
    require: (id) => {
      if (id === 'vue') return { ref: (v) => ({ value: v }) }
      throw new Error('未预期的外部依赖: ' + id)
    },
  }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename: SRC })
  return sandbox.module.exports
}

function listOf(storage) {
  const raw = storage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : []
}

// ===== 1. 空态 =====
check('空存储：自举后列表为空，且不抛错', () => {
  const m = loadModule(makeStorage())
  assert(m.useKnownAccounts().value.length === 0, '初始列表应为空')
})

// ===== 2. 记一笔 =====
check('登录一次记一笔：标识字段与登录时间都写进去', () => {
  const s = makeStorage()
  const m = loadModule(s)
  m.rememberAccount({ id: 'u1', email: 'a@x.com', name: '甲', role: 'admin' })
  const list = listOf(s)
  assert(list.length === 1, '应恰好一条，实际 ' + list.length)
  assert(list[0].id === 'u1', 'id 应写入')
  assert(list[0].email === 'a@x.com', 'email 应写入')
  assert(list[0].name === '甲', 'name 应写入')
  assert(typeof list[0].last_login_at === 'string' && list[0].last_login_at.length > 0,
    'last_login_at 应是 ISO 字符串')
})

// ===== 3. 同一账号去重 =====
check('同一账号重复登录：不新增，只置顶', () => {
  const s = makeStorage()
  const m = loadModule(s)
  m.rememberAccount({ id: 'u1', email: 'a@x.com', name: '甲' })
  m.rememberAccount({ id: 'u2', email: 'b@x.com', name: '乙' })
  m.rememberAccount({ id: 'u1', email: 'a@x.com', name: '甲' })
  const list = listOf(s)
  assert(list.length === 2, '去重后应仍是 2 条，实际 ' + list.length)
  assert(list[0].id === 'u1', '刚登录的应排在最前，实际 ' + list.map((x) => x.id).join(','))
  assert(m.useKnownAccounts().value.length === 2, '响应式镜像也要同步')
})

// ===== 4. 缺 id 时用 email 兜底 =====
check('后端没给 user.id 时用 email 兜底，不丢记录', () => {
  const s = makeStorage()
  const m = loadModule(s)
  m.rememberAccount({ email: 'c@x.com', name: '丙' })
  const list = listOf(s)
  assert(list.length === 1, '应记下来，而不是静默丢掉')
  assert(list[0].id === 'c@x.com', '兜底 id 应为 email')
})

// ===== 5. 上限淘汰 =====
check('条数上限：超出后淘汰最早登录的那个', () => {
  const s = makeStorage()
  const m = loadModule(s)
  const MAX = m.MAX_KNOWN_ACCOUNTS
  assert(typeof MAX === 'number' && MAX > 0, 'MAX_KNOWN_ACCOUNTS 应是正数')
  for (let i = 1; i <= MAX + 1; i++) {
    m.rememberAccount({ id: 'u' + i, email: `u${i}@x.com`, name: '用户' + i })
  }
  const list = listOf(s)
  assert(list.length === MAX, `应封顶在 ${MAX}，实际 ${list.length}`)
  assert(list[0].id === 'u' + (MAX + 1), '最新的应在最前')
  assert(!list.some((x) => x.id === 'u1'), '最早的应已被淘汰')
})

// ===== 6. 移除 / 清空 =====
check('移除单条与清空都只动本机这份列表', () => {
  const s = makeStorage()
  const m = loadModule(s)
  m.rememberAccount({ id: 'u1', email: 'a@x.com', name: '甲' })
  m.rememberAccount({ id: 'u2', email: 'b@x.com', name: '乙' })

  m.forgetAccount('u1')
  assert(listOf(s).length === 1, '移除后应剩 1 条')
  assert(listOf(s)[0].id === 'u2', '移除的应是被指定的那条')

  m.forgetAllAccounts()
  assert(listOf(s).length === 0, '清空后应为空')
  assert(m.useKnownAccounts().value.length === 0, '响应式镜像也要清空')
})

// ===== 7. ★ 安全不变量 =====
check('★ 安全不变量：整个登录响应丢进来，也不得有任何凭据落盘', () => {
  const s = makeStorage()
  const m = loadModule(s)
  m.rememberAccount({
    id: 'u1',
    email: 'a@x.com',
    name: '甲',
    role: 'admin',
    // 下面这些是"手滑把 authResponse 摊开传进来"时会出现的字段
    access_token: 'SECRET_ACCESS',
    refresh_token: 'SECRET_REFRESH',
    password: 'SECRET_PASSWORD',
    token_version: 7,
    jti: 'SECRET_JTI',
  })
  const raw = s.getItem(STORAGE_KEY)
  const forbidden = [
    'SECRET_ACCESS', 'SECRET_REFRESH', 'SECRET_PASSWORD', 'SECRET_JTI',
    'access_token', 'refresh_token', 'password', 'token_version',
  ]
  for (const bad of forbidden) {
    assert(!raw.includes(bad), `落盘内容里出现了「${bad}」：${raw}`)
  }
})

// ===== 8. 脏数据容错 =====
check('localStorage 是脏数据：当空表处理，不抛错', () => {
  for (const junk of ['not json', '{"a":1}', '[1,2,3]', '[{"id":1}]', 'null']) {
    const s = makeStorage(junk)
    const m = loadModule(s)
    assert(m.useKnownAccounts().value.length === 0, `脏数据 ${junk} 应被当成空表`)
  }
})

// ===== 输出 =====
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n账号注册表门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log('账号注册表门禁通过（安全不变量：无凭据落盘 ✓）')
