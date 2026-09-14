/**
 * 浏览器麦克风录音 —— 产出可直接上传的 WAV File
 *
 * ★ 与 `useSpeechInput` 的区别（两者常被混淆，本质不同）：
 *   - `useSpeechInput` 走 **Web Speech API**，终点是**文字**，音频流不留存 → **拿不到音频**；
 *   - 本 composable 走 **getUserMedia + WebAudio**，终点是**音频数据本身**（WAV）。
 *   语音克隆要的恰恰是音频，因此必须单独开这条采集链。
 *
 * ★ 安全上下文是硬门槛：`getUserMedia` 只在 HTTPS / localhost 可用。
 *   生产若以 http 访问（如直接 IP），浏览器不暴露麦克风 → 录音不可用。
 *   因此**必须保留上传兜底**，不能把上传入口删掉（见 VoiceClonePanel 的双通道设计）。
 *
 * ★ 失败必须显式给出原因（项目铁律）：不静默降级、不假装成功。
 */

import { onBeforeUnmount, reactive, ref } from 'vue'
import { TARGET_SAMPLE_RATE, encodeWavPcm16, mergeChunks, resampleLinear } from '@/utils/wav'

export interface VoiceRecorder {
  /** 当前环境是否支持录音（安全上下文 + getUserMedia + WebAudio） */
  supported: boolean
  /** 不支持时的具体原因（直接展示给用户，不做兜底文案） */
  unsupportedReason: string
  isRecording: boolean
  /** 已录秒数（录制中实时刷新） */
  elapsed: number
  /** 实时音量 0~1，用于波形/电平提示 */
  level: number
  /** 最近一次失败原因 */
  error: string
  /** 达到上限自动停止的秒数 */
  maxSeconds: number
  start: () => Promise<boolean>
  /** 停止并返回 WAV 文件；太短或失败返回 null（原因写入 error） */
  stop: () => Promise<File | null>
  /** 丢弃已录内容，回到待录状态 */
  reset: () => void
}

/** 录音低于这个时长直接判无效：至少得念完一句话 */
const MIN_RECORD_SECONDS = 1.5

/**
 * 把 getUserMedia 的异常翻译成**可操作**的中文原因。
 *
 * ★ 不能统一说「请检查权限」——`NotAllowedError` 一个码背后可能是
 *   权限拒绝 / 系统隐私开关 / 设备独占 / 无设备四种情况，指引完全不同。
 */
function describeMicError(e: unknown): string {
  const name = (e as { name?: string } | null)?.name || ''
  const msg = (e as { message?: string } | null)?.message || ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '麦克风权限被拒绝：请点地址栏左侧图标，把「麦克风」改为允许后重试'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return '没有检测到麦克风设备，请先接入麦克风'
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return '麦克风被其它程序占用（会议 / 录音软件），请关闭后重试'
  }
  if (name === 'OverconstrainedError') {
    return '当前麦克风不支持所需的音频参数'
  }
  return msg || '无法启动录音'
}

