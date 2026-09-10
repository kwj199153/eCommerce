<template>
  <div class="sentiment-result" v-if="data">
    <!-- 情感概览 -->
    <div class="sentiment-overview" :class="'sent-' + (data.sentiment || 'neutral')">
      <div class="emotion-icon">{{ emotionIcon(data.sentiment) }}</div>
      <div class="emotion-info">
        <h3>{{ sentimentLabel(data.sentiment) }}</h3>
        <div class="confidence-bar">
          <span>置信度</span>
          <a-progress
            :percent="Math.round((data.confidence || 0) * 100)"
            :stroke-color="progressColor(data.sentiment)"
            size="small"
            style="width: 120px"
          />
        </div>
      </div>
    </div>

    <!-- 详细指标 -->
    <div class="metrics-row">
      <div class="metric-card">
        <span class="m-label">情感强度</span>
        <a-progress type="circle" :percent="Math.round((data.intensity || 0) * 100)" :width="56" :stroke-color="neutralColor" />
      </div>
      <div class="metric-card">
        <span class="m-label">升级风险</span>
        <a-tag :color="data.should_escalate ? 'red' : 'green'" style="font-size: 12px;">
          {{ data.should_escalate ? '需要转人工' : '无需升级' }}
        </a-tag>
        <p v-if="data.escalate_reason" class="reason-text">{{ data.escalate_reason }}</p>
      </div>
    </div>

    <!-- 关键情感词 -->
    <div v-if="data.key_emotions?.length" class="keywords-section">
      <h4>🔤 关键情感词</h4>
      <div class="keyword-tags">
        <a-tag v-for="(kw, i) in data.key_emotions" :key="i" :class="isNegative(kw) ? 'tag-neg' : 'tag-pos'">
          {{ kw }}
        </a-tag>
      </div>
    </div>

    <!-- 操作建议 -->
    <div class="action-suggestion" :class="data.should_escalate ? 'suggest-escalate' : 'suggest-normal'">
      <h4>💡 处理建议</h4>
      <p v-if="data.should_escalate">
        ⚠️ 检测到负面情绪较强，建议优先处理或升级给资深客服。客户可能需要人工介入。
      </p>
      <p v-else>
        ✅ 情绪状态正常，可继续使用自动回复处理。保持友好专业的语气。
      </p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const neutralColor = '#8c8c8c'

const sentimentLabel = (s: string) => ({
  positive: '😊 正面情绪',
  neutral: '😐 中性情绪',
  negative: '😟 负面情绪',
  angry: '😠 愤怒情绪',
}[s] || s)

const emotionIcon = (s: string) => ({
  positive: '😊', neutral: '😐', negative: '😟', angry: '😠',
}[s] || '❓')

const progressColor = (s: string) => ({
  positive: '#52c41a', neutral: '#faad14', negative: '#ff7a45', angry: '#ff4d4f',
}[s] || '#d9d9d9')

const isNegative = (w: string) => {
  const negatives = ['差', '烂', '垃圾', '失望', '生气', '愤怒', '投诉', '退款', 'bad', 'terrible', 'angry']
  return negatives.some(n => w.toLowerCase().includes(n.toLowerCase()))
}
</script>

<style scoped>
.sentiment-result { padding: 16px; background: #fff; border-radius: 8px; }

.sentiment-overview {
  display: flex; align-items: center; gap: 18px;
  padding: 20px; border-radius: 12px; margin-bottom: 14px;
}
.sent-positive { background: linear-gradient(135deg, #f6ffed, #e6fffb); border: 1px solid #b7eb8f; }
.sent-neutral { background: linear-gradient(135deg, #fafafa, #f5f5f5); border: 1px solid #d9d9d9; }
.sent-negative { background: linear-gradient(135deg, #fffbe6, #fff7e6); border: 1px solid #ffe58f; }
.sent-angry { background: linear-gradient(135deg, #fff1f0, #fff2f0); border: 1px solid #ffa39e; }

.emotion-icon { font-size: 48px; }
.emotion-info h3 { margin: 0 0 8px; font-size: 17px; color: #262626; }
.confidence-bar { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: #8c8c8c; }

.metrics-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
.metric-card {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 14px; background: #fafafa; border-radius: 10px;
}
.m-label { font-size: 11.5px; color: #8c8c8c; }
.reason-text { margin: 4px 0 0; font-size: 11px; color: #ff4d4f; text-align: center; line-height: 1.4; }

.keywords-section { margin-bottom: 14px; }
.keywords-section h4 { font-size: 13px; font-weight: 600; color: #262626; margin-bottom: 8px; }
.keyword-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-pos { background: #f6ffed !important; border-color: #b7eb8f !important; color: #389e0d !important; }
.tag-neg { background: #fff1f0 !important; border-color: #ffa39e !important; color: #cf1322 !important; }

.action-suggestion { padding: 14px; border-radius: 10px; }
.suggest-escalate { background: #fff1f0; border: 1px solid #ffa39e; }
.suggest-normal { background: #f6ffed; border: 1px solid #b7eb8f; }
.action-suggestion h4 { margin: 0 0 8px; font-size: 13px; }
.action-suggestion p { margin: 0; font-size: 12.5px; line-height: 1.6; color: #434343; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>
