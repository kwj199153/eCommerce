<template>
  <div class="seo-diagnostic-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">📊</span>
        <div>
          <h3>Listing SEO 诊断报告</h3>
          <p class="subtitle">ASIN: {{ resultData.asin }} · 诊断时间: {{ resultData.diagnostic_time }}</p>
        </div>
      </div>
      <div class="header-actions">
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 总分仪表盘 -->
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
              <div class="score-grade" :class="getGradeClass(resultData.overall_score)">
                {{ getGrade(resultData.overall_score) }}
              </div>
            </div>
          </template>
        </a-progress>
      </div>
      <div class="score-details">
        <div class="detail-item" v-for="(dim, idx) in resultData.dimensions" :key="idx">
          <div class="detail-label">{{ dim.name }}</div>
          <a-progress
            :percent="dim.score"
            :stroke-color="getScoreColor(dim.score)"
            :show-info="true"
            size="small"
          />
          <div class="detail-status" :class="dim.status">
            {{ dim.status === 'good' ? '优秀' : dim.status === 'warn' ? '待改进' : '需优化' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 各维度详细诊断 -->
    <div class="dimension-cards">
      <a-tabs v-model:activeKey="activeTab" size="small">
        <a-tab-pane key="title" tab="📝 标题">
          <div class="dimension-detail">
            <div class="metric-row" v-for="(m, i) in resultData.title_metrics" :key="i">
              <span class="metric-name">{{ m.name }}</span>
              <span class="metric-value" :class="m.status">{{ m.value }}</span>
              <span class="metric-target">目标: {{ m.target }}</span>
            </div>
            <div class="improvement-box" v-if="resultData.title_improvements?.length">
              <h4>💡 改进建议</h4>
              <ul>
                <li v-for="(imp, i) in resultData.title_improvements" :key="i">{{ imp }}</li>
              </ul>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="bullets" tab="✨ 五点描述">
          <div class="dimension-detail">
            <div class="bullet-quality-grid">
              <div
                v-for="(bq, idx) in resultData.bullet_quality"
                :key="idx"
                class="quality-card"
                :class="bq.grade"
              >
                <div class="quality-num">{{ idx + 1 }}</div>
                <div class="quality-score">{{ bq.score }}/100</div>
                <div class="quality-issues" v-if="bq.issues?.length">
                  <span v-for="(issue, i) in bq.issues" :key="i" class="issue-tag">{{ issue }}</span>
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="images" tab="🖼️ 主图">
          <div class="dimension-detail">
            <div class="image-audit-grid">
              <div
                v-for="(img, idx) in resultData.image_audit"
                :key="idx"
                class="image-card"
              >
                <div class="image-placeholder">
                  <PictureOutlined style="font-size: 32px; color: var(--text-disabled)" />
                  <span>图 {{ idx + 1 }}</span>
                </div>
                <div class="image-score" :class="img.grade">
                  {{ img.score }}分
                </div>
                <div class="image-issues">
                  <div v-for="(issue, i) in img.issues" :key="i" class="issue-row">
                    <span :class="['issue-dot', issue.severity]"></span>
                    {{ issue.text }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="price" tab="💰 定价">
          <div class="dimension-detail">
            <div class="price-analysis">
              <div class="price-compare">
                <div class="price-item current">
                  <label>当前售价</label>
                  <span class="price-value">${{ resultData.price_analysis?.current_price }}</span>
                </div>
                <div class="price-item suggested">
                  <label>建议售价</label>
                  <span class="price-value">${{ resultData.price_analysis?.suggested_price }}</span>
                </div>
              </div>
              <div class="price-insights">
                <a-alert
                  :type="resultData.price_analysis?.action === 'raise' ? 'success' : resultData.price_analysis?.action === 'lower' ? 'warning' : 'info'"
                  :message="resultData.price_analysis?.insight"
                  show-icon
                />
              </div>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="reviews" tab="⭐ 评论">
          <div class="dimension-detail">
            <div class="review-summary">
              <div class="summary-stat">
                <div class="stat-value">{{ resultData.review_data?.avg_rating }}</div>
                <div class="stat-label">平均评分</div>
              </div>
              <div class="summary-stat">
                <div class="stat-value">{{ resultData.review_data?.total_reviews }}</div>
                <div class="stat-label">评论总数</div>
              </div>
              <div class="summary-stat">
                <div class="stat-value">{{ resultData.review_data?.rating_distribution?.[5] || 0 }}%</div>
                <div class="stat-label">五星占比</div>
              </div>
              <div class="summary-stat">
                <div class="stat-value" :class="resultData.review_data?.review_velocity === 'fast' ? 'positive' : 'negative'">
                  {{ resultData.review_data?.review_velocity === 'fast' ? '快' : '慢' }}
                </div>
                <div class="stat-label">增长速度</div>
              </div>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>

    <!-- 竞品对标 -->
    <div class="competitor-benchmark">
      <div class="benchmark-title">
        <TrophyOutlined /> 与 Top 3 竞品对比
      </div>
      <table class="benchmark-table">
        <thead>
          <tr>
            <th>维度</th>
            <th>您的Listing</th>
            <th v-for="(comp, idx) in resultData.competitors" :key="idx">{{ comp.name }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in resultData.benchmark_rows" :key="idx">
            <td class="row-label">{{ row.label }}</td>
            <td :class="['cell-value', row.your_status]">{{ row.your_value }}</td>
            <td v-for="(val, vi) in row.comp_values" :key="vi" class="cell-value">{{ val }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 行动计划 -->
    <div class="action-plan">
      <div class="plan-title">
        <RocketOutlined /> 优化行动计划
      </div>
      <a-timeline>
        <a-timeline-item
          v-for="(action, idx) in resultData.action_plan"
          :key="idx"
          :color="action.priority === 'high' ? 'red' : action.priority === 'medium' ? 'orange' : 'green'"
        >
          <div class="action-item">
            <strong>{{ action.title }}</strong>
            <p>{{ action.description }}</p>
            <a-tag :color="action.priority === 'high' ? 'red' : action.priority === 'medium' ? 'orange' : 'blue'" size="small">
              预计提升: +{{ action.estimated_lift }}%
            </a-tag>
          </div>
        </a-timeline-item>
      </a-timeline>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  CloseOutlined, PictureOutlined, TrophyOutlined, RocketOutlined,
} from '@ant-design/icons-vue'
import { ref } from 'vue'

const props = defineProps<{
  data: any
}>()

defineEmits<{
  (e: 'close'): void
}>()

const activeTab = ref('title')

const resultData = props.data || {
  asin: 'B0CXXXX001',
  diagnostic_time: new Date().toLocaleString('zh-CN'),
  overall_score: 72,
  dimensions: [
    { name: '标题 SEO', score: 78, status: 'warn' },
    { name: '图片质量', score: 65, status: 'warn' },
    { name: '定价竞争力', score: 82, status: 'good' },
    { name: '评论健康度', score: 70, status: 'warn' },
    { name: 'A+ 内容', score: 0, status: 'bad' },
    { name: '关键词覆盖', score: 75, status: 'warn' },
  ],
  title_metrics: [
    { name: '字符数', value: '156 / 200', target: '150-200', status: 'ok' },
    { name: '关键词密度', value: '3.2%', target: '2-4%', status: 'ok' },
    { name: '品牌位置', value: '末尾', target: '前部/末尾', status: 'warn' },
    { name: '核心词覆盖', value: '8 / 10', target: '≥9', status: 'warn' },
    { name: '可读性', value: '中等', target: '高', status: 'warn' },
  ],
  title_improvements: [
    '将品牌名移至标题开头以增强品牌曝光',
    '补充缺失的核心长尾词 "for small room"',
    '移除冗余修饰语 "premium quality"，节省 18 字符给更有价值的关键词',
  ],
  bullet_quality: [
    { score: 85, grade: 'good', issues: [] },
    { score: 72, grade: 'warn', issues: ['缺少数字量化'] },
    { score: 68, grade: 'warn', issues: ['情感触发不足'] },
    { score: 90, grade: 'good', issues: [] },
    { score: 55, grade: 'bad', issues: ['过于通用', '缺乏差异化'] },
  ],
  image_audit: [
    { score: 75, grade: 'warn', issues: [{ severity: 'warn', text: '背景不够纯净' }, { severity: 'info', text: '可增加场景图' }] },
    { score: 60, grade: 'bad', issues: [{ severity: 'error', text: '尺寸未占满 85%' }, { severity: 'warn', text: '信息图模糊' }] },
    { score: 70, grade: 'warn', issues: [{ severity: 'info', text: '缺少使用场景展示' }] },
    { score: 55, grade: 'bad', issues: [{ severity: 'error', text: '缺少尺寸对比图' }] },
    { score: 80, grade: 'good', issues: [{ severity: 'info', text: '整体不错' }] },
    { score: 65, grade: 'warn', issues: [{ severity: 'warn', text: '包装展示不清晰' }] },
    { score: 72, grade: 'warn', issues: [{ severity: 'info', text: '可增加 lifestyle 图' }] },
  ],
  price_analysis: {
    current_price: 24.99,
    suggested_price: 27.99,
    action: 'raise',
    insight: '当前定价低于竞品均价 $3.5，且利润率仅 28%。建议提价至 $27.99，预计销量下降 <5% 但利润增长 35%。',
  },
  review_data: {
    avg_rating: 4.3,
    total_reviews: 256,
    rating_distribution: { 5: 62, 4: 20, 3: 10, 2: 5, 1: 3 },
    review_velocity: 'normal',
  },
  competitors: [
    { name: '竞品 A' },
    { name: '竞品 B' },
    { name: '竞品 C' },
  ],
  benchmark_rows: [
    { label: '标题长度', your_value: '156字', your_status: 'ok', comp_values: ['165字', '148字', '172字'] },
    { label: '主图质量', your_value: '75分', your_status: 'warn', comp_values: ['88分', '82分', '79分'] },
    { label: '评论数', your_value: '256', your_status: 'ok', comp_values: ['1,240', '567', '89'] },
    { label: '评分', your_value: '4.3', your_status: 'ok', comp_values: ['4.5', '4.2', '4.1'] },
    { label: '价格', your_value: '$24.99', your_status: 'warn', comp_values: ['$29.99', '$26.99', '$22.99'] },
    { label: 'BSR 排名', your_value: '#2,340', your_status: 'warn', comp_values: ['#450', '#1,120', '#3,800'] },
  ],
  action_plan: [
    { priority: 'high', title: '优化主图质量', description: '重新拍摄白底主图，确保产品占比 85%+，分辨率 2000x2000+', estimated_lift: 15 },
    { priority: 'high', title: '完善第 5 点描述', description: '替换通用的售后说明为具体的使用场景和用户证言', estimated_lift: 10 },
    { priority: 'medium', title: '创建 A+ Content', description: '利用品牌故事模块和对比图表提升页面停留时间', estimated_lift: 20 },
    { priority: 'medium', title: '调整定价策略', description: '提价至 $27.99 并配合优惠券活动测试价格弹性', estimated_lift: 25 },
    { priority: 'low', title: '增加视频内容', description: '上传 30 秒产品演示视频到视频位', estimated_lift: 8 },
  ],
}

const getScoreColor = (score: number) => {
  if (score >= 80) return '#52c41a'
  if (score >= 60) return '#faad14'
  return '#ff4d4f'
}

const getGrade = (score: number) => {
  if (score >= 90) return 'A'
  if (score >= 80) return 'B'
  if (score >= 70) return 'C'
  if (score >= 60) return 'D'
  return 'F'
}

const getGradeClass = (score: number) => {
  if (score >= 80) return 'grade-good'
  if (score >= 60) return 'grade-warn'
  return 'grade-bad'
}
</script>

<style scoped>
.seo-diagnostic-result {
  background: var(--bg-elevated);
  border-radius: 8px;
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: #fff;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-icon { font-size: 28px; }
.header-info h3 { margin: 0; font-size: 16px; font-weight: 600; }
.subtitle { margin: 2px 0 0; font-size: 12px; opacity: 0.85; }

/* 分数仪表盘 */
.score-dashboard {
  display: flex;
  gap: 24px;
  padding: 24px 20px;
  background: var(--bg-base);
  border-bottom: 1px solid #f0f0f0;
  align-items: center;
}

.score-inner {
  text-align: center;
}

.score-number {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
}

.score-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.score-grade {
  font-size: 18px;
  font-weight: 700;
  margin-top: 2px;
}

.grade-good { color: #52c41a; }
.grade-warn { color: #faad14; }
.grade-bad { color: #ff4d4f; }

.score-details {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-label {
  width: 80px;
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.detail-item :deep(.ant-progress) {
  flex: 1;
  max-width: 200px;
}

.detail-status {
  width: 50px;
  font-size: 11px;
  font-weight: 600;
}

.detail-status.good { color: #52c41a; }
.detail-status.warn { color: #faad14; }
.detail-status.bad { color: #ff4d4f; }

/* 维度详情 */
.dimension-cards {
  padding: 0;
}

.dimension-detail {
  padding: 16px;
}

.metric-row {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px dashed #f0f0f0;
}

.metric-name {
  width: 100px;
  font-size: 13px;
  color: var(--text-secondary);
}

.metric-value {
  width: 120px;
  font-weight: 600;
  font-size: 13px;
}

.metric-value.ok { color: #52c41a; }
.metric-value.warn { color: #faad14; }
.metric-value.bad { color: #ff4d4f; }

.metric-target {
  font-size: 12px;
  color: var(--text-disabled);
}

.improvement-box {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg-elevated)be6;
  border-radius: 6px;
  border-left: 3px solid #faad14;
}

.improvement-box h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #d48806;
}

.improvement-box ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--text-secondary);
}

.improvement-box li {
  margin-bottom: 4px;
}

/* 五点质量 */
.bullet-quality-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}

.quality-card {
  background: var(--bg-base);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
  border-top: 3px solid #d9d9d9;
}

.quality-card.good { border-top-color: #52c41a; }
.quality-card.warn { border-top-color: #faad14; }
.quality-card.bad { border-top-color: #ff4d4f; }

.quality-num {
  width: 24px;
  height: 24px;
  line-height: 24px;
  background: var(--bg-hover-light);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  margin: 0 auto 8px;
}

.quality-score {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.quality-issues {
  margin-top: 8px;
}

.issue-tag {
  display: inline-block;
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-elevated)1f0;
  color: #cf1322;
  border-radius: 4px;
  margin: 2px;
}

/* 图片审核 */
.image-audit-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.image-card {
  background: var(--bg-base);
  border-radius: 8px;
  overflow: hidden;
}

.image-placeholder {
  aspect-ratio: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg-base);
  gap: 4px;
  color: var(--text-disabled);
  font-size: 11px;
}

.image-score {
  text-align: center;
  padding: 6px;
  font-weight: 700;
  font-size: 14px;
}

.image-score.good { background: #f6ffed; color: #52c41a; }
.image-score.warn { background: var(--bg-elevated)be6; color: #faad14; }
.image-score.bad { background: var(--bg-elevated)2f0; color: #ff4d4f; }

.image-issues {
  padding: 8px;
}

.issue-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 3px;
}

.issue-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.issue-dot.error { background: #ff4d4f; }
.issue-dot.warn { background: #faad14; }
.issue-dot.info { background: #1890ff; }

/* 价格分析 */
.price-compare {
  display: flex;
  gap: 24px;
  justify-content: center;
  margin-bottom: 16px;
}

.price-item {
  text-align: center;
  padding: 16px 24px;
  border-radius: 8px;
}

.price-item.current {
  background: var(--bg-elevated)1f0;
  border: 1px solid #ffa39e;
}

.price-item.suggested {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}

.price-item label {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}

.price-value {
  font-size: 28px;
  font-weight: 700;
}

.price-item.current .price-value { color: #cf1322; }
.price-item.suggested .price-value { color: #389e0d; }

/* 评论摘要 */
.review-summary {
  display: flex;
  justify-content: space-around;
  padding: 16px 0;
}

.summary-stat {
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.positive { color: #52c41a; }
.stat-value.negative { color: #ff4d4f; }

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

/* 竞品对标 */
.competitor-benchmark {
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
}

.benchmark-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.benchmark-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.benchmark-table th {
  background: var(--bg-base);
  padding: 8px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid #f0f0f0;
}

.benchmark-table td {
  padding: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.row-label {
  font-weight: 500;
  color: var(--text-primary);
}

.cell-value.ok { color: #52c41a; font-weight: 600; }
.cell-value.warn { color: #faad14; }

/* 行动计划 */
.action-plan {
  padding: 16px 20px;
  background: var(--bg-base);
}

.plan-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.action-item strong {
  font-size: 13px;
  color: var(--text-primary);
}

.action-item p {
  margin: 4px 0 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
