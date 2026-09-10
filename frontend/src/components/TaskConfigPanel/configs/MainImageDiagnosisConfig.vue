<template>
  <div class="image-diagnosis-config">
    <!-- 工作商品横幅 -->
    <div v-if="workingProduct" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.title?.slice(0, 30) }}{{ workingProduct.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <!-- 诊断模式 -->
    <div class="section-title">诊断方式</div>
    <div class="mode-cards">
      <div
        class="mode-card"
        :class="{ active: form.mode === 'url' }"
        @click="form.mode = 'url'"
      >
        <LinkOutlined /> 输入图片 URL
      </div>
      <div
        class="mode-card"
        :class="{ active: form.mode === 'upload' }"
        @click="form.mode = 'upload'"
      >
        <UploadOutlined /> 上传图片
      </div>
      <div
        v-if="workingProduct"
        class="mode-card"
        :class="{ active: form.mode === 'product' }"
        @click="form.mode = 'product'"
      >
        <ShopOutlined /> 使用产品库图片
      </div>
    </div>

    <!-- URL 模式 -->
    <template v-if="form.mode === 'url'">
      <div class="form-group" style="margin-top: 10px">
        <label>主图 URL</label>
        <a-input
          v-model:value="form.imageUrl"
          placeholder="粘贴 Amazon 主图链接..."
          size="small"
        />
      </div>
    </template>

    <!-- 上传模式 -->
    <template v-if="form.mode === 'upload'">
      <div class="upload-area" @click="triggerUpload">
        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          style="display: none"
          @change="handleFileChange"
        />
        <div v-if="!form.uploadedImage">
          <CloudUploadOutlined style="font-size: 32px; color: #1890ff; margin-bottom: 8px" />
          <p>点击或拖拽上传主图</p>
          <p style="font-size: 11px; color: #bfbfbf">支持 JPG/PNG/WebP，最大 10MB</p>
        </div>
        <div v-else class="preview-container">
          <img :src="form.uploadedImage" alt="预览" class="preview-img" />
          <a-button size="small" danger type="link" @click.stop="form.uploadedImage = ''">移除</a-button>
        </div>
      </div>
    </template>

    <!-- 产品库模式 -->
    <template v-if="form.mode === 'product' && workingProduct">
      <div class="product-images-preview">
        <div
          v-for="(img, idx) in (workingProduct.images || [])"
          :key="idx"
          class="thumb-item"
          :class="{ selected: form.selectedImageIdx === idx }"
          @click="form.selectedImageIdx = idx"
        >
          <img :src="img" :alt="`主图${idx + 1}`" />
          <span class="thumb-label">{{ idx + 1 }}</span>
        </div>
      </div>
    </template>

    <!-- 诊断维度选择 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">诊断维度</div>

    <a-checkbox-group v-model:value="form.diagnosisDimensions" style="width: 100%">
      <div class="dimension-grid">
        <a-checkbox value="quality" class="dim-item">
          <span class="dim-icon">📐</span>
          <span><strong>画质质量</strong><br/><small>分辨率/清晰度/噪点</small></span>
        </a-checkbox>
        <a-checkbox value="composition" class="dim-item">
          <span class="dim-icon">🎯</span>
          <span><strong>构图规范</strong><br/><small>主体位置/留白/比例</small></span>
        </a-checkbox>
        <a-checkbox value="compliance" class="dim-item">
          <span class="dim-icon">✅</span>
          <span><strong>平台合规</strong><br/><small>白底/边距/水印/文字</small></span>
        </a-checkbox>
        <a-checkbox value="ctr-prediction" class="dim-item">
          <span class="dim-icon">📈</span>
          <span><strong>CTR 预测</strong><br/><small>点击率预估/A/B参考</small></span>
        </a-checkbox>
        <a-checkbox value="brand-consistency" class="dim-item">
          <span class="dim-icon">🎨</span>
          <span><strong>品牌一致性</strong><br/><small>色调/风格统一度</small></span>
        </a-checkbox>
        <a-checkbox value="competitor-compare" class="dim-item">
          <span class="dim-icon">⚔️</span>
          <span><strong>竞品对比</strong><br/><small>与 Top Seller 差距分析</small></span>
        </a-checkbox>
      </div>
    </a-checkbox-group>

    <!-- 竞品 ASIN（可选） -->
    <div v-if="form.diagnosisDimensions.includes('competitor-compare')" class="form-group" style="margin-top: 8px">
      <label>竞品 ASIN（可选）</label>
      <div class="input-with-picker">
        <a-input
          v-model:value="form.competitorAsin"
          placeholder="输入竞品 ASIN 进行对比分析"
          size="small"
          style="flex: 1"
        />
        <ProductPickerButton
          :model-value="selectedCompetitorProduct"
          @select="onCompetitorSelect"
        />
      </div>
    </div>

    <!-- 输出选项 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">输出选项</div>

    <a-checkbox-group v-model:value="form.outputOptions">
      <div class="output-options">
        <a-checkbox value="score-report"><strong>评分报告</strong> — 各维度 A-F 评级</a-checkbox>
        <a-checkbox value="issue-list"><strong>问题清单</strong> — 具体问题 + 改进建议</a-checkbox>
        <a-checkbox value="regen-instruction" checked disabled><strong>重绘指令</strong> — AI 可直接使用的优化提示词</a-checkbox>
        <a-checkbox value="before-after"><strong>前后对比</strong> — 模拟优化效果示意</a-checkbox>
      </div>
    </a-checkbox-group>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <SearchOutlined /> 开始诊断
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, type Ref } from 'vue'
import {
  ReloadOutlined,
  SearchOutlined,
  LinkOutlined,
  UploadOutlined,
  ShopOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { inject } from 'vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

const defaultForm = () => ({
  mode: 'url' as 'url' | 'upload' | 'product',
  imageUrl: '',
  uploadedImage: '',
  selectedImageIdx: 0,
  diagnosisDimensions: ['quality', 'composition', 'compliance', 'ctr-prediction'] as string[],
  competitorAsin: '',
  outputOptions: ['score-report', 'issue-list', 'regen-instruction'] as string[],
})

const form = reactive(defaultForm())

function triggerUpload() {
  fileInputRef.value?.click()
}

function handleFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 10 * 1024 * 1024) {
    message.error('图片大小不能超过 10MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    form.uploadedImage = reader.result as string
  }
  reader.readAsDataURL(file)
}

const handleSubmit = () => {
  if (form.mode === 'url' && !form.imageUrl.trim()) {
    message.warning('请输入图片 URL 或上传图片')
    return
  }
  loading.value = true
  emit('startAnalysis', {
    tool: 'main-image-diagnosis',
    ...form,
    _sourceProduct: workingProduct?.value,
  })
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
  selectedCompetitorProduct.value = null
}

// ====== 产品库选择（竞品 ASIN）======
const selectedCompetitorProduct = ref<any>(null)

const onCompetitorSelect = (product: any) => {
  selectedCompetitorProduct.value = product
  if (product.asin) {
    form.competitorAsin = product.asin
  }
}
</script>

<style scoped>
.image-diagnosis-config {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.product-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #e6f7ff;
  border: 1px solid #91d5ff;
  border-radius: 6px;
  font-size: 12px;
  color: #1890ff;
}
.banner-icon { font-size: 14px; }
.banner-text { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #262626;
  margin-top: 4px;
}

/* 诊断模式卡片 */
.mode-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.mode-card {
  padding: 10px 8px;
  border: 2px solid #f0f0f0;
  border-radius: 8px;
  text-align: center;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.mode-card:hover { border-color: #bae7ff; }
.mode-card.active {
  border-color: #1890ff;
  background: #e6f7ff;
  color: #1890ff;
}

/* 上传区域 */
.upload-area {
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
  background: #fafafa;
}

.upload-area:hover { border-color: #1890ff; }

.preview-container {
  position: relative;
}

.preview-img {
  max-width: 100%;
  max-height: 160px;
  border-radius: 6px;
  object-fit: contain;
}

/* 产品图片缩略图 */
.product-images-preview {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.thumb-item {
  width: 56px;
  height: 56px;
  border: 2px solid #f0f0f0;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  position: relative;
  transition: border-color 0.2s;
}

.thumb-item:hover { border-color: #bae7ff; }
.thumb-item.selected { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2); }

.thumb-item img { width: 100%; height: 100%; object-fit: cover; }

.thumb-label {
  position: absolute;
  bottom: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 0 0 4px 0;
}

/* 诊断维度网格 */
.dimension-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.dim-item {
  display: flex !important;
  align-items: flex-start !important;
  gap: 6px !important;
  padding: 8px !important;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  transition: background 0.2s;
}

.dim-item:hover { background: #fafafa; }
.dim-item > span:last-child small { color: #8c8c8c; }
.dim-icon { font-size: 18px; flex-shrink: 0; }

/* 输出选项 */
.output-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 3px;
  font-weight: 500;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
}

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
