/**
 * 账户上下文（★ C 档 2026-09-17）
 *
 * ★ 解决的问题
 * 改造前「当前账户」只是 `Team.vue` 里的一个**局部 ref**（`currentAccountId`），
 * 它只影响成员列表的加载 —— 与店铺列表、对话、结果面板**毫无关系**。
 * 于是用户切了账户，看到的店铺、能操作的数据完全不变，
 * 「账户」这一层在界面上是不可感知的。
 *
 * 本 store 把它提升为**应用级上下文**：
 *   · `currentAccountId` 持久化，全应用共享；
 *   · 切换账户后，若当前选中的店铺不属于新账户 ⇒ 自动切到该账户下的第一家；
 *   · 店铺列表按当前账户过滤（`shopsOfCurrentAccount`）。
 *
 * ★★ 演示模式必须**完全不请求**账户接口（这里最容易踩的坑）
 *   `api/accounts.ts` 的所有请求都带 `requiresIdentity: true`
 *   —— 那个标志的语义是"401 要走正常通路（清状态 + 跳登录）"，
 *   而不是像业务数据那样被静默降级到 mock（身份数据没有可降级的东西）。
 *
 *   而演示模式下 token 是 `demo-token`，后端**不认**它会回 401。
 *   所以在启动时无条件拉账户 = 演示模式一进首页就被弹到登录页。
 *   ⇒ 本 store 在 `isDemoToken()` 为真时**直接保持空态**，
 *     此时 `currentAccountId` 为 null、店铺不做账户过滤，
 *     与演示模式"业务数据不设限"的既有语义一致。
 *
 * ★ 依赖方向：account → shop（单向）。
 *   反向（shop → account）会构成模块级循环 import —— 两个 store 各自在顶层
 *   调 `defineStore`，ESM 循环下有一侧的绑定会是 undefined。
 *   所以「按账户筛店铺」的 getter 放在**本文件**，而不是 shop store。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { listAccounts, type AccountInfo } from '@/api/accounts'
import { isDemoToken } from '@/config/demoMode'
import { useShopStore } from '@/stores/shop'
import { useUserStore } from '@/stores/user'

const LS_KEY = 'current_account_id'

export const useAccountStore = defineStore('account', () => {
  // ====== State ======

  const accounts = ref<AccountInfo[]>([])
  const currentAccountId = ref<string | null>(localStorage.getItem(LS_KEY))
  const isLoading = ref(false)
  /** 是否已成功拉取过（幂等键；演示模式下永远为 false） */
  const loaded = ref(false)

  // ====== Getters ======

  const currentAccount = computed(
    () => accounts.value.find((a) => a.id === currentAccountId.value) || null
  )

  // ★ 第 110 轮：此处曾有 `personalAccount` / `teamAccounts` 两个 getter，
  //   它们按 `kind === 'personal' / 'team'` 分类容器。该二分已被证伪
  //   （容器只有一种，「私有」是**成员数**的取值）⇒ 两个 getter 一起删除。
  //   ★ 刻意**不**在前端补一个「默认容器」getter：那会变成后端
  //     `ensure_default_account()` 判据的第二份实现（本项目吃过亏：
  //     同一判定两份实现 ⇒ 至少一份永远测不到）。落点由后端决定，
  //     前端只需读建店响应里的 `account_id`（见 ShopPopoverContent.vue）。

  /**
   * 当前账户下的店铺。
   *
   * ★ 未选定账户（含演示模式）时返回**全部**，不做过滤 ——
   *   宁可不过滤也不能误伤：过滤掉本应可见的店铺会让用户以为数据丢了，
   *   而"多显示几个"在演示模式下是既定语义。
   */
  const shopsOfCurrentAccount = computed(() => {
    const shopStore = useShopStore()
    const aid = currentAccountId.value
    if (!aid) return shopStore.shops
    // `Shop.account_id` 原本缺失，这里曾被迫写 `(s as any).account_id`；
    // 第 106 轮把字段补进 `Shop` 接口后类型才真正可用。
    return shopStore.shops.filter((s) => s.account_id === aid)
  })

  // ====== Actions ======

  /**
   * 加载我可见的账户（幂等）。
   *
   * ★ 演示模式早退，理由见文件头「演示模式必须完全不请求账户接口」。
   */
  let _loadPromise: Promise<void> | null = null
  async function loadAccounts(force = false): Promise<void> {
    const userStore = useUserStore()
    if (isDemoToken(userStore.token)) {
      // 演示模式：demo-token 不是身份，账户数据不可得。保持空态即可，
      // **绝不能**发请求（会 401 → requiresIdentity 分支 → 跳登录页）。
      return
    }
    if (!force && loaded.value) return
    if (_loadPromise) return _loadPromise

    _loadPromise = (async () => {
      isLoading.value = true
      try {
        applyAccounts((await listAccounts())?.accounts || [])
      } catch (error) {
        console.error('[account] 加载账户列表失败:', error)
      } finally {
        isLoading.value = false
        _loadPromise = null
      }
    })()

    return _loadPromise
  }

  /**
   * 把一批账户写入状态（并校正"当前账户 / 当前店铺"）。
   *
   * ★ 为什么单独一个入口：`Team.vue` 需要**自己**处理 401
   *   （它要给出页面内的登录引导，而本 store 的 `loadAccounts` 把错误
   *   吞掉记 console）。让它在成功分支把结果交回这里，
   *   既保留了那份页面级错误处理，又保证**账户状态只有一处**——
   *   否则 Team.vue 会持有第二份 `accounts` 副本，于是"在侧栏切了账户、
   *   Team 页下拉纹丝不动"这类不同步问题会再次出现。
   */
  function applyAccounts(list: AccountInfo[]) {
    accounts.value = list
    loaded.value = true

    // ① 已选账户若不再可见（被移除 / 停用）⇒ 清掉，避免指向幽灵账户
    if (currentAccountId.value && !list.some((a) => a.id === currentAccountId.value)) {
      currentAccountId.value = null
      localStorage.removeItem(LS_KEY)
    }

    // ② 未选 ⇒ 选**列表第一项**。
    //    ★ 第 110 轮改口径：改造前这里优先选「个人账户」（那个概念已被证伪）。
    //    ★ 刻意不在这里推算"默认建店落点"：那是后端 `ensure_default_account()`
    //      的判据（"你名下最早创建的容器"），在前端重算就是第二份实现。
    //      这里只是"列表第一项"，与建店落点**可能不同** —— 后果是刚建的店
    //      可能不在当前视图里，这一点由 ShopPopoverContent 的显式提示兜住
    //      （读建店响应里的 account_id，不猜）。
    if (!currentAccountId.value && list.length > 0) {
      setCurrentAccount(list[0].id)
    } else {
      syncCurrentShopToAccount()
    }
  }

  /**
   * 切换当前账户。
   *
   * ★ 切换后必须**同时**把店铺选中项迁移到新账户内 ——
   *   否则会出现"账户是 A、但所有请求带着 B 账户店铺的 X-Shop-ID"，
   *   表现为：看板数据来自 B，而账户面板显示 A。后端 P0 修复后会直接 403，
   *   但前端不该主动构造这种矛盾状态。
   */
  function setCurrentAccount(id: string | null) {
    currentAccountId.value = id
    if (id) localStorage.setItem(LS_KEY, id)
    else localStorage.removeItem(LS_KEY)
    syncCurrentShopToAccount()
  }

  /**
   * 把「当前选中店铺」校正到当前账户内。
   *
   * 三种情况：
   *   ① 还没选过店铺 → 选该账户下第一家（没有则不动）
   *   ② 已选店铺仍属于当前账户 → 不动（用户的选择优先）
   *   ③ 已选店铺不属于当前账户 → 迁移到该账户下第一家（没有则清空）
   */
  function syncCurrentShopToAccount() {
    const shopStore = useShopStore()
    const aid = currentAccountId.value
    if (!aid) return

    const inAccount = shopStore.shops.filter((s) => (s as any).account_id === aid)
    const cur = shopStore.currentShopId

    if (cur && inAccount.some((s) => s.id === cur)) return

    if (inAccount.length > 0) {
      shopStore.setCurrentShop(inAccount[0].id)
    } else if (cur) {
      // 该账户下一家店都没有 ⇒ 清掉选中，让界面回到"未选店铺"的空态，
      // 而不是继续带着一个不属于本账户的 shop_id 发请求。
      shopStore.clearCurrentShop()
    }
  }

  /** 退出登录 / 切换用户时重置（避免残留上一个用户的账户选择） */
  function reset() {
    accounts.value = []
    currentAccountId.value = null
    loaded.value = false
    localStorage.removeItem(LS_KEY)
  }

  return {
    // State
    accounts,
    currentAccountId,
    isLoading,
    loaded,

    // Getters
    currentAccount,
    shopsOfCurrentAccount,

    // Actions
    loadAccounts,
    applyAccounts,
    setCurrentAccount,
    syncCurrentShopToAccount,
    reset,
  }
})
