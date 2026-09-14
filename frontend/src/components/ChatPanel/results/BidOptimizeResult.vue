<template>
  <div class="bid-optimize-result" v-if="data">
    <!-- 策略概览 -->
    <div class="strategy-overview" :class="'strat-' + (data.strategy_type || 'balanced')">
      <div class="overview-left">
        <span class="strategy-label">出价策略</span>
        <span class="strategy-name">{{ strategyNameMap[data.strategy_type] || data.strategy_type }}</span>
      </div>
      <div class="overview-stats">
        <div class="stat">涉及关键词: <b>{{ data.total_keywords || 0 }}</b></div>
        <div class="stat">
          预算影响:
          <b :class="(data.budget_impact || 0) > 0 ? 'pos' : (data.budget_impact || 0) < 0 ? 'neg' : ''">
            {{ (data.budget_impact || 0) > 0 ? '+' : '' }}${{ Number(Math.abs(data.budget_impact || 0)).toFixed(2) }}/天
          </b>
        </div>
        <div class="stat">
          预期 ACoS:
          <b :class="(data.expected_acos_change || 0) < 0 ? 'pos' : 'neg'">
            {{ (data.expected_acos_change || 0) > 0 ? '+' : '' }}{{ Number(data.expected_acos_change || 0).toFixed(1) }}%
          </b>
        </div>
      </div>
    </div>

    <!-- 出价建议列表 -->
    <h4 class="section-title">💡 出价建议明细</h4>

    <!-- 提价列表 -->
    <div v-if="increaseList.length" class="bid-section">
      <div class="section-header header-increase">
        <ArrowUpOutlined /> 建议提价 ({{ increaseList.length }})
      </div>
      <a-table
        :dataSource="increaseList"
        :columns="bidColumns"
        :pagination="{ pageSize: 5, size: 'small' }"
        size="small"
        rowKey="keyword"
        :rowClassName="() => 'row-increase'"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'bid_change_pct'">
            <span class="change-up">+{{ Number(record.bid_change_pct).toFixed(0) }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'priority'">
            <a-tag :color="priorityColor(record.priority)" class="priority-tag">{{ priorityLabel(record.priority) }}</a-tag>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 降价列表 -->
    <div v-if="decreaseList.length" class="bid-section">
      <div class="section-header header-decrease">
        <ArrowDownOutlined /> 建议降价 ({{ decreaseList.length }})
      </div>
      <a-table
        :dataSource="decreaseList"
        :columns="bidColumns"
        :pagination="{ pageSize: 5, size: 'small' }"
        size="small"
        rowKey="keyword"
        :rowClassName="() => 'row-decrease'"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'bid_change_pct'">
            <span class="change-down">{{ Number(record.bid_change_pct).toFixed(0) }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'priority'">
            <a-tag :color="priorityColor(record.priority)" class="priority-tag">{{ priorityLabel(record.priority) }}</a-tag>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 策略依据 -->
    <div class="rationale-box">
      <h4>📋 调价依据</h4>
      <p>{{ data.rationale || '基于近30天转化数据、竞争强度、季节性因素综合计算' }}</p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons-vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const strategyNameMap: Record<string, string> = {
  aggressive: '激进型',
  balanced: '平衡型',
  conservative: '保守型',
}

const priorityColor = (p: string) => {
  return p === 'high' ? 'red' : p === 'medium' ? 'orange' : 'blue'
}
const priorityLabel = (p: string) => {
  return p === 'high' ? '高' : p === 'medium' ? '中' : '低'
}

const bidColumns = [
  { title: '关键词', dataIndex: 'keyword', width: 180, ellipsis: true },
  { title: '匹配', dataIndex: 'match_type', width: 60, align: 'center' },
  { title: '当前出价', dataIndex: 'current_bid', width: 85, align: 'right' },
  { title: '建议出价', dataIndex: 'suggested_bid', width: 85, align: 'right' },
  { title: '调整', dataIndex: 'bid_change_pct', width: 75, align: 'center' },
  { title: '优先级', dataIndex: 'priority', width: 75, align: 'center' },
  { title: '调价理由', dataIndex: 'reason', ellipsis: true },
]

// 表格列 customRender（金额列保留）
const columnRenderers = {
  current_bid: (text: any) => `$${Number(text).toFixed(2)}`,
  suggested_bid: (text: any) => `$${Number(text).toFixed(2)}`,
}

// 给 columns 注入自定义渲染（仅金额列，避免 <a-tag> 字符串化 bug）
bidColumns.forEach((col: any) => {
  if (col.dataIndex === 'current_bid') {
    col.customRender = ({ text }: any) => `$${Number(text).toFixed(2)}`
  } else if (col.dataIndex === 'suggested_bid') {
    col.customRender = ({ text }: any) => `$${Number(text).toFixed(2)}`
  }
})

const increaseList = computed(() => (props.data.recommendations || []).filter((r: any) => r.bid_change_pct > 0))
const decreaseList = computed(() => (props.data.recommendations || []).filter((r: any) => r.bid_change_pct <= 0))
</script>

<style scoped>
.bid-optimize-result {
  padding: var(--space-16);
  /* --bg-raised：比 --bg-elevated 再浮起一档的卡片底（深色下 #262626），
     box-shadow 走 --shadow-card（浅色 none / 深色有投影），替代原 styles/dark-overrides.css */
  background: var(--bg-raised);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  box-shadow: var(--shadow-card);
}

.strategy-overview {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-16) var(--space-20); border-radius: var(--radius-12); margin-bottom: var(--space-16);
}
.strat-aggressive { background: linear-gradient(135deg, var(--orange-bg), var(--orange-bg-2)); border: 1px solid var(--orange-border); }
.strat-balanced { background: linear-gradient(135deg, var(--info-bg), var(--info-bg-2)); border: 1px solid var(--info-border); }
.strat-conservative { background: linear-gradient(135deg, var(--success-bg), var(--success-bg-2)); border: 1px solid var(--success-border); }

.overview-left { display: flex; flex-direction: column; gap: var(--space-2); }
.strategy-label { font-size: var(--font-size-11-5); color: var(--text-tertiary); }
.strategy-name { font-size: var(--font-size-18); font-weight: 700; color: var(--text-primary); }
.overview-stats { display: flex; gap: var(--space-16); font-size: var(--font-size-12); color: var(--text-secondary); }
.overview-stats .stat b { margin-left: var(--space-3); color: var(--text-primary); }
.overview-stats .pos { color: var(--success) !important; }
.overview-stats .neg { color: var(--danger) !important; }

.section-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-10); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }

