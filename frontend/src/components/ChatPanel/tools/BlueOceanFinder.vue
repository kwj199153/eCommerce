<template>
  <div class="blue-ocean-finder">
    <!-- ===== 顶部操作栏 ===== -->
    <div class="finder-header">
      <div class="header-left">
        <span class="tool-icon-lg">🌊</span>
        <span class="tool-title">蓝海挖掘</span>
        <a-tag color="default" size="small" class="mode-tag">表单模式</a-tag>
      </div>
      <div class="header-right">
        <a-tooltip title="切换到对话模式，用自然语言描述需求">
          <a-button type="link" size="small" @click="$emit('switchToChat', '帮我找蓝海商品机会')">
            <MessageOutlined /> 切换对话模式
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 辅助提示 -->
    <div class="helper-hint">
      <InfoCircleOutlined />
      基于类目与关键词筛选高需求、低竞争的蓝海候选商品
    </div>

    <!-- ===== 筛选条件表单区 ===== -->
    <div v-if="!hasResults && !isAnalyzing" class="filter-section">
      <a-form
        :model="filterForm"
        :label-col="{ span: 7 }"
        :wrapper-col="{ span: 16 }"
        layout="horizontal"
        size="small"
      >
        <!-- 1. 市场基础（自动带出） -->
        <div class="filter-group">
          <div class="group-title">
            <EnvironmentOutlined /> 市场基础
            <a-tag v-if="currentStore" color="success" size="small">已锁定店铺</a-tag>
          </div>

          <a-form-item label="目标站点">
            <a-select
              v-model:value="filterForm.marketplace"
              placeholder="选择目标站点"
              :disabled="!!currentStore"
              style="width: 100%"
            >
              <a-select-option value="amazon_us">🇺🇸 Amazon US (美国)</a-select-option>
              <a-select-option value="amazon_uk">🇬🇧 Amazon UK (英国)</a-select-option>
              <a-select-option value="amazon_de">🇩🇪 Amazon DE (德国)</a-select-option>
              <a-select-option value="amazon_jp">🇯🇵 Amazon JP (日本)</a-select-option>
              <a-select-option value="shopee_my">🇲🇾 Shopee MY (马来西亚)</a-select-option>
              <a-select-option value="shopee_tw">🇹🇼 Shopee TW (台湾)</a-select-option>
              <a-select-option value="shopee_sg">🇸🇬 Shopee SG (新加坡)</a-select-option>
            </a-select>
          </a-form-item>

          <a-form-item label="类目选择">
            <a-cascader
              v-model:value="filterForm.category"
              :options="categoryOptions"
              placeholder="选择亚马逊/平台类目"
              change-on-select
              style="width: 100%"
            />
          </a-form-item>
        </div>

        <!-- 2. 价格区间 -->
        <div class="filter-group">
          <div class="group-title"><DollarOutlined /> 价格区间</div>
          <a-input-group compact>
            <a-form-item label="" :wrapper-col="{ span: 24 }" style="margin-bottom: 0">
              <a-input-number
                v-model:value="filterForm.priceMin"
                placeholder="最低售价"
                :min="0"
                :precision="2"
                prefix="$"
                style="width: 50%"
                addon-before="售价"
              />
              <a-input-number
                v-model:value="filterForm.priceMax"
                placeholder="最高售价"
                :min="0"
                :precision="2"
                prefix="$"
                style="width: 50%"
              />
            </a-form-item>
          </a-input-group>
        </div>

        <!-- 3. 竞争筛选条件（蓝海核心规则） -->
        <div class="filter-group highlight">
          <div class="group-title"><AimOutlined /> 竞争筛选（蓝海核心规则）</div>

          <a-form-item label="评论数上限">
            <a-input-number
              v-model:value="filterForm.maxReviews"
              placeholder="例：≤100 控制低竞争"
              :min="0"
              :max="10000"
              style="width: 100%"
              addon-after="条"
            >
              <template #prefix><span style="color: #fa8c16;">≤</span></template>
            </a-input-number>
            <div class="field-hint">评论越少，竞争越小，蓝海机会越大</div>
          </a-form-item>

          <a-form-item label="最小月销量">
            <a-input-number
              v-model:value="filterForm.minMonthlySales"
              placeholder="保证市场需求"
              :min="0"
              :max="50000"
              style="width: 100%"
              addon-after="件/月"
            >
              <template #prefix><span style="color: #52c41a;">≥</span></template>
            </a-input-number>
            <div class="field-hint">有销量证明有真实需求</div>
          </a-form-item>

          <a-form-item label="最低目标 ROI">
            <a-input-number
              v-model:value="filterForm.minRoi"
              placeholder="过滤无利润产品"
              :min="0"
              :max="500"
              :precision="1"
              style="width: 100%"
              addon-after="%"
            >
              <template #prefix><span style="color: #1890ff;">≥</span></template>
            </a-input-number>
            <div class="field-hint">建议设置 20% 以上确保盈利空间</div>
          </a-form-item>
        </div>

        <!-- 4. 高级筛选（默认折叠） -->
        <a-collapse ghost>
          <a-collapse-panel key="advanced" header="高级筛选选项">
            <div class="advanced-options">
              <a-checkbox v-model:checked="filterForm.excludeSeasonal">
                <span>排除季节性商品</span>
                <span class="option-desc">如圣诞装饰、泳衣等季节性强的产品</span>
              </a-checkbox>
              <a-checkbox v-model:checked="filterForm.excludeBrandDominant">
                <span>排除品牌垄断商品</span>
                <span class="option-desc">头部品牌市占率 >60% 的类目</span>
              </a-checkbox>
              <a-checkbox v-model:checked="filterForm.excludeHighRisk">
                <span>排除侵权高危品类</span>
                <span class="option-desc">涉及专利/商标风险的敏感品类</span>
              </a-checkbox>
            </div>
          </a-collapse-panel>
        </a-collapse>
      </a-form>

      <!-- 底部操作按钮 -->
      <div class="form-actions">
        <a-button @click="resetFilters">
          <ReloadOutlined /> 重置条件
        </a-button>
        <a-button type="primary" :loading="isAnalyzing" @click="startAnalysis">
          <SearchOutlined /> 开始挖掘分析
        </a-button>
      </div>
    </div>

    <!-- ===== 加载状态 ===== -->
    <div v-if="isAnalyzing" class="analyzing-state">
      <div class="loading-animation">
        <a-spin size="large" />
        <div class="loading-waves">
          <span></span><span></span><span></span>
        </div>
      </div>
      <h3>AI 正在批量采集市场数据</h3>
      <p class="loading-hint">预计耗时 1-3 分钟，请耐心等待...</p>
      <a-steps :current="analysisStep" size="small" style="max-width: 400px; margin: 20px auto;">
        <a-step title="采集商品数据" />
        <a-step title="计算竞争指标" />
        <a-step title="蓝海评分排序" />
        <a-step title="生成分析报告" />
      </a-steps>
    </div>

    <!-- ===== 结果列表面板 ===== -->
    <div v-if="hasResults && !isAnalyzing" class="results-section">
      <!-- 结果统计栏 -->
      <div class="results-bar">
        <div class="stats">
          <a-statistic title="候选商品" :value="results.length" suffix="个" :value-style="{ fontSize: '18px' }" />
          <a-divider type="vertical" />
          <a-statistic title="优质蓝海" :value="premiumCount" suffix="个" :value-style="{ color: '#52c41a', fontSize: '18px' }" />
          <a-divider type="vertical" />
          <a-statistic title="一般潜力" :value="moderateCount" suffix="个" :value-style="{ color: '#faad14', fontSize: '18px' }" />
          <a-divider type="vertical" />
          <a-statistic title="高竞争" :value="highCompetitionCount" suffix="个" :value-style="{ color: '#ff4d4f', fontSize: '18px' }" />
        </div>
        <div class="result-actions">
          <a-button size="small" @click="exportCSV">
            <DownloadOutlined /> 导出 CSV
          </a-button>
          <a-button size="small" @click="resetAndBack">
            <EditOutlined /> 重新筛选
          </a-button>
        </div>
      </div>

      <!-- 商品结果表格 -->
      <a-table
        :columns="tableColumns"
        :data-source="results"
        :pagination="{ pageSize: 10, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条记录` }"
        :row-class-name="rowClassName"
        size="middle"
        row-key="asin"
      >
        <!-- 蓝海评分列 -->
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'blue_ocean_score'">
            <div class="score-cell">
              <a-progress
                :percent="record.blue_ocean_score"
                :stroke-color="getScoreColor(record.blue_ocean_score)"
                :show-info="false"
                size="small"
                style="width: 60px"
              />
              <span class="score-value" :style="{ color: getScoreColor(record.blue_ocean_score) }">
                {{ record.blue_ocean_score }}
              </span>
            </div>
          </template>

          <!-- 商品标题列 -->
          <template v-if="column.key === 'title'">
            <div class="title-cell">
              <img v-if="record.main_image" class="title-thumb" :src="record.main_image" alt="" loading="lazy" @error="onImgError" />
              <span class="title-thumb-ph" v-else>🖼️</span>
              <a-tooltip :title="record.title">
                <span class="title-text">{{ record.title }}</span>
              </a-tooltip>
            </div>
          </template>

          <!-- ROI 列 -->
          <template v-if="column.key === 'roi_estimated'">
            <span :class="{ 'roi-positive': record.roi_estimated >= filterForm.minRoi, 'roi-negative': record.roi_estimated < filterForm.minRoi }">
              {{ record.roi_estimated }}%
            </span>
          </template>

          <!-- 操作列 -->
          <template v-if="column.key === 'action'">
            <a-space>
              <a-tooltip title="利润测算">
                <a-button type="link" size="small" @click="openProfitCalc(record)">
                  <CalculatorOutlined /> 利润测算
                </a-button>
              </a-tooltip>
              <a-tooltip title="查看竞品详情">
                <a-button type="link" size="small" @click="viewCompetitorDetail(record)">
                  <EyeOutlined /> 竞品详情
                </a-button>
              </a-tooltip>
              <a-tooltip title="添加至产品库">
                <a-button type="link" size="small" @click="addToProductLibrary(record)">
                  <PlusCircleOutlined /> 入库
                </a-button>
              </a-tooltip>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>

    <!-- ===== 初始空白状态 ===== -->
    <div v-if="!hasResults && !isAnalyzing && !showFilterForm" class="initial-empty-state">
      <div class="empty-icon">🌊</div>
      <h3>蓝海挖掘工具</h3>
      <p>设置市场筛选条件，点击「开始挖掘」获取蓝海商品清单</p>
      <a-button type="primary" @click="showFilterForm = true">
        <SearchOutlined /> 开始设置筛选条件
      </a-button>
    </div>

    <!-- ===== 无结果状态 ===== -->
    <div v-if="noResults && !isAnalyzing" class="no-results-state">
      <a-result
        status="warning"
        title="未找到符合筛选条件的蓝海商品"
        sub-title="请放宽筛选参数重新挖掘"
      >
        <template #extra>
          <a-button type="primary" @click="resetAndBack">
            <EditOutlined /> 调整筛选条件
          </a-button>
        </template>
      </a-result>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  MessageOutlined, InfoCircleOutlined, EnvironmentOutlined,
  DollarOutlined, AimOutlined, ReloadOutlined, SearchOutlined,
  DownloadOutlined, EditOutlined, CalculatorOutlined, EyeOutlined,
  PlusCircleOutlined,
} from '@ant-design/icons-vue'
import { message, Modal } from 'ant-design-vue'
import { useShopStore } from '@/stores/shop'
// 使用统一 Mock 数据源
import {
  MOCK_PRODUCTS,
  getMockPainPointAnalysis,
  getMockCompetitorComparison,
  type MockProduct,
} from '@/mock/data'

