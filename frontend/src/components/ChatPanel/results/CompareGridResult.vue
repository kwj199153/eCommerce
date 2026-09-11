<template>
  <div class="compare-grid-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>⚔️ 多维竞品对比</h3>
      <a-tag color="blue">{{ data.compared_count || 0 }} 个竞品</a-tag>
    </div>

    <!-- 竞品基本信息表 -->
    <a-table
      :dataSource="data.competitors"
      :columns="infoColumns"
      size="small"
      row-key="asin"
      :pagination="false"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'price'">
          <strong>${{ record.price }}</strong>
        </template>
        <template v-else-if="column.key === 'rating'">
          <span>{{ record.rating }} ⭐</span>
        </template>
        <template v-else-if="column.key === 'reviews'">
          {{ Number(record.reviews).toLocaleString() }}
        </template>
        <template v-else-if="column.key === 'bsr'">
          #{{ Number(record.bsr).toLocaleString() }}
        </template>
      </template>
    </a-table>

    <!-- 维度对比详情 -->
    <div v-if="data.comparison?.dimensions" class="dimensions-section">
      <h4>📊 各维度详细对比</h4>
      <div
        v-for="(dim, i) in data.comparison.dimensions"
        :key="i"
        class="dimension-card"
      >
        <h5>{{ dimLabel(dim.dimension) }}</h5>
        <div class="dim-bars">
          <div
            v-for="(v, j) in dim.values"
            :key="j"
            class="dim-bar-item"
          >
            <span class="bar-label">{{ v.asin || v.brand || '-' }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: barWidth(dim.dimension, v.value), background: j === dim.best_index ? '#1890ff' : '#bae7ff' }"
              ></div>
              <span class="bar-value">{{ formatValue(dim.dimension, v.value) }}</span>
            </div>
            <a-badge v-if="j === dim.best_index" status="success" />
          </div>
        </div>
      </div>
    </div>

    <!-- 性价比排名 -->
    <div v-if="data.comparison?.value_ranking" class="value-ranking">
      <h4>🏆 性价比综合排名</h4>
      <div class="rank-list">
        <div
          v-for="(item, i) in data.comparison.value_ranking"
          :key="item.asin"
          class="rank-row"
          :class="{ 'top1': i === 0, 'top2': i === 1, 'top3': i === 2 }"
        >
          <span class="rank-num">#{{ i + 1 }}</span>
          <span class="rank-brand">{{ item.brand }}</span>
          <a-progress
            :percent="item.value_score"
            size="small"
            :stroke-color="i === 0 ? '#faad14' : i === 1 ? '#d9d9d9' : i === 2 ? '#cd7f32' : '#1890ff'"
            :width="70"
          />
          <span class="rank-score">{{ item.value_score?.toFixed(0) }}分</span>
        </div>
      </div>
    </div>

    <!-- 差异化分析 -->
    <div v-if="data.comparison?.differentiation" class="diff-section">
      <h4>💡 差异化分析</h4>
      <div class="diff-stats">
        <div class="diff-stat">
          <span class="ds-label">价格跨度</span>
          <span class="ds-value">${{ data.comparison.differentiation.price_spread?.toFixed(2) }}</span>
        </div>
        <div class="diff-stat">
          <span class="ds-label">评分跨度</span>
          <span class="ds-value">{{ data.comparison.differentiation.rating_spread?.toFixed(1) }} ⭐</span>
        </div>
      </div>
      <div v-if="data.comparison.differentiation.gap_opportunities?.length" class="gap-box">
        <p><strong>市场空白机会：</strong></p>
        <ul>
          <li v-for="(g, i) in data.comparison.differentiation.gap_opportunities" :key="i">{{ g }}</li>
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

const infoColumns = [
  { title: 'ASIN', dataIndex: 'asin', key: 'asin', width: 115 },
  { title: '品牌', dataIndex: 'brand', key: 'brand', width: 110 },
  { title: '价格', key: 'price', width: 80 },
  { title: '评分', key: 'rating', width: 65 },
  { title: '评论数', key: 'reviews', width: 75 },
  { title: 'BSR', key: 'bsr', width: 85 },
]

