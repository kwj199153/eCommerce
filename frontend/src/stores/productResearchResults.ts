/**
 * 选品分析师结果池（按 toolId 保存最近一次生成结果 / 生成中状态）
 *
 * 第 312 轮：选品分析师对齐 AIGC 大屏双模式范式 —— 大屏模式下结果只进右栏
 * 结果窗口、不进对话流。三个工具（market-insight / blue-ocean / profit-calc）
 * 的配置面板由 TaskConfigPanel 用 `v-else-if` 挂载，切换工具即销毁重建，
 * 结果存组件内会随销毁归零。提到 store 与组件生命周期解耦。
 *
 * 与 chatStore 的分工（同 aigcResults）：
 * - 对话模式：结果卡进对话流，chatStore 也持有同一份对象
 * - 大屏模式：orchestrator `skipChatStream`，结果根本不进对话流 → 此处是唯一持有者
 *
 * 注意：存的是 `product-research-result-ready` 透传的**同一个对象引用**（不做拷贝）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useProductResearchResultsStore = defineStore('productResearchResults', () => {
  /** { [toolId]: result } —— 按工具 id 存最近一次结果 */
  const byTool = ref<Record<string, any>>({})
  /** { [toolId]: boolean } —— 生成中状态（大屏结果窗口据此转圈） */
  const generating = ref<Record<string, boolean>>({})

  function setResult(toolId: string, result: any) {
    if (!toolId) return
    byTool.value[toolId] = result
  }

  function getResult(toolId: string): any {
    return byTool.value[toolId] ?? null
  }

  function clearResult(toolId: string) {
    if (!toolId) return
    delete byTool.value[toolId]
  }

  function setGenerating(toolId: string, value: boolean) {
    if (!toolId) return
    generating.value[toolId] = value
  }

  function isGenerating(toolId: string): boolean {
    return Boolean(generating.value[toolId])
  }

  // ====== window 事件桥（全局唯一）======
  // 放在 store 而非组件里是关键：监听器不随组件销毁而移除，
  // 所以「生成中途切走工具」也不会丢掉即将到达的结果。
  if (typeof window !== 'undefined') {
    window.addEventListener('product-research-result-ready', (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.toolId) setResult(detail.toolId, detail.result)
    })
    window.addEventListener('product-research-generating', (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.toolId) setGenerating(detail.toolId, Boolean(detail.generating))
    })
  }

  return { byTool, generating, setResult, getResult, clearResult, setGenerating, isGenerating }
})