// Props & Emits
const emit = defineEmits<{
  (e: 'switchToChat', question: string): void
  (e: 'resultReady', data: any): void
}>()

// 店铺上下文
const shopStore = useShopStore()
const currentStore = computed(() => shopStore.currentShop)

// ========== 状态 ==========

const isAnalyzing = ref(false)
const analysisStep = ref(0)
const showFilterForm = ref(true)
const results = ref<any[]>([])

// ========== 筛选表单 ==========

const filterForm = reactive({
  marketplace: '',
  category: [] as string[],
  priceMin: undefined as number | undefined,
  priceMax: undefined as number | undefined,
  maxReviews: 100,
  minMonthlySales: 100,
  minRoi: 20,
  excludeSeasonal: false,
  excludeBrandDominant: false,
  excludeHighRisk: false,
})

// 类目选项（MVP 阶段简化）
const categoryOptions = [
  {
    value: 'home_kitchen',
    label: 'Home & Kitchen',
    children: [
      { value: 'kitchen_dining', label: 'Kitchen & Dining' },
      { value: 'home_decor', label: 'Home Decor' },
      { value: 'bedding_bath', label: 'Bedding & Bath' },
      { value: 'furniture', label: 'Furniture' },
    ],
  },
  {
    value: 'sports_outdoors',
    label: 'Sports & Outdoors',
    children: [
      { value: 'fitness', label: 'Fitness Accessories' },
      { value: 'camping', label: 'Camping & Hiking' },
      { value: 'team_sports', label: 'Team Sports' },
    ],
  },
  {
    value: 'beauty_personal_care',
    label: 'Beauty & Personal Care',
    children: [
      { value: 'skin_care', label: 'Skin Care' },
      { value: 'hair_care', label: 'Hair Care' },
      { value: 'makeup', label: 'Makeup' },
    ],
  },
  {
    value: 'toys_games',
    label: 'Toys & Games',
    children: [
      { value: 'educational', label: 'Educational Toys' },
      { value: 'outdoor_play', label: 'Outdoor Play' },
      { value: 'games', label: 'Games' },
    ],
  },
  {
    value: 'electronics',
    label: 'Electronics',
    children: [
      { value: 'accessories', label: 'Electronics Accessories' },
      { value: 'audio', label: 'Audio Equipment' },
      { value: 'camera_photo', label: 'Camera & Photo' },
    ],
  },
  {
    value: 'pet_supplies',
    label: 'Pet Supplies',
    children: [
      { value: 'dog_supplies', label: 'Dog Supplies' },
      { value: 'cat_supplies', label: 'Cat Supplies' },
      { value: 'aquarium', label: 'Aquarium & Fish' },
    ],
  },
]

