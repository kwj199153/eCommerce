/**
 * 语音输入（浏览器原生 Web Speech API）
 * =====================================
 * 把话变成字，填进对话框。走的是浏览器自带的识别能力，**不经过我们的后端**：
 * 零费用、零延迟、不需要新增上传端点。
 *
 * 几个刻意的设计（都有代价，别随手改）：
 *
 * 1. **只在 Chrome / Edge 上保证可用**。Safari 支持有限、Firefox 默认关闭。
 *    不支持的浏览器 `supported = false`，由调用方把按钮置灰/隐藏 ——
 *    **不要**做一个点了没反应的按钮。
 *
 * 2. **要求安全上下文**。Web Speech API 只在 HTTPS / localhost 下工作。
 *    生产若走 http，表现是「有 API 但 start() 立刻报 not-allowed」，极难归因，
 *    所以这里提前用 `isSecureContext` 判定并给出明确原因。
 *
 * 3. **每次 start 都重建识别实例**。部分浏览器在 stop 之后复用同一实例会
 *    静默不再触发回调（不报错、就是没反应）—— 这是踩过的坑，别为省一个 new 改回去。
 *
 * 4. **拼接按中英文分别处理**。中文之间不该有空格，英文单词之间必须有。
 *    统一加空格会让中文变成「帮我 看看 这个 竞品」，统一不加会让英文粘成一坨。
 *
 * 5. **已知取舍：收音期间手动改输入框会被覆盖**。回填用的是「开始收音时的快照 + 语音」，
 *    因为说话时基本不会同时打字。若将来出现投诉，改成「监听手动输入即自动停止收音」。
 */

import { computed, reactive } from 'vue'

/** 浏览器厂商前缀：Chrome / Edge 暴露的是 webkitSpeechRecognition */
const SpeechRecognitionCtor: any =
  typeof window !== 'undefined'
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null
    : null

/** 安全上下文：Web Speech API 只在 HTTPS / localhost 下可用 */
const isSecureContext = typeof window === 'undefined' ? true : window.isSecureContext

export const speechState = reactive({
  /** 当前浏览器能否用（含安全上下文），false 时调用方应禁用按钮 */
  supported: SpeechRecognitionCtor !== null && isSecureContext,
  /** 是否正在收音 */
  listening: false,
  /** 本次会话已确认（final）的文本 */
  transcript: '',
  /** 正在识别的临时（interim）文本，只用于实时预览 */
  interim: '',
  /** 错误码，空字符串表示无错误 */
  error: '',
})

/** 不支持的原因（supported 为 true 时是空字符串），用于 tooltip */
export const speechUnsupportedReason = computed(() => {
  if (SpeechRecognitionCtor === null) return '当前浏览器不支持原生语音识别，建议使用 Chrome 或 Edge'
  if (!isSecureContext) return '语音识别需要在 HTTPS 或 localhost 环境下使用'
  return ''
})

let recognizer: any = null
/** 错误探测的竞态序号：探测是异步的，重开收音后旧结果必须作废 */
let errorSeq = 0
/** 开始收音时的既有输入框内容，语音结果追加在它之后 */
let baseText = ''
/** 文本变化回调：调用方据此回填输入框 */
let emitText: ((text: string) => void) | null = null

/** 拼接时决定是否补空格：ASCII 字母/数字之间补，含中文则直接接 */
function joinText(a: string, b: string): string {
  if (!a) return b
  if (!b) return a
  const needSpace = /[0-9A-Za-z]$/.test(a) && /^[0-9A-Za-z]/.test(b)
  return needSpace ? `${a} ${b}` : a + b
}

/** 当前完整文本 = 既有内容 + 已确认 + 临时 */
function compose(): string {
  return joinText(joinText(baseText, speechState.transcript), speechState.interim)
}

function emit() {
  emitText?.(compose())
}

/**
 * 开始收音。
 *
 * @param options.base   输入框当前内容（语音结果会追加在它之后）
 * @param options.onText 文本变化回调，收到的是**完整文本**，直接赋给输入框即可
 */
