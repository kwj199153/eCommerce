/**
 * 差评工作台 —— **视图状态**（第 341 轮从 `ReviewDeskConfig.vue` 外移）。
 *
 * ★ 这里放什么 / 不放什么
 * ------------------------------------------------------------------------
 * 放：四个视图共用的**原始状态**（当前视图、筛选、三套行、计数、加载态）与
 *     由它们派生的**纯展示判定**（当前视图名、有没有行、空态文案与图标）。
 * 不放：任何**取数**。所有接口调用仍在 `ReviewDeskConfig.vue` 的 `reload()` /
 *     `loadDispositionStates()` 里 —— 门禁 `check-review-risk-view.cjs` R14 要求
 *     `reload` 的函数体（含它末尾那个「指纹变了才清风险标记」的条件）留在面板内，
 *     且 `check-disposition-write-exit.cjs` C2 要求 `.ts` 层不得 import 任何写 API。
 *     ⇒ 本模块**零 api import**，只持有状态；写入由面板侧完成。
 *
 * ★ 为什么 `view` / `days` / `maxRating` 搬走是安全的
 *     它们是纯 ref，`reload()` 与 `runRiskScan()` 仍能通过返回值写入；
 *     门禁 R13 钉的 `riskListKey`（风险指纹）**没有**搬进来 —— 它必须与
 *     `listKeyOf` / `clearRisk` 同处面板，否则 R13/R14 会判红。
 */
import { ref, computed } from 'vue'
import type {
  ProductReview,
  Disposition,
  DispositionStatus,
  CompensationRule,
} from '@/api/trade'
import { VIEWS, type ViewKey } from './reviewDeskVocabulary'

export function useReviewDeskViews() {
  const view = ref<ViewKey>('recent')
  const days = ref(30)
  const maxRating = ref(3)
  const loading = ref(false)
  const error = ref('')
  const items = ref<ProductReview[]>([])
  const total = ref(0)
  const counts = ref<Record<ViewKey, number | null>>({ recent: null, orphan: null, ledger: null, rules: null })

  /** 处置台账的行 —— 以**处置**为主语，与上面以差评为主语的 `items` 不是一回事 */
  const dispositions = ref<Disposition[]>([])
  const dispTotal = ref(0)
  const dispStatusFilter = ref<DispositionStatus | undefined>(undefined)
  const backfilling = ref(false)

  /** 加载中的「正在读取…」要跟当前视图同名，不能写死成「近期差评」 */
  const viewLabel = computed(
    () => VIEWS.find((v) => v.key === view.value)?.label || '',
  )

  /** 每条差评有没有处置 / 什么状态 —— 列表上要能一眼看出「哪些还没管」 */
  const dispositionStatus = ref<Record<string, DispositionStatus>>({})

  /** 本店全部补偿规则（含停用） */
  const rules = ref<CompensationRule[]>([])
  const rulesError = ref('')

  /** 当前视图有没有行 —— 台账 / 差评列表 / 规则是**三套不同的行**，不能合成一个数组算 */
  const hasRows = computed(() => {
    if (view.value === 'ledger') return dispositions.value.length > 0
    if (view.value === 'rules') return rules.value.length > 0
    return items.value.length > 0
  })

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
    if (view.value === 'rules') return '还没有配置补偿规则'
    return view.value === 'orphan' ? '没有未关联产品的差评' : '本时间窗内没有符合条件的评价'
  })
  const emptyDesc = computed(() => {
    if (view.value === 'ledger') {
      return dispStatusFilter.value
        ? '换一个状态，或清空筛选看全部。'
        : '点「生成待处置」：按已落库的归因与补偿规则，为还没处理的中差评生成待批准草稿。'
    }
    if (view.value === 'rules') {
      return '给每个归因（物流延迟 / 包装破损 / 商品缺陷…）配一条补偿规则，'
        + '处置草稿的补偿金额由这里唯一算出。'
    }
    return view.value === 'orphan'
      ? '所有差评都能对上本店产品的 ASIN / SKU 码 —— 这是好消息，说明关联没缺口。'
      : '可以放宽时间窗或改成全部星级再看。'
  })
  const emptyIcon = computed(() =>
    view.value === 'ledger' ? '📋' : view.value === 'orphan' ? '🧩' : view.value === 'rules' ? '⚙️' : '✅',
  )
  /** ★ 筛选造成的空必须有逃生口 —— 否则用户只能靠回忆自己刚筛了什么 */
  const isFilteredEmpty = computed(() => view.value === 'ledger' && !!dispStatusFilter.value)

  return {
    // 状态（面板侧写入）
    view, days, maxRating, loading, error, items, total, counts,
    dispositions, dispTotal, dispStatusFilter, backfilling,
    dispositionStatus, rules, rulesError,
    // 派生（只读）
    viewLabel, hasRows, emptyTitle, emptyDesc, emptyIcon, isFilteredEmpty,
  }
}
