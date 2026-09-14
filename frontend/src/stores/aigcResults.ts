/**
 * AIGC 结果池（按 toolId 保存最近一次生成结果 / 生成中状态）
 *
 * 为什么需要（09-14 老板报的 bug）：
 * 三个 AIGC 配置面板由 TaskConfigPanel 用 `v-else-if` 挂载 —— 切换工具即销毁重建。
 * 结果原本存在组件内的 `ref(null)`，组件一销毁就归零，于是
 * 「切走再切回来，刚生成的素材 / 脚本 / 视频就没了」。
 * 把结果提到 store，与组件生命周期解耦：切工具只是换了个消费方，数据仍在。
 *
 * 与 chatStore 的分工：
 * - 对话模式：结果卡进对话流，chatStore 也持有同一份对象
 * - 大屏模式：orchestrator `skipChatStream`，结果**根本不进对话流** → 此处是唯一持有者
 *
 * 注意：存的是 `aigc-result-ready` 透传的**同一个对象引用**（不做拷贝），
 * 所以分镜表就地编辑仍天然两端同步，不需要任何回写/同步代码。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAigcResultsStore = defineStore('aigcResults', () => {
  /** { [toolId]: result } —— 按工具 id 存最近一次结果 */
  const byTool = ref<Record<string, any>>({})
  /** { [toolId]: boolean } —— 生成中状态（大屏预览区据此转圈） */
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
  // 放在 store 而非组件里是关键：监听器不再随组件销毁而移除，
  // 所以「生成中途切走工具」也不会丢掉即将到达的结果。
  // store 是单例，这段只会执行一次。
  if (typeof window !== 'undefined') {
    window.addEventListener('aigc-result-ready', (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.toolId) setResult(detail.toolId, detail.result)
    })
    window.addEventListener('aigc-generating', (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.toolId) setGenerating(detail.toolId, Boolean(detail.generating))
    })
  }

  return { byTool, generating, setResult, getResult, clearResult, setGenerating, isGenerating }
})
