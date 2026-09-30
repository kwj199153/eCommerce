<script setup lang="ts">
/**
 * 审计日志面板（P0-5c）—— 后端读口 `GET /api/v1/audit/{logs,actions}` 的界面。
 *
 * ============================================================================
 * ★ 为什么是**抽屉**而不是路由页
 * ============================================================================
 * 姊妹面板 `Settings.vue` / `MemoryEvolution.vue` 是「抽屉 + 路由」双形态。本面板
 * **刻意只做抽屉**，两个理由：
 *
 *   ① 读口要求**平台超管**。对其它任何身份，`/audit` 这条路由永远是一屏 403 空态
 *      —— 那正是本仓反复防过的「死路由」（第 323 轮刚把两条死路由做活）。
 *      没有 UI 入口的路由等于没有页面。
 *   ② 它是超管工具、不是用户功能，不需要书签 / 分享地址。
 *   ⇒ 入口在账户菜单（`AccountMenu.vue`，**仅超管可见**），
 *     经 `open-audit-drawer` 事件打开（与 `open-settings-drawer` 同一套约定）。
 *
 * ============================================================================
 * ★ 三种「没有数据」必须分开呈现（这是本面板最要紧的一条）
 * ============================================================================
 *     无权（403）   ⇒ 「无权访问」—— 不是"没有记录"，去重试也没用
 *     读失败        ⇒ `AsyncEmpty` 失败态 + 重试出口（不许说"暂无"）
 *     确实为空      ⇒ 「暂无审计记录」
 * 三者压成一句「暂无数据」的话，用户会去**翻页 / 等待**，而真相是他根本没有权限。
 * 三态互斥由模板的 `v-if="forbidden"` / `v-else` 两支保证（403 优先于空态）。
 */

import { computed, onMounted, reactive, ref, watch } from 'vue'
import dayjs from 'dayjs'
import { listAuditActions, listAuditLogs, statusColor, statusLabel } from '@/api/audit'
import type { AuditActionMeta, AuditLogItem } from '@/api/audit'
import AsyncEmpty from '@/components/common/AsyncEmpty.vue'
import { WINDOW_W } from '@/config/layout'

const props = defineProps<{ open?: boolean }>()
const emit = defineEmits<{ (e: 'update:open', val: boolean): void }>()

const PAGE_SIZE = 20

// ====== 状态 ======

const rows = ref<AuditLogItem[]>([])
const total = ref(0)
const loading = ref(false)
/** 读失败原因（只在**失败**时非空）—— 交给统一空态组件判定呈现哪一支 */
const loadError = ref<string | null>(null)
/** 后端 403：已登录但不是平台超管。与「读失败」是**两回事**，所以单独一个标志 */
const forbidden = ref(false)

/** 动作目录（后端 `GET /actions` 下发，前端不存第二份） */
const actions = ref<AuditActionMeta[]>([])

const filters = reactive({
  action: undefined as string | undefined,
  status: undefined as string | undefined,
  target_type: undefined as string | undefined,
  actor_id: undefined as string | undefined,
  target_id: undefined as string | undefined,
})

/** 时间区间（RangePicker 给的是 dayjs；清空时是 null） */
const range = ref<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
const offset = ref(0)

// ====== 派生 ======

/**
 * 动作下拉。★ 选项**只**来自后端目录 —— 前端不列第二份清单，
 * 否则新增动作后会「记进了库、筛选框里选不到」。
 */
const actionOptions = computed(() =>
  actions.value.map((a) => ({ value: a.action, label: a.label }))
)

/**
 * 结果选项。★ 对应后端 `core/audit/actions.py::STATUSES`；审计只记这两种结果。
 * 后端若加了第三种，必须回来补 —— 漏补的症状同上。
 */
const statusOptions = [
  { value: 'success', label: '成功' },
  { value: 'failure', label: '失败' },
]

/** 目标类型：从动作目录**派生**（不手写第二份清单） */
const targetOptions = computed(() => {
  const seen = new Set<string>()
  for (const a of actions.value) if (a.target_type) seen.add(a.target_type)
  return [...seen].map((t) => ({ value: t, label: t }))
})

/** 动作码 → 中文标签（目录还没到货时**原样回显动作码**，不猜） */
function actionLabel(action: string): string {
  return actions.value.find((a) => a.action === action)?.label || action
}

const columns = [
  { title: '时间', key: 'created_at', width: 142 },
  { title: '动作', key: 'action', width: 250 },
  { title: '结果', key: 'status', width: 78 },
  { title: '操作人', key: 'actor', width: 188 },
  { title: '目标', key: 'target', width: 160 },
]

