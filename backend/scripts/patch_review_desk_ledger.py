# -*- coding: utf-8 -*-
"""
第 291 轮 · 一次性补丁：把「处置台账」并入 ReviewDeskConfig 第三视图。

★ 为什么要用脚本而不是发多个 Edit：
  同一条消息里多个 Edit 并发读同一个 src，后写覆盖先写（本仓铁律）；
  这里对同一个文件有 14 处替换，必须串行 + `assert count == 1`。

★ 行尾：本文件实测全是 CRLF（614/614），所有替换串落盘前会换成 '\r\n'，
  否则：①锚点匹配不到；②侥幸匹配到也会把全文件翻成 LF ⇒ diff 全是噪声。
"""
from pathlib import Path

TARGET = Path(
    r"D:\ai\eCommerce\frontend\src\components\TaskConfigPanel\configs\ReviewDeskConfig.vue"
)

raw = TARGET.read_bytes().decode("utf-8")
NL = "\r\n" if "\r\n" in raw else "\n"
src = raw
log: list[str] = []


def rep(tag: str, old: str, new: str, expect: int = 1) -> None:
    global src
    o = old.replace("\n", NL)
    n = new.replace("\n", NL)
    c = src.count(o)
    assert c == expect, "[{}] anchor count {} != {}: {!r}".format(tag, c, expect, old[:70])
    src = src.replace(o, n, expect)
    log.append("  OK  {}  (old {}B -> new {}B)".format(tag, len(o), len(n)))


# ---------------------------------------------------------------- 头部注释
rep(
    "R1 头部注释：三视图关系 + 为什么台账要并进来",
    """ * ★ 为什么它要单独立一个面板，而不是复用 `DispositionLibrary`
 * ------------------------------------------------------------------------
 * 两者**主语不同**，不是同一能力的两份实现：
 *   · `DispositionLibrary`（资料库）以**处置**为主语 —— 台账视角，看的是
 *     「已经发起过的处置」，天然看不到"还没处置过的差评"；
 *   · 本面板以**差评**为主语 —— 看的是「本店发生了什么」，处置是它下面的一个
 *     动作区。⇒ 没有第二个视图，未处置的差评就永远不会出现在任何界面上。
 *   两者的处置**动作**（propose/approve/reject/issue）都走同一份
 *   `api/trade.ts` 与同一批后端端点，不存在第二套调用。
""",
    """ * ★ 三个视图不是三个功能，是**同一件事的三个切面**（第 291 轮收敛）
 * ------------------------------------------------------------------------
 *   · 近期差评 / 未关联产品 —— 以**差评**为主语：本店发生了什么、哪条还没管；
 *   · 处置台账 —— 以**处置**为主语：已经发起过的草稿，现在处于什么状态。
 *   两者不能互相顶替：台账天然看不到「还没处置过的差评」，而差评列表也看不到
 *   「差评本身已不在时间窗内、但历史上发放过」的那批处置。
 *
 * ★★ 为什么台账必须并到这里，而不是留在资料库独立成页
 * ------------------------------------------------------------------------
 *   原先资料库里的 `DispositionLibrary`（资料库 → 差评处置）与本面板
 *   **各有一套** approve / reject / issue 按钮 —— 同一个「人审不可逆动作」
 *   存在两个 UI 出口，HITL 的唯一把关点就被架空了。
 *   合并后这三个写动作全仓只在本文件被调用；那个入口连同侧边栏项一并删除。
""",
)

# ---------------------------------------------------------------- import
rep(
    "R2 import：补 listDispositions / backfillDispositions / DispositionReview",
    """import { ReloadOutlined } from '@ant-design/icons-vue'
import {
  listShopReviews,
  listOrphanReviews,
  getDisposition,
  proposeDisposition,
  approveDisposition,""",
    """import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import {
  listShopReviews,
  listOrphanReviews,
  listDispositions,
  getDisposition,
  proposeDisposition,
  backfillDispositions,
  approveDisposition,""",
)

