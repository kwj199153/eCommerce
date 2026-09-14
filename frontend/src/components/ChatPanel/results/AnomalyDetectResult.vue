<template>
  <div class="anomaly-detect-result" v-if="data">
    <!-- 检测概览 -->
    <div class="detect-overview" :class="(data.alert_count || 0) > 0 ? 'has-alert' : 'clean'">
      <span class="overview-icon">{{ (data.alert_count || 0) > 0 ? '🚨' : '✅' }}</span>
      <div class="overview-text">
        <h3>{{ data.summary || '检测完成' }}</h3>
        <p class="period">检测周期: {{ data.check_period || '近7天' }}</p>
      </div>
      <div class="alert-count" v-if="(data.alert_count || 0) > 0">
        {{ data.alert_count }} 个高风险
      </div>
    </div>

    <!-- 异常列表 -->
    <div class="anomaly-list">
      <div
        v-for="(item, idx) in (data.anomalies || [])"
        :key="idx"
        class="anomaly-card"
        :class="'severity-' + (item.severity || 'medium')"
      >
        <div class="card-header">
          <a-tag :color="severityColor(item.severity)" class="severity-tag">
            {{ severityLabel(item.severity) }}
          </a-tag>
          <span class="anomaly-type">{{ typeMap[item.type] || item.type }}</span>
          <span class="campaign-name">{{ item.campaign }}</span>
          <span class="detect-time">{{ item.detected_at }}</span>
        </div>

        <div class="card-body">
          <div class="metric-row">
            <span class="m-label">指标</span>
            <span class="m-value">{{ item.metric }}</span>
            <span class="m-current">当前: {{ formatValue(item.metric, item.current_value) }}</span>
            <span class="m-expected">预期: {{ formatValue(item.metric, item.expected_value) }}</span>
            <span class="m-deviation" :class="item.deviation_pct > 0 ? 'up' : 'down'">
              {{ item.deviation_pct > 0 ? '+' : '' }}{{ item.deviation_pct?.toFixed(1) }}%
            </span>
          </div>

          <div class="cause-row">
            <span class="label">可能原因:</span> {{ item.possible_cause }}
          </div>
          <div class="action-row">
            <span class="label">建议操作:</span>
            <span class="action-text">{{ item.suggested_action }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 无异常提示 -->
    <div v-if="!(data.anomalies?.length)" class="no-anomaly">
      <CheckCircleOutlined style="font-size: var(--font-size-32); color: var(--success);" />
      <p>未发现明显异常，账户运行正常</p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const typeMap: Record<string, string> = {
  spend_spike: '花费突增',
  conversion_drop: '转化骤降',
  impression_anomaly: '展示异常',
  ctr_drop: 'CTR 波动',
}

const severityLabel = (s: string) => ({ high: '高风险', medium: '中风险', low: '低风险' }[s] || s)
const severityColor = (s: string) => ({ high: 'red', medium: 'orange', low: 'blue' }[s] || 'default')

const formatValue = (metric: string, val: number) => {
  if (metric.includes('率') || metric === 'CTR') return `${val}%`
  if (metric === '日花费' || metric === '周花费') return `$${val}`
  return String(val)
}
</script>

<script lang="ts">
import { CheckCircleOutlined } from '@ant-design/icons-vue'
</script>

<style scoped>
.anomaly-detect-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

.detect-overview {
  display: flex; align-items: center; gap: var(--space-14);
  padding: var(--space-14) var(--space-18); border-radius: var(--radius-10); margin-bottom: var(--space-14);
}
.detect-overview.has-alert { background: var(--danger-bg); border: 1px solid var(--danger-border-strong); }
.detect-overview.clean { background: var(--success-bg); border: 1px solid var(--success-border); }
.overview-icon { font-size: var(--font-size-28); }
.overview-text h3 { margin: 0; font-size: var(--font-size-14); color: var(--text-primary); }
.overview-text .period { margin: var(--space-2) 0 0; font-size: var(--font-size-11-5); color: var(--text-tertiary); }
.alert-count {
  margin-left: auto; padding: var(--space-4) var(--space-12); border-radius: var(--radius-12);
  background: var(--danger); color: #fff; font-size: var(--font-size-12); font-weight: 600;
}

.anomaly-list { display: flex; flex-direction: column; gap: var(--space-10); }
.anomaly-card {
  border: 1px solid var(--border-base); border-radius: var(--radius-10); overflow: hidden;
}
.anomaly-card.severity-high { border-color: var(--danger-border-strong); border-width: 1.5px; }
.anomaly-card.severity-medium { border-color: var(--orange-border); }
.anomaly-card.severity-low { border-color: var(--border-strong); }

.card-header {
  display: flex; align-items: center; gap: var(--space-8);
  padding: var(--space-8) var(--space-12); font-size: var(--font-size-11-5);
}
.severity-high .card-header { background: var(--danger-bg); }
.severity-medium .card-header { background: var(--warning-bg); }
.severity-low .card-header { background: var(--bg-base); }
.severity-tag { font-size: var(--font-size-10-5); border-radius: var(--radius-8); }
.anomaly-type { font-weight: 600; color: var(--text-primary); }
.campaign-name { color: var(--text-secondary); margin-left: auto; }
.detect-time { color: var(--text-disabled); font-size: var(--font-size-10-5); }

.card-body { padding: var(--space-10) var(--space-12); }
.metric-row { display: flex; align-items: center; gap: var(--space-8); font-size: var(--font-size-12); margin-bottom: var(--space-6); flex-wrap: wrap; }
.m-label { color: var(--text-tertiary); min-width: 32px; }
.m-value { font-weight: 600; color: var(--text-primary); }
.m-current { color: var(--text-secondary); }
.m-expected { color: var(--text-tertiary); text-decoration: line-through; }
.m-deviation { font-weight: 700; padding: var(--space-1) var(--space-6); border-radius: var(--radius-8); }
.m-deviation.up { background: var(--danger-bg); color: var(--danger); }
.m-deviation.down { background: var(--success-bg); color: var(--success); }

.cause-row, .action-row { font-size: var(--font-size-11-5); line-height: 1.6; margin-top: var(--space-4); }
.cause-row .label, .action-row .label { color: var(--text-tertiary); font-weight: 500; }
.action-row .action-text { color: var(--primary); cursor: pointer; }

.no-anomaly { text-align: center; padding: var(--space-30); color: var(--success); }
.no-anomaly p { margin: var(--space-10) 0 0; font-size: var(--font-size-14); }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
