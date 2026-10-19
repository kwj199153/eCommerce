/**
 * 存盘唯一出口 —— Web 走浏览器下载，壳走原生「另存为」
 * ==================================================
 *
 * ★★★ 为什么必须收成一个出口（这是"打包能成功但用不了"的第三个断点）
 * ---------------------------------------------------------------------------
 * Web 上 `a[download]` 由**浏览器下载管理器**接手：存下载目录、显示下载条、失败会报错。
 * WebView2 / Android WebView 里**没有下载管理器** ⇒ 同一个 `a.click()` 的表现是
 * **什么都没发生**：不报错、不弹框、控制台干净。
 * ⇒ "没报错"在这里一文不值 —— 改之前它也不报错。
 *
 * ★★★ 判据只能落在磁盘上
 * ---------------------------------------------------------------------------
 * 唯一有证明力的读数是**目标位置多了一个字节完全一致的文件**
 * （`desktop/probes/_probe-desktop-save.mjs` 的 S2）。
 *
 * ★ 为什么先解 base64 再编码、再传（而不是传 Blob）：Tauri 2 的 IPC 走 JSON 序列化，
 *   `Uint8Array` 会展开成 `number[]`（体积约 3.5 倍、解析极慢）；base64 只膨胀 33%。
 *
 * ★ 为什么壳里失败要**回落**到浏览器下载：桌面开发态（vite dev）没有壳的注入，
 *   同一份代码要照常工作。但注意——**在没有下载管理器的宿主上，回落等于静默失败**，
 *   所以调用方必须把 `fallback` 与 `saved` 分开对待（该提示的提示、该说实话的说实话）。
 */

import type {} from '@/config/runtimeApi'

export type SaveStatus = 'saved' | 'cancelled' | 'fallback'

export interface SaveOutcome {
  status: SaveStatus
  /** 壳里保存成功时的绝对路径（Web 上为 undefined） */
  path?: string
  /** 实际文件名 */
  filename: string
  /** 壳里失败的原因（用于 console.warn，不直接给用户看） */
  error?: string
}

/** 当前宿主是否具备原生存盘能力（壳注入的才算是） */
export function hasNativeSave(): boolean {
  return typeof window !== 'undefined' && typeof window.__ECOM_SAVE_FILE__ === 'function'
}

/** Blob → base64（不带 data: 前缀；Rust 侧按 STANDARD 解码） */
export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'))
    reader.onload = () => {
      const s = String(reader.result ?? '')
      // FileReader 给的是 data:...;base64,xxxx —— 只取逗号后面那段
      const idx = s.indexOf(',')
      resolve(idx >= 0 ? s.slice(idx + 1) : s)
    }
    reader.readAsDataURL(blob)
  })
}

/** 浏览器下载（唯一的 `a[download]` 出口） */
function anchorDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * 保存一个 Blob。
 *
 * 顺序：壳的原生存盘 → 浏览器下载。
 * ★ 为什么不放在 `showSaveFilePicker` 后面：那个 API 在 WebView2 里
 *   **存在但不可用**（有函数、点了没反应），属于"看起来支持、实际不生效"的典型，
 *   一旦排在前面就会把壳里唯一的正路挡掉。
 */
export async function saveBlob(blob: Blob, filename: string): Promise<SaveOutcome> {
  if (hasNativeSave()) {
    try {
      const base64 = await blobToBase64(blob)
      const path = await window.__ECOM_SAVE_FILE__!(filename, base64)
      if (path === null) return { status: 'cancelled', filename }
      return { status: 'saved', path: path || undefined, filename }
    } catch (e) {
      // ★ 说实话：壳里存盘失败就是失败，不假装成功（但给出原因，便于排查）
      const msg = e instanceof Error ? e.message : String(e)
      console.warn('[saveFile] 壳内存盘失败，回落浏览器下载：', msg)
      anchorDownload(blob, filename)
      return { status: 'fallback', filename, error: msg }
    }
  }
  anchorDownload(blob, filename)
  return { status: 'fallback', filename }
}

/** 文本落盘（UTF-8）。用于对话记录 .md 这类纯文本导出。 */
export async function saveText(text: string, filename: string, mime = 'text/plain;charset=utf-8') {
  return saveBlob(new Blob([text], { type: mime }), filename)
}
