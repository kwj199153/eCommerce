/**
 * SSE 流式请求封装
 *
 * 用 fetch + ReadableStream 解析 text/event-stream，
 * 支持自定义事件（event: delta / progress / step / meta / done / error）。
 *
 * 为什么不用 EventSource：
 * - EventSource 只支持 GET，无法携带请求体（POST JSON）
 * - 无法自定义 Authorization / X-Shop-ID 头
 * 故用 fetch + 手动解析。
 */

// ★ L3-3（第 351 轮）：SSE 走的是**第二个** HTTP 出口（裸 fetch，不经 axios），
//   所以它必须自己带 X-Request-ID、自己读响应头 —— 否则流式链路的 trace 永远是断的。
//   生成/记忆规则与 axios 出口共用同一份实现（`api/traceId.ts`）。
import { newTraceId, rememberTraceId } from '@/api/traceId'
import { useUserStore } from '@/stores/user'

/**
 * 用户主动取消（「停止生成」按钮）时抛出的异常。
 *
 * ★★ 为什么必须是一个**独立的错误类型**（而不是 `new Error('已取消')`）：
 *   6 条回复链的 `catch` 只认一件事 —— 「这一轮是不是被用户取消的」。
 *   若取消与真失败抛同一种异常，那 6 条链只能靠**文案**去区分，而文案是会变的
 *   （改措辞、做本地化）⇒ 取消会被误渲染成「后端服务暂时不可用」，
 *   甚至触发一次非流式重试把答案又补回来。类型是编译期事实，文案是运行时猜测。
 */
export class StreamCancelledError extends Error {
  /** 标记位：跨模块实例（打包分块 / 不同 import 路径）时 `instanceof` 会失效，兜底认它 */
  readonly cancelled = true
  constructor(message = '已停止生成') {
    super(message)
    this.name = 'StreamCancelledError'
  }
}

/**
 * 「这一轮是被用户取消的」的**唯一判定实现**。
 *
 * ★ 全仓只允许有这一份：抄成两份时，至少一条链路的取消会漏判
 *   —— 而取消是低频手动操作，漏了很难在日常点击里发现（本仓「同一判定两份实现」的形态）。
 */
export function isStreamCancelled(err: unknown): boolean {
  if (!err) return false
  if (err instanceof StreamCancelledError) return true
  const e = err as { name?: string; cancelled?: boolean }
  return e?.name === 'StreamCancelledError' || e?.cancelled === true
}

/**
 * fetch / reader 因 abort 而 reject 的判定。
 * 浏览器是 `DOMException{name:'AbortError'}`，个别环境给 `code:'ABORT_ERR'`；
 * 另外 `signal.aborted` 是**最可靠**的一条 —— 三者取或。
 */
function isAbort(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true
  const e = err as { name?: string; code?: string }
  return e?.name === 'AbortError' || e?.code === 'ABORT_ERR'
}

/**
 * 一条「思考过程」步骤（后端 `event: step`，见 `ai_infra/sse.py::step`）。
 *
 * ★ 一次工具调用由**两条**事件组成：`running`（带 `detail` = 入参）与
 *   `done`/`error`（带 `result` = 返回值、`ms` = 耗时）。两者 `id` 相同
 *   （后端用 LangChain 的 `run_id`）—— `stores/chat.ts::appendThinkingStep`
 *   按 `id` 把两条**合成一条**，所以界面上一次工具调用只占一行。
 */
export interface ThinkingStep {
  /** 同一次工具调用的开始 / 结束事件共享此 id（= 后端 `run_id`），是**合并键** */
  id?: string
  kind: 'tool' | 'note'
  /** 人话标题（后端给的是通用措辞，如「正在调用工具」） */
  title: string
  status: 'running' | 'done' | 'error'
  /** 原始工具名 */
  tool?: string
  /** 入参摘要（开始态） */
  detail?: string
  /** 返回值 / 报错摘要（结束态） */
  result?: string
  /** 耗时毫秒（结束态） */
  ms?: number
}

