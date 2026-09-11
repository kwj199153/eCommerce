/**
 * SSE 流式请求封装
 *
 * 用 fetch + ReadableStream 解析 text/event-stream，
 * 支持自定义事件（event: delta / done / meta / error）。
 *
 * 为什么不用 EventSource：
 * - EventSource 只支持 GET，无法携带请求体（POST JSON）
 * - 无法自定义 Authorization / X-Shop-ID 头
 * 故用 fetch + 手动解析。
 */

import { useUserStore } from '@/stores/user'

export interface SSEHandlers {
  /** 增量文本 */
  onDelta?: (text: string) => void
  /** 元信息（结构化结果 + 展示类型，可选） */
  onMeta?: (meta: { display_type?: string; data?: any }) => void
  /** 结束（携带完整文本） */
  onDone?: (fullText: string) => void
  /** 出错 */
  onError?: (message: string) => void
}

/**
 * 发起 SSE 流式 POST 请求
 *
 * @param url     相对路径，如 '/listing/chat/stream'（自动补 /api/v1 前缀）
 * @param body    请求体（JSON）
 * @param handlers 事件回调
 */
export async function streamSSE(
  url: string,
  body: Record<string, any>,
  handlers: SSEHandlers = {},
): Promise<string> {
  const userStore = useUserStore()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (userStore.token) {
    headers.Authorization = `Bearer ${userStore.token}`
  }
  const shopId = localStorage.getItem('current_shop_id')
  if (shopId) {
    headers['X-Shop-ID'] = shopId
  }

  const fullUrl = url.startsWith('/api') ? url : `/api/v1${url}`

  const response = await fetch(fullUrl, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    const message = `请求失败 (${response.status}) ${detail}`
    handlers.onError?.(message)
    throw new Error(message)
  }

  if (!response.body) {
    const message = '当前环境不支持流式读取'
    handlers.onError?.(message)
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let fullText = ''

  // 逐行解析 SSE 帧
  const handleLine = (line: string, eventType: string) => {
    if (line.startsWith('data:')) {
      const payload = line.slice(5).trim()
      if (!payload) return
      let data: any
      try {
        data = JSON.parse(payload)
      } catch {
        data = payload
      }

      if (eventType === 'delta') {
        const text = typeof data === 'string' ? data : data?.text || ''
        if (text) {
          fullText += text
          handlers.onDelta?.(text)
        }
      } else if (eventType === 'meta') {
        handlers.onMeta?.(data)
      } else if (eventType === 'done') {
        const doneText = typeof data === 'string' ? data : data?.text || fullText
        if (doneText) fullText = doneText
        handlers.onDone?.(fullText)
      } else if (eventType === 'error') {
        const msg = typeof data === 'string' ? data : data?.message || '流式请求出错'
        handlers.onError?.(msg)
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 按 \n\n 分隔事件帧
    let frameIdx: number
    while ((frameIdx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, frameIdx)
      buffer = buffer.slice(frameIdx + 2)

      // 解析帧内的 event: 和 data: 行
      let eventType = 'message'
      const lines = frame.split('\n')
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else {
          handleLine(line, eventType)
        }
      }
    }
  }

  // 兜底：若服务端未显式发 done，这里补齐
  handlers.onDone?.(fullText)
  return fullText
}
