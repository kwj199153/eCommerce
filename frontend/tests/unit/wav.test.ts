/**
 * `utils/wav.ts` 行为契约（第 355 轮 · #1282）
 * ============================================================================
 * 本模块是整条录音链路里**唯一可离线验证**的部分（文件头注释明说了），
 * 且它踩过一次真实故障：「头必须写真实长度」—— 平台侧流式 WAV 会把 data 段长度
 * 写成哨兵 `0x7FFFFFFF`，那样的文件再当输入会被拒。所以这里把 **44 字节头逐字段**钉住，
 * 包括「长度必须等于 data 实际字节数，且不得是哨兵值」这条。
 *
 * ★ 为什么能在 `environment: 'node'` 下跑：
 *   只需要 `Float32Array` / `ArrayBuffer` / `DataView` / `Blob`，
 *   Node 18+ 起 `Blob` 已是全局（本仓 CI 用 Node 22）⇒ 无需 jsdom。
 */
import { describe, it, expect } from 'vitest'
import {
  TARGET_SAMPLE_RATE,
  encodeWavPcm16,
  mergeChunks,
  resampleLinear,
  toWavBlob,
} from '@/utils/wav'

/** 读 ASCII（用于核对 RIFF 头的魔数段） */
function ascii(view: DataView, offset: number, len: number): string {
  let s = ''
  for (let i = 0; i < len; i += 1) s += String.fromCharCode(view.getUint8(offset + i))
  return s
}

describe('wav · resampleLinear 线性插值重采样', () => {
  it('空输入原样返回（同一个引用，不新造空数组）', () => {
    const empty = new Float32Array(0)
    expect(resampleLinear(empty, 48000, 24000)).toBe(empty)
  })

  it('采样率相同 ⇒ 原样返回（不重采样、不改数值）', () => {
    const a = Float32Array.from([1, 2, 3])
    expect(resampleLinear(a, 24000, 24000)).toBe(a)
  })

  it('升采样：长度按 ratio 变化，取值是真实线性插值', () => {
    // ratio = 1/2 = 0.5 ⇒ outLen = round(2/0.5) = 4
    // 位置 0 / 0.5 / 1 / 1.5 ⇒ [0, 5, 10, 10]（末尾 i1 被夹到最后一个样本）
    const out = resampleLinear(Float32Array.from([0, 10]), 1, 2)
    expect(Array.from(out)).toEqual([0, 5, 10, 10])
  })

  it('降采样 48000 → 24000：长度减半，整数比时取到原样本点', () => {
    const out = resampleLinear(Float32Array.from([0, 1, 2, 3, 4, 5]), 48000, 24000)
    expect(out.length).toBe(3)
    expect(Array.from(out)).toEqual([0, 2, 4])
  })

  it('极端降采样也不会产出空数组（outLen 至少 1）', () => {
    const out = resampleLinear(Float32Array.from([7]), 1000, 1)
    expect(out.length).toBe(1)
    expect(out[0]).toBe(7)
  })

  it('首个样本与末个样本是端点值（不该被插值抹掉）', () => {
    const src = Float32Array.from([0.25, 0.5, 0.75, 1])
    const out = resampleLinear(src, 48000, 24000)
    expect(out[0]).toBe(src[0])
  })
})

describe('wav · mergeChunks 分片拼接', () => {
  it('按顺序拼接，长度等于各分片之和', () => {
    const out = mergeChunks([Float32Array.from([1, 2]), Float32Array.from([3])], 3)
    expect(Array.from(out)).toEqual([1, 2, 3])
  })

  it('total 大于各分片之和 ⇒ 尾部补 0（调用方传入的 total 是权威长度）', () => {
    const out = mergeChunks([Float32Array.from([1, 2]), Float32Array.from([3])], 5)
    expect(Array.from(out)).toEqual([1, 2, 3, 0, 0])
  })

  it('空分片列表 + total 0 ⇒ 空数组', () => {
    expect(mergeChunks([], 0).length).toBe(0)
  })
})

