<template>
  <div class="competitor-compare">
    <!-- ===== 顶部操作栏 ===== -->
    <div class="compare-header">
      <div class="header-left">
        <span class="tool-icon-lg">⚔️</span>
        <span class="tool-title">竞品对比</span>
        <a-tag color="default" size="small" class="mode-tag">多维分析</a-tag>
      </div>
      <div class="header-right">
        <a-tooltip title="切换到对话模式，用自然语言描述">
          <a-button type="link" size="small" @click="$emit('switchToChat', '帮我分析这个类目的竞品格局')">
            <MessageOutlined /> 切换对话模式
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 辅助提示 -->
    <div class="helper-hint">
      <InfoCircleOutlined />
      多维度对比多个竞品 Listing，发现市场定位空白与差异化机会
    </div>

    <!-- ===== 输入区域 ===== -->
    <div v-if="!hasResults && !isAnalyzing" class="input-section">
      <a-form
        :model="compareForm"
        :label-col="{ span: 6 }"
        :wrapper-col="{ span: 17 }"
        layout="horizontal"
        size="small"
      >
        <!-- 竞品选择 -->
        <div class="filter-group">
          <div class="group-title"><TeamOutlined /> 选择竞品 (2-5个)</div>

          <a-form-item label="竞品列表">
            <div class="competitor-selector">
              <div v-for="(asin, index) in compareForm.asins" :key="index" class="competitor-input-row">
                <a-select
                  :value="asin"
                  placeholder="输入或选择 ASIN"
                  show-search
                  :filter-option="filterOption"
                  style="flex: 1"
                  allow-clear
                  size="small"
                  @change="(val: string) => updateAsin(index, val)"
                >
                  <a-select-option v-for="p in productOptions" :key="p.asin" :value="p.asin">
                    {{ p.asin }} - {{ p.title.slice(0, 35) }}...
                  </a-select-option>
                </a-select>
                <a-button
                  type="text"
                  danger
                  size="small"
                  :disabled="compareForm.asins.length <= 2"
                  @click="removeAsin(index)"
                >
                  <MinusCircleOutlined />
                </a-button>
              </div>
              <a-button
                v-if="compareForm.asins.length < 5"
                type="dashed"
                block
                size="small"
                @click="addAsin"
                style="margin-top: 8px"
              >
                <PlusOutlined /> 添加竞品
              </a-button>
            </div>
          </a-form-item>

          <!-- 已选商品预览 -->
          <div v-if="selectedProducts.length > 0" class="selected-preview">
            <div v-for="p in selectedProducts" :key="p.asin" class="preview-card">
              <div class="preview-title">{{ p.title.slice(0, 40) }}...</div>
              <div class="preview-meta">
                <span>${{ p.price }}</span>
                <a-rate :value="Math.round(p.rating)" disabled size="small" />
                <span>{{ p.review_count }} 评论</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 对比维度 -->
        <div class="filter-group">
          <div class="group-title"><ApartmentOutlined /> 对比维度</div>

          <a-form-item label="核心维度">
            <a-checkbox-group v-model:value="compareForm.dimensions" style="width: 100%">
              <a-row>
                <a-col :span="12"><a-checkbox value="price">价格定位</a-checkbox></a-col>
                <a-col :span="12"><a-checkbox value="quality">Listing 质量</a-checkbox></a-col>
                <a-col :span="12"><a-checkbox value="rating">用户评价</a-checkbox></a-col>
                <a-col :span="12"><a-checkbox value="bsr">销量排名</a-checkbox></a-col>
                <a-col :span="12"><a-checkbox value="ad">广告策略</a-checkbox></a-col>
                <a-col :span="12"><a-checkbox value="content">内容丰富度</a-checkbox></a-col>
              </a-row>
            </a-checkbox-group>
          </a-form-item>
        </div>

        <!-- 操作按钮 -->
        <div class="action-bar">
          <a-button @click="resetForm">重置</a-button>
          <a-button type="primary" :loading="isAnalyzing" @click="startCompare" :disabled="validAsinCount < 2">
            <BarChartOutlined /> 开始对比
          </a-button>
        </div>
      </a-form>
    </div>

    <!-- ===== 分析中状态 ===== -->
    <div v-if="isAnalyzing" class="analyzing-state">
      <a-spin size="large" />
      <div class="progress-steps">
        <a-steps :current="analysisProgress" size="small" direction="vertical">
          <a-step title="采集竞品数据" description="获取各竞品 Listing 信息" />
          <a-step title="多维度解析" :description="`分析 ${compareForm.dimensions.length} 个对比维度`" />
          <a-step title="SWOT 建模" description="识别各竞品优劣势" />
          <a-step title="生成对比报告" description="输出市场定位建议" />
        </a-steps>
      </div>
    </div>

    <!-- ===== 对比结果 ===== -->
    <CompareResult
      v-if="hasResults && !isAnalyzing"
      :result="compareResult!"
      @switch-to-chat="(text: string) => $emit('switchToChat', text)"
      @reset="resetCompare"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  MessageOutlined, InfoCircleOutlined, TeamOutlined, ApartmentOutlined,
  BarChartOutlined, PlusOutlined, MinusCircleOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

