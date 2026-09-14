<template>
  <div class="monitor-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>📊 竞品监控仪表盘</h3>
      <a-tag :color="data.total_competitors > 0 ? 'blue' : 'default'">
        {{ data.total_competitors }} 个竞品
      </a-tag>
    </div>

    <!-- 摘要 -->
    <div class="summary-card" v-if="data.summary">
      <p>{{ data.summary.overview || '监控概览' }}</p>
    </div>

    <!-- 竞品列表表格 -->
    <a-table
      :dataSource="data.competitors"
      :columns="competitorColumns"
      :pagination="{ pageSize: 8 }"
      size="small"
      row-key="asin"
      :row-class-name="(record: any) => record.alert_count > 0 ? 'alert-row' : ''"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'price'">
          <span :style="{ color: record.price_change < -3 ? 'var(--danger-strong)' : record.price_change > 3 ? 'var(--success)' : undefined, fontWeight: record.price_change !== 0 ? 600 : 400 }">
            ${{ record.price?.toFixed(2) }}
          </span>
          <span v-if="record.price_change !== 0" style="font-size: var(--font-size-11); margin-left: var(--space-4);" :class="record.price_change < 0 ? 'down' : 'up'">
            {{ record.price_change > 0 ? '+' : '' }}{{ record.price_change?.toFixed(1) }}%
          </span>
        </template>
        <template v-else-if="column.key === 'bsr_rank'">
          <span>{{ formatBSR(record.bsr_rank) }}</span>
        </template>
        <template v-else-if="column.key === 'stock_status'">
          <a-badge :status="stockStatusMap[record.stock_status]?.status || 'default'" :text="record.stock_status || '-'" />
        </template>
        <template v-else-if="column.key === 'health_score'">
          <a-progress
            :percent="record.health_score"
            size="small"
            :stroke-color="healthColor(record.health_score)"
            :width="60"
          />
        </template>
        <template v-else-if="column.key === 'alerts'">
          <a-tooltip v-if="record.alert_count > 0" :title="`${record.alert_count} 条警报`">
            <a-tag color="red">{{ record.alert_count }}</a-tag>
          </a-tooltip>
          <span v-else style="color: var(--text-disabled);">-</span>
        </template>
      </template>
    </a-table>

    <!-- 警报摘要 -->
    <div v-if="data.summary?.recent_alerts?.length" class="alert-section">
      <h4>🔔 近期警报</h4>
      <a-timeline>
        <a-timeline-item v-for="(alert, i) in data.summary.recent_alerts.slice(0, 5)" :key="i" :color="severityColor(alert.severity)">
          <strong>{{ alert.type === 'price_drop' ? '价格骤降' : alert.type === 'rank_jump' ? '排名突变' : alert.type === 'stock_out' ? '缺货' : alert.type }}</strong>
          — {{ alert.message }}
          <br><span style="font-size: 11px; color: var(--text-tertiary);">{{ alert.timestamp }}</span>
        </a-timeline-item>
      </a-timeline>
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

const competitorColumns = [
  { title: 'ASIN', dataIndex: 'asin', key: 'asin', width: 120 },
  { title: '品牌/标题', dataIndex: 'brand', key: 'brand', ellipsis: true },
  { title: '价格', key: 'price', width: 100 },
  { title: 'BSR', key: 'bsr_rank', width: 70 },
  { title: '评分', dataIndex: 'rating', key: 'rating', width: 55 },
  { title: '评论数', dataIndex: 'review_count', key: 'review_count', width: 65 },
  { title: '库存', key: 'stock_status', width: 80 },
  { title: '健康分', key: 'health_score', width: 90 },
  { title: '警报', key: 'alerts', width: 50 },
]

const stockStatusMap: Record<string, { status: string }> = {
  'In Stock': { status: 'success' },
  'Out of Stock': { status: 'error' },
  'Low Stock': { status: 'warning' },
}

/** 商品监控健康度 四档（与广告 Campaign 健康分是不同指标，见 bands.ts `monitorHealth`） */
const healthColor = (score: number) => bandColor('monitorHealth', score)

const severityColor = (s: string) => ({ critical: 'red', warning: 'orange', info: 'blue' }[s] || 'gray')

const formatBSR = (rank: number) => rank ? `#${rank.toLocaleString()}` : '-'
</script>

<style scoped>
.monitor-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-12); }
.result-header h3 { margin: 0; font-size: var(--font-size-16); }
.summary-card { background: var(--bg-base); padding: var(--space-12); border-radius: var(--radius-8); margin-bottom: var(--space-14); font-size: var(--font-size-13); line-height: 1.6; }
.alert-section { margin-top: var(--space-16); padding: var(--space-12); background: var(--warning-bg); border-radius: var(--radius-8); border: 1px solid var(--warning-border); }
.alert-section h4 { margin: 0 0 var(--space-10); font-size: var(--font-size-13); color: var(--orange-strong); }
.up { color: var(--danger-strong); }
.down { color: var(--success); }
:deep(.alert-row) { background-color: var(--danger-bg); }
.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); margin-top: var(--space-12); }
</style>
