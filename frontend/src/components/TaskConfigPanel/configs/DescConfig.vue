<template>
  <div class="desc-config">
    <!-- 顶部「载入产品」入口 -->
    <div v-if="workingProduct?.value" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.value.title?.slice(0, 30) }}{{ workingProduct.value.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <a-collapse v-model:activeKey="activeKeys" ghost>
      <a-collapse-panel key="product" header="📦 产品信息">
        <a-form layout="vertical" :model="form">
          <!-- 产品名称：右侧可从产品库选择 -->
          <a-form-item label="产品名称" required>
            <div class="input-with-picker">
              <a-input
                v-model:value="form.product_name"
                placeholder="例：便携式迷你加湿器"
                @change="saveForm"
              />
              <ProductPickerButton
                :model-value="pickedProduct"
                @select="onProductSelect"
              />
            </div>
          </a-form-item>
          <a-form-item label="品牌名称">
            <a-input v-model:value="form.brand_name" placeholder="例：AeroLife" @change="saveForm" />
          </a-form-item>
          <a-form-item label="品牌 Slogan">
            <a-input v-model:value="form.brand_slogan" placeholder="例：Breathe Better, Live Better" @change="saveForm" />
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="style" header="🎨 内容风格">
        <a-form layout="vertical" :model="form">
          <a-form-item label="调性选择">
            <a-radio-group v-model:value="form.tone" @change="saveForm">
              <a-radio-button value="professional">专业科技</a-radio-button>
              <a-radio-button value="warm">温馨生活</a-radio-button>
              <a-radio-button value="luxury">高端奢华</a-radio-button>
              <a-radio-button value="playful">活泼有趣</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="内容模块">
            <a-checkbox-group v-model:value="form.modules" @change="saveForm">
              <div style="display: flex; flex-direction: column; gap: 6px;">
                <a-checkbox value="hero">🖼️ Hero 图文模块（首屏大图+卖点）</a-checkbox>
                <a-checkbox value="highlights">✨ 要点列表模块</a-checkbox>
                <a-checkbox value="comparison">📊 对比表格模块</a-checkbox>
                <a-checkbox value="scenarios">🏠 使用场景模块</a-checkbox>
                <a-checkbox value="specs">📐 规格参数模块</a-checkbox>
                <a-checkbox value="story">📖 品牌故事模块</a-checkbox>
                <a-checkbox value="lifestyle">🌟 Lifestyle 场景图</a-checkbox>
              </div>
            </a-checkbox-group>
          </a-form-item>
          <a-form-item label="目标字数">
            <a-slider
              v-model:value="form.target_words"
              :min="500"
              :max="2000"
              :step="100"
              :marks="{ 800: '800', 1200: '1200', 1600: '1600' }"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="content" header="📝 内容要点">
        <a-form layout="vertical" :model="form">
          <a-form-item label="核心卖点（3-6 个）">
            <a-textarea
              v-model:value="form.key_selling_points"
              :rows="4"
              placeholder="每行一个卖点，可包含具体数据和用户利益点"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="技术规格">
            <a-textarea
              v-model:value="form.specifications"
              :rows="3"
              placeholder="容量/尺寸/材质/认证等参数"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="适用场景">
            <a-select
              v-model:value="form.scenarios"
              mode="tags"
              placeholder="例：卧室、办公室、旅行..."
              style="width: 100%"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="brand" header="🏆 品牌故事（可选）">
        <a-form layout="vertical" :model="form">
          <a-form-item label="品牌起源">
            <a-textarea
              v-model:value="form.brand_origin_story"
              :rows="3"
              placeholder="简述品牌创立背景和理念"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="品质承诺">
            <a-textarea
              v-model:value="form.quality_promise"
              :rows="2"
              placeholder="质保政策、质检流程等"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>
    </a-collapse>

    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleGenerate" :loading="generating">
        <FileTextOutlined /> 生成 A+ 描述
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { FileTextOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// 由 TaskConfigPanel 显式传入载入产品（与 ListingOptimConfig props 方式一致，避免 inject 时序不确定）
const props = defineProps<{ workingProduct?: any }>()
const workingProduct = computed(() => props.workingProduct)

// ====== 表单（先定义 → 让 watch 立即回调能安全读 form.value）======
const activeKeys = ref(['product', 'style'])
const generating = ref(false)
const pickedProduct = ref<any>(null)

const defaultForm = {
  product_name: '',
  brand_name: '',
  brand_slogan: '',
  tone: 'professional',
  modules: ['hero', 'highlights', 'comparison', 'specs'] as string[],
  target_words: 1200,
  key_selling_points: '',
  specifications: '',
  scenarios: [] as string[],
  brand_origin_story: '',
  quality_promise: '',
}

const form = ref({ ...defaultForm })

/** 从工作商品或 Picker 选中的产品回填（产品名/品牌/卖点） */
const fillFromProduct = (p: any) => {
  if (!p) return
  if (p.title) form.value.product_name = p.title
  if (p.brand) form.value.brand_name = p.brand
  if (typeof p.selling_points === 'string' && p.selling_points.trim()) {
    // 产品档案卖点用 ` | `、`、`或`，`分隔 → 转每行一个（对齐 textarea 每行一卖点）
    form.value.key_selling_points = p.selling_points.split(/\s*\|\s*|、|，/).map((s: string) => s.trim()).filter(Boolean).join('\n')
  }
}

/** 本组件「从产品库选择」按钮选中回调 */
const onProductSelect = (product: any) => {
  pickedProduct.value = product
  if (product) {
    fillFromProduct(product)
    saveForm()
    message.success(`已载入产品「${product.title?.slice(0, 20) || ''}」并回填表单`)
  }
}

/** 监听「顶部载入产品」变化自动回填 */
watch(() => workingProduct?.value, (product) => {
  try {
    if (product?.title) {
      nextTick(() => fillFromProduct(product))
    }
  } catch (e) {
    console.error('[DescConfig watch ERROR]', e)
  }
}, { immediate: true })

onMounted(() => {
  // 有载入产品时以产品预填为准，不用 localStorage 旧值覆盖（对齐 title-gen）
  const saved = localStorage.getItem('desc-gen-config')
  if (saved && !workingProduct?.value) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

const saveForm = () => localStorage.setItem('desc-gen-config', JSON.stringify(form.value))

const handleGenerate = () => {
  if (!form.value.product_name.trim()) return message.warning('请填写产品名称')
  if (!form.value.key_selling_points.trim()) return message.warning('请填写核心卖点')
  generating.value = true
  setTimeout(() => {
    generating.value = false
    const src = workingProduct?.value || pickedProduct.value
    const extra = src
      ? { source: 'product_library', product_id: src.id, product_title: src.title, product_asin: src.asin }
      : { source: 'manual_input' }
    emit('startAnalysis', { ...form.value, ...extra })
  }, 800)
}

const handleReset = () => { form.value = { ...defaultForm }; localStorage.removeItem('desc-gen-config') }
</script>

<style scoped>
.desc-config { display: flex; flex-direction: column; height: 100%; }

/* 顶部产品横幅 */
.product-banner {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px; margin-bottom: 8px;
  background: #f0f7ff; border: 1px solid #91caff; border-radius: 4px;
  font-size: 12px; color: #0958d9;
}
.product-banner .banner-icon { font-size: 14px; }

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.input-with-picker .ant-input { flex: 1; }

.desc-config :deep(.ant-collapse) { flex: 1; overflow-y: auto; }
.config-actions { padding: 16px 0 0; border-top: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
</style>
