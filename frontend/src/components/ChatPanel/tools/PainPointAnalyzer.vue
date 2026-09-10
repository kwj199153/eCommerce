<template>
  <div class="pain-point-analyzer">
    <!-- ===== 顶部操作栏 ===== -->
    <div class="analyzer-header">
      <div class="header-left">
        <span class="tool-icon-lg">🔍</span>
        <span class="tool-title">痛点分析</span>
        <a-tag color="default" size="small" class="mode-tag">评论洞察</a-tag>
      </div>
      <div class="header-right">
        <a-tooltip title="切换到对话模式，用自然语言提问">
          <a-button type="link" size="small" @click="$emit('switchToChat', '帮我分析这个产品的用户痛点')">
            <MessageOutlined /> 切换对话模式
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 辅助提示 -->
    <div class="helper-hint">
      <InfoCircleOutlined />
      从竞品评论中提取高频痛点，发现产品改进机会与市场空白
    </div>

    <!-- ===== 输入区域 ===== -->
    <div v-if="!hasResults && !isAnalyzing" class="input-section">
      <a-form
        :model="analysisForm"
        :label-col="{ span: 6 }"
        :wrapper-col="{ span: 17 }"
        layout="horizontal"
        size="small"
      >
        <!-- 目标商品 -->
        <div class="filter-group">
          <div class="group-title"><SearchOutlined /> 目标商品</div>

          <a-form-item label="ASIN / 商品">
            <a-select
              v-model:value="analysisForm.asin"
              placeholder="输入 ASIN 或选择商品"
              show-search
              :filter-option="filterOption"
              style="width: 100%"
              allow-clear
            >
              <a-select-option v-for="p in productOptions" :key="p.asin" :value="p.asin">
                {{ p.asin }} - {{ p.title.slice(0, 40) }}...
              </a-select-option>
            </a-select>
          </a-form-item>

          <a-form-item label="商品标题" v-if="selectedProduct">
            <a-typography-paragraph
              :ellipsis="{ rows: 2, expandable: true, symbol: '更多' }"
              :content="selectedProduct.title"
              style="margin-bottom: 0; font-size: 12px; color: #666"
            />
          </a-form-item>
        </div>

        <!-- 分析配置 -->
        <div class="filter-group">
          <div class="group-title"><SettingOutlined /> 分析配置</div>

          <a-form-item label="分析深度">
            <a-radio-group v-model:value="analysisForm.depth" size="small">
              <a-radio-button value="quick">快速分析 (Top 10 痛点)</a-radio-button>
              <a-radio-button value="deep">深度分析 (全量评论)</a-radio-button>
            </a-radio-group>
          </a-form-item>

          <a-form-item label="评论范围">
            <a-checkbox-group v-model:value="analysisForm.reviewScope" style="width: 100%">
              <a-checkbox value="negative">仅分析差评 (1-3星)</a-checkbox>
              <a-checkbox value="positive">同时分析好评 (4-5星)</a-checkbox>
            </a-checkbox-group>
          </a-form-item>

          <a-form-item label="痛点分类">
            <a-select
              v-model:value="analysisForm.categories"
              mode="multiple"
              placeholder="全部分类"
              style="width: 100%"
              allow-clear
            >
              <a-select-option value="quality">产品质量</a-select-option>
              <a-select-option value="function">功能体验</a-select-option>
              <a-select-option value="logistics">物流包装</a-select-option>
              <a-select-option value="service">售后服务</a-select-option>
            </a-select>
          </a-form-item>
        </div>

        <!-- 操作按钮 -->
        <div class="action-bar">
          <a-button @click="resetForm">重置</a-button>
          <a-button type="primary" :loading="isAnalyzing" @click="startAnalysis" :disabled="!analysisForm.asin">
            <SearchOutlined /> 开始分析
          </a-button>
        </div>
      </a-form>
    </div>

    <!-- ===== 分析中状态 ===== -->
    <div v-if="isAnalyzing" class="analyzing-state">
      <a-spin size="large" />
      <div class="progress-steps">
        <a-steps :current="analysisProgress" size="small" direction="vertical">
          <a-step title="采集评论数据" description="获取目标商品的全部评论" />
          <a-step title="NLP 痛点提取" description="AI 语义分析识别痛点关键词" />
          <a-step title="聚类与评分" description="痛点归类合并，计算严重程度" />
          <a-step title="生成洞察报告" :description="`输出 ${analysisForm.depth === 'deep' ? '完整' : '精简'}分析结论`" />
        </a-steps>
      </div>
    </div>

    <!-- ===== 分析结果 ===== -->
    <div v-if="hasResults && !isAnalyzing" class="result-section">
      <!-- 结果概览卡片 -->
      <div class="overview-cards">
        <div class="overview-card">
          <div class="card-value">{{ analysisResult.total_reviews_analyzed }}</div>
          <div class="card-label">分析评论数</div>
        </div>
        <div class="overview-card negative">
          <div class="card-value">{{ analysisResult.negative_review_count }}</div>
          <div class="card-label">差评数量</div>
          <div class="card-sub">{{ negativeRate }}% 差评率</div>
        </div>
        <div class="overview-card warning">
          <div class="card-value">{{ analysisResult.pain_points.length }}</div>
          <div class="card-label">发现痛点</div>
        </div>
        <div class="overview-card success">
          <div class="card-value">{{ analysisResult.market_gap_score }}</div>
          <div class="card-label">市场空白分</div>
          <div class="card-sub" :class="gapLevelClass">{{ gapLevelText }}</div>
        </div>
      </div>

      <!-- 痛点排行表格 -->
      <div class="section-block">
        <div class="section-header">
          <span class="section-title"><FireOutlined /> 高频痛点排行</span>
          <a-space>
            <a-select v-model:value="filterCategory" size="small" style="width: 120px" allow-clear placeholder="全部分类">
              <a-select-option value="quality">产品质量</a-select-option>
              <a-select-option value="function">功能体验</a-select-option>
              <a-select-option value="logistics">物流包装</a-select-option>
              <a-select-option value="service">售后服务</a-select-option>
            </a-select>
            <a-button size="small" @click="$emit('switchToChat', `基于以下痛点分析结果，给出产品改进方案：${topPainPointsSummary}`)">
              <CommentOutlined /> AI 改进建议
            </a-button>
          </a-space>
        </div>

        <a-table
          :dataSource="filteredPainPoints"
          :columns="painPointColumns"
          :pagination="{ pageSize: 8, size: 'small' }"
          size="small"
          row-key="pain_point"
          :row-class-name="rowClassName"
        >
          <!-- 痛点名称 -->
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'pain_point'">
              <div class="pain-point-cell">
                <a-tag :color="getCategoryColor(record.category)" size="small">{{ getCategoryName(record.category) }}</a-tag>
                <span class="pain-text">{{ record.pain_point }}</span>
              </div>
            </template>

            <!-- 严重程度 -->
            <template v-else-if="column.dataIndex === 'severity'">
              <a-tag :color="getSeverityColor(record.severity)" size="small">
                {{ record.severity === 'high' ? '高' : record.severity === 'medium' ? '中' : '低' }}
              </a-tag>
            </template>

            <!-- 占比 -->
            <template v-else-if="column.dataIndex === 'percentage'">
              <a-progress
                :percent="Math.round(record.percentage)"
                :stroke-color="getSeverityColor(record.severity)"
                size="small"
                :show-info="true"
              />
            </template>

            <!-- 操作 -->
            <template v-else-if="column.dataIndex === 'action'">
              <a-button type="link" size="small" @click="viewExampleReviews(record)">
                <EyeOutlined /> 查看原文
              </a-button>
            </template>
          </template>
        </a-table>
      </div>

      <!-- 原始评论摘录 -->
      <div class="section-block" v-if="exampleReviews.length > 0">
        <div class="section-header">
          <span class="section-title"><FileTextOutlined /> 相关评论摘录</span>
          <a-tag color="blue">{{ currentPainPoint?.pain_point }}</a-tag>
          <a-button type="text" size="small" @click="exampleReviews = []">关闭</a-button>
        </div>
        <div class="review-list">
          <div v-for="review in exampleReviews" :key="review.review_id" class="review-item" :class="review.rating <= 3 ? 'negative-review' : ''">
            <div class="review-meta">
              <a-rate :value="review.rating" disabled size="small" />
              <span class="review-author">{{ review.author }}</span>
              <span class="review-date">{{ review.date }}</span>
              <a-tag v-if="review.verified_purchase" color="blue" size="small">Verified</a-tag>
            </div>
            <div class="review-title">{{ review.title }}</div>
            <div class="review-body">{{ review.body }}</div>
            <div class="review-pain-tags" v-if="review.pain_points?.length">
              <a-tag v-for="tag in review.pain_points" :key="tag" size="small" color="error">{{ tag }}</a-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 改进建议 & 市机空白 -->
      <div class="section-block">
        <a-row :gutter="16">
          <!-- 改进建议 -->
          <a-col :span="12">
            <div class="insight-card">
              <div class="insight-header"><BulbOutlined /> 产品改进建议</div>
              <a-list :data-source="analysisResult.improvement_suggestions" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #avatar>
                        <CheckCircleOutlined style="color: #52c41a; font-size: 16px" />
                      </template>
                      <template #title>{{ item }}</template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </div>
          </a-col>

          <!-- 竞品弱点 / 市场机会 -->
          <a-col :span="12">
            <div class="insight-card opportunity">
              <div class="insight-header"><ThunderboltOutlined /> 市场机会</div>
              <a-list :data-source="analysisResult.competitor_weaknesses" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #avatar>
                        <StarOutlined style="color: #faad14; font-size: 16px" />
                      </template>
                      <template #title>{{ item }}</template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </div>
          </a-col>
        </a-row>
      </div>

      <!-- 底部操作栏 -->
      <div class="result-actions">
        <a-space>
          <a-button @click="resetAnalysis">
            <ReloadOutlined /> 重新分析
          </a-button>
          <a-button @click="$emit('switchToChat', `请根据以下痛点分析结果，为我生成差异化产品方案：\n\n${analysisSummary}`)">
            <SendOutlined /> 询问 AI 选品顾问
          </a-button>
          <a-button type="primary" @click="exportReport">
            <DownloadOutlined /> 导出报告
          </a-button>
        </a-space>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  MessageOutlined, InfoCircleOutlined, SearchOutlined, SettingOutlined,
  FireOutlined, CommentOutlined, EyeOutlined, FileTextOutlined,
  BulbOutlined, ThunderboltOutlined, CheckCircleOutlined, StarOutlined,
  ReloadOutlined, SendOutlined, DownloadOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

