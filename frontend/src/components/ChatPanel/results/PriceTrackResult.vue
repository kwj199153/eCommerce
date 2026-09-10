<template>
  <div class="price-track-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>📉 价格追踪报告</h3>
      <a-tag color="blue">{{ data.tracked_count || data.competitors?.length || 0 }} 个竞品</a-tag>
    </div>

    <!-- 对比矩阵表格 -->
    <a-table
      :dataSource="data.competitors"
      :columns="priceColumns"
      size="small"
      row-key="asin"
      :pagination="false"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'current_price'">
          <strong>${{ record.current_price?.toFixed(2) }}</strong>
        </template>
        <template v-else-if="column.key === 'price_change'">
          <span :style="{ color: (record.price_change_pct || 0) < 0 ? '#389e0d' : '#cf1322', fontWeight: 600 }">
            {{ (record.price_change_pct || 0) > 0 ? '+' : '' }}{{ record.price_change_pct?.toFixed(1) }}%
          </span>
        </template>
        <template v-else-if="column.key === 'rank_change'">
          <span :style="{ color: (record.rank_change || 0) > 0 ? '#cf1322' : '#389e0d' }">
            {{ (record.rank_change || 0) > 0 ? '+' : '' }}{{ record.rank_change }}
          </span>
        </template>
        <template v-else-if="column.key === 'score'">
          <a-progress
            :percent="record.competitiveness_score || 60"
            size="small"
            :stroke-color="(record.competitiveness_score || 60) >= 75 ? '#52c41a' : (record.competitiveness_score || 60) >= 50 ? '#faad14' : '#ff4d4f'"
            :width="56"
          />
        </template>
      </template>
    </a-table>

    <!-- 综合排名 -->
    <div v-if="data.comparison_matrix?.ranking" class="ranking-section">
      <h4>🏆 综合竞争力排名</h4>
      <div class="ranking-list">
        <div v-for="(item, i) in data.comparison_matrix.ranking" :key="item.asin" class="rank-item" :class="{ 'top3': i < 3 }">
          <span class="rank-num">#{{ i + 1 }}</span>
          <span class="rank-brand">{{ item.brand }}</span>
          <span class="rank-score">{{ item.score?.toFixed(1) }}</span>
        </div>
      </div>
    </div>

    <!-- 价格趋势提示 -->
    <div class="insight-box">
      <p><strong>💡 关键发现：</strong></p>
      <ul>
        <li v-for="(insight, i) in (data.insights || ['暂无洞察数据'])" :key="i">{{ insight }}</li>
      </ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const priceColumns = [
  { title: 'ASIN', dataIndex: 'asin', key: 'asin', width: 115 },
  { title: '品牌', dataIndex: 'brand', key: 'brand', width: 100 },
  { title: '当前价格', key: 'current_price', width: 90 },
  { title: '30天前价格', dataIndex: 'price_30d_ago', key: 'price_30d_ago', width: 95 },
  { title: '价格变动', key: 'price_change', width: 80 },
  { title: 'BSR变化', key: 'rank_change', width: 75 },
  { title: '竞争力', key: 'score', width: 80 },
]
</script>

<style scoped>
.price-track-result { padding: 16px; background: #fff; border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.ranking-section { margin-top: 18px; padding: 14px; background: #f6f8fa; border-radius: 8px; }
.ranking-section h4 { margin: 0 0 10px; font-size: 13px; }
.ranking-list { display: flex; flex-direction: column; gap: 6px; }
.rank-item { display: flex; align-items: center; gap: 10px; padding: 6px 10px; background: #fff; border-radius: 6px; }
.rank-item.top3 { background: #fffbe6; border: 1px solid #ffe58f; }
.rank-num { font-weight: 700; color: #1890ff; min-width: 28px; }
.rank-brand { flex: 1; font-size: 13px; }
.rank-score { font-weight: 600; color: #262626; }
.insight-box { margin-top: 14px; padding: 12px; background: #e6f7ff; border-radius: 8px; font-size: 12.5px; line-height: 1.7; }
.insight-box p { margin: 0 0 6px; }
.insight-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
