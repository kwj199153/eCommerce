<template>
  <div class="pricing-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>💵 定价策略分析</h3>
      <a-tag color="blue">{{ data.analyzed_count || 0 }} 个竞品</a-tag>
    </div>

    <!-- 策略分类概览 -->
    <div v-if="data.strategies" class="strategy-grid">
      <div
        v-for="(s, i) in data.strategies"
        :key="i"
        class="strategy-card"
        :class="'strategy-' + s.strategy_type"
      >
        <div class="strategy-header">
          <span class="strategy-name">{{ strategyName(s.strategy_type) }}</span>
          <span class="strategy-price">${{ s.base_price?.toFixed(2) }}</span>
        </div>
        <div class="strategy-metrics">
          <div class="metric">
            <span class="m-label">平均折扣</span>
            <span class="m-val">{{ s.avg_discount?.toFixed(0) }}%</span>
          </div>
          <div class="metric">
            <span class="m-label">促销频率</span>
            <span class="m-val">{{ promoLabel(s.promo_frequency) }}</span>
          </div>
          <div class="metric">
            <span class="m-label">价格弹性</span>
            <span class="m-val">{{ s.price_elasticity?.toFixed(2) }}</span>
          </div>
          <div class="metric">
            <span class="m-label">波动率</span>
            <span class="m-val">{{ (s.price_volatility * 100)?.toFixed(1) }}%</span>
          </div>
        </div>
        <ul class="rec-list" v-if="s.recommendations?.length">
          <li v-for="(r, j) in s.recommendations.slice(0, 2)" :key="j">{{ r }}</li>
        </ul>
      </div>
    </div>

    <!-- 市场定位图（简化版） -->
    <div v-if="data.market_positioning_map" class="position-map">
      <h4>📍 市场定位分布</h4>
      <div class="position-legend">
        <span v-for="(pos, k) in data.market_positioning_map.segments" :key="k" class="legend-item">
          <span class="dot" :style="{ background: pos.color || SEM.primary }"></span>
          {{ pos.name }}: {{ pos.count || 0 }}
        </span>
      </div>
    </div>

    <!-- 建议 -->
    <div class="insight-box">
      <p><strong>💡 定价建议：</strong></p>
      <ul>
        <li v-for="(tip, i) in aggregatedRecommendations" :key="i">{{ tip }}</li>
      </ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { SEM } from '@/theme/semantic'
import { computed } from 'vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const strategyName = (t: string) => ({
  premium: '溢价策略 🏷️',
  economy: '经济策略 💰',
  competitive: '竞争策略 ⚔️',
  dynamic: '动态定价 📊',
}[t] || t)

const promoLabel = (f: string) => ({
  high: '高频',
  medium: '中频',
  low: '低频',
  none: '无促销',
}[f] || f)

const aggregatedRecommendations = computed(() => {
  const recs: string[] = []
  props.data.strategies?.forEach((s: any) => {
    if (s.recommendations) recs.push(...s.recommendations)
  })
  return [...new Set(recs)].slice(0, 6)
})
</script>

<style scoped>
.pricing-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-14); }
.result-header h3 { margin: 0; font-size: var(--font-size-16); }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: var(--space-12); margin-bottom: var(--space-14); }
.strategy-card { padding: var(--space-14); border-radius: var(--radius-10); border: 1px solid var(--border-base); }
.strategy-premium { background: linear-gradient(135deg, var(--orange-bg), var(--warning-bg)); border-color: var(--orange-border); }
.strategy-economy { background: linear-gradient(135deg, #f6ffed, #eaffff); border-color: var(--success-border); }
.strategy-competitive { background: linear-gradient(135deg, #e6f7ff, #f0f5ff); border-color: var(--info-border); }
.strategy-dynamic { background: linear-gradient(135deg, #f9f0ff, #fff0f6); border-color: #d3adf7; }
.strategy-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-10); }
.strategy-name { font-weight: 600; font-size: var(--font-size-13-5); }
.strategy-price { font-size: var(--font-size-18); font-weight: 700; color: var(--text-primary); }
.strategy-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-6); margin-bottom: var(--space-10); }
.metric { text-align: center; padding: var(--space-4); background: rgba(255,255,255,0.6); border-radius: var(--radius-4); }
.m-label { display: block; font-size: var(--font-size-10-5); color: var(--text-tertiary); }
.m-val { font-weight: 600; font-size: var(--font-size-12-5); color: var(--text-primary); }
.rec-list { margin: 0; padding-left: var(--space-16); font-size: var(--font-size-11-5); line-height: 1.6; color: var(--text-secondary); }
.rec-list li { margin-bottom: var(--space-2); }
.position-map { padding: var(--space-12); background: var(--bg-base); border-radius: var(--radius-8); margin-bottom: var(--space-14); }
.position-map h4 { margin: 0 0 var(--space-8); font-size: var(--font-size-13); }
.position-legend { display: flex; flex-wrap: wrap; gap: var(--space-12); }
.legend-item { display: flex; align-items: center; gap: var(--space-5); font-size: var(--font-size-12); }
.dot { width: 10px; height: 10px; border-radius: var(--radius-circle); display: inline-block; }
.insight-box { padding: var(--space-12); background: #fff0f6; border-radius: var(--radius-8); font-size: var(--font-size-12-5); line-height: 1.7; }
.insight-box p { margin: 0 0 var(--space-6); }
.insight-box ul { margin: 0; padding-left: var(--space-18); }
.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); margin-top: var(--space-12); }
</style>