import { MOCK_PRODUCTS, type MockProduct, type MockPainPointAnalysis, type PainPointItem, type MockReview } from '@/mock/data'

// ====== Props & Emits ======
const emit = defineEmits(['switchToChat', 'resultReady'])

// ====== 表单状态 ======
const analysisForm = ref({
  asin: '' as string | undefined,
  depth: 'quick' as 'quick' | 'deep',
  reviewScope: ['negative'] as string[],
  categories: undefined as string[] | undefined,
})

// ====== 数据状态 ======
const isAnalyzing = ref(false)
const analysisProgress = ref(0)
const analysisResult = ref<MockPainPointAnalysis | null>(null)
const exampleReviews = ref<MockReview[]>([])
const currentPainPoint = ref<PainPointItem | null>(null)
const filterCategory = ref<string | undefined>(undefined)

// ====== 计算属性 ======

// 商品选项（从 Mock 数据）
const productOptions = computed(() => MOCK_PRODUCTS)

// 当前选中的商品
const selectedProduct = computed(() => {
  if (!analysisForm.value.asin) return null
  return MOCK_PRODUCTS.find(p => p.asin === analysisForm.value.asin) || null
})

// 是否有结果
const hasResults = computed(() => analysisResult.value !== null)

// 差评率
const negativeRate = computed(() => {
  if (!analysisResult.value || analysisResult.value.total_reviews_analyzed === 0) return 0
  return Math.round((analysisResult.value.negative_review_count / analysisResult.value.total_reviews_analyzed) * 100 * 10) / 10
})

