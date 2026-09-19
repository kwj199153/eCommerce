/**
 * 长期记忆 API（第 149~152 轮 批 C2）
 *
 * 后端真源：`backend/modules/memory/router.py`（prefix = `/memory`）
 *
 *      GET  /memory           读：开关 + 记忆全文 + 条目 + 上限（一次给全）
 *      PUT  /memory           写：提交**整份** markdown
 *      PUT  /memory/profile   写：开关
 *      POST /memory/reset     写：清空全部条目（开关保留）
 *      GET  /memory/logs      读：学习时间线
 *      POST /memory/distill   写：立即整理一次（同步执行、会调模型、计配额）
 *
 * ★★ 为什么这些类型要照抄后端的返回结构
 * ======================================
 * 本模块此前**根本没有** api 层 —— `MemoryEvolution.vue` 是 36 行硬编码假记忆
 * + 7 条假日志 + 保存零 API 调用（r141 §2.4 判定为「假页面」）。
 * 那时"类型"是照着假数据编的；现在照 `service.snapshot()` / `list_logs()` /
 * `tasks.distill_one_owner()` 的真实返回写。**形状抄错不会有任何东西报错**，
 * 只会表现为界面上某个字段永远显示 `undefined` —— 所以有一条门禁
 * （`frontend/scripts/check-memory-reality.cjs`）拿本文件与后端 router
 * 做双向路径对账。
 *
 * ★★ 为什么这里**没有** `owner_id`
 * =================================
 * 归属一律取自服务端身份（`current_user.id`）。请求体里带 `owner_id` 是本项目
 * 真实踩过的洞 —— `ConversationCreateRequest.owner_id` 曾是客户端自报字段，
 * 实测能把自己的会话挂到别人名下。
 * ★ 客户端**照旧发** `owner_id` 不会 422（pydantic 默认忽略多余字段），
 *   但也不会被采纳 —— 所以"发了没事"不是可以发的理由，而是更难发现的理由。
 *   本文件里连这个字段名都不出现（门禁钉住）。
 *
 * ★ 上限（60 条 / 每节配额 / 单条 500 字）**只有一份**，在后端
 *   `ai_infra/memory/limits.py`，经 `GET /memory` 的 `limits` 字段下发。
 *   前端不得再写一份常量：改了后端忘改前端，界面上那个"60 条上限"与实际
 *   开始 400 的阈值就对不上，而没有任何东西会红。
 */

import { get, post, put } from './request'

// ====== 返回类型（照抄后端）======

/** 条目来源。`distill` 只能由每晚任务写，客户端不得自报。 */
export type MemorySource = 'manual' | 'import' | 'distill'

/** 一条长期记忆（= `ai_infra.memory.entry.MemoryEntry.as_dict()`）。 */
export interface MemoryEntry {
  /** 数据库主键（可空：机制层不保证有） */
  id: string | null
  content: string
  section: string
  source: MemorySource
  /** 去重键（后端算，前端不用管） */
  key: string
  /** 重要性权重（10 = 手写/导入，1 = AI 归纳）。满了先挤掉权重低的。 */
  weight: number
  updated_at: string | null
}

/** 「生成对话记忆」开关状态。 */
export interface MemoryProfile {
  enabled: boolean
  /** 上次**发起**整理的时间（成功与失败都写；见 service.claim_distill_run） */
  last_distilled_at: string | null
}

/**
 * 上限口径（后端真源，前端不要再写一份）。
 *
 * ★ 为什么由后端下发：上限是**后端判据**。前端写一份就是第二份实现。
 */
export interface MemoryLimits {
  max_entries: number
  max_entry_chars: number
  max_logs: number
  /** 规范分节名（顺序即展示顺序） */
  sections: string[]
  /** 分节 → 配额 */
  section_quota: Record<string, number>
}

