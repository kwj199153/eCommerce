<template>
  <ConversationCard
    icon="💰"
    title="利润测算"
    :badge="roiText"
    :badge-color="roiColor"
    :note="analysis?.product_name || ''"
  >
    <div class="pf-grid">
      <div class="pf-cell">
        <div class="pf-k">售价</div>
        <div class="pf-v">{{ money(analysis?.selling_price) }}</div>
      </div>
      <div class="pf-cell">
        <div class="pf-k">总成本</div>
        <div class="pf-v">{{ money(analysis?.total_cost) }}</div>
      </div>
      <div class="pf-cell">
        <div class="pf-k">净利润</div>
        <div class="pf-v" :class="profitClass">{{ money(analysis?.net_profit) }}</div>
      </div>
      <div class="pf-cell">
        <div class="pf-k">回本件数</div>
        <div class="pf-v">{{ analysis?.break_even_quantity ?? '—' }}</div>
      </div>
    </div>

    <div v-if="feeRows.length" class="pf-fees">
      <div v-for="row in feeRows" :key="row.name" class="pf-fee-row">
        <span class="pf-fee-name">{{ row.name }}</span>
        <span class="pf-fee-amount">{{ money(row.amount) }}</span>
      </div>
    </div>
    <div v-else class="pf-empty">{{ summary || '未获取到费用明细。' }}</div>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConversationCard from './ConversationCard.vue'
import { money } from './format'

const props = defineProps<{ data: any }>()

const analysis = computed(() => props.data?.analysis || null)
const summary = computed(() => props.data?.summary || '')

const roiText = computed(() => {
  const roi = Number(analysis.value?.roi_percentage)
  return Number.isFinite(roi) ? `ROI ${roi.toFixed(1)}%` : ''
})

/** ROI 语义：≥30% 健康（绿），15%~30% 及格（橙），<15% 偏薄（红） */
const roiColor = computed(() => {
  const roi = Number(analysis.value?.roi_percentage)
  if (!Number.isFinite(roi)) return 'default'
  if (roi >= 30) return 'green'
  if (roi >= 15) return 'orange'
  return 'red'
})

/** 净利润正负决定颜色 */
const profitClass = computed(() => {
  const p = Number(analysis.value?.net_profit)
  if (!Number.isFinite(p)) return ''
  if (p > 0) return 'is-good'
  if (p < 0) return 'is-bad'
  return ''
})

const feeRows = computed(() =>
  Object.entries(props.data?.fees_breakdown || {}).map(([name, amount]) => ({
    name,
    amount: amount as number,
  })),
)
</script>

<style scoped>
.pf-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}
.pf-cell {
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-6) var(--space-8);
}
.pf-k {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.pf-v {
  margin-top: var(--space-2);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.pf-fees {
  border-top: 1px dashed var(--border-base);
  padding-top: var(--space-6);
}
.pf-fee-row {
  display: flex;
  justify-content: space-between;
  padding: var(--space-2) 0;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.pf-fee-amount {
  color: var(--text-secondary);
}
.pf-empty {
  color: var(--text-tertiary);
  line-height: 1.6;
}
.is-good {
  color: var(--success);
}
.is-bad {
  color: var(--danger);
}
</style>
