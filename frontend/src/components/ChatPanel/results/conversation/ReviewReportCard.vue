<template>
  <!--
    运营复盘师 · 会话结论卡（第 246 轮 P2）

    ★ 它解决的是**结构化载荷没有人接**：后端 6 项复盘能力都返回
      `metrics / insights / actions / details`，而改前 `_wrap` 的
      `display_type` 恒为 `"text"` ⇒ 前端 `resolveConversationResult('text')`
      返回 null ⇒ 报告只能按纯文本渲染，`data` 里的列表**白白下发**。
      后端现在下发 `review_report`（`REVIEW_REPORT_DISPLAY_TYPE`），本卡是它的消费点。

    ★ 字段口径**只认后端那一个真源**：`report_type` / `period_days` /
      `summary` / `metrics[]` / `insights[]` / `actions[]` / `details`。
      本卡不推算、不补齐任何后端没给的值 —— 缺什么就显示「—」或整块不渲染
      （本仓判据：空状态优于虚构默认）。
  -->
  <ConversationCard icon="🧾" :title="title" :badge="periodText" badge-color="geekblue">
    <p v-if="summary" class="rr-summary">{{ summary }}</p>

    <div v-if="metrics.length" class="rr-grid">
      <div v-for="m in metrics" :key="m.label" class="rr-cell">
        <div class="rr-k">{{ m.label }}</div>
        <div class="rr-v" :class="statusClass(m.status)">{{ metricTextOf(m) }}</div>
      </div>
    </div>
    <div v-else class="rr-empty">本次没有返回指标。</div>

    <div v-if="table" class="rr-table-wrap">
      <div class="rr-caption">{{ table.caption }}</div>
      <table class="rr-table">
        <thead>
          <tr>
            <th v-for="c in table.columns" :key="c.key" :class="{ num: c.num }">{{ c.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in table.rows" :key="i">
            <td v-for="c in table.columns" :key="c.key" :class="{ num: c.num }">
              {{ c.render(row) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="insights.length || actions.length">
      <div v-if="insights.length" class="rr-list-block">
        <div class="rr-caption">观察</div>
        <ul class="rr-list">
          <li v-for="(t, i) in insights" :key="i">{{ t }}</li>
        </ul>
      </div>
      <div v-if="actions.length" class="rr-list-block">
        <div class="rr-caption">建议动作</div>
        <ul class="rr-list">
          <li v-for="(t, i) in actions" :key="i">{{ t }}</li>
        </ul>
      </div>
    </template>
    <!--
      ★ 第 251 轮：底部「归档到复盘库」。
        「人工确认才入库」是本仓既有范式（先例：AIGC 出图 → 归档到营销素材库）。
        6 项复盘能力**算完不落库**；只有老板点这一下，这一份才进复盘库 ——
        下一期复盘才读得到它（`list_reviews` 工具 / 复盘库页面）。

      ★ 失败必须**回写界面状态**：只弹一个 toast 的话，按钮会停在可点状态、
        老板不知道到底进没进库（本仓：失败路径必须回写界面状态）。
    -->
    <template #footer>
      <span v-if="archiveState === 'done'" class="rr-ok">
        <CheckCircleOutlined />
        {{ archiveNote }}
      </span>
      <span v-else-if="archiveState === 'failed'" class="rr-err">
        {{ archiveError }}
      </span>
      <a-button
        v-if="archiveState === 'done'"
        size="small"
        @click="goLibrary"
      >查看复盘库</a-button>
      <a-button
        v-if="canArchive"
        size="small"
        type="primary"
        ghost
        :loading="archiving"
        @click="onArchive"
      >
        <InboxOutlined />
        归档到复盘库
      </a-button>
      <!--
        ★ 第 266 轮：导出。与本卡的文字内容**同源** —— 表格行由
          `reviewReportToRows(data)` 摊平、JSON 直接是后端那份快照。
          为什么要有：界面只渲染了报告的一部分（`details` 里的 sales/ad/
          commission 汇总、以及恒空的观察/建议两块），导出得让老板拿到全量。
      -->
      <a-button v-if="exportRows.length" size="small" @click="exportOpen = true">
        <DownloadOutlined />
        导出
      </a-button>
    </template>
  </ConversationCard>

  <!--
    ★ 与「复盘库详情抽屉」的导出**共用同一份摊平函数**（`utils/reviewExport.ts`）：
      两处各写一份的后果是同一份复盘从两个入口导出的表格不一样，且谁都不报错。
    ★ `json-data` 传后端**原样**的这份快照 —— 不在前端重算任何数值。
  -->
  <ExportModal
    v-model:open="exportOpen"
    :title="`导出${title}`"
    unit="数据"
    :count="exportRows.length"
    :base-name="exportBaseName"
    :json-data="data"
    :columns="REVIEW_EXPORT_COLUMNS"
    :rows="exportRows"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { CheckCircleOutlined, DownloadOutlined, InboxOutlined } from '@ant-design/icons-vue'
import ConversationCard from './ConversationCard.vue'
import ExportModal from '@/components/common/ExportModal.vue'
import { money, num } from './format'
import { saveReviewReport, reviewTitleOf } from '@/api/review'
import {
  REVIEW_EXPORT_COLUMNS,
  healthStatusText,
  metricTextOf,
  reviewExportBaseName,
  reviewReportToRows,
  textListOf,
} from '@/utils/reviewExport'

const props = defineProps<{ data: any }>()

/** 中文名**唯一真源**在 `@/api/review`（两处消费点共用同一份，见其说明）。 */
const reportType = computed(() => String(props.data?.report_type || ''))
const title = computed(() => reviewTitleOf(reportType.value))
const summary = computed(() => String(props.data?.summary || ''))
const metrics = computed<any[]>(() => (Array.isArray(props.data?.metrics) ? props.data.metrics : []))
const insights = computed<string[]>(() => textListOf(props.data?.insights))
const actions = computed<string[]>(() => textListOf(props.data?.actions))

// ==================== 导出（第 266 轮）====================
//
// ★ 表格行与「复盘库详情抽屉」共用同一个摊平实现（`utils/reviewExport.ts`），
//   避免「同一判定两份实现」——两处各写一份时谁都不会报错，
//   但同一份复盘从两个入口导出的表格内容会不一样。
// ★ 行与 JSON 都从同一个 `props.data` 派生 ⇒ 不存在「表格一个数、JSON 另一个数」。
// ★ 没有可导出的条目时按钮**不渲染**（空状态优于给一个导出空表的假入口）。

const exportOpen = ref(false)
const exportRows = computed<(string | number)[][]>(() => reviewReportToRows(props.data))
const exportBaseName = computed(() => reviewExportBaseName(title.value))

// ==================== 归档到复盘库（第 251 轮）====================
//
// 三态：idle（可点）/ done（已归档）/ failed（失败，可重试且**显示原因**）。
// ★ 为什么不只用 `loading` 一个布尔：失败后若不留下任何状态，界面与「从没点过」
//   完全一样 —— 老板只能靠回忆判断有没有进库。

type ArchiveState = 'idle' | 'done' | 'failed'
const archiveState = ref<ArchiveState>('idle')
const archiving = ref(false)
const archiveNote = ref('')
const archiveError = ref('')

const canArchive = computed(() => archiveState.value !== 'done' && !archiving.value)

/**
 * 归档。成功/失败都要**落到界面上**：
 *  · 成功 ⇒ 换成「已归档 + 查看复盘库」（`created` 决定文案：新增 / 覆盖今天那条）；
 *  · 失败 ⇒ 显示后端给的原因（缺店铺 → 400「请先选店铺」；
 *    非法取值 → 422；库不可用 → 500），并把按钮恢复成可点（可重试）。
 */
async function onArchive() {
  // ★ 前置校验：没有 report_type / period_days 就没法归档。
  //   这里不"猜"一个默认值 —— 后端要求两者都在，猜出来的报告类型会进错库位。
  const rt = reportType.value
  const days = Number(props.data?.period_days)
  if (!rt || !Number.isFinite(days) || days <= 0) {
    archiveState.value = 'failed'
    archiveError.value = '这份结果缺少报告类型或周期，无法归档。'
    return
  }

  archiving.value = true
  archiveError.value = ''
  try {
    const res: any = await saveReviewReport({
      report_type: rt,
      period_days: days,
      // 原样回传后端刚给的那份快照（不让后端重算 —— 会拿到另一批数字）
      data: props.data,
    })
    // ★★ 防「伪成功」：后端这三个端点**不回**统一信封（没有 success 字段），
    //    所以不能只看"请求没抛错"。`item.id` 是**只有真的写成功才可能出现**的值
    //    （写入返回 `{created, item}`，item 由 commit 后的 refresh 得来）。
    if (!res || !res.item || !res.item.id) {
      archiveState.value = 'failed'
      archiveError.value = '归档没有落库（服务端未返回记录），请重试。'
      return
    }
    archiveState.value = 'done'
    archiveNote.value = res.created ? '已归档到复盘库' : '已更新今天的这份复盘'
    // ★ 与按钮上的「已归档」不重复：toast 只补充「新增 / 覆盖」这一层信息。
    message.success(archiveNote.value)
  } catch (e: any) {
    archiveState.value = 'failed'
    // 400 的「请先选店铺」是可行动的业务结论，必须原样带出来
    archiveError.value = e?.response?.data?.detail || '归档失败，请稍后重试。'
  } finally {
    archiving.value = false
  }
}

/** 跳到「资料库 → 复盘库」（复用 Workspace 既有的 view-navigate 事件）。 */
function goLibrary() {
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'reviews' } }))
}

