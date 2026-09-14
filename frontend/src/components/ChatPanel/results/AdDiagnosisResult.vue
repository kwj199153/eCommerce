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
import { bandColor } from '@/theme/bands'
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
      // 红界 50 对齐后端 agent_ad.py:902 的 health_score < 50 告警阈值
      const color = bandColor('campaignHealth', score)
      return `<span style="color:${color};font-weight:600">${score}</span>`
    }
  },
]

// ⚠️ 此处曾遗留 `const campaignTableData = (props) => props.data?.campaigns || []`，
//    它在 <script setup> 里遮蔽了下方 Options API 的同名 computed，
//    导致 <a-table :dataSource> 收到**函数**而非数组 → 渲染期 TypeError。
//    已删除，统一由下方 computed 提供数据。
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
.ad-diagnosis-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

/* 评分头部 */
.score-header {
  display: flex; align-items: center; gap: var(--space-20);
  padding: var(--space-20); border-radius: var(--radius-12); margin-bottom: var(--space-16);
}
.score-header.grade-A { background: linear-gradient(135deg, var(--success-bg), var(--success-bg-2)); border: 1px solid var(--success-border); }
.score-header.grade-B { background: linear-gradient(135deg, #e6f7ff, #bae7ff); border: 1px solid var(--info-border); }
.score-header.grade-C { background: linear-gradient(135deg, var(--warning-bg), var(--warning-border)); border: 1px solid var(--orange-border); }
.score-header.grade-D, .score-header.grade-F { background: linear-gradient(135deg, var(--danger-bg), var(--danger-border)); border: 1px solid var(--danger-border-strong); }

.score-circle {
  width: 80px; height: 80px; border-radius: var(--radius-circle);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: var(--bg-elevated); box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.score-value { font-size: var(--font-size-28); font-weight: 700; color: var(--text-primary); line-height: 1; }
.grade-label { font-size: var(--font-size-18); font-weight: 800; margin-top: var(--space-2); }
.grade-A .grade-label { color: var(--success); }
.grade-B .grade-label { color: var(--primary); }
.grade-C .grade-label { color: var(--warning); }
.grade-D .grade-label, .grade-F .grade-label { color: var(--danger); }

.score-info h3 { margin: 0 0 var(--space-6); font-size: var(--font-size-16); color: var(--text-primary); }
.score-info .summary { margin: 0; font-size: var(--font-size-13); color: var(--text-secondary); line-height: 1.5; }

/* 指标卡片 */
.metrics-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--space-10); margin-bottom: var(--space-16); }
.metric-card {
  padding: var(--space-12) var(--space-8); border-radius: var(--radius-8); text-align: center;
  border: 1px solid var(--border-base); transition: all 0.2s;
}
.metric-card.status-good { border-color: var(--success-border); background: var(--bg-base); }
.metric-card.status-warning { border-color: var(--orange-border); background: var(--warning-bg); }
.metric-card.status-critical { border-color: var(--danger-border-strong); background: var(--danger-bg); }

.metric-name { display: block; font-size: var(--font-size-11-5); color: var(--text-tertiary); margin-bottom: var(--space-4); }
.metric-value { display: block; font-size: var(--font-size-17); font-weight: 700; color: var(--text-primary); }
.benchmark { display: block; font-size: var(--font-size-10); color: var(--text-disabled); margin-top: var(--space-2); }
.change { display: inline-block; font-size: var(--font-size-10); margin-top: var(--space-3); padding: var(--space-1) var(--space-6); border-radius: var(--radius-8); }
.change.up { background: var(--success-bg); color: var(--success); }
.change.down { background: var(--danger-bg); color: var(--danger); }

/* 区块 */
.section-block { margin-bottom: var(--space-16); }
.section-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-10); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }

/* 问题列表 */
.issue-list { display: flex; flex-direction: column; gap: var(--space-8); }
.issue-item {
  display: flex; align-items: center; gap: var(--space-10);
  padding: var(--space-10) var(--space-12); border-radius: var(--radius-8); border: 1px solid var(--border-base);
}
.issue-item.priority-high { background: var(--danger-bg); border-color: var(--danger-border-strong); }
.issue-item.priority-medium { background: var(--warning-bg); border-color: var(--warning-border); }
.issue-item.priority-low { background: var(--success-bg); border-color: var(--success-border); }

.issue-rank {
  width: 22px; height: 22px; border-radius: var(--radius-circle);
  display: flex; align-items: center; justify-content: center;
  font-size: var(--font-size-11); font-weight: 600; background: var(--bg-hover-light); color: var(--text-secondary); flex-shrink: 0;
}
.issue-content { flex: 1; min-width: 0; }
.issue-title { display: block; font-size: var(--font-size-13); font-weight: 500; color: var(--text-primary); }
.issue-desc { display: block; font-size: var(--font-size-11-5); color: var(--text-tertiary); margin-top: var(--space-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 建议列表 */
.rec-list { margin: 0; padding-left: var(--space-20); font-size: var(--font-size-13); line-height: 1.9; color: var(--text-secondary); }
.rec-list li::marker { content: '✅ '; }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