rep(
    "R3 import type：补 DispositionReview",
    """  type ProductReview,
  type Disposition,
  type DispositionStatus,
} from '@/api/trade'""",
    """  type ProductReview,
  type Disposition,
  type DispositionReview,
  type DispositionStatus,
} from '@/api/trade'""",
)

# ---------------------------------------------------------------- 常量表
rep(
    "R4 通道/补偿中文名 + 状态筛选项",
    """const REVIEW_STATUS_LABELS: Record<string, string> = {
  new: '待处理',
  triaged: '已归因',
  replied: '已回复',
  closed: '已结案',
}
""",
    """const REVIEW_STATUS_LABELS: Record<string, string> = {
  new: '待处理',
  triaged: '已归因',
  replied: '已回复',
  closed: '已结案',
}

/** 处置通道中文名 —— 与后端 `service.DISPOSITION_CHANNELS` 逐字对齐（5 个取值） */
const CHANNEL_LABELS: Record<string, string> = {
  reply: '回复',
  coupon: '补偿券',
  refund: '退款',
  reship: '补发',
  escalate: '升级',
}

/** 补偿类型中文名 —— 额度为 0 时也要能把「升级处理」这类无额度的通道说清楚 */
const COMPENSATION_TYPE_LABELS: Record<string, string> = {
  coupon: '优惠券',
  refund: '退款',
  reship: '重发',
  escalate: '升级处理',
}

/** 台账状态筛选项 —— 与 `DISPOSITION_STATUS_LABELS` 同源，不手写第二份 */
const DISPOSITION_STATUS_OPTIONS = (
  Object.keys(DISPOSITION_STATUS_LABELS) as DispositionStatus[]
).map((s) => ({ label: DISPOSITION_STATUS_LABELS[s], value: s }))
""",
)

# ---------------------------------------------------------------- VIEWS
rep(
    "R5 VIEWS 加第三个视图 + viewLabel",
    """const VIEWS = [
  { key: 'recent', label: '近期差评', icon: '📉', hint: '本店时间窗内的中差评' },
  { key: 'orphan', label: '未关联产品', icon: '🧩', hint: 'ASIN / SKU 码对不上本店任何产品的差评' },
] as const
""",
    """const VIEWS = [
  { key: 'recent', label: '近期差评', icon: '📉', hint: '本店时间窗内的中差评' },
  { key: 'orphan', label: '未关联产品', icon: '🧩', hint: 'ASIN / SKU 码对不上本店任何产品的差评' },
  { key: 'ledger', label: '处置台账', icon: '📋', hint: '已发起的处置：草稿在这里由人批准 / 发放' },
] as const
""",
)

# ---------------------------------------------------------------- state
rep(
    "R6 state：台账行 + 状态筛选 + backfilling",
    """const counts = ref<Record<ViewKey, number | null>>({ recent: null, orphan: null })
""",
    """const counts = ref<Record<ViewKey, number | null>>({ recent: null, orphan: null, ledger: null })

/** 处置台账的行 —— 以**处置**为主语，与上面以差评为主语的 `items` 不是一回事 */
const dispositions = ref<Disposition[]>([])
const dispTotal = ref(0)
const dispStatusFilter = ref<DispositionStatus | undefined>(undefined)
const backfilling = ref(false)

/** 加载中的「正在读取…」要跟当前视图同名，不能写死成「近期差评」 */
const viewLabel = computed(
  () => VIEWS.find((v) => v.key === view.value)?.label || '',
)
""",
)

