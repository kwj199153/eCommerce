<template>
  <div class="seo-diagnostic-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">📊</span>
        <div>
          <h3>Listing SEO 诊断报告</h3>
          <p class="subtitle">对当前 Listing 文本的 SEO 诊断（后端真实分析结果）</p>
        </div>
      </div>
      <div class="header-actions">
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 总分仪表盘 + 各维度得分 -->
    <div class="score-dashboard">
      <div class="main-score-ring">
        <a-progress
          type="circle"
          :percent="resultData.overall_score"
          :stroke-color="getScoreColor(resultData.overall_score)"
          :width="140"
        >
          <template #format>
            <div class="score-inner">
              <div class="score-number">{{ resultData.overall_score }}</div>
              <div class="score-label">综合评分</div>
              <div class="score-grade" :class="gradeClass">
                {{ resultData.grade || gradeOf(resultData.overall_score) }}
              </div>
            </div>
          </template>
        </a-progress>
      </div>
      <div class="score-details">
        <div class="detail-item" v-for="dim in resultData.dimensions" :key="dim.key">
          <div class="detail-label">{{ dim.name }}</div>
          <a-progress
            :percent="dim.score"
            :stroke-color="getScoreColor(dim.score)"
            :show-info="true"
            size="small"
          />
        </div>
        <a-empty v-if="!resultData.dimensions?.length" description="后端未返回分维度评分" />
      </div>
    </div>

    <!-- 检查项清单（后端 checklist 真值：通过 / 未通过） -->
    <div class="dimension-cards" v-if="resultData.checklist?.length">
      <div class="benchmark-title">
        <CheckCircleOutlined /> SEO 检查项
        <span class="check-summary">
          {{ resultData.passed_count }} / {{ resultData.total_count }} 通过
        </span>
      </div>
      <div class="check-list">
        <div
          v-for="(c, i) in resultData.checklist"
          :key="i"
          class="check-item"
          :class="c.passed ? 'ok' : 'bad'"
        >
          <span class="check-mark">{{ c.passed ? '✓' : '✗' }}</span>
          <span class="check-text">{{ c.item }}</span>
        </div>
      </div>
    </div>

    <!-- 待改进项（后端 improvement_areas 真值） -->
    <div class="improvement-box" v-if="resultData.improvement_areas?.length">
      <h4>💡 待改进项</h4>
      <ul>
        <li v-for="(imp, i) in resultData.improvement_areas" :key="i">{{ imp }}</li>
      </ul>
    </div>

    <div class="improvement-box" v-if="!resultData.improvement_areas?.length && !resultData.checklist?.length">
      <a-empty description="后端本次未返回检查项与改进建议" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { bandColor, bandOf } from '@/theme/bands'
import { CloseOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'

const props = defineProps<{
  data: any
}>()

defineEmits<{
  (e: 'close'): void
}>()

// ★ 不再提供硬编码 fallback：没有真实结果就显式空着，
//   让「后端没给」这件事可见，而不是拿本地样张把它盖住。
const resultData = computed<any>(() => props.data || {})

/** 总分 / 各维度配色（通用 0–100 口径，唯一真源在 theme/bands.ts） */
const getScoreColor = (score: number) => bandColor('score', score)

/** 等级 A–F —— 与后端 `listing_generator._calculate_grade` 同源 */
const gradeOf = (score: number) => bandOf('grade', score)

/** 头部配色档（A/B/C/D-F） */
const gradeClass = computed(() => {
  const g = String(resultData.value.grade || gradeOf(resultData.value.overall_score || 0))
  if (g === 'A') return 'excellent'
  if (g === 'B') return 'good'
  if (g === 'C') return 'fair'
  return 'poor'
})
</script>

<style scoped>
.seo-diagnostic-result {
  background: var(--bg-elevated);
  border-radius: var(--radius-8);
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-16) var(--space-20);
  border-bottom: 1px solid var(--border-base);
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: #fff;
}

.header-info {
  display: flex;
  align-items: center;
  gap: var(--space-12);
}

