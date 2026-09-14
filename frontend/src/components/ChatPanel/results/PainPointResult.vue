<template>
  <div class="pain-point-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">🔍</span>
        <span class="result-title">痛点分析结果</span>
        <a-tag color="blue">{{ data.pain_points?.length || 0 }} 个痛点</a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- 概览卡片 -->
    <div class="overview-cards">
      <div class="overview-card">
        <div class="card-value">{{ data.total_reviews_analyzed }}</div>
        <div class="card-label">分析评论</div>
      </div>
      <div class="overview-card negative">
        <div class="card-value">{{ data.negative_review_count }}</div>
        <div class="card-label">差评数</div>
      </div>
      <div class="overview-card">
        <div class="card-value">{{ data.market_gap_score }}</div>
        <div class="card-label">市场空白分</div>
      </div>
    </div>

    <!-- 痛点排行表 -->
    <a-table
      :dataSource="data.pain_points"
      :columns="columns"
      size="small"
      :pagination="{ pageSize: 6, size: 'small' }"
      :scroll="{ y: 200 }"
      rowKey="pain_point"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'percentage'">
          <a-progress
            :percent="record.percentage"
            :stroke-color="getSeverityColor(record.severity)"
            size="small"
          />
        </template>
        <template v-else-if="column.key === 'severity'">
          <a-tag :color="getSeverityTagColor(record.severity)" size="small">
            {{ record.severity === 'high' ? '严重' : record.severity === 'medium' ? '中等' : '轻微' }}
          </a-tag>
        </template>
      </template>
    </a-table>

    <!-- 改进建议 -->
    <div v-if="data.improvement_suggestions?.length" class="suggestions">
      <div class="section-title">💡 改进建议</div>
      <ul class="suggestion-list">
        <li v-for="(s, i) in data.improvement_suggestions.slice(0, 4)" :key="i">{{ s }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { SEM } from '@/theme/semantic'
import { CloseOutlined } from '@ant-design/icons-vue'

defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const columns = [
  { title: '排名', width: 50, customRender: ({ index }: any) => index + 1 },
  { title: '痛点词', dataIndex: 'pain_point', key: 'pain_point', ellipsis: true },
  { title: '分类', dataIndex: 'category', key: 'category', width: 80 },
  { title: '提及次数', dataIndex: 'count', key: 'count', width: 70, align: 'center' },
  { title: '占比', dataIndex: 'percentage', key: 'percentage', width: 120 },
  { title: '程度', dataIndex: 'severity', key: 'severity', width: 65, align: 'center' },
]

const getSeverityColor = (severity: string): string => {
  if (severity === 'high') return SEM.danger
  if (severity === 'medium') return SEM.warning
  return SEM.success
}

const getSeverityTagColor = (severity: string): string => {
  if (severity === 'high') return 'red'
  if (severity === 'medium') return 'orange'
  return 'green'
}
</script>

<style scoped>
.pain-point-result {
  background: var(--bg-elevated);
  border-radius: var(--radius-8);
  border: 1px solid var(--border-base);
  margin: var(--space-12) var(--space-16);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-10) var(--space-16);
  background: linear-gradient(135deg, var(--accent-pink-2) 0%, var(--accent-pink) 100%);
  color: #fff;
}
.header-left { display: flex; gap: var(--space-8); align-items: center; }
.result-icon { font-size: var(--font-size-18); }
.result-title { font-weight: 600; }

.overview-cards {
  display: flex;
  gap: var(--space-1);
  background: var(--bg-hover-light);
}
.overview-card {
  flex: 1;
  text-align: center;
  padding: var(--space-10);
  background: var(--bg-elevated);
}
.overview-card .card-value {
  font-size: var(--font-size-18);
  font-weight: 700;
  color: var(--text-primary);
}
.overview-card.negative .card-value { color: var(--danger); }
.card-label { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); }

.suggestions {
  padding: var(--space-12) var(--space-16);
  border-top: 1px solid var(--border-base);
}
.section-title { font-size: var(--font-size-13); font-weight: 600; margin-bottom: var(--space-8); }
.suggestion-list {
  margin: 0;
  padding-left: var(--space-18);
  font-size: var(--font-size-12);
  line-height: 1.8;
  color: var(--text-secondary);
}
</style>