# ---------------------------------------------------------------- 抽屉入参归一
rep(
    "R7 抽屉的评价字段归一（三个入口字段多寡不同）",
    """const detailOpen = ref(false)
const detailLoading = ref(false)
const detailReview = ref<ProductReview | null>(null)
const detailReviewId = ref('')
const disposition = ref<Disposition | null>(null)
const acting = ref(false)
""",
    """const detailOpen = ref(false)
const detailLoading = ref(false)
const detailReviewId = ref('')
const disposition = ref<Disposition | null>(null)
const acting = ref(false)

/**
 * 抽屉里那条差评的展示形状。
 *
 * ★ 为什么多这一层：抽屉有三个入口 —— 近期差评 / 孤儿差评给的是 `ProductReview`
 *   （字段最全），台账给的是 `DispositionReview` 摘要（**没有** asin / source /
 *   status）。不归一就会变成「同一个抽屉按入口不同走两套取值」，这正是本仓
 *   反复踩的「同一判定两份实现」。
 */
interface DetailView {
  id: string
  sku: string
  asin: string
  rating: number | null
  title: string
  body: string
  review_at: string
  buyer_name: string
  source: string
}

const detailView = ref<DetailView | null>(null)

function toDetailView(
  r: ProductReview | DispositionReview | null | undefined,
  id: string,
): DetailView {
  return {
    id,
    sku: r?.sku || '',
    asin: (r as ProductReview | undefined)?.asin || '',
    rating: r?.rating ?? null,
    title: r?.title || '',
    body: r?.body || '',
    review_at: r?.review_at || '',
    buyer_name: r?.buyer_name || '',
    source: (r as ProductReview | undefined)?.source || '',
  }
}
""",
)

# ---------------------------------------------------------------- 空态计算
rep(
    "R8 空态三语义 + 逃生口",
    """async function reload() {
  loading.value = true""",
    """/** 当前视图有没有行 —— 台账与差评列表是**两套不同的行**，不能合成一个数组算 */
const hasRows = computed(() =>
  view.value === 'ledger' ? dispositions.value.length > 0 : items.value.length > 0,
)

/**
 * ★ 台账的「空」有两种语义，必须分开播报：
 *   · 筛选后为空 ⇒ 「换个状态看看」；
 *   · 压根没有处置 ⇒ 「点生成待处置」；
 *   统一写成「暂无差评处置」＝把「我筛错了」转译成「你还没处置过」。
 */
const emptyTitle = computed(() => {
  if (view.value === 'ledger') {
    return dispStatusFilter.value ? '这个状态下没有处置记录' : '还没有任何差评处置'
  }
  return view.value === 'orphan' ? '没有未关联产品的差评' : '本时间窗内没有符合条件的评价'
})
const emptyDesc = computed(() => {
  if (view.value === 'ledger') {
    return dispStatusFilter.value
      ? '换一个状态，或清空筛选看全部。'
      : '点「生成待处置」：按已落库的归因与补偿规则，为还没处理的中差评生成待批准草稿。'
  }
  return view.value === 'orphan'
    ? '所有差评都能对上本店产品的 ASIN / SKU 码 —— 这是好消息，说明关联没缺口。'
    : '可以放宽时间窗或改成全部星级再看。'
})
const emptyIcon = computed(() =>
  view.value === 'ledger' ? '📋' : view.value === 'orphan' ? '🧩' : '✅',
)
/** ★ 筛选造成的空必须有逃生口 —— 否则用户只能靠回忆自己刚筛了什么 */
const isFilteredEmpty = computed(() => view.value === 'ledger' && !!dispStatusFilter.value)

async function reload() {
  loading.value = true""",
)