const dimLabel = (d: string) => ({
  price: '💰 价格',
  rating: '⭐ 评分',
  reviews: '💬 评论数',
  bsr: '📊 BSR排名',
  value: '🎯 性价比',
}[d] || d)

const formatValue = (dim: string, val: any) => {
  if (dim === 'price') return `$${Number(val).toFixed(2)}`
  if (dim === 'rating') return `${val} ⭐`
  if (dim === 'reviews') return Number(val).toLocaleString()
  if (dim === 'bsr') return `#${Number(val).toLocaleString()}`
  return String(val)
}

const barWidth = (dim: string, val: any) => {
  const num = Number(val) || 0
  // BSR 排名是越低越好，需要反转
  if (dim === 'bsr') {
    const maxBsr = 50000
    return `${Math.min(100, Math.max(5, ((maxBsr - num) / maxBsr) * 100))}%`
  }
  // 价格：假设最大 $100
  if (dim === 'price') return `${Math.min(100, Math.max(5, (num / 100) * 100))}%`
  // 评论数：假设最大 20000
  if (dim === 'reviews') return `${Math.min(100, Math.max(5, (num / 20000) * 100))}%`
  // 评分/性价比：直接百分比
  return `${Math.min(100, Math.max(5, num))}%`
}
</script>

<style scoped>
.compare-grid-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.dimensions-section { margin-top: 18px; padding: 14px; background: var(--bg-base); border-radius: 8px; }
.dimensions-section h4 { margin: 0 0 12px; font-size: 13.5px; }
.dimension-card { margin-bottom: 16px; }
.dimension-card:last-child { margin-bottom: 0; }
.dimension-card h5 { margin: 0 0 10px; font-size: 13px; color: var(--text-primary); }
.dim-bars { display: flex; flex-direction: column; gap: 6px; }
.dim-bar-item { display: flex; align-items: center; gap: 8px; }
.bar-label { min-width: 90px; font-size: 11.5px; font-family: monospace; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { flex: 1; height: 20px; background: var(--bg-hover-light); border-radius: 4px; position: relative; min-width: 60px; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-value { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: 10.5px; font-weight: 600; white-space: nowrap; }
.value-ranking { margin-top: 18px; padding: 14px; background: var(--bg-elevated)be6; border-radius: 8px; }
.value-ranking h4 { margin: 0 0 10px; font-size: 13.5px; }
.rank-list { display: flex; flex-direction: column; gap: 6px; }
.rank-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: var(--bg-elevated); border-radius: 6px; }
.rank-row.top1 { background: linear-gradient(135deg, #fffbe6, #fff7e6); border: 1px solid #ffd666; }
.rank-row.top2 { background: var(--bg-base); border: 1px solid #e8e8e8; }
.rank-row.top3 { background: var(--bg-elevated)7e6; border: 1px solid #ffe7ba; }
.rank-num { font-weight: 700; font-size: 15px; min-width: 24px; }
.rank-row.top1 .rank-num { color: #d48806; }
.rank-row.top2 .rank-num { color: var(--text-tertiary); }
.rank-row.top3 .rank-num { color: #ad6800; }
.rank-brand { flex: 1; font-size: 13px; }
.rank-score { font-weight: 600; font-size: 12px; min-width: 40px; text-align: right; }
.diff-section { margin-top: 18px; padding: 14px; background: #f9f0ff; border-radius: 8px; }
.diff-section h4 { margin: 0 0 10px; font-size: 13.5px; }
.diff-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 10px; }
.diff-stat { text-align: center; padding: 10px; background: var(--bg-elevated); border-radius: 6px; }
.ds-label { display: block; font-size: 11px; color: var(--text-tertiary); }
.ds-value { font-size: 20px; font-weight: 700; color: #722ed1; }
.gap-box { font-size: 12.5px; line-height: 1.7; }
.gap-box p { margin: 0 0 4px; }
.gap-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
