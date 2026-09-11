<template>
  <div class="market-share-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>🌍 市场份额分析</h3>
      <a-tag color="blue">{{ data.category || '-' }}</a-tag>
    </div>

    <!-- 市场总览 -->
    <div class="market-overview">
      <div class="overview-stat">
        <span class="stat-label">预估市场规模</span>
        <span class="stat-value">${{ formatNumber(data.total_market_estimate) }}</span>
        <span class="stat-unit">/月</span>
      </div>
      <div class="overview-stat">
        <span class="stat-label">竞争品牌数</span>
        <span class="stat-value">{{ data.competitors?.length || 0 }}</span>
      </div>
      <div class="overview-stat">
        <span class="stat-label">市场格局</span>
        <a-tag :color="marketStructureColor">{{ marketStructureLabel }}</a-tag>
      </div>
    </div>

    <!-- 品牌份额表格 -->
    <a-table
      :dataSource="data.competitors"
      :columns="shareColumns"
      size="small"
      row-key="competitor_asin"
      :pagination="{ pageSize: 8 }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'share'">
          <div style="display: flex; align-items: center; gap: 8px;">
            <a-progress
              :percent="record.estimated_market_share"
              size="small"
              :stroke-color="shareColor(record.estimated_market_share)"
              :width="70"
              :show-info="false"
            />
            <strong>{{ record.estimated_market_share?.toFixed(1) }}%</strong>
          </div>
        </template>
        <template v-else-if="column.key === 'trend'">
          <a-tag :color="trendColor(record.trend)" style="font-size: 11px;">
            {{ trendLabel(record.trend) }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'revenue'">
          ${{ formatNumber(record.revenue_estimate) }}
        </template>
      </template>
    </a-table>

    <!-- 集中度指标 -->
    <div v-if="data.concentration_ratio" class="concentration-section">
      <h4>📊 市场集中度</h4>
      <div class="conc-grid">
        <div class="conc-item">
          <span class="conc-label">CR4（前4名份额）</span>
          <span class="conc-value">{{ data.concentration_ratio.cr4?.toFixed(1) }}%</span>
        </div>
        <div class="conc-item">
          <span class="conc-label">HHI 指数</span>
          <span class="conc-value">{{ data.concentration_ratio.hhi?.toFixed(0) }}</span>
          <span class="conc-hint">({{ hhiLevel(data.concentration_ratio.hhi) }})</span>
        </div>
      </div>
    </div>

    <!-- 洞察 -->
    <div v-if="data.insights?.length" class="insight-box">
      <p><strong>💡 市场洞察：</strong></p>
      <ul>
        <li v-for="(ins, i) in data.insights" :key="i">{{ ins }}</li>
      </ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const shareColumns = [
  { title: '品牌', dataIndex: 'brand_name', key: 'brand_name', width: 120 },
  { title: 'ASIN', dataIndex: 'competitor_asin', key: 'competitor_asin', width: 115 },
  { title: '市场份额', key: 'share', width: 180 },
  { title: 'BSR排名', dataIndex: 'bsr_rank', key: 'bsr_rank', width: 80 },
  { title: '月收入估算', key: 'revenue', width: 110 },
  { title: '趋势', key: 'trend', width: 80 },
]

const shareColor = (share: number) => {
  if (share >= 30) return '#cf1322'
  if (share >= 15) return '#fa8c16'
  if (share >= 5) return '#1890ff'
  return '#52c41a'
}

const trendColor = (t: string) => ({ rising: 'red', stable: 'blue', declining: 'green' }[t] || 'default')
const trendLabel = (t: string) => ({ rising: '上升 📈', stable: '稳定 ➡️', declining: '下降 📉' }[t] || t)

const marketStructureLabel = computed(() => {
  const cr4 = props.data.concentration_ratio?.cr4 || 0
  if (cr4 >= 75) return '高度集中（寡头）'
  if (cr4 >= 50) return '中度集中'
  if (cr4 >= 30) return '低度集中'
  return '充分竞争'
})

const marketStructureColor = computed(() => {
  const cr4 = props.data.concentration_ratio?.cr4 || 0
  if (cr4 >= 75) return 'red'
  if (cr4 >= 50) return 'orange'
  return 'green'
})

const hhiLevel = (hhi: number) => {
  if (!hhi) return '-'
  if (hhi > 2500) return '高度集中'
  if (hhi > 1500) return '中度集中'
  return '竞争充分'
}

const formatNumber = (n: number | undefined) => n ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '-'
</script>

<style scoped>
.market-share-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.market-overview { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 14px; }
.overview-stat { background: var(--bg-base); padding: 12px; border-radius: 8px; text-align: center; }
.stat-label { display: block; font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 700; color: #1890ff; }
.stat-unit { font-size: 11px; color: var(--text-tertiary); }
.concentration-section { margin-top: 18px; padding: 14px; background: #f9f0ff; border-radius: 8px; }
.concentration-section h4 { margin: 0 0 10px; font-size: 13px; }
.conc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.conc-item { text-align: center; }
.conc-label { display: block; font-size: 11px; color: var(--text-tertiary); }
.conc-value { font-size: 22px; font-weight: 700; color: #722ed1; }
.conc-hint { font-size: 11px; color: var(--text-tertiary); }
.insight-box { margin-top: 14px; padding: 12px; background: #f6ffed; border-radius: 8px; font-size: 12.5px; line-height: 1.7; }
.insight-box p { margin: 0 0 6px; }
.insight-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
