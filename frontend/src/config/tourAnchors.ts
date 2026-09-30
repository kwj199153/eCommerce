/**
 * 新手引导 · 锚点注册表（唯一真源）
 * ==================================
 *
 * ★ 锚点一律写在 DOM 的 `data-tour="<id>"` 属性上，**禁止**用 CSS 选择器。
 *   理由不是洁癖：`class="main-content"` 在本仓同时存在于
 *   `views/Workspace.vue`（中间内容区）和 `components/ChatPanel/index.vue`（对话区），
 *   是两个不同的盒子。用类名当锚点会得到「选中两个 ⇒ 按第一个算」的**静默错高亮**。
 *
 * ★ 本文件是 `#1015` 双向对账门禁的**唯一输入**：
 *   · 方向 A（注册了没标）：本文件里的 id 在源码里找不到对应的 `data-tour` ⇒ 门禁失败
 *   · 方向 B（标了没注册）：源码里出现的 `data-tour` 值不在本表里 ⇒ 门禁失败
 *   ⇒ 所以增删锚点**只改这里**（以及对应的那一处 DOM 打标），别在别处另立一份清单。
 *
 * ★ 供 guidance/ ESLint 之类静态工具使用时注意：id 必须**逐字**与本表一致，
 *   改一个字符就会触发方向 A + B 同时红（这正是我们想要的灵敏度）。
 */

/** DOM 属性名。DOM 侧把它写成元素的属性、值取自本表；别在别处硬写这个世界值 */
export const TOUR_ATTR = 'data-tour'

/**
 * 全部锚点 id（**顺序即引导顺序**，见 `config/tourSteps.ts`）。
 *
 * ⚠️ 保持 `--每行一个字符串字面量--` 的写法：`scripts/check-tour-anchors.cjs`
 *    用正则从这里取值，压成一行会让门禁取不到东西（症状是"门禁还在跑，其实已经查不到东西了"）。
 */
export const TOUR_ANCHOR_IDS = [
  'tour-brand',
  'tour-shop-switch',
  'tour-agent-list',
  'tour-chat-input',
  'tour-chat-stream',
  'tour-right-panel',
  'tour-sidebar-repo',
] as const

export type TourAnchorId = (typeof TOUR_ANCHOR_IDS)[number]

/** CSS 选择器（给真实浏览器量测 / CDP 探针用） */
export function tourSelector(id: TourAnchorId): string {
  return `[${TOUR_ATTR}="${id}"]`
}

/**
 * 取锚点元素。
 *
 * ★ 返回 `null` 表示「此刻没挂载」，**不是**错误 —— 调用方（TourHost）据此决定
 *   「跳这一步并如实记录原因」还是「先做布局准备再重试」。
 *   ⚠️ 不要在这里塞任何 fallback（换父节点 / 取近似盒子）：一旦容错，
 *   锚点漂移就再也查不出来了。
 */
export function queryTourAnchor(id: TourAnchorId): HTMLElement | null {
  if (typeof document === 'undefined') return null
  return document.querySelector<HTMLElement>(tourSelector(id))
}
