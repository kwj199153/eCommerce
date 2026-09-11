<template>
  <!-- ===== 对比结果 ===== -->
  <div class="result-section">
    <!-- 结果概览 -->
    <div class="overview-bar">
      <div class="overview-stat">
        <span class="stat-label">对比竞品</span>
        <span class="stat-value">{{ result.competitors.length }} 个</span>
      </div>
      <div class="overview-stat">
        <span class="stat-label">价格区间</span>
        <span class="stat-value">${{ result.price_range.min }} - ${{ result.price_range.max }}</span>
      </div>
      <div class="overview-stat">
        <span class="stat-label">平均评分</span>
        <span class="stat-value">{{ result.avg_rating.toFixed(1) }} ⭐</span>
      </div>
      <div class="overview-stat highlight">
        <span class="stat-label">市场领导者</span>
        <span class="stat-value leader">{{ marketLeaderName }}</span>
      </div>
    </div>

    <!-- 对比矩阵表格 -->
    <div class="section-block">
      <div class="section-header">
        <span class="section-title"><TableOutlined /> 竞品对比矩阵</span>
        <a-space>
          <a-radio-group v-model:value="viewMode" size="small" button-style="solid">
            <a-radio-button value="table">表格视图</a-radio-button>
            <a-radio-button value="card">卡片视图</a-radio-button>
          </a-radio-group>
        </a-space>
      </div>

      <!-- 表格视图 -->
      <a-table
        v-if="viewMode === 'table'"
        :dataSource="result.competitors"
        :columns="compareColumns"
        :pagination="false"
        size="small"
        row-key="asin"
        :row-class-name="(record: MockCompetitor) => record.asin === result.market_leader ? 'row-leader' : ''"
      >
        <template #bodyCell="{ column, record }">
          <!-- 商品信息 -->
          <template v-if="column.dataIndex === 'title'">
            <div class="product-cell">
              <div class="product-brand">{{ record.brand }}</div>
              <div class="product-title-text">{{ record.title.slice(0, 45) }}...</div>
              <a-tag v-if="record.asin === result.market_leader" color="gold" size="small">👑 领导者</a-tag>
            </div>
          </template>

          <!-- 价格 + 定位 -->
          <template v-else-if="column.dataIndex === 'price'">
            <div class="price-cell">
              <span class="price-value">${{ record.price }}</span>
              <a-tag :color="getPositionColor(record.price_positioning)" size="small">
                {{ getPositionLabel(record.price_positioning) }}
              </a-tag>
            </div>
          </template>

          <!-- 评分 -->
          <template v-else-if="column.dataIndex === 'rating'">
            <div class="rating-cell">
              <a-rate :value="Math.round(record.rating)" disabled size="small" />
              <span class="rating-num">{{ record.rating.toFixed(1) }}</span>
            </div>
          </template>

          <!-- Listing 质量 -->
          <template v-else-if="column.dataIndex === 'listing_quality_score'">
            <div class="score-cell">
              <a-progress
                type="circle"
                :percent="record.listing_quality_score"
                :width="44"
                :stroke-color="getScoreColor(record.listing_quality_score)"
                size="small"
              />
            </div>
          </template>

          <!-- BSR 排名 -->
          <template v-else-if="column.dataIndex === 'bsr_rank'">
            <span :class="{'bsr-good': record.bsr_rank < 5000, 'bsr-bad': record.bsr_rank > 20000}">
              #{{ record.bsr_rank.toLocaleString() }}
            </span>
          </template>

          <!-- 优劣势 -->
          <template v-else-if="column.dataIndex === 'swot'">
            <div class="swot-cell">
              <div class="swot-strengths">
                <CaretUpOutlined style="color: #52c41a" />
                <span v-for="s in record.strengths.slice(0, 2)" :key="s" class="swot-item good">{{ s }}</span>
              </div>
              <div class="swot-weaknesses">
                <CaretDownOutlined style="color: #ff4d4f" />
                <span v-for="w in record.weaknesses.slice(0, 2)" :key="w" class="swot-item bad">{{ w }}</span>
              </div>
            </div>
          </template>
        </template>
      </a-table>

      <!-- 卡片视图 -->
      <div v-else class="card-view">
        <a-row :gutter="[12, 12]">
          <a-col v-for="comp in result.competitors" :key="comp.asin" :span="12">
            <div class="competitor-card" :class="{ 'is-leader': comp.asin === result.market_leader }">
              <div class="card-header">
                <span class="card-brand">{{ comp.brand }}</span>
                <a-tag v-if="comp.asin === result.market_leader" color="gold" size="small">👑 领导者</a-tag>
              </div>
              <div class="card-title">{{ comp.title.slice(0, 50) }}...</div>
              <div class="card-stats">
                <div class="mini-stat">
                  <span class="mini-value">${{ comp.price }}</span>
                  <span class="mini-label">{{ getPositionLabel(comp.price_positioning) }}</span>
                </div>
                <div class="mini-stat">
                  <span class="mini-value">{{ comp.rating }}⭐</span>
                  <span class="mini-label">{{ comp.review_count }} 评论</span>
                </div>
                <div class="mini-stat">
                  <span class="mini-value">#{{ comp.bsr_rank.toLocaleString() }}</span>
                  <span class="mini-label">BSR</span>
                </div>
              </div>
              <div class="card-score">
                <span>Listing 分：</span>
                <a-progress
                  :percent="comp.listing_quality_score"
                  :show-info="false"
                  :stroke-color="getScoreColor(comp.listing_quality_score)"
                  size="small"
                />
                <span class="score-num">{{ comp.listing_quality_score }}</span>
              </div>
              <div class="card-swot">
                <div class="swot-mini"><CaretUpOutlined style="color: #52c41a" /> {{ comp.strengths[0] || '-' }}</div>
                <div class="swot-mini"><CaretDownOutlined style="color: #ff4d4f" /> {{ comp.weaknesses[0] || '-' }}</div>
              </div>
            </div>
          </a-col>
        </a-row>
      </div>
    </div>

    <!-- 定位图谱 -->
    <div class="section-block">
      <div class="section-header">
        <span class="section-title"><DotChartOutlined /> 市场定位图谱</span>
        <span class="section-desc">X轴=价格 Y轴=评分，气泡大小=月销量估算</span>
      </div>
      <div class="position-chart">
        <svg viewBox="0 0 500 320" class="position-svg">
          <!-- 背景网格 -->
          <defs>
            <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#f0f0f0" stroke-width="0.5"/>
            </pattern>
          </defs>
          <rect width="500" height="320" fill="url(#grid)" />

          <!-- 坐标轴 -->
          <line x1="50" y1="280" x2="480" y2="280" stroke="#d9d9d9" stroke-width="1.5" />
          <line x1="50" y1="280" x2="50" y2="30" stroke="#d9d9d9" stroke-width="1.5" />

          <!-- X轴标签 (价格) -->
          <text x="265" y="310" text-anchor="middle" font-size="11" fill="#8c8c8c">售价 ($)</text>
          <text x="80" y="296" font-size="9" fill="#999">$10</text>
          <text x="200" y="296" font-size="9" fill="#999">$25</text>
          <text x="340" y="296" font-size="9" fill="#999">$35</text>
          <text x="455" y="296" font-size="9" fill="#999">$45+</text>

          <!-- Y轴标签 (评分) -->
          <text x="20" y="160" text-anchor="middle" font-size="11" fill="#8c8c8c" transform="rotate(-90, 20, 160)">用户评分</text>
          <text x="42" y="275" font-size="9" fill="#999">3.0</text>
          <text x="42" y="200" font-size="9" fill="#999">4.0</text>
          <text x="42" y="120" font-size="9" fill="#999">4.5+</text>

          <!-- 四象限标注 -->
          <rect x="55" y="35" width="205" height="115" fill="#f6ffed" fill-opacity="0.4" rx="4"/>
          <text x="157" y="52" text-anchor="middle" font-size="10" fill="#389e0d" font-weight="600">★ 高端优质区</text>

          <rect x="270" y="35" width="205" height="115" fill="#fff7e6" fill-opacity="0.4" rx="4"/>
          <text x="372" y="52" text-anchor="middle" font-size="10" fill="#d48806" font-weight="600">💰 高价竞争区</text>

          <rect x="55" y="160" width="205" height="115" fill="#e6f7ff" fill-opacity="0.4" rx="4"/>
          <text x="157" y="177" text-anchor="middle" font-size="10" fill="#0958d9" font-weight="600">🎯 性价比蓝海区</text>

          <rect x="270" y="160" width="205" height="115" fill="#fff1f0" fill-opacity="0.4" rx="4"/>
          <text x="372" y="177" text-anchor="middle" font-size="10" fill="#cf1322" font-weight="600">⚠️ 低质低价区</text>

          <!-- 数据点 -->
          <g v-for="(comp, idx) in result.competitors" :key="comp.asin">
            <circle
              :cx="getXPosition(comp.price)"
              :cy="getYPosition(comp.rating)"
              :r="getBubbleRadius(comp.review_count)"
              :fill="comp.asin === result.market_leader ? '#faad14' : '#1890ff'"
              fill-opacity="0.65"
              stroke="#fff"
              stroke-width="2"
              class="data-point"
            />
            <text
              :x="getXPosition(comp.price)"
              :y="getYPosition(comp.rating) - getBubbleRadius(comp.review_count) - 6"
              text-anchor="middle"
              font-size="9"
              font-weight="500"
              :fill="comp.asin === result.market_leader ? '#d48806' : '#262626'"
            >{{ comp.brand.slice(0, 6) }}</text>
          </g>
        </svg>
      </div>
    </div>

    <!-- SWOT 总结 & 机会领域 -->
    <div class="section-block">
      <a-row :gutter="[16, 16]">
        <!-- SWOT 分析 -->
        <a-col :span="12">
          <div class="swot-grid">
            <div class="swot-box strength">
              <div class="swot-box-title">S 优势 (行业共通)</div>
              <ul>
                <li v-for="item in industryStrengths" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="swot-box weakness">
              <div class="swot-box-title">W 劣势 (行业痛点)</div>
              <ul>
                <li v-for="item in industryWeaknesses" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="swot-box opportunity">
              <div class="swot-box-title">O 机会 (进入窗口)</div>
              <ul>
                <li v-for="item in result.opportunity_areas" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="swot-box threat">
              <div class="swot-box-title">T 威胁 (竞争风险)</div>
              <ul>
                <li v-for="item in industryThreats" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
        </a-col>

        <!-- 结论与建议 -->
        <a-col :span="12">
          <div class="conclusion-card">
            <div class="conclusion-header"><TrophyOutlined /> 分析结论</div>
            <div class="conclusion-summary">{{ result.comparison_summary }}</div>

            <div class="conclusion-section">
              <div class="conclusion-subtitle"><AimOutlined /> 进入策略建议</div>
              <p class="recommendation-text">{{ result.recommendation }}</p>
            </div>

            <div class="conclusion-section">
              <div class="conclusion-subtitle"><BulbOutlined /> 差异化方向</div>
              <a-list :data-source="differentiationTips" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #avatar><CheckCircleOutlined style="color: #1890ff; font-size: 14px"/></template>
                      <template #title style="font-size: 12px">{{ item }}</template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </div>
          </div>
        </a-col>
      </a-row>
    </div>

    <!-- 底部操作栏 -->
    <div class="result-actions">
      <a-space>
        <a-button @click="$emit('reset')">
          <ReloadOutlined /> 重新选择
        </a-button>
        <a-button @click="$emit('switchToChat', `基于以下竞品对比结果，帮我制定选品策略：\n${comparisonSummaryText}`)">
          <SendOutlined /> 询问 AI 选品顾问
        </a-button>
        <a-button type="primary" @click="exportReport">
          <DownloadOutlined /> 导出对比报告
        </a-button>
      </a-space>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  TableOutlined, CaretUpOutlined, CaretDownOutlined,
  DotChartOutlined, TrophyOutlined, AimOutlined, BulbOutlined,
  CheckCircleOutlined, ReloadOutlined, SendOutlined, DownloadOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { MockCompetitor, MockCompetitorCompareResult } from '@/mock/data'

