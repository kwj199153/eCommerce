/**
 * 语音克隆（客服音色）API —— 附加模块，可插拔
 *
 * ★ 与主功能的隔离：
 *  - 本文件是独立模块，**不 import 任何既有业务 api**。
 *  - 后端路由前缀 `/voice-clone` 独立；总开关关闭时后端**不注册该路由**，
 *    因此这里所有调用都会拿到 404 —— 前端据此隐藏入口（见 `fetchVoiceConfig`）。
 *  - 失败必须显式展示「原因」：后端返回的 `detail` 直接透出，不做兜底文案。
 */

import request from './request'

/** 音色状态：none（未创建）/ pending（审核中）/ ready（可用）/ failed（失败） */
export type VoiceStatus = 'none' | 'pending' | 'ready' | 'failed'

/** 音色记录（GET /voice-clone/status 的返回） */
export interface VoiceRecord {
  exists: boolean
  id?: string
  shop_id?: string
  voice_id?: string
  voice_name?: string
  target_model?: string
  status: VoiceStatus
  ready: boolean
  error_msg?: string
  sample_url?: string
  sample_name?: string
  sample_size?: number
  sample_duration?: number
  duration_verified?: boolean
  authorized_at?: string
  authorized_by?: string
  authorized?: boolean
  preview_text?: string
  createdAt?: string
  updatedAt?: string
  /** 仅在 refresh=true 时返回：远端实时状态（DEPLOYING / OK / UNDEPLOYED） */
  remote_status?: string
}

/** 面板初始化配置（GET /voice-clone/config 的返回） */
export interface VoiceConfig {
  enabled: boolean
  default_target_model: string
  target_models: { value: string; label: string; note?: string }[]
  default_preview_text: string
  agreement_version: string
  sample_limits: {
    max_bytes: number
    min_seconds: number
    max_seconds: number
    exts: string[]
    /** true = 后端没配 PUBLIC_BASE_URL，样本无法公网回源 → 创建音色会失败 */
    require_public_url: boolean
  }
}

/** 上传样本返回 */
export interface SampleUploadResult {
  url: string
  name: string
  size: number
  duration: number | null
  duration_verified: boolean
  message: string
}

/**
 * 拉取面板配置。
 *
 * ★ 总开关关闭时后端路由不存在 → 抛错。调用方捕获后**隐藏入口**，
 *   而不是把错误弹给用户（用户根本不该知道有这个模块）。
 */
export async function fetchVoiceConfig(): Promise<VoiceConfig> {
  return request.get('/voice-clone/config', { silent: true } as any)
}

/**
 * 上传音频样本（只校验 + 落盘，不创建音色）
 */
export async function uploadVoiceSample(file: File, duration: number | null): Promise<SampleUploadResult> {
  const form = new FormData()
  form.append('file', file)
  if (duration !== null && Number.isFinite(duration)) {
    form.append('duration', String(duration))
  }
  return request.post('/voice-clone/sample', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  } as any)
}

/**
 * 创建复刻音色。
 *
 * `agreementSnapshot` 必须是**用户勾选时前端展示的文案原文** ——
 * 后端原样快照落库，用于日后证明当时授权的是哪一版文本。
 */
export async function enrollVoice(payload: {
  sample_url: string
  filename: string
  duration: number | null
  authorized_by: string
  agreement_snapshot: string
  target_model?: string
  language_hint?: string
  enable_preprocess?: boolean
}): Promise<VoiceRecord> {
  return request.post('/voice-clone/enroll', payload)
}

/**
 * 查询当前店铺音色状态。
 * `refresh=true` 会向远端拉最新状态并同步落库（用于「审核中」的后续确认）。
 *
 * `silentError=true` 时不弹错误提示 —— 供喇叭开关做「静默体检」：
 * 没有音色是**正常情况**（不是故障），提示由开关自己按上下文给。
 */
export async function fetchVoiceStatus(
  refresh = false,
  silentError = false
): Promise<VoiceRecord> {
  return request.get('/voice-clone/status', { params: { refresh }, silentError } as any)
}

/**
 * 试听合成（返回已转存到本地的长期有效 URL）
 */