// ========== 计算属性 ==========

const hasResults = computed(() => results.value.length > 0)
const noResults = computed(() => !isAnalyzing.value && results.value.length === 0 && showFilterForm.value === false)

const premiumCount = computed(() => results.value.filter(r => r.blue_ocean_score >= 70).length)
const moderateCount = computed(() => results.value.filter(r => r.blue_ocean_score >= 40 && r.blue_ocean_score < 70).length)
const highCompetitionCount = computed(() => results.value.filter(r => r.blue_ocean_score < 40).length)

// 表格列定义
const tableColumns = [
  {
    title: 'ASIN',
    dataIndex: 'asin',
    key: 'asin',
    width: 110,
    fixed: 'left' as const,
  },
  {
    title: '商品标题',
    dataIndex: 'title',
    key: 'title',
    width: 250,
    ellipsis: true,
  },
  {
    title: '售价',
    dataIndex: 'price',
    key: 'price',
    width: 80,
    sorter: (a: any, b: any) => a.price - b.price,
  },
  {
    title: '预估月销',
    dataIndex: 'estimated_monthly_sales',
    key: 'estimated_monthly_sales',
    width: 90,
    sorter: (a: any, b: any) => a.estimated_monthly_sales - b.estimated_monthly_sales,
  },
  {
    title: '评论数量',
    dataIndex: 'review_count',
    key: 'review_count',
    width: 85,
    sorter: (a: any, b: any) => a.review_count - b.review_count,
  },
  {
    title: 'ROI 预估',
    dataIndex: 'roi_estimated',
    key: 'roi_estimated',
    width: 90,
    sorter: (a: any, b: any) => a.roi_estimated - b.roi_estimated,
  },
  {
    title: '蓝海评分',
    dataIndex: 'blue_ocean_score',
    key: 'blue_ocean_score',
    width: 130,
    sorter: (a: any, b: any) => a.blue_ocean_score - b.blue_ocean_score,
    defaultSortOrder: 'descend' as const,
  },
  {
    title: '操作',
    key: 'action',
    width: 220,
    fixed: 'right' as const,
  },
]

