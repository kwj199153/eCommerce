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
  if (severity === 'high') return '#ff4d4f'
  if (severity === 'medium') return '#faad14'
  return '#52c41a'
}

const getSeverityTagColor = (severity: string): string => {
  if (severity === 'high') return 'red'
  if (severity === 'medium') return 'orange'
  return 'green'
}
</script>

<style scoped>
.pain-point-result {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  margin: 12px 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: #fff;
}
.header-left { display: flex; gap: 8px; align-items: center; }
.result-icon { font-size: 18px; }
.result-title { font-weight: 600; }

.overview-cards {
  display: flex;
  gap: 1px;
  background: #f0f0f0;
}
.overview-card {
  flex: 1;
  text-align: center;
  padding: 10px;
  background: #fff;
}
.overview-card .card-value {
  font-size: 18px;
  font-weight: 700;
  color: #262626;
}
.overview-card.negative .card-value { color: #ff4d4f; }
.card-label { font-size: 11px; color: #8c8c8c; margin-top: 2px; }

.suggestions {
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}
.section-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.suggestion-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
  color: #595959;
}
</style>
