<template>
  <div class="bullet-config">
    <!-- 顶部「载入产品」入口（参考 StaticAssetConfig 的双入口设计：组件内部也能选产品） -->
    <div v-if="workingProduct?.value" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.value.title?.slice(0, 30) }}{{ workingProduct.value.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <a-collapse v-model:activeKey="activeKeys" ghost>
      <a-collapse-panel key="product" header="📦 产品信息">
        <a-form layout="vertical" :model="form">
          <!-- 产品名称：右侧可从产品库选择（像 StaticAssetConfig/VideoGeneratorConfig 一样） -->
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
          <a-form-item label="目标受众">
            <a-select
              v-model:value="form.target_audience"
              mode="tags"
              placeholder="例：宝妈、上班族、学生..."
              style="width: 100%"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="使用场景">
            <a-select
              v-model:value="form.use_cases"
              mode="tags"
              placeholder="例：卧室、办公室、旅行、婴儿房..."
              style="width: 100%"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="features" header="✨ 产品特性">
        <div class="feature-list">
          <div v-for="(feat, idx) in form.features" :key="idx" class="feature-row">
            <a-input
              v-model:value="form.features[idx].name"
              placeholder="特性名称"
              style="flex: 1"
              @change="saveForm"
            />
            <a-input
              v-model:value="form.features[idx].detail"
              placeholder="具体描述/数据"
              style="flex: 2"
              @change="saveForm"
            />
            <a-button
              type="text"
              danger
              size="small"
              @click="removeFeature(idx)"
              v-if="form.features.length > 1"
            >
              <DeleteOutlined />
            </a-button>
          </div>
          <a-button type="dashed" block size="small" @click="addFeature">
            <PlusOutlined /> 添加特性
          </a-button>
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="style" header="🎨 写作风格">
        <a-form layout="vertical" :model="form">
          <a-form-item label="风格选择">
            <a-radio-group v-model:value="form.style" @change="saveForm">
              <a-radio-button value="professional">专业严谨</a-radio-button>
              <a-radio-button value="warm">亲切温暖</a-radio-button>
              <a-radio-button value="energetic">活力激情</a-radio-button>
              <a-radio-button value="luxury">高端奢华</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="情感触发策略">
            <a-checkbox-group v-model:value="form.emotion_triggers" @change="saveForm">
              <a-checkbox value="fear_avoidance">痛点消除</a-checkbox>
              <a-checkbox value="aspiration">向往憧憬</a-checkbox>
              <a-checkbox value="trust">信任构建</a-checkbox>
              <a-checkbox value="urgency">紧迫感</a-checkbox>
              <a-checkbox value="exclusivity">独特性</a-checkbox>
            </a-checkbox-group>
          </a-form-item>
          <a-form-item label="每点字符数目标">
            <a-slider
              v-model:value="form.target_chars"
              :min="60"
              :max="200"
              :marks="{ 80: '80', 120: '120', 160: '160' }"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="reference" header="📎 参考素材">
        <a-form layout="vertical" :model="form">
          <a-form-item label="竞品 ASIN（可选）">
            <div class="input-with-picker">
              <a-textarea
                v-model:value="form.competitor_asins"
                placeholder="每行一个 ASIN"
                :rows="3"
                style="flex: 1"
                @change="saveForm"
              />
              <ProductPickerButton
                :model-value="selectedCompetitorProduct"
                @select="onCompetitorSelect"
              />
            </div>
          </a-form-item>
          <a-form-item label="已有标题（可选）">
            <a-textarea
              v-model:value="form.existing_title"
              placeholder="粘贴当前标题用于优化"
              :rows="2"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>
    </a-collapse>

    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleGenerate" :loading="generating">
        <ThunderboltOutlined /> 生成五点描述
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// 由 TaskConfigPanel 显式传入载入产品（与 ListingOptimConfig props 方式一致，避免 inject 时序不确定）
const props = defineProps<{ workingProduct?: any }>()
const workingProduct = computed(() => props.workingProduct)

// ====== 表单默认值（在 watch 之前定义，避免 TDZ；fillFromProduct 立即读 form.value）======
const activeKeys = ref(['product', 'features'])
const generating = ref(false)
const pickedProduct = ref<any>(null)  // 当前「从产品库选择」按钮选中的产品（与顶部载入产品并行）

const defaultForm = {
  product_name: '',
  target_audience: [] as string[],
  use_cases: [] as string[],
  features: [
    { name: '', detail: '' },
    { name: '', detail: '' },
    { name: '', detail: '' },
    { name: '', detail: '' },
    { name: '', detail: '' },
  ],
  style: 'professional',
  emotion_triggers: ['trust'] as string[],
  target_chars: 100,
  competitor_asins: '',
  existing_title: '',
}

const form = ref(JSON.parse(JSON.stringify(defaultForm)))

/** 从工作商品（顶部「载入产品」或本组件 Picker 选的产品）全字段回填 */
const fillFromProduct = (p: any) => {
  if (!p) return
  if (p.title) form.value.product_name = p.title
  if (p.competitor_asins?.length) form.value.competitor_asins = p.competitor_asins.join('\n')
  if (p.generated_title) form.value.existing_title = p.generated_title
  // 卖点：产品档案 selling_points 用 ` | ` 分隔 → 拆成多条特性
  if (typeof p.selling_points === 'string' && p.selling_points.trim()) {
    const points = p.selling_points.split('|').map((s: string) => s.trim()).filter(Boolean)
    if (points.length) {
      form.value.features = points.map((pt: string) => ({ name: pt.slice(0, 40), detail: '' }))
    }
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

/** 监听「顶部载入产品」变化自动回填（含 initial mount 时已载入产品） */
watch(() => workingProduct?.value, (product) => {
  try {
    if (product?.title) {
      // 首次挂在时 immediate 触发可能撞 nextTick；统一 nextTick 保证 form 已挂
      nextTick(() => fillFromProduct(product))
    }
  } catch (e) {
    console.error('[BulletConfig watch ERROR]', e)
  }
}, { immediate: true })

onMounted(() => {
  // 有载入产品时以产品预填为准，不用 localStorage 旧值覆盖（对齐 title-gen）
  const saved = localStorage.getItem('bullet-gen-config')
  if (saved && !workingProduct?.value) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

const saveForm = () => localStorage.setItem('bullet-gen-config', JSON.stringify(form.value))

const addFeature = () => form.value.features.push({ name: '', detail: '' })
const removeFeature = (idx: number) => { form.value.features.splice(idx, 1); saveForm() }

const handleGenerate = () => {
  if (!form.value.product_name.trim()) return message.warning('请填写产品名称')
  const validFeatures = form.value.features.filter((f: any) => f.name)
  if (validFeatures.length < 3) return message.warning('请至少填写 3 个产品特性')
  generating.value = true
  setTimeout(() => {
    generating.value = false
    // 把来源产品信息透传给 execute，供结果卡「应用到当前产品 Listing」定位
    const src = workingProduct?.value || pickedProduct.value
    const extra = src
      ? { source: 'product_library', product_id: src.id, product_title: src.title, product_asin: src.asin }
      : { source: 'manual_input' }
    emit('startAnalysis', { ...form.value, ...extra })
  }, 600)
}

const handleReset = () => { form.value = JSON.parse(JSON.stringify(defaultForm)); localStorage.removeItem('bullet-gen-config'); selectedCompetitorProduct.value = null }

// ====== 产品库选择（竞品 ASIN）======
const selectedCompetitorProduct = ref<any>(null)

const onCompetitorSelect = (product: any) => {
  selectedCompetitorProduct.value = product
  if (product.asin) {
    const current = form.value.competitor_asins || ''
    const asinList = current.split('\n').map((s: string) => s.trim()).filter(Boolean)
    if (!asinList.includes(product.asin)) {
      asinList.push(product.asin)
      form.value.competitor_asins = asinList.join('\n')
      saveForm()
    }
  }
}
</script>

<style scoped>
.bullet-config { display: flex; flex-direction: column; height: 100%; }

/* 顶部产品横幅（载入产品时显示） */
.product-banner {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px; margin-bottom: 8px;
  background: #f0f7ff; border: 1px solid #91caff; border-radius: 4px;
  font-size: 12px; color: #0958d9;
}
.product-banner .banner-icon { font-size: 14px; }

.bullet-config :deep(.ant-collapse) { flex: 1; overflow-y: auto; }
.feature-list { display: flex; flex-direction: column; gap: 8px; }
.feature-row { display: flex; gap: 6px; align-items: center; }
.config-actions { padding: 16px 0 0; border-top: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.input-with-picker .ant-input {
  flex: 1;
}
</style>