// ========== 方法 ==========

// 获取评分颜色
const getScoreColor = (score: number): string => {
  if (score >= 70) return '#52c41a'   // 绿色 - 优质蓝海
  if (score >= 40) return '#faad14'   // 黄色 - 一般
  return '#ff4d4f'                     // 红色 - 高竞争
}

// 图片加载失败隐藏破图
const onImgError = (e: Event) => {
  ;(e.target as HTMLImageElement).style.display = 'none'
}

// 行样式
const rowClassName = (record: any): string => {
  if (record.blue_ocean_score >= 70) return 'row-premium'
  if (record.blue_ocean_score >= 40) return 'row-moderate'
  return 'row-high-competition'
}

// 重置筛选条件
const resetFilters = () => {
  filterForm.marketplace = currentStore.value?.platform || ''
  filterForm.category = []
  filterForm.priceMin = undefined
  filterForm.priceMax = undefined
  filterForm.maxReviews = 100
  filterForm.minMonthlySales = 100
  filterForm.minRoi = 20
  filterForm.excludeSeasonal = false
  filterForm.excludeBrandDominant = false
  filterForm.excludeHighRisk = false
}

// 开始分析
const startAnalysis = async () => {
  // 基础验证
  if (!filterForm.marketplace && !currentStore.value) {
    message.warning('请选择目标站点')
    return
  }

  isAnalyzing.value = true
  showFilterForm.value = false
  results.value = []
  analysisStep.value = 0

  // 模拟分析步骤（Mock 数据快速响应）
  const steps = [
    { step: 1, delay: 200 },
    { step: 2, delay: 250 },
    { step: 3, delay: 200 },
    { step: 4, delay: 150 },
  ]

  for (const s of steps) {
    await new Promise(resolve => setTimeout(resolve, s.delay))
    analysisStep.value = s.step
  }

  // 生成模拟数据（MVP 阶段）
  results.value = generateMockResults()

  isAnalyzing.value = false

  // 触发事件
  emit('resultReady', {
    type: 'blue_ocean_analysis',
    filters: { ...filterForm },
    results: results.value,
    summary: {
      total: results.value.length,
      premium: premiumCount.value,
      moderate: moderateCount.value,
      highCompetition: highCompetitionCount.value,
    },
  })

  message.success(`挖掘完成！发现 ${results.value.length} 个候选商品`)
}

