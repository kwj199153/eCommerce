/**
 * 短视频带货脚本共享 store
 *
 * 短视频带货脚本工具生成的脚本，作为 AI 短视频生成「分镜脚本专业模式」的素材源。
 * - chatStore 工具执行结果（msg.data.resultData）通过 saveLastScript 写入
 * - VideoGeneratorConfig 通过 lastScript 读取后做场景转换
 *
 * 设计目标：打通工具链，单脚本 → 单视频的工作流闭环。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface VideoScriptScene {
  duration: number
  visual: string       // 画面描述
  narration: string    // 旁白文案
  cameraMovement: string
  shotSize?: string
  bgm?: string
  subtitleStyle?: string
  frameRef?: string
}

export interface LastVideoScript {
  productName: string
  productId?: string
  platform: string
  platformLabel: string
  videoStyle: string
  totalDuration: number
  scriptSummary: string
  storyboard: VideoScriptScene[]
  generatedAt: string
}

const STORAGE_KEY = 'last-video-script-v1'

function loadFromStorage(): LastVideoScript | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as LastVideoScript
  } catch (e) {
    console.warn('lastVideoScript 读取失败', e)
  }
  return null
}

function saveToStorage(script: LastVideoScript | null) {
  try {
    if (script) localStorage.setItem(STORAGE_KEY, JSON.stringify(script))
    else localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    console.warn('lastVideoScript 写入失败', e)
  }
}

export const useVideoScriptsStore = defineStore('videoScripts', () => {
  const lastScript = ref<LastVideoScript | null>(loadFromStorage())

  /**
   * 从工具执行结果写入最近脚本
   * 入参为 mock executeVideoScriptGen 的返回对象
   */
  function saveLastScript(result: any) {
    if (!result || result.type !== 'video_script_gen') return
    lastScript.value = {
      productName: result.product_name,
      productId: result.params?._sourceProduct?.id,
      platform: result.platform,
      platformLabel: result.platform_label,
      videoStyle: result.video_style,
      totalDuration: result.total_duration,
      scriptSummary: result.script_summary || '',
      storyboard: (result.storyboard || []).map((s: any) => ({
        duration: s.duration ?? 3,
        visual: s.visual ?? '',
        narration: s.narration ?? '',
        cameraMovement: s.cameraMovement ?? 'static',
        shotSize: s.shotSize ?? '',
        bgm: s.bgm ?? '',
        subtitleStyle: s.subtitleStyle ?? '',
        frameRef: s.frameRef ?? '',
      })),
      generatedAt: new Date().toISOString(),
    }
    saveToStorage(lastScript.value)
  }

  /** 清空最近脚本 */
  function clearLastScript() {
    lastScript.value = null
    saveToStorage(null)
  }

  /** 最近脚本的镜头数（用于 UI 显示「已有 N 镜可导入」） */
  const sceneCount = () => lastScript.value?.storyboard?.length || 0

  return { lastScript, saveLastScript, clearLastScript, sceneCount }
})