# ---------------------------------------------------------------- reload
rep(
    "R9 reload 分支到台账",
    """  try {
    if (view.value === 'orphan') {
      const res = await listOrphanReviews({
        max_rating: maxRating.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.orphan = res.total
    } else {
      const res = await listShopReviews({
        max_rating: maxRating.value, days: days.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.recent = res.total
    }
    await loadDispositionStates()
  } catch (e: any) {
    // ★ 失败必须回写界面：否则所有失败都表现为「列表是空的，但又说不清为什么」
    error.value = e?.response?.data?.detail || e?.message || '差评列表加载失败'
    items.value = []
    total.value = 0
  } finally {""",
    """  try {
    if (view.value === 'ledger') {
      const res = await listDispositions({
        status: dispStatusFilter.value, limit: 200,
      })
      dispositions.value = res.items
      dispTotal.value = res.total
      counts.value.ledger = res.total
    } else if (view.value === 'orphan') {
      const res = await listOrphanReviews({
        max_rating: maxRating.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.orphan = res.total
      await loadDispositionStates()
    } else {
      const res = await listShopReviews({
        max_rating: maxRating.value, days: days.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.recent = res.total
      await loadDispositionStates()
    }
  } catch (e: any) {
    // ★ 失败必须回写界面：否则所有失败都表现为「列表是空的，但又说不清为什么」
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
    items.value = []
    total.value = 0
    dispositions.value = []
    dispTotal.value = 0
  } finally {""",
)

# ---------------------------------------------------------------- 动态 import → 静态
rep(
    "R10 loadDispositionStates 改静态 import",
    """    const { listDispositions } = await import('@/api/trade')
    const res = await listDispositions({ limit: 200 })""",
    """    const res = await listDispositions({ limit: 200 })""",
)

# ---------------------------------------------------------------- 逃生口
rep(
    "R11 resetFilters",
    """function switchView(k: ViewKey) {
  view.value = k
  void reload()
}
""",
    """function switchView(k: ViewKey) {
  view.value = k
  void reload()
}

/** 清空台账状态筛选 —— 筛选造成的空态唯一的逃生口 */
function resetFilters() {
  dispStatusFilter.value = undefined
  void reload()
}
""",
)

# ---------------------------------------------------------------- 抽屉入口
rep(
    "R12 抽屉：三个入口归一 + 详情接口摘要覆盖",
    """async function openDetail(r: ProductReview) {
  detailReview.value = r
  detailReviewId.value = r.id
  disposition.value = null
  detailOpen.value = true
  detailLoading.value = true
  try {
    disposition.value = await getDisposition(r.id)
  } catch {
    disposition.value = null    // 404：尚无处置，属正常状态
  } finally {
    detailLoading.value = false
  }
}
""",
    """/** 差评列表行 → 抽屉 */
function openDetail(r: ProductReview) {
  void openDispositionDrawer(r.id, toDetailView(r, r.id))
}

/** 台账行 → 抽屉（`review` 摘要可能没带 ⇒ 允许先只认 review_id） */
function openDispositionDetail(d: Disposition) {
  void openDispositionDrawer(d.review_id, d.review ? toDetailView(d.review, d.review_id) : null)
}

async function openDispositionDrawer(reviewId: string, seedView: DetailView | null) {
  detailView.value = seedView
  detailReviewId.value = reviewId
  disposition.value = null
  detailOpen.value = true
  detailLoading.value = true
  try {
    disposition.value = await getDisposition(reviewId)
    // ★ 详情接口带的评价摘要才是权威的：台账行的摘要字段不全 ⇒ 拿到就覆盖
    if (disposition.value?.review) {
      detailView.value = toDetailView(disposition.value.review, reviewId)
    }
  } catch {
    disposition.value = null    // 404：尚无处置，属正常状态
  } finally {
    // 兜底：seed 与详情都没有 ⇒ 至少把 id 撑住，别让抽屉整个空白
    if (!detailView.value) detailView.value = toDetailView(null, reviewId)
    detailLoading.value = false
  }
}
""",
)

