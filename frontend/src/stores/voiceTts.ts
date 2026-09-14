/**
 * 语音播报（TTS）store —— 对话框右上角喇叭开关的后端。
 *
 * 形态：右上角一个喇叭按钮，打开后 **Agent 回复自动朗读**（复用该店铺已克隆的音色）。
 * 首期只服务「店秘书」（见 `VOICE_TTS_AGENTS`），效果满意后再扩到其他 Agent ——
 * 扩展方式**只改白名单**，调用方（编排层/按钮）一行都不用动。
 *
 * ---------------------------------------------------------------------------
 * ★★★ 分句流水线（P0+P1，2026-09-14 重构）
 * ---------------------------------------------------------------------------
 * 旧实现把**整段回复**一次性丢给 `/speak`，于是「等回复说完 → 再等合成 5.2s →
 * 才出声」，首声实测 **8.7s**。现在改成「逐段合成 + 逐段播放」：
 *
 *   喂入正文 ──► /speak-plan（纯计算，0.22ms）──► 已定型的段
 *              │                                     │
 *              │                          ┌──────────┘
 *              │                          ▼
 *              │                  【生产者】串行合成（必须串行：7 并发会被
 *              │                   DashScope 以 Throttling.RateQuota 拒掉大半）
 *              │                          │
 *              └──────── 正文继续增长 ─────┘
 *                                         ▼
 *                                【消费者】按段顺序播放
 *
 * 三条不变量（破坏任何一条都会出可见 bug）：
 *
 * 1. **游标必须用「原文坐标」**：流式期间会反复对「更长的原文」重算计划，
 *    所以用后端返回的 `raw_end` 当游标，`raw_end > cursor` 才算新段。
 *    用「第几段」这种序号会在重算时错位 → 重念或漏念。
 * 2. **只消费 `stable` 的段**：`stable=false` 说明这一段还在长，提前念会念半句，
 *    且下一轮会把同一句当新段再念一遍。
 * 3. **生产者必须串行**：见上，并行会被限流，反而更慢。
 *
 * 段间无缝接力用 **Web Audio 绝对时间轴**（不是「两个 <audio> 轮流」）：
 * 每段用 `source.start(t)` 排到上一段结束的确切时刻，采样级首尾相接 → 间隙 0。
 * 拿不到 AudioContext 时降级为 `<audio>` 串行接力（此时间隙由 `lastRunMetrics.gaps` 如实记录）。
 *
 * 另外三条来自项目铁律的设计约束：
 *
 * 1. **失败显式给原因，且不许静默换音色**。没有可用音色时不偷偷用系统默认音色顶上，
 *    而是明确告诉用户「当前店铺还没有克隆音色，去设置里创建」，并让开关保持关闭。
 * 2. **不静默丢内容**。正文超过朗读上限时后端会如实回报 `truncated`，这里转述给用户。
 * 3. **开关是用户偏好，不该丢**。落 localStorage，刷新后保持。
 *
 * 另外两个不显眼但必须处理的点：
 * - **并发令牌**（`runId`）：开关关掉 / 切店铺 / 新回复插队时，正在飞的合成请求
 *   与已排期的音频必须全部作废，否则会出现「已经关了还在念」。
 * - **自动失败即关闭**：失败若不自动关，每来一条回复就弹一次同样的错，变成刷屏。
 */

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { message } from 'ant-design-vue'

import { fetchSpeechPlan, fetchVoiceStatus, speakVoice } from '@/api/voiceClone'

/** 允许语音播报的 Agent（首期只有店秘书；扩展就是往这里加 id） */
export const VOICE_TTS_AGENTS: readonly string[] = ['secretary']

/** 播放状态机：idle 空闲 / checking 体检音色 / loading 合成中 / playing 播放中 */
export type VoiceTtsPhase = 'idle' | 'checking' | 'loading' | 'playing'