/** `GET /memory` 的返回：打开抽屉就是这一发。 */
export interface MemorySnapshot {
  profile: MemoryProfile
  /** 记忆全文（★ 空串 = 真的没有内容，**不是**"暂无记忆"占位文案） */
  markdown: string
  entries: MemoryEntry[]
  entry_count: number
  updated_at: string | null
  limits: MemoryLimits
}

/** 时间线记录类型。★ 真源在 `ai_infra/memory/limits.py` 的 `LOG_KINDS`。 */
export type MemoryLogKind =
  | 'distill'
  | 'distill_failed'
  | 'manual'
  | 'import'
  | 'reset'

/** 一条学习时间线记录。 */
export interface MemoryLog {
  id: string
  kind: MemoryLogKind
  content: string
  detail: Record<string, any> | null
  /** 带 `Z` 的 ISO 串（后端补的，否则 JS 会按本地时区解析） */
  created_at: string | null
  /**
   * ★★ 「这条是坏消息吗」由**后端**回答，前端不要再列一遍 `kind` 名单。
   *
   * 后端新增一种失败类型时，前端那份名单不会跟着变 ——
   * 结果是一条失败记录被渲染成正常记录，**比不渲染更糟**。
   * 判据见 `ai_infra.memory.limits.FAILURE_LOG_KINDS`（当前 = `distill_failed`）。
   */
  is_failure: boolean
}

/**
 * 「本次整理为什么是这个结局」的**机器可读代码**。
 *
 * ★★ 真源在**后端**，本数组不是 —— 它由两处生产者合起来构成：
 *
 *     `modules/memory/service.py::claim_distill_run`   disabled / too_soon / cooling
 *     `modules/memory/tasks.py::_outcome(reason=...)`   no_messages / distill_failed / persist_failed / ok
 *
 *   前者是**三道闸门**拦下来的三种，后者是**放行之后**的四种。
 *
 * ★ 为什么不用手写联合类型（本文件第一版就是那么写的，而且写错了）：
 *   第一版写的是 `'' | 'disabled' | 'too_soon' | 'cooling'` —— 只有闸门那三种。
 *   而一个**刚注册、还没说过话**的用户点「立即整理」，拿到的第一个 `reason`
 *   就是 `no_messages`：**界面上第一次出现的值就不在那个联合类型里**。
 *   手写清单就是第二份真源，它不会报错，只会在某天安静地漏掉一种结局。
 *
 * ⇒ 改成「一个数组 + 由它派生的类型」，并让
 *   `backend/tests/test_memory_contract.py` **现算**后端那两个文件里的全部
 *   `reason` 取值，与本数组断言**相等**。所以本数组不是"前端又抄了一遍"，
 *   而是**被门禁钉住的镜像**：后端新增一种结局而这里没跟上，CI 会红。
 */
export const DISTILL_REASON_CODES = [
  'disabled',
  'too_soon',
  'cooling',
  'no_messages',
  'distill_failed',
  'persist_failed',
  'ok',
] as const

export type DistillReason = (typeof DISTILL_REASON_CODES)[number]

/** 「立即整理」这一趟做了什么。 */
export interface DistillResult {
  /** 有没有真的跑。false ⇒ 三道闸门拦住了，看 `reason` / `content` */
  ran: boolean
  /** 跑了之后成不成功（`ran=false` 时恒为 false） */
  ok: boolean
  /**
   * 本次结局的代码，见 `DISTILL_REASON_CODES`。
   *
   * ★ 与 `content`（人话）分开是**必要**的：界面要按它分支 ——
   *   开关关着要引导去打开开关，连点只需提示等待。
   *   只有人话串的话，前端就只能做字符串匹配。
   * ★ 界面只对 `disabled` 有额外动作，其余一律按 `content` 展示。
   */
  reason: DistillReason
  /** 跑了但失败时的错误原因 */
  error: string | null
  /** 增删改的计数摘要（`{added, updated, removed, kept}`） */
  summary: Record<string, number> | null
  /** 给人看的一句话结论 */
  content: string
  elapsed_ms: number
}