export function startSpeech(options: { base?: string; onText: (text: string) => void }) {
  if (!speechState.supported || speechState.listening) return

  baseText = options.base ?? ''
  emitText = options.onText
  speechState.transcript = ''
  speechState.interim = ''
  speechState.error = ''
  errorSeq++ // 让上一轮未完成的探测作废，别把旧结论写到新会话上

  recognizer = new SpeechRecognitionCtor()
  recognizer.lang = 'zh-CN'
  recognizer.continuous = true
  recognizer.interimResults = true
  recognizer.maxAlternatives = 1

  recognizer.onresult = (event: any) => {
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]
      const text = result[0]?.transcript ?? ''
      if (result.isFinal) {
        speechState.transcript = joinText(speechState.transcript, text.trim())
      } else {
        interim += text
      }
    }
    speechState.interim = interim
    emit()
  }

  recognizer.onerror = async (event: any) => {
    const code = event?.error || 'unknown'
    // aborted 是我们主动 stop 触发的，不算错误
    if (code === 'aborted') return
    // 原始码必须落 console：线上排查只认它，别删
    console.warn('[speech] recognition error:', code, event)
    speechState.listening = false

    if (code !== 'not-allowed') {
      speechState.error = code
      return
    }
    // 垃圾桶码：二次定位后再报，否则文案会把用户引到错误的方向
    const seq = ++errorSeq
    const probed = await probeMicError()
    if (seq !== errorSeq) return // 探测期间又重开过收音，丢弃过期结论
    speechState.error = probed
  }

  recognizer.onend = () => {
    // continuous 模式下浏览器也会因静音超时自动结束，这里统一收尾
    speechState.listening = false
    speechState.interim = ''
    emit()
  }

  try {
    recognizer.start()
    speechState.listening = true
  } catch (e) {
    speechState.listening = false
    speechState.error = 'start-failed'
  }
}

export function stopSpeech() {
  speechState.listening = false
  if (!recognizer) return
  try {
    recognizer.stop()
  } catch (e) {
    /* 已经结束，忽略 */
  }
}

/** 按钮点击入口：收音中则停止，否则开始 */
export function toggleSpeech(options: { base?: string; onText: (text: string) => void }) {
  if (speechState.listening) {
    stopSpeech()
  } else {
    startSpeech(options)
  }
}

export function clearSpeechError() {
  speechState.error = ''
}

/**
 * `not-allowed` 的二次定位。
 *
 * Web Speech 把这几种情况混成一个码，单看它无法归因。这里用 getUserMedia 反向试探：
 * - 拿得到设备 → 麦克风本身没问题，是「识别服务」那条路不通
 * - 拿不到     → 看 DOMException.name 精确拆开（拒绝 / 无设备 / 被占用 / 非安全上下文）
 *
 * 副作用：首次调用会触发浏览器的权限弹窗。这其实是好事 —— Web Speech 的 start()
 * 并不总会弹窗，用户此前可能连一次授权机会都没拿到过。
 */
async function probeMicError(): Promise<string> {
  // 非安全上下文下浏览器根本不暴露 mediaDevices，连问都不必问
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
    return 'insecure-context'
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    // 只为探测，拿到就立刻释放，别占着设备
    stream.getTracks().forEach((t) => t.stop())
    return 'recognizer-blocked'
  } catch (e: any) {
    switch (e?.name) {
      case 'NotAllowedError':
        return 'mic-permission-denied'
      case 'NotFoundError':
        return 'no-mic-device'
      case 'NotReadableError':
        return 'mic-busy'
      case 'SecurityError':
        return 'insecure-context'
      default:
        return 'not-allowed'
    }
  }
}

/**
 * 错误码 → 用户可读文案（空字符串表示不用提示）。
 * 前 5 条是 `not-allowed` 由 probeMicError 拆出来的细分真因，每条都对应一个**不同的动作**，
 * 合并回一句就等于让用户瞎试。
 */
const ERROR_TEXT: Record<string, string> = {
  'mic-permission-denied':
    '麦克风权限被拒绝。请点地址栏左侧图标 → 麦克风 → 允许；若地址栏根本没有该图标，请打开「Windows 设置 → 隐私和安全性 → 麦克风」，开启总开关及「允许桌面应用访问麦克风」后重启浏览器',
  'no-mic-device': '没有检测到麦克风设备，请确认设备已连接且未被系统禁用',
  'mic-busy': '麦克风被其它程序占用（会议 / 录音类软件），请关闭后重试',
  'insecure-context':
    '当前页面不是 HTTPS 或 localhost，浏览器禁止使用麦克风，请改用 localhost 或 HTTPS 访问',
  'recognizer-blocked':
    '麦克风本身可用，但浏览器自带的语音识别服务不可用（Chrome 的识别依赖其境外云端服务，当前网络下通常不可达）。建议改用 Edge 浏览器重试',

  'not-allowed': '麦克风权限被拒绝，请检查浏览器与系统的麦克风权限后重试',
  'service-not-allowed': '浏览器不允许使用语音识别服务，建议改用 Edge 浏览器',
  'audio-capture': '没有检测到麦克风设备',
  'no-speech': '没听到声音，请再说一次',
  network: '语音识别需要联网，请检查网络后重试',
  'start-failed': '语音识别启动失败，请重试',
}

export const speechErrorText = computed(() =>
  speechState.error ? ERROR_TEXT[speechState.error] ?? '语音识别出错，请重试' : ''
)
