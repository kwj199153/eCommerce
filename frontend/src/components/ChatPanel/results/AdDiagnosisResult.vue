<template>
  <div class="ad-diagnosis-result" v-if="data">
    <!-- 综合评分头部 -->
    <div class="score-header" :class="'grade-' + (data.grade || 'C')">
      <div class="score-circle">
        <span class="score-value">{{ data.overall_score || 0 }}</span>
        <span class="grade-label">{{ data.grade || '?' }}</span>
      </div>
      <div class="score-info">
        <h3>广告账户健康诊断</h3>
        <p class="summary">{{ data.summary || '诊断完成' }}</p>
      </div>
    </div>

    <!-- 核心指标卡片 -->
    <div class="metrics-grid">
      <div
        v-for="(metric, idx) in (data.metrics || [])"
        :key="idx"
        class="metric-card"
        :class="'status-' + (metric.status || 'normal')"
      >
        <span class="metric-name">{{ metric.name }}</span>
        <span class="metric-value">
          {{ metric.unit === '%' ? metric.value?.toFixed(1) + '%' : metric.unit === '$' ? '$' + metric.value?.toFixed(2) : metric.unit === 'x' ? metric.value?.toFixed(2) + 'x' : metric.value?.toFixed(2) + '%' }}
        </span>
        <span class="benchmark">基准: {{ metric.unit === '%' ? metric.benchmark?.toFixed(1) + '%' : metric.unit === 'x' ? metric.benchmark?.toFixed(2) + 'x' : '$' + metric.benchmark?.toFixed(2) }}</span>
        <span class="change" :class="metric.change_pct > 0 ? 'up' : 'down'">
          {{ metric.change_pct > 0 ? '↑' : '↓' }} {{ Math.abs(metric.change_pct)?.toFixed(1) }}%
        </span>
      </div>
    </div>

    <!-- Campaign 健康表 -->
    <div class="section-block">
      <h4 class="section-title">📊 Campaign 健康状态</h4>
      <a-table
        :dataSource="campaignTableData"
        :columns="campaignColumns"
        :pagination="false"
        size="small"
        :scroll="{ x: 700 }"
        rowKey="campaign_name"
      />
    </div>

    <!-- 问题列表 -->
    <div class="section-block" v-if="data.top_issues?.length">
      <h4 class="section-title">⚠️ 主要问题 (Top {{ data.top_issues.length }})</h4>
      <div class="issue-list">
        <div
          v-for="(issue, idx) in data.top_issues"
          :key="idx"
          class="issue-item"
          :class="'priority-' + (issue.priority || 'medium')"
        >
          <span class="issue-rank">{{ idx + 1 }}</span>
          <div class="issue-content">
            <span class="issue-title">{{ issue.title }}</span>
            <span class="issue-desc">{{ issue.description }}</span>
          </div>
          <a-tag :color="priorityColor(issue.priority)">{{ issue.priority }}</a-tag>
        </div>
      </div>
    </div>

    <!-- 优化建议 -->
    <div class="section-block" v-if="data.recommendations?.length">
      <h4 class="section-title">💡 优化建议</h4>
      <ul class="rec-list">
        <li v-for="(rec, idx) in data.recommendations" :key="idx">{{ rec }}</li>
      </ul>
    </div>

    <!-- 关闭按钮 -->
    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭报告</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  data: any
}>()

defineEmits<{
  (e: 'close'): void
}>()

const campaignColumns = [
  { title: 'Campaign', dataIndex: 'campaign_name', width: 160, ellipsis: true },
  { title: '类型', dataIndex: 'campaign_type', width: 50, align: 'center' },
  { title: '花费', dataIndex: 'spend', width: 70, align: 'right', customRender: ({ text }: { text: any }) => `$${Number(text).toFixed(0)}` },
  { title: 'RoAS', dataIndex: 'roas', width: 55, align: 'right', customRender: ({ text }: { text: any }) => Number(text).toFixed(1) },
  { title: 'ACoS', dataIndex: 'acos', width: 55, align: 'right', customRender: ({ text }: { text: any }) => `${Number(text).toFixed(0)}%` },
  { title: 'CTR', dataIndex: 'ctr', width: 50, align: 'right', customRender: ({ text }: { text: any }) => `${Number(text).toFixed(2)}%` },
  { title: '健康分', dataIndex: 'health_score', width: 60, align: 'center',
    customRender: ({ text }: { text: any }) => {
      const score = Number(text)
      const color = score >= 80 ? '#52c41a' : score >= 60 ? '#faad14' : '#ff4d4f'
      return `<span style="color:${color};font-weight:600">${score}</span>`
    }
  },
]