export interface SSEHandlers {
  /** 增量文本（**正文**：后端会把它累进 `done`，也会按它落库） */
  onDelta?: (text: string) => void
  /**
   * 正文**预览**增量（后端 `event: preview`，见 `ai_infra/sse.py::preview`）。
   *
   * ★ 与 `onDelta` 的分工是**可靠性级别**，不是"格式"：
   *   `onDelta` 来的就是正文（会被 `done` 与落库采纳）；
   *   本回调来的只是**预览** —— 它随时会被后一段（见下 `segment`）或最终正文
   *   整段替换。所以：
   *   · **不计入 `fullText`**（否则 `done` 的正文会被预览拼脏）；
   *   · 消费方必须自己决定"怎么把它收口成正文"。
   *
   * ★ `segment` = 触发这段预览的那次模型调用的 `run_id`。同一段内 token 连续
   *   到达；**换段即意味着上一段作废**（ReAct 中间轮那句"我先查一下…"不该留在
   *   屏上）。缺 `segment` 时按"还是同一段"处理 —— 宁可两段黏在一起，
   *   也不要因为拿不到 id 就把预览整段丢掉。
   */
  onPreview?: (text: string, segment: string) => void
  /** 阶段进度提示（长任务期间的状态文案，非正文） */
  onProgress?: (text: string) => void
  /**
   * 思考过程的一步（工具调用的开始 / 结束）。
   *
   * ★ 与 `onProgress` 的分工：progress 是**会被覆盖**的单行提示、用完即弃
   *   （前端只在 `setLoading(false)` 之前拿它当 loading 文案）；
   *   step 是**逐条追加**的轨迹，结果到达后仍要留着 —— 折叠起来可回看。
   */
  onStep?: (step: ThinkingStep) => void
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
 * @param options.signal 中断信号（「停止生成」）。★ 传了它才**真的**能取消：
 *   中止时 `fetch` / `reader.read()` 会 reject，本函数把它转成
 *   `StreamCancelledError` 并**刻意不调 `onError`** —— 后者的消费方会把"取消"
 *   渲染成失败文案（见各回复链 `onError: () => {}` 的注释）。取消的收口一律
 *   由调用方经 `isStreamCancelled` 判定，不走失败路径。
 */
export async function streamSSE(
  url: string,
  body: Record<string, any>,
  handlers: SSEHandlers = {},
  options: { signal?: AbortSignal } = {},
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
  // ★ L3-3：追踪 ID —— 与本仓另一个出口（axios 实例）用同一份生成规则。
  const traceId = newTraceId()
  headers['X-Request-ID'] = traceId
  rememberTraceId(traceId)

  const fullUrl = url.startsWith('/api') ? url : `/api/v1${url}`

  const signal = options.signal

  let response: Response
  try {
    response = await fetch(fullUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      // ★ 唯一让「停止生成」真的生效的地方：没有它，abort() 打不到这条请求，
      //   服务端会一直推到结束、前端也会一直渲染。
      signal,
    })
  } catch (err) {
    // ★ 取消**不是**失败：不调 onError（其消费方会据此写出失败文案），
    //   改抛可识别的取消异常，由回复链短路收口。
    if (isAbort(err, signal)) throw new StreamCancelledError()
    throw err
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    if (isAbort(null, signal)) throw new StreamCancelledError()
    // ★ L3-3：服务端回写的 X-Request-ID 优先于本地生成值（网关可能改写过）。
    //   ⚠️ 尾巴只能加在 detail **之后** —— `请求失败 (${response.status}) `
    //   这个前缀是既有契约（`check-chat-failure-path.cjs` 逐字引用它），
    //   改前缀会打红门禁，也会让用户已经习惯的排障读法失效。
    const serverTraceId = response.headers?.get?.('x-request-id') || ''
    rememberTraceId(serverTraceId || traceId)
    const trace = serverTraceId || traceId
    const message = `请求失败 (${response.status}) ${detail}（追踪 ID：${trace}）`
    handlers.onError?.(message)
    throw new Error(message)
  }

  if (!response.body) {
    if (isAbort(null, signal)) throw new StreamCancelledError()
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
      } else if (eventType === 'preview') {
        // 正文**预览**增量（店秘书链路）。
        // ★ 刻意**不**累进 `fullText`：它是临时管道，真正的正文由 `delta` / `done`
        //   给出。累进来的后果是 `done` 的正文变成「预览 + 正文」拼两遍 ——
        //   而且不报错，只是那段话悄悄变长了。
        const text = typeof data === 'string' ? data : data?.text || ''
        const segment = typeof data === 'string' ? '' : data?.segment || ''
        if (text) handlers.onPreview?.(text, segment)
      } else if (eventType === 'progress') {
        // 阶段进度：只更新状态文案，不计入正文
        const text = typeof data === 'string' ? data : data?.text || ''
        if (text) handlers.onProgress?.(text)
      } else if (eventType === 'step') {
        // 思考过程：交给上层追加到**当前这条**消息上。
        // ★ 与 delta 完全无关 —— 它不计入 fullText（后端也没把它拼进正文）。
        if (data && typeof data === 'object') handlers.onStep?.(data as ThinkingStep)
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
    // ★ 读循环也要过取消判定：`fetch` 已返回、正文正在流时点「停止生成」，
    //   中止点落在这里（`reader.read()` reject），而不是上面那次 fetch。
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch (err) {
      if (isAbort(err, signal)) throw new StreamCancelledError()
      throw err
    }
    const { done, value } = chunk
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
