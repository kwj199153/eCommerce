/**
 * 会话结论卡注册表
 *
 * 规则：对话里跑出的结构化结论（后端 SSE `meta` 下发 display_type + data）
 * 一律通过本表映射成卡片，模板里不散落 if-else。
 *
 * 与「工具结果卡」的关系 —— 同区、同规则，只是重量不同：
 * - 工具结果卡：key = toolId（右栏/顶部发起「开始分析」→ 结果内联进对话），带关闭按钮与密集表格
 * - 会话结论卡：key = display_type（直接在对话里提问 → 结论以卡承托），只读轻量
 * 两者都渲染在**对话消息流**里，都由一张映射表驱动渲染。
 *
 * 新增一个 Agent 的结论卡：写组件 → 在此登记一行 → 后端 stream_chat 补 meta。
 */

import type { Component } from 'vue'

import BlueOceanProductCard from './BlueOceanProductCard.vue'
import ProfitAnalysisCard from './ProfitAnalysisCard.vue'
import PainPointAnalysisCard from './PainPointAnalysisCard.vue'
import CompetitorAnalysisCard from './CompetitorAnalysisCard.vue'
import PendingApprovalCard from './PendingApprovalCard.vue'
import ReviewReportCard from './ReviewReportCard.vue'

export const CONVERSATION_RESULT_COMPONENTS: Record<string, Component> = {
  // 选品分析师
  blue_ocean_analysis: BlueOceanProductCard,
  profit_analysis: ProfitAnalysisCard,
  pain_point_analysis: PainPointAnalysisCard,
  competitor_analysis: CompetitorAnalysisCard,
  // 选品分析师 · HITL 人工审批（有副作用的工具被 interrupt() 挂起时由后端下发）
  pending_approval: PendingApprovalCard,
  // 运营复盘师 · 6 项复盘报告（后端 `REVIEW_REPORT_DISPLAY_TYPE = "review_report"`）
  //   ★ 键名必须与后端那个常量逐字一致 —— 不一致的后果是**静默按纯文本渲染**
  //     （`resolveConversationResult` 未登记返回 null），结构化 data 白白下发。
  //     这条对账由 `backend/tests/test_skill_shortcut_compat.py` 钉住。
  review_report: ReviewReportCard,
}

/** display_type → 组件；未登记的类型返回 null（按普通文本处理） */
export function resolveConversationResult(displayType?: string): Component | null {
  if (!displayType) return null
  return CONVERSATION_RESULT_COMPONENTS[displayType] || null
}