// 生成模拟结果数据（使用统一 Mock 数据源）
const generateMockResults = (): any[] => {
  // 从统一 Mock 数据池获取商品
  let candidates: MockProduct[] = [...MOCK_PRODUCTS]

  // 如果选择了类目，优先使用该类目商品
  if (filterForm.category.length > 0) {
    const targetCategory = filterForm.category[0]
    const categoryProducts = MOCK_PRODUCTS.filter(p =>
      p.category_path.some(c => c.toLowerCase().includes(targetCategory.replace('_', ' ').toLowerCase()))
    )
    if (categoryProducts.length > 0) {
      candidates = categoryProducts
      // 补充其他类目的商品使结果更丰富
      const others = MOCK_PRODUCTS.filter(p => !categoryProducts.includes(p)).slice(0, 3)
      candidates = [...candidates, ...others]
    }
  }

  // 根据筛选条件过滤
  let filtered = candidates.filter(p => {
    if (filterForm.priceMin && p.price < filterForm.priceMin) return false
    if (filterForm.priceMax && p.price > filterForm.priceMax) return false
    if (filterForm.maxReviews && p.review_count > filterForm.maxReviews) return false
    if (filterForm.minMonthlySales && p.estimated_monthly_sales < filterForm.minMonthlySales) return false
    if (filterForm.minRoi && p.roi_estimated < filterForm.minRoi) return false
    // 高级筛选
    if (filterForm.excludeSeasonal && ['Christmas', 'Holiday', 'Swimwear'].some(s => p.title.includes(s))) return false
    if (filterForm.excludeBrandDominant && p.review_count > 500) return false
    if (filterForm.excludeHighRisk && ['Patent', 'Trademark', 'Disney', 'Marvel'].some(s => p.title.includes(s))) return false
    return true
  })

  // 如果过滤后为空，返回评分最高的部分商品作为"接近匹配"
  if (filtered.length === 0) {
    filtered = [...MOCK_PRODUCTS].sort((a, b) => b.blue_ocean_score - a.blue_ocean_score).slice(0, 5)
  }

  // 转换为表格格式（蓝海评分已在 Mock 数据中预计算）
  return filtered.map(p => ({
    asin: p.asin,
    title: p.title,
    main_image: p.main_image,
    price: p.price,
    estimated_monthly_sales: p.estimated_monthly_sales,
    review_count: p.review_count,
    roi_estimated: p.roi_estimated,
    blue_ocean_score: p.blue_ocean_score,
    marketplace: p.marketplace,
    category: p.category_path.join(' > '),
    // 携带完整产品数据供操作按钮使用
    _fullProduct: p,
  })).sort((a, b) => b.blue_ocean_score - a.blue_ocean_score)
}

