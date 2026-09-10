<template>
  <div class="listing-optim-config">
    <!-- 当前店铺平台提示（自动跟随店铺属性，无需手动切换） -->
    <a-alert
      class="platform-banner"
      :type="isSimplified ? 'warning' : 'info'"
      show-icon
    >
      <template #message>
        <span class="platform-banner-text">
          🏪 当前店铺平台：<b>{{ getPlatformLabel(currentPlatform) }}</b>
          <span class="platform-mode-hint">
            {{ isSimplified ? '（简化 Listing：短标题 + 商品详情）' : '（完整 Listing：标题 / 五点 / Search Term / A+）' }}
          </span>
        </span>
      </template>
    </a-alert>

    <!-- 统一表单（手动输入 / 产品库回填 共用） -->
    <a-form layout="vertical" :model="form" class="optim-form">

      <!-- 产品名称 -->
      <a-form-item :label="isSimplified ? '商品名称' : '产品名称'" required>
        <a-input
          v-model:value="form.product_name"
          :placeholder="isSimplified ? '例：便携式加湿器 USB静音卧室（Temu/Shopee 短标题）' : '例：便携式加湿器 USB静音卧室'"
          size="large"
          show-count
          :maxlength="isSimplified ? 60 : 100"
        />
      </a-form-item>

      <!-- 品牌 + 站点 -->
      <a-row :gutter="12">
        <a-col :span="12">
          <a-form-item label="品牌名">
            <a-input v-model:value="form.brand" placeholder="例：AirComfort" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="目标站点">
            <a-select v-model:value="form.site">
              <!-- 亚马逊站点 -->
              <template v-if="!isSimplified">
                <a-select-option value="com">美国 (amazon.com)</a-select-option>
                <a-select-option value="co.uk">英国 (amazon.co.uk)</a-select-option>
                <a-select-option value="de">德国 (amazon.de)</a-select-option>
                <a-select-option value="jp">日本 (amazon.co.jp)</a-select-option>
              </template>
              <!-- Temu / Shopee 站点 -->
              <template v-else>
                <a-select-option value="temu_us">Temu 美国站</a-select-option>
                <a-select-option value="temu_uk">Temu 英国站</a-select-option>
                <a-select-option value="shopee_my">Shopee 马来西亚</a-select-option>
                <a-select-option value="shopee_tw">Shopee 台湾</a-select-option>
                <a-select-option value="shopee_ph">Shopee 菲律宾</a-select-option>
                <a-select-option value="shopee_th">Shopee 泰国</a-select-option>
                <a-select-option value="shopee_sg">Shopee 新加坡</a-select-option>
                <a-select-option value="shopee_vn">Shopee 越南</a-select-option>
                <a-select-option value="shopee_id">Shopee 印尼</a-select-option>
              </template>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>

      <!-- 分类 -->
      <a-form-item label="产品分类">
        <a-input v-model:value="form.category" placeholder="例：Home & Kitchen > Humidifiers" />
      </a-form-item>

      <!-- 核心关键词 -->
      <a-form-item :label="isSimplified ? '核心关键词（逗号分隔，用于站内搜索）' : '核心关键词 / Search Term（逗号分隔）'">
        <a-textarea
          v-model:value="form.keywords_str"
          :placeholder="isSimplified ? '加湿器, 静音, 卧室, USB, 便携' : 'portable humidifier, mini humidifier, bedroom humidifier, quiet, usb'"
          :auto-size="{ minRows: 2, maxRows: 4 }"
        />
      </a-form-item>

      <!-- 竞品 ASIN（仅亚马逊模式，Temu/Shopee 用站内竞品链接更合适） -->
      <a-form-item v-if="!isSimplified" label="竞品 ASIN（可选，用于对标分析）">
        <div class="input-with-picker">
          <a-select
            v-model:value="form.competitors"
            mode="tags"
            placeholder="输入竞品 ASIN，回车添加"
            style="flex: 1"
          />
          <ProductPickerButton
            :model-value="selectedCompetitorProduct"
            @select="onCompetitorSelect"
          />
        </div>
      </a-form-item>

      <!-- 核心卖点 -->
      <a-form-item label="核心卖点 / 差异化亮点">
        <a-textarea
          v-model:value="form.selling_points"
          :placeholder="isSimplified ? '例：300ml大容量、2档雾量调节、7色夜灯、自动断电' : '例：300ml大容量、2档雾量调节、7色夜灯、自动断电保护'"
          :auto-size="{ minRows: 2, maxRows: 4 }"
        />
      </a-form-item>

      <!-- 简化模式：商品详情（Temu/Shopee） -->
      <a-form-item v-if="isSimplified" label="商品详情（详情页描述）">
        <a-textarea
          v-model:value="form.detail_desc"
          placeholder="填写商品的完整详情描述，AI 将据此生成结构化商品详情页文案…"
          :auto-size="{ minRows: 4, maxRows: 8 }"
        />
      </a-form-item>

      <!-- 分隔线 -->
      <a-divider style="margin: 16px 0 12px" />

      <!-- 生成选项：本工具只产出标题（+ Temu/Shopee 商品详情），五点/A+ 走各自独立工具 -->
      <div class="option-section">
        <div class="section-title">生成内容</div>
        <div class="scope-hint">
          <span class="scope-tag">{{ isSimplified ? '短标题 + 商品详情' : '标题（含备选变体）' }}</span>
          <span class="scope-note">
            {{ isSimplified
              ? 'Temu/Shopee 模式一次产出短标题与结构化商品详情'
              : '仅生成标题与备选变体；五点描述、A+ 文案请用各自独立工具' }}
          </span>
        </div>
      </div>

      <div class="option-section">
        <div class="section-title">优化风格</div>
        <a-select v-model:value="genOptions.style" style="width: 100%">
          <a-select-option value="conversion">高转化型（突出卖点+痛点解决）</a-select-option>
          <a-select-option value="seo">SEO 权重型（关键词密集覆盖）</a-select-option>
          <a-select-option value="brand">品牌调性型（故事化+情感连接）</a-select-option>
          <a-select-option value="balanced">均衡型（转化+SEO平衡）</a-select-option>
        </a-select>
      </div>

      <div class="option-section">
        <div class="section-title">语言</div>
        <a-radio-group v-model:value="genOptions.language" size="small">
          <a-radio-button value="zh">中文</a-radio-button>
          <a-radio-button value="en">English</a-radio-button>
        </a-radio-group>
      </div>
    </a-form>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <a-button
        type="primary"
        block
        size="large"
        @click="handleGenerate"
        :loading="generating"
        :disabled="!form.product_name.trim()"
      >
        <ThunderboltOutlined /> {{ isSimplified ? '生成商品详情' : (workingProduct ? '开始生成 Listing' : '生成文案') }}
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, inject, onMounted, computed } from 'vue'
import {
  ThunderboltOutlined, ReloadOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import { useShopStore } from '@/stores/shop'
import { getPlatformMode, isSimplifiedListingMode, getPlatformLabel } from '@/utils/platform'

const props = defineProps<{
  workingProduct?: any
}>()

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const generating = ref(false)

// ====== 店铺平台（自动切换 Listing 字段，无需手动按钮） ======
const shopStore = useShopStore()
const currentPlatform = computed(() => shopStore.currentShop?.platform || null)
const platformMode = computed(() => getPlatformMode(currentPlatform.value))
// 简化模式：Temu / Shopee → 短标题 + 商品详情（隐藏五点/Search Term/A+）
const isSimplified = computed(() => isSimplifiedListingMode(currentPlatform.value))

// ====== 统一表单数据 ======
const form = reactive({
  product_name: '',
  brand: '',
  site: 'com',
  category: '',
  keywords_str: '',
  competitors: [] as string[],
  selling_points: '',
  // 简化模式：短标题 + 商品详情
  short_title: '',
  detail_desc: '',
})

// ====== 生成选项（本工具只产出标题，无「生成内容」多选）======
const genOptions = reactive({
  style: 'balanced',
  language: 'zh',
})

// ====== 监听工作商品变化 → 自动回填到表单 ======
watch(() => props.workingProduct, (product) => {
  if (product) {
    // 自动回填所有字段
    form.product_name = product.title || ''
    form.brand = product.brand || ''
    form.category = product.category || ''

    // 站点映射
    if (product.site) {
      const siteMap: Record<string, string> = {
        'Amazon US': 'com', 'Amazon UK': 'co.uk',
        'Amazon DE': 'de', 'Amazon JP': 'jp',
      }
      form.site = siteMap[product.site] || 'com'
    }

    // 关键词
    if (product.keywords?.length) {
      form.keywords_str = product.keywords.join(', ')
    }

    // 竞品 ASIN
    if (product.competitor_asins?.length) {
      form.competitors = [...product.competitor_asins]
    }

    // 卖点
    if (product.selling_points) {
      form.selling_points = product.selling_points
    }
  }
}, { immediate: true })

// ====== 平台切换 → 站点默认值跟随店铺平台 ======
const AMAZON_SITES = ['com', 'co.uk', 'de', 'jp']
const SIMPLIFIED_SITES = ['temu_us', 'temu_uk', 'shopee_my', 'shopee_tw', 'shopee_ph', 'shopee_th', 'shopee_sg', 'shopee_vn', 'shopee_id']

// 各平台的首个默认站点
function getDefaultSite(simplified: boolean): string {
  return simplified ? 'temu_us' : 'com'
}

watch(platformMode, (mode, prev) => {
  if (mode === prev) return

  const validSites = isSimplified.value ? SIMPLIFIED_SITES : AMAZON_SITES
  // 仅当当前站点不属于新平台时，才重置为该平台默认站点（避免覆盖用户已选）
  if (!validSites.includes(form.site)) {
    form.site = getDefaultSite(isSimplified.value)
  }
})

// 从 localStorage 恢复
onMounted(() => {
  const savedForm = localStorage.getItem('listing-optim-form')
  if (savedForm && !props.workingProduct) {
    try { Object.assign(form, JSON.parse(savedForm)) } catch {}
  }

  const savedGenOpts = localStorage.getItem('listing-optim-genopts')
  if (savedGenOpts) try { Object.assign(genOptions, JSON.parse(savedGenOpts)) } catch {}
})

// ====== 表单提交 ======// 提交生成
const handleGenerate = () => {
  if (!form.product_name.trim()) {
    return message.warning('请输入产品名称')
  }

  const params: any = {
    source: props.workingProduct ? 'product_library' : 'manual_input',
    product_name: form.product_name,
    brand: form.brand,
    site: form.site,
    category: form.category,
    keywords: form.keywords_str.split(',').map((s: string) => s.trim()).filter(Boolean),
    competitors: form.competitors,
    selling_points: form.selling_points,
    // 平台信息（驱动后端/结果按平台返回不同结构）
    platform: currentPlatform.value,
    platform_mode: platformMode.value,
    is_simplified: isSimplified.value,
    // 简化模式字段
    short_title: form.short_title,
    detail_desc: form.detail_desc,
    ...genOptions,
  }

  // 如果来自产品库，补充产品 ID 和原始数据
  if (props.workingProduct) {
    params.product_id = props.workingProduct.id
    params.asin = props.workingProduct.asin
    params.cost_price = props.workingProduct.cost
    params.selling_price = props.workingProduct.price
  }

  // 保存表单到 localStorage
  localStorage.setItem('listing-optim-form', JSON.stringify(form))
  localStorage.setItem('listing-optim-genopts', JSON.stringify(genOptions))

  generating.value = true
  setTimeout(() => {
    generating.value = false
    emit('startAnalysis', params)
  }, 600)
}

// 重置
const handleReset = () => {
  Object.assign(form, {
    product_name: '', brand: '', site: getDefaultSite(isSimplified.value), category: '',
    keywords_str: '', competitors: [], selling_points: '',
    short_title: '', detail_desc: '',
  })
  Object.assign(genOptions, { style: 'balanced', language: 'zh' })
  localStorage.removeItem('listing-optim-form')
  localStorage.removeItem('listing-optim-genopts')
  selectedCompetitorProduct.value = null
}

// ====== 产品库选择（竞品 ASIN）======
const selectedCompetitorProduct = ref<any>(null)

const onCompetitorSelect = (product: any) => {
  selectedCompetitorProduct.value = product
  // 将选中商品的 ASIN 添加到竞品列表（避免重复）
  if (product.asin && !form.competitors.includes(product.asin)) {
    form.competitors = [...form.competitors, product.asin]
  }
}
</script>

<style scoped>
.listing-optim-config {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 平台提示条 */
.platform-banner {
  flex-shrink: 0;
  margin-bottom: 12px;
}

.platform-banner-text {
  font-size: 12px;
}

.platform-mode-hint {
  margin-left: 8px;
  color: #8c8c8c;
  font-size: 11px;
}

/* 表单区域 */
.optim-form {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}

.option-section {
  margin-bottom: 12px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #595959;
  margin-bottom: 6px;
}

/* 生成内容作用域提示（本工具只出标题，替代原无效的多选勾选组） */
.scope-hint {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px dashed var(--border-base, #d9d9d9);
  border-radius: 6px;
  background: var(--bg-hover-light, #fafafa);
}

.scope-tag {
  align-self: flex-start;
  font-size: 12px;
  font-weight: 600;
  color: var(--primary, #1890ff);
  background: rgba(24, 144, 255, 0.1);
  border-radius: 10px;
  padding: 1px 8px;
}

.scope-note {
  font-size: 12px;
  line-height: 1.6;
  color: #8c8c8c;
}

/* 操作按钮 */
.config-actions {
  padding: 16px 0 0;
  border-top: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