# ---------------------------------------------------------------- backfill
rep(
    "R13 runBackfill（review_dispositions 唯一批量写入口）",
    """/** 生成草稿 —— 幂等，Agent 也能调这一步；后面的批准/发放只能人点 */""",
    """/**
 * 批量给「有归因但还没处置」的差评补生成草稿（幂等，已有则跳过）。
 *
 * ★★ 全仓只有这一处按钮：这个能力是从被删掉的资料库页搬过来的。
 *   若不搬，「批量生成」这条**写入路径就彻底消失** —— 而它是
 *   `review_dispositions` 唯一的批量写入口（单条走上面 proposeDraft）。
 */
async function runBackfill() {
  backfilling.value = true
  try {
    const out = await backfillDispositions()
    if (out.created > 0) {
      message.success(`已生成 ${out.created} 条待批准处置`)
    } else if (out.failed?.length) {
      message.warning(
        `没有生成新草稿：${out.failed.length} 条给不出方案（多半是缺归因或没配规则）`,
      )
    } else {
      message.info('没有需要生成的差评（都已处置，或还没有归因）')
    }
    await reload()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '生成处置失败'
  } finally {
    backfilling.value = false
  }
}

/** 生成草稿 —— 幂等，Agent 也能调这一步；后面的批准/发放只能人点 */""",
)

# ---------------------------------------------------------------- 文案函数
rep(
    "R14 compensationText 补 refund_percent / 通道名 / 时间",
    """function compensationText(comp: Record<string, any>): string {
  const type = String(comp.type || '')
  const amount = Number(comp.amount || 0)
  const currency = comp.currency || 'USD'
  const label = { coupon: '优惠券', refund: '退款', reship: '重发', escalate: '升级处理' }[type] || type
  return amount ? `${label} ${amount} ${currency}` : label
}
""",
    """/** 补偿金额文案 —— ★ 退款可以按**百分比**给（`refund_percent`），要先赛过金额 */
function compensationText(comp: Record<string, any> | null | undefined): string {
  if (!comp) return '—'
  const type = String(comp.type || '')
  const amount = Number(comp.amount || 0)
  const currency = comp.currency || 'USD'
  if (type === 'refund' && comp.refund_percent) return `退款 ${comp.refund_percent}%`
  const label = COMPENSATION_TYPE_LABELS[type] || type
  return amount > 0 ? `${label} ${amount} ${currency}` : label || '—'
}

/** 通道中文名（与后端值域对齐；认不出的取值原样吐出来，不静默吞掉） */
function channelLabel(c: string): string {
  return CHANNEL_LABELS[c] || c
}

function shortTime(v: string): string {
  return (v || '').replace('T', ' ').slice(0, 16)
}
""",
)

# ================================================================ template

rep(
    "T1 工具条：差评视图 / 台账视图分开",
    """    <div class="rd-filter">
      <span class="rd-filter-label">时间窗</span>""",
    """    <!-- 差评列表：时间窗 + 星级 -->
    <div v-if="view !== 'ledger'" class="rd-filter">
      <span class="rd-filter-label">时间窗</span>""",
)

rep(
    "T2 台账工具条（状态筛选 + 生成待处置）",
    """      <a-select v-model:value="maxRating" size="small" class="rd-days" @change="reload">
        <a-select-option :value="3">≤3 星（中差评）</a-select-option>
        <a-select-option :value="5">全部星级</a-select-option>
      </a-select>
    </div>
""",
    """      <a-select v-model:value="maxRating" size="small" class="rd-days" @change="reload">
        <a-select-option :value="3">≤3 星（中差评）</a-select-option>
        <a-select-option :value="5">全部星级</a-select-option>
      </a-select>
    </div>

    <!-- 处置台账：状态筛选 + 批量生成（★「生成待处置」全仓只此一处） -->
    <div v-else class="rd-filter">
      <span class="rd-filter-label">状态</span>
      <a-select
        v-model:value="dispStatusFilter"
        size="small"
        class="rd-days"
        allow-clear
        placeholder="全部状态"
        :options="DISPOSITION_STATUS_OPTIONS"
        @change="reload"
      />
      <a-button size="small" type="primary" :loading="backfilling" @click="runBackfill">
        <ThunderboltOutlined /> 生成待处置
      </a-button>
      <span class="rd-filter-tip">按「有归因但还没处置」的中差评批量生成草稿（已有则跳过）</span>
    </div>
""",
)

