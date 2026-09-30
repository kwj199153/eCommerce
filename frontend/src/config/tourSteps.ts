/**
 * 新手引导 · 步骤规格表
 * =====================
 *
 * ★ 与 `tourAnchors.ts` 的分工：
 *   · 锚点表回答「界面上有哪些可讲的位置」（id 的唯一真源）
 *   · 本表回答「按什么顺序讲、每一步讲什么」（主线的唯一真源）
 *   两张表由 `anchor` 字段关联；本表**不许**再写一遍 id 字符串。
 *
 * ★ `prepare` / `requires` 只是**声明**，判定实现不在这里
 *   （同一判定两份实现 ⇒ 至少一份永远测不到，本仓吃过这个亏）。
 *   两张表的消费者 `components/Tour/TourHost.vue` 各持一份技术实现：
 *     · `prepare` = 进入该步**之前**要做的布局准备（幂等）
 *     · `requires` = 进入该步**之后**必须成立的前置；不成立 ⇒ 跳过并如实记录原因
 *
 * ★ `narration` vs `body`：
 *   前者是念出来的话（口语、句子短、可以比正文啰嗦），后者是气泡里显示的字。
 *   刻意分成两个字段而不是全文朗读 —— 念书面语听着像机器人，
 *   而把口语塞进界面读起来又不专业。
 */

import type { TourAnchorId } from './tourAnchors'

/** 进入该步之前要做的布局准备（由 TourHost 执行，一律幂等） */
export type TourPrepare = 'ensure-sidebar' | 'ensure-right-panel' | 'goto-chat'

/**
 * 该步成立所需的前置条件（由 TourHost 判定，不满足则跳过）。
 *
 * ★ 这里**只允许出现 TourHost 真的能判的东西**：
 *   `currentView` 之类是 Workspace 的局部 ref、外部读不到，写在这就是一条
 *   永远评估不了的假门禁（比没有更糟——它看着像有）。
 *   「有没有切回对话视图」这类问题，改由「锚点元素在不在」这个直接事实来回答。
 */
export type TourRequire = 'agent-selected'

/** 气泡相对聚光圈的首选方位；空间不够时 TourTooltip 会自行翻转 */
export type TourPlace = 'right' | 'left' | 'bottom' | 'top'

export interface TourStep {
  /** 步骤 id（用于跳过记录与进度 1/N 之外的定位，保持稳定，不要复用） */
  id: string
  anchor: TourAnchorId
  title: string
  /** 气泡正文 */
  body: string
  /** 语音播报稿 */
  narration: string
  place?: TourPlace
  prepare?: TourPrepare
  requires?: TourRequire
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: 'welcome',
    anchor: 'tour-brand',
    title: '① 欢迎来到店管家 AI',
    body:
      '左上角是你的全局入口。中间的机器人头像随时带你回到「店秘书」——它负责听懂你想干什么、再把你交给合适的 Agent。' +
      '旁边那一长串里，后半截是你**当前所在的店铺**。',
    narration:
      '欢迎来到店管家。左上角是全局入口，点机器人头像随时回到店秘书，它负责听懂你想干什么，再把你交给合适的专员。' +
      '旁边显示的是你当前所在的店铺。',
    place: 'right',
    prepare: 'ensure-sidebar',
  },
  {
    id: 'shop-scope',
    anchor: 'tour-shop-switch',
    title: '② 切店铺 = 换一整套数据',
    body:
      '点这颗图标可以在你的店铺之间切换，角标是店铺数量。' +
      '**换店等于换作用域**：订单、资料库、复盘数据会整套跟着变。' +
      '所以动手之前先看一眼左上角现在挂的是哪个店。',
    narration:
      '点这颗图标可以在你的店铺之间切换，角标是店铺数量。换店等于换作用域，订单、资料库、复盘数据会整套跟着变。' +
      '所以动手之前，先看一眼左上角现在挂的是哪个店。',
    place: 'bottom',
    prepare: 'ensure-sidebar',
  },
  {
    id: 'agents',
    anchor: 'tour-agent-list',
    title: '③ 六个专员，各管一摊',
    body:
      '选品分析师帮你找货，Listing 优化师写文案，广告分析师管投放，智能客服处置差评，竞品监控盯同行，运营复盘师看经营。' +
      '选一个进去，它就是你现在唯一的工作台。',
    narration:
      '这里有六个专员，各管一摊：选品分析师帮你找货，Listing 优化师写文案，广告分析师管投放，智能客服处置差评，' +
      '竞品监控盯同行，运营复盘师看经营。选一个进去，它就是你现在唯一的工作台。',
    place: 'right',
    prepare: 'ensure-sidebar',
  },
  {
    id: 'chat-input',
    anchor: 'tour-chat-input',
    title: '④ 说人话就行，不用会写指令',
    body:
      '在这里交代一件事，就像跟同事说一句话。旁边麦克风可以**直接说话**，' +
      '不会写提示词就点「增强」帮你润色，回答到一半想打断点停止即可。',
    narration:
      '在这里交代一件事，就像跟同事说一句话。旁边的麦克风可以直接说话，不会写提示词就点增强，让它帮你润色。' +
      '回答到一半想打断，点停止就行。',
    place: 'top',
    prepare: 'goto-chat',
  },
  {
    id: 'chat-result',
    anchor: 'tour-chat-stream',
    title: '⑤ 答案会长出结构化卡片',
    body:
      '回复逐字出现的同时，结论会就地长成**可以下钻的结果卡**。' +
      '它可能被后来的消息顶上去——别慌，顶部那条「📌 最近结果」随时能把上一次的结论找回来。',
    narration:
      '回复逐字出现的同时，结论会就地长成一张可以下钻的结果卡。它可能被后来的消息顶上去，别慌，' +
      '顶部那条最近结果，随时能把上一次的结论找回来。',
    place: 'top',
    prepare: 'goto-chat',
  },
  {
    id: 'right-panel',
    anchor: 'tour-right-panel',
    title: '⑥ 参数是填的，不是猜的',
    body:
      '这一栏是当前专员的**任务参数**。左边负责说「要什么」，右边负责说「具体怎么算」。' +
      '万一不小心收起来了，对话窗口右上角那个箭头能把它叫回来。',
    narration:
      '右边这一栏是当前专员的任务参数。左边负责说要什么，右边负责说具体怎么算。' +
      '万一不小心收起来了，对话窗口右上角那个箭头能把它叫回来。',
    place: 'left',
    prepare: 'ensure-right-panel',
    requires: 'agent-selected',
  },
  {
    id: 'libraries',
    anchor: 'tour-sidebar-repo',
    title: '⑦ 你的家底都在侧边栏',
    body:
      '选品库、竞品池、素材库、自有产品库、话术库、复盘库、平台规则——你攒下来的东西都在这里，' +
      '而且**按当前店铺隔离**。下面「能力」一栏可以管理技能与工具。',
    narration:
      '你的家底都在侧边栏：选品库、竞品池、素材库、自有产品库、话术库、复盘库、平台规则，' +
      '都在这里，而且按当前店铺隔离。下面能力一栏，可以管理技能与工具。',
    place: 'right',
    prepare: 'ensure-sidebar',
  },
]
