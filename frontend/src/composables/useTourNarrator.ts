/**
 * 新手引导 · 语音解说（双通道）
 * =============================
 *
 * ★ 通道优先级：**店铺克隆音色优先，浏览器原生兜底**。
 *
 *   为什么是「优先 + 兜底」而不是二选一（r284 的教训，别再改回单通道）：
 *   · 只做原生 —— 你自己的克隆音色明明 ready，却永远用不上；
 *     而且「面向新人的功能，验收者是老板」这条决定了：降级若按最弱目标用户做，
 *     老板永远看不到最好的那条路。
 *   · 只做克隆 —— 新店铺 / 未选店铺 / 后端 fail-closed 时引导会全程哑掉，
 *     而引导恰恰是这些人在看。
 *   ⇒ 两条都要，且**降级必须说出来**（见 `channelLabel`），不许静默换声音。
 *
 * ★ 复用到什么程度（刻意不复用 `stores/voiceTts.ts`）：
 *   · 复用：api 层的 `fetchVoiceStatus`（查音色就绪）+ `speakVoice`（合成）
 *   · 不复用：`voiceTts` 那套流式调度（runKey / Web Audio 绝对时间轴 / `enabled` 开关）。
 *     它是给「Agent 边生成边念」用的；引导是「一步一段、整段一次性合成」，
 *     套上去只会让引导的静音开关和对话的喇叭开关互相打架。
 *   · 播放用裸 `<audio>`：一段一个 URL，不需要排队时间轴。
 *
 * 三条刻意的设计（都有代价，别随手改）：
 *
 * 1. **原生通道没有 zh-CN 语音包就不念**。用英文音色念中文是把中文拆成拼音 + 英文音素，
 *    听起来像噪声，比不念更糟。此时 `reason` 非空，界面必须显示它。
 *
 * 2. **原生通道整段拆句排队**，而不是一次 `speak()` 整段。Chrome 对单次 utterance 有约
 *    15 秒的截断（不报错、直接停）。拆句还有个副作用好处：切步时能在句边界干净地停。
 *    （克隆通道不需要拆：后端 `speak` 一次合成整段，超长会回 `truncated` 如实告知。）
 *
 * 3. **首次发声必须发生在用户手势之后**。Chrome 在没有 `userActivation` 时调用
 *    `speak()` / `audio.play()` 都会**静默失败**（既不发声也不报错）——
 *    这正是本项目反复防过的形态。⇒ 引导入口是一张需要用户点「开始」的卡片
 *    （`TourHost.vue`），这个手势同时也是音频链路的解封动作。别把它改成自动弹出。
 */

import { reactive, computed } from 'vue'
import { fetchVoiceStatus, speakVoice } from '@/api/voiceClone'
import { useShopStore } from '@/stores/shop'

const MUTE_KEY = 'tour_narrator_muted'

/** 本次发声实际走的通道。`none` = 一点声音都没出来 */
export type TourVoiceChannel = 'clone' | 'system' | 'none'

/** 原生通道的能力探测只做一次：它是「浏览器有没有这个 API」，与音色是否就绪无关 */
const systemSupported =
  typeof window !== 'undefined' && typeof window.speechSynthesis !== 'undefined'

let voices: SpeechSynthesisVoice[] = []
let voicesLoaded = false
/** 排队序号：切步骤 / 静音时自增，让上一段未播完的作废（否则两步的解说会叠着念） */
let queueSeq = 0

/** 克隆音色不可用（或未就绪）的具体原因。空串 = 可用 */
let cloneUnavailableReason = ''
/** 克隆侧「已就绪但合成/播放失败」的原因。与上面区分开：这是故障，那只是没有 */
let cloneFailureReason = ''
/** 后端如实回报的截断说明（超长只念了一段） */
let truncatedNote = ''

export const narratorState = reactive({
  systemSupported,
  speaking: false,
  muted: readMuted(),
  /** 完全发不出声时的具体原因（能发声时为空串）。**必须由界面显示**，不允许只置灰了事 */
  reason: '',
  /** 本次发声实际走的通道 */
  channel: 'none' as TourVoiceChannel,
  /** 通道的一句话说明，含「为什么不是另一条」——★ 降级必须说出来，不许静默 */
  channelLabel: '',
})

export const narratorReason = computed(() => narratorState.reason)

function readMuted(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === '1'
  } catch {
    return false
  }
}

// --------------------------------------------------------------------------- //
// 克隆通道：可用性探测
// --------------------------------------------------------------------------- //

let cloneProbe: Promise<boolean> | null = null
let cloneProbedShop = ''

/** 探测结果按店铺缓存：切了店铺就得重问，否则会拿上一个店的结果给这个店配音 */
function probeClone(shopId: string): Promise<boolean> {
  if (cloneProbe && cloneProbedShop === shopId) return cloneProbe
  cloneProbedShop = shopId
  cloneProbe = doProbeClone(shopId).catch(() => false)
  return cloneProbe
}

