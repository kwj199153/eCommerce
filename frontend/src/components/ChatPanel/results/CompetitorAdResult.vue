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
.competitor-ad-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

.sov-overview {
  display: flex; align-items: center; gap: var(--space-16);
  padding: var(--space-16) var(--space-20); background: linear-gradient(135deg, #f0f5ff, #d6e4ff);
  border-radius: var(--radius-12); margin-bottom: var(--space-16);
}
.sov-card { flex: 1; }
.sov-card .label { display: block; font-size: var(--font-size-12); color: var(--text-secondary); margin-bottom: var(--space-4); }
.sov-card .value { display: block; font-size: var(--font-size-32); font-weight: 800; color: var(--primary); }

.position-badge {
  padding: var(--space-8) var(--space-16); border-radius: var(--radius-20); font-size: var(--font-size-13); font-weight: 600;
}
.pos-leader { background: #ffd591; color: var(--warning); }
.pos-challenger { background: #91d5ff; color: #003a8c; }
.pos-nicher { background: #b7eb8f; color: #237804; }

.section-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-10); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }

.competitor-cards { display: flex; flex-direction: column; gap: var(--space-10); margin-bottom: var(--space-14); }
.comp-card {
  border: 1px solid var(--border-base); border-radius: var(--radius-10); padding: var(--space-14);
  transition: box-shadow 0.2s;
}
.comp-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

.comp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-10); }
.comp-name { font-size: var(--font-size-15); font-weight: 600; color: var(--text-primary); }

.comp-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-8); margin-bottom: var(--space-10); }
.metric { text-align: center; padding: var(--space-6); background: var(--bg-base); border-radius: var(--radius-6); }
.m-label { display: block; font-size: var(--font-size-10-5); color: var(--text-tertiary); }
.m-value { display: block; font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-top: var(--space-2); }

.comp-swot { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-12); }
.swot-col ul { margin: var(--space-4) 0 0; padding-left: var(--space-16); font-size: var(--font-size-11-5); line-height: 1.6; color: var(--text-secondary); }
.swot-label { font-size: var(--font-size-11); font-weight: 600; color: var(--text-tertiary); }

.insights-box { padding: var(--space-12); background: var(--orange-bg); border-radius: var(--radius-8); border: 1px solid var(--orange-border); }
.insights-box h4 { margin: 0 0 var(--space-8); font-size: var(--font-size-13); color: var(--orange-strong); }
.insights-box ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-12-5); line-height: 1.8; color: var(--text-secondary); }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
