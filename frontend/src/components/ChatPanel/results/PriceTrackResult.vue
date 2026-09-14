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
          <span :style="{ color: (record.price_change_pct || 0) < 0 ? 'var(--success)' : 'var(--danger-strong)', fontWeight: 600 }">
            {{ (record.price_change_pct || 0) > 0 ? '+' : '' }}{{ record.price_change_pct?.toFixed(1) }}%
          </span>
        </template>
        <template v-else-if="column.key === 'rank_change'">
          <span :style="{ color: (record.rank_change || 0) > 0 ? 'var(--danger-strong)' : 'var(--success)' }">
            {{ (record.rank_change || 0) > 0 ? '+' : '' }}{{ record.rank_change }}
          </span>
        </template>
        <template v-else-if="column.key === 'score'">
          <a-progress
            :percent="record.competitiveness_score || 60"
            size="small"
            :stroke-color="bandColor('competitiveness', record.competitiveness_score || 60)"
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
import { bandColor } from '@/theme/bands'
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
.price-track-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-14); }
.result-header h3 { margin: 0; font-size: var(--font-size-16); }
.ranking-section { margin-top: var(--space-18); padding: var(--space-14); background: var(--bg-base); border-radius: var(--radius-8); }
.ranking-section h4 { margin: 0 0 var(--space-10); font-size: var(--font-size-13); }
.ranking-list { display: flex; flex-direction: column; gap: var(--space-6); }
.rank-item { display: flex; align-items: center; gap: var(--space-10); padding: var(--space-6) var(--space-10); background: var(--bg-elevated); border-radius: var(--radius-6); }
.rank-item.top3 { background: var(--warning-bg); border: 1px solid var(--warning-border); }
.rank-num { font-weight: 700; color: var(--primary); min-width: 28px; }
.rank-brand { flex: 1; font-size: var(--font-size-13); }
.rank-score { font-weight: 600; color: var(--text-primary); }
.insight-box { margin-top: var(--space-14); padding: var(--space-12); background: var(--info-bg); border-radius: var(--radius-8); font-size: var(--font-size-12-5); line-height: 1.7; }
.insight-box p { margin: 0 0 var(--space-6); }
.insight-box ul { margin: 0; padding-left: var(--space-18); }
.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); margin-top: var(--space-12); }
</style>