.result-icon { font-size: var(--font-size-28); }
.header-info h3 { margin: 0; font-size: var(--font-size-16); font-weight: 600; }
.subtitle { margin: var(--space-2) 0 0; font-size: var(--font-size-12); opacity: 0.85; }

/* 分数仪表盘 */
.score-dashboard {
  display: flex;
  gap: var(--space-24);
  padding: var(--space-24) var(--space-20);
  background: var(--bg-base);
  border-bottom: 1px solid var(--border-base);
  align-items: center;
}

.score-inner {
  text-align: center;
}

.score-number {
  font-size: var(--font-size-36);
  font-weight: 700;
  color: var(--text-primary);
}

.score-label {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.score-grade {
  font-size: var(--font-size-18);
  font-weight: 700;
  margin-top: var(--space-2);
}

.grade-good { color: var(--success); }
.grade-warn { color: var(--warning); }
.grade-bad { color: var(--danger); }

.score-details {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.detail-item {
  display: flex;
  align-items: center;
  gap: var(--space-10);
}

.detail-label {
  width: 80px;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  font-weight: 500;
}

.detail-item :deep(.ant-progress) {
  flex: 1;
  max-width: 200px;
}

.detail-status {
  width: 50px;
  font-size: var(--font-size-11);
  font-weight: 600;
}

.detail-status.good { color: var(--success); }
.detail-status.warn { color: var(--warning); }
.detail-status.bad { color: var(--danger); }

/* 维度详情 */
.dimension-cards {
  padding: 0;
}

.dimension-detail {
  padding: var(--space-16);
}

.metric-row {
  display: flex;
  align-items: center;
  padding: var(--space-8) 0;
  border-bottom: 1px dashed var(--border-base);
}

.metric-name {
  width: 100px;
  font-size: var(--font-size-13);
  color: var(--text-secondary);
}

.metric-value {
  width: 120px;
  font-weight: 600;
  font-size: var(--font-size-13);
}

.metric-value.ok { color: var(--success); }
.metric-value.warn { color: var(--warning); }
.metric-value.bad { color: var(--danger); }

.metric-target {
  font-size: var(--font-size-12);
  color: var(--text-disabled);
}

.improvement-box {
  margin-top: var(--space-16);
  padding: var(--space-12);
  background: var(--warning-bg);
  border-radius: var(--radius-6);
  border-left: 3px solid var(--warning);
}

.improvement-box h4 {
  margin: 0 0 var(--space-8);
  font-size: var(--font-size-13);
  color: var(--warning-strong);
}

.improvement-box ul {
  margin: 0;
  padding-left: var(--space-18);
  font-size: var(--font-size-13);
  color: var(--text-secondary);
}

.improvement-box li {
  margin-bottom: var(--space-4);
}

/* 五点质量 */
.bullet-quality-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-10);
}

.quality-card {
  background: var(--bg-base);
  border-radius: var(--radius-8);
  padding: var(--space-12);
  text-align: center;
  border-top: 3px solid var(--border-strong);
}

.quality-card.good { border-top-color: var(--success); }
.quality-card.warn { border-top-color: var(--warning); }
.quality-card.bad { border-top-color: var(--danger); }

.quality-num {
  width: 24px;
  height: 24px;
  line-height: 24px;
  background: var(--bg-hover-light);
  border-radius: var(--radius-circle);
  font-size: var(--font-size-12);
  font-weight: 700;
  margin: 0 auto var(--space-8);
}

.quality-score {
  font-size: var(--font-size-20);
  font-weight: 700;
  color: var(--text-primary);
}

.quality-issues {
  margin-top: var(--space-8);
}

.issue-tag {
  display: inline-block;
  font-size: var(--font-size-10);
  padding: var(--space-2) var(--space-6);
  background: var(--danger-bg);
  color: var(--danger-strong);
  border-radius: var(--radius-4);
  margin: var(--space-2);
}

/* 图片审核 */
.image-audit-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-12);
}