const props = defineProps<{
  result: MockCompetitorCompareResult
}>()

const emit = defineEmits<{
  (e: 'switchToChat', text: string): void
  (e: 'reset'): void
}>()

const viewMode = ref<'table' | 'card'>('table')

// ====== 计算属性 ======
// 市场领导者名称
const marketLeaderName = computed(() => {
  const leader = props.result.competitors.find(c => c.asin === props.result.market_leader)
  return leader?.brand || '-'
})

// 行业 SWOT
const industryStrengths = computed(() => {
  const allStrengths = props.result.competitors.flatMap(c => c.strengths)
  const freq = new Map<string, number>()
  allStrengths.forEach(s => freq.set(s, (freq.get(s) || 0) + 1))
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([name]) => name)
})

const industryWeaknesses = computed(() => {
  const allWeaknesses = props.result.competitors.flatMap(c => c.weaknesses)
  const freq = new Map<string, number>()
  allWeaknesses.forEach(w => freq.set(w, (freq.get(w) || 0) + 1))
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([name]) => name)
})

const industryThreats = computed<string[]>(() => [
  '头部品牌已建立口碑壁垒',
  '价格战压缩利润空间',
  '新进入者持续增加',
])

// 差异化建议
const differentiationTips = computed(() => {
  const tips: string[] = []

  const commonWeaknesses = industryWeaknesses.value
  if (commonWeaknesses.some(w => w.includes('质量') || w.includes('材质'))) {
    tips.push('主打高品质材料，突出耐用性卖点')
  }
  if (commonWeaknesses.some(w => w.includes('功能') || w.includes('体验'))) {
    tips.push('优化核心功能体验，解决用户最大不满')
  }
  if (commonWeaknesses.some(w => w.includes('包装') || w.includes('物流'))) {
    tips.push('升级开箱体验，增强包装质感')
  }

  const avgPrice = (props.result.price_range.min + props.result.price_range.max) / 2
  if (avgPrice < 20) {
    tips.push('可考虑中高端定位，避开低价红海')
  } else if (avgPrice > 35) {
    tips.push('存在性价比产品空间')
  }

  tips.push('针对 Top 差评点制作差异化 Listing 内容')

  return tips.slice(0, 5)
})