rep(
    "T3 loading / 空态改用三语义",
    """    <div v-else-if="loading && !items.length" class="rd-hint">
      <a-spin size="small" /> 正在读取{{ view === 'orphan' ? '孤儿差评' : '近期差评' }}…
    </div>

    <div v-else-if="!items.length" class="rd-hint">
      <div class="rd-hint-icon">{{ view === 'orphan' ? '🧩' : '✅' }}</div>
      <div class="rd-hint-title">
        {{ view === 'orphan' ? '没有未关联产品的差评' : '本时间窗内没有符合条件的评价' }}
      </div>
      <div class="rd-hint-desc">
        {{ view === 'orphan'
          ? '所有差评都能对上本店产品的 ASIN / SKU 码 —— 这是好消息，说明关联没缺口。'
          : '可以放宽时间窗或改成全部星级再看。' }}
      </div>
    </div>
""",
    """    <div v-else-if="loading && !hasRows" class="rd-hint">
      <a-spin size="small" /> 正在读取{{ viewLabel }}…
    </div>

    <div v-else-if="!hasRows" class="rd-hint">
      <div class="rd-hint-icon">{{ emptyIcon }}</div>
      <div class="rd-hint-title">{{ emptyTitle }}</div>
      <div class="rd-hint-desc">{{ emptyDesc }}</div>
      <div v-if="isFilteredEmpty" class="rd-hint-acts">
        <a-button size="small" @click="resetFilters">清空筛选</a-button>
      </div>
      <div v-else-if="view === 'ledger'" class="rd-hint-acts">
        <a-button size="small" type="primary" :loading="backfilling" @click="runBackfill">
          生成待处置
        </a-button>
      </div>
    </div>
""",
)

rep(
    "T4 台账表格插在差评列表之前（v-else 自动兜差评视图）",
    """    <div v-else class="rd-list">
""",
    """    <!-- ===== 处置台账：以处置为主语 ===== -->
    <div v-else-if="view === 'ledger'" class="rd-ledger">
      <table class="rd-table">
        <thead>
          <tr>
            <th>SKU</th>
            <th class="num">评分</th>
            <th>差评标题</th>
            <th>通道</th>
            <th class="num">补偿</th>
            <th>状态</th>
            <th class="num">更新</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in dispositions" :key="d.id" @click="openDispositionDetail(d)">
            <td><code>{{ d.review?.sku || '—' }}</code></td>
            <td class="num">{{ d.review?.rating ?? '—' }} 星</td>
            <td class="rd-table-title" :title="d.review?.title || ''">
              {{ d.review?.title || '—' }}
            </td>
            <td>
              <a-tag v-for="c in d.channels" :key="c">{{ channelLabel(c) }}</a-tag>
            </td>
            <td class="num">{{ compensationText(d.compensation) }}</td>
            <td>
              <a-tag :color="DISPOSITION_STATUS_COLORS[d.status]">
                {{ DISPOSITION_STATUS_LABELS[d.status] }}
              </a-tag>
            </td>
            <td class="num">{{ shortTime(d.updated_at) }}</td>
            <td class="rd-table-act">
              <a-button type="link" size="small">查看</a-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="dispTotal > dispositions.length" class="rd-more">
        共 {{ dispTotal }} 条，当前显示 {{ dispositions.length }} 条
      </div>
    </div>

    <!-- ===== 差评列表：以差评为主语 ===== -->
    <div v-else class="rd-list">
""",
)

rep(
    "T5 抽屉标题与字段改用归一后的 detailView",
    """      :title="detailReview ? `差评处置 · ${detailReview.title || detailReview.id}` : '差评处置'\"""",
    """      :title="detailView ? `差评处置 · ${detailView.title || detailView.id}` : '差评处置'\"""",
)

