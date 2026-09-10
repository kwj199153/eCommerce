<template>
  <div class="title-config">
    <!-- 产品基础信息 -->
    <a-collapse v-model:activeKey="activeKeys" ghost>
      <a-collapse-panel key="basic" header="📦 产品信息">
        <a-form layout="vertical" :model="form">
          <a-form-item label="产品名称" required>
            <a-input
              v-model:value="form.product_name"
              placeholder="例：便携式迷你加湿器"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="品牌名称">
            <a-input
              v-model:value="form.brand_name"
              placeholder="例：AeroLife"
              @change="saveForm"
            />
          </a-form-item>
          <a-form-item label="目标站点">
            <a-select
              v-model:value="form.marketplace"
              placeholder="选择站点"
              @change="saveForm"
            >
              <a-select-option value="us">美国 (US)</a-select-option>
              <a-select-option value="uk">英国 (UK)</a-select-option>
              <a-select-option value="de">德国 (DE)</a-select-option>
              <a-select-option value="jp">日本 (JP)</a-select-option>
            </a-select>
          </a-form-item>
        </a-form>
      </a-collapse-panel>

      <a-collapse-panel key="features" header="✨ 核心卖点">
        <div class="feature-list">
          <div
            v-for="(feat, idx) in form.features"
            :key="idx"
            class="feature-item"
          >
            <a-input
              v-model:value="form.features[idx]"
              :placeholder="`卖点 ${idx + 1}`"
              @change="saveForm"
            >
              <template #suffix>
                <DeleteOutlined
                  class="delete-btn"
                  @click="removeFeature(idx)"
                  v-if="form.features.length > 1"
                />
              </template>
            </a-input>
          </div>
          <a-button type="dashed" block size="small" @click="addFeature">
            <PlusOutlined /> 添加卖点
          </a-button>
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="keywords" header="🔑 目标关键词">
        <div class="keyword-section">
          <div class="kw-label">核心关键词（必填）</div>
          <a-select
            v-model:value="form.core_keywords"
            mode="tags"
            placeholder="输入关键词后按回车"
            style="width: 100%"
            @change="saveForm"
          />
        </div>
        <div class="keyword-section">
          <div class="kw-label">长尾关键词（可选）</div>
          <a-select
            v-model:value="form.long_tail_keywords"
            mode="tags"
            placeholder="输入长尾词"
            style="width: 100%"
            @change="saveForm"
          />
        </div>
        <div class="keyword-section">
          <div class="kw-label">竞品参考 ASIN（可选）</div>
          <a-input
            v-model:value="form.competitor_asin"
            placeholder="例：B0XXXXXXXXX"
            @change="saveForm"
          />
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="options" header="⚙️ 生成选项">
        <a-form layout="vertical" :model="form">
          <a-form-item label="标题风格">
            <a-radio-group v-model:value="form.style" @change="saveForm">
              <a-radio-button value="seo">SEO 优化</a-radio-button>
              <a-radio-button value="benefit">利益导向</a-radio-button>
              <a-radio-button value="minimal">简洁型</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="品牌位置">
            <a-radio-group v-model:value="form.brand_position" @change="saveForm">
              <a-radio value="front">前置</a-radio>
              <a-radio value="back">后置</a-radio>
              <a-radio value="none">不包含</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="生成数量">
            <a-input-number
              v-model:value="form.variant_count"
              :min="1"
              :max="5"
              style="width: 100%"
              @change="saveForm"
            />
          </a-form-item>
        </a-form>
      </a-collapse-panel>
    </a-collapse>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleGenerate" :loading="generating">
        <ThunderboltOutlined /> 生成标题
      </a-button>
      <a-button block @click="handleReset">
        <ReloadOutlined /> 重置条件
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const activeKeys = ref(['basic', 'keywords'])
const generating = ref(false)

const defaultForm = {
  product_name: '',
  brand_name: '',
  marketplace: 'us',
  features: ['', '', ''],
  core_keywords: [] as string[],
  long_tail_keywords: [] as string[],
  competitor_asin: '',
  style: 'seo',
  brand_position: 'back',
  variant_count: 3,
}

const form = ref({ ...defaultForm })

// 从 localStorage 恢复
onMounted(() => {
  const saved = localStorage.getItem('title-gen-config')
  if (saved) {
    try {
      form.value = { ...defaultForm, ...JSON.parse(saved) }
    } catch (e) {}
  }
})

const saveForm = () => {
  localStorage.setItem('title-gen-config', JSON.stringify(form.value))
}

const addFeature = () => {
  form.value.features.push('')
}

const removeFeature = (idx: number) => {
  form.value.features.splice(idx, 1)
  saveForm()
}

const handleGenerate = () => {
  if (!form.value.product_name.trim()) {
    message.warning('请填写产品名称')
    return
  }
  if (!form.value.core_keywords.length) {
    message.warning('请至少添加一个核心关键词')
    return
  }
  generating.value = true
  setTimeout(() => {
    generating.value = false
    emit('startAnalysis', form.value)
  }, 600)
}

const handleReset = () => {
  form.value = { ...defaultForm }
  localStorage.removeItem('title-gen-config')
}
</script>

<style scoped>
.title-config {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.title-config :deep(.ant-collapse) {
  flex: 1;
  overflow-y: auto;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.feature-item {
  position: relative;
}

.delete-btn {
  color: #ff4d4f;
  cursor: pointer;
}

.delete-btn:hover {
  color: #cf1322;
}

.keyword-section {
  margin-bottom: 12px;
}

.kw-label {
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 6px;
  font-weight: 500;
}

.config-actions {
  padding: 16px 0 0;
  border-top: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
</style>
