/**
 * 通用文件导出工具
 *
 * 支持 JSON / Excel(.xlsx) / CSV / TXT 四种格式。
 * 「目标位置」优先走 File System Access API（showSaveFilePicker），
 * 弹出系统级「另存为」对话框让用户选择目标文件夹；浏览器不支持时自动降级为普通下载。
 */

/** 今天的日期戳，用于文件名，如 20260906 */
export function todayStamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
}

/** 导出格式 */
export type ExportFormat = 'json' | 'excel' | 'csv' | 'txt'

export const EXPORT_FORMAT_META: Record<
  ExportFormat,
  { label: string; ext: string; icon: string; mime: string }
> = {
  json: { label: 'JSON（完整结构）', ext: 'json', icon: '🧾', mime: 'application/json;charset=utf-8' },
  excel: { label: 'Excel（表格）', ext: 'xlsx', icon: '📊', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
  csv: { label: 'CSV（表格文本）', ext: 'csv', icon: '📄', mime: 'text/csv;charset=utf-8' },
  txt: { label: 'TXT（纯文本）', ext: 'txt', icon: '📝', mime: 'text/plain;charset=utf-8' },
}

/** 表格数据（Excel/CSV/TXT 用；首行即表头） */
export interface ExportTable {
  headers: string[]
  rows: (string | number)[][]
}

export interface ExportPayload {
  format: ExportFormat
  /** JSON 格式时导出的完整对象数组 */
  jsonData?: unknown
  /** Excel/CSV/TXT 时的表格（含表头） */
  table?: ExportTable
  /** 文件名（不含扩展名），如：平台规则库_20260906 */
  baseName: string
}

// ================= 各格式序列化 =================

/** JSON：2 空格缩进 UTF-8 字符串 */
function toJsonString(data: unknown): string {
  return JSON.stringify(data, null, 2)
}

/** CSV：自动转义（逗号/引号/换行包引号）；加 BOM 防 Excel 中文乱码 */
function toCsvString(headers: (string | number)[], rows: (string | number)[][]): string {
  const esc = (v: string | number) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [headers.map(esc).join(',')]
  for (const r of rows) lines.push(r.map(esc).join(','))
  return '\ufeff' + lines.join('\r\n')
}

/** TXT：可读的分行文本（每条标题 + 内容块，之间空行分隔） */
function toTxtString(headers: string[], rows: (string | number)[][]): string {
  const blocks = rows.map(r => {
    // 第一列作为"标题行"，其余列缩进列出（用于话术/规则这种"标题+正文"结构）
    const [head, ...rest] = r
    const title = headers[0] ? `【${headers[0]}】${head}` : String(head ?? '')
    const body = rest
      .map((cell, i) => {
        const h = headers[i + 1] ?? ''
        const s = String(cell ?? '')
        if (!h) return s
        return `${h}：${s}`
      })
      .filter(Boolean)
      .join('\n')
    return body ? `${title}\n${body}` : title
  })
  return blocks.join('\n\n')
}

/** Excel：用 xlsx 库构建 sheet，返回 ArrayBuffer 供写文件 */
export async function toExcelArrayBuffer(headers: string[], rows: (string | number)[][]): Promise<ArrayBuffer> {
  const XLSX = await import('xlsx')
  const aoa = [headers, ...rows]
  const ws = XLSX.utils.aoa_to_sheet(aoa)
  // 简单自适应列宽
  const maxCol = Math.max(...aoa.map(r => r.length))
  ws['!cols'] = Array.from({ length: maxCol }, (_, ci) => {
    const width = aoa.reduce((m, r) => Math.max(m, String(r[ci] ?? '').length), 10)
    return { wch: Math.min(Math.max(width + 2, 10), 60) }
  })
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '导出数据')
  const out = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  return out as ArrayBuffer
}

// ================= 文件写出（优先系统另存为） =================

type SaveHandle = FileSystemFileHandle

/** 判断当前浏览器是否支持 File System Access API */
export function canUseSavePicker(): boolean {
  return typeof window !== 'undefined' && 'showSaveFilePicker' in window
}

function blobFor(payload: ExportPayload): Promise<Blob> | Blob {
  const meta = EXPORT_FORMAT_META[payload.format]
  if (payload.format === 'json') {
    return new Blob([toJsonString(payload.jsonData ?? [])], { type: meta.mime })
  }
  const headers = payload.table?.headers ?? []
  const rows = payload.table?.rows ?? []
  if (payload.format === 'excel') {
    return toExcelArrayBuffer(headers, rows).then(
      buf => new Blob([buf], { type: meta.mime })
    )
  }
  const text =
    payload.format === 'csv' ? toCsvString(headers, rows) : toTxtString(headers, rows)
  return new Blob([text], { type: meta.mime })
}

/** 降级：普通浏览器下载到默认下载目录 */
function fallbackDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export interface ExportResult {
  /** saved=已写入用户所选位置; fallback=浏览器不支持另存为,已下载到默认目录; cancelled=用户取消 */
  status: 'saved' | 'fallback' | 'cancelled'
  /** 实际文件名（含扩展名） */
  filename: string
}

/**
 * 导出文件。优先 showSaveFilePicker 让用户选目标文件夹；不支持则降级下载。
 */
export async function saveExportFile(payload: ExportPayload): Promise<ExportResult> {
  const ext = EXPORT_FORMAT_META[payload.format].ext
  const filename = `${payload.baseName}.${ext}`
  const blob = await blobFor(payload)

  // 1) 支持 File System Access：弹系统「另存为」对话框选择位置
  const w = window as unknown as {
    showSaveFilePicker?: (opts: {
      suggestedName?: string
      types?: { description: string; accept: Record<string, string[]> }[]
    }) => Promise<SaveHandle>
  }
  if (typeof w.showSaveFilePicker === 'function') {
    try {
      const handle = await w.showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: EXPORT_FORMAT_META[payload.format].label,
            accept: { [EXPORT_FORMAT_META[payload.format].mime.split(';')[0]]: [`.${ext}`] },
          },
        ],
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return { status: 'saved', filename: handle.name }
    } catch (e) {
      // AbortError = 用户在对话框点了取消；其它错误可降级
      if ((e as Error)?.name === 'AbortError') return { status: 'cancelled', filename }
      // 其它错误（如权限被拒）——降级为普通下载
      fallbackDownload(blob, filename)
      return { status: 'fallback', filename }
    }
  }

  // 2) 不支持：降级普通下载
  fallbackDownload(blob, filename)
  return { status: 'fallback', filename }
}

// ================= 保留旧 API（向后兼容 / 其它调用方） =================

/** 下载 JSON 文件（浏览器 Blob 下载，无另存为） */
export function downloadJsonFile(data: unknown, filename: string): void {
  fallbackDownload(new Blob([toJsonString(data)], { type: 'application/json;charset=utf-8' }), filename)
}

/** 下载 CSV 文件（无另存为） */
export function downloadCsvFile(rows: (string | number)[][], filename: string): void {
  // rows 需已含表头行
  const [header, ...body] = rows
  fallbackDownload(
    new Blob([toCsvString(header ?? [], body)], { type: 'text/csv;charset=utf-8' }),
    filename
  )
}