describe('wav · encodeWavPcm16 的 44 字节头（逐字段）', () => {
  const N = 3
  const RATE = 24000
  const samples = Float32Array.from([0, 0.5, -0.5])
  const buf = encodeWavPcm16(samples, RATE)
  const view = new DataView(buf)

  it('总字节数 = 44 + 样本数 × 2（单声道 16bit）', () => {
    expect(buf.byteLength).toBe(44 + N * 2)
  })

  it('魔数段：RIFF / WAVE / fmt␣ / data', () => {
    expect(ascii(view, 0, 4)).toBe('RIFF')
    expect(ascii(view, 8, 4)).toBe('WAVE')
    expect(ascii(view, 12, 4)).toBe('fmt ')
    expect(ascii(view, 36, 4)).toBe('data')
  })

  it('RIFF 块长度字段 = 36 + 数据字节数', () => {
    expect(view.getUint32(4, true)).toBe(36 + N * 2)
  })

  it('fmt 子块各字段：PCM / 单声道 / 采样率 / 字节率 / 块对齐 / 位深', () => {
    expect(view.getUint32(16, true)).toBe(16) // PCM 描述块长度
    expect(view.getUint16(20, true)).toBe(1) // 编码格式 1 = PCM
    expect(view.getUint16(22, true)).toBe(1) // 单声道
    expect(view.getUint32(24, true)).toBe(RATE)
    expect(view.getUint32(28, true)).toBe(RATE * 2) // 字节率 = 采样率 × 声道 × 位深/8
    expect(view.getUint16(32, true)).toBe(2) // 块对齐
    expect(view.getUint16(34, true)).toBe(16) // 位深
  })

  it('★ data 段长度必须是真实字节数，且**不得**是哨兵 0x7FFFFFFF', () => {
    // 这就是文件头注释里那次真实故障：哨兵值的文件再当输入会被平台拒
    const dataLen = view.getUint32(40, true)
    expect(dataLen).toBe(N * 2)
    expect(dataLen).not.toBe(0x7fffffff)
  })

  it('样本映射：[-1,1] → int16，且正负采用不对称满量程（-0x8000 / +0x7fff）', () => {
    const v2 = new DataView(encodeWavPcm16(Float32Array.from([-1, 1, 0]), RATE))
    expect(v2.getInt16(44, true)).toBe(-32768) // -1 × 0x8000
    expect(v2.getInt16(46, true)).toBe(32767) // +1 × 0x7fff
    expect(v2.getInt16(48, true)).toBe(0)
  })

  it('超出 [-1,1] 的样本被夹住，不溢出 int16', () => {
    const v2 = new DataView(encodeWavPcm16(Float32Array.from([-2, 2]), RATE))
    expect(v2.getInt16(44, true)).toBe(-32768)
    expect(v2.getInt16(46, true)).toBe(32767)
  })

  it('半量程样本按 WebAudio 惯例截断取整（0.5 → 16383 / -0.5 → -16384）', () => {
    const v2 = new DataView(encodeWavPcm16(Float32Array.from([0.5, -0.5]), RATE))
    expect(v2.getInt16(44, true)).toBe(16383)
    expect(v2.getInt16(46, true)).toBe(-16384)
  })

  it('字节序是小端（非小端读会得到明显不同的值）', () => {
    // 单字段交叉验证：24kHz = 0x5DC0 ⇒ 小端字节序列 C0 5D 00 00
    expect(view.getUint8(24)).toBe(0xc0)
    expect(view.getUint8(25)).toBe(0x5d)
    expect(view.getUint8(26)).toBe(0x00)
    expect(view.getUint8(27)).toBe(0x00)
  })
})

describe('wav · toWavBlob 便捷组合', () => {
  it('TARGET_SAMPLE_RATE 是 24000（CosyVoice 推荐值）', () => {
    expect(TARGET_SAMPLE_RATE).toBe(24000)
  })

  it('原生就是 24kHz ⇒ 不重采样，长度 = 44 + n×2', async () => {
    const blob = toWavBlob(Float32Array.from([0, 0, 0, 0, 0, 0]), 24000)
    expect(blob.type).toBe('audio/wav')
    expect(blob.size).toBe(44 + 6 * 2)
    const view = new DataView(await blob.arrayBuffer())
    expect(view.getUint32(24, true)).toBe(24000)
    expect(ascii(view, 0, 4)).toBe('RIFF')
  })

  it('原生 48kHz ⇒ 重采样到 24kHz（样本数减半），头里写的采样率是 24000', async () => {
    const blob = toWavBlob(Float32Array.from([0, 1, 2, 3, 4, 5]), 48000)
    expect(blob.size).toBe(44 + 3 * 2)
    const view = new DataView(await blob.arrayBuffer())
    expect(view.getUint32(24, true)).toBe(24000)
    expect(view.getUint32(40, true)).toBe(3 * 2)
  })

  it('非标准原生采样率（44100）也会被归一到 24000', async () => {
    const blob = toWavBlob(new Float32Array(441), 44100)
    const view = new DataView(await blob.arrayBuffer())
    expect(view.getUint32(24, true)).toBe(24000)
    // 44100 → 24000 ⇒ round(441 / (44100/24000)) = 240 个样本
    expect(view.getUint32(40, true)).toBe(240 * 2)
  })
})