// 计算属性需要用 computed，这里简化为方法调用
const campaignTableData = (props: any) => props.data?.campaigns || []

const priorityColor = (p: string) => {
  return p === 'high' ? 'red' : p === 'medium' ? 'orange' : 'blue'
}
</script>

<script lang="ts">
export default {
  computed: {
    campaignTableData() {
      return (this as any).data?.campaigns || []
    }
  }
}
</script>

<style scoped>
.ad-diagnosis-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }

/* 评分头部 */
.score-header {
  display: flex; align-items: center; gap: 20px;
  padding: 20px; border-radius: 12px; margin-bottom: 16px;
}
.score-header.grade-A { background: linear-gradient(135deg, #f6ffed, #d9f7be); border: 1px solid #b7eb8f; }
.score-header.grade-B { background: linear-gradient(135deg, #e6f7ff, #bae7ff); border: 1px solid #91d5ff; }
.score-header.grade-C { background: linear-gradient(135deg, #fffbe6, #ffe58f); border: 1px solid #ffd591; }
.score-header.grade-D, .score-header.grade-F { background: linear-gradient(135deg, #fff2f0, #ffccc7); border: 1px solid #ffa39e; }

.score-circle {
  width: 80px; height: 80px; border-radius: 50%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: var(--bg-elevated); box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.score-value { font-size: 28px; font-weight: 700; color: var(--text-primary); line-height: 1; }
.grade-label { font-size: 18px; font-weight: 800; margin-top: 2px; }
.grade-A .grade-label { color: #52c41a; }
.grade-B .grade-label { color: #1890ff; }
.grade-C .grade-label { color: #faad14; }
.grade-D .grade-label, .grade-F .grade-label { color: #ff4d4f; }

.score-info h3 { margin: 0 0 6px; font-size: 16px; color: var(--text-primary); }
.score-info .summary { margin: 0; font-size: 13px; color: var(--text-secondary); line-height: 1.5; }

/* 指标卡片 */
.metrics-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; }
.metric-card {
  padding: 12px 8px; border-radius: 8px; text-align: center;
  border: 1px solid #f0f0f0; transition: all 0.2s;
}
.metric-card.status-good { border-color: #b7eb8f; background: var(--bg-base); }
.metric-card.status-warning { border-color: #ffd591; background: var(--bg-elevated)beb; }
.metric-card.status-critical { border-color: #ffa39e; background: var(--bg-elevated)1f0; }

.metric-name { display: block; font-size: 11.5px; color: var(--text-tertiary); margin-bottom: 4px; }
.metric-value { display: block; font-size: 17px; font-weight: 700; color: var(--text-primary); }
.benchmark { display: block; font-size: 10px; color: var(--text-disabled); margin-top: 2px; }
.change { display: inline-block; font-size: 10px; margin-top: 3px; padding: 1px 6px; border-radius: 8px; }
.change.up { background: #f6ffed; color: #52c41a; }
.change.down { background: var(--bg-elevated)1f0; color: #ff4d4f; }

/* 区块 */
.section-block { margin-bottom: 16px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }

/* 问题列表 */
.issue-list { display: flex; flex-direction: column; gap: 8px; }
.issue-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px; border: 1px solid #f0f0f0;
}
.issue-item.priority-high { background: var(--bg-elevated)1f0; border-color: #ffa39e; }
.issue-item.priority-medium { background: var(--bg-elevated)be6; border-color: #ffe58f; }
.issue-item.priority-low { background: #f6ffed; border-color: #b7eb8f; }

.issue-rank {
  width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; background: var(--bg-hover-light); color: var(--text-secondary); flex-shrink: 0;
}
.issue-content { flex: 1; min-width: 0; }
.issue-title { display: block; font-size: 13px; font-weight: 500; color: var(--text-primary); }
.issue-desc { display: block; font-size: 11.5px; color: var(--text-tertiary); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 建议列表 */
.rec-list { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.9; color: var(--text-secondary); }
.rec-list li::marker { content: '✅ '; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>
