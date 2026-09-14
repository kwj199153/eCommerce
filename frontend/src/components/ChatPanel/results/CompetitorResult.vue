<template>
  <div class="competitor-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">⚔️</span>
        <span class="result-title">竞品对比结果</span>
        <a-tag color="blue">{{ data.competitors?.length || 0 }} 个竞品</a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- 概览 -->
    <div class="overview-bar">
      <span>💰 ${{ data.price_range?.min || 0 }} - ${{ data.price_range?.max || 0 }}</span>
      <span>⭐ {{ data.avg_rating?.toFixed(1) || '-' }}</span>
      <span>👑 {{ leaderBrand }}</span>
    </div>

    <!-- 对比表格 -->
    <a-table
      :dataSource="data.competitors"
      :columns="columns"
      size="small"
      :pagination="false"
      :scroll="{ y: 220 }"
      rowKey="asin"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'price_positioning'">
          <a-tag :color="getPositionColor(record.price_positioning)" size="small">
            {{ getPositionLabel(record.price_positioning) }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'listing_quality_score'">
          <a-progress
            :percent="record.listing_quality_score"
            :stroke-color="bandColor('score', record.listing_quality_score)"
            size="small"
          />
        </template>
      </template>
    </a-table>

    <!-- 结论 -->
    <div v-if="data.recommendation" class="conclusion">
      <div class="conclusion-title">📋 分析结论</div>
      <p>{{ data.recommendation }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { bandColor } from '@/theme/bands'
import { computed } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const columns = [
  { title: '商品', dataIndex: 'title', key: 'title', ellipsis: true },
  { title: '价格', dataIndex: 'price', key: 'price', width: 65, align: 'right' },
  { title: '评分', dataIndex: 'rating', key: 'rating', width: 50, align: 'center' },
  { title: '评论', dataIndex: 'review_count', key: 'review_count', width: 55, align: 'center' },
  { title: 'Listing质量', dataIndex: 'listing_quality_score', key: 'listing_quality_score', width: 100 },
  { title: '定位', dataIndex: 'price_positioning', key: 'price_positioning', width: 75, align: 'center' },
]

const leaderBrand = computed(() => {
  const leader = props.data.competitors?.find((c: any) => c.asin === props.data.market_leader)
  return leader?.brand || '-'
})

const getPositionColor = (pos: string): string => {
  if (pos === 'premium') return 'red'
  if (pos === 'mid-range') return 'blue'
  return 'green'
}

const getPositionLabel = (pos: string): string => {
  if (pos === 'premium') return '高端'
  if (pos === 'mid-range') return '中端'
  return '平价'
}
</script>

<style scoped>
.competitor-result {
  background: var(--bg-elevated);
  border-radius: var(--radius-8);
  border: 1px solid var(--border-base);
  margin: var(--space-12) var(--space-16);
}
.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-10) var(--space-16);
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: #fff;
}
.header-left { display: flex; gap: var(--space-8); align-items: center; }
.result-icon { font-size: var(--font-size-18); }
.result-title { font-weight: 600; }

.overview-bar {
  display: flex; gap: var(--space-20); padding: var(--space-10) var(--space-16);
  font-size: var(--font-size-12); border-bottom: 1px solid var(--border-base);
  background: var(--bg-base);
}

.conclusion {
  padding: var(--space-12) var(--space-16); border-top: 1px solid var(--border-base);
}
.conclusion-title { font-weight: 600; margin-bottom: var(--space-6); }
.conclusion p { margin: 0; font-size: var(--font-size-12); line-height: 1.6; color: var(--text-secondary); }
</style>