export async function previewVoice(text: string, targetModel = ''): Promise<{
  audio_url: string
  text: string
  model: string
  expires_hint: string
}> {
  return request.post('/voice-clone/preview', { text, target_model: targetModel })
}

/** 对话播报结果 */
export interface SpeakResult {
  /** 已转存到本地静态目录的音频 URL（远端链接 24h 过期，后端已转存） */
  audio_url: string
  /** 后端**净化后真正念出去**的文本（去掉 markdown/emoji/代码块） */
  spoken_text: string
  model: string
  /** true = 原文超过朗读上限，只念了前面一段（后端如实回报，不静默截断） */
  truncated: boolean
  /** 原始正文长度（未净化），用于向用户解释「为什么只念了一部分」 */
  source_chars: number
  expires_hint: string
}

/**
 * 对话播报：把一条 Agent 回复合成成语音。
 *
 * ★ 与 `previewVoice`（面板试听）的区别，别混用：
 * - **不回写** `preview_text` —— 试听样例是用户选定的，不该被对话正文冲掉
 * - 正文先做**朗读净化**（去 markdown / emoji / 代码块）
 *
 * 失败时静默错误提示（`silentError`），由调用方给出精确原因并关闭开关。
 */
export async function speakVoice(text: string, targetModel = ''): Promise<SpeakResult> {
  return request.post(
    '/voice-clone/speak',
    { text, target_model: targetModel },
    { silentError: true, timeout: 60000 } as any
  )
}

/** 分句计划里的一段（`POST /voice-clone/speak-plan` 的 `segments` 元素） */
export interface SpeechPlanSegment {
  /** 后端**净化后真正要念**的文本（已去 markdown/emoji/代码块） */
  text: string
  /**
   * ★ 该段在**原文坐标系**里的结束偏移 —— 前端拿它当**游标**去重。
   *
   * 为什么必须用原文坐标，而不是「第几段」这种序号：
   * 流式期间会反复对「更长的原文」重算计划，切分点也会因后续内容而变化。
   * 序号在重算时会整体错位；而 `raw_end` **单调不减** ——
   * 只要 `raw_end > cursor`，这段就一定没念过，且不会跳过任何内容。
   */
  raw_end: number
  /** 这一段是否**已定型**（后续增量不会改动它）—— 只有 true 才允许提前合成 */
  stable: boolean
  /** 净化后字数 */
  chars: number
}

/** 分句计划（`POST /voice-clone/speak-plan` 的返回） */
export interface SpeechPlanResult {
  segments: SpeechPlanSegment[]
  /** 全文净化后的总字数 */
  clean_chars: number
  /** 计划实际会念的字数 */
  plan_chars: number
  /** true = 全文超过朗读上限，计划只覆盖了前面一段（后端如实回报） */
  truncated: boolean
  /** 原始正文长度（未净化） */
  source_chars: number
}

/**
 * 对话播报：**分句计划**（纯计算，不合成、不查库、不落库）。
 *
 * ★ 为什么切句要问后端、而不是前端自己按标点 split：
 * 切句规则与「朗读净化」规则是**同一条业务规则的两面** —— 段边界必须落在
 * 「换行补句号」不生效的位置，否则「逐段净化后拼接」会与「整段净化」不一致。
 * 前端再实现一遍就是同一规则两套实现，早晚分叉。
 *
 * 调用形态（分句流水线）：
 * 1. 流式期间反复拿「到目前为止的正文」来算，**只消费 `stable=true` 的段**；
 * 2. 用返回的 `raw_end` 当游标去重；
 * 3. 流结束后再算一次，把结尾那段 `stable=false` 的碎片补上。
 *
 * ★ 静默：本端点由播报队列**自动高频**调用（每个增量一次），
 *   既不该弹成功提示，也不该弹错误提示 —— 失败原因由 store 统一给出并关开关。
 */
export async function fetchSpeechPlan(text: string): Promise<SpeechPlanResult> {
  return request.post(
    '/voice-clone/speak-plan',
    { text },
    { silent: true, silentError: true, timeout: 15000 } as any
  )
}

/**
 * 删除当前店铺音色（同时释放远端配额）
 */
export async function deleteVoice(): Promise<{ success: boolean; message: string }> {
  return request.delete('/voice-clone')
}