rep(
    "T6 抽屉描述项",
    """      <template v-if="detailReview">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="星级">{{ detailReview.rating }} 星</a-descriptions-item>
          <a-descriptions-item label="ASIN"><code>{{ detailReview.asin || '-' }}</code></a-descriptions-item>
          <a-descriptions-item label="SKU"><code>{{ detailReview.sku || '-' }}</code></a-descriptions-item>
          <a-descriptions-item label="时间">{{ detailReview.review_at || '-' }}</a-descriptions-item>
          <a-descriptions-item label="买家">{{ detailReview.buyer_name || '匿名' }}</a-descriptions-item>
          <a-descriptions-item label="来源">
            {{ detailReview.source === 'mock_seed' ? '演示数据' : detailReview.source }}
          </a-descriptions-item>
        </a-descriptions>

        <div class="rd-section">
          <h4>📝 评价正文</h4>
          <div class="rd-body-full">{{ detailReview.body || '（无正文）' }}</div>
        </div>""",
    """      <template v-if="detailView">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="星级">{{ detailView.rating ?? '-' }} 星</a-descriptions-item>
          <a-descriptions-item label="ASIN"><code>{{ detailView.asin || '-' }}</code></a-descriptions-item>
          <a-descriptions-item label="SKU"><code>{{ detailView.sku || '-' }}</code></a-descriptions-item>
          <a-descriptions-item label="时间">{{ detailView.review_at || '-' }}</a-descriptions-item>
          <a-descriptions-item label="买家">{{ detailView.buyer_name || '匿名' }}</a-descriptions-item>
          <a-descriptions-item label="来源">
            {{ detailView.source === 'mock_seed' ? '演示数据' : detailView.source || '-' }}
          </a-descriptions-item>
        </a-descriptions>

        <div class="rd-section">
          <h4>📝 评价正文</h4>
          <div class="rd-body-full">{{ detailView.body || '（无正文）' }}</div>
        </div>""",
)

rep(
    "T7 抽屉里的通道也要中文（与台账同一份文案）",
    """              <span class="rd-v">{{ disposition.channels.join(' / ') }}</span>""",
    """              <span class="rd-v">{{ disposition.channels.map(channelLabel).join(' / ') }}</span>""",
)

rep(
    "T8 样式：台账表格 / 工具条提示 / 空态按钮",
    """.rd-disp-rejected { color: #ff4d4f; }
""",
    """.rd-disp-rejected { color: #ff4d4f; }
.rd-filter-tip {
  font-size: var(--font-size-12);
  color: var(--text-disabled);
}
.rd-hint-acts {
  margin-top: var(--space-8);
}
.rd-ledger {
  overflow-x: auto;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
}
.rd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-12);
  white-space: nowrap;
}
.rd-table th,
.rd-table td {
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--border-base);
  text-align: left;
}
.rd-table th {
  background: var(--bg-elevated);
  font-weight: 600;
}
.rd-table .num {
  text-align: right;
}
.rd-table tbody tr {
  cursor: pointer;
}
.rd-table tbody tr:hover {
  background: var(--bg-elevated);
}
.rd-table-title {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rd-table-act {
  text-align: right;
}
""",
)

# ================================================================ 落盘
TARGET.write_bytes(src.encode("utf-8"))

print("NL =", repr(NL))
print("patches applied:", len(log))
for line in log:
    print(line)

# 残留检查：detailReview 必须彻底消失，否则模板里会取 undefined
leftover = src.count("detailReview.")
print("leftover 'detailReview.' =", leftover)
assert leftover == 0, "还有 detailReview. 残留 —— 模板会取到 undefined"

after = TARGET.read_bytes().decode("utf-8")
print("bytes:", len(raw), "->", len(after))
print("CRLF count:", after.count("\r\n"), " LF-without-CR:", after.count("\n") - after.count("\r\n"))