// 打开利润测算（使用 Mock 完整数据）
const openProfitCalc = (record: any) => {
  const product = record._fullProduct
  if (product) {
    // 携带完整产品数据到利润测算
    emit('switchToChat', `请对以下商品进行利润测算：\nASIN: ${product.asin}\n标题: ${product.title.slice(0, 60)}...\n售价: $${product.price}\n采购成本: $${product.cost_price}\n重量: ${product.weight_lbs} lbs\n尺寸: ${product.dimensions}`)
  } else {
    emit('switchToChat', `请对以下商品进行利润测算：\nASIN: ${record.asin}\n标题: ${record.title}\n售价: $${record.price}`)
  }
}

// 查看竞品详情（使用 Mock 数据）
const viewCompetitorDetail = (record: any) => {
  // 使用统一 Mock 数据生成竞品对比
  const relatedASINs = MOCK_PRODUCTS
    .filter(p => p.category === record._fullProduct?.category || p.marketplace === record.marketplace)
    .slice(0, 4)
    .map(p => p.asin)

  if (relatedASINs.length < 2) {
    // 如果同类商品不足，随机选取
    relatedASINs.push(...MOCK_PRODUCTS.filter(p => !relatedASINs.includes(p.asin)).slice(0, 4 - relatedASINs.length).map(p => p.asin))
  }

  const comparison = getMockCompetitorComparison(relatedASINs)
  console.log('竞品对比数据:', comparison)

  message.info(`正在查询 ${record.asin} 的竞品信息...`)
  emit('switchToChat', `请分析 ${record.title.slice(0, 40)}... (${record.asin}) 的竞品情况，包括价格区间、主要竞争对手、市场占有率等`)
}

// 添加到产品库
const addToProductLibrary = (record: any) => {
  Modal.confirm({
    title: '添加到产品库',
    content: `确定将 "${record.title}" 添加到产品库吗？`,
    okText: '确认添加',
    cancelText: '取消',
    onOk() {
      message.success(`已将 ${record.asin} 添加到产品库`)
      // TODO: 调用后端 API 保存到产品库
    },
  })
}

