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
  { title: '当前预算', dataIndex: 'current_budget', width: 80, align: 'right', customRender: ({ text }: { text: any }) => `$${text}` },
  { title: '建议预算', dataIndex: 'suggested_budget', width: 80, align: 'right', customRender: ({ text }: { text: any }) => `$${text}` },
  { title: '变化', dataIndex: 'change', width: 65, align: 'center' },
  { title: '分配占比', dataIndex: 'allocation_pct', width: 75, align: 'center',
    customRender: ({ text }: { text: any }) => `${Number(text).toFixed(1)}%` },
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
  padding: var(--space-16);
  /* --bg-raised / --shadow-card 替代原 styles/dark-overrides.css 的深色补丁 */
  background: var(--bg-raised);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  box-shadow: var(--shadow-card);
}

.budget-overview {
  display: flex; align-items: center; justify-content: center; gap: var(--space-20);
  padding: var(--space-20); background: linear-gradient(135deg, var(--success-bg), var(--info-bg));
  border-radius: var(--radius-12); margin-bottom: var(--space-16);
}
.budget-card { text-align: center; }
.budget-card .label { display: block; font-size: var(--font-size-11-5); color: var(--text-tertiary); margin-bottom: var(--space-4); }
.budget-card .value { display: block; font-size: var(--font-size-28); font-weight: 800; color: var(--text-primary); }
.budget-card.suggested .value { color: var(--success); }
.arrow { font-size: var(--font-size-24); color: var(--text-disabled); }
.change { display: inline-block; font-size: var(--font-size-13); font-weight: 600; margin-top: var(--space-2); padding: var(--space-1) var(--space-8); border-radius: var(--radius-10); }
.change.up { background: var(--success-bg); color: var(--success); }
.change.down { background: var(--danger-bg); color: var(--danger); }

.section-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-10); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }

.change-up { color: var(--success); font-weight: 600; }
.change-down { color: var(--danger); font-weight: 600; }

.improvement-grid { margin-top: var(--space-14); padding: var(--space-14); background: var(--info-bg); border-radius: var(--radius-8); border: 1px solid var(--info-border); }
.improvement-grid h4 { margin: 0 0 var(--space-10); font-size: var(--font-size-13); color: var(--primary-strong); }
.improvement-items { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-10); }
.imp-item { text-align: center; padding: var(--space-8); background: var(--bg-raised); border-radius: var(--radius-6); }
.imp-label { display: block; font-size: var(--font-size-11); color: var(--text-tertiary); }
.imp-value { display: block; font-size: var(--font-size-18); font-weight: 700; color: var(--primary); margin-top: var(--space-2); }

.risk-box { margin-top: var(--space-14); padding: var(--space-12) var(--space-16); border-radius: var(--radius-8); }
.risk-low { background: var(--success-bg); border: 1px solid var(--success-border); }
.risk-medium { background: var(--warning-bg); border: 1px solid var(--warning-border); }
.risk-high { background: var(--danger-bg); border: 1px solid var(--danger-border-strong); }
.risk-box h4 { margin: 0 0 var(--space-6); font-size: var(--font-size-13); }
.risk-low h4 { color: var(--success); }
.risk-medium h4 { color: var(--warning-strong); }
.risk-high h4 { color: var(--danger-strong); }
.risk-box p { margin: 0; font-size: var(--font-size-12-5); line-height: 1.5; color: var(--text-secondary); }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }

:deep(.ant-table) { background: transparent; }
:deep(.ant-table-thead > tr > th) { background: var(--bg-base); color: var(--text-secondary); border-bottom-color: var(--border-base); }
:deep(.ant-table-tbody > tr > td) { border-bottom-color: var(--border-base); }
:deep(.change-up) { color: var(--success); font-weight: 600; }
:deep(.change-down) { color: var(--danger); font-weight: 600; }

</style>
