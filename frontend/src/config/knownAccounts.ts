/**
 * 已知账号注册表（★ 第 113 轮）
 *
 * 支撑需求：「切换账号」按钮 + 记录以前登录过的账号。
 *
 * ★★ 本模块唯一的红线：只记**账号标识**，绝不记凭据
 *   记 id / email / name / role / 上次登录时间，**一个字节的 token 都不写**。
 *   两条理由，任一条单独成立就足够：
 *     · 登出会让后端把 refresh token 的 jti 写进黑名单 ⇒ 存下来的旧 token 是
 *       **死凭据**，「一键免密切回」根本做不出来。留着它只会变成
 *       「点了没反应」的假入口（本项目已有过同形态的教训）。
 *     · localStorage 里的明文凭据可被任何同源脚本读走，且**长期有效** ——
 *       比明文密码更持久。本项目对凭证明文的既有判据是「宁可拒绝写入」。
 *   ⇒ 所以「切换账号」的正确语义只能是：**登出当前账号 + 去登录另一个**，
 *     只是把邮箱从历史里带出来，省掉重新敲一遍。
 *
 * ★ 为什么不做成 Pinia store
 *   `stores/user.ts` 要调本模块（登录成功后记一笔），而 `stores/account.ts`
 *   已经 import 了 `stores/user.ts`。若再引入 user → account 方向的 store 依赖，
 *   就有构成环的风险（`stores/account.ts` 头注释专门警告过这一类环）。
 *   本模块是**零依赖**的纯持久化层，任何 store 都能安全 import。
 *
 * ★ 为什么不需要判断演示模式
 *   唯一写入点是 `stores/user.ts` 的 `setAuthData()`，而它只被
 *   `login()` / `register()` 调用。演示模式走的是 `$patch` + 直接写
 *   localStorage（见 `views/Login.vue` 与 `router/index.ts` 的守卫），
 *   不经过 `setAuthData` ⇒ 演示身份**自动**不会进历史。
 *   （判据：记录点选在「真实登录的必经之路」上，而不是事后去过滤。）
 */

import { ref } from 'vue'

const LS_KEY = 'known_accounts'

/** 最多记住几个账号；超出后淘汰最后一次登录最早的那个 */
export const MAX_KNOWN_ACCOUNTS = 5

export interface KnownAccount {
  /** 后端 user.id —— 去重主键 */
  id: string
  email: string
  name: string
  role?: string
  avatar_url?: string | null
  /** ISO 时间戳：最后一次**成功登录**的时间 */
  last_login_at: string
}

/** 供 UI 响应式消费的镜像；写入一律经本模块的函数，不直接改它 */
const list = ref<KnownAccount[]>([])

function hasStorage(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage !== null
  } catch {
    return false
  }
}

/**
 * 宽松解析：localStorage 是用户可编辑的，这个键还可能有旧版本遗留的脏数据。
 * 解析不出来就当空表（**不是**抛错 —— 脏数据不该让整个应用起不来）。
 */
function parse(raw: string | null): KnownAccount[] {
  if (!raw) return []
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return []
  }
  if (!Array.isArray(data)) return []

  const out: KnownAccount[] = []
  for (const item of data) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const id = typeof o.id === 'string' ? o.id : ''
    const email = typeof o.email === 'string' ? o.email : ''
    if (!id || !email) continue
    out.push({
      id,
      email,
      name: typeof o.name === 'string' && o.name ? o.name : email,
      role: typeof o.role === 'string' ? o.role : undefined,
      avatar_url: typeof o.avatar_url === 'string' ? o.avatar_url : null,
      last_login_at: typeof o.last_login_at === 'string' ? o.last_login_at : '',
    })
    if (out.length >= MAX_KNOWN_ACCOUNTS) break
  }
  return out
}

function persist(next: KnownAccount[]): void {
  list.value = next
  if (!hasStorage()) return
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(next))
  } catch {
    // 配额满 / 隐私模式禁用存储：内存里仍然是新的，界面照常可用
  }
}

/** 从 localStorage 载入并刷新响应式镜像 */
export function loadKnownAccounts(): KnownAccount[] {
  const next = hasStorage() ? parse(localStorage.getItem(LS_KEY)) : []
  list.value = next
  return next
}

/**
 * 记一笔：登录成功后调用。
 *
 * 同一账号（按 id）重复登录只**置顶并刷新时间**，不产生第二条 ——
 * 否则「切换账号」列表很快会被同一账号刷满。
 */
export function rememberAccount(user: {
  id?: string | null
  email?: string | null
  name?: string | null
  role?: string | null
  avatar_url?: string | null
}): void {
  const email = (user.email || '').trim()
  // ★ 兜底用 email 当 id：后端 user.id 缺失时也不能把这条丢掉，
  //   否则用户会遇到"刚登录完，历史里却没有"这种说不通的行为
  const id = (user.id || email).trim()
  if (!id || !email) return

  const entry: KnownAccount = {
    id,
    email,
    name: (user.name || '').trim() || email,
    role: user.role || undefined,
    avatar_url: user.avatar_url ?? null,
    last_login_at: new Date().toISOString(),
  }

  const rest = loadKnownAccounts().filter((a) => a.id !== id)
  persist([entry, ...rest].slice(0, MAX_KNOWN_ACCOUNTS))
}

/** 从历史里移除一个账号（不影响该账号本身，只影响本机这份快捷入口） */
export function forgetAccount(id: string): void {
  persist(loadKnownAccounts().filter((a) => a.id !== id))
}

/** 清空本机的账号历史 —— **只**清这个键，不碰当前登录态 */
export function forgetAllAccounts(): void {
  persist([])
}

/** 只读镜像（模板直接绑它） */
export function useKnownAccounts() {
  return list
}

/** 给门禁/自检用：让外部断言「存下去的东西里没有凭据」 */
export const KNOWN_ACCOUNTS_STORAGE_KEY = LS_KEY

// ★ 模块导入即自举。
//   刷新页面时 `setAuthData()` 不会跑（那是"登录"才走的路径），若不在
//   这里读一次，侧栏的账号列表会一直空着 —— 用户看到的是"我明明登录过"。
//   放在这里而不是各消费组件的 onMounted：消费方漏写就是永久空列表，
//   而这种遗漏不会有任何报错。
loadKnownAccounts()
