<template>
  <div class="keyword-miner-config">
    <a-collapse v-model:activeKey="activeKeys" ghost>
      <!-- 种子词来源 -->
      <a-collapse-panel key="seed" header="🌱 种子词来源">
        <a-form layout="vertical" :model="form">
          <a-form-item label="挖掘模式" required>
            <a-radio-group v-model:value="form.mode" @change="onModeChange; saveForm()">
              <a-radio-button value="product">产品驱动</a-radio-button>
              <a-radio-button value="asin">竞品 ASIN</a-radio-button>
              <a-radio-button value="custom">自定义种子词</a-radio-button>
            </a-radio-group>
          </a-form-item>

          <!-- 模式1：产品驱动（从工作商品获取） -->
          <template v-if="form.mode === 'product'">
            <a-form-item label="目标产品">
              <div class="input-with-picker">
                <a-input
                  :value="productTitle || '未选择产品'"
                  placeholder="请先从产品库载入商品"
                  :disabled="true"
                  size="large"
                  style="flex: 1"
                />
                <ProductPickerButton
                  :model-value="selectedProduct"
                  @select="onProductSelect"
                />
              </div>
              <div v-if="productTitle" class="seed-preview">
                <a-tag color="blue">📦 {{ productTitle }}</a-tag>
                <span v-if="productAsin" class="text-hint">ASIN: {{ productAsin }}</span>
              </div>
            </a-form-item>
          </template>

          <!-- 模式2：竞品 ASIN -->
          <template v-if="form.mode === 'asin'">
            <a-form-item label="竞品 ASIN 列表" required>
              <div class="input-with-picker">
                <a-textarea
                  v-model:value="form.seed_asins"
                  placeholder="每行一个 ASIN，如：&#10;B0CXXXX001&#10;B0CXXXX002"
                  :rows="3"
                  style="flex: 1"
                  @change="saveForm"
                />
                <ProductPickerButton
                  :model-value="selectedProduct"
                  @select="onAsinSelect"
                />
              </div>
            </a-form-item>
          </template>

          <!-- 模式3：自定义种子词 -->
          <template v-if="form.mode === 'custom'">
            <a-form-item label="种子关键词" required>
              <a-select
                v-model:value="form.seed_keywords"
                mode="tags"
                placeholder="输入核心词后按回车，如：便携加湿器、mini humidifier"
                style="width: 100%"
                @change="saveForm"
              />
            </a-form-item>
            <a-form-item label="补充语境（可选）">
              <a-input
                v-model:value="form.context"
                placeholder="例：适用于卧室、办公室的静音加湿设备"
                @change="saveForm"
              />
            </a-form-item>
          </template>
        </a-form>
      </a-collapse-panel>

      <!-- 挖掘策略 -->
      <a-collapse-panel key="strategy" header="⚙️ 挖掘策略">
        <a-form layout="vertical" :model="form">
          <a-form-item label="关键词类型">
            <a-checkbox-group v-model:value="form.keyword_types" @change="saveForm" class="keyword-type-grid">
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('long_tail') }" @click="toggleKeywordType('long_tail')">
                <span class="kw-icon">🔍</span>
                <span class="kw-label">长尾词</span>
                <span class="kw-desc">低竞争高转化</span>
              </div>
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('high_volume') }" @click="toggleKeywordType('high_volume')">
                <span class="kw-icon">📈</span>
                <span class="kw-label">大流量词</span>
                <span class="kw-desc">品牌曝光</span>
              </div>
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('competitor') }" @click="toggleKeywordType('competitor')">
                <span class="kw-icon">🎯</span>
                <span class="kw-label">竞品词</span>
                <span class="kw-desc">截流对手</span>
              </div>
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('question') }" @click="toggleKeywordType('question')">
                <span class="kw-icon">❓</span>
                <span class="kw-label">问答词</span>
                <span class="kw-desc">匹配用户疑问</span>
              </div>
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('seasonal') }" @click="toggleKeywordType('seasonal')">
                <span class="kw-icon">📅</span>
                <span class="kw-label">季节性词</span>
                <span class="kw-desc">时效流量</span>
              </div>
              <div class="kw-type-card" :class="{ active: form.keyword_types.includes('trend') }" @click="toggleKeywordType('trend')">
                <span class="kw-icon">🔥</span>
                <span class="kw-label">趋势词</span>
                <span class="kw-desc">新兴搜索</span>
              </div>
            </a-checkbox-group>
          </a-form-item>

          <a-form-item label="目标市场/站点">
            <a-select v-model:value="form.marketplace" @change="saveForm">
              <a-select-option value="us">🇺🇸 美国 (amazon.com)</a-select-option>
              <a-select-option value="uk">🇬🇧 英国 (amazon.co.uk)</a-select-option>
              <a-select-option value="de">🇩🇪 德国 (amazon.de)</a-select-option>
              <a-select-option value="jp">🇯🇵 日本 (amazon.co.jp)</a-select-option>
              <a-select-option value="ca">🇨🇦 加拿大 (amazon.ca)</a-select-option>
              <a-select-option value="au">🇦🇺 澳大利亚 (amazon.com.au)</a-select-option>
            </a-select>
          </a-form-item>

          <a-form-item label="输出数量">
            <a-slider
              v-model:value="form.limit"
              :min="20"
              :max="200"
              :step="10"
              :marks="{ 50: '50', 100: '100', 150: '150', 200: '200' }"
              @change="saveForm"
            />
          </a-form-item>

          <a-form-item label="排序方式">
            <a-radio-group v-model:value="form.sort_by" @change="saveForm">
              <a-radio-button value="search_volume">搜索量</a-radio-button>
              <a-radio-button value="competition">竞争度(低→高)</a-radio-button>
              <a-radio-button value="suggested_bid">建议竞价</a-radio-button>
              <a-radio-button value="relevance">相关度</a-radio-button>
            </a-radio-group>
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <!-- 过滤条件 -->
      <a-collapse-panel key="filter" header="🔎 过滤条件">
        <a-form layout="vertical" :model="form">
          <a-form-item label="最低搜索量阈值">
            <a-input-number
              v-model:value="form.min_search_volume"
              :min="0"
              :max="100000"
              :step="1000"
              style="width: 100%"
              addon-after="月"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="排除词（否定关键词）">
            <a-select
              v-model:value="form.exclude_words"
              mode="tags"
              placeholder="输入要排除的词，如：免费、cheap、二手"
              style="width: 100%"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="语言">
            <a-select v-model:value="form.language" @change="saveForm">
              <a-select-option value="all">全部</a-select-option>
              <a-select-option value="en">English</a-select-option>
              <a-select-option value="zh">中文</a-select-option>
              <a-select-option value="es">Español</a-select-option>
              <a-select-option value="de">Deutsch</a-select-option>
              <a-select-option value="ja">日本語</a-select-option>
            </a-select>
          </a-form-item>
        </a-form>
      </a-collapse-panel>
    </a-collapse>

    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleMine" :loading="mining">
        <ThunderboltOutlined /> 开始挖掘
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// 由 TaskConfigPanel 显式传入载入产品（与 ListingOptimConfig props 方式一致，避免 inject 时序不确定）
const props = defineProps<{ workingProduct?: any }>()
const workingProduct = computed(() => props.workingProduct)

