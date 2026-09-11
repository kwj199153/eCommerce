<template>
  <div class="search-term-result" v-if="data">
    <!-- 统计摘要 -->
    <div class="summary-bar">
      <span class="stat-item">📊 总搜索词: <b>{{ data.total_terms || 0 }}</b></span>
      <span class="stat-item">🟢 高效词: <b>{{ (data.high_performers || []).length }}</b></span>
      <span class="stat-item">🔴 低效词: <b>{{ (data.low_performers || []).length }}</b></span>
      <span class="stat-item">⚠️ 浪费词: <b>{{ (data.waste_terms || []).length }}</b></span>
      <span class="stat-item">💡 机会词: <b>{{ (data.new_opportunities || []).length }}</b></span>
    </div>

    <!-- 四象限标签页 -->
    <a-tabs v-model:activeKey="activeTab" size="small">
      <!-- 高效词 -->
      <a-tab-pane key="high" :tab="`🟢 高效词 (${(data.high_performers || []).length})`">
        <a-table
          :dataSource="data.high_performers || []"
          :columns="termColumns"
          :pagination="{ pageSize: 5, size: 'small' }"
          size="small"
          :scroll="{ x: 650 }"
          rowKey="term"
          :rowClassName="() => 'row-high'"
        />
      </a-tab-pane>

      <!-- 低效词 -->
      <a-tab-pane key="low" :tab="`🔴 低效词 (${(data.low_performers || []).length})`">
        <a-table
          :dataSource="data.low_performers || []"
          :columns="termColumns"
          :pagination="{ pageSize: 5, size: 'small' }"
          size="small"
          :scroll="{ x: 650 }"
          rowKey="term"
          :rowClassName="() => 'row-low'"
        />
      </a-tab-pane>

      <!-- 浪费词 -->
      <a-tab-pane key="waste" :tab="`⚠️ 浪费词 (${(data.waste_terms || []).length})`">
        <a-table
          :dataSource="data.waste_terms || []"
          :columns="termColumns"
          :pagination="{ pageSize: 5, size: 'small' }"
          size="small"
          :scroll="{ x: 650 }"
          rowKey="term"
          :rowClassName="() => 'row-waste'"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'acos'">
              <span style="color: #ff4d4f; font-weight: 600;">{{ record.acos === 999 ? '∞' : record.acos + '%' }}</span>
            </template>
            <template v-if="column.dataIndex === 'sales'">
              <span style="color: var(--text-tertiary);">$0.00</span>
            </template>
          </template>
        </a-table>
      </a-tab-pane>

      <!-- 新机会词 -->
      <a-tab-pane key="opp" :tab="`💡 机会词 (${(data.new_opportunities || []).length})`">
        <a-table
          :dataSource="data.new_opportunities || []"
          :columns="termColumns"
          :pagination="{ pageSize: 5, size: 'small' }"
          size="small"
          :scroll="{ x: 650 }"
          rowKey="term"
          :rowClassName="() => 'row-opp'"
        />
      </a-tab-pane>
    </a-tabs>

    <!-- 优化建议 -->
    <div v-if="data.suggestions?.length" class="suggestions-box">
      <h4>💡 优化建议</h4>
      <ul><li v-for="(s, i) in data.suggestions" :key="i">{{ s }}</li></ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const activeTab = ref('high')

const termColumns = [
  { title: '搜索词', dataIndex: 'term', width: 220, ellipsis: true },
  { title: '展示量', dataIndex: 'impressions', width: 65, align: 'right' },
  { title: '点击', dataIndex: 'clicks', width: 50, align: 'right' },
  { title: 'CTR', dataIndex: 'ctr', width: 55, align: 'right', customRender: ({ text }: { text: any }) => `${Number(text).toFixed(2)}%` },
  { title: '花费', dataIndex: 'spend', width: 60, align: 'right', customRender: ({ text }: { text: any }) => `$${Number(text).toFixed(2)}` },
  { title: '销售额', dataIndex: 'sales', width: 70, align: 'right', customRender: ({ text }: { text: any }) => `$${Number(text).toFixed(2)}` },
  { title: 'ACoS', dataIndex: 'acos', width: 55, align: 'right', customRender: ({ text }: { text: any }) => Number(text) >= 999 ? '∞%' : `${Number(text).toFixed(0)}%` },
  { title: 'RoAS', dataIndex: 'roas', width: 55, align: 'right', customRender: ({ text }: { text: any }) => Number(text).toFixed(1) },
  { title: '匹配', dataIndex: 'match_type', width: 50, align: 'center' },
]
</script>

<style scoped>
.search-term-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }

.summary-bar {
  display: flex; gap: 16px; padding: 12px 16px;
  background: var(--bg-base); border-radius: 8px; margin-bottom: 14px;
  flex-wrap: wrap; font-size: 12.5px; color: var(--text-secondary);
}
.stat-item b { color: var(--text-primary); margin-left: 2px; }

.suggestions-box { margin-top: 14px; padding: 12px; background: #f6ffed; border-radius: 8px; border: 1px solid #b7eb8f; }
.suggestions-box h4 { margin: 0 0 8px; font-size: 13px; color: #389e0d; }
.suggestions-box ul { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.8; color: var(--text-secondary); }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }

:deep(.row-high) { background-color: #f6ffed !important; }
:deep(.row-low) { background-color: #fffbe6 !important; }
:deep(.row-waste) { background-color: #fff1f0 !important; }
:deep(.row-opp) { background-color: #e6f7ff !important; }
</style>