import {
  MOCK_PRODUCTS, type MockProduct, type MockCompetitor,
  type MockCompetitorCompareResult
} from '@/mock/data'
import CompareResult from './CompareResult.vue'

// ====== Props & Emits ======
const emit = defineEmits(['switchToChat', 'resultReady'])

// ====== 表单状态 ======
const compareForm = ref({
  asins: [''] as string[],
  dimensions: ['price', 'quality', 'rating', 'bsr'] as string[],
})

// ====== 数据状态 ======
const isAnalyzing = ref(false)
const analysisProgress = ref(0)
const compareResult = ref<MockCompetitorCompareResult | null>(null)

// ====== 计算属性 ======

// 商品选项
const productOptions = computed(() => MOCK_PRODUCTS)

// 已选商品详情
const selectedProducts = computed(() => {
  return compareForm.value.asins
    .filter(a => a)
    .map(asin => MOCK_PRODUCTS.find(p => p.asin === asin))
    .filter((p): p is MockProduct => !!p)
})

// 有效 ASIN 数量
const validAsinCount = computed(() => compareForm.value.asins.filter(a => a).length)

// 是否有结果
const hasResults = computed(() => compareResult.value !== null)

// ====== 方法 ======

// 下拉搜索过滤
const filterOption = (input: string, option: any) => {
  const product = MOCK_PRODUCTS.find(p => p.asin === option.value)
  if (!product) return false
  return product.title.toLowerCase().includes(input.toLowerCase()) ||
         product.asin.toLowerCase().includes(input.toLowerCase()) ||
         product.brand.toLowerCase().includes(input.toLowerCase())
}

// 更新 ASIN
const updateAsin = (index: number, val: string) => {
  compareForm.value.asins[index] = val
}

// 添加 ASIN
const addAsin = () => {
  if (compareForm.value.asins.length < 5) {
    compareForm.value.asins.push('')
  }
}

// 移除 ASIN
const removeAsin = (index: number) => {
  if (compareForm.value.asins.length > 2) {
    compareForm.value.asins.splice(index, 1)
  }
}

// 开始对比
const startCompare = async () => {
  if (validAsinCount.value < 2) {
    message.warning('请至少选择 2 个竞品进行对比')
    return
  }

  isAnalyzing.value = true
  analysisProgress.value = 0

  for (let i = 1; i <= 4; i++) {
    await new Promise(resolve => setTimeout(resolve, 150 + Math.random() * 150))
    analysisProgress.value = i
  }

  // 生成对比结果
  const products = selectedProducts.value
  if (products.length >= 2) {
    compareResult.value = generateCompareResult(products)
    emit('resultReady', compareResult.value)
  }

  isAnalyzing.value = false
}

