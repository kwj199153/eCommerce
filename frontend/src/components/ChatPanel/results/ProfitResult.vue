<template>
  <div class="profit-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">💰</span>
        <span class="result-title">利润测算结果</span>
        <a-tag :color="ROI_TAGS[bandIndex('roi', data.roi || 0)]">
          ROI {{ (data.roi ?? 0).toFixed(1) }}%
        </a-tag>
        <a-tag>{{ platformLabel }}</a-tag>
        <a-tag v-if="data.calculation_mode === 'reverse'">逆向定价</a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- 核心指标 -->
    <div class="key-metrics">
      <div class="metric">
        <span class="metric-label">{{ data.effective_discount_pct > 0 ? '成交价' : '售价' }}</span>
        <span class="metric-value price">{{ money(data.final_price) }}</span>
        <span v-if="data.effective_discount_pct > 0" class="metric-sub">
          标价 {{ money(data.listing_price) }} · 折扣 {{ (data.effective_discount_pct ?? 0).toFixed(1) }}%
        </span>
      </div>
      <div class="metric-divider"></div>
      <div class="metric">
        <span class="metric-label">总成本</span>
        <span class="metric-value cost">{{ money(data.total_cost) }}</span>
        <span class="metric-sub">占成交价 {{ costPercent }}%</span>
      </div>
      <div class="metric-divider"></div>
      <div class="metric">
        <span class="metric-label">净利润</span>
        <span class="metric-value" :class="{ profit: data.net_profit > 0 }">
          {{ money(data.net_profit) }}
        </span>
        <span class="metric-sub">毛利率 {{ (data.profit_margin_pct ?? 0).toFixed(1) }}%</span>
      </div>
    </div>

    <!-- 成本明细 -->
    <div class="breakdown-section">
      <div class="section-title">📊 成本明细</div>
      <div v-if="(data.fee_breakdown || []).length" class="breakdown-list">
        <div v-for="(item, i) in data.fee_breakdown" :key="i" class="breakdown-item">
          <span>{{ item.name }}</span>
          <span>{{ money(item.amount) }}</span>
        </div>
        <div class="breakdown-item total">
          <span>成本合计</span>
          <span>{{ money(data.total_cost) }}</span>
        </div>
      </div>
      <div v-else class="breakdown-empty">未获取到成本明细。</div>
    </div>

    <!-- 成本 / 利润 占成交价的可视化 -->
    <div v-if="data.final_price > 0" class="profit-visual">
      <div class="bar-container">
        <div class="bar cost-bar" :style="{ width: Math.min(100, costPercent) + '%' }"></div>
        <div class="bar profit-bar" :style="{ width: Math.max(0, 100 - costPercent) + '%' }"></div>
      </div>
      <div class="bar-legend">
        <span><i class="dot cost-dot"></i> 成本 {{ costPercent }}%</span>
        <span><i class="dot profit-dot"></i> 利润 {{ Math.max(0, 100 - costPercent) }}%</span>
      </div>
    </div>

    <div v-if="data.formula_summary" class="formula-note">{{ data.formula_summary }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'
import { bandIndex } from '@/theme/bands'

/** ROI 档位 → antd 预设标签色（阈值见 bands.ts `roi`） */
const ROI_TAGS = ['green', 'orange', 'red']

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

/** 数据来自后端 core/profit_engine.py 的 ProfitCalculationResult，与右栏预览是同一份 */
const data = computed(() => props.data || {})

const money = (v: any) => `$${(Number(v) || 0).toFixed(2)}`

const platformLabel = computed(() => {
  const p = String(data.value.platform || '').toLowerCase()
  const name = p === 'shopee' ? 'Shopee' : p === 'amazon' ? 'Amazon' : p || '—'
  return data.value.currency ? `${name} · ${data.value.currency}` : name
})

const costPercent = computed(() => {
  const price = Number(data.value.final_price) || 0
  if (!price) return 0
  return Math.round(((Number(data.value.total_cost) || 0) / price) * 100)
})
</script>

<style scoped>
.profit-result {
  background: var(--bg-elevated);
  border-radius: var(--radius-8);
  border: 1px solid var(--border-base);
  margin: var(--space-12) var(--space-16);
}
.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-10) var(--space-16);
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: #fff;
}
.header-left { display: flex; gap: var(--space-8); align-items: center; }
.result-icon { font-size: var(--font-size-18); }
.result-title { font-weight: 600; }

.key-metrics {
  display: flex; align-items: center; justify-content: center;
  gap: var(--space-20); padding: var(--space-14) var(--space-16); background: var(--bg-base);
}
.metric { text-align: center; }
.metric-label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.metric-value { font-size: var(--font-size-18); font-weight: 700; color: var(--text-primary); display: block; margin-top: var(--space-2); }
.metric-value.price { color: var(--primary); }
.metric-value.cost { color: var(--danger); }
.metric-value.profit { color: var(--success) !important; }
.metric-sub { display: block; margin-top: var(--space-2); font-size: var(--font-size-10); color: var(--text-tertiary); }
.metric-divider { width: 1px; height: 32px; background: var(--bg-hover-light); }

.breakdown-section { padding: var(--space-12) var(--space-16); border-top: 1px solid var(--border-base); }
.section-title { font-size: var(--font-size-13); font-weight: 600; margin-bottom: var(--space-10); }

.breakdown-list { font-size: var(--font-size-13); }
.breakdown-empty { font-size: var(--font-size-12); color: var(--text-tertiary); }
.breakdown-item {
  display: flex; justify-content: space-between; padding: var(--space-5) 0;
  color: var(--text-secondary);
}
.breakdown-item.total {
  border-top: 1px dashed var(--border-strong); margin-top: var(--space-6); padding-top: var(--space-8);
  font-weight: 600; color: var(--text-primary);
}

.profit-visual { padding: var(--space-12) var(--space-16); }
.bar-container {
  display: flex; height: 20px; border-radius: var(--radius-4); overflow: hidden;
  background: var(--bg-hover-light);
}
.bar { transition: width 0.3s ease; }
.cost-bar { background: var(--danger); }
.profit-bar { background: var(--success); }

.bar-legend {
  display: flex; justify-content: center; gap: var(--space-20); margin-top: var(--space-8);
  font-size: var(--font-size-11); color: var(--text-tertiary);
}
.dot { display: inline-block; width: 8px; height: 8px; border-radius: var(--radius-circle); margin-right: var(--space-4); }
.formula-note {
  padding: var(--space-8) var(--space-16) var(--space-12);
  border-top: 1px dashed var(--border-base);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1.6;
}
.cost-dot { background: var(--danger); }
.profit-dot { background: var(--success); }
</style>
