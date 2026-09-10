<template>
  <div class="profit-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">💰</span>
        <span class="result-title">利润测算结果</span>
        <a-tag :color="data.calculation?.roi >= 25 ? 'green' : data.calculation?.roi >= 15 ? 'orange' : 'red'">
          ROI {{ data.calculation?.roi || 0 }}%
        </a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- 核心指标 -->
    <div class="key-metrics">
      <div class="metric">
        <span class="metric-label">售价</span>
        <span class="metric-value price">${{ data.calculation?.selling_price || 0 }}</span>
      </div>
      <div class="metric-divider"></div>
      <div class="metric">
        <span class="metric-label">总成本</span>
        <span class="metric-value cost">${{ data.calculation?.total_cost || 0 }}</span>
      </div>
      <div class="metric-divider"></div>
      <div class="metric">
        <span class="metric-label">净利润</span>
        <span class="metric-value" :class="{ profit: data.calculation?.net_profit > 0 }">
          ${{ data.calculation?.net_profit || 0 }}
        </span>
      </div>
    </div>

    <!-- 费用明细 -->
    <div class="breakdown-section">
      <div class="section-title">📊 费用明细</div>
      <div class="breakdown-list">
        <div v-for="(item, i) in data.breakdown" :key="i" class="breakdown-item">
          <span>{{ item.item }}</span>
          <span>${{ item.amount }}</span>
        </div>
        <div class="breakdown-item total">
          <span>合计成本</span>
          <span>${{ data.calculation?.total_cost || 0 }}</span>
        </div>
      </div>
    </div>

    <!-- 利润率可视化 -->
    <div class="profit-visual">
      <div class="bar-container">
        <div class="bar cost-bar" :style="{ width: costPercent + '%' }"></div>
        <div class="bar profit-bar" :style="{ width: (100 - costPercent) + '%' }"></div>
      </div>
      <div class="bar-legend">
        <span><i class="dot cost-dot"></i> 成本 {{ costPercent }}%</span>
        <span><i class="dot profit-dot"></i> 利润 {{ 100 - costPercent }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const costPercent = computed(() => {
  if (!props.data.calculation?.selling_price) return 50
  return Math.round((props.data.calculation.total_cost / props.data.calculation.selling_price) * 100)
})
</script>

<style scoped>
.profit-result {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  margin: 12px 16px;
}
.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px;
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: #fff;
}
.header-left { display: flex; gap: 8px; align-items: center; }
.result-icon { font-size: 18px; }
.result-title { font-weight: 600; }

.key-metrics {
  display: flex; align-items: center; justify-content: center;
  gap: 20px; padding: 14px 16px; background: #fafafa;
}
.metric { text-align: center; }
.metric-label { font-size: 11px; color: #8c8c8c; }
.metric-value { font-size: 18px; font-weight: 700; color: #262626; display: block; margin-top: 2px; }
.metric-value.price { color: #1890ff; }
.metric-value.cost { color: #ff4d4f; }
.metric-value.profit { color: #52c41a !important; }
.metric-divider { width: 1px; height: 32px; background: #e8e8e8; }

.breakdown-section { padding: 12px 16px; border-top: 1px solid #f0f0f0; }
.section-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; }

.breakdown-list { font-size: 13px; }
.breakdown-item {
  display: flex; justify-content: space-between; padding: 5px 0;
  color: #595959;
}
.breakdown-item.total {
  border-top: 1px dashed #d9d9d9; margin-top: 6px; padding-top: 8px;
  font-weight: 600; color: #262626;
}

.profit-visual { padding: 12px 16px; }
.bar-container {
  display: flex; height: 20px; border-radius: 4px; overflow: hidden;
  background: #f0f0f0;
}
.bar { transition: width 0.3s ease; }
.cost-bar { background: #ff4d4f; }
.profit-bar { background: #52c41a; }

.bar-legend {
  display: flex; justify-content: center; gap: 20px; margin-top: 8px;
  font-size: 11px; color: #8c8c8c;
}
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.cost-dot { background: #ff4d4f; }
.profit-dot { background: #52c41a; }
</style>
