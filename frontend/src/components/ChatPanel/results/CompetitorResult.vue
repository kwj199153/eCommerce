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
            :stroke-color="record.listing_quality_score >= 80 ? '#52c41a' : record.listing_quality_score >= 60 ? '#faad14' : '#ff4d4f'"
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
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  margin: 12px 16px;
}
.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px;
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: #fff;
}
.header-left { display: flex; gap: 8px; align-items: center; }
.result-icon { font-size: 18px; }
.result-title { font-weight: 600; }

.overview-bar {
  display: flex; gap: 20px; padding: 10px 16px;
  font-size: 12px; border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.conclusion {
  padding: 12px 16px; border-top: 1px solid #f0f0f0;
}
.conclusion-title { font-weight: 600; margin-bottom: 6px; }
.conclusion p { margin: 0; font-size: 12px; line-height: 1.6; color: #595959; }
</style>
