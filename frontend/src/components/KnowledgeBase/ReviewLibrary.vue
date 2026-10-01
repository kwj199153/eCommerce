<template>
  <!--
    资料库 → 复盘库（第 251 轮 · 第 7 个资料库）

    ★ 与「运营复盘师」对话区的分工：
      那 6 项复盘能力是**算**（算完不落库）；本页是**存**（只放老板点过
      「归档到复盘库」的那些）。所以本页**不生成**任何复盘 —— 空状态里的
      引导是「去对话里生成并归档」，不是给一个「立即生成」的假按钮。

    ★★ 归属完全交给后端：`X-Shop-ID` 由 `api/request.ts` 的请求拦截器注入，
      本页**不传 store_id、也不推算「哪些复盘我看得到」**。
      本仓铁律：前端自算容器 = 后端判据的第二份实现。

    ★★ 空 vs 失败的区分（本仓「两种空语义」那条）：
      · 库里确实没有（total=0）⇒ 空状态 + 引导去归档；
      · 类型筛选后为空 ⇒ 空状态 + 一键清筛选（**必须**留逃生口）；
      · 请求失败 ⇒ 错误态 + 重试，**绝不**退回空状态（那会把故障说成"你没归档过"）。
  -->
  <div class="review-library">
    <div class="rl-head">
      <div class="rl-title-row">
        <h2 class="rl-title">
          复盘库
        </h2>
        <a-tag
          v-if="!loading && !error"
          color="blue"
        >
          共 {{ total }} 份
        </a-tag>
      </div>
      <p class="rl-sub">
        只存你**确认过**的复盘：在对话里生成复盘后点「归档到复盘库」才会进来。
        做下一期复盘时，Agent 会读这里的上期结论做对比。按店铺隔离（换店铺就换内容）。
      </p>
    </div>

    <!-- ===== 工具条 ===== -->
    <div class="rl-bar">
      <a-select
        v-model:value="typeFilter"
        :options="typeOptions"
        allow-clear
        placeholder="全部类型"
        style="width: 180px"
        @change="reload"
      />
      <a-select
        v-model:value="sortBy"
        :options="SORT_OPTIONS"
        style="width: 190px"
        @change="reload"
      />
      <a-button
        :loading="loading"
        @click="reload"
      >
        <ReloadOutlined />
        刷新
      </a-button>
      <span class="rl-hint">
        勾选<b>两份</b>可做「上期 vs 本期」指标对比
      </span>
    </div>

    <!-- ===== 错误态（优先于空状态渲染：故障不得被说成"没有数据"）===== -->
    <a-alert
      v-if="error"
      type="error"
      show-icon
      :message="error"
      class="rl-alert"
    >
      <template #action>
        <a-button
          size="small"
          @click="reload"
        >
          重试
        </a-button>
      </template>
    </a-alert>

    <!-- ===== 空状态 ===== -->
    <a-empty
      v-else-if="!loading && !items.length"
      class="rl-empty"
    >
      <template #description>
        <div class="rl-empty-title">
          {{ emptyTitle }}
        </div>
        <div class="rl-empty-sub">
          {{ emptySub }}
        </div>
      </template>
      <a-button
        v-if="typeFilter"
        size="small"
        @click="clearFilter"
      >
        清空筛选
      </a-button>
    </a-empty>

    <!-- ===== 列表 ===== -->
    <a-spin
      v-else
      :spinning="loading"
    >
      <div class="rl-table-wrap">
        <table class="rl-table">
          <thead>
            <tr>
              <th class="c-pick" />
              <th>类型</th>
              <th class="num">
                周期
              </th>
              <th class="num">
                周期末日
              </th>
              <th>一句话结论</th>
              <th class="num">
                归档时间
              </th>
              <th class="c-act" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in items"
              :key="it.id"
              :class="{ picked: compareIds.includes(it.id) }"
            >
              <td class="c-pick">
                <a-checkbox
                  :checked="compareIds.includes(it.id)"
                  :disabled="!compareIds.includes(it.id) && compareIds.length >= 2"
                  @change="toggleCompare(it.id)"
                />
              </td>
              <td>
                <a-tag color="geekblue">
                  {{ reviewTitleOf(it.report_type) }}
                </a-tag>
              </td>
              <td class="num">
                近 {{ it.period_days }} 天
              </td>
              <td class="num">
                {{ it.period_end }}
              </td>
              <td
                class="c-summary"
                :title="it.summary"
              >
                {{ it.summary || '—' }}
              </td>
              <td class="num">
                {{ shortTime(it.created_at) }}
              </td>
              <td class="c-act">
                <a-button
                  type="link"
                  size="small"
                  @click="openDetail(it.id)"
                >
                  查看
                </a-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <!-- ===== 周期对比（勾选两份后出现）===== -->
    <section
      v-if="compareIds.length === 2"
      class="rl-compare"
    >
      <div class="rl-cmp-head">
        <DiffOutlined />
        <span>周期对比</span>
        <a-button
          type="link"
          size="small"
          @click="compareIds = []"
        >
          清空
        </a-button>
      </div>

      <a-spin :spinning="cmpLoading">
        <a-alert
          v-if="cmpError"
          type="error"
          show-icon
          :message="cmpError"
          class="rl-alert"
        />
        <template v-else>
          <div class="rl-cmp-title">
            <span class="rl-cmp-side">
              本期 · {{ reviewTitleOf(cmpNew?.report_type) }} · {{ cmpNew?.period_end }}
            </span>
            <span class="rl-cmp-vs">vs</span>
            <span class="rl-cmp-side">
              上期 · {{ reviewTitleOf(cmpOld?.report_type) }} · {{ cmpOld?.period_end }}
            </span>
          </div>
          <div
            v-if="cmpTypeMismatch"
            class="rl-cmp-warn"
          >
            两份复盘的<b>类型不同</b>，只有指标名相同的行能对比（其余显示「—」）。
          </div>
          <table class="rl-table rl-cmp-table">
            <thead>
              <tr>
                <th>指标</th>
                <th class="num">
                  本期
                </th>
                <th class="num">
                  上期
                </th>
                <th class="num">
                  变化
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in cmpRows"
                :key="row.label"
              >
                <td>{{ row.label }}</td>
                <td class="num">
                  {{ row.newText }}
                </td>
                <td class="num">
                  {{ row.oldText }}
                </td>
                <td
                  class="num"
                  :class="row.deltaClass"
                >
                  {{ row.deltaText }}
                </td>
              </tr>
            </tbody>
          </table>
          <div
            v-if="!cmpRows.length"
            class="rl-cmp-empty"
          >
            两份复盘都没有可对比的指标（后端这份报告没给 `metrics`）。
          </div>
        </template>
      </a-spin>
    </section>

    <!-- ===== 详情抽屉（含完整快照）===== -->
    <a-drawer
      v-model:open="detailOpen"
      title="复盘详情"
      :width="WINDOW_W.xxl"
      placement="right"
    >
      <!--
        ★ 第 266 轮：导出入口。挂在抽屉头部 —— 老板正在看这份复盘时最想导的
          就是它。表格行与「对话结果卡」的导出共用同一份摊平函数
          （`utils/reviewExport.ts`），两处各写一份会导出成两张不一样的表。
      -->
      <template #extra>
        <a-button
          v-if="exportRows.length"
          size="small"
          @click="exportOpen = true"
        >
          <DownloadOutlined />
          导出
        </a-button>
      </template>
      <a-spin :spinning="detailLoading">
        <a-alert
          v-if="detailError"
          type="error"
          show-icon
          :message="detailError"
          class="rl-alert"
        />
        <template v-else-if="detail">
          <div class="rl-d-head">
            <a-tag color="geekblue">
              {{ reviewTitleOf(detail.report_type) }}
            </a-tag>
            <a-tag>近 {{ detail.period_days }} 天</a-tag>
            <a-tag>周期末日 {{ detail.period_end }}</a-tag>
          </div>
          <p class="rl-d-summary">
            {{ detail.summary || '（这份复盘没有一句话结论）' }}
          </p>

          <div
            v-if="detailMetrics.length"
            class="rl-d-grid"
          >
            <div
              v-for="m in detailMetrics"
              :key="m.label"
              class="rl-d-cell"
            >
              <div class="rl-d-k">
                {{ m.label }}
              </div>
              <div class="rl-d-v">
                {{ metricTextOf(m) }}
              </div>
            </div>
          </div>

          <div
            v-if="detailInsights.length"
            class="rl-d-block"
          >
            <div class="rl-d-caption">
              观察
            </div>
            <ul class="rl-d-list">
              <li
                v-for="(t, i) in detailInsights"
                :key="i"
              >
                {{ t }}
              </li>
            </ul>
          </div>
          <div
            v-if="detailActions.length"
            class="rl-d-block"
          >
            <div class="rl-d-caption">
              建议动作
            </div>
            <ul class="rl-d-list">
              <li
                v-for="(t, i) in detailActions"
                :key="i"
              >
                {{ t }}
              </li>
            </ul>
          </div>

          <div
            v-if="detailTable"
            class="rl-d-block"
          >
            <div class="rl-d-caption">
              {{ detailTable.caption }}
            </div>
            <table class="rl-table">
              <thead>
                <tr>
                  <th
                    v-for="c in detailTable.columns"
                    :key="c.key"
                    :class="{ num: c.num }"
                  >
                    {{ c.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, i) in detailTable.rows"
                  :key="i"
                >
                  <td
                    v-for="c in detailTable.columns"
                    :key="c.key"
                    :class="{ num: c.num }"
                  >
                    {{ c.render(row) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="rl-d-foot">
            归档时间 {{ detail.created_at }}<span v-if="detail.updated_at !== detail.created_at"> · 更新于 {{ detail.updated_at }}</span>
          </div>
        </template>
        <a-empty
          v-else
          description="没有内容"
        />
      </a-spin>
    </a-drawer>

    <!--
      导出弹窗。★ 与对话结果卡的导出**共用同一份摊平函数与同一份表头**
        （`utils/reviewExport.ts`）。
      ★ `json-data` 是详情接口回的 `data` 快照**原样**，本页不重算任何值。
      ★ 周期末日只进**文件名**：`ReviewReport` 里没有 `period_end`（它是归档时
        服务端写的），所以同类型同周期长度的两份归档在 JSON 里彼此不可区分 ——
        用文件名兜住这一层，而不是往快照里塞字段改变两个入口的 JSON 形状。
    -->
    <ExportModal
      v-model:open="exportOpen"
      :title="`导出${detail ? reviewTitleOf(detail.report_type) : '复盘'}`"
      unit="数据"
      :count="exportRows.length"
      :base-name="exportBaseName"
      :json-data="detail?.data"
      :columns="REVIEW_EXPORT_COLUMNS"
      :rows="exportRows"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 复盘库页面。
 *
 * ★ 数据全部来自后端（`api/review.ts` 的三个函数）—— 本页**不落任何本地缓存**：
 *   复盘是低频数据（一个月几条），本地缓存带来的"刷新后看到旧值"问题
 *   远比省下的那一次请求贵。
 *
 * ★ 详情**按需拉取**（`getSavedReport`）：列表出参刻意不含 `data` 快照
 *   （一份可挂 35 行 SKU 明细），列表拉全量会把页面拖慢。对比同理 ——
 *   只有真的勾了两份才去拉那两份的快照。
 */
import { WINDOW_W } from '@/config/layout'
import { computed, onMounted, ref, watch } from 'vue'
import { DiffOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import {
  getSavedReport,
  listSavedReports,
  reviewTitleOf,
  REVIEW_REPORT_OPTIONS,
  REVIEW_REPORT_TITLES,
  type ReviewSortKey,
  type SavedReviewDetail,
  type SavedReviewItem,
} from '@/api/review'
import ExportModal from '@/components/common/ExportModal.vue'
import { money, num } from '@/components/ChatPanel/results/conversation/format'
import {
  REVIEW_EXPORT_COLUMNS,
  healthStatusText,
  metricTextOf,
  reviewExportBaseName,
  reviewReportToRows,
  textListOf,
} from '@/utils/reviewExport'

/** 类型下拉：选项来自唯一真源 `REVIEW_REPORT_TITLES`（不在这里再抄一份名单）。 */
const typeOptions = REVIEW_REPORT_OPTIONS.map((o) => ({ label: o.label, value: o.value }))

/** 排序维度 = 后端 `REVIEW_SPEC.sort_fields` 的白名单（写错会 400）。 */
const SORT_OPTIONS = [
  { label: '按周期末日（最近在前）', value: 'period_end' },
  { label: '按归档时间', value: 'created_at' },
  { label: '按周期长度', value: 'period_days' },
]

const items = ref<SavedReviewItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const typeFilter = ref<string | undefined>(undefined)
const sortBy = ref<ReviewSortKey>('period_end')

/**
 * 空状态的两种语义必须分开说（本仓「两种空」那条判据）：
 * 库里没有 vs 筛选后为空 —— 后者的逃生口是「清空筛选」，前者是「去归档」。
 */
const emptyTitle = computed(() =>
  typeFilter.value ? '这个类型下还没有归档的复盘' : '复盘库还是空的'
)
const emptySub = computed(() =>
  typeFilter.value
    ? '换一个类型，或清空筛选看全部。'
    : '在左侧选「运营复盘师」，生成一份复盘后点卡片上的「归档到复盘库」，这里就会出现它。'
)

function clearFilter() {
  typeFilter.value = undefined
  reload()
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const res: any = await listSavedReports({
      order_by: sortBy.value,
      ...(typeFilter.value ? { report_type: typeFilter.value } : {}),
      limit: 200,
    })
    // ★★ 防「伪成功」：后端这三个端点**没有**统一信封（无 `success` 字段），
    //    所以不能只判"没抛错"。`items` 是数组才算真成功 ——
    //    拿不到数组一律按失败处理，**绝不**退回空列表
    //    （那会把"读不到"显示成"你还没归档过"，方向错得很远）。
    if (!res || !Array.isArray(res.items)) {
      error.value = '复盘库返回了无法识别的数据，请重试。'
      items.value = []
      total.value = 0
      return
    }
    items.value = res.items
    total.value = Number(res.total ?? res.items.length)
  } catch (e: any) {
    // 400「请先选店铺」是可行动的业务结论，原样带出来
    error.value = e?.response?.data?.detail || '复盘库读取失败，请稍后重试。'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ==================== 详情 ====================

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<SavedReviewDetail | null>(null)

async function openDetail(id: string) {
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const res: any = await getSavedReport(id)
    if (!res || !res.id) {
      detailError.value = '复盘详情返回了无法识别的数据。'
      return
    }
    detail.value = res
  } catch (e: any) {
    // 后端把「不存在」与「不属于本店」压成同一句 404 ⇒ 这里也只说这一句。
    detailError.value = e?.response?.data?.detail || '复盘详情读取失败。'
  } finally {
    detailLoading.value = false
  }
}

const detailMetrics = computed<any[]>(() =>
  Array.isArray(detail.value?.data?.metrics) ? (detail.value!.data!.metrics as any[]) : []
)
const detailInsights = computed<string[]>(() => textListOf(detail.value?.data?.insights))
const detailActions = computed<string[]>(() => textListOf(detail.value?.data?.actions))

// ==================== 导出（第 266 轮）====================
//
// ★ 摊平口径与「对话结果卡」共用同一份实现（`utils/reviewExport.ts`）：
//   指标格式化、观察/建议的文本解析、库存状态中文名都收归到那里，
//   本页只把结果交给 `ExportModal`。
// ★ 后端详情接口**恒**返回 `data`（没有快照时是 `{}`）⇒ 能不能导出按
//   **行数**判，`{}` 自然得到 0 行，不会出现「有按钮、导出是空表」。
// ★ 行与 JSON 同源（都是 `detail.data`）⇒ 不会出现表格一个数、JSON 另一个数。

const exportOpen = ref(false)
const exportRows = computed<(string | number)[][]>(() => reviewReportToRows(detail.value?.data))
const exportBaseName = computed(() =>
  reviewExportBaseName(reviewTitleOf(detail.value?.report_type), detail.value?.period_end)
)

/**
 * 详情表：与 `ReviewReportCard` 同一取舍 —— 只认 `details` 里**实际存在的那个键**，
 * 不按 `report_type` 分支（那等于把同一判定写两份）。详情页不截断行数
 * （它在抽屉里，不是对话流）。
 */
const detailTable = computed(() => {
  const d: any = detail.value?.data?.details || {}
  if (Array.isArray(d.campaigns) && d.campaigns.length) {
    return {
      caption: `广告计划明细（${d.campaigns.length} 个，按花费降序）`,
      columns: [
        { key: 'campaign', label: '广告计划', num: false, render: (r: any) => r.campaign ?? '—' },
        { key: 'spend', label: '花费', num: true, render: (r: any) => money(r.spend) },
        { key: 'sales', label: '销售额', num: true, render: (r: any) => money(r.sales) },
        { key: 'acos', label: 'ACoS', num: true, render: (r: any) => pctCell(r.acos) },
        { key: 'roas', label: 'ROAS', num: true, render: (r: any) => numCell(r.roas) },
        { key: 'grade', label: '评级', num: true, render: (r: any) => r.grade ?? '—' },
      ],
      rows: d.campaigns,
    }
  }
  if (Array.isArray(d.products) && d.products.length) {
    return {
      caption: `SKU 表现（${d.products.length} 个，按营收降序）`,
      columns: [
        { key: 'asin', label: 'ASIN', num: false, render: (r: any) => r.asin ?? '—' },
        { key: 'units', label: '销量', num: true, render: (r: any) => numCell(r.units) },
        { key: 'revenue', label: '营收', num: true, render: (r: any) => money(r.revenue) },
        { key: 'profit', label: '利润', num: true, render: (r: any) => money(r.profit) },
        { key: 'days_supply', label: '库存天数', num: true, render: (r: any) => numCell(r.days_supply) },
      ],
      rows: d.products,
    }
  }
  if (Array.isArray(d.sku_rank) && d.sku_rank.length) {
    return {
      caption: `SKU 贡献（${d.sku_rank.length} 个，按营收降序）`,
      columns: [
        { key: 'asin', label: 'ASIN', num: false, render: (r: any) => r.asin ?? '—' },
        { key: 'units', label: '销量', num: true, render: (r: any) => numCell(r.units) },
        { key: 'revenue', label: '营收', num: true, render: (r: any) => money(r.revenue) },
        { key: 'profit', label: '利润', num: true, render: (r: any) => money(r.profit) },
      ],
      rows: d.sku_rank,
    }
  }
  if (Array.isArray(d.items) && d.items.length) {
    return {
      caption: `库存明细（${d.items.length} 个，按库存天数升序）`,
      columns: [
        { key: 'asin', label: 'ASIN', num: false, render: (r: any) => r.asin ?? '—' },
        { key: 'sku', label: 'SKU', num: false, render: (r: any) => r.sku ?? '—' },
        { key: 'fulfillable', label: '可售', num: true, render: (r: any) => numCell(r.fulfillable) },
        { key: 'inbound', label: '在途', num: true, render: (r: any) => numCell(r.inbound) },
        { key: 'days_supply', label: '库存天数', num: true, render: (r: any) => numCell(r.days_supply) },
        { key: 'health_status', label: '状态', num: true, render: (r: any) => healthStatusText(r.health_status) },
      ],
      rows: d.items,
    }
  }
  return null
})

function numCell(v: any): string {
  const n = Number(v)
  return Number.isFinite(n) ? num(n) : '—'
}
function pctCell(v: any): string {
  const n = Number(v)
  return Number.isFinite(n) ? `${n}%` : '—'
}

// ==================== 周期对比 ====================

const compareIds = ref<string[]>([])
const cmpLoading = ref(false)
const cmpError = ref('')
const cmpReports = ref<SavedReviewDetail[]>([])

function toggleCompare(id: string) {
  if (compareIds.value.includes(id)) {
    compareIds.value = compareIds.value.filter((x) => x !== id)
  } else if (compareIds.value.length < 2) {
    compareIds.value = [...compareIds.value, id]
  }
}

/**
 * 勾满两份就拉那两份的快照。
 *
 * ★ 谁「本期」谁「上期」**不看勾选顺序** —— 按 `period_end`（业务周期末日）
 *   倒序决定：较新的是本期。勾选顺序是操作噪声，用它会把"上期 vs 本期"说反。
 */
watch(compareIds, async (ids) => {
  cmpReports.value = []
  cmpError.value = ''
  if (ids.length !== 2) return
  cmpLoading.value = true
  try {
    const [a, b]: any[] = await Promise.all(ids.map((id) => getSavedReport(id)))
    if (!a?.id || !b?.id) {
      cmpError.value = '对比所需的复盘详情读取不完整。'
      return
    }
    cmpReports.value = [a, b]
  } catch (e: any) {
    cmpError.value = e?.response?.data?.detail || '对比失败，请稍后重试。'
  } finally {
    cmpLoading.value = false
  }
})

const cmpNew = computed<SavedReviewDetail | null>(() => {
  if (cmpReports.value.length !== 2) return null
  const [a, b] = cmpReports.value
  return String(a.period_end) >= String(b.period_end) ? a : b
})
const cmpOld = computed<SavedReviewDetail | null>(() => {
  if (cmpReports.value.length !== 2) return null
  const [a, b] = cmpReports.value
  return String(a.period_end) >= String(b.period_end) ? b : a
})

const cmpTypeMismatch = computed(
  () => !!cmpNew.value && !!cmpOld.value && cmpNew.value.report_type !== cmpOld.value.report_type
)

/**
 * 对比行：按**指标名**对齐（两份的类型可能不同 ⇒ 取并集，缺的一侧显示「—」）。
 * ★ 不用「按下标对齐」：两份报告的指标**条数不一定相同**，
 *   按下标对齐会把「营收」和「ACoS」摆在同一行比 —— 比没有对比更糟（看着像结论）。
 */
const cmpRows = computed(() => {
  const n = cmpNew.value?.data?.metrics as any[] | undefined
  const o = cmpOld.value?.data?.metrics as any[] | undefined
  if (!Array.isArray(n) || !Array.isArray(o)) return []
  const labels: string[] = []
  for (const m of [...n, ...o]) {
    const l = String(m?.label ?? '')
    if (l && !labels.includes(l)) labels.push(l)
  }
  return labels.map((label) => {
    const nm = n.find((m: any) => String(m?.label) === label)
    const om = o.find((m: any) => String(m?.label) === label)
    const nv = Number(nm?.value)
    const ov = Number(om?.value)
    const unit = nm?.unit ?? om?.unit
    const fmt = (v: number, present: boolean) =>
      !present || !Number.isFinite(v) ? '—' : unit === 'USD' ? money(v) : unit === '%' ? `${v}%` : num(v)

    let deltaText = '—'
    let deltaClass = ''
    if (Number.isFinite(nv) && Number.isFinite(ov)) {
      const diff = nv - ov
      // ★ 上期为 0 时**不给百分比**（除零会得到 Infinity，显示成「∞%」是错误信息）。
      const pctText = ov !== 0 ? `（${diff >= 0 ? '+' : ''}${((diff / Math.abs(ov)) * 100).toFixed(1)}%）` : ''
      deltaText = `${diff >= 0 ? '+' : ''}${unit === 'USD' ? money(diff) : num(diff)}${pctText}`
      // ★ 中国股市/电商惯例：涨用红、跌用绿 —— 本仓 `theme/bands.ts` 同族语义。
      deltaClass = diff > 0 ? 'is-up' : diff < 0 ? 'is-down' : ''
    }
    return {
      label,
      newText: fmt(nv, nm !== undefined),
      oldText: fmt(ov, om !== undefined),
      deltaText,
      deltaClass,
    }
  })
})

// ==================== 杂项 ====================

/** 归档时间只显示到分钟：表格里放完整 ISO 会撑破列宽。 */
function shortTime(v: unknown): string {
  const s = String(v || '')
  if (!s) return '—'
  // `2026-09-24T11:39:46.123456` → `2026-09-24 11:39`
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/)
  return m ? `${m[1]} ${m[2]}` : s
}

onMounted(reload)

// 类型列表变了（后端加了新类型）时，`REVIEW_REPORT_TITLES` 也要跟上 ——
// 这里只做一次开发期提醒，界面不依赖它（未知类型会回兜底名，不会渲染崩）。
if (import.meta.env.DEV) {
  const local = Object.keys(REVIEW_REPORT_TITLES)
  if (local.length !== 6) {
    console.warn(
      `[review-library] REVIEW_REPORT_TITLES 有 ${local.length} 项，` +
        '与后端六种报告类型不一致 —— 新增类型时前端可能没跟上。'
    )
  }
}
</script>

<style scoped>
.review-library {
  padding: var(--space-16) var(--space-20);
  height: 100%;
  overflow-y: auto;
}
.rl-head {
  margin-bottom: var(--space-12);
}
.rl-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}
.rl-title {
  margin: 0;
  font-size: var(--font-size-18);
  font-weight: 600;
  color: var(--text-primary);
}
.rl-sub {
  margin: var(--space-6) 0 0;
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-tertiary);
}
.rl-bar {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-12);
  flex-wrap: wrap;
}
.rl-hint {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.rl-alert {
  margin-bottom: var(--space-12);
}
.rl-empty {
  margin-top: var(--space-40);
}
.rl-empty-title {
  font-size: var(--font-size-13);
  color: var(--text-secondary);
}
.rl-empty-sub {
  margin-top: var(--space-4);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.rl-table-wrap {
  overflow-x: auto;
}
.rl-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-12);
}
.rl-table th,
.rl-table td {
  padding: var(--space-8) var(--space-10);
  text-align: left;
  border-bottom: 1px solid var(--border-base);
  color: var(--text-secondary);
  vertical-align: middle;
}
.rl-table th {
  color: var(--text-tertiary);
  font-weight: 500;
  white-space: nowrap;
}
.rl-table .num {
  text-align: right;
  white-space: nowrap;
}
.rl-table .c-pick {
  width: 32px;
}
.rl-table .c-act {
  width: 64px;
  text-align: right;
}
.rl-table tr.picked {
  background: var(--bg-hover-light);
}
.c-summary {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 对比 ===== */
.rl-compare {
  margin-top: var(--space-16);
  padding: var(--space-12);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
}
.rl-cmp-head {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-8);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.rl-cmp-title {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-8);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.rl-cmp-vs {
  color: var(--text-tertiary);
}
.rl-cmp-warn {
  margin-bottom: var(--space-8);
  font-size: var(--font-size-11);
  color: var(--warning-strong);
}
.rl-cmp-empty {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.is-up {
  color: var(--danger-strong);
}
.is-down {
  color: var(--success);
}

/* ===== 详情 ===== */
.rl-d-head {
  display: flex;
  gap: var(--space-6);
  flex-wrap: wrap;
  margin-bottom: var(--space-8);
}
.rl-d-summary {
  margin: 0 0 var(--space-12);
  line-height: 1.7;
  color: var(--text-secondary);
}
.rl-d-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: var(--space-8);
  margin-bottom: var(--space-12);
}
.rl-d-cell {
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-6) var(--space-8);
}
.rl-d-k {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.rl-d-v {
  margin-top: var(--space-2);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.rl-d-block {
  margin-top: var(--space-12);
}
.rl-d-caption {
  margin-bottom: var(--space-4);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.rl-d-list {
  margin: 0;
  padding-left: var(--space-16);
  line-height: 1.8;
  color: var(--text-secondary);
}
.rl-d-foot {
  margin-top: var(--space-16);
  padding-top: var(--space-8);
  border-top: 1px dashed var(--border-base);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
</style>
