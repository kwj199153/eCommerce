<template>
  <div class="mp-page">
    <!-- ================= 页头 ================= -->
    <div class="mp-head">
      <div class="mph-text">
        <h2 class="mph-title">
          🎯 竞品监控池
          <a-tag color="default" class="mph-count">{{ pool.totalCount }} 个 ASIN</a-tag>
        </h2>
        <div class="mph-sub">
          持续盯盘的竞品清单 —— 与「自有产品库」里内嵌的<b>对标竞品</b>区分：这里是长期监控的对手池，
          那里是某个主品/候选的一次性对比集。
        </div>
      </div>
      <a-space :size="8">
        <a-button @click="openGroupModal"><AppstoreOutlined /> 分组管理</a-button>
        <a-button type="primary" @click="openAddModal"><PlusOutlined /> 添加竞品</a-button>
      </a-space>
    </div>

    <!-- ================= 统计卡 ================= -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ pool.totalCount }}</div>
        <div class="stat-label">在池竞品</div>
      </div>
      <div class="stat-card">
        <div class="stat-value blue">{{ pool.selectedAsins.length }}</div>
        <div class="stat-label">已圈选</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ pool.groupCount }}</div>
        <div class="stat-label">分组</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" :class="{ red: alertTotal > 0 }">{{ alertTotal }}</div>
        <div class="stat-label">待关注</div>
      </div>
    </div>

    <!-- ================= 额度提示 ================= -->
    <a-alert
      v-if="pool.quotaReached"
      type="warning"
      show-icon
      class="quota-alert"
      :message="`监控额度已达 ${pool.monitoringCount} / ${pool.monitorQuota}`"
      description="后台定时采集按额度计费，超出的竞品仍可保留在池中手动查看。"
    />

    <!-- ================= 工具条 ================= -->
    <div class="toolbar">
      <div class="toolbar-left">
        <a-input-search
          v-model:value="searchQuery"
          placeholder="搜索 ASIN / 标题 / 品牌"
          style="width: 240px"
          allow-clear
        >
          <template #prefix><SearchOutlined /></template>
        </a-input-search>

        <a-radio-group v-model:value="ownershipModel" size="small" button-style="solid">
          <a-radio-button value="all">全部 {{ pool.ownershipCount.all }}</a-radio-button>
          <a-radio-button value="owned">有归属 {{ pool.ownershipCount.owned }}</a-radio-button>
          <a-radio-button value="free">游离 {{ pool.ownershipCount.free }}</a-radio-button>
        </a-radio-group>

        <a-select v-model:value="groupModel" style="width: 168px">
          <a-select-option value="">全部分组</a-select-option>
          <a-select-option value="__ungrouped__">未分组 ({{ ungroupedCount }})</a-select-option>
          <a-select-option v-for="g in pool.groups" :key="g.id" :value="g.id">
            {{ g.name }} ({{ countInGroup(g.id) }})
          </a-select-option>
        </a-select>
      </div>

      <div class="toolbar-right">
        <template v-if="pool.selectedAsins.length">
          <a-dropdown :trigger="['click']">
            <a-button><FolderAddOutlined /> 加入分组 ({{ pool.selectedAsins.length }})</a-button>
            <template #overlay>
              <a-menu @click="onAssignMenuClick">
                <a-menu-item v-for="g in pool.groups" :key="g.id">
                  <span class="grp-dot" :style="{ background: g.color }"></span>{{ g.name }}
                </a-menu-item>
                <a-menu-divider v-if="pool.groups.length" />
                <a-menu-item key="__manage__"><SettingOutlined /> 管理分组…</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
          <a-popconfirm
            :title="`确认把选中的 ${pool.selectedAsins.length} 个竞品移出监控池？`"
            @confirm="handleBatchRemove"
          >
            <a-button danger><DeleteOutlined /> 移出监控池</a-button>
          </a-popconfirm>
          <a-button type="text" @click="pool.clearSelected()">取消选择</a-button>
        </template>
        <a-button v-else type="link" size="small" :disabled="!filtered.length" @click="handleSelectAllFiltered">
          全选当前 {{ filtered.length }} 条
        </a-button>
      </div>
    </div>

    <!-- ================= 活跃过滤 chip ================= -->
    <div v-if="hasLocalFilters" class="active-filters">
      <span class="af-label"><FilterOutlined /> 已启用过滤</span>
      <a-tag v-if="pool.currentGroupId" closable class="af-chip" @close="pool.selectGroup(null)">
        {{ currentGroupLabel }}
      </a-tag>
      <a-tag v-if="pool.currentOwnership !== 'all'" closable class="af-chip" @close="pool.selectOwnership('all')">
        归属：{{ OWNERSHIP_LABEL[pool.currentOwnership] }}
      </a-tag>
      <a-tag v-if="searchQuery.trim()" closable class="af-chip" @close="searchQuery = ''">
        搜索：“{{ searchQuery }}”
      </a-tag>
      <a-button type="link" size="small" danger @click="clearLocalFilters">清空全部</a-button>
    </div>

    <!-- ================= 表格 ================= -->
    <a-table
      class="mp-table"
      :columns="columns"
      :data-source="filtered"
      row-key="asin"
      :row-selection="rowSelection"
      :pagination="{ pageSize: 15, size: 'small', showTotal: (t: number) => `共 ${t} 个竞品` }"
      size="middle"
      :scroll="{ x: 1180, y: 'calc(100vh - 430px)' }"
    >
      <template #bodyCell="{ column, record }">
        <!-- ASIN / 品牌 -->
        <template v-if="column.key === 'asin'">
          <div class="asin-cell">
            <span class="asin-main">{{ record.asin }}</span>
            <span class="asin-sub">
              <span v-if="record.brand">{{ record.brand }}</span>
              <em v-else class="muted">无品牌</em>
              <em class="origin-badge" :class="record.origin">{{ ORIGIN_LABEL[record.origin || 'manual'] }}</em>
            </span>
          </div>
        </template>

        <!-- 标题 -->
        <template v-else-if="column.key === 'title'">
          <a-tooltip :title="record.title" placement="topLeft">
            <span class="ttl-text">{{ record.title }}</span>
          </a-tooltip>
        </template>

        <!-- 当前价 -->
        <template v-else-if="column.key === 'price'">
          <span class="num">${{ record.latest_price.toFixed(2) }}</span>
        </template>

        <!-- 7 日价格变化（涨红跌绿，与调度层既有约定一致） -->
        <template v-else-if="column.key === 'price_delta'">
          <span class="num" :class="deltaClass(record.price_change_7d)">
            {{ record.price_change_7d > 0 ? '+' : '' }}{{ record.price_change_7d }}%
          </span>
        </template>

        <!-- BSR -->
        <template v-else-if="column.key === 'bsr'">
          <div class="bsr-cell">
            <span class="num">#{{ record.latest_bsr.toLocaleString() }}</span>
            <span class="bsr-delta" :class="record.bsr_change_7d < 0 ? 'up' : record.bsr_change_7d > 0 ? 'down' : 'muted'">
              {{ record.bsr_change_7d > 0 ? '↓' : record.bsr_change_7d < 0 ? '↑' : '·' }}{{ Math.abs(record.bsr_change_7d) }}
            </span>
          </div>
        </template>

        <!-- 评分 / 评论 -->
        <template v-else-if="column.key === 'review'">
          <div class="rv-cell">
            <span class="rv-star">★ {{ record.rating.toFixed(1) }}</span>
            <span class="rv-count">{{ record.review_count.toLocaleString() }} 条</span>
          </div>
        </template>

        <!-- 库存 -->
        <template v-else-if="column.key === 'stock'">
          <a-tag :color="stockColor(record.stock_status)" class="mini-tag">{{ stockLabel(record.stock_status) }}</a-tag>
        </template>

        <!-- 分组 -->
        <template v-else-if="column.key === 'groups'">
          <div class="grp-chips">
            <a-tag v-for="gid in record.group_ids" :key="gid" :color="groupColor(gid)" class="grp-chip">
              {{ groupName(gid) }}
            </a-tag>
            <span v-if="!record.group_ids.length" class="muted">—</span>
          </div>
        </template>

        <!-- 归属 -->
        <template v-else-if="column.key === 'owner'">
          <a-tag v-if="record.owned_by" class="ow-tag" :title="record.owned_by.title || record.owned_by.asin">
            {{ record.owned_by.type === 'product' ? '主品' : '候选' }} · {{ record.owned_by.asin }}
          </a-tag>
          <span v-else class="ow-free">游离</span>
        </template>

        <!-- 操作 -->
        <template v-else-if="column.key === 'action'">
          <a-popconfirm title="把该竞品移出监控池？" @confirm="pool.removeRecords([record.asin])">
            <a-button type="text" size="small" danger><DeleteOutlined /></a-button>
          </a-popconfirm>
        </template>
      </template>

      <template #emptyText>
        <a-empty
          :description="pool.totalCount ? '没有符合当前过滤条件的竞品' : '监控池还是空的，先添加一个竞品 ASIN'"
        />
      </template>
    </a-table>

    <!-- ================= 添加竞品 ================= -->
    <a-modal v-model:open="addModalOpen" title="➕ 添加竞品到监控池" :width="440" centered :footer="null">
      <a-form layout="vertical">
        <a-form-item label="ASIN">
          <a-input v-model:value="addForm.asin" placeholder="如 B0XXXXXXXXX" @press-enter="submitAdd" />
        </a-form-item>
        <a-form-item label="标题 / 备注">
          <a-input v-model:value="addForm.title" placeholder="可先留空，抓取后自动回填" />
        </a-form-item>
        <a-form-item label="归入分组">
          <a-select v-model:value="addForm.groupId" allow-clear placeholder="可不选" style="width: 100%">
            <a-select-option v-for="g in pool.groups" :key="g.id" :value="g.id">
              <span class="grp-dot" :style="{ background: g.color }"></span>{{ g.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-button type="primary" block :disabled="!addForm.asin.trim()" @click="submitAdd">
          加入监控池
        </a-button>
        <div class="add-hint">纯前端原型：录入后本池可见，抓取 / 时间序列待后端接入后补齐。</div>
      </a-form>
    </a-modal>

    <!-- ================= 分组管理 ================= -->
    <a-modal v-model:open="groupModalOpen" title="🗂️ 分组管理" :width="500" centered :footer="null">
      <a-form layout="vertical">
        <a-form-item label="新建分组">
          <a-space-compact style="width: 100%">
            <a-input v-model:value="newGroup.name" placeholder="分组名，如：Q4 重点盯防" @press-enter="submitGroup" />
            <a-select v-model:value="newGroup.kind" style="width: 118px">
              <a-select-option value="custom">自定义</a-select-option>
              <a-select-option value="product">对标产品</a-select-option>
              <a-select-option value="store">对标店铺</a-select-option>
              <a-select-option value="brand">对标品牌</a-select-option>
            </a-select>
            <a-button type="primary" :disabled="!newGroup.name.trim()" @click="submitGroup">创建</a-button>
          </a-space-compact>
        </a-form-item>
      </a-form>

      <div class="grp-list">
        <div v-for="g in pool.groups" :key="g.id" class="grp-row">
          <span class="grp-dot" :style="{ background: g.color }"></span>
          <a-input
            class="grp-name-input"
            size="small"
            :value="g.name"
            @blur="onRenameGroup(g.id, $event)"
            @press-enter="onRenameGroup(g.id, $event)"
          />
          <span class="grp-count">{{ countInGroup(g.id) }} 个</span>
          <a-button type="text" size="small" title="只看该分组" @click="focusGroup(g.id)">
            <FilterOutlined />
          </a-button>
          <a-popconfirm title="删除该分组？组内 ASIN 不会被删除" @confirm="pool.deleteGroup(g.id)">
            <a-button type="text" danger size="small"><DeleteOutlined /></a-button>
          </a-popconfirm>
        </div>
        <a-empty v-if="!pool.groups.length" description="还没有分组" :image-style="{ height: '48px' }" />
      </div>
      <div class="grp-hint">分组名可直接点击修改，失焦即保存。</div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  SearchOutlined,
  PlusOutlined,
  DeleteOutlined,
  AppstoreOutlined,
  FolderAddOutlined,
  SettingOutlined,
  FilterOutlined,
} from '@ant-design/icons-vue'
import { useMonitorPoolStore, type MonitorPoolRecord } from '@/stores/monitorPool'

const pool = useMonitorPoolStore()

/**
 * 监控池是后端权威源。正常路径上 Workspace 的 `watch(currentShopId)` 已经拉过，
 * `ensureLoaded()` 会直接返回；这里兜底是为了「直接进本页但店铺 watcher 未触发」的情况。
 */
onMounted(() => { pool.ensureLoaded() })

// ---------------------------------------------------------------------------
// 过滤：store 负责「分组 + 归属」，搜索是本页本地叠加（store 里没有 searchQuery）
// ---------------------------------------------------------------------------
const searchQuery = ref('')

const filtered = computed<MonitorPoolRecord[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const base = pool.filteredRecords
  if (!q) return base
  return base.filter(
    r =>
      r.asin.toLowerCase().includes(q) ||
      r.title.toLowerCase().includes(q) ||
      r.brand.toLowerCase().includes(q)
  )
})