async function doProbeClone(shopId: string): Promise<boolean> {
  try {
    // silentError=true：没有音色是**正常情况**，不是故障，不该由这里弹提示
    const rec = await fetchVoiceStatus(false, true)
    if (rec.ready) {
      cloneUnavailableReason = ''
      return true
    }
    cloneUnavailableReason =
      rec.error_msg ||
      (rec.exists
        ? `音色当前状态「${rec.status}」，还不可用`
        : shopId
          ? '当前店铺还没有克隆音色'
          : '还没选择店铺')
    return false
  } catch (e: any) {
    cloneUnavailableReason = e?.response?.data?.detail || e?.message || '无法确认当前店铺的音色状态'
    return false
  }
}

// --------------------------------------------------------------------------- //
// 克隆通道：合成 + 播放
// --------------------------------------------------------------------------- //

/** `shopId|文案` → 音频 URL。★ 键必须带店铺：同一段文案在不同店铺是不同的声音 */
const urlCache = new Map<string, string>()
const CACHE_LIMIT = 64

let audioEl: HTMLAudioElement | null = null

function ensureAudio(): HTMLAudioElement | null {
  if (typeof window === 'undefined') return null
  if (!audioEl) audioEl = new Audio()
  return audioEl
}

function stopAudio(): void {
  if (!audioEl) return
  try {
    audioEl.pause()
    audioEl.currentTime = 0
  } catch {
    /* 某些浏览器在未加载 src 时 pause 会抛，忽略 */
  }
  audioEl.onended = null
  audioEl.onerror = null
}

/** 取（必要时合成）这段文案的音频 URL。只缓存不播放 —— 供预取用 */
async function resolveCloneUrl(text: string, shopId: string): Promise<string> {
  const key = `${shopId}|${text}`
  const hit = urlCache.get(key)
  if (hit) return hit

  const res = await speakVoice(text)
  const url = res?.audio_url
  if (!url) throw new Error('合成结果没有返回音频地址')

  truncatedNote = res.truncated ? `（原文 ${res.source_chars} 字，只念了前面一段）` : ''
  urlCache.set(key, url)
  if (urlCache.size > CACHE_LIMIT) {
    const oldest = urlCache.keys().next().value
    if (oldest !== undefined) urlCache.delete(oldest)
  }
  return url
}

async function playClone(text: string, seq: number, shopId: string): Promise<boolean> {
  const url = await resolveCloneUrl(text, shopId)
  if (seq !== queueSeq) return false

  const el = ensureAudio()
  if (!el) throw new Error('当前环境不支持音频播放')
  stopAudio()
  el.src = url
  narratorState.speaking = true

  await new Promise<void>((resolve, reject) => {
    const done = () => {
      if (seq === queueSeq) narratorState.speaking = false
      resolve()
    }
    el.onended = done
    el.onerror = () => reject(new Error('音频播放失败'))
    // 自动播放被拦时 play() 会 reject：如实往外抛，由 speak() 写进 reason
    el.play().catch((e) => reject(e instanceof Error ? e : new Error(String(e))))
  })
  return true
}

/**
 * 预取下一步的音频（不播放）。
 *
 * ★ 这里**故意静默失败**：预取只是提速手段，真正的播报会再走一遍并如实报错。
 *   若在预取阶段就弹提示，用户会看到「还没讲到这一步，先报了个错」。
 */
export async function prefetch(text: string): Promise<void> {
  if (!text || narratorState.muted) return
  try {
    let shopId = ''
    try {
      shopId = useShopStore().currentShopId || ''
    } catch {
      shopId = ''
    }
    if (!(await probeClone(shopId))) return
    await resolveCloneUrl(text, shopId)
  } catch {
    /* 预取失败：静默，等真正播报时再报 */
  }
}

// --------------------------------------------------------------------------- //
// 原生通道：浏览器 speechSynthesis
// --------------------------------------------------------------------------- //

/** 语音列表在部分浏览器上是异步到位的，首次 `getVoices()` 可能返回空数组 */
function ensureVoices(): void {
  if (typeof window === 'undefined' || !systemSupported) return
  if (!voicesLoaded) {
    voices = window.speechSynthesis.getVoices() || []
    voicesLoaded = voices.length > 0
  }
  if (typeof window.speechSynthesis.addEventListener === 'function') {
    window.speechSynthesis.addEventListener('voiceschanged', () => {
      voices = window.speechSynthesis.getVoices() || []
      voicesLoaded = voices.length > 0
    })
  }
}

