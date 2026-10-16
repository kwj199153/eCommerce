/**
 * 每日经营简报 store 的**行为**用例（第 371 轮）
 * ============================================================================
 * 这批用例钉的不是「能取到数」，而是**失败时的三个诚实性判据** ——
 * 它们都不会报错、不会被类型系统拦住，只有在界面上表现为「徽标骗人 / 空态撒谎」：
 *
 *   B1 取数失败**不得清空** items / unread（保留旧值 = 显示「上一次的内容」，
 *      清空 = 显示「今天没有需要你处理的变化」—— 后者是一句**关于业务的话**）
 *   B2 标记已读**失败**时本地 read_at / unread 一个都不动
 *      （否则请求 404 了徽标却减一 ⇒ 刷新又冒出来，用户看到「点了没反应、还越来越多」）
 *   B3 已读重复标记走**本地短路**，不再发请求（服务端虽然幂等，但没必要往返）
 *
 * 依赖注入：`@/api/briefings` 整个被 mock 掉 —— 顺带避免加载 `./request`
 * （它带着 axios 实例与浏览器侧设施，本目录的 vitest 跑在 `environment: 'node'`）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/briefings', () => ({
  fetchBriefings: vi.fn(),
  markBriefingRead: vi.fn(),
}))

import { fetchBriefings, markBriefingRead } from '@/api/briefings'
import { useBriefingStore } from '@/stores/briefing'
import type { DailyBriefing } from '@/api/briefings'

const mockFetch = vi.mocked(fetchBriefings)
const mockMark = vi.mocked(markBriefingRead)

function row(over: Partial<DailyBriefing> = {}): DailyBriefing {
  return {
    id: 'brief-2026-10-03-shopA',
    brief_date: '2026-10-03',
    shop_id: 'shopA',
    items: [],
    summary: '今天有 1 项变化：1 个降价',
    item_count: 1,
    read_at: null,
    generated_at: '2026-10-03T00:37:00+00:00',
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('briefing store · load', () => {
  it('成功：写入列表与未读数', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 1 })
    const s = useBriefingStore()
    await s.load()
    expect(s.items).toHaveLength(1)
    expect(s.unread).toBe(1)
    expect(s.loadError).toBeNull()
    expect(s.loading).toBe(false)
  })

  it('★ 失败：保留旧值而不是清空（B1）', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 3 })
    const s = useBriefingStore()
    await s.load()

    mockFetch.mockRejectedValueOnce(new Error('boom'))
    await s.load()

    // 失败后：仍然拿着上一次的数据 + 明确记下错误（界面两个都要画）
    expect(s.items).toHaveLength(1)
    expect(s.unread).toBe(3)
    expect(s.loadError).toBe('boom')
    expect(s.loading).toBe(false)
  })

  it('失败：错误信息缺失时给固定人话，而不是空串', async () => {
    mockFetch.mockRejectedValueOnce({})
    const s = useBriefingStore()
    await s.load()
    expect(s.loadError).toBe('简报加载失败')
  })
})

describe('briefing store · markRead', () => {
  it('成功：read_at 落地且未读数减一', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 1 })
    mockMark.mockResolvedValueOnce(row({ read_at: '2026-10-03T01:00:00+00:00' }))
    const s = useBriefingStore()
    await s.load()

    await expect(s.markRead('brief-2026-10-03-shopA')).resolves.toBe(true)
    expect(s.items[0].read_at).toBe('2026-10-03T01:00:00+00:00')
    expect(s.unread).toBe(0)
  })

  it('已读重复标记：本地短路，不发请求（B3）', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row({ read_at: '2026-10-03T01:00:00+00:00' })], total: 1, unread: 0 })
    const s = useBriefingStore()
    await s.load()

    await expect(s.markRead('brief-2026-10-03-shopA')).resolves.toBe(true)
    expect(mockMark).not.toHaveBeenCalled()
  })

  it('★ 失败：本地已读态与未读数**一个都不动**（B2）', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 1 })
    mockMark.mockRejectedValueOnce(new Error('404'))
    const s = useBriefingStore()
    await s.load()

    await expect(s.markRead('brief-2026-10-03-shopA')).resolves.toBe(false)
    expect(s.items[0].read_at).toBeNull()
    expect(s.unread).toBe(1)
  })

  it('未读数夹到 0（服务端已算出 0 时本地减一不得为负）', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 0 })
    mockMark.mockResolvedValueOnce(row({ read_at: '2026-10-03T01:00:00+00:00' }))
    const s = useBriefingStore()
    await s.load()

    await s.markRead('brief-2026-10-03-shopA')
    expect(s.unread).toBe(0)
  })

  it('列表里没有这个 id：直接 false，不发请求', async () => {
    const s = useBriefingStore()
    await expect(s.markRead('nope')).resolves.toBe(false)
    expect(mockMark).not.toHaveBeenCalled()
  })
})

describe('briefing store · 在途响应的时序（真机竞态）', () => {
  /**
   * 这一组钉的是**在途响应乱序**：`openDrawer()` 的 `load()` 不等响应就把抽屉
   * 打开，用户完全可能在它落地前展开并标记已读 ⇒ 那次响应描述的是「旧世界」。
   * ★ 归因留痕：最初的线索是真机探针 B9 报「徽标停在 1」，但**后续取证推翻**了
   *   「就是这个竞态」的结论 —— B9 的真因是探针读错了 antd 数字滚筒的 DOM。
   *   竞态本身仍然成立（只是本机 localhost 太快没复现），所以照写并在此钉住。
   *   用 `Awaited<ReturnType<typeof fetchBriefings>>` 而不是再 import 一份返回类型：
   *   手抄的类型一旦和 `api/briefings.ts` 漂移，用例会「因为类型对不上」而红，
   *   而红的理由与产品行为无关（本仓记过的「同一事实两份声明」）。
   */
  it('★ 迟到的旧响应不得把「刚标记的已读」覆盖回去', async () => {
    mockFetch.mockResolvedValueOnce({ items: [row()], total: 1, unread: 1 })
    const s = useBriefingStore()
    await s.load()

    // ① 「打开抽屉」发出的那次取数（慢，描述的是**写之前**的世界）
    let release!: (v: Awaited<ReturnType<typeof fetchBriefings>>) => void
    mockFetch.mockImplementationOnce(
      () => new Promise<Awaited<ReturnType<typeof fetchBriefings>>>((res) => { release = res }),
    )
    const inflight = s.load()

    // ② 期间用户展开 ⇒ 标记已读成功
    mockMark.mockResolvedValueOnce(row({ read_at: '2026-10-03T01:00:00+00:00' }))
    await s.markRead('brief-2026-10-03-shopA')
    expect(s.unread).toBe(0)

    // ③ 旧响应迟到（带着 unread=1）⇒ 必须**丢弃**，不许写回去
    release({ items: [row()], total: 1, unread: 1 })
    await inflight

    expect(s.unread).toBe(0)
    expect(s.items[0].read_at).toBe('2026-10-03T01:00:00+00:00')
  })

  it('后发的取数赢：先发的响应迟到不得覆盖它', async () => {
    let releaseFirst!: (v: Awaited<ReturnType<typeof fetchBriefings>>) => void
    mockFetch.mockImplementationOnce(
      () => new Promise<Awaited<ReturnType<typeof fetchBriefings>>>((res) => { releaseFirst = res }),
    )
    const s = useBriefingStore()
    const first = s.load()

    mockFetch.mockResolvedValueOnce({ items: [row({ summary: '新的' })], total: 1, unread: 5 })
    await s.load()
    expect(s.unread).toBe(5)

    releaseFirst({ items: [row({ summary: '旧的' })], total: 1, unread: 1 })
    await first
    expect(s.unread).toBe(5)
    expect(s.items[0].summary).toBe('新的')
  })
})