const STORAGE_KEY = 'voice_tts_enabled'

/** 音频 URL / 解码缓冲缓存上限（同一条回复重播不再打接口） */
const CACHE_LIMIT = 40

/**
 * ★ 段间间隙的**验收上限**（ms）。Web Audio 绝对时间轴下正常恒为 0；
 * 只有「生产者没赶上播放」才会出现正间隙，届时 `lastRunMetrics.gaps` 会如实记下来。
 */
export const TTS_MAX_GAP_MS = 50

/** 调度余量：给 `currentTime` 与调度之间留一点安全边界（秒） */
const SCHEDULE_LEAD_S = 0.04

/**
 * ★★ 计划器节流（不是优化，是**必需**）。
 *
 * 后端 `RateLimitMiddleware` 是**全局**固定窗口：`rate_limit_requests_per_minute = 60`
 * —— 按客户端 IP 算，**整个 App 的所有接口共用这 60 次/60s**。
 * 所以「正文每增长一点就调一次 `/speak-plan`」会在几秒内打光配额，
 * 实测直接拿到 `429 请求过于频繁，请 4 秒后重试（上限 60 次/60s）`。
 *
 * 节流的两条闸：
 * - `PLAN_MIN_GROWTH_CHARS`：正文每增长这么多字才算一次计划；
 * - `PLAN_MIN_INTERVAL_MS`：两次计划之间的最小间隔（同一时间窗内的增量合并）。
 *
 * 首声不受影响：**第一次**计划总是立刻发生（`lastPlanAt === 0`），
 * 节流只约束后续追赶。粗算一条 400 字回复 ≈ 10 次计划 + 4~5 次合成，配额安全。
 */
const PLAN_MIN_GROWTH_CHARS = 40
const PLAN_MIN_INTERVAL_MS = 500

/** 稳定的短哈希（给 `speak` 生成 runKey；只求稳定，不求抗碰撞） */
function hashText(s: string): string {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return `${s.length}:${(h >>> 0).toString(36)}`
}

/** 一轮播报的实测指标（验收用真实数字，不靠感觉） */
export interface TtsRunMetrics {
  /** 会话标识（= 编排层传来的消息 key） */
  runKey: string
  /** 本轮**第一次**喂入正文的时刻（`performance.now()`） */
  feedAt: number
  /** 首声时刻（`performance.now()`）；-1 = 本轮没发出声 */
  firstSoundAt: number
  /** 首声延迟（ms）；-1 = 本轮没发出声 */
  firstSoundMs: number
  /** 相邻段之间的实际间隙（ms）。恒 0 = 采样级首尾相接 */
  gaps: number[]
  /** 最大间隙（ms）；无间隙段时为 -1 */
  maxGapMs: number
  /** 本轮一共排了多少段 */
  segments: number
}

/** 队列里的一段（待合成 / 已合成待播） */
interface Utterance {
  text: string
  rawEnd: number
  /** 解析结果：`url` 一定非空（合成成功才有）；`buffer` 为 null 表示走 `<audio>` 降级 */
  ready: Promise<{ url: string; buffer: AudioBuffer | null } | null>
}