/** 归属筛选走 store（全站共享），用 computed 双向桥避免直接绑 ref 丢副作用 */
const ownershipModel = computed({
  get: () => pool.currentOwnership,
  set: (v: string) => pool.selectOwnership(v as 'all' | 'owned' | 'free'),
})

/** 空串 = 全部分组（store 里用 null 表示不过滤） */
const groupModel = computed({
  get: () => pool.currentGroupId ?? '',
  set: (v: string) => pool.selectGroup(v === '' ? null : v),
})

const hasLocalFilters = computed(
  () => !!searchQuery.value.trim() || !!pool.currentGroupId || pool.currentOwnership !== 'all'
)

function clearLocalFilters() {
  searchQuery.value = ''
  pool.selectGroup(null)
  pool.selectOwnership('all')
}

const ungroupedCount = computed(
  () => pool.records.filter(r => !r.group_ids || r.group_ids.length === 0).length
)

const currentGroupLabel = computed(() => {
  if (pool.currentGroupId === '__ungrouped__') return '未分组'
  return pool.groups.find(g => g.id === pool.currentGroupId)?.name || '分组'
})

// ---------------------------------------------------------------------------
// 表格
// ---------------------------------------------------------------------------
const columns = [
  { title: 'ASIN / 品牌', key: 'asin', width: 150 },
  { title: '标题', key: 'title', ellipsis: true },
  { title: '当前价', key: 'price', width: 90, align: 'right' as const },
  { title: '7日变化', key: 'price_delta', width: 90, align: 'right' as const },
  { title: 'BSR', key: 'bsr', width: 118, align: 'right' as const },
  { title: '评分 / 评论', key: 'review', width: 118 },
  { title: '库存', key: 'stock', width: 76 },
  { title: '分组', key: 'groups', width: 152 },
  { title: '归属', key: 'owner', width: 128 },
  { title: '操作', key: 'action', width: 70, fixed: 'right' as const },
]

