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
  padding: 16px;
  background: var(--bg-elevated);
  border: 1px solid #e8e8e8;
  border-radius: 8px;
}

.strategy-overview {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; border-radius: 12px; margin-bottom: 16px;
}
.strat-aggressive { background: linear-gradient(135deg, #fff7e6, #ffe7ba); border: 1px solid #ffd591; }
.strat-balanced { background: linear-gradient(135deg, #e6f7ff, #d6e4ff); border: 1px solid #91d5ff; }
.strat-conservative { background: linear-gradient(135deg, #f6ffed, #d9f7be); border: 1px solid #b7eb8f; }

.overview-left { display: flex; flex-direction: column; gap: 2px; }
.strategy-label { font-size: 11.5px; color: #8c8c8c; }
.strategy-name { font-size: 18px; font-weight: 700; color: var(--text-primary); }
.overview-stats { display: flex; gap: 16px; font-size: 12px; color: #595959; }
.overview-stats .stat b { margin-left: 3px; color: var(--text-primary); }
.overview-stats .pos { color: #52c41a !important; }
.overview-stats .neg { color: #ff4d4f !important; }

.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border-base); }

.bid-section { margin-bottom: 14px; }
.section-header {
  display: flex; align-items: center; gap: 6px; padding: 8px 12px;
  border-radius: 8px 8px 0 0; font-size: 13px; font-weight: 600;
}
.header-increase { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; border-bottom: none; }
.header-decrease { background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; border-bottom: none; }

.change-up { color: #52c41a; font-weight: 600; }
.change-down { color: #ff4d4f; font-weight: 600; }
.priority-tag { border-radius: 10px; font-size: 11px; margin: 0; padding: 0 8px; }

.rationale-box { margin-top: 14px; padding: 12px; background: #fafafa; border-radius: 8px; }
.rationale-box h4 { margin: 0 0 6px; font-size: 13px; color: #595959; }
.rationale-box p { margin: 0; font-size: 12.5px; color: #8c8c8c; line-height: 1.6; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid var(--border-base); }

:deep(.row-increase) > td { background-color: #f6ffed !important; }
:deep(.row-decrease) > td { background-color: #fffbe6 !important; }
:deep(.ant-table) { background: transparent; }
:deep(.ant-table-thead > tr > th) { background: #fafafa; color: #595959; border-bottom-color: var(--border-base); }
:deep(.ant-table-tbody > tr > td) { border-bottom-color: var(--border-base); }

/* ====== 深色模式精调移至下方 <style> 块（scoped 内 :global() 嵌套会被 Vue 编译器丢弃） ====== */
</style>

<!-- ====== 深色模式精调（必须用非 scoped 块，整段选择器全局化；Vue scoped 内 :global() 嵌套会被编译器丢弃） ====== -->
<style>
html.dark .bid-optimize-result {
  background: #262626;
  border-color: #404040;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}
html.dark .bid-optimize-result .strat-aggressive {
  background: linear-gradient(135deg, rgba(250,173,20,0.16), rgba(250,173,20,0.05));
  border-color: rgba(250,173,20,0.4);
}
html.dark .bid-optimize-result .strat-balanced {
  background: linear-gradient(135deg, rgba(24,144,255,0.16), rgba(24,144,255,0.05));
  border-color: rgba(24,144,255,0.4);
}
html.dark .bid-optimize-result .strat-conservative {
  background: linear-gradient(135deg, rgba(82,196,26,0.16), rgba(82,196,26,0.05));
  border-color: rgba(82,196,26,0.4);
}
html.dark .bid-optimize-result .strategy-label { color: rgba(255, 255, 255, 0.55); }
html.dark .bid-optimize-result .strategy-name { color: rgba(255, 255, 255, 0.95); }
html.dark .bid-optimize-result .overview-stats { color: rgba(255, 255, 255, 0.7); }
html.dark .bid-optimize-result .overview-stats .stat b { color: rgba(255, 255, 255, 0.95); }
html.dark .bid-optimize-result .section-title { color: rgba(255, 255, 255, 0.95); }
html.dark .bid-optimize-result .header-increase {
  background: rgba(82,196,26,0.18);
  border-color: rgba(82,196,26,0.45);
  color: #73d13d;
}
html.dark .bid-optimize-result .header-decrease {
  background: rgba(255,77,79,0.18);
  border-color: rgba(255,77,79,0.45);
  color: #ff7875;
}
html.dark .bid-optimize-result .rationale-box {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
html.dark .bid-optimize-result .rationale-box h4 { color: rgba(255, 255, 255, 0.85); }
html.dark .bid-optimize-result .rationale-box p { color: rgba(255, 255, 255, 0.6); }
html.dark .bid-optimize-result .result-footer { border-top-color: rgba(255, 255, 255, 0.1); }
html.dark .bid-optimize-result .ant-table-thead > tr > th {
  background: rgba(255, 255, 255, 0.04) !important;
  color: rgba(255, 255, 255, 0.7) !important;
}
html.dark .bid-optimize-result .ant-table-tbody > tr > td {
  background: transparent !important;
  border-bottom-color: rgba(255, 255, 255, 0.06) !important;
  color: rgba(255, 255, 255, 0.85);
}
html.dark .bid-optimize-result .row-increase > td {
  background-color: rgba(82,196,26,0.08) !important;
}
html.dark .bid-optimize-result .row-decrease > td {
  background-color: rgba(250,173,20,0.08) !important;
}
</style>