const pagination = computed(() => ({
  current: Math.floor(offset.value / PAGE_SIZE) + 1,
  pageSize: PAGE_SIZE,
  total: total.value,
  showSizeChanger: false,
  showTotal: (t: number) => `共 ${t} 条`,
}))

function formatTime(v: string | null): string {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—'
}

/** 目标：`type:id`；两者都缺时给破折号（不拼出 `null:null` 这种假象） */
function targetText(r: AuditLogItem): string {
  if (!r.target_type && !r.target_id) return '—'
  return [r.target_type, r.target_id].filter(Boolean).join(':')
}

/** detail 的只读呈现：审计表里可能是任意 JSON，序列化失败不许把面板搞崩 */
function detailText(r: AuditLogItem): string {
  if (r.detail == null) return '—'
  try {
    return JSON.stringify(r.detail, null, 2)
  } catch {
    return '[无法序列化]'
  }
}

// ====== 取数 ======

async function loadActions() {
  try {
    const res = await listAuditActions()
    actions.value = res?.items || []
  } catch {
    // 目录拉不到只影响筛选下拉与中文标签（退化成显示动作码），
    // **不影响**日志本身的呈现 ⇒ 不置 loadError、不弹窗。
  }
}

async function loadLogs() {
  loading.value = true
  loadError.value = null
  forbidden.value = false
  try {
    const res = await listAuditLogs({
      action: filters.action || undefined,
      status: filters.status || undefined,
      target_type: filters.target_type || undefined,
      actor_id: filters.actor_id?.trim() || undefined,
      target_id: filters.target_id?.trim() || undefined,
      since: range.value?.[0] ? range.value[0].toISOString() : undefined,
      until: range.value?.[1] ? range.value[1].toISOString() : undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
    })
    rows.value = res?.items || []
    total.value = res?.total || 0
  } catch (err: unknown) {
    rows.value = []
    total.value = 0
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      // ★ 403 是**业务结论**（你不是超管），不是故障 ⇒ 不报「加载失败」，
      //   否则用户会反复重试一件永远不会成功的事。
      forbidden.value = true
    } else if (status === 401) {
      // 401 已被拦截器接管（清状态 + 跳登录 + 带回跳）⇒ 这里不再重复解释。
      loadError.value = null
    } else {
      loadError.value = (err as Error)?.message || 'unknown'
      console.warn('[audit] 审计日志加载失败:', err)
    }
  } finally {
    loading.value = false
  }
}

/** 筛选 / 刷新 ⇒ **必须回到第 1 页**：否则会停在一个超出新结果集的 offset 上看到空表 */
function reload() {
  offset.value = 0
  void loadLogs()
}

function resetFilters() {
  filters.action = undefined
  filters.status = undefined
  filters.target_type = undefined
  filters.actor_id = undefined
  filters.target_id = undefined
  range.value = null
  reload()
}

function hasFilters(): boolean {
  return !!(
    filters.action ||
    filters.status ||
    filters.target_type ||
    filters.actor_id ||
    filters.target_id ||
    range.value
  )
}

function handleTableChange(pag: { current?: number }) {
  offset.value = ((pag?.current || 1) - 1) * PAGE_SIZE
  void loadLogs()
}

function handleOpenChange(val: boolean) {
  emit('update:open', val)
}

// ★ 取数的**唯一触发点**是「open 由假变真」：
//   抽屉自身只会在**关闭**时 emit `update:open(false)`，打开是父组件改 prop ⇒
//   若在 handleOpenChange 里也 reload，就会与这里的 watch 构成两条触发路径。
watch(
  () => props.open,
  (val) => {
    if (!val) return
    if (!actions.value.length) void loadActions()
    reload()
  }
)

onMounted(() => {
  if (props.open) {
    void loadActions()
    reload()
  }
})
</script>

