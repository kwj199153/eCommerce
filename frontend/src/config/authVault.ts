/**
 * 本机「已记住账号」索引（★ 第 119 轮重写）
 *
 * ═══════════════════════════════════════════════════════════════════════
 *  本模块**只记账号标识，不记任何凭据**
 * ═══════════════════════════════════════════════════════════════════════
 * 支撑需求：「切换账号在一段时间内不用重复输密码」。
 *
 * 第 118 轮曾把 refresh token（明文）存在这个 localStorage 键里，
 * 第 119 轮**整体搬去服务端托管**：真正的凭据经 Fernet 加密后躺在
 * Redis 的 `auth:device:<device_id>` 里，浏览器只持有一个 httpOnly Cookie
 * 里的 `device_id`。本模块随之退化为一个**纯标识索引**。
 *
 * 于是本文件里再也读不到、也写不进任何 token ——
 * 门禁 `scripts/check-auth-vault.cjs` 用 AST 钉住这一点。
 *
 * ⚠️ 为什么不做 store 化、也不在这里发请求：
 *   `api/request.ts` 已经 `import { useUserStore } from '@/stores/user'`，
 *   而 `stores/user.ts` 要 import 本模块。若本模块再去 import `api/request`，
 *   就构成 `user.ts → authVault.ts → request.ts → user.ts` 的**循环依赖**。
 *   所以本模块**零依赖**：只碰 localStorage，网络调用一律由 `stores/user.ts` 承担。
 *
 * ⚠️ 与 `knownAccounts.ts` 的分工（主键同为 `user.id`，职责不重叠）
 *   · `knownAccounts.ts` 记 id/email/name/role/头像/时间 —— 目的是
 *     「把邮箱带出来，省掉重新敲一遍」。
 *   · 本模块只记 **user_id 列表** —— 目的是「切换时显示『免密』标记，
 *     并知道该向服务端要哪个账号」。它**不是**凭据，删了也不影响安全，
 *     只是下次要多输一次密码。
 *   两者可以各自独立清空（「清空记录」会同时清两边）。
 */

import { ref, computed } from 'vue'

/** 只存 `string[]`（user_id 列表）—— 门禁断言这个键的值里不得出现任何 token 形态串 */
const INDEX_KEY = 'auth_remembered_accounts'

/**
 * ★★★ 第 118 轮遗留键：里面躺着**明文 refresh token**。
 *
 * 第 119 轮起不再使用它，但**必须在模块加载时主动删掉** ——
 * 只在代码里"不再写"是不够的：升级前用过的人，localStorage 里
 * 那串明文会一直留着，直到过期（7 天）。留着的期间它照样能被抄走并用。
 * 用户看不到任何提示，也不会知道要手动清。
 */
const LEGACY_KEYS = ['auth_credentials']

/** 供 UI 响应式消费的镜像；写入一律经本模块函数，不直接改它 */
const remembered = ref<string[]>([])

/**
 * 本机已记住几个账号的登录状态（切换面板要显示这个数）。
 *
 * ★ 名字刻意**不带** "Credential"：本模块一个凭据都不存（见文件头）。
 *   叫 "storedCredentialCount" 会让后来的人以为这里躺着 N 份凭据 ——
 *   命名承诺与实现不符，就是下一个「注释承诺型」缺陷。
 *   这里数的是 **user_id 的个数**。
 */
export const rememberedAccountCount = computed(() => remembered.value.length)

function hasStorage(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage !== null
  } catch {
    return false
  }
}

/**
 * 清掉 v1 版遗留的凭据仓库（明文 token 所在处）。
 *
 * @returns 是否真的删掉了一个存在的键（供自检/日志观测）
 */
export function purgeLegacyCredentialStore(): boolean {
  if (!hasStorage()) return false
  let removed = false
  for (const key of LEGACY_KEYS) {
    try {
      if (localStorage.getItem(key) !== null) {
        localStorage.removeItem(key)
        removed = true
      }
    } catch {
      // 隐私模式下 storage 可能直接抛错 —— 清理失败不该让应用起不来
    }
  }
  return removed
}