// 导出 CSV
const exportCSV = () => {
  if (results.value.length === 0) {
    message.warning('没有可导出的数据')
    return
  }

  const headers = ['ASIN', '商品标题', '售价($)', '预估月销', '评论数', 'ROI(%)', '蓝海评分']
  const rows = results.value.map(r => [
    r.asin,
    `"${r.title}"`,
    r.price,
    r.estimated_monthly_sales,
    r.review_count,
    r.roi_estimated,
    r.blue_ocean_score,
  ])

  const csvContent = [headers.join(','), ...rows.map(row => row.join(','))].join('\n')
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `蓝海挖掘_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)

  message.success('导出成功')
}

// 重置并返回筛选
const resetAndBack = () => {
  results.value = []
  showFilterForm.value = true
  resetFilters()
}

// 组件挂载时初始化站点
onMounted(() => {
  if (currentStore.value) {
    filterForm.marketplace = currentStore.value.platform
  }
})
</script>

<style scoped>
.blue-ocean-finder {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

/* ===== 顶部操作栏 ===== */
.finder-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--border-base);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-icon-lg {
  font-size: 24px;
}

.tool-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.mode-tag {
  font-size: 11px;
}

/* 辅助提示 */
.helper-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 12px;
  color: var(--text-tertiary);
  background-color: var(--bg-hover-light);
  border-bottom: 1px solid var(--border-base);
  flex-shrink: 0;
}

/* ===== 筛选区域 ===== */
.filter-section {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.filter-group {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}

.filter-group.highlight {
  border-color: #bae7ff;
  background: linear-gradient(to bottom, #e6f7ff 0%, var(--bg-elevated) 30%);
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.field-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* 高级选项 */
.advanced-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.advanced-options .ant-checkbox-wrapper {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}

.option-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: 24px;
}

/* 底部按钮 */
.form-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-base);
}

.form-actions .ant-btn {
  flex: 1;
}

/* ===== 加载状态 ===== */
.analyzing-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.loading-animation {
  position: relative;
  margin-bottom: 20px;
}

.loading-waves {
  position: absolute;
  bottom: -10px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 4px;
}

.loading-waves span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  animation: wave 1.4s ease-in-out infinite;
}

.loading-waves span:nth-child(2) { animation-delay: 0.2s; }
.loading-waves span:nth-child(3) { animation-delay: 0.4s; }

@keyframes wave {
  0%, 100% { transform: translateY(0); opacity: 0.4; }
  50% { transform: translateY(-10px); opacity: 1; }
}

.analyzing-state h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: var(--text-primary);
}

.loading-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  margin: 0;
}

/* ===== 结果区域 ===== */
.results-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
  overflow: hidden;
}

.results-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-hover-light);
  border-radius: 8px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.results-bar .stats {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-actions {
  display: flex;
  gap: 8px;
}

/* 评分单元格 */
.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 标题单元格 */
.title-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--border-base);
  flex-shrink: 0;
  background: var(--bg-hover-light);
}

.title-thumb-ph {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  border-radius: 4px;
  background: var(--bg-hover-light);
  border: 1px solid var(--border-base);
}

.title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
  font-size: 13px;
}

.score-value {
  font-weight: 600;
  font-size: 13px;
  min-width: 28px;
}

/* ROI 样式 */
.roi-positive {
  color: #52c41a;
  font-weight: 500;
}
.roi-negative {
  color: #ff4d4f;
  font-weight: 500;
}

/* 表格行颜色 */
:deep(.row-premium) {
  background-color: #f6ffed !important;
}
:deep(.row-moderate) {
  background-color: #fffbe6 !important;
}
:deep(.row-high-competition) {
  background-color: #fff2f0 !important;
}

:deep(.row-premium:hover > td) {
  background-color: #d9f7be !important;
}
:deep(.row-moderate:hover > td) {
  background-color: #ffe58f !important;
}
:deep(.row-high-competition:hover > td) {
  background-color: #ffa39e !important;
}

/* ===== 空状态 ===== */
.initial-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  gap: 12px;
}

.empty-icon {
  font-size: 64px;
  opacity: 0.6;
}

.initial-empty-state h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-secondary);
}

.initial-empty-state p {
  margin: 0;
  font-size: 13px;
  max-width: 300px;
  text-align: center;
}

.no-results-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