// 对比摘要文本
const comparisonSummaryText = computed(() => {
  const r = props.result
  return `对比 ${r.competitors.length} 个竞品：${r.competitors.map(c => c.brand).join('、')}\n价格区间：$${r.price_range.min}-$${r.price_range.max}\n平均评分：${r.avg_rating.toFixed(1)}\n市场领导者：${marketLeaderName.value}\n\n结论：${r.comparison_summary}\n建议：${r.recommendation}`
})

// ====== 表格列定义 ======
const compareColumns = [
  {
    title: '商品',
    dataIndex: 'title',
    ellipsis: true,
    width: 220,
  },
  {
    title: '价格/定位',
    dataIndex: 'price',
    width: 110,
    sorter: (a: MockCompetitor, b: MockCompetitor) => a.price - b.price,
  },
  {
    title: '评分',
    dataIndex: 'rating',
    width: 90,
    sorter: (a: MockCompetitor, b: MockCompetitor) => a.rating - b.rating,
  },
  {
    title: '评论数',
    dataIndex: 'review_count',
    width: 80,
    sorter: (a: MockCompetitor, b: MockCompetitor) => a.review_count - b.review_count,
  },
  {
    title: 'BSR排名',
    dataIndex: 'bsr_rank',
    width: 90,
    sorter: (a: MockCompetitor, b: MockCompetitor) => a.bsr_rank - b.bsr_rank,
  },
  {
    title: 'Listing质量',
    dataIndex: 'listing_quality_score',
    width: 100,
    sorter: (a: MockCompetitor, b: MockCompetitor) => a.listing_quality_score - b.listing_quality_score,
  },
  {
    title: 'A+内容',
    dataIndex: 'a_plus_content',
    width: 70,
  },
  {
    title: '优劣势',
    dataIndex: 'swot',
    width: 200,
  },
]

