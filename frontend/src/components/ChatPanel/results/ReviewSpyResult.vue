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
          <a-rate :value="Math.round(product.overall_rating)" disabled :count="5" style="font-size: var(--font-size-13);" />
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
            <span style="font-size: var(--font-size-10); margin-left: var(--space-4);">{{ ins.mention_count }}次</span>
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
import { bandColor, bandOf } from '@/theme/bands'
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const sentimentColor = (score: number) => bandColor('sentiment', score)

const sentimentClass = (score: number) => bandOf('sentiment', score)
</script>

<style scoped>
.review-spy-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-14); }
.result-header h3 { margin: 0; font-size: var(--font-size-16); }
.product-card { padding: var(--space-14); background: var(--bg-base); border-radius: var(--radius-10); margin-bottom: var(--space-12); border: 1px solid var(--border-base); }
.product-header { display: flex; align-items: center; gap: var(--space-10); flex-wrap: wrap; margin-bottom: var(--space-10); }
.brand-name { font-weight: 600; color: var(--primary); }
.product-name { color: var(--text-secondary); font-size: var(--font-size-13); }
.rating-badge { display: flex; align-items: center; gap: var(--space-6); font-size: var(--font-size-12); color: var(--text-tertiary); }
.insights-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-8); margin-bottom: var(--space-12); }
.insight-item { display: flex; align-items: center; gap: var(--space-6); padding: var(--space-6) var(--space-8); background: var(--bg-elevated); border-radius: var(--radius-6); font-size: var(--font-size-11-5); }
.aspect-tag { background: var(--info-bg); color: var(--primary-strong); padding: var(--space-1) var(--space-6); border-radius: var(--radius-4); font-size: var(--font-size-10-5); white-space: nowrap; }
.topic-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sentiment-bar { display: flex; align-items: center; flex-shrink: 0; }
.swot-section { margin-bottom: var(--space-10); }
.swot-section h4 { margin: 0 0 var(--space-8); font-size: var(--font-size-13); }
.swot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-8); }
.swot-cell { padding: var(--space-10); border-radius: var(--radius-6); font-size: var(--font-size-11-5); line-height: 1.5; }
.swot-cell strong { display: block; margin-bottom: var(--space-4); font-size: var(--font-size-12); }
.swot-cell ul { margin: 0; padding-left: var(--space-16); }
.swot-s { background: var(--success-bg); border: 1px solid var(--success-border); }
.swot-w { background: var(--danger-bg); border: 1px solid var(--danger-border-strong); }
.swot-o { background: var(--info-bg); border: 1px solid var(--info-border); }
.swot-t { background: var(--warning-bg); border: 1px solid var(--warning-border); }
.intel-box { padding: var(--space-10); background: var(--success-bg); border-radius: var(--radius-6); font-size: var(--font-size-12); line-height: 1.6; }
.intel-box p { margin: 0 0 var(--space-4); }
.intel-box ul { margin: 0; padding-left: var(--space-18); }
.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); margin-top: var(--space-4); }
</style>