// 市场空白等级
const gapLevelText = computed(() => {
  const score = analysisResult.value?.market_gap_score || 0
  if (score >= 80) return '巨大空白'
  if (score >= 60) return '明显机会'
  if (score >= 40) return '一般空间'
  return '竞争激烈'
})

const gapLevelClass = computed(() => {
  const score = analysisResult.value?.market_gap_score || 0
  if (score >= 80) return 'level-high'
  if (score >= 60) return 'level-medium'
  return 'level-low'
})

// 过滤后的痛点列表
const filteredPainPoints = computed(() => {
  if (!analysisResult.value) return []
  let points = [...analysisResult.value.pain_points]
  if (filterCategory.value) {
    points = points.filter(p => p.category === filterCategory.value)
  }
  return points.sort((a, b) => b.count - a.count)
})

// Top 痛点摘要（用于 AI 对话）
const topPainPointsSummary = computed(() => {
  if (!analysisResult.value) return ''
  return analysisResult.value.pain_points.slice(0, 5).map(p => p.pain_point).join('、')
})

// 完整摘要
const analysisSummary = computed(() => {
  if (!analysisResult.value || !selectedProduct.value) return ''
  const r = analysisResult.value
  const p = selectedProduct.value
  return `商品：${p.title} (${p.asin})\n总评论：${r.total_reviews_analyzed} 条，差评 ${r.negative_review_count} 条（${negativeRate.value}%）\n发现 ${r.pain_points.length} 个核心痛点\n市场空白评分：${r.market_gap_score}/100\nTop 痛点：${r.pain_points.slice(0, 5).map(pp => pp.pain_point).join('、')}`
})