export function useVoiceRecorder(options: { maxSeconds?: number } = {}): VoiceRecorder {
  const maxSeconds = options.maxSeconds ?? 60

  const isSecure =
    typeof window !== 'undefined' && (window as unknown as { isSecureContext?: boolean }).isSecureContext === true
  const hasGum = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  const AudioCtxCtor =
    typeof window !== 'undefined'
      ? ((window as unknown as { AudioContext?: typeof AudioContext }).AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
      : undefined

  const supported = isSecure && hasGum && !!AudioCtxCtor
  const unsupportedReason = supported
    ? ''
    : !isSecure
      ? '当前页面不是安全上下文（需 HTTPS 或 localhost），浏览器不允许调用麦克风'
      : !hasGum
        ? '当前浏览器不支持麦克风采集（建议使用 Chrome / Edge）'
        : '当前浏览器不支持 WebAudio，无法处理录音'

  const isRecording = ref(false)
  const elapsed = ref(0)
  const level = ref(0)
  const error = ref('')

  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let processor: ScriptProcessorNode | null = null
  let chunks: Float32Array[] = []
  let totalSamples = 0
  let timer: number | null = null
  let startedAt = 0

  function clearTimer(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  /** 释放全部底层资源（麦克风指示灯灭掉靠这里） */
  function release(): void {
    clearTimer()
    try {
      processor?.disconnect()
    } catch {
      /* 已断开 */
    }
    try {
      source?.disconnect()
    } catch {
      /* 已断开 */
    }
    try {
      stream?.getTracks().forEach((t) => t.stop())
    } catch {
      /* 已停止 */
    }
    try {
      if (ctx && ctx.state !== 'closed') void ctx.close()
    } catch {
      /* 已关闭 */
    }
    processor = null
    source = null
    stream = null
    ctx = null
  }

  function reset(): void {
    chunks = []
    totalSamples = 0
    elapsed.value = 0
    level.value = 0
    error.value = ''
  }

  async function start(): Promise<boolean> {
    error.value = ''
    if (!supported) {
      error.value = unsupportedReason
      return false
    }
    if (isRecording.value) return true
    reset()

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (e) {
      error.value = describeMicError(e)
      release()
      return false
    }

    try {
      // 尽量让硬件直接给 24kHz；不支持指定时用默认采样率，停止时再重采样
      ctx = new AudioCtxCtor!({ sampleRate: TARGET_SAMPLE_RATE })
    } catch {
      ctx = new AudioCtxCtor!()
    }

    source = ctx.createMediaStreamSource(stream)
    // ScriptProcessorNode 虽已标记废弃，但它是唯一无需额外 worklet 文件、
    // 且全平台（含旧版 Safari）都能用的采集方式。输出 buffer 留空 → 不会外放回声。
    processor = ctx.createScriptProcessor(4096, 1, 1)
    processor.onaudioprocess = (ev: AudioProcessingEvent) => {
      if (!isRecording.value) return
      const input = ev.inputBuffer.getChannelData(0)
      const copy = new Float32Array(input.length)
      copy.set(input)
      chunks.push(copy)
      totalSamples += copy.length
      let sum = 0
      for (let i = 0; i < copy.length; i += 1) sum += copy[i] * copy[i]
      level.value = Math.min(1, Math.sqrt(sum / copy.length) * 4)
    }
    source.connect(processor)
    processor.connect(ctx.destination)

    isRecording.value = true
    startedAt = performance.now()
    timer = window.setInterval(() => {
      elapsed.value = (performance.now() - startedAt) / 1000
      if (elapsed.value >= maxSeconds) {
        // 到上限自动停，避免用户忘了按停止而录出超长文件
        void stop()
      }
    }, 100)
    return true
  }

  async function stop(): Promise<File | null> {
    if (!isRecording.value) return null
    isRecording.value = false
    clearTimer()
    const nativeRate = ctx?.sampleRate || TARGET_SAMPLE_RATE
    const merged = mergeChunks(chunks, totalSamples)
    release()

    if (merged.length < nativeRate * MIN_RECORD_SECONDS) {
      error.value = `录音太短（${(merged.length / nativeRate).toFixed(1)} 秒），请完整念完一段后再停止`
      level.value = 0
      return null
    }
    level.value = 0
    const data =
      nativeRate === TARGET_SAMPLE_RATE ? merged : resampleLinear(merged, nativeRate, TARGET_SAMPLE_RATE)
    const blob = new Blob([encodeWavPcm16(data, TARGET_SAMPLE_RATE)], { type: 'audio/wav' })
    return new File([blob], `recording-${Date.now()}.wav`, { type: 'audio/wav' })
  }

  onBeforeUnmount(release)

  // ★ 必须用 reactive 包一层：
  //   Vue 模板只解包**顶层**绑定，嵌套在普通对象里的 ref 不会自动解包 ——
  //   若直接返回裸对象，模板里 recorder.isRecording 拿到的是 Ref 对象（恒为真值），
  //   录制态判断会全部失效。reactive 会解包其内部的 ref。
  return reactive({
    supported,
    unsupportedReason,
    isRecording,
    elapsed,
    level,
    error,
    maxSeconds,
    start,
    stop,
    reset,
  })
}
