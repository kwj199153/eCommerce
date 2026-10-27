/**
 * 审批续跑的**通用** API（第 400 轮 P0-2）。
 *
 * ## 为什么新开一个模块，而不是继续用 `api/productResearch.ts`
 *
 * 改造前 `resumeApproval` 打在 `/product-research/approval/resume` 上 ——
 * 于是「能点批准」这件事被绑死在选品分析师身上。智能客服的 `create_ticket`、
 * trade 域的 `propose_review_disposition` 同样会被 `interrupt()` 挂起，
 * 但它们**没有**任何端点能放行（点了批准什么也不会发生）。
 *
 * 后端现在有通用端点 `POST /api/v1/agents/{agent}/approval/resume`，
 * 本模块是它在前端的唯一入口。
 *
 * ## 铁律
 *
 * ① 字段名必须与后端 `ApprovalResumeRequest` **逐字一致**（snake_case）。
 *    写成 camelCase 会被 Pydantic 丢掉 ⇒ 必填缺失 ⇒ 稳定 422。
 * ② `agent` 走**路径**而不是请求体：这样网关/日志能按 agent 归集，
 *    而前端也不必在一个"万能"接口里传一堆路由信息。
 * ③ `agent` **必须由服务端下发的 `data.agent` 提供**（见
 *    `modules/hitl/hitl.py::pending_approval_payload`），不由前端猜
 *    "当前在哪个页面" —— 同一张卡可能在多 Agent 编排里出现。
 *    取不到时退回 `product-research`（旧 payload 没有这个字段，兼容已发布版本）。
 */
import { get, post } from '@/api/request'

/** 四档决策，与后端 `modules/hitl/hitl.py::build_resume_payload` 的取值逐字一致 */
export type ApprovalDecision = 'accept' | 'reject' | 'edit' | 'response'

/** 老 payload 没有 `agent` 字段时的兜底（改造前唯一支持的 Agent） */
export const DEFAULT_APPROVAL_AGENT = 'product-research'

export interface ResumeApprovalPayload {
  /** 后端 `ApprovalResumeRequest.context_id` —— 与首轮对话同一个 */
  context_id: string
  decision: ApprovalDecision
  reason?: string
  args?: Record<string, any>
  feedback?: string
}

export interface ResumeApprovalResult {
  reply: string
  display_type?: string
  data?: Record<string, any>
}

/**
 * 回传一次审批决策。
 *
 * @param agent `data.agent`（服务端下发）；空值退回默认 Agent
 */
export async function resumeAgentApproval(
  agent: string | undefined | null,
  payload: ResumeApprovalPayload,
): Promise<ResumeApprovalResult> {
  const id = (agent || '').trim() || DEFAULT_APPROVAL_AGENT
  // `encodeURIComponent`：agent 里出现 `/`、`?` 会把路径改掉（租户/agent 名
  // 将来若带上这类字符，直接拼字符串会静默打到别的端点）
  return post<ResumeApprovalResult>(
    `/agents/${encodeURIComponent(id)}/approval/resume`,
    payload,
  )
}

/**
 * 哪些 Agent 支持审批续跑（排查 / 能力发现用）。
 *
 * ★ 存在的理由：前端**不该**硬编码一份"支持审批的 Agent 名单" ——
 *   那份名单一定会与后端漂移，而漂移的表现是"点了批准 404"。
 */
export async function listApprovalChannels(): Promise<string[]> {
  const resp: any = await get('/agents/approval/channels')
  return resp?.agents ?? []
}
