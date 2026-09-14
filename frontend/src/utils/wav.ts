/**
 * WAV 编码 / 重采样 —— 纯函数，零浏览器依赖
 *
 * ★ 为什么不用 MediaRecorder：
 *   Chrome/Edge 的 `MediaRecorder` 默认产出 `audio/webm;codecs=opus`，
 *   而后端样本白名单只有 `.wav / .mp3 / .m4a`（见 backend/modules/voice_clone/client.py）。
 *   走 WebAudio 拿原始 PCM 自己封 WAV，可以：
 *     1) 直接落在白名单内（后端零改动）；
 *     2) 采样率 / 声道 / 位深全可控（服务器无需 ffmpeg）；
 *     3) 体积可控：24kHz / 单声道 / 16bit 的 20 秒 ≈ 940 KB（上限 10 MB）。
 *
 * ★ 本文件被抽成纯函数的原因：它是整条录音链路里**唯一可离线验证**的部分，
 *   用 Node 直接跑就能生成真实 WAV 并走一遍上传，不必开浏览器。
 */

/** 目标采样率：CosyVoice 推荐值，且 24000 已被本项目的真实链路验证通过。 */
export const TARGET_SAMPLE_RATE = 24000

/**
 * 线性插值重采样。
 *
 * 浏览器 AudioContext 常见的原生采样率是 44100 / 48000，需要降到 24000。
 * 线性插值对语音克隆足够（样本会再经平台侧预处理），且无需引入重采样库。
 */
export function resampleLinear(
  input: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (input.length === 0 || fromRate === toRate) return input
  const ratio = fromRate / toRate
  const outLen = Math.max(1, Math.round(input.length / ratio))
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i += 1) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const frac = pos - i0
    out[i] = input[i0] * (1 - frac) + input[i1] * frac
  }
  return out
}

/** 把多个 Float32 分片按顺序拼成一个数组 */
export function mergeChunks(chunks: Float32Array[], total: number): Float32Array {
  const out = new Float32Array(total)
  let off = 0
  for (const c of chunks) {
    out.set(c, off)
    off += c.length
  }
  return out
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
}

/**
 * 编码为 16bit PCM 单声道 WAV（标准 44 字节头）。
 *
 * ★ 头必须写**真实长度**：CosyVoice 合成接口返回的流式 WAV 把 data 段长度写成哨兵值
 *   0x7FFFFFFF，那样的文件再拿去当输入会被平台拒（历史上已被咬过一次）。
 */
export function encodeWavPcm16(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const n = samples.length
  const buffer = new ArrayBuffer(44 + n * 2)
  const view = new DataView(buffer)

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + n * 2, true)
  writeAscii(view, 8, 'WAVE')

  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // PCM 描述块长度
  view.setUint16(20, 1, true) // 编码格式：1 = PCM
  view.setUint16(22, 1, true) // 声道数：单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 字节率 = 采样率 × 声道 × 位深/8
  view.setUint16(32, 2, true) // 块对齐 = 声道 × 位深/8
  view.setUint16(34, 16, true) // 位深

  writeAscii(view, 36, 'data')
  view.setUint32(40, n * 2, true)

  let off = 44
  for (let i = 0; i < n; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    off += 2
  }
  return buffer
}

/** 便捷组合：任意采样率 PCM → 24kHz 单声道 16bit WAV 的 Blob */
export function toWavBlob(samples: Float32Array, nativeRate: number): Blob {
  const rate = nativeRate === TARGET_SAMPLE_RATE ? nativeRate : TARGET_SAMPLE_RATE
  const data = rate === nativeRate ? samples : resampleLinear(samples, nativeRate, rate)
  return new Blob([encodeWavPcm16(data, rate)], { type: 'audio/wav' })
}