/**
 * 勾选直接读写 store 的 selectedAsins —— 与右栏大屏共用同一个「工作集」：
 * 在这里挑好的竞品，切到竞品监控员就自动是图表画的那几支。
 */
const rowSelection = computed(() => ({
  selectedRowKeys: pool.selectedAsins,
  onChange: (keys: (string | number)[]) => pool.setSelected(keys as string[]),
}))

const alertTotal = computed(() => {
  const s = pool.alertStats
  return s.negative + s.price_drop + s.low_stock
})

const ORIGIN_LABEL: Record<string, string> = {
  candidate: '选自品库',
  manual: '手动添加',
  monitor_page: '监控页新建',
}
const OWNERSHIP_LABEL: Record<string, string> = { all: '全部', owned: '有归属', free: '游离' }

function deltaClass(v: number) {
  return v > 0 ? 'up' : v < 0 ? 'down' : 'muted'
}
function stockLabel(s: MonitorPoolRecord['stock_status']) {
  return s === 'out_of_stock' ? '缺货' : s === 'low_stock' ? '告急' : '在售'
}
function stockColor(s: MonitorPoolRecord['stock_status']) {
  return s === 'out_of_stock' ? 'red' : s === 'low_stock' ? 'orange' : 'green'
}
function groupName(id: string) {
  return pool.groups.find(g => g.id === id)?.name || id
}
function groupColor(id: string) {
  return pool.groups.find(g => g.id === id)?.color || 'default'
}
function countInGroup(id: string) {
  return pool.records.filter(r => r.group_ids?.includes(id)).length
}
function focusGroup(id: string) {
  pool.selectGroup(id)
  groupModalOpen.value = false
}