// 产品驱动模式的显示标题（与 BulletConfig 相同的 watch 回填模式）
const productTitle = ref('')
const productAsin = ref('')

// 监听工作商品变化，产品模式下自动同步显示
watch(() => workingProduct?.value, (p) => {
  try {
    console.log('[KeywordMinerConfig watch] product:', p?.title || null)
    if (p) {
      productTitle.value = p.title || ''
      productAsin.value = p.asin || ''
      selectedProduct.value = p
    } else {
      productTitle.value = ''
      productAsin.value = ''
    }
  } catch (e) {
    console.error('[KeywordMinerConfig watch ERROR]', e)
  }
}, { immediate: true })

const activeKeys = ref(['seed', 'strategy'])
const mining = ref(false)

const defaultForm = {
  mode: 'product' as 'product' | 'asin' | 'custom',
  seed_asins: '',
  seed_keywords: [] as string[],
  context: '',
  keyword_types: ['long_tail', 'high_volume', 'competitor'] as string[],
  marketplace: 'us',
  limit: 100,
  sort_by: 'search_volume',
  min_search_volume: 10,
  exclude_words: [] as string[],
  language: 'en',
}

const form = ref({ ...defaultForm })

onMounted(() => {
  // 有载入产品时以产品预填为准，不覆盖为残留的自定义/ASIN 模式
  const saved = localStorage.getItem('keyword-miner-config')
  if (saved && !workingProduct?.value) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

// 载入产品 → 自动切到「产品驱动」模式（让挖掘锚定该产品；无产品时才尊重用户残留模式）
watch(() => workingProduct?.value, (p) => {
  try {
    if (p && form.value.mode !== 'product') form.value.mode = 'product'
  } catch (e) { console.error('[KeywordMinerConfig mode watch ERROR]', e) }
}, { immediate: true })

const saveForm = () => localStorage.setItem('keyword-miner-config', JSON.stringify(form.value))

// 卡片式关键词类型切换
const toggleKeywordType = (type: string) => {
  const idx = form.value.keyword_types.indexOf(type)
  if (idx >= 0) {
    form.value.keyword_types.splice(idx, 1)
  } else {
    form.value.keyword_types.push(type)
  }
  saveForm()
}

const onModeChange = () => {
  // 切换模式时清空无关字段
  if (form.value.mode !== 'asin') form.value.seed_asins = ''
  if (form.value.mode !== 'custom') {
    form.value.seed_keywords = []
    form.value.context = ''
  }
}

// ====== 产品库选择 ======
const selectedProduct = ref<any>(null)

const onProductSelect = (product: any) => {
  selectedProduct.value = product
  // 同步到显示字段（模板绑定的是 productTitle/productAsin，不是 selectedProduct）
  productTitle.value = product.title || ''
  productAsin.value = product.asin || ''
  form.value.mode = 'product'
  saveForm()
  message.success(`已选择产品: ${product.title}`)
}

const onAsinSelect = (product: any) => {
  selectedProduct.value = product
  if (product.asin) {
    form.value.mode = 'asin'
    const current = form.value.seed_asins || ''
    const asinList = current.split('\n').map((s: string) => s.trim()).filter(Boolean)
    if (!asinList.includes(product.asin)) {
      asinList.push(product.asin)
      form.value.seed_asins = asinList.join('\n')
      saveForm()
    }
  }
}

const handleMine = () => {
  // 根据模式校验（产品驱动模式：检查 productTitle 而非 workingProduct，因为 📂 按钮也走这个路径）
  if (form.value.mode === 'product' && !productTitle.value) {
    return message.warning('请先从产品库选择或载入商品')
  }
  if (form.value.mode === 'asin' && !form.value.seed_asins.trim()) {
    return message.warning('请输入至少一个竞品 ASIN')
  }
  if (form.value.mode === 'custom' && !form.value.seed_keywords.length) {
    return message.warning('请输入至少一个种子关键词')
  }
  if (!form.value.keyword_types.length) {
    return message.warning('请至少选择一种关键词类型')
  }

  mining.value = true
  setTimeout(() => {
    mining.value = false
    const src = workingProduct?.value || (form.value.mode === 'product' ? selectedProduct.value : null)
    const extra = src
      ? { source: 'product_library', product_id: src.id, product_title: src.title, product_asin: src.asin }
      : { source: 'manual_input' }
    emit('startAnalysis', {
      ...form.value,
      // 产品模式附加完整产品信息（优先 inject，其次 📂 手选）
      ...(form.value.mode === 'product' ? {
        product: workingProduct?.value || { title: productTitle.value, asin: productAsin.value },
      } : {}),
      ...extra,
    })
  }, 800)
}

const handleReset = () => {
  form.value = { ...defaultForm }
  selectedProduct.value = null
  localStorage.removeItem('keyword-miner-config')
}
</script>

<style scoped>
.keyword-miner-config { display: flex; flex-direction: column; height: 100%; }

.keyword-miner-config :deep(.ant-collapse) { flex: 1; overflow-y: auto; }
.config-actions { padding: 16px 0 0; border-top: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.input-with-picker .ant-input,
.input-with-picker .ant-input-textarea {
  flex: 1;
}

/* 已选产品预览 */
.seed-preview {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.text-hint {
  font-size: 12px;
  color: #8c8c8c;
}

/* 卡片式关键词类型选择 */
.keyword-type-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.kw-type-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #fff;
  user-select: none;
}
.kw-type-card:hover {
  border-color: #1677ff;
  background: #f0f7ff;
}
.kw-type-card.active {
  border-color: #1677ff;
  background: #e6f4ff;
  box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.1);
}
.kw-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.kw-label {
  font-size: 13px;
  font-weight: 500;
  color: #262626;
  white-space: nowrap;
}
.kw-desc {
  font-size: 11px;
  color: #8c8c8c;
  white-space: nowrap;
}
</style>
