/**
 * 最近结果槽（Recent Result）
 *
 * 为什么需要：
 * 对话是 append-only 的线性流——结论会被后来的消息冲出视野，执行
 * `clearMessages()` 后更是彻底消失。而「刚才那次分析到底得出了什么」
 * 是高频回溯诉求。这里按 agentId 存一份**最近一次结构化结论**，
 * 供中列顶部的「最近结果」条一键找回。
 *
 * 与 chatStore 的分工：
 * - chatStore 存对话流水（可被清空）
 * - 本 store 存结论本身（独立存活，清空对话后仍可找回）
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface RecentResult {
  /** 展示类型（决定用哪张结论卡渲染），如 blue_ocean_analysis */
  displayType: string
  /** 结构化载荷（后端 meta.data），可能为空（持久化配额不足时降级） */
  data: any
  /** 一行摘要，供顶部条展示 */
  summary: string
  /** 写入时间戳 */
  ts: number
}

const STORAGE_KEY = 'agent_recent_results'

export const useRecentResultStore = defineStore('recentResult', () => {
  // { [agentId]: RecentResult }
  const byAgent = ref<Record<string, RecentResult>>({})

  const _persist = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(byAgent.value))
    } catch {
      // 配额超限（结果 data 可能很大）：降级为只存摘要，避免「找回入口」整体失效
      try {
        const slim: Record<string, RecentResult> = {}
        for (const [agentId, item] of Object.entries(byAgent.value)) {
          slim[agentId] = { ...item, data: null }
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
      } catch {
        // 连摘要都存不下就放弃持久化，内存态仍然可用
      }
    }
  }

  const _restore = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) byAgent.value = JSON.parse(raw) || {}
    } catch {
      byAgent.value = {}
    }
  }

  /** 写入某 Agent 的最近结果（摘要缺省时从 data.summary 提取） */
  const setRecent = (
    agentId: string,
    payload: { displayType: string; data?: any; summary?: string },
  ) => {
    if (!agentId || !payload?.displayType) return
    byAgent.value[agentId] = {
      displayType: payload.displayType,
      data: payload.data ?? null,
      summary: payload.summary || payload.data?.summary || '',
      ts: Date.now(),
    }
    _persist()
  }

  const getRecent = (agentId: string): RecentResult | undefined => byAgent.value[agentId]

  /** 清除某 Agent 的最近结果（「最近结果」条上的关闭按钮） */
  const clearRecent = (agentId: string) => {
    delete byAgent.value[agentId]
    _persist()
  }

  _restore()

  return { byAgent, setRecent, getRecent, clearRecent }
})