// 生成对比结果
const generateCompareResult = (products: MockProduct[]): MockCompetitorCompareResult => {
  // 转换为竞品格式
  const competitors: MockCompetitor[] = products.map(p => {
    // 判断价格定位
    let price_positioning: 'premium' | 'mid-range' | 'budget' = 'mid-range'
    if (p.price >= 30) price_positioning = 'premium'
    else if (p.price <= 18) price_positioning = 'budget'

    // 生成优势/劣势
    const strengths = generateStrengths(p)
    const weaknesses = generateWeaknesses(p)

    return {
      asin: p.asin,
      title: p.title,
      brand: p.brand,
      price: p.price,
      rating: p.rating,
      review_count: p.review_count,
      bsr_rank: p.bsr_rank,
      listing_quality_score: p.overall_listing_score,
      title_score: p.title_score,
      image_score: p.image_score,
      bullet_score: p.bullet_score,
      a_plus_content: p.overall_listing_score >= 85,
      price_positioning,
      strengths,
      weaknesses,
      sponsored_rank: Math.floor(Math.random() * 10) + 1,
      estimated_ppc: parseFloat((0.5 + Math.random() * 2).toFixed(2)),
    }
  })

  // 找出市场领导者（综合评分最高）
  const leader = competitors.reduce((best, curr) =>
    (curr.listing_quality_score + curr.rating * 10) > (best.listing_quality_score + best.rating * 10)
      ? curr : best
  )

  // 价格范围
  const prices = competitors.map(c => c.price)
  const price_range = { min: Math.min(...prices), max: Math.max(...prices) }

  // 平均评分
  const avg_rating = competitors.reduce((sum, c) => sum + c.rating, 0) / competitors.length

  // 机会领域
  const opportunity_areas = generateOpportunities(competitors)

  // 对比总结
  const comparison_summary = generateComparisonSummary(competitors, leader)

  // 建议
  const recommendation = generateRecommendation(competitors, leader)

  return {
    compared_asins: products.map(p => p.asin),
    comparison_summary,
    recommendation,
    competitors,
    price_range,
    avg_rating,
    market_leader: leader.asin,
    opportunity_areas,
  }
}

// 生成优势
const generateStrengths = (p: MockProduct): string[] => {
  const strengths: string[] = []
  if (p.overall_listing_score >= 80) strengths.push('Listing 质量优秀')
  if (p.rating >= 4.4) strengths.push('高用户好评率')
  if (p.review_count >= 150) strengths.push('评论基数大，信任度高')
  if (p.bsr_rank <= 5000) strengths.push('BSR 排名靠前')
  if (p.image_score >= 85) strengths.push('主图视觉吸引力强')
  if (p.net_profit >= 10) strengths.push('利润空间健康')
  if (strengths.length < 2) strengths.push('有一定市场认知度')
  return strengths.slice(0, 3)
}

// 生成劣势
const generateWeaknesses = (p: MockProduct): string[] => {
  const weaknesses: string[] = []
  if (p.rating < 4.2) weaknesses.push('评分偏低，有改进空间')
  if (p.overall_listing_score < 75) weaknesses.push('Listing 优化不足')
  if (p.bullet_score < p.title_score - 5) weaknesses.push('五点描述不够吸引')
  if (p.price > 30 && p.review_count < 100) weaknesses.push('高价但评论少，转化存疑')
  if (p.blue_ocean_score < 45) weaknesses.push('红海品类，竞争激烈')
  if (weaknesses.length < 2) weaknesses.push('差异化不明显')
  return weaknesses.slice(0, 3)
}