/** 挑嗓门：优先 zh-CN，其次任意 zh 开头，都没有则返回 null */
function pickVoice(): SpeechSynthesisVoice | null {
  ensureVoices()
  if (!voices.length) return null
  return (
    voices.find((v) => (v.lang || '').toLowerCase() === 'zh-cn') ||
    voices.find((v) => (v.lang || '').toLowerCase().startsWith('zh')) ||
    null
  )
}

/** 按句拆，短句不拆、过长句按 40 字再切一刀（防止单句本身就超限） */
function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[。！？!?；;])/)
    .map((s) => s.trim())
    .filter(Boolean)
    .flatMap((s) => (s.length <= 40 ? [s] : (s.match(/.{1,40}/g) ?? [s])))
}

function speakSystem(text: string, seq: number): boolean {
  if (!systemSupported || typeof window === 'undefined') {
    narratorState.reason = '当前浏览器不支持语音播报，建议使用 Chrome 或 Edge'
    return false
  }
  const chunks = splitSentences(text)
  if (!chunks.length) return false
  const voice = pickVoice()
  if (!voice) {
    narratorState.reason =
      '系统没有安装中文语音包，本次引导只显示文字（Windows 可在「设置 → 时间和语言 → 语音」添加）'
    return false
  }

  const synth = window.speechSynthesis
  try {
    synth.cancel()
  } catch {
    /* 某些浏览器在未初始化时 cancel 会抛，忽略 */
  }

  let cursor = 0
  narratorState.speaking = true
  const playNext = () => {
    if (seq !== queueSeq || narratorState.muted) {
      narratorState.speaking = false
      return
    }
    if (cursor >= chunks.length) {
      narratorState.speaking = false
      return
    }
    const u = new SpeechSynthesisUtterance(chunks[cursor++])
    u.voice = voice
    u.lang = voice.lang || 'zh-CN'
    u.rate = 1.0
    u.pitch = 1.0
    u.volume = 1.0
    u.onend = playNext
    u.onerror = (e) => {
      if (seq !== queueSeq) return
      narratorState.speaking = false
      narratorState.reason = `语音播报中断：${(e as any)?.error || 'unknown'}`
    }
    synth.speak(u)
  }
  playNext()
  return true
}

/** 系统音通道的说明文案（含「为什么没用克隆」） */
function systemLabel(): string {
  if (cloneFailureReason) return `系统语音（克隆合成失败：${cloneFailureReason}）`
  return `系统语音（${cloneUnavailableReason || '当前店铺没有可用的克隆音色'}）`
}

// --------------------------------------------------------------------------- //
// 对外：speak / cancel / setMuted
// --------------------------------------------------------------------------- //

/**
 * 念一段引导词。
 *
 * @returns 是否**真的**开始发声。false 表示没念成（原因写进 `narratorState.reason`）。
 */
export async function speak(text: string): Promise<boolean> {
  const seq = ++queueSeq
  narratorState.reason = ''
  narratorState.channel = 'none'
  narratorState.channelLabel = ''
  cloneFailureReason = ''
  truncatedNote = ''

  if (!text) return false
  if (narratorState.muted) {
    narratorState.channelLabel = '已静音'
    return false
  }

  let shopId = ''
  try {
    shopId = useShopStore().currentShopId || ''
  } catch {
    shopId = ''
  }

  // ---- ① 克隆优先 ----
  if (await probeClone(shopId)) {
    if (seq !== queueSeq) return false
    try {
      const played = await playClone(text, seq, shopId)
      if (seq !== queueSeq) return false
      if (played) {
        narratorState.channel = 'clone'
        narratorState.channelLabel = `你的克隆音色在讲解${truncatedNote}`
        return true
      }
    } catch (e: any) {
      if (seq !== queueSeq) return false
      // ★ 合成/播放失败 ⇒ 不静默：记下原因，退回系统音，并把原因显示在气泡里
      cloneFailureReason = e?.response?.data?.detail || e?.message || '未知原因'
    }
  } else if (seq !== queueSeq) {
    return false
  }

  // ---- ② 系统音兜底 ----
  const ok = speakSystem(text, seq)
  if (ok) {
    narratorState.channel = 'system'
    narratorState.channelLabel = systemLabel()
  } else {
    narratorState.channel = 'none'
    narratorState.channelLabel = narratorState.reason
  }
  return ok
}

/** 停止当前解说（切步骤 / 跳过 / 关掉引导 / 静音都要调） */
export function cancel(): void {
  queueSeq++
  narratorState.speaking = false
  stopAudio()
  if (!systemSupported || typeof window === 'undefined') return
  try {
    window.speechSynthesis.cancel()
  } catch {
    /* 同上 */
  }
}

export function setMuted(v: boolean): void {
  narratorState.muted = v
  try {
    localStorage.setItem(MUTE_KEY, v ? '1' : '0')
  } catch {
    /* 无痕模式下 localStorage 不可写：静音只在这一个会话内有效，可接受 */
  }
  if (v) cancel()
}