export const useVoiceTtsStore = defineStore('voiceTts', () => {
  /** 自动朗读开关（持久化） */
  const enabled = ref(readEnabled())

  const phase = ref<VoiceTtsPhase>('idle')

  /** 当前店铺是否有可用音色（体检结果，只作 UI 提示用） */
  const available = ref(false)

  /** 不可用的原因（原样来自后端 detail，不加工、不兜底） */
  const unavailableReason = ref('')

  const lastError = ref('')

  /** ★ 最近一轮播报的实测指标（首声延迟 / 段间间隙）—— 验收直接读它 */
  const lastRunMetrics = ref<TtsRunMetrics | null>(null)

  // ---- 非响应式内部状态（不要放进 ref：Audio 元素与 Vue 代理互相折磨） ----
  const urlCache = new Map<string, string>()
  const bufferCache = new Map<string, AudioBuffer>()

  let audioCtx: AudioContext | null = null
  let audioCtxUnavailable = false
  const liveSources = new Set<AudioBufferSourceNode>()
  const liveElements = new Set<HTMLAudioElement>()

  /** 并发令牌：任何「取消」动作 +1，落后于它的异步环节直接作废 */
  let runId = 0
  /** 当前轮次的消息标识 */
  let activeRunKey = ''
  /** ★ 原文坐标游标：`raw_end <= cursor` 的段都已入队（不是「已念完」） */
  let cursor = 0
  /** 待播队列（次序 = 原文次序） */
  let queue: Utterance[] = []
  /** 消费者已取走的段数 */
  let consumed = 0
  /** ★ 生产者串行链：下一段的合成必须等这一段完成 */
  let producerChain: Promise<void> = Promise.resolve()

  /** 最近一次喂进来的**完整正文**（每轮都拿它重算计划） */
  let pendingText = ''
  /** 已经为哪一长度的原文算过计划（避免同长度重复请求） */
  let plannedFor = 0
  let planBusy = false
  let planDirty = false
  /** 上一次真的发出计划请求的时刻（节流用，0 = 本轮还没发过） */
  let lastPlanAt = 0
  let planTimer: ReturnType<typeof setTimeout> | null = null
  /** 计划是否已「追平」正文（决定消费者能否收工） */
  let planSettled = true
  /** 正文是否已结束（决定结尾那段 `stable=false` 的碎片能否念） */
  let ended = false

  /** Web Audio 时间轴上「下一段最早可开始」的时刻 */
  let scheduledUntil = 0
  /** 上一段的计划结束时刻（算间隙用）；-1 = 本段是第一段 */
  let prevSchedEnd = -1
  /** `<audio>` 降级模式下的上一段真实结束时刻 */
  let lastEndedAt = -1

  let workSignal: (() => void) | null = null
  let idleTimer: ReturnType<typeof setTimeout> | null = null

  // 本轮指标
  let feedAt = 0
  let firstSoundAt = -1
  let gapLog: number[] = []
  let segCount = 0

  function readEnabled(): boolean {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  }

  function persistEnabled() {
    try {
      localStorage.setItem(STORAGE_KEY, enabled.value ? 'true' : 'false')
    } catch {
      /* 隐私模式下写不了，忽略：开关在本次会话内仍有效 */
    }
  }

  /** 该 Agent 是否支持语音播报（唯一判据在这里，别在调用方再写一遍） */
  function supports(agentId: string | undefined | null): boolean {
    return !!agentId && VOICE_TTS_AGENTS.includes(agentId)
  }

  /** 静默体检当前店铺音色（失败不弹提示 —— 没音色是正常情况，不是故障） */
  async function refreshAvailability(): Promise<boolean> {
    phase.value = 'checking'
    try {
      const rec = await fetchVoiceStatus(false, true)
      available.value = !!rec.ready
      unavailableReason.value = rec.ready
        ? ''
        : rec.error_msg ||
          (rec.exists
            ? `音色当前状态「${rec.status}」，还不可用`
            : '当前店铺还没有克隆音色')
      return available.value
    } catch (e: any) {
      available.value = false
      unavailableReason.value =
        e?.response?.data?.detail || e?.message || '无法确认当前店铺的音色状态'
      return false
    } finally {
      // 只在仍处于体检态时收尾，避免覆盖掉同时开始的合成态
      if (phase.value === 'checking') phase.value = 'idle'
    }
  }

  // ======================= 调度基础设施 =======================

  function getAudioCtx(): AudioContext | null {
    if (audioCtxUnavailable) return null
    if (audioCtx) return audioCtx
    try {
      const Ctor: any = (window as any).AudioContext || (window as any).webkitAudioContext
      if (!Ctor) {
        audioCtxUnavailable = true
        return null
      }
      audioCtx = new Ctor() as AudioContext
      return audioCtx
    } catch (e) {
      // 降级不静默：`<audio>` 接力仍可用，但间隙会变大，所以留一条 warn
      console.warn('[voice-tts] Web Audio 不可用，降级为 <audio> 接力：', e)
      audioCtxUnavailable = true
      return null
    }
  }

  function resumeCtx(c: AudioContext) {
    // 自动播放策略：开关是点击开的，正常路径 ctx 已是 running；若被挂起则救一次
    if (c.state === 'suspended') void c.resume().catch(() => undefined)
  }

  /** 消费者等待「有新活干」；生产者/计划器每次推进都会 `wakeConsumer()` */
  function waitWork(): Promise<void> {
    return new Promise<void>((resolve) => {
      workSignal = resolve
    })
  }

  function wakeConsumer() {
    const fn = workSignal
    workSignal = null
    if (fn) fn()
  }

  /** 作废当前轮的一切：停声、断链、唤醒所有等待者 */
  function cancel() {
    runId += 1
    for (const src of liveSources) {
      try {
        src.stop()
      } catch {
        /* 尚未 start 的 source 会抛，忽略 */
      }
    }
    liveSources.clear()
    for (const el of liveElements) {
      try {
        el.pause()
        el.src = ''
      } catch {
        /* 元素已释放，忽略 */
      }
    }
    liveElements.clear()
    if (idleTimer) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
    if (planTimer) {
      clearTimeout(planTimer)
      planTimer = null
    }
    wakeConsumer()
    if (phase.value === 'playing' || phase.value === 'loading') phase.value = 'idle'
  }

  function stop() {
    cancel()
  }

  function disable() {
    enabled.value = false
    persistEnabled()
    cancel()
  }

  /** 起一轮新的播报：重置游标与队列，并启动消费者 */
  function setupRun(key: string) {
    cancel()
    activeRunKey = key
    cursor = 0
    queue = []
    consumed = 0
    producerChain = Promise.resolve()
    pendingText = ''
    plannedFor = 0
    planBusy = false
    planDirty = false
    lastPlanAt = 0
    planSettled = true
    ended = false
    scheduledUntil = 0
    prevSchedEnd = -1
    lastEndedAt = -1
    feedAt = performance.now()
    firstSoundAt = -1
    gapLog = []
    segCount = 0

    const my = runId
    const c = getAudioCtx()
    if (c) void consumeAudio(my, c)
    else void consumeElements(my)
  }

  // ======================= 生产者：串行合成 =======================

  async function synth(text: string, my: number): Promise<string> {
    const hit = urlCache.get(text)
    if (hit) return hit
    if (my === runId && phase.value === 'idle') phase.value = 'loading'
    const res = await speakVoice(text)
    if (my !== runId) return ''
    urlCache.set(text, res.audio_url)
    if (urlCache.size > CACHE_LIMIT) {
      const oldest = urlCache.keys().next().value
      if (oldest !== undefined) urlCache.delete(oldest)
    }
    return res.audio_url
  }

  async function decode(url: string, my: number): Promise<AudioBuffer | null> {
    const hit = bufferCache.get(url)
    if (hit) return hit
    const c = getAudioCtx()
    if (!c) return null
    try {
      // `/static/**` 由 vite 代理为同源，故这里能直接 fetch（不需要 CORS）
      const resp = await fetch(url, { credentials: 'same-origin' })
      if (!resp.ok) return null
      const raw = await resp.arrayBuffer()
      if (my !== runId) return null
      const buf = await c.decodeAudioData(raw)
      bufferCache.set(url, buf)
      if (bufferCache.size > CACHE_LIMIT) {
        const oldest = bufferCache.keys().next().value
        if (oldest !== undefined) bufferCache.delete(oldest)
      }
      return buf
    } catch (e) {
      // 解码失败不是致命错误 → 这一段退回 `<audio>` 播，但要留痕
      console.warn('[voice-tts] 解码失败，该段退回 <audio>：', url, e)
      return null
    }
  }

  function enqueue(text: string, rawEnd: number) {
    const my = runId
    segCount += 1
    const u = {
      text,
      rawEnd,
      ready: Promise.resolve(null),
    } as Utterance
    queue.push(u)
    // ★ 生产者**串行**：上一段合成完才轮到这一段（并行会被 DashScope 限流拒掉大半）
    u.ready = producerChain
      .then(async () => {
        if (my !== runId) return null
        const url = await synth(text, my)
        if (!url || my !== runId) return null
        const buffer = await decode(url, my)
        if (my !== runId) return null
        return { url, buffer }
      })
      .catch((e: unknown) => {
        if (my === runId) failAndDisable(e)
        return null
      })
    producerChain = u.ready.then(() => undefined)
    wakeConsumer()
  }

  function failAndDisable(e: unknown) {
    const status = (e as any)?.response?.status
    const detail = (e as any)?.response?.data?.detail || (e as any)?.message || '未知原因'
    lastError.value = String(detail)
    // ★ 429 是**暂时性**故障（全局 60 次/60s，全 App 共用），不能按「音色不可用」处理：
    //   报一次原因、本轮跳过就够了。若也走 disable()，用户会莫名其妙发现开关自己关了，
    //   而真正的原因（配额）早就过去了。
    if (status === 429) {
      message.warning(`语音播报本轮被限流跳过：${detail}`, 4)
      cancel()
      return
    }
    message.error(`语音播报失败：${detail}`)
    disable()
  }

  // ======================= 计划器：正文 → 已定型的段 =======================

  /** 把一批计划段吃进队列。★ 游标去重 + 只吃已定型的段（两条不变量都在这） */
  function ingest(segments: { text: string; raw_end: number; stable: boolean }[]) {
    for (const seg of segments) {
      if (seg.raw_end <= cursor) continue // ① 念过的（或已入队的）不再吃
      if (!seg.stable && !ended) break // ② 还在长 → 后面的都先别念（保序）
      cursor = seg.raw_end
      if (!seg.text) continue // 整段都是 markdown 符号 → 没得念，但游标照推（否则会卡死）
      enqueue(seg.text, seg.raw_end)
    }
  }

  /** 节流命中时排一个稍后再算的定时器（同一时间窗内的多次增量合并成一次请求） */
  function schedulePlanRetry(delayMs: number) {
    if (planTimer) return
    planTimer = setTimeout(() => {
      planTimer = null
      void pumpPlan()
    }, Math.max(0, delayMs))
  }

  async function pumpPlan(): Promise<void> {
    if (planBusy) {
      planDirty = true
      return
    }
    const grew = pendingText.length - plannedFor
    if (grew <= 0) {
      planSettled = true
      wakeConsumer() // 正文没长 → 计划已追平，消费者可以决定收工
      return
    }

    // ★ 节流（见文件头 PLAN_MIN_* 的说明）：后端是**全局** 60 次/60s，逐 delta 必炸。
    //   注意 `ended` 是**放行**条件：正文已结束的那一次必须无条件算，
    //   否则结尾那点增量会永远等不到计划。
    if (!ended) {
      if (grew < PLAN_MIN_GROWTH_CHARS) return // 攒够字再算
      const since = performance.now() - lastPlanAt
      if (lastPlanAt > 0 && since < PLAN_MIN_INTERVAL_MS) {
        schedulePlanRetry(PLAN_MIN_INTERVAL_MS - since)
        return
      }
    }

    const my = runId
    const raw = pendingText
    lastPlanAt = performance.now()
    planBusy = true
    planSettled = false
    try {
      const res = await fetchSpeechPlan(raw)
      if (my !== runId) return
      plannedFor = raw.length
      ingest(res.segments)
    } catch (e: unknown) {
      if (my !== runId) return
      failAndDisable(e)
      return
    } finally {
      planBusy = false
    }
    if (my !== runId) return
    // 期间正文又长了（或有一次被合并进来的脏标记）→ 继续追
    if (planDirty || pendingText.length !== plannedFor) {
      planDirty = false
      void pumpPlan()
      return
    }
    planSettled = true
    wakeConsumer()
  }

  // ======================= 喂入（唯一入口） =======================

  /**
   * ★ 唯一入口：把「到目前为止的正文」喂给播报流水线。
   *
   * 为什么必须有唯一入口：正文的到达方式有两种 —— 流式（delta 累加）与非流式
   * （一次性拿到全文），但它们对播报的语义是**同一个**：「这是目前已知的全部正文，
   * 能念的段先念」。所以由调用方声明 `streaming`，而不是给两条链路各写一套播报逻辑。
   *
   * @param text            到目前为止的完整正文（markdown，净化与切段都在后端做）
   * @param opts.runKey     消息标识；**变化即开启新一轮**（重置游标、清空队列）
   * @param opts.streaming  true = 正文还在增长；false = 已结束（可以念结尾那段碎片）
   */
  function feed(text: string, opts: { runKey?: string; streaming?: boolean } = {}) {
    if (!enabled.value) return
    const raw = text || ''
    const key = opts.runKey || ''
    const streaming = opts.streaming !== false

    if (!raw.trim()) return // 流式刚开头的空消息 → 什么都别做
    if (key && key !== activeRunKey) setupRun(key)

    pendingText = raw
    ended = !streaming
    void pumpPlan()
  }

  /**
   * 一次性读完（`streaming = false` 的语法糖）。
   *
   * @deprecated 新代码请用 `feed` —— 编排层需要「边生成边念」，只有 `feed` 能表达。
   *   保留它是为了兼容「整段读一遍」这类调用点。
   */
  function speak(text: string) {
    const payload = (text || '').trim()
    if (!payload) return
    feed(payload, { runKey: `speak:${hashText(payload)}`, streaming: false })
  }

  /**
   * 消费者（Web Audio 绝对时间轴）：每段排到上一段结束的确切时刻 → 间隙 0。
   */
  async function consumeAudio(my: number, c: AudioContext) {
    while (my === runId) {
      const u = queue[consumed]
      if (!u) {
        if (ended && planSettled) break
        await waitWork()
        continue
      }
      consumed += 1
      const ready = await u.ready
      if (my !== runId) return
      if (!ready) continue

      if (!ready.buffer) {
        // 该段解码失败（或整个 Web Audio 不可用）→ 退回 <audio>，时间轴要重新起算
        prevSchedEnd = -1
        await playElement(ready.url, my)
        if (my !== runId) return
        continue
      }

      resumeCtx(c)
      const start = Math.max(scheduledUntil, c.currentTime + SCHEDULE_LEAD_S)
      if (prevSchedEnd >= 0) gapLog.push(Math.max(0, (start - prevSchedEnd) * 1000))
      const src = c.createBufferSource()
      src.buffer = ready.buffer
      src.connect(c.destination)
      src.start(start)
      scheduledUntil = start + ready.buffer.duration
      prevSchedEnd = scheduledUntil
      liveSources.add(src)
      src.onended = () => liveSources.delete(src)
      if (firstSoundAt < 0) {
        // start 是 ctx 时间轴上的时刻；换算回 performance.now() 域
        firstSoundAt = performance.now() + (start - c.currentTime) * 1000
      }
      phase.value = 'playing'
    }
    if (my !== runId) return
    const remainMs = Math.max(0, (scheduledUntil - c.currentTime) * 1000)
    if (remainMs <= 0) {
      phase.value = 'idle'
    } else {
      idleTimer = setTimeout(() => {
        idleTimer = null
        if (my === runId) phase.value = 'idle'
      }, remainMs + 150)
    }
    settleMetrics(my)
  }

  /** 播放单个 URL（`<audio>` 路径），resolve 于播放结束 */
  function playElement(url: string, my: number): Promise<void> {
    return new Promise<void>((resolve) => {
      const el = new Audio(url)
      liveElements.add(el)
      el.preload = 'auto'
      const done = () => {
        liveElements.delete(el)
        if (my === runId) lastEndedAt = performance.now()
        resolve()
      }
      el.onplay = () => {
        const now = performance.now()
        if (my === runId) {
          if (lastEndedAt >= 0) gapLog.push(Math.max(0, now - lastEndedAt))
          if (firstSoundAt < 0) firstSoundAt = now
          phase.value = 'playing'
        }
      }
      el.onended = done
      el.onerror = () => {
        done()
        message.error('音频播放失败：浏览器无法播放该音频（或地址不可达）')
      }
      el.play().catch((err: unknown) => {
        done()
        message.warning('浏览器拦截了自动播放，请再点一次喇叭')
        console.warn('[voice-tts] play() 被拒：', err)
      })
    })
  }

  /** 消费者（`<audio>` 降级路径）：串行接力，段间间隙如实记进 metrics */
  async function consumeElements(my: number) {
    while (my === runId) {
      const u = queue[consumed]
      if (!u) {
        if (ended && planSettled) break
        await waitWork()
        continue
      }
      consumed += 1
      const ready = await u.ready
      if (my !== runId) return
      if (!ready?.url) continue
      await playElement(ready.url, my)
      if (my !== runId) return
    }
    if (my !== runId) return
    phase.value = 'idle'
    settleMetrics(my)
  }

  function settleMetrics(my: number) {
    if (my !== runId) return
    const gaps = gapLog.slice()
    lastRunMetrics.value = {
      runKey: activeRunKey,
      feedAt,
      firstSoundAt,
      firstSoundMs: firstSoundAt < 0 ? -1 : firstSoundAt - feedAt,
      gaps,
      maxGapMs: gaps.length ? Math.max(...gaps) : -1,
      segments: segCount,
    }
    if (import.meta.env.DEV) {
      const m = lastRunMetrics.value
      console.info(
        `[voice-tts] 首声 ${m.firstSoundMs < 0 ? '—' : Math.round(m.firstSoundMs) + 'ms'}` +
          ` / ${m.segments} 段 / 最大段间间隙 ${m.maxGapMs < 0 ? '0（单段）' : m.maxGapMs.toFixed(1) + 'ms'}`
      )
    }
  }

  /** 点喇叭：正在播 → 只停止（保持自动朗读）；否则开/关开关 */
  async function toggle(agentId: string | undefined | null) {
    if (phase.value === 'playing' || phase.value === 'loading') {
      stop()
      return
    }
    if (enabled.value) {
      disable()
      return
    }
    if (!supports(agentId)) {
      message.info('语音播报目前只支持店秘书')
      return
    }
    const ok = await refreshAvailability()
    if (!ok) {
      // ★ 显式拒绝 + 给去路，绝不「先用系统默认音色顶上」
      message.warning(`无法开启语音播报：${unavailableReason.value}。可在「设置 → 语音克隆」里创建。`, 6)
      return
    }
    enabled.value = true
    persistEnabled()
  }

  /** 切店铺：停掉正在播的，清缓存，并重新体检（音色是 per-shop 的） */
  async function handleShopChange() {
    cancel()
    urlCache.clear()
    bufferCache.clear()
    if (enabled.value) await refreshAvailability()
  }

  return {
    enabled,
    phase,
    available,
    unavailableReason,
    lastError,
    lastRunMetrics,
    supports,
    refreshAvailability,
    feed,
    speak,
    stop,
    disable,
    toggle,
    handleShopChange,
  }
})
