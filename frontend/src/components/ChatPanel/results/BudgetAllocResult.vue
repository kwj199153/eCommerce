<template>
  <div class="budget-alloc-result" v-if="data">
    <!-- 预算总览 -->
    <div class="budget-overview">
      <div class="budget-card current">
        <span class="label">当前日预算</span>
        <span class="value">${{ Number(data.total_current_budget || 0).toFixed(0) }}</span>
      </div>
      <div class="arrow">→</div>
      <div class="budget-card suggested">
        <span class="label">建议日预算</span>
        <span class="value">${{ Number(data.total_suggested_budget || 0).toFixed(0) }}</span>
        <span class="change" :class="(data.total_suggested_budget || 0) > (data.total_current_budget || 0) ? 'up' : 'down'">
          {{ ((data.total_suggested_budget - data.total_current_budget) / data.total_current_budget * 100 || 0).toFixed(1) }}%
        </span>
      </div>
    </div>

    <!-- 分配详情表 -->
    <h4 class="section-title">💰 各 Campaign 预算分配</h4>
    <a-table
      :dataSource="data.allocations || []"
      :columns="allocColumns"
      :pagination="false"
      size="small"
      rowKey="campaign_name"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.dataIndex === 'change'">
          <span :class="getChangeClass(record)">
            {{ getChangePct(record) }}
          </span>
        </template>
        <template v-if="column.dataIndex === 'reason'">
          <a-tooltip :title="record.reason">{{ record.reason?.slice(0, 20) }}...</a-tooltip>
        </template>
      </template>
    </a-table>

    <!-- 预期改善 -->
    <div v-if="data.projected_improvement" class="improvement-grid">
      <h4>📈 预期改善</h4>
      <div class="improvement-items">
        <div v-for="(val, key) in data.projected_improvement" :key="key" class="imp-item">
          <span class="imp-label">{{ improvementLabels[key] || key }}</span>
          <span class="imp-value">{{ val }}</span>
        </div>
      </div>
    </div>

    <!-- 风险评估 -->
    <div class="risk-box" :class="riskLevel">
      <h4>⚠️ 风险评估</h4>
      <p>{{ data.risk_assessment || '风险可控' }}</p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const allocColumns = [
  { title: 'Campaign', dataIndex: 'campaign_name', width: 180, ellipsis: true },
  { title: '当前预算', dataIndex: 'current_budget', width: 80, align: 'right', customRender: ({ text }) => `$${text}` },
  { title: '建议预算', dataIndex: 'suggested_budget', width: 80, align: 'right', customRender: ({ text }) => `$${text}` },
  { title: '变化', dataIndex: 'change', width: 65, align: 'center' },
  { title: '分配占比', dataIndex: 'allocation_pct', width: 75, align: 'center',
    customRender: ({ text }) => `${Number(text).toFixed(1)}%` },
  { title: '预期 RoAS', dataIndex: 'expected_roas', width: 75, align: 'right' },
  { title: '调拨原因', dataIndex: 'reason', ellipsis: true },
]

const improvementLabels: Record<string, string> = {
  expected_roas_increase: 'RoAS 提升',
  expected_acos_decrease: 'ACoS 降低',
  efficiency_gain: '效率提升',
}