// ====== 表格列定义 ======
const painPointColumns = [
  {
    title: '排名',
    width: 50,
    customRender: ({ index }: { index: number }) => index + 1,
  },
  {
    title: '痛点描述',
    dataIndex: 'pain_point',
    ellipsis: true,
  },
  {
    title: '分类',
    dataIndex: 'category',
    width: 100,
  },
  {
    title: '提及次数',
    dataIndex: 'count',
    width: 90,
    sorter: (a: PainPointItem, b: PainPointItem) => a.count - b.count,
  },
  {
    title: '占比',
    dataIndex: 'percentage',
    width: 120,
  },
  {
    title: '严重程度',
    dataIndex: 'severity',
    width: 90,
  },
  {
    title: '操作',
    dataIndex: 'action',
    width: 90,
  },
]

// ====== 方法 ======

// 下拉搜索过滤
const filterOption = (input: string, option: any) => {
  const product = MOCK_PRODUCTS.find(p => p.asin === option.value)
  if (!product) return false
  return product.title.toLowerCase().includes(input.toLowerCase()) ||
         product.asin.toLowerCase().includes(input.toLowerCase())
}

// 获取分类颜色
const getCategoryColor = (category: string) => {
  const map: Record<string, string> = {
    quality: 'red',
    function: 'orange',
    logistics: 'blue',
    service: 'purple',
  }
  return map[category] || 'default'
}

const getCategoryName = (category: string) => {
  const map: Record<string, string> = {
    quality: '产品质量',
    function: '功能体验',
    logistics: '物流包装',
    service: '售后服务',
  }
  return map[category] || category
}

