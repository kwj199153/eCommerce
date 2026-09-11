<template>
  <div class="review-spy-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>🔎 竞品评论侦探</h3>
      <a-tag color="blue">{{ data.analyzed_products || 0 }} 个产品</a-tag>
    </div>

    <!-- 产品分析卡片 -->
    <div v-for="(product, idx) in data.analyses" :key="product.asin" class="product-card">
      <div class="product-header">
        <span class="brand-name">{{ product.brand }}</span>
        <span class="product-name">{{ product.product }}</span>
        <div class="rating-badge">
          <a-rate :value="Math.round(product.overall_rating)" disabled :count="5" style="font-size: 13px;" />
          <span>{{ product.overall_rating?.toFixed(1) }} ({{ product.total_reviews }})</span>
        </div>
      </div>

      <!-- 评论洞察 -->
      <div v-if="product.insights?.length" class="insights-grid">
        <div v-for="(ins, i) in product.insights.slice(0, 6)" :key="i" class="insight-item" :class="'sent-' + sentimentClass(ins.sentiment_score)">
          <span class="aspect-tag">{{ ins.aspect }}</span>
          <span class="topic-text">{{ ins.topic }}</span>
          <span class="sentiment-bar">
            <a-progress
              :percent="Math.round((ins.sentiment_score || 0.5) * 100)"
              size="small"
              :stroke-color="sentimentColor(ins.sentiment_score)"
              :width="50"
              :show-info="false"
            />
            <span style="font-size: 10px; margin-left: 4px;">{{ ins.mention_count }}次</span>
          </span>
        </div>
      </div>

      <!-- SWOT 分析 -->
      <div v-if="product.swot" class="swot-section">
        <h4>SWOT 分析</h4>
        <div class="swot-grid">
          <div class="swot-cell swot-s"><strong>优势</strong><ul><li v-for="(s, j) in product.swot.strengths?.slice(0,3)" :key="j">{{ s }}</li></ul></div>
          <div class="swot-cell swot-w"><strong>劣势</strong><ul><li v-for="(w, j) in product.swot.weaknesses?.slice(0,3)" :key="j">{{ w }}</li></ul></div>
          <div class="swot-cell swot-o"><strong>机会</strong><ul><li v-for="(o, j) in product.swot.opportunities?.slice(0,2)" :key="j">{{ o }}</li></ul></div>
          <div class="swot-cell swot-t"><strong>威胁</strong><ul><li v-for="(thr, j) in product.swot.threats?.slice(0,2)" :key="j">{{ thr }}</li></ul></div>
        </div>
      </div>

      <!-- 可行动情报 -->
      <div v-if="product.actionable_intelligence?.length" class="intel-box">
        <p><strong>🎯 可行动情报：</strong></p>
        <ul>
          <li v-for="(ai, j) in product.actionable_intelligence.slice(0, 4)" :key="j">{{ ai }}</li>
        </ul>
      </div>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const sentimentColor = (score: number) => {
  if (score >= 0.7) return '#52c41a'
  if (score >= 0.45) return '#faad14'
  return '#ff4d4f'
}

const sentimentClass = (score: number) => {
  if (score >= 0.7) return 'pos'
  if (score >= 0.45) return 'neu'
  return 'neg'
}
</script>

<style scoped>
.review-spy-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.product-card { padding: 14px; background: var(--bg-base); border-radius: 10px; margin-bottom: 12px; border: 1px solid #f0f0f0; }
.product-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.brand-name { font-weight: 600; color: #1890ff; }
.product-name { color: var(--text-secondary); font-size: 13px; }
.rating-badge { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-tertiary); }
.insights-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; margin-bottom: 12px; }
.insight-item { display: flex; align-items: center; gap: 6px; padding: 6px 8px; background: var(--bg-elevated); border-radius: 6px; font-size: 11.5px; }
.aspect-tag { background: #e6f7ff; color: #0958d9; padding: 1px 6px; border-radius: 4px; font-size: 10.5px; white-space: nowrap; }
.topic-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sentiment-bar { display: flex; align-items: center; flex-shrink: 0; }
.swot-section { margin-bottom: 10px; }
.swot-section h4 { margin: 0 0 8px; font-size: 13px; }
.swot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.swot-cell { padding: 10px; border-radius: 6px; font-size: 11.5px; line-height: 1.5; }
.swot-cell strong { display: block; margin-bottom: 4px; font-size: 12px; }
.swot-cell ul { margin: 0; padding-left: 16px; }
.swot-s { background: #f6ffed; border: 1px solid #b7eb8f; }
.swot-w { background: var(--bg-elevated)1f0; border: 1px solid #ffa39e; }
.swot-o { background: #e6f7ff; border: 1px solid #91d5ff; }
.swot-t { background: var(--bg-elevated)be6; border: 1px solid #ffe58f; }
.intel-box { padding: 10px; background: #fcffe6; border-radius: 6px; font-size: 12px; line-height: 1.6; }
.intel-box p { margin: 0 0 4px; }
.intel-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 4px; }
</style>
