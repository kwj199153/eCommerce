/**
 * 身份相关上下文的清理（★ 第 113 轮）
 *
 * 「切换账号」「登出」「401 身份失效」这三件事有一个共同点：
 * **当前身份没了**。但"身份没了"不等于"状态干净了" —— 还有一批
 * 按身份隔离的前端上下文必须一起清，否则它们会被下一个身份继承。
 *
 * 具体漏的是什么（本轮实测）：
 *   · `current_shop_id`（`stores/shop.ts`，同时是 `X-Shop-ID` 请求头的来源）
 *   · `current_account_id`（即"当前团队"，`stores/account.ts`）
 *   · 会话消息 + `secretary_session_ids`（★ 第 127 轮补上，P0-1 配套）
 *     它同样是**全局** localStorage key、不带用户维度 ⇒ 换账号直接继承
 *     上一个身份的会话 ID。后端 P0-1 已能把这种请求挡成"没有可用会话"，
 *     但前端不该把别人的 ID 发出去 —— 归属不该只有一层兜底。
 *   两者都持久化在 localStorage，登出**都不会**被清。后果是：换账号登录后、
 *   在店铺/团队列表加载完成之前，请求已经带着**上一个账号的** shop_id 发出去了
 *   —— 后端归属校验会 403，而界面上看起来是"我的店铺不见了"。
 *
 * ★★ 为什么这个函数不放在 `stores/user.ts` 里
 *   `stores/account.ts` 已经 `import { useUserStore } from '@/stores/user'`。
 *   反过来让 `user.ts` 去 import `account.ts`，就构成 ESM 环 ——
 *   两个 store 都在顶层调 `defineStore`，环下会有一侧的绑定是 undefined。
 *   （`stores/account.ts` 头注释第 26-29 行专门写了这件事。）
 *   ⇒ 放在这里：本模块**只被调用点 import**，谁也不 import 它，
 *     拓扑上永远不在环里。
 *
 * ★ 为什么用函数而不用"在 store 内部自动监听"
 *   Pinia 的 store 之间没有生命周期钩子，`user.clearAuth()` 也不该知道
 *   account/shop 的存在（那是反向依赖）。所以清理动作由**调用点**显式触发，
 *   但实现只有这一份 —— 三个调用点共用，不是三份实现。
 */

import { useAccountStore } from '@/stores/account'
import { useChatStore } from '@/stores/chat'
import { useShopStore } from '@/stores/shop'

/** 已清理过的项，便于日志与自检（不含任何身份数据） */
export interface ResetOutcome {
  accountContextCleared: boolean
  shopSelectionCleared: boolean
  conversationContextCleared: boolean
}

/**
 * 清掉随身份失效的上下文。
 *
 * 调用点（目前三处，都是"身份失效"的入口）：
 *   1. `components/Sidebar/AccountMenu.vue` 的 `handleLogout()`
 *   2. `components/Sidebar/AccountMenu.vue` 的 `switchToAccount()`（切换账号）
 *   3. `api/request.ts` 的 401 分支
 *
 * ★ 刻意**不**清 `known_accounts`（账号历史）。
 *   那是"已知身份"，不是"当前身份"；切账号的价值恰恰依赖它留着。
 *   把两者混在一起清，等于每次登出都把切换入口清空。
 *
 * ★ 无副作用：只改内存与 localStorage，**不发任何网络请求**。
 *   （401 分支调用它时后端正在回 401，发请求会递归打转。）
 */
export function resetSessionContext(): ResetOutcome {
  const accountStore = useAccountStore()
  const shopStore = useShopStore()
  const chatStore = useChatStore()

  accountStore.reset()
  shopStore.clearCurrentShop()
  // ★ P0-1 配套（2026-09-18）：会话状态（消息 + sessionId）也按身份隔离，
  //   而 sessionId 存在**全局** key 里，不清就会被下一个身份继承。
  chatStore.resetSessionState()

  return {
    accountContextCleared: true,
    shopSelectionCleared: true,
    conversationContextCleared: true,
  }
}