// ---------------------------------------------------------------------------
// 批量操作
// ---------------------------------------------------------------------------
function handleSelectAllFiltered() {
  pool.setSelected(filtered.value.map(r => r.asin))
}

async function onAssignMenuClick({ key }: { key: string | number }) {
  if (key === '__manage__') {
    groupModalOpen.value = true
    return
  }
  const n = pool.selectedAsins.length
  const name = groupName(String(key))
  await pool.assignToGroup([...pool.selectedAsins], String(key))
  message.success(`已把 ${n} 个竞品加入「${name}」`)
}

async function handleBatchRemove() {
  const n = pool.selectedAsins.length
  await pool.removeRecords([...pool.selectedAsins])
  message.success(`已移出 ${n} 个竞品`)
}

// ---------------------------------------------------------------------------
// 添加竞品
// ---------------------------------------------------------------------------
const addModalOpen = ref(false)
const addForm = reactive({ asin: '', title: '', groupId: undefined as string | undefined })

function openAddModal() {
  addForm.asin = ''
  addForm.title = ''
  addForm.groupId = undefined
  addModalOpen.value = true
}

async function submitAdd() {
  const asin = addForm.asin.trim().toUpperCase()
  // 真实 ASIN = B0 + 8 位字母数字（第 3 位是字母），别用旧的「B 后 9 位纯数字」
  if (!/^[Bb]0[0-9A-Za-z]{8}$/.test(asin)) {
    message.warning('请输入合法 ASIN（B0 开头共 10 位）')
    return
  }
  if (pool.records.some(r => r.asin === asin)) {
    message.warning('该 ASIN 已在监控池中')
    return
  }
  // 只填 ASIN 也能入池：价格/BSR/时序由后端按 ASIN 确定性推导（不传空值才不会覆盖成 0）
  const payload: Partial<MonitorPoolRecord> & { asin: string } = {
    asin,
    origin: 'manual',
  }
  if (addForm.title.trim()) payload.title = addForm.title.trim()
  if (addForm.groupId) payload.group_ids = [addForm.groupId]
  const saved = await pool.upsertRecord(payload)
  if (!saved) {
    message.error(`加入监控池失败，请稍后重试`)
    return
  }
  message.success(`已把 ${asin} 加入监控池`)
  addModalOpen.value = false
}