const getChangePct = (r: any) => {
  const pct = ((r.suggested_budget - r.current_budget) / r.current_budget * 100)
  return (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%'
}
const getChangeClass = (r: any) => {
  const change = r.suggested_budget - r.current_budget
  return change > 0 ? 'change-up' : change < 0 ? 'change-down' : ''
}

const riskLevel = computed(() => {
  const text = props.data.risk_assessment || ''
  if (text.includes('低')) return 'risk-low'
  if (text.includes('中')) return 'risk-medium'
  return 'risk-high'
})
</script>

<style scoped>
.budget-alloc-result {
  padding: 16px;
  background: var(--bg-elevated);
  border: 1px solid #e8e8e8;
  border-radius: 8px;
}

.budget-overview {
  display: flex; align-items: center; justify-content: center; gap: 20px;
  padding: 20px; background: linear-gradient(135deg, #f6ffed, #e6fffb);
  border-radius: 12px; margin-bottom: 16px;
}
.budget-card { text-align: center; }
.budget-card .label { display: block; font-size: 11.5px; color: #8c8c8c; margin-bottom: 4px; }
.budget-card .value { display: block; font-size: 28px; font-weight: 800; color: var(--text-primary); }
.budget-card.suggested .value { color: #52c41a; }
.arrow { font-size: 24px; color: #bfbfbf; }
.change { display: inline-block; font-size: 13px; font-weight: 600; margin-top: 2px; padding: 1px 8px; border-radius: 10px; }
.change.up { background: #f6ffed; color: #52c41a; }
.change.down { background: #fff1f0; color: #ff4d4f; }

.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border-base); }

.change-up { color: #52c41a; font-weight: 600; }
.change-down { color: #ff4d4f; font-weight: 600; }

.improvement-grid { margin-top: 14px; padding: 14px; background: #e6f7ff; border-radius: 8px; border: 1px solid #91d5ff; }
.improvement-grid h4 { margin: 0 0 10px; font-size: 13px; color: #0958d9; }
.improvement-items { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.imp-item { text-align: center; padding: 8px; background: #fff; border-radius: 6px; }
.imp-label { display: block; font-size: 11px; color: #8c8c8c; }
.imp-value { display: block; font-size: 18px; font-weight: 700; color: #1890ff; margin-top: 2px; }

.risk-box { margin-top: 14px; padding: 12px 16px; border-radius: 8px; }
.risk-low { background: #f6ffed; border: 1px solid #b7eb8f; }
.risk-medium { background: #fffbe6; border: 1px solid #ffe58f; }
.risk-high { background: #fff1f0; border: 1px solid #ffa39e; }
.risk-box h4 { margin: 0 0 6px; font-size: 13px; }
.risk-low h4 { color: #389e0d; }
.risk-medium h4 { color: #d48806; }
.risk-high h4 { color: #cf1322; }
.risk-box p { margin: 0; font-size: 12.5px; line-height: 1.5; color: #595959; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid var(--border-base); }

:deep(.ant-table) { background: transparent; }
:deep(.ant-table-thead > tr > th) { background: #fafafa; color: #595959; border-bottom-color: var(--border-base); }
:deep(.ant-table-tbody > tr > td) { border-bottom-color: var(--border-base); }
:deep(.change-up) { color: #52c41a; font-weight: 600; }
:deep(.change-down) { color: #ff4d4f; font-weight: 600; }

/* ====== 深色模式精调移至下方 <style> 块（scoped 内 :global() 嵌套会被 Vue 编译器丢弃） ====== */
</style>

<!-- ====== 深色模式精调（必须用非 scoped 块，整段选择器全局化） ====== -->
<style>
html.dark .budget-alloc-result {
  background: #262626;
  border-color: #404040;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}
html.dark .budget-alloc-result .budget-overview {
  background: linear-gradient(135deg, rgba(82,196,26,0.1), rgba(24,144,255,0.08));
  border: 1px solid rgba(82,196,26,0.3);
}
html.dark .budget-alloc-result .budget-card .label { color: rgba(255, 255, 255, 0.55); }
html.dark .budget-alloc-result .budget-card .value { color: rgba(255, 255, 255, 0.95); }
html.dark .budget-alloc-result .budget-card.suggested .value { color: #73d13d; }
html.dark .budget-alloc-result .arrow { color: rgba(255, 255, 255, 0.4); }
html.dark .budget-alloc-result .section-title { color: rgba(255, 255, 255, 0.95); }
html.dark .budget-alloc-result .improvement-grid {
  background: rgba(24,144,255,0.12);
  border-color: rgba(24,144,255,0.35);
}
html.dark .budget-alloc-result .improvement-grid h4 { color: #40a9ff; }
html.dark .budget-alloc-result .imp-item {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
html.dark .budget-alloc-result .imp-label { color: rgba(255, 255, 255, 0.55); }
html.dark .budget-alloc-result .imp-value { color: #40a9ff; }
html.dark .budget-alloc-result .risk-low { background: rgba(82,196,26,0.12); border-color: rgba(82,196,26,0.4); }
html.dark .budget-alloc-result .risk-medium { background: rgba(250,173,20,0.12); border-color: rgba(250,173,20,0.4); }
html.dark .budget-alloc-result .risk-high { background: rgba(255,77,79,0.12); border-color: rgba(255,77,79,0.4); }
html.dark .budget-alloc-result .risk-low h4 { color: #73d13d; }
html.dark .budget-alloc-result .risk-medium h4 { color: #ffc53d; }
html.dark .budget-alloc-result .risk-high h4 { color: #ff7875; }
html.dark .budget-alloc-result .risk-box p { color: rgba(255, 255, 255, 0.75); }
html.dark .budget-alloc-result .result-footer { border-top-color: rgba(255, 255, 255, 0.1); }
html.dark .budget-alloc-result .ant-table-thead > tr > th {
  background: rgba(255, 255, 255, 0.04) !important;
  color: rgba(255, 255, 255, 0.7) !important;
}
html.dark .budget-alloc-result .ant-table-tbody > tr > td {
  background: transparent !important;
  border-bottom-color: rgba(255, 255, 255, 0.06) !important;
  color: rgba(255, 255, 255, 0.85);
}
</style>
