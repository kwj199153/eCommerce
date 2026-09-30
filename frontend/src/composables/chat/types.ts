/**
 * 对话编排层 · 共享类型（第 169 轮 #664「按域拆编排器」）
 *
 * 原来这一切都在 `composables/useChatOrchestrator.ts` 一个 1,744 行的巨型闭包里
 * （一个 `useChatOrchestrator()` 函数包住 5 个 store、30 个返回值、9 条 Agent 回复链路）。
 * 拆开后，本文件只放**两个域之间要共享的形状**，不放任何实现。
 *
 * ★ `ChatCtx` 为什么用「稳定 thunk + 装配期回填」而不是让各域互相 import：
 *   动作条要调 `handleSend`、事件桥要调 `runAgentReply`、回复链路要调 `ensureCandidateLoaded`
 *   —— 三者两两成环。若让它们互相 import，只能靠「谁先 import 谁」的偶然顺序；
 *   而且更深的问题是：**同一个 handler 只能有一份实现**（否则 loading 看门狗会被
 *   两份实现各管一半）。所以这里定义一份 thunk，由编排壳在装配期 `set` 进去。
 *
 * ★ 回填前被调用 ⇒ **抛错**（`[编排层] xxx 在装配完成前被调用`），不静默。
 *   装配是同步完成的，用户操作一定在之后 ⇒ 这个异常只会在「编排顺序写错」时出现，
 *   也就是我们确实想立刻知道的那类 bug。
 */