/** `POST /memory/distill` 的返回。 */
export interface DistillResponse {
  result: DistillResult
  /**
   * ★ 整理之后的完整快照（与 `GET` 同一个实现）。
   *
   * 刻意与 `result` **一起**返回：只给 result 的话前端要再发一次 GET 才能刷新，
   * 于是出现"整理成功但界面还是旧的"这个中间态 —— 用户会再点一次（= 再烧一次钱）。
   */
  memory: MemorySnapshot
}

// ====== 读 ======

/**
 * 读：开关 + 记忆全文 + 条目 + 上限。
 *
 * ★ 空记忆返回 `markdown: ''` 而不是占位文案：占位文案一旦进了文本，
 *   会被后端的 `parse_markdown` 读成**一条真实的记忆**。空状态由界面渲染。
 */
export function fetchMemory(): Promise<MemorySnapshot> {
  return get('/memory')
}

/** 读：学习时间线（**倒序**，最新在前）。 */
export function fetchMemoryLogs(limit = 30): Promise<{ logs: MemoryLog[] }> {
  return get('/memory/logs', { limit })
}

// ====== 写 ======

/**
 * 写：提交**整份** markdown（编辑器里看到的就是全集）。
 *
 * @param source `manual`（编辑器保存）或 `import`（导入文件）。
 *   ★ 只有客户端知道这次是"手打"还是"导入"，所以由调用方给；
 *     但服务端会再校验一次，且**不接受** `distill`（那会让用户内容被标成
 *     "AI 猜测"从而优先被挤掉，而他完全看不出这件事发生过）。
 *
 * ★ 返回**保存之后的完整快照**：界面直接用它重渲染，不需要再发一次 GET ——
 *   也就不会出现"保存成功但界面还是旧内容"这种要刷新才对的中间态。
 * ★ 超限 ⇒ **400**，`detail` 是「第几条超了」的人话清单，不静默截断。
 *   调用方必须把 `detail` 展示出来（只有一个 toast 会丢掉"是哪几条"）。
 */
export function saveMemory(
  markdown: string,
  source: Extract<MemorySource, 'manual' | 'import'> = 'manual',
): Promise<MemorySnapshot> {
  return put('/memory', { markdown, source })
}

/**
 * 写：开关。返回库里的**权威值**，由调用方回写本地开关状态。
 *
 * ★ 必须用返回值回写、失败时要重新取一次权威值：否则一次失败的写入会留下
 *   一个"看起来打开了、其实没打开"的界面状态，而用户唯一的线索是
 *   "为什么它不记我的偏好"。
 */
export function setMemoryEnabled(enabled: boolean): Promise<{ profile: MemoryProfile }> {
  return put('/memory/profile', { enabled })
}

/**
 * 写：清空全部条目（**保留开关**）。
 *
 * ★ 保留开关是刻意的：用户点"重置"的意思是「忘掉我记过的东西」，
 *   不是「以后别再记了」。要停止学习请用开关。
 */
export function resetMemory(): Promise<MemorySnapshot> {
  return post('/memory/reset')
}

/**
 * 写：立即整理一次（**同步执行**，会调模型，计配额）。
 *
 * 三种结局都由 200 返回、靠字段区分（HTTP 200 包装业务失败**不构成伪成功**，
 * 判据是 `ok` 而不是状态码）：
 *
 *     result.ran === false          —— 没跑；`content` 是人话原因，`reason` 是原因代码
 *     result.ran && result.ok       —— 跑了且成功
 *     result.ran && !result.ok      —— 跑了但失败（`error`；时间线里也有一条记录）
 *
 * ★ 三道闸门**绕不过**（开关关着 / 60 秒内连点 / 24 小时冷却）：
 *   它们是后端在 `service.claim_distill_run` 里判的，前端不要预先判 ——
 *   前端判一次就是第二份实现，而两边迟早不一致。
 */
export function distillMemoryNow(): Promise<DistillResponse> {
  return post('/memory/distill')
}