.image-card {
  background: var(--bg-base);
  border-radius: var(--radius-8);
  overflow: hidden;
}

.image-placeholder {
  aspect-ratio: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg-base);
  gap: var(--space-4);
  color: var(--text-disabled);
  font-size: var(--font-size-11);
}

.image-score {
  text-align: center;
  padding: var(--space-6);
  font-weight: 700;
  font-size: var(--font-size-14);
}

.image-score.good { background: var(--success-bg); color: var(--success); }
.image-score.warn { background: var(--warning-bg); color: var(--warning); }
.image-score.bad { background: var(--danger-bg); color: var(--danger); }

.image-issues {
  padding: var(--space-8);
}

.issue-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}

.issue-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-circle);
  flex-shrink: 0;
}

.issue-dot.error { background: var(--danger); }
.issue-dot.warn { background: var(--warning); }
.issue-dot.info { background: var(--primary); }

/* 价格分析 */
.price-compare {
  display: flex;
  gap: var(--space-24);
  justify-content: center;
  margin-bottom: var(--space-16);
}

.price-item {
  text-align: center;
  padding: var(--space-16) var(--space-24);
  border-radius: var(--radius-8);
}

.price-item.current {
  background: var(--danger-bg);
  border: 1px solid var(--danger-border-strong);
}

.price-item.suggested {
  background: var(--success-bg);
  border: 1px solid var(--success-border);
}

.price-item label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
  margin-bottom: var(--space-6);
}

.price-value {
  font-size: var(--font-size-28);
  font-weight: 700;
}

.price-item.current .price-value { color: var(--danger-strong); }
.price-item.suggested .price-value { color: var(--success); }

/* 评论摘要 */
.review-summary {
  display: flex;
  justify-content: space-around;
  padding: var(--space-16) 0;
}

.summary-stat {
  text-align: center;
}

.stat-value {
  font-size: var(--font-size-24);
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.positive { color: var(--success); }
.stat-value.negative { color: var(--danger); }

.stat-label {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
  margin-top: var(--space-4);
}

/* 竞品对标 */
.competitor-benchmark {
  padding: var(--space-16) var(--space-20);
  border-top: 1px solid var(--border-base);
}

.benchmark-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-12);
}

.benchmark-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-12);
}

.benchmark-table th {
  background: var(--bg-base);
  padding: var(--space-8);
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid var(--border-base);
}

.benchmark-table td {
  padding: var(--space-8);
  border-bottom: 1px solid var(--border-base);
}

.row-label {
  font-weight: 500;
  color: var(--text-primary);
}

.cell-value.ok { color: var(--success); font-weight: 600; }
.cell-value.warn { color: var(--warning); }

/* 行动计划 */
.action-plan {
  padding: var(--space-16) var(--space-20);
  background: var(--bg-base);
}

.plan-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-12);
}

.action-item strong {
  font-size: var(--font-size-13);
  color: var(--text-primary);
}

.action-item p {
  margin: var(--space-4) 0 var(--space-8);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}

/* ====== P0-2 批 1：后端真值区块（检查项清单）====== */
.benchmark-title .check-summary { font-weight: 400; color: var(--text-tertiary); font-size: var(--font-size-12); margin-left: var(--space-6); }
.check-list { display: flex; flex-direction: column; gap: var(--space-6); }
.check-item {
  display: flex; align-items: flex-start; gap: var(--space-8);
  padding: var(--space-8) var(--space-12);
  border-radius: var(--radius-8); border: 1px solid var(--border-base);
  font-size: var(--font-size-13);
}
.check-item.ok { background: var(--success-bg); border-color: var(--success-border); }
.check-item.bad { background: var(--danger-bg); border-color: var(--danger-border-strong); }
.check-mark { font-weight: 700; flex-shrink: 0; }
.check-item.ok .check-mark { color: var(--success); }
.check-item.bad .check-mark { color: var(--danger); }
.check-text { color: var(--text-primary); word-break: break-word; }
</style>
