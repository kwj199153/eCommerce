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
          <span class="dot" :style="{ background: pos.color || '#1890ff' }"></span>
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
.pricing-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-bottom: 14px; }
.strategy-card { padding: 14px; border-radius: 10px; border: 1px solid #f0f0f0; }
.strategy-premium { background: linear-gradient(135deg, #fff7e6, #fffbe6); border-color: #ffd591; }
.strategy-economy { background: linear-gradient(135deg, #f6ffed, #eaffff); border-color: #b7eb8f; }
.strategy-competitive { background: linear-gradient(135deg, #e6f7ff, #f0f5ff); border-color: #91d5ff; }
.strategy-dynamic { background: linear-gradient(135deg, #f9f0ff, #fff0f6); border-color: #d3adf7; }
.strategy-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.strategy-name { font-weight: 600; font-size: 13.5px; }
.strategy-price { font-size: 18px; font-weight: 700; color: var(--text-primary); }
.strategy-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px; }
.metric { text-align: center; padding: 4px; background: rgba(255,255,255,0.6); border-radius: 4px; }
.m-label { display: block; font-size: 10.5px; color: var(--text-tertiary); }
.m-val { font-weight: 600; font-size: 12.5px; color: var(--text-primary); }
.rec-list { margin: 0; padding-left: 16px; font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); }
.rec-list li { margin-bottom: 2px; }
.position-map { padding: 12px; background: var(--bg-base); border-radius: 8px; margin-bottom: 14px; }
.position-map h4 { margin: 0 0 8px; font-size: 13px; }
.position-legend { display: flex; flex-wrap: wrap; gap: 12px; }
.legend-item { display: flex; align-items: center; gap: 5px; font-size: 12px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.insight-box { padding: 12px; background: var(--bg-elevated)0f6; border-radius: 8px; font-size: 12.5px; line-height: 1.7; }
.insight-box p { margin: 0 0 6px; }
.insight-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