// ---------------------------------------------------------------------------
// 分组管理
// ---------------------------------------------------------------------------
const groupModalOpen = ref(false)
const newGroup = reactive({ name: '', kind: 'custom' as 'custom' | 'product' | 'store' | 'brand' })

function openGroupModal() {
  newGroup.name = ''
  groupModalOpen.value = true
}

async function submitGroup() {
  const name = newGroup.name.trim()
  if (!name) return
  const created = await pool.createGroup({ name, kind: newGroup.kind })
  if (!created) {
    message.error('创建分组失败，请稍后重试')
    return
  }
  message.success(`分组「${name}」已创建`)
  newGroup.name = ''
}

/** 失焦提交：不做 v-model，避免每敲一个字就写 store */
async function onRenameGroup(id: string, e: Event) {
  const el = e.target as HTMLInputElement
  const name = el.value.trim()
  const old = pool.groups.find(g => g.id === id)?.name
  if (!name || name === old) {
    el.value = old || ''
    return
  }
  await pool.renameGroup(id, name)
  message.success(`分组已重命名为「${name}」`)
}
</script>

<style scoped>
.mp-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  height: 100%;
  min-height: 0;
  padding: var(--space-16) var(--space-20) 0;
  overflow: hidden;
}

/* ===== 页头 ===== */
.mp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-16);
  flex-shrink: 0;
}
.mph-title {
  margin: 0;
  font-size: var(--font-size-17);
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-8);
}
.mph-count {
  font-size: var(--font-size-11);
  font-weight: 500;
  margin: 0;
}
.mph-sub {
  margin-top: var(--space-4);
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-tertiary);
  max-width: 720px;
}
.mph-sub b {
  color: var(--text-secondary);
}