// 获取严重程度颜色
const getSeverityColor = (severity: string) => {
  if (severity === 'high') return '#f5222d'
  if (severity === 'medium') return '#fa8c16'
  return '#52c41a'
}

// 行样式
const rowClassName = (record: PainPointItem) => {
  if (record.severity === 'high') return 'row-severity-high'
  if (record.severity === 'medium') return 'row-severity-medium'
  return ''
}

// 开始分析
const startAnalysis = async () => {
  if (!analysisForm.value.asin) {
    message.warning('请先选择目标商品')
    return
  }

  isAnalyzing.value = true
  analysisProgress.value = 0
  analysisResult.value = null

  // 模拟分析进度（Mock 数据快速响应）
  for (let i = 1; i <= 4; i++) {
    await new Promise(resolve => setTimeout(resolve, 150 + Math.random() * 150))
    analysisProgress.value = i
  }

  // 生成分析结果
  const product = MOCK_PRODUCTS.find(p => p.asin === analysisForm.value.asin)
  if (product) {
    analysisResult.value = generatePainPointAnalysis(product, analysisForm.value.depth)
    emit('resultReady', analysisResult.value)
  }

  isAnalyzing.value = false
}

// 生成痛点分析结果
const generatePainPointAnalysis = (product: MockProduct, depth: 'quick' | 'deep'): MockPainPointAnalysis => {
  const reviews = product.reviews
  const negativeReviews = reviews.filter(r => r.rating <= 3)
  const positiveReviews = reviews.filter(r => r.rating >= 4)

  // 统计所有痛点词频
  const painMap = new Map<string, { count: number; category: string; severity: 'high' | 'medium' | 'low'; examples: string[] }>()

  reviews.forEach(review => {
    if (review.pain_points) {
      review.pain_points.forEach(point => {
        const existing = painMap.get(point)
        if (existing) {
          existing.count++
          if (existing.examples.length < 3 && !existing.examples.includes(review.review_id)) {
            existing.examples.push(review.review_id)
          }
        } else {
          // 根据情感和评分判断严重程度
          let severity: 'high' | 'medium' | 'low' = 'medium'
          if (review.rating <= 2) severity = 'high'
          else if (review.rating >= 4) severity = 'low'

          // 判断分类
          let category = 'function'
          const qualityKeywords = ['漏水', 'leak', '开裂', 'crack', '变形', 'deform', '生锈', 'rust', '异味', 'smell', '划痕', 'scratch']
          const logisticsKeywords = ['包装', 'packaging', '破损', 'damaged', '缺失', 'missing', '慢', 'slow']
          const serviceKeywords = ['客服', 'service', '退换', 'return', '保修', 'warranty']

          const lowerPoint = point.toLowerCase()
          if (qualityKeywords.some(k => lowerPoint.includes(k.toLowerCase()))) category = 'quality'
          else if (logisticsKeywords.some(k => lowerPoint.includes(k.toLowerCase()))) category = 'logistics'
          else if (serviceKeywords.some(k => lowerPoint.includes(k.toLowerCase()))) category = 'service'

          painMap.set(point, { count: 1, category, severity, examples: [review.review_id] })
        }
      })
    }
  })

  // 转换为数组并排序
  let painPoints: PainPointItem[] = Array.from(painMap.entries()).map(([point, data]) => ({
    pain_point: point,
    count: data.count,
    percentage: (data.count / reviews.length) * 100,
    severity: data.severity,
    category: data.category,
    example_review_id: data.examples[0],
  })).sort((a, b) => b.count - a.count)

  // 快速模式只取 Top 10
  if (depth === 'quick') {
    painPoints = painPoints.slice(0, 10)
  }

  // 生成改进建议
  const improvementSuggestions = generateImprovements(painPoints)

  // 生成竞品弱点/市场机会
  const competitorWeaknesses = generateOpportunities(painPoints)

  // 计算市场空白度评分
  const highSevereCount = painPoints.filter(p => p.severity === 'high').length
  const mediumSevereCount = painPoints.filter(p => p.severity === 'medium').length
  const marketGapScore = Math.min(95, Math.max(15,
    40 + (highSevereCount * 12) + (mediumSevereCount * 6) + (painPoints.length > 8 ? 15 : 0)
  ))

  return {
    product_asin: product.asin,
    total_reviews_analyzed: reviews.length,
    negative_review_count: negativeReviews.length,
    positive_review_count: positiveReviews.length,
    pain_points: painPoints,
    improvement_suggestions: improvementSuggestions,
    market_gap_score,
    competitor_weaknesses: competitorWeaknesses,
  }
}

