/**
 * 新手引导 · 进度状态机
 * =====================
 *
 * ★ 为什么单独一个 store 而不是塞进某个既有 store：
 *   本仓没有一个「用户偏好」store（19 个 store 全是业务域），为一个引导去给它加，
 *   等于给所有未来的偏好项开了个没人守口子的抽屉。引导自成一个小域更清楚。
 *
 * ★ 持久化只放 localStorage（老板拍板），**不引入后端表**。
 *   它的代价必须写明白：换浏览器 / 换设备 ⇒ 引导会重新出现。
 *   这是**可接受**的代价 —— 引导本来就该跟着"这个人在这台机器上是不是第一次来"走，
 *   而把它做成账号级反而会误伤（同一账号在同事机器上登录，不该被当成新用户）。
 *
 * ★ 状态在两个地方同时写进去，语义不同，不要合并：
 *   · `seen`   —— 这个浏览器**这辈子**有没有走过一遍（决定还要不要自动出现）
 *   · `running`—— 此刻是不是正在走（决定遮罩与气泡渲不渲染）
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { TOUR_STEPS, type TourStep } from '@/config/tourSteps'

const STORAGE_KEY = 'onboarding_tour_v1'
const VERSION = 1

/** 一步被跳过的原因（收尾时要**如实列出来**，不许静默吞掉） */
export interface TourSkip {
  stepId: string
  title: string
  reason: string
}

interface Persisted {
  v: number
  seen: boolean
  lastIndex: number
  ts: number
}

export const useTourStore = defineStore('tour', () => {
  /** 持久化：**是否已经听过一遍**。true ⇒ 不再自动出现（但可以手动重播） */
  const seen = ref(false)
  /** 是否走到了第几步（仅内存，用于 progress） */
  const index = ref(0)
  /** 是否正在走；UI 是否渲染遮罩/气泡的唯一开关 */
  const running = ref(false)
  /** 本次累积跳过的步骤 */
  const skips = ref<TourSkip[]>([])
  /** 当前高亮元素的视口矩形（由 TourHost 量完写进来，UI 只负责画） */
  const rect = ref<{ top: number; left: number; width: number; height: number } | null>(null)
  /** localStorage 是否已读取（首帧不要抢跑，否则会把默认 seen=false 写回去覆盖真值） */
  const hydrated = ref(false)

  const steps = computed(() => TOUR_STEPS)
  const total = computed(() => TOUR_STEPS.length)
  const current = computed<TourStep | undefined>(() => TOUR_STEPS[index.value])
  const isFirst = computed(() => index.value === 0)
  const isLast = computed(() => index.value >= TOUR_STEPS.length - 1)
  const progress = computed(() => `${Math.min(index.value + 1, TOUR_STEPS.length)}/${TOUR_STEPS.length}`)

  function persist() {
    try {
      const payload: Persisted = {
        v: VERSION,
        seen: seen.value,
        lastIndex: index.value,
        ts: Date.now(),
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
      /* 无痕模式 / 配额超限：退化为"本次会话内不重复出现"，不做别的补偿 */
    }
  }

  function hydrate() {
    if (hydrated.value) return
    hydrated.value = true
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) {
        seen.value = false
        return
      }
      const p = JSON.parse(raw) as Partial<Persisted>
      // 版本不同 ⇒ 当作没走过（步骤表变了，旧的"看过了"没有意义）
      seen.value = p.v === VERSION ? !!p.seen : false
    } catch {
      // 坏数据不当真，但也别把它当用户没看过 —— 走一次就好
      seen.value = false
    }
  }

  /** 从头开始（手动重播也走这里） */
  function start() {
    hydrate()
    index.value = 0
    skips.value = []
    rect.value = null
    running.value = true
  }

  /** 正常收尾：标记看过，落盘 */
  function finish() {
    running.value = false
    rect.value = null
    seen.value = true
    persist()
  }

  /** 中途退出（跳过 / Esc）：也算"见过"，不反复骚扰 */
  function abandon() {
    running.value = false
    rect.value = null
    seen.value = true
    persist()
  }

  function next() {
    if (index.value < TOUR_STEPS.length - 1) {
      index.value += 1
      return true
    }
    return false
  }

  function prev() {
    if (index.value > 0) {
      index.value -= 1
      return true
    }
    return false
  }

  /**
   * 记录一步被跳过。
   *
   * ★ 为什么必须带 `reason` 而不是只跳过：这也是本仓的纪律 ——
   *   引导最怕的不是"跳过"，是"跳过了却不说为什么"，用户回头发现某块没讲过，
   *   界面上没有任何线索解释。
   */
  function markSkip(stepId: string, title: string, reason: string) {
    skips.value.push({ stepId, title, reason })
  }

  function setRect(r: { top: number; left: number; width: number; height: number } | null) {
    rect.value = r
  }

  /** 抹掉"看过"标记（用于验证与排障，界面上的「重看」走 `start()` 即可） */
  function resetSeen() {
    seen.value = false
    index.value = 0
    persist()
  }

  return {
    seen,
    index,
    running,
    skips,
    rect,
    hydrated,
    steps,
    total,
    current,
    isFirst,
    isLast,
    progress,
    hydrate,
    start,
    finish,
    abandon,
    next,
    prev,
    markSkip,
    setRect,
    resetSeen,
  }
})