/** 宽松解析：localStorage 用户可编辑，且这个键可能有旧版本脏数据 */
function parse(raw: string | null): string[] {
  if (!raw) return []
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return []
  }
  if (!Array.isArray(data)) return []

  const out: string[] = []
  for (const item of data) {
    // ★ 只接受非空字符串。
    //   若历史数据里混进了对象（v1 的形状是 `{user_id, refresh_token, ...}`），
    //   这里**直接丢弃**而不是"尽力解析出 user_id" —— 因为 v1 的对象里
    //   带着凭据，把它的任何一部分留在新索引里都会让
    //   「本模块不持有凭据」这条不变量出现例外。
    if (typeof item === 'string' && item.trim()) out.push(item.trim())
  }
  // 去重（历史脏数据可能重复）
  return Array.from(new Set(out))
}

function persist(next: string[]): void {
  remembered.value = next
  if (!hasStorage()) return
  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(next))
  } catch {
    // 配额满 / 隐私模式禁用存储：内存里仍是新的，本次会话可用
  }
}

/** 从 localStorage 载入索引 */
export function loadRemembered(): string[] {
  const next = hasStorage() ? parse(localStorage.getItem(INDEX_KEY)) : []
  persist(next)
  return next
}

/**
 * 用**服务端的权威清单**整体替换本地索引。
 *
 * ★ 为什么服务端是权威：本地这份只是"首屏不闪"的缓存。
 *   真正的凭据在服务端，只有它知道哪些还在（可能已被撤销、已过期、
 *   或换了密钥解不开）。本地的唯一价值是**同步渲染**那个「免密」标记 ——
 *   若只信本地，会出现"界面上挂着免密、点下去却是登录页"。
 */
export function setRemembered(ids: string[]): void {
  persist(Array.from(new Set((ids || []).filter((i) => typeof i === 'string' && i.trim()).map((i) => i.trim()))))
}

/** 是否已记住某个账号（决定切换时要不要输密码） */
export function isRemembered(userId?: string | null): boolean {
  if (!userId) return false
  return remembered.value.includes(userId)
}

/**
 * 读一份当前索引的**只读副本**。
 *
 * ★★★ 第 120 轮新增，专供「请求失败时保留旧值」那条分支使用：
 *   `stores/user.ts` 的 `fetchRememberedAccounts()` 失败时不能再
 *   `setRemembered([])` —— 那等于把「拿不到权威清单」当成
 *   「权威清单是空的」。但要保留旧值，它得先读得到旧值。
 *
 * ★ 返回副本而不是内部 ref 本身：调用方拿到引用后原地改数组，
 *   会绕过 `persist()` ⇒ 内存变了、localStorage 没变，
 *   刷新一次就回到旧值。出口必须是只读的。
 */
export function getRemembered(): string[] {
  return Array.from(remembered.value)
}

/**
 * 忘掉某个账号的本地标记（对应后端 `POST /auth/device/forget`）。
 *
 * ★ 本地标记与后端容器必须**成对**变更：只改一边会留下错位 ——
 *   本地删了、服务端还在 ⇒ 下次登录又"莫名其妙能免密"；
 *   服务端删了、本地还在 ⇒ 一直显示免密而每次点都失败。
 */
export function forgetRemembered(userId?: string | null): void {
  if (!userId) return
  persist(remembered.value.filter((id) => id !== userId))
}

/** 清空本地索引（对应后端 `POST /auth/device/forget-all`） */
export function clearRemembered(): void {
  persist([])
}

/** 给门禁/自检用 */
export const AUTH_VAULT_STORAGE_KEY = INDEX_KEY
export const AUTH_VAULT_LEGACY_KEYS = LEGACY_KEYS

// ★ 模块导入即自举（与 knownAccounts.ts 同理）：
//   刷新页面后 `setAuthData()` 不会跑（那是"登录"才走的路径），
//   不在这里读一次，切换面板上的"已记住 N 个"就会显示成 0。
loadRemembered()
// ★ 顺手清掉 v1 遗留的明文凭据仓库 —— 见 LEGACY_KEYS 的注释。
purgeLegacyCredentialStore()