/* ===== 统计卡 ===== */
.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-10);
  flex-shrink: 0;
}
.stat-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-10) var(--space-14);
}
.stat-value {
  font-size: var(--font-size-20);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.stat-value.blue { color: var(--primary); }
.stat-value.red { color: var(--danger); }
.stat-label {
  margin-top: var(--space-2);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.quota-alert { flex-shrink: 0; }

/* ===== 工具条 ===== */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  flex-wrap: wrap;
  flex-shrink: 0;
}
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex-wrap: wrap;
}

/* ===== 活跃过滤 ===== */
.active-filters {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  flex-wrap: wrap;
  padding: var(--space-6) var(--space-10);
  background: var(--bg-hover-light);
  border-radius: var(--radius-8);
  flex-shrink: 0;
}
.af-label {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
}
.af-chip { margin: 0; font-size: var(--font-size-11-5); }

/* ===== 表格 ===== */
.mp-table {
  flex: 1;
  min-height: 0;
}

.asin-cell { display: flex; flex-direction: column; gap: var(--space-1); }
.asin-main {
  font-family: monospace;
  font-size: var(--font-size-12-5);
  font-weight: 600;
  color: var(--primary);
}
.asin-sub {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.origin-badge {
  font-style: normal;
  font-size: var(--font-size-10);
  padding: 0 var(--space-5);
  border-radius: var(--radius-8);
  border: 1px solid var(--border-base);
  color: var(--text-disabled);
}
.origin-badge.candidate {
  border-color: var(--success-border, var(--border-base));
  color: var(--success);
}

.ttl-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.num {
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.num.up { color: var(--danger); }
.num.down { color: var(--success); }
.num.muted { color: var(--text-disabled); }

.bsr-cell { display: flex; align-items: baseline; gap: var(--space-5); justify-content: flex-end; }
.bsr-delta { font-size: var(--font-size-11); font-variant-numeric: tabular-nums; }
.bsr-delta.up { color: var(--success); }
.bsr-delta.down { color: var(--danger); }
.bsr-delta.muted { color: var(--text-disabled); }

.rv-cell { display: flex; flex-direction: column; gap: var(--space-1); }
.rv-star { font-size: var(--font-size-12); color: var(--text-primary); }
.rv-count { font-size: var(--font-size-11); color: var(--text-tertiary); }

.grp-chips { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.grp-chip { margin: 0; font-size: var(--font-size-11); }
.ow-tag { margin: 0; font-size: var(--font-size-11); }
.ow-free { font-size: var(--font-size-11-5); color: var(--text-disabled); }
.muted { color: var(--text-disabled); }
.mini-tag { margin: 0; font-size: var(--font-size-11); }

/* ===== 弹窗内小件 ===== */
.grp-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: var(--radius-circle);
  margin-right: var(--space-6);
  vertical-align: middle;
}
.grp-list { max-height: 280px; overflow-y: auto; }
.grp-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-4);
  border-bottom: 1px solid var(--border-base);
}
.grp-name-input { flex: 1; }
.grp-count { font-size: var(--font-size-12); color: var(--text-tertiary); white-space: nowrap; }
.grp-hint { margin-top: var(--space-10); font-size: var(--font-size-12); color: var(--text-disabled); }
.add-hint { margin-top: var(--space-8); font-size: var(--font-size-12); color: var(--text-disabled); }
</style>