/** 周期徽标：后端给的是天数（`period_days`），在此翻译成「近 N 天」 */
const periodText = computed(() => {
  const d = Number(props.data?.period_days)
  return Number.isFinite(d) && d > 0 ? `近 ${d} 天` : ''
})

const STATUS_CLASS: Record<string, string> = {
  good: 'is-good',
  warning: 'is-warn',
  critical: 'is-bad',
}

function statusClass(s?: string): string {
  return STATUS_CLASS[String(s || '')] || ''
}

/**
 * 明细表：后端 6 项能力的 `details` 是**不同形状**（campaigns / sku_rank /
 * products / items），这里按**实际存在的那个键**挑一张表渲染。
 *
 * ★ 刻意不做成「六张表都写一遍再按 report_type 分支」：`report_type` 与
 *   `details` 的键是**一一对应**的同一份信息，按 `report_type` 分支等于把同一
 *   判定写两份（本仓「同一判定两份实现」）。这里只看 `details` 里有什么。
 * ★ 行数上限 8 行：这卡片长在对话流里，完整清单在右栏看板 —— 卡只做承接，
 *   不做第二份看板。不截断会让一条消息占满整屏。
 */
const MAX_ROWS = 8

const table = computed(() => {
  const d = props.data?.details || {}
  if (Array.isArray(d.campaigns) && d.campaigns.length) {
    return {
      caption: `广告计划明细（${d.campaigns.length} 个，按花费降序）`,
      columns: [
        { key: 'campaign', label: '广告计划', num: false, render: (r: any) => r.campaign ?? '—' },
        { key: 'spend', label: '花费', num: true, render: (r: any) => money(r.spend) },
        { key: 'acos', label: 'ACoS', num: true, render: (r: any) => pctCell(r.acos) },
        { key: 'roas', label: 'ROAS', num: true, render: (r: any) => numCell(r.roas) },
        { key: 'grade', label: '评级', num: true, render: (r: any) => r.grade ?? '—' },
      ],
      rows: d.campaigns.slice(0, MAX_ROWS),
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
      rows: d.products.slice(0, MAX_ROWS),
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
      rows: d.sku_rank.slice(0, MAX_ROWS),
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
      rows: d.items.slice(0, MAX_ROWS),
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
</script>

<style scoped>
.rr-summary {
  margin: 0 0 var(--space-8);
  line-height: 1.6;
}
.rr-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}
.rr-cell {
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-6) var(--space-8);
}
.rr-k {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.rr-v {
  margin-top: var(--space-2);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.is-good {
  color: var(--success);
}
.is-warn {
  color: var(--warning-strong);
}
.is-bad {
  color: var(--danger-strong);
}
.rr-caption {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-bottom: var(--space-4);
}
.rr-table-wrap {
  border-top: 1px dashed var(--border-base);
  padding-top: var(--space-8);
  margin-bottom: var(--space-8);
}
.rr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-11);
}
.rr-table th,
.rr-table td {
  padding: var(--space-4) var(--space-6);
  text-align: left;
  border-bottom: 1px solid var(--border-base);
  color: var(--text-secondary);
}
.rr-table th {
  color: var(--text-tertiary);
  font-weight: 500;
}
.rr-table .num {
  text-align: right;
}
.rr-list-block {
  margin-top: var(--space-8);
}
.rr-list {
  margin: 0;
  padding-left: var(--space-16);
  line-height: 1.7;
}
.rr-empty {
  color: var(--text-tertiary);
  line-height: 1.6;
}
.rr-ok {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  margin-right: auto;
  font-size: var(--font-size-11);
  color: var(--success);
}
.rr-err {
  margin-right: auto;
  font-size: var(--font-size-11);
  color: var(--danger-strong);
}
</style>