// 生成机会领域
const generateOpportunities = (competitors: MockCompetitor[]): string[] => {
  const opportunities: string[] = []

  // 检查是否有价格空档
  const prices = competitors.map(c => c.price)
  const minPrice = Math.min(...prices)
  const maxPrice = Math.max(...prices)
  if (maxPrice - minPrice > 15) {
    opportunities.push(`价格区间 $${minPrice + 5}-$${maxPrice - 5} 存在空档`)
  }

  // 检查是否普遍低评分
  const avgRating = competitors.reduce((s, c) => s + c.rating, 0) / competitors.length
  if (avgRating < 4.3) {
    opportunities.push('整体评分不高，品质升级有机会')
  }

  // 检查 A+ 内容覆盖率
  const aPlusRate = competitors.filter(c => c.a_plus_content).length / competitors.length
  if (aPlusRate < 0.5) {
    opportunities.push('多数竞品无 A+ 内容，可通过品牌故事突围')
  }

  // 检查 BSR 分布
  const highBsrCount = competitors.filter(c => c.bsr_rank > 15000).length
  if (highBsrCount > competitors.length / 2) {
    opportunities.push('多数竞品 BSR 不高，新进入者有机会快速起量')
  }

  opportunities.push('结合痛点分析结果，针对性改进 Top 差评问题')

  return opportunities.slice(0, 4)
}

// 生成对比总结
const generateComparisonSummary = (competitors: MockCompetitor[], leader: MockCompetitor): string => {
  const avgPrice = competitors.reduce((s, c) => s + c.price, 0) / competitors.length
  const avgRating = competitors.reduce((s, c) => s + c.rating, 0) / competitors.length
  const avgScore = competitors.reduce((s, c) => s + c.listing_quality_score, 0) / competitors.length

  return `当前市场由 ${leader.brand}（ASIN: ${leader.asin}）领跑，均价约 $${avgPrice.toFixed(1)}，平均评分 ${avgRating.toFixed(1)}。` +
         `各竞品 Listing 质量参差不齐（平均 ${avgScore.toFixed(0)} 分），` +
         `${competitors.filter(c => !c.a_plus_content).length}/${competitors.length} 缺少 A+ 内容。` +
         `市场存在差异化空间，新进入者可通过解决共性痛点建立竞争优势。`
}

// 生成建议
const generateRecommendation = (competitors: MockCompetitor[], leader: MockCompetitor): string => {
  const lowestPrice = Math.min(...competitors.map(c => c.price))
  const highestScore = Math.max(...competitors.map(c => c.listing_quality_score))

  if (leader.price > 30) {
    return `建议走「高品质+合理定价」路线，定价在 $${lowestPrice + 3}-${leader.price - 5} 区间，` +
           `同时将 Listing 质量目标设为 ${highestScore + 5}+ 分，重点优化图片和五点描述。`
  } else if (leader.price < 18) {
    return `建议避免直接价格战，通过「微创新+品牌感」提升溢价能力，` +
           `目标定价 $18-25，用更好的材质和包装支撑价位。`
  } else {
    return `建议采用「精准对标+局部超越」策略，在 ${leader.brand} 的薄弱环节做差异化，` +
           `如提升包装质感、增加使用场景说明、补充视频内容等。`
  }
}

// 重置表单
const resetForm = () => {
  compareForm.value = {
    asins: [''],
    dimensions: ['price', 'quality', 'rating', 'bsr'],
  }
}

// 重置对比
const resetCompare = () => {
  compareResult.value = null
  resetForm()
}
</script>

<style scoped>
.competitor-compare {
  height: 100%;
  overflow-y: auto;
}

/* 顶部 */
.compare-header {
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
  background: var(--bg-hover-light);
  border-radius: 6px;
  font-size: 13px;
  color: #722ed1;
  margin-bottom: 16px;
}

/* 输入区域 */
.input-section { padding: 0 4px; }
.filter-group { margin-bottom: 18px; }
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

/* 竞品选择器 */
.competitor-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

/* 已选预览 */
.selected-preview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.preview-card {
  background: var(--bg-hover-light);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  padding: 10px;
}
.preview-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 6px;
  line-height: 1.4;
}
.preview-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--text-secondary);
}

/* 分析中 */
.analyzing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 24px;
}
.progress-steps { margin-top: 32px; width: 300px; }

</style>