// 生成改进建议
const generateImprovements = (painPoints: PainPointItem[]): string[] => {
  const suggestions: string[] = []
  const highPains = painPoints.filter(p => p.severity === 'high').slice(0, 3)

  highPains.forEach(p => {
    if (p.category === 'quality') {
      suggestions.push(`优化材质/工艺解决「${p.pain_point}」问题，提升耐用性`)
    } else if (p.category === 'function') {
      suggestions.push(`改进「${p.pain_point}」相关功能设计，增强用户体验`)
    } else if (p.category === 'logistics') {
      suggestions.push(`加强包装防护，减少运输过程中的${p.pain_point}`)
    } else {
      suggestions.push(`完善${p.pain_point}相关的服务体系`)
    }
  })

  // 补充通用建议
  if (suggestions.length < 4) {
    suggestions.push('在 Listing 中突出已解决的痛点，形成差异化卖点')
    suggestions.push('针对高频差评点制作 FAQ 或视频说明')
  }

  return suggestions.slice(0, 5)
}

// 生成市场机会
const generateOpportunities = (painPoints: PainPointItem[]): string[] => {
  const opportunities: string[] = []

  // 从高严重程度痛点中提炼机会
  const highPains = painPoints.filter(p => p.severity === 'high')
  if (highPains.some(p => p.category === 'quality')) {
    opportunities.push('市场上缺乏高品质替代品，存在品质升级空间')
  }
  if (highPains.some(p => p.category === 'function')) {
    opportunities.push('现有产品功能缺陷明显，可推出改良版抢占市场')
  }
  if (painPoints.length > 6) {
    opportunities.push('竞品普遍评价不高，新进入者有较大差异化空间')
  }

  opportunities.push('可通过解决 Top 3 痛点建立口碑优势')

  return opportunities.slice(0, 4)
}

// 查看示例评论
const viewExampleReviews = (record: PainPointItem) => {
  currentPainPoint.value = record
  const product = MOCK_PRODUCTS.find(p => p.asin === analysisForm.value.asin)
  if (!product) return

  // 找出包含该痛点的所有评论
  const relatedReviews = product.reviews.filter(r =>
    r.pain_points && r.pain_points.includes(record.pain_point)
  ).slice(0, 8)

  exampleReviews.value = relatedReviews
}

// 重置表单
const resetForm = () => {
  analysisForm.value = {
    asin: undefined,
    depth: 'quick',
    reviewScope: ['negative'],
    categories: undefined,
  }
}

// 重置分析
const resetAnalysis = () => {
  analysisResult.value = null
  exampleReviews.value = []
  currentPainPoint.value = null
  filterCategory.value = undefined
  resetForm()
}

