<template>
  <div class="competitor-ad-result" v-if="data">
    <!-- SOV 概览 -->
    <div class="sov-overview">
      <div class="sov-card yours">
        <span class="label">你的展示份额 (SOV)</span>
        <span class="value">{{ data.your_share_of_voice || 0 }}%</span>
      </div>
      <div class="position-badge" :class="'pos-' + (data.market_position || 'nicher')">
        {{ positionMap[data.market_position] || '未知' }}
      </div>
    </div>

    <!-- 竞品卡片列表 -->
    <h4 class="section-title">🎯 竞品广告分析</h4>
    <div class="competitor-cards">
      <div v-for="(comp, idx) in (data.competitors || [])" :key="idx" class="comp-card">
        <div class="comp-header">
          <span class="comp-name">{{ comp.competitor_name }}</span>
          <a-tag color="blue">{{ comp.asin }}</a-tag>
        </div>
        <div class="comp-metrics">
          <div class="metric">
            <span class="m-label">SOV</span><span class="m-value">{{ comp.share_of_voice }}%</span>
          </div>
          <div class="metric">
            <span class="m-label">重叠词</span><span class="m-value">{{ comp.overlap_keywords }}</span>
          </div>
          <div class="metric">
            <span class="m-label">排名</span><span class="m-value">#{{ comp.avg_position?.toFixed(1) }}</span>
          </div>
          <div class="metric">
            <span class="m-label">预估花费</span><span class="m-value">${{ Number(comp.estimated_spend).toFixed(0) }}/天</span>
          </div>
        </div>
        <div class="comp-swot">
          <div class="swot-col">
            <span class="swot-label">优势</span>
            <ul><li v-for="(s, i) in (comp.strengths || []).slice(0, 2)" :key="i">{{ s }}</li></ul>
          </div>
          <div class="swot-col">
            <span class="swot-label">劣势</span>
            <ul><li v-for="(w, i) in (comp.weaknesses || []).slice(0, 2)" :key="i">{{ w }}</li></ul>
          </div>
        </div>
      </div>
    </div>

    <!-- 可执行洞察 -->
    <div v-if="data.actionable_insights?.length" class="insights-box">
      <h4>💡 可执行洞察</h4>
      <ul><li v-for="(ins, i) in data.actionable_insights" :key="i">{{ ins }}</li></ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const positionMap: Record<string, string> = {
  leader: '👑 市场领导者',
  challenger: '⚔️ 市场挑战者',
  nicher: '🎯 利基玩家',
}
</script>

<style scoped>
.competitor-ad-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }

.sov-overview {
  display: flex; align-items: center; gap: 16px;
  padding: 16px 20px; background: linear-gradient(135deg, #f0f5ff, #d6e4ff);
  border-radius: 12px; margin-bottom: 16px;
}
.sov-card { flex: 1; }
.sov-card .label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
.sov-card .value { display: block; font-size: 32px; font-weight: 800; color: #1890ff; }

.position-badge {
  padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: 600;
}
.pos-leader { background: #ffd591; color: #ad6800; }
.pos-challenger { background: #91d5ff; color: #003a8c; }
.pos-nicher { background: #b7eb8f; color: #237804; }

.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }

.competitor-cards { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
.comp-card {
  border: 1px solid #f0f0f0; border-radius: 10px; padding: 14px;
  transition: box-shadow 0.2s;
}
.comp-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

.comp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.comp-name { font-size: 15px; font-weight: 600; color: var(--text-primary); }

.comp-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }
.metric { text-align: center; padding: 6px; background: var(--bg-base); border-radius: 6px; }
.m-label { display: block; font-size: 10.5px; color: var(--text-tertiary); }
.m-value { display: block; font-size: 14px; font-weight: 600; color: var(--text-primary); margin-top: 2px; }

.comp-swot { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.swot-col ul { margin: 4px 0 0; padding-left: 16px; font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); }
.swot-label { font-size: 11px; font-weight: 600; color: var(--text-tertiary); }

.insights-box { padding: 12px; background: var(--bg-elevated)7e6; border-radius: 8px; border: 1px solid #ffd591; }
.insights-box h4 { margin: 0 0 8px; font-size: 13px; color: #d46b08; }
.insights-box ul { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.8; color: var(--text-secondary); }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>