// ====== 方法 ======
// 价格定位颜色
const getPositionColor = (pos: string) => {
  if (pos === 'premium') return 'gold'
  if (pos === 'mid-range') return 'blue'
  return 'green'
}
const getPositionLabel = (pos: string) => {
  if (pos === 'premium') return '高端'
  if (pos === 'mid-range') return '中端'
  return '性价比'
}

// 评分颜色
const getScoreColor = (score: number) => {
  if (score >= 80) return '#52c41a'
  if (score >= 60) return '#faad14'
  return '#ff4d4f'
}

// 图表坐标计算
const getXPosition = (price: number) => {
  // 映射 $0-$50 到 x=60~470
  return Math.max(60, Math.min(470, 60 + (price / 50) * 410))
}
const getYPosition = (rating: number) => {
  // 映射 3.0-5.0 到 y=270~50
  return Math.max(50, Math.min(270, 270 - ((rating - 3.0) / 2.0) * 220))
}
const getBubbleRadius = (reviewCount: number) => {
  // 根据评论数决定气泡大小
  return Math.max(10, Math.min(30, 10 + Math.log(reviewCount) * 4))
}

// 导出报告
const exportReport = () => {
  const r = props.result
  const report = `
====================================
  竞品对比分析报告
  生成时间：${new Date().toLocaleString()}
====================================

【概览】
- 对比竞品：${r.competitors.map(c => `${c.brand}(${c.asin})`).join('、')}
- 价格区间：$${r.price_range.min} - $${r.price_range.max}
- 平均评分：${r.avg_rating.toFixed(1)}
- 市场领导者：${marketLeaderName.value}

【竞品详细对比】
${r.competitors.map(c =>
`${c.brand} (${c.asin})
  价格：$${c.price} [${getPositionLabel(c.price_positioning)}]
  评分：${c.rating} (${c.review_count} 条评论)
  BSR：#${c.bsr_rank.toLocaleString()}
  Listing质量：${c.listing_quality_score}/100
  A+内容：${c.a_plus_content ? '有' : '无'}
  优势：${c.strengths.join('、')}
  劣势：${c.weaknesses.join('、')}`
).join('\n\n')}

【SWOT 分析】
优势：${industryStrengths.value.join('、')}
劣势：${industryWeaknesses.value.join('、')}
机会：${r.opportunity_areas.join('、')}
威胁：${industryThreats.value.join('、')}

【结论】
${r.comparison_summary}

【建议】
${r.recommendation}
  `.trim()

  const blob = new Blob([report], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `竞品对比_${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)

  message.success('对比报告已导出')
}
</script>

<style scoped>
.result-section { padding: 0 4px; }

/* 概览条 */
.overview-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 10px;
  padding: 16px 20px;
}
.overview-stat {
  flex: 1;
  text-align: center;
  color: #fff;
}
.stat-label {
  font-size: 11px;
  opacity: 0.85;
  display: block;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  display: block;
  margin-top: 2px;
}
.overview-stat.highlight .stat-value.leader {
  color: #ffd666;
}

/* 区块 */
.section-block { margin-bottom: 20px; }
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-base);
  flex-wrap: wrap;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.section-desc {
  font-size: 11px;
  color: var(--text-secondary);
}

/* 表格内单元格 */
.product-cell { line-height: 1.4; }
.product-brand { font-weight: 600; font-size: 12px; color: var(--text-primary); }
.product-title-text { font-size: 11px; color: var(--text-secondary); }
.price-cell { display: flex; flex-direction: column; gap: 4px; }
.price-value { font-weight: 600; font-size: 14px; }
.rating-cell, .score-cell { display: flex; align-items: center; gap: 6px; }
.rating-num { font-weight: 600; font-size: 13px; }
.bsr-good { color: #52c41a; font-weight: 600; }
.bsr-bad { color: #ff4d4f; }
.swot-cell { font-size: 11px; }
.swot-strengths, .swot-weaknesses { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; }
.swot-item { font-size: 10px; }
.swot-item.good { color: #389e0d; }
.swot-item.bad { color: #cf1322; }

:deep(.row-leader) {
  background-color: #fffbe6 !important;
}

/* 卡片视图 */
.competitor-card {
  background: var(--bg-hover-light);
  border: 2px solid var(--border-base);
  border-radius: 10px;
  padding: 14px;
  transition: all 0.2s;
}
.competitor-card:hover { border-color: var(--border-base); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.competitor-card.is-leader { border-color: #faad14; background: #fffbe6; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.card-brand { font-weight: 700; font-size: 14px; color: var(--text-primary); }
.card-title { font-size: 11px; color: var(--text-secondary); line-height: 1.4; margin-bottom: 10px; }
.card-stats { display: flex; gap: 12px; margin-bottom: 10px; }
.mini-stat { display: flex; flex-direction: column; align-items: center; }
.mini-value { font-weight: 600; font-size: 13px; color: var(--text-primary); }
.mini-label { font-size: 10px; color: var(--text-secondary); }
.card-score { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-bottom: 8px; }
.score-num { font-weight: 600; min-width: 24px; }
.card-swot { font-size: 11px; }
.swot-mini { margin-bottom: 2px; }

/* 定位图谱 */
.position-chart {
  background: var(--bg-hover-light);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  padding: 16px;
}
.position-svg { width: 100%; height: auto; }
.data-point { cursor: pointer; transition: r 0.2s; }
.data-point:hover { r: +4; }

/* SWOT 网格 */
.swot-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.swot-box {
  border-radius: 8px;
  padding: 12px;
}
.swot-box.strength { background: #f6ffed; border: 1px solid #b7eb8f; }
.swot-box.weakness { background: #fff1f0; border: 1px solid #ffa39e; }
.swot-box.opportunity { background: #e6f7ff; border: 1px solid #91d5ff; }
.swot-box.threat { background: #fff7e6; border: 1px solid #ffd591; }
.swot-box-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
}
.swot-box ul { margin: 0; padding-left: 16px; }
.swot-box li { font-size: 11px; line-height: 1.8; color: var(--text-secondary); }

/* 结论卡片 */
.conclusion-card {
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  border-radius: 10px;
  padding: 16px;
  height: 100%;
}
.conclusion-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.conclusion-summary {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-primary);
  margin-bottom: 14px;
  padding: 10px;
  background: rgba(255,255,255,0.6);
  border-radius: 6px;
}
.conclusion-section { margin-bottom: 12px; }
.conclusion-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.recommendation-text {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-primary);
  padding: 10px;
  background: rgba(255,255,255,0.6);
  border-radius: 6px;
}
:deep(.conclusion-card .ant-list-item) { padding: 4px 0; }
:deep(.conclusion-card .ant-list-item-meta-title) { font-size: 11px; line-height: 1.5; }

/* 底部操作 */
.result-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--border-base);
  margin-top: 8px;
}
</style>