.bid-section { margin-bottom: var(--space-14); }
.section-header {
  display: flex; align-items: center; gap: var(--space-6); padding: var(--space-8) var(--space-12);
  border-radius: var(--radius-8) var(--radius-8) 0 0; font-size: var(--font-size-13); font-weight: 600;
}
.header-increase { background: var(--success-bg); color: var(--success); border: 1px solid var(--success-border); border-bottom: none; }
.header-decrease { background: var(--danger-bg); color: var(--danger-strong); border: 1px solid var(--danger-border-strong); border-bottom: none; }

.change-up { color: var(--success); font-weight: 600; }
.change-down { color: var(--danger); font-weight: 600; }
.priority-tag { border-radius: var(--radius-10); font-size: var(--font-size-11); margin: 0; padding: 0 var(--space-8); }

.rationale-box { margin-top: var(--space-14); padding: var(--space-12); background: var(--bg-base); border-radius: var(--radius-8); }
.rationale-box h4 { margin: 0 0 var(--space-6); font-size: var(--font-size-13); color: var(--text-secondary); }
.rationale-box p { margin: 0; font-size: var(--font-size-12-5); color: var(--text-tertiary); line-height: 1.6; }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }

:deep(.row-increase) > td { background-color: var(--success-bg) !important; }
:deep(.row-decrease) > td { background-color: var(--warning-bg) !important; }
:deep(.ant-table) { background: transparent; }
:deep(.ant-table-thead > tr > th) { background: var(--bg-base); color: var(--text-secondary); border-bottom-color: var(--border-base); }
:deep(.ant-table-tbody > tr > td) { border-bottom-color: var(--border-base); }

</style>
