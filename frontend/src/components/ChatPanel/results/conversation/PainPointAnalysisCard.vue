<template>
  <ConversationCard
    icon="🔍"
    title="痛点机会"
    :badge="gapText"
    badge-color="orange"
    :note="asin"
  >
    <div v-if="points.length" class="pp-list">
      <div v-for="pp in points" :key="pp.pain_point" class="pp-item">
        <div class="pp-line">
          <span class="pp-name">{{ pp.pain_point }}</span>
          <span class="pp-pct">{{ pp.percentage }}%</span>
        </div>
        <div class="pp-bar">
          <i :style="{ width: `${Math.min(100, Number(pp.percentage) || 0)}%` }" />
        </div>
        <div class="pp-count">{{ pp.count }} 条提及</div>
      </div>
    </div>
    <div v-else class="pp-empty">{{ summary || '暂未提炼出明显痛点。' }}</div>

    <ul v-if="suggestions.length" class="pp-sug">
      <li v-for="(s, i) in suggestions" :key="i">{{ s }}</li>
    </ul>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConversationCard from './ConversationCard.vue'

const props = defineProps<{ data: any }>()

const summary = computed(() => props.data?.summary || '')
const asin = computed(() => props.data?.asin || props.data?.analysis?.product_asin || '')

/** 优先用后端裁好的 top_pain_points，回退 analysis.pain_points */
const points = computed<any[]>(
  () => props.data?.top_pain_points || props.data?.analysis?.pain_points || [],
)

const suggestions = computed<string[]>(() =>
  (props.data?.analysis?.improvement_suggestions || []).slice(0, 3),
)

const gapText = computed(() => {
  const gap = Number(props.data?.analysis?.market_gap_score)
  return Number.isFinite(gap) ? `市场空白度 ${Math.round(gap)}` : ''
})
</script>

<style scoped>
.pp-item {
  margin-bottom: var(--space-8);
}
.pp-item:last-child {
  margin-bottom: 0;
}
.pp-line {
  display: flex;
  align-items: baseline;
  gap: var(--space-8);
}
.pp-name {
  font-weight: 600;
  color: var(--text-primary);
}
.pp-pct {
  margin-left: auto;
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--warning);
}
.pp-bar {
  margin-top: var(--space-4);
  height: 4px;
  border-radius: var(--radius-2);
  background: var(--bg-card-pill);
  overflow: hidden;
}
.pp-bar i {
  display: block;
  height: 100%;
  background: var(--warning);
}
.pp-count {
  margin-top: var(--space-2);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.pp-sug {
  margin: var(--space-8) 0 0;
  padding-left: var(--space-18);
  border-top: 1px dashed var(--border-base);
  padding-top: var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  line-height: 1.6;
}
.pp-empty {
  color: var(--text-tertiary);
  line-height: 1.6;
}
</style>