<template>
  <a-drawer
    :open="!!open"
    title="审计日志"
    placement="right"
    :width="WINDOW_W.xxl"
    :body-style="{ padding: '0' }"
    :destroyOnClose="false"
    @update:open="handleOpenChange"
  >
    <div class="audit-panel">
      <div class="audit-lead">
        <span class="audit-lead-text">
          记录关键写操作（登录 · 店铺 · 成员）。审计只增不改，没有编辑与删除入口。
        </span>
        <a-button size="small" :loading="loading" @click="reload">刷新</a-button>
      </div>

      <div class="audit-filters">
        <a-select
          v-model:value="filters.action"
          class="f-item f-action"
          :options="actionOptions"
          placeholder="全部动作"
          allow-clear
          @change="reload"
        />
        <a-select
          v-model:value="filters.status"
          class="f-item f-status"
          :options="statusOptions"
          placeholder="全部结果"
          allow-clear
          @change="reload"
        />
        <a-select
          v-model:value="filters.target_type"
          class="f-item f-target"
          :options="targetOptions"
          placeholder="全部目标"
          allow-clear
          @change="reload"
        />
        <a-range-picker
          v-model:value="range"
          class="f-item f-range"
          show-time
          :placeholder="['开始时间', '结束时间']"
          @change="reload"
        />
        <a-input
          v-model:value="filters.actor_id"
          class="f-item f-id"
          placeholder="执行者 ID（精确）"
          allow-clear
          @press-enter="reload"
        />
        <a-input
          v-model:value="filters.target_id"
          class="f-item f-id"
          placeholder="目标 ID（精确）"
          allow-clear
          @press-enter="reload"
        />
        <a-button v-if="hasFilters()" size="small" type="link" @click="resetFilters">
          重置筛选
        </a-button>
      </div>

      <!-- 403：单独的第三态。既不能说「加载失败」，更不能说「暂无记录」。 -->
      <div v-if="forbidden" class="audit-blocked">
        <a-empty description="无权访问审计日志（此功能仅平台管理员可用）" />
      </div>

      <!-- 空态 / 失败态：统一组件（`:error` 非空 ⇒ 失败态 + 重试出口） -->
      <a-table
        v-else
        class="audit-table"
        size="small"
        row-key="id"
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        :pagination="pagination"
        :scroll="{ x: 818 }"
        @change="handleTableChange"
      >
        <template #emptyText>
          <AsyncEmpty
            :error="loadError"
            label="审计日志"
            empty-description="暂无审计记录"
            @retry="reload"
          />
        </template>

        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at'">
            <span class="c-time">{{ formatTime(record.created_at) }}</span>
          </template>

          <template v-else-if="column.key === 'action'">
            <div class="c-action">
              <span class="c-action-label">{{ actionLabel(record.action) }}</span>
              <span class="c-action-code">{{ record.action }}</span>
            </div>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>

          <template v-else-if="column.key === 'actor'">
            <div class="c-actor">
              <span class="c-actor-mail">{{ record.actor_email || '—' }}</span>
              <a-tooltip v-if="record.actor_id" :title="record.actor_id">
                <span class="c-actor-id">{{ record.actor_id.slice(0, 8) }}</span>
              </a-tooltip>
            </div>
          </template>

          <template v-else-if="column.key === 'target'">
            <a-tooltip :title="targetText(record)">
              <span class="c-target">{{ targetText(record) }}</span>
            </a-tooltip>
          </template>
        </template>

        <template #expandedRowRender="{ record }">
          <div class="audit-detail">
            <div class="d-row">
              <span class="d-k">摘要</span>
              <span class="d-v">{{ record.summary || '—' }}</span>
            </div>
            <div class="d-row">
              <span class="d-k">来源 IP</span>
              <span class="d-v">{{ record.ip || '—' }}</span>
            </div>
            <div class="d-row">
              <span class="d-k">User-Agent</span>
              <span class="d-v">{{ record.user_agent || '—' }}</span>
            </div>
            <div v-if="record.detail != null" class="d-row">
              <span class="d-k">明细</span>
              <pre class="d-pre">{{ detailText(record) }}</pre>
            </div>
          </div>
        </template>
      </a-table>
    </div>
  </a-drawer>
</template>

<style scoped>
.audit-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-base);
}

.audit-lead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  padding: var(--space-12) var(--space-16);
  border-bottom: 1px solid var(--border-base);
}

.audit-lead-text {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  line-height: 1.6;
}

.audit-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-12) var(--space-16);
  border-bottom: 1px solid var(--border-base);
}

.f-item {
  min-width: 132px;
}

.f-action {
  width: 168px;
}

.f-status {
  width: 116px;
}

.f-target {
  width: 130px;
}

.f-range {
  width: 300px;
}

.f-id {
  width: 176px;
}

.audit-blocked {
  padding: var(--space-40) var(--space-16);
}

.audit-table {
  flex: 1;
  padding: 0 var(--space-16);
  overflow: auto;
}

.c-time {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

.c-action {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.c-action-label {
  color: var(--text-primary);
}

.c-action-code {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

.c-actor {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.c-actor-mail {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-actor-id {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

.c-target {
  color: var(--text-secondary);
}

.audit-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.d-row {
  display: flex;
  gap: var(--space-8);
  font-size: var(--font-size-12);
}

.d-k {
  flex: 0 0 84px;
  color: var(--text-tertiary);
}

.d-v {
  color: var(--text-secondary);
  word-break: break-all;
}

.d-pre {
  margin: 0;
  padding: var(--space-8);
  border-radius: var(--radius-4);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: var(--font-size-12);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
