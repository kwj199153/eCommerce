<template>
  <div class="competitor-monitor">
    <!-- ===== 顶部工作台头 ===== -->
    <div class="cm-header">
      <div class="cm-header-left">
        <div class="cm-title">📡 竞品监控工作台</div>
        <div class="cm-sub">一套监控池 · 六种追踪视角 · 全 Agent 共用同一份数据</div>
      </div>
      <div class="cm-header-right">
        <a-space>
          <a-tag :color="COLOR_COUNT">{{ pool.totalCount }} 个监控 ASIN</a-tag>
          <a-tag :color="COLOR_COUNT">{{ pool.groups.length }} 个分组</a-tag>
          <a-tag :color="COLOR_COUNT">{{ pool.selectedAsins.length }} 已圈选</a-tag>
          <a-button size="small" @click="openAddModal">
            <PlusOutlined /> 添加竞品
          </a-button>
          <a-button size="small" @click="openGroupModal">
            <AppstoreOutlined /> 分组管理
          </a-button>
        </a-space>
      </div>
    </div>

    <!-- ===== 告警条：全池提醒聚合（跨面板共用） ===== -->
    <div v-if="alertList.length" class="cm-alert-bar">
      <a-space wrap :size="4">
        <span class="cm-alert-title">🔔 今日需关注</span>
        <template v-for="(a, i) in alertList" :key="i">
          <a-tag :color="a.color">{{ a.text }}</a-tag>
        </template>
      </a-space>
    </div>

    <!-- ===== 主导航标签：6 追踪面板 + 监控池 ===== -->
    <div class="cm-panel-tabs">
      <div class="cm-tabs">
        <button class="cm-tab" :class="{ active: pool.activePanel === 'pool' }" @click="setPanel('pool')">
          <span class="cm-tab-icon">🗂️</span>监控池
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'price' }" @click="setPanel('price')">
          <span class="cm-tab-icon">📉</span>价格历史
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'bsr' }" @click="setPanel('bsr')">
          <span class="cm-tab-icon">📈</span>BSR 趋势
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'review' }" @click="setPanel('review')">
          <span class="cm-tab-icon">💬</span>评论 &amp; 星级
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'variation' }" @click="setPanel('variation')">
          <span class="cm-tab-icon">🧩</span>变体
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'listing' }" @click="setPanel('listing')">
          <span class="cm-tab-icon">📄</span>Listing 快照
        </button>
        <button class="cm-tab" :class="{ active: pool.activePanel === 'inventory' }" @click="setPanel('inventory')">
          <span class="cm-tab-icon">📦</span>库存/入仓
        </button>
      </div>
      <a-button
        type="primary"
        size="small"
        class="launch-ai-btn"
        @click="launchAiAnalysis"
      >
        🤖 发起 AI 分析
      </a-button>
    </div>

    <!-- ===== 面板内容区 ===== -->
    <div class="cm-body">
      <!-- 监控池面板：统一清单 + 多选 + 分组过滤 -->
      <div v-if="pool.activePanel === 'pool'" class="cm-panel">
        <PoolPanel
          :store="pool"
          @open-add="openAddModal"
          @open-group="openGroupModal"
          @jump-panel="setPanel"
        />
      </div>

      <!-- 六个追踪面板：骨架演示「同一监控池 → 不同视角」 -->
      <div v-else class="cm-panel">
        <PanelPlaceholder :panel="pool.activePanel" @goto-pool="setPanel('pool')" />
      </div>
    </div>

    <!-- ===== 添加竞品弹窗 ===== -->
    <a-modal v-model:open="addModalOpen" title="➕ 添加竞品到监控池" :width="460" centered :footer="null">
      <a-form layout="vertical">
        <a-form-item label="ASIN">
          <a-input v-model:value="addForm.asin" placeholder="如 B0XXXXXXXXX" @pressEnter="submitAdd" />
        </a-form-item>
        <a-form-item label="标题 / 备注">
          <a-input v-model:value="addForm.title" placeholder="可先留空，抓取后自动回填" />
        </a-form-item>
        <a-form-item label="归入分组">
          <a-select v-model:value="addForm.groupId" allowClear placeholder="可不选" style="width: 100%">
            <a-select-option v-for="g in pool.groups" :key="g.id" :value="g.id">
              <span class="grp-dot" :style="{ background: g.color }"></span>{{ g.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-button type="primary" block :disabled="!addForm.asin.trim()" @click="submitAdd">
          加入监控池
        </a-button>
        <div class="add-hint">纯前端原型：录入后本池可见，抓取/时间序列后端接入后补齐。</div>
      </a-form>
    </a-modal>

    <!-- ===== 分组管理弹窗 ===== -->
    <a-modal v-model:open="groupModalOpen" title="🗂️ 分组管理" :width="520" centered :footer="null">
      <a-form layout="vertical">
        <a-form-item label="新建分组">
          <a-space-compact style="width: 100%">
            <a-input v-model:value="newGroup.name" placeholder="分组名，如：Q4 重点盯防" />
            <a-select v-model:value="newGroup.kind" style="width: 130px">
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
          <span class="grp-name">{{ g.name }}</span>
          <a-tag>{{ g.kind === 'product' ? '对标产品' : g.kind === 'store' ? '对标店铺' : g.kind === 'brand' ? '对标品牌' : '自定义' }}</a-tag>
          <span class="grp-count">{{ countInGroup(g.id) }} 个</span>
          <a-popconfirm title="删除该分组？组内 ASIN 不会被删除" @confirm="pool.deleteGroup(g.id)">
            <a-button type="text" danger size="small"><DeleteOutlined /></a-button>
          </a-popconfirm>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, AppstoreOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { useMonitorPoolStore, type MonitorPoolRecord } from '@/stores/monitorPool'
import PoolPanel from './CompetitorMonitor/PoolPanel.vue'
import PanelPlaceholder from './CompetitorMonitor/PanelPlaceholder.vue'
import { COLOR_COUNT } from '@/utils/colorSemantics'

const pool = useMonitorPoolStore()

// —— 顶部主导航 ——
function setPanel(p: any) {
  pool.activePanel = p
}

// —— 告警聚合 ——
const alertList = computed(() => {
  const s = pool.alertStats
  const list: Array<{ text: string; color: string }> = []
  if (s.negative) list.push({ text: `${s.negative} 个竞品近 7 天有差评`, color: 'red' })
  if (s.price_drop) list.push({ text: `${s.price_drop} 个竞品价格骤降(>5%)`, color: 'orange' })
  if (s.low_stock) list.push({ text: `${s.low_stock} 个竞品库存告急/缺货`, color: 'volcano' })
  return list
})

// —— 添加竞品 ——
const addModalOpen = ref(false)
const addForm = reactive({ asin: '', title: '', groupId: undefined as string | undefined })
function openAddModal() {
  addForm.asin = ''
  addForm.title = ''
  addForm.groupId = undefined
  addModalOpen.value = true
}
function submitAdd() {
  const asin = addForm.asin.trim().toUpperCase()
  if (!/^B[0-9A-Z]{9}$/.test(asin)) {
    message.warning('请输入合法 ASIN（B0 开头共 10 位）')
    return
  }
  if (pool.records.some(r => r.asin === asin)) {
    message.warning('该 ASIN 已在监控池中')
    return
  }
  pool.upsertRecord({
    asin,
    title: addForm.title || asin,
    group_ids: addForm.groupId ? [addForm.groupId] : [],
  })
  pool.setSelected([asin])
  message.success(`已把 ${asin} 加入监控池`)
  addModalOpen.value = false
}

// —— 分组管理 ——
const groupModalOpen = ref(false)
const newGroup = reactive({ name: '', kind: 'custom' as any })
function openGroupModal() {
  newGroup.name = ''
  groupModalOpen.value = true
}
function submitGroup() {
  pool.createGroup({ name: newGroup.name, kind: newGroup.kind })
  message.success(`分组「${newGroup.name}」已创建`)
  newGroup.name = ''
}
function countInGroup(id: string) {
  return pool.records.filter(r => r.group_ids?.includes(id)).length
}

/** 快捷「发起 AI 分析」：带当前勾选 ASIN → 跳到竞品监控员 Agent 对话页 */
function launchAiAnalysis() {
  if (!pool.selectedAsins.length) {
    message.warning('请先在监控池勾选要分析的竞品')
    return
  }
  window.dispatchEvent(new CustomEvent('monitor-launch-analysis'))
}
</script>

<style scoped>
.competitor-monitor {
  padding: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}
.cm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.cm-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.cm-sub { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }
.cm-header-right { flex-shrink: 0; }
.launch-ai-btn { font-weight: 500; flex-shrink: 0; box-shadow: 0 2px 6px rgba(24, 144, 255, 0.2); }

.cm-alert-bar {
  background: var(--warning-bg, #fffbe6);
  border: 1px solid var(--warning-border, #ffe58f);
  border-radius: 8px;
  padding: 6px 12px;
}
.cm-alert-title { font-size: 12px; font-weight: 600; color: var(--warning, #ad6800); margin-right: 4px; }

.cm-panel-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.cm-tabs {
  display: flex;
  gap: 4px;
  background: var(--bg-hover-light);
  border-radius: 8px;
  padding: 3px;
  overflow-x: auto;
  flex: 1;
}
.cm-tab {
  border: none;
  background: transparent;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  transition: all 0.2s;
}
.cm-tab:hover { background: var(--bg-elevated); }
.cm-tab.active { background: var(--bg-elevated); color: var(--primary); font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
.cm-tab-icon { margin-right: 4px; }

.cm-body {
  flex: 1;
  min-height: 0;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  overflow: hidden;
}
.cm-panel { height: 100%; }

.grp-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.add-hint { margin-top: 8px; font-size: 12px; color: var(--text-disabled); }
.grp-list { max-height: 300px; overflow-y: auto; }
.grp-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border-base); }
.grp-name { flex: 1; font-size: 13px; color: var(--text-primary); }
.grp-count { font-size: 12px; color: var(--text-tertiary); }
</style>
