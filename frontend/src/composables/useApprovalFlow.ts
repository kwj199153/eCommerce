/**
 * HITL 审批决策编排（第 131 轮 · item2-C）
 *
 * 为什么单独一个模块，而不是写进 `useChatOrchestrator.ts`：
 *   后者已 1574 行且是对话主链路。第 131 轮任务书 item 7 明确要求
 *   「按域拆、不要在里面继续加分支」。审批决策 → API → 续跑消息
 *   是一条**独立**的域，自成模块后主链路不再增长，而且门禁
 *   （`scripts/check-hitl-approval.cjs`）能对这一个文件单独断言。
 *
 * ★ 它解决的是什么问题（这是本模块存在的唯一理由）：
 *   审批卡上点「批准」**不是在说话**。被 `interrupt()` 冻结的图停在
 *   `tool_node` 上，等的是一个 `Command(resume=...)`。如果像普通对话那样
 *   再发一句 `/chat`，只会**开一轮全新对话**，那个待审批的操作永远挂着 ——
 *   而且不报任何错（前端还会显示「已批准执行」）。所以必须走
 *   `POST /product-research/approval/resume`。
 *
 * ★ 三条诚实性约束（都是「宁可报错，不要假装成功」）：
 *   ① `sessionId` 缺失 ⇒ **不发请求**，直接回报错并在对话里说明。
 *      没有会话 ID 就无法恢复那张图，发出去也只会得到「没有可用会话」。
 *   ② 请求失败 ⇒ **必须回写界面**（追加一条 assistant 消息说明失败原因）。
 *      只弹 toast 的话，卡片会停在「已批准」的样子上，而操作从未执行 ——
 *      这正是本轮要消灭的「假成功提示」。
 *   ③ 结果原样展示后端返回的 `reply`，**不本地编造**「已入库」这类结论。
 */
import { useChatStore } from '@/stores/chat'
import { resumeAgentApproval, type ApprovalDecision } from '@/api/agentApproval'

/**
 * 四档决策，与后端 `ApprovalResumeRequest.decision` 的 `Literal` 逐字一致。
 *
 * ★ 第 400 轮：**定义搬到了 `api/agentApproval.ts`**，这里只做转发。
 *   搬走的原因是它原来在 `api` 与 `composable` 各写了一份 —— 同一份四档契约
 *   两份实现，改一处漏一处的表现是「类型检查过了、后端 422」。
 *   转发而不是让消费方改路径，是为了不惊动 `PendingApprovalCard.vue` 的 import。
 */
export type { ApprovalDecision }

export interface ApprovalSubmitOptions {
  /** 会话 ID —— 必须与**首轮**那次对话的同一个（后端按它重算 thread_id） */
  sessionId: string
  /**
   * 哪个 Agent 的审批（第 400 轮 P0-2）。
   *
   * ★ 由**服务端**在审批 payload 的 `data.agent` 里下发，前端不猜当前页面 ——
   *   同一张卡可能在多 Agent 编排里出现；猜错的后果是"点了批准 404"。
   *   缺省（老 payload 没有这个字段）退回 `product-research`，
   *   兼容改造前已发布的卡片。
   */
  agentId?: string
  decision: ApprovalDecision
  /** decision=reject：拒绝原因 */
  reason?: string
  /** decision=edit：改写后的工具入参 */
  args?: Record<string, any>
  /** decision=response：直接回复内容 */
  feedback?: string
}

export interface ApprovalSubmitResult {
  ok: boolean
  message: string
}

/**
 * 提交一次**澄清回答**（第 400 轮 P0-3）。
 *
 * ★ 为什么复用同一个续跑出口而不是新开一个端点/函数体：
 *   澄清与审批停的是**同一张图**，续跑动作也完全相同 —— 都是
 *   `POST /agents/{agent}/approval/resume` 带 `Command(resume=...)`。
 *   区别只在续跑值的形状，而形状由**服务端**看图判断（`_pending_kind`）。
 *   前端多一条实现，就是多一处会与后端漂移的地方。
 *
 * ★ 为什么这里传 `decision: 'response'`：后端在「停在澄清上」时**不读**
 *   `decision`（它读 `feedback`）。这个取值只是为了让请求体满足通用模型
 *   （`decision` 是必填）。若哪天服务端判定失效退化成审批路径，
 *   `response` 也是四种里语义最近的一档 —— 而不是让请求直接 422。
 */
export async function submitClarificationAnswer(opts: {
  sessionId: string
  agentId?: string
  answer: string
}): Promise<ApprovalSubmitResult> {
  const text = (opts.answer || '').trim()
  if (!text) {
    // 空回答**不发请求**：喂给模型一个空串，它会再问一遍 —— 老板会以为"没反应"。
    return { ok: false, message: '回答不能为空。' }
  }
  return submitApprovalDecision({
    sessionId: opts.sessionId,
    agentId: opts.agentId,
    decision: 'response',
    feedback: text,
  })
}

/**
 * 提交一次审批决策，并把结果续进对话。
 *
 * 调用方（审批卡）只负责 UI 与本地校验；「怎么发、发完往哪儿写、失败怎么办」
 * 全部收在这里 —— 这样「审批后行为」只有一份实现。
 */
export async function submitApprovalDecision(
  opts: ApprovalSubmitOptions,
): Promise<ApprovalSubmitResult> {
  const { sessionId, agentId, decision, reason, args, feedback } = opts
  const chatStore = useChatStore()

  // ① 前置校验：没有会话 ID 就不发请求。
  //    这里**刻意不**退回 `/chat` —— 那条路只会开一轮新对话，
  //    用户会看到「已处理」但待审批的操作其实还挂着。
  if (!sessionId) {
    const msg =
      '无法提交审批：这条待审批操作没有关联的会话 ID，无法恢复被挂起的操作。请重新发起一次。'
    chatStore.addMessage({ role: 'assistant', content: `❌ ${msg}` })
    return { ok: false, message: msg }
  }

  // `edit` 必须带非空入参：后端会回 422，这里提前拦（少一次往返，文案也更具体）
  if (decision === 'edit' && (!args || !Object.keys(args).length)) {
    const msg = '改写并执行需要提供修改后的工具入参（不能为空）。'
    chatStore.addMessage({ role: 'assistant', content: `❌ ${msg}` })
    return { ok: false, message: msg }
  }

  try {
    // ★ 第 400 轮 P0-2：走**通用**端点 `/agents/{agent}/approval/resume`。
    //   改造前这里打的是 `/product-research/approval/resume` —— 于是客服的
    //   `create_ticket` 审批卡点下去必然 404，而界面会显示"已提交"。
    const resp: any = await resumeAgentApproval(agentId, {
      // ⚠️ 字段名必须与后端 `ApprovalResumeRequest` 同名（snake_case）。
      //    写成 camelCase 会被 Pydantic 丢掉 → 必填缺失 → 稳定 422。
      context_id: sessionId,
      decision,
      reason,
      args,
      feedback,
    })

    const reply = resp?.reply || resp?.content || ''
    chatStore.addMessage({
      role: 'assistant',
      content: reply || '操作已处理。',
      data: resp?.data,
      displayType: resp?.display_type || undefined,
    })
    return { ok: true, message: reply }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '未知错误'
    const msg = `审批提交失败：${detail}`
    // ② 失败必须落到对话里。只弹 toast 会让卡片保持「已批准」的假象。
    chatStore.addMessage({ role: 'assistant', content: `❌ ${msg}` })
    return { ok: false, message: msg }
  }
}