import type { ComputedRef, Ref } from 'vue'
import type { ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import type { ThinkingStep } from '@/api/stream'

/**
 * 本次请求的「作用对象」（第 251 轮）—— 前端**唯一**的结构化来源。
 *
 * ★ 三态由 `ChatCtx.contextTarget` 承载（`undefined` / `null` / 对象），
 *   含义与后端 `ContextTargetPayload` 一一对应，不能压成两态：
 *   `undefined` = 本 Agent 不参与该机制（请求体里**不带**这个字段），
 *   `null` = 参与但本次**明确没有**对象。
 *   后端正是靠后者去挡「点名的技能需要对象却没给」那条路径 ——
 *   把两者压成一个，门禁就只在"新客户端"上生效。
 *
 * ★ 第 257 轮：参与该机制的 Agent 从 1 个扩到 3 个，于是 `label` 有两个取值：
 *   选品分析师用「候选选品」（来源 `workingCandidate`），
 *   Listing 优化师 / AIGC 媒体生成器用「工作商品」（来源 `workingProduct`）。
 *   ★ 这两个词都是**业务词**，由前端填、后端原样渲染 —— 机制层不认识它们。
 */
export interface ContextTargetPayload {
  /** 类型的人话名（「候选选品」/「工作商品」）。机制层原样渲染 ⇒ 业务词不必下沉到 ai_infra */
  label: string
  /** 展示名（如候选标题 / 商品标题） */
  title: string
  /** 机器可识别的标识（如商品编号）。后端判"有没有"只看 title / ref */
  ref: string
  /** 补充数据（第 272 轮）：本次作用对象的**具体字段**（类目/五点/库存/价格等）。
   *  机制层原样渲染给模型，不解析 —— 于是「载入产品」的完整数据能随技能一起
   *  传到模型，而不只是标题+标识。可选，未提供时不影响既有行为。 */
  detail?: Record<string, unknown>
}

export interface ChatOrchestratorOptions {
  /** 输入框内容：v-model 绑在组件模板上，须由组件持有 */
  inputMessage: Ref<string>
  /** 消息滚动容器：模板 ref，须由组件持有 */
  messageListRef: Ref<HTMLElement | undefined>
  /** 主内容区容器：模板 ref，须由组件持有 */
  mainContentRef: Ref<HTMLElement | undefined>
  /** 竞品监控分析周期：v-model 绑在组件模板上，须由组件持有 */
  intelDays: Ref<number>
  /** 选品分析师当前载入的评估主角：inject 自 Workspace，须由组件注入后传入 */
  loadedCandidate: Ref<any>
  /**
   * Listing 优化师 / AIGC 媒体生成器当前载入的**工作商品**（第 257 轮）。
   *
   * ★ 与 `loadedCandidate` 完全同构：值来自 `Workspace.vue` 的
   *   `provide('workingProduct', …)`，须由组件 inject 后传入 —— 编排层自己
   *   不 inject（「组件持有、注入后传入」是本文件既有的约定，两条通道保持一致）。
   * ★ 为什么它现在要进编排层：这条 ref 此前只喂右栏的工具入参（表单预填），
   *   而**对话链路拿不到它** —— 于是「在顶部载入了商品、然后只说『帮我优化标题』」
   *   时，模型只能从用户消息里猜品名。第 257 轮把它接进 `contextTarget`，
   *   对话与右栏从此看的是**同一个**对象。
   */
  workingProduct: Ref<any>
  /**
   * 智能客服当前处置的**差评**（第 298 轮）。
   *
   * ★ 与 `loadedCandidate` / `workingProduct` 同构：值来自 `Workspace.vue` 的
   *   `provide('workingReview', …)`，须由组件 inject 后传入 —— 编排层自己不 inject
   *   （「组件持有、注入后传入」是本文件既有的约定，三条通道保持一致）。
   * ★ 为什么客服也需要它：差评应对技能第 0 步是
   *   `get_customer_review_context(review_id)`，而 `review_id` 此前只能来自
   *   用户消息文本或**会话历史** —— 台账里明明选中了某条、界面还写着
   *   「在对话里直接问」，对话却只能靠模型从历史里挑一条顶上。
   */
  workingReview: Ref<any>

  /**
   * 「取消本次作用对象」的三个写口（第 298 轮 · 老板 bug2：
   * 「上下文被某条处置差评填入后，你没有给取消按钮」）。
   *
   * ★★ 为什么必须由组件 inject 后传入、而不是在编排层里 inject：
   *   与上面三个 Ref 同源同约定（`provide` 在 `Workspace.vue`，
   *   组件注入后传入编排层）。三个写口是 `provide` 成对给出的
   *   （`set*` / `clear*`），只打通 `set` 不通 `clear` 就是本条 bug 的形态：
   *   **对象载得进来、出不去**。
   *
   * ★ 为什么给三个而不是一个 `clearScopeTarget()`：本层是**哑管线**，
   *   「当前 Agent ↔ 哪一份对象」的映射只允许有一处实现，那一处在
   *   `useAgentShortcuts`（`contextTarget` 的唯一产地）。在这里按 Agent 分派
   *   = 把同一条判定抄成两份，将来加第四个载入型 Agent 必然漏一处。
   *
   * ★ 默认 `noop`：`provide` 缺位（单测直接挂组件）时「点了没反应」，
   *   而不是抛错把整条链带崩 —— 与三个 Ref 的默认值口径一致。
   */
  clearWorkingCandidate?: () => void
  clearWorkingProduct?: () => void
  clearWorkingReview?: () => void
}

/** 各域模块共享的运行时上下文。字段由 `useChatOrchestrator` 按依赖顺序填入。 */
export interface ChatCtx extends ChatOrchestratorOptions {
  /** 加载态。动作条 chip 用它做重入保护（`if (isLoading.value) return`） */
  isLoading: Ref<boolean>

  // —— 生成流的生命周期（第 241 轮：可取消）——

  /**
   * 是否有**活跃的生成流**。
   *
   * ★★ 与 `isLoading` 是**两回事**，不能互相替代：店秘书 / 选品 / Listing / 广告 /
   *   客服 / 竞品 六条链都在**首个 token 到达时**就 `setLoading(false)` 了（spinner
   *   退场），可流还在跑 ⇒ 只看 `isLoading` 会得出「已经结束」的错误结论。
   *   「停止生成」按钮的显隐必须读这个。
   */
  isStreaming: Ref<boolean>
  /** 开一次生成流，返回本次流的信号（交给 `streamSSE` 第 4 个参数） */
  beginStream: () => AbortSignal
  /** 收一次生成流（正常 / 失败 / 取消都走这里）。幂等 */
  endStream: (signal: AbortSignal) => void
  /**
   * 取消纪元快照（读 `.value` 取当前值）。
   *
   * ★ 为什么需要它：`fetch` 能真正中断，但**结构化的 axios 调用不能** ——
   *   只能让等待中的那一段在回来时自我否决（否则点了停止，十几秒后答案又冒出来）。
   *   用法：await 之前 `const e0 = ctx.cancelEpoch.value`，之后 `ctx.isCancelledSince(e0)`。
   */
  cancelEpoch: Ref<number>
  /** 「自 e0 起用户是否按过停止」。全仓唯一的纪元判定实现（在 runtime 里） */
  isCancelledSince: (epoch: number) => boolean
  /** 后端 progress 事件写的阶段文案；SSE 各分支的 `onProgress` 都写它 */
  loadingStatus: Ref<string>
  /** tool / chat 模式；工具执行事件会切到 'tool' */
  currentMode: Ref<'tool' | 'chat'>
  /** 当前选中的工具；由 tool-analysis 事件写入 */
  selectedTool: Ref<ToolDefinition | null>
  /** 统一加载闸门（内含 60s 看门狗）—— **只此一份实现** */
  setLoading: (on: boolean, source: string) => void
  /** 滚动到底部。滚动容器是 `.main-content` 而不是 `.message-list`，别取错 */
  scrollToBottom: () => Promise<void>
  /** SSE meta → 结论卡/最近结果的回填（一处分发、两处落点） */
  handleAgentMeta: (meta: { display_type?: string; data?: any }) => void
  /**
   * SSE step → 当前消息的「思考过程」轨迹（第 210 轮）。
   * ★ 与 `handleAgentMeta` 同样必须**只有一份实现**（在 runtime 里）。
   */
  handleThinkingStep: (step: ThinkingStep) => void

  /**
   * 卡片点名的技能（存 `skills.name`，**不是** id）。
   *
   * ★ 为什么要有这条通道（第 189 轮 · 第 4/5 面）：
   *   动作条上的卡片现在**就是技能**（「skill 当源」）。点一张卡 = 指名让后端把该技能
   *   的正文注入 system prompt，而不是把正文塞进用户消息。
   *   `handleSend` 还有两个**没有技能可传**的入口（键盘 Enter / 发送按钮）⇒ 不能把
   *   技能做成它的必填参数。改用一条「待消费」通道：点卡时置入、发送时消费，
   *   两个非卡片入口自然拿到 `null`。
   * ★★★ **第 249 轮语义变更：从「一次请求」改成一个「任务」**（老板报障驱动）。
   *
   *   旧语义是「消费即清空」。它保护的是：点过卡之后再手动打字发消息，不会**继续带着
   *   上一张卡的技能**发出去而用户看不见这个残留。
   *
   *   但点名的真实生命周期是**一个任务**：`review-action-plan`（行动计划）这类技能的
   *   适用条件本身就写着「已经产出了复盘结论」⇒ 第一轮 Agent 必然追问「基于哪份复盘」、
   *   第二轮用户才回答。旧语义在第一轮就把点名清掉了，于是第二轮：
   *     ① `is_skill_requested()` 变回 false ⇒ 关键词短路重新生效；
   *     ② 用户的**回答**（"基于月报"）被当成**新任务指令**，命中 `monthly_review`；
   *     ③ 输出的是一张**月度复盘卡** —— 而且永远如此（用户按追问回答就必然撞关键词）。
   *   ⇒ 这不是概率问题，是**结构性不可达**：那条技能永远拿不到。
   *
   *   新语义 = 点名保持到「任务结束」，两条清除条件（都是**确定的、非猜测的**）：
   *     · **本轮产出了结果**（`replies/index.ts` 的 `turnProducedResult`，判据与后端
   *       「追问 ⇒ display_type='text' 且无 data」同口径）；
   *     · **切换 Agent**（点名是按 `agent_name` 生效的技能名，跨 Agent 无意义）。
   *   ⇒ 残留窗口从「永久」收窄到「一次追问之内」，第 189 轮那条理由的代价量级被压掉。
   *   而代价的**两方向不对称**（残留 = 用户再点一次就好；丢失 = 结构性拿不到）
   *   决定了选安全的一侧。
   */
  pendingSkill: Ref<string | null>
  /** 点卡时**点名**一个技能。传 `null` = 清空（丢弃尚未消费的点名） */
  setPendingSkill: (name: string | null) => void
  /**
   * 取出点名但**不清空**。**全仓唯一的读取点**（在回复分派器开头），`null` = 非点卡触发。
   * 是否清除由分派器在本轮结束时按「有没有产出结果」决定 —— 见上方语义说明。
   */
  peekPendingSkill: () => string | null
  /** 清空点名。仅两个调用点：本条任务产出结果之后 / 切换 Agent 时 */
  clearPendingSkill: () => void

  /**
   * 本次请求的「作用对象」（第 251 轮）。
   *
   * ★ 为什么要它：前端原先把「这次针对谁」只表达成**一句话**拼进用户消息
   *   （`（评估对象：X）` / `（未载入选品（…））`），后端既不解析也不校验；
   *   又因为点名技能时强制走带**全量会话历史**的工具环路，模型从历史里
   *   「续」上了上一轮的对象 —— 实测「没载入选品」却答出了上架建议，
   *   商品名还是那个设备从没选过的。
   * ★ 三态（`undefined` / `null` / 对象）与后端 `ContextTargetPayload`
   *   一一对应，见 `ContextTargetPayload` 的注释与
   *   `ai_infra/context_target.py` 的模块 docstring。
   *
   * ★★ 第 257 轮：参与该机制的 Agent 从 1 个扩到 3 个
   *   （选品分析师 / Listing 优化师 / AIGC 媒体生成器）。
   *
   *   起因（老板报障 + 截图）：Listing 与 AIGC 的上下文条都显示
   *   「（无上下文参数）」—— 而这两个 Agent 同样要先选一个商品才能开工。
   *   取证结论：**不是取舍，是疏漏**（第 251 轮那条链五层全只接了选品）。
   *
   *   ★ 三态的**语义一个字都没变**，变的是"谁参与"：`undefined` 仍是
   *     「本 Agent 不参与」，只是现在只有其余 5 个 Agent 会拿到它。
   *   ★ ⚠️ AIGC 目前**没有对话链路**（分派器里它没有专属分支，兜底文案
   *     逐字写着「对话能力尚未接入」）⇒ 它现在会**产出**这个字段、由上下文条
   *     消费，但请求体还发不出去（没有可发的链路）。这不是本字段的缺陷，
   *     是那条链路尚未接（见 `replies/fallback.ts`）。后端端点已备好。
   */
  contextTarget: ComputedRef<ContextTargetPayload | null | undefined>

  // —— 以下三个是**装配期回填的稳定 thunk**，可安全解构 ——
  /** 把输入框内容发出去（动作条复用同一条发送链路） */
  handleSend: () => Promise<void>
  /** 直接跑一次 Agent 回复链路（事件桥的「路由带参续跑」用） */
  runAgentReply: (text: string) => Promise<void>
  /** 确保候选库已加载（动作条与选品回复链路共用） */
  ensureCandidateLoaded: () => Promise<void>
}

/**
 * 一个 Agent 回复分支的结局。
 *
 * ★ 必须区分，因为原实现是「一串 `if (agentId === …) { try { … return } catch { console.error } }`」
 *   —— **未 `return` 的 catch 会把控制流交给下一个 `if`**，最后落到「默认模拟响应」。
 *   这是有意为之的降级链（真后端挂了 → 本地兜底 → 通用提示），不是笔误；
 *   所以拆开后必须把「没接住」显式表达出来，否则降级链会被静默改成「什么都不做」。
 */
export type ReplyOutcome = 'handled' | 'fallthrough'