// 导出报告
const exportReport = () => {
  if (!analysisResult.value || !selectedProduct.value) return

  const report = `
====================================
  痛点分析报告
  商品：${selectedProduct.value.title}
  ASIN：${selectedProduct.value.asin}
  生成时间：${new Date().toLocaleString()}
====================================

【概览】
- 分析评论数：${analysisResult.value.total_reviews_analyzed}
- 差评数量：${analysisResult.value.negative_review_count} (${negativeRate.value}%)
- 发现痛点：${analysisResult.value.pain_points.length} 个
- 市场空白评分：${analysisResult.value.market_gap_score}/100

【Top 痛点排行】
${analysisResult.value.pain_points.map((p, i) =>
  `${i + 1}. [${getCategoryName(p.category)}] ${p.pain_point} - 提及${p.count}次(${Math.round(p.percentage)}%) - ${p.severity === 'high' ? '高' : p.severity === 'medium' ? '中' : '低'}风险`
).join('\n')}

【改进建议】
${analysisResult.value.improvement_suggestions.map((s, i) => `${i + 1}. ${s}`).join('\n')}

【市场机会】
${analysisResult.value.competitor_weaknesses.map((o, i) => `${i + 1}. ${o}`).join('\n')}
  `.trim()

  const blob = new Blob([report], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `痛点分析_${selectedProduct.value.asin}_${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)

  message.success('报告已导出')
}
</script>

<style scoped>
.pain-point-analyzer {
  height: 100%;
  overflow-y: auto;
}

/* 顶部 */
.analyzer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0 12px;
  border-bottom: 1px solid var(--border-base);
  margin-bottom: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tool-icon-lg { font-size: 24px; }
.tool-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.helper-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  background: #fff7e6;
  border-radius: 6px;
  font-size: 13px;
  color: #d46b08;
  margin-bottom: 16px;
}

/* 输入区域 */
.input-section {
  padding: 0 4px;
}
.filter-group {
  margin-bottom: 18px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-base);
}
.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid var(--border-base);
}

/* 分析中 */
.analyzing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 24px;
}
.progress-steps {
  margin-top: 32px;
  width: 300px;
}

/* 结果区域 */
.result-section {
  padding: 0 4px;
}

/* 概览卡片 */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.overview-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 10px;
  padding: 16px;
  text-align: center;
  color: #fff;
}
.overview-card.negative {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
}
.overview-card.warning {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}
.overview-card.success {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
}
.card-value {
  font-size: 28px;
  font-weight: 700;
}
.card-label {
  font-size: 12px;
  opacity: 0.9;
  margin-top: 4px;
}
.card-sub {
  font-size: 11px;
  opacity: 0.8;
  margin-top: 2px;
}
.card-sub.level-high { color: #ffd666; }
.card-sub.level-medium { color: #fff; }
.card-sub.level-low { color: #ffccc7; }

/* 区块 */
.section-block {
  margin-bottom: 20px;
}
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-base);
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 痛点单元格 */
.pain-point-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pain-text {
  font-size: 13px;
}

/* 行严重程度样式 */
:deep(.row-severity-high) {
  background-color: #fff1f0 !important;
}
:deep(.row-severity-medium) {
  background-color: #fffbe6 !important;
}

/* 评论摘录 */
.review-list {
  max-height: 300px;
  overflow-y: auto;
}
.review-item {
  padding: 12px;
  border: 1px solid var(--border-base);
  border-radius: 8px;
  margin-bottom: 10px;
  background: var(--bg-hover-light);
}
.review-item.negative-review {
  border-left: 3px solid #ff4d4f;
}
.review-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.review-author {
  font-weight: 500;
  color: var(--text-secondary);
}
.review-date {
  color: var(--text-tertiary);
}
.review-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
  color: var(--text-primary);
}
.review-body {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.review-pain-tags {
  margin-top: 8px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

/* 洞察卡片 */
.insight-card {
  background: var(--bg-hover-light);
  border-radius: 8px;
  padding: 14px;
  border: 1px solid var(--border-base);
  height: 100%;
}
.insight-card.opportunity {
  background: #fffbe6;
  border-color: #ffe58f;
}
.insight-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary);
}
:deep(.insight-card .ant-list-item) {
  padding: 6px 0;
}
:deep(.insight-card .ant-list-item-meta-title) {
  font-size: 12px;
  line-height: 1.5;
}

/* 底部操作 */
.result-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--border-base);
  margin-top: 8px;
}
</style>
