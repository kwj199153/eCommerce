/**
 * 每日经营简报 store（第 371 轮）
 * ==============================
 *
 * 持有「铃铛要用的两个数」：`unread`（徽标）+ `items`（抽屉列表）。
 * 二者来自**同一个响应**（见 `api/briefings.ts`），所以本地只会一起更新 ——
 * 不存两份再各自维护，那正是「徽标 3 条、列表 2 条」的来源。
 *
 * ★ 为什么提到 store 而不是组件内的 `ref`：
 *   抽屉由 `Header/NotificationBell.vue` 持有，但**未来的入口不止一个**
 *   （侧栏、首屏卡片都可能要展示「今天有几项变化」）。放组件里等于把
 *   同一份取数逻辑预埋成两份 —— 本仓对这种形态已有多次实测代价。
 *
 * ★ 失败时**保留旧值**、不置空。两个方向的代价不对称：
 *   保留旧值最坏是「看到的是上一次的内容」，用户能自己重试；
 *   置空则会让界面显示「今天没有需要你处理的变化」—— 那是一句**关于业务的话**，
 *   而事实只是「没取到」。后者用户无从分辨，会把网络问题读成生意没问题。
 *   ⇒ 所以 `loadError` 与 `items` **可以同时非空**，界面必须两个都画
 *   （见 `NotificationBell.vue` 的横幅 + 列表并存那一分支）。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { fetchBriefings, markBriefingRead, type DailyBriefing } from '@/api/briefings'

export const useBriefingStore = defineStore('briefing', () => {
  const items = ref<DailyBriefing[]>([])
  /** 未读简报数（徽标）。★ 来源是服务端计数，不是本地 `filter` 出来的 */
  const unread = ref(0)
  const loading = ref(false)
  /** 取数失败原因；非空即「界面要说失败」（空态门禁 D3 的 `:error` 绑定源） */
  const loadError = ref<string | null>(null)

  // ★★ 两个单调计数器 —— 防「过期响应覆盖新事实」的在途乱序。
  //
  //   ★ 来历必须说清（本仓铁律：归因错方向比不归因更糟）。
  //   `scripts/cdp-r371-briefing-bell.mjs` 的 B9 曾报「展开后徽标仍是 1」，
  //   我当时的解释是「t0 打开抽屉发出的 load 响应迟到、把刚减掉的 unread
  //   覆盖回 1」，据此加了这两个计数器。
  //   **后续取证推翻了那个归因**：B9 的真因是**探针读错了 DOM** ——
  //   antd 徽标是数字滚筒，`sup.textContent` 是 `value..value+10` 共 11 个
  //   数字格的拼接，读数本身就是错的。修好读数口径（只取 `.current` 那格）后，
  //   B9 一跑就绿。
  //
  //   ⇒ 那这两个计数器为什么还留着：**乱序在原理上真的成立** ——
  //   `openDrawer()` 的 `load()` 不等响应就把抽屉打开（`visible = true`），
  //   用户完全可能在它落地之前展开并标记已读。只是本机 localhost 往返太快没复现。
  //   既然已经知道这条路径存在，就该按它写。
  //   `tests/unit/briefingStore.test.ts` 的「在途响应的时序」两组用例钉的就是它 ——
  //   那也是**唯一**能钉住它的方式（真机复现要控制网络时序，不可复现）。
  //
  //   判据：`load` 在**发出时**记下 `loadTicket` 与 `mutations`；响应回来时
  //     ① 若期间已有更晚的 `load` 发出 ⇒ 丢弃（后发者赢）；
  //     ② 若期间发生过成功的「标记已读」⇒ 丢弃（那次响应描述的是旧世界）。
  let loadTicket = 0
  let mutations = 0

  async function load(limit = 30): Promise<void> {
    const ticket = ++loadTicket
    const seenMutations = mutations
    loading.value = true
    loadError.value = null
    try {
      const res = await fetchBriefings(limit)
      // 过期响应：丢弃（不写 items / unread）—— 理由见上面两个计数器
      if (ticket !== loadTicket || seenMutations !== mutations) return
      items.value = res.items ?? []
      unread.value = res.unread ?? 0
    } catch (e) {
      if (ticket !== loadTicket) return
      // 只记错误，**不清空** items / unread（理由见文件头）
      loadError.value = (e as Error)?.message || '简报加载失败'
      console.warn('[briefing] 加载失败', e)
    } finally {
      if (ticket === loadTicket) loading.value = false
    }
  }

  /** 标记一条已读，返回是否成功（失败由调用方决定要不要提示）。
   *
   * ★ 已读时**短路不发请求**：服务端本来就幂等，但省一次往返；
   *   更重要的是避免「展开一条已读的简报」在服务端产生一次无意义的写。
   * ★ 只有服务端确认后才改本地 `read_at` / `unread`：
   *   否则请求失败时徽标已经减一，界面就开始说谎（刷新才对得上）。
   */
  async function markRead(id: string): Promise<boolean> {
    const i = items.value.findIndex((r) => r.id === id)
    if (i < 0) return false
    if (items.value[i].read_at) return true
    try {
      const updated = await markBriefingRead(id)
      mutations += 1 // ★ 让所有**在途**的 load 响应作废（理由见上面的计数器）
      items.value[i] = { ...items.value[i], ...updated }
      // 本地减一并夹到 0：下一次 `load()` 会用服务端的权威值覆盖它
      unread.value = Math.max(0, unread.value - 1)
      return true
    } catch (e) {
      console.warn('[briefing] 标记已读失败', e)
      return false
    }
  }

  return { items, unread, loading, loadError, load, markRead }
})
