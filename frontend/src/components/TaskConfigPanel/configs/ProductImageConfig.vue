<template>
  <div class="product-image-config">
    <!-- 工作商品横幅 -->
    <div v-if="workingProduct" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.title?.slice(0, 30) }}{{ workingProduct.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <!-- 上传产品实拍原图（必填） -->
    <div class="section-title">
      上传产品实拍原图 <span class="required-mark">*</span>
    </div>
    <div
      class="upload-area"
      :class="{ 'has-image': sourceImage }"
      @click="triggerUpload"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="handleDrop"
    >
      <input
        ref="fileInputRef"
        type="file"
        accept="image/*"
        style="display: none"
        @change="handleFileChange"
      />
      <template v-if="!sourceImage">
        <CloudUploadOutlined class="upload-icon" />
        <p class="upload-hint">拖拽图片到此处上传，或点击选择文件</p>
        <p class="upload-sub">支持 JPG / PNG / WebP，最大 10MB</p>
      </template>
      <template v-else>
        <img :src="sourceImage" alt="产品实拍原图预览" class="preview-img" />
        <div class="preview-actions" @click.stop>
          <a-button size="small" @click="triggerUpload">
            <RedoOutlined /> 更换
          </a-button>
          <a-button size="small" danger @click="removeImage">
            <DeleteOutlined /> 删除
          </a-button>
        </div>
      </template>
    </div>

    <!-- 图片类型 -->
    <div class="section-title">图片类型</div>
    <div class="image-type-grid">
      <div
        v-for="type in imageTypes"
        :key="type.id"
        class="type-card"
        :class="{ active: form.imageTypes.includes(type.id) }"
        @click="toggleImageType(type.id)"
      >
        <span class="type-emoji">{{ type.icon }}</span>
        <span class="type-name">{{ type.name }}</span>
        <span class="type-desc">{{ type.desc }}</span>
      </div>
    </div>

    <!-- 补充产品信息（选填） -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">补充产品信息 <span class="optional-mark">选填，提升画质</span></div>

    <div class="form-group">
      <label>产品名称</label>
      <div class="product-name-row">
        <a-input
          v-model:value="form.productName"
          placeholder="输入产品名称（用于 AI 理解产品特征）"
          size="small"
          style="flex: 1"
        />
        <ProductPickerButton
          :model-value="pickedProduct"
          :show-label="true"
          @select="onProductSelect"
        />
      </div>
    </div>

    <div class="form-group">
      <label>卖点关键词</label>
      <a-textarea
        v-model:value="form.keywords"
        :rows="2"
        placeholder="如：便携、防水、无线充电、长续航..."
        size="small"
      />
    </div>

    <!-- 风格与场景 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">风格设置</div>

    <div class="form-row">
      <div class="form-group flex-1">
        <label>拍摄风格</label>
        <a-select
          v-model:value="form.style"
          size="small"
          style="width: 100%"
        >
          <a-select-option value="studio">专业棚拍</a-select-option>
          <a-select-option value="lifestyle">生活方式</a-select-option>
          <a-select-option value="minimalist">极简风</a-select-option>
          <a-select-option value="luxury">奢华高端</a-select-option>
          <a-select-option value="playful">活泼趣味</a-select-option>
          <a-select-option value="tech">科技感</a-select-option>
        </a-select>
      </div>
      <div class="form-group flex-1">
        <label>色调偏好</label>
        <a-select
          v-model:value="form.colorTone"
          size="small"
          style="width: 100%"
        >
          <a-select-option value="warm">暖色调</a-select-option>
          <a-select-option value="cool">冷色调</a-select-option>
          <a-select-option value="neutral">中性色</a-select-option>
          <a-select-option value="vibrant">鲜艳饱和</a-select-option>
          <a-select-option value="muted">柔和低饱和</a-select-option>
        </a-select>
      </div>
    </div>

    <!-- 场景图/生活方式图专属选项 -->
    <template v-if="form.imageTypes.includes('scene') || form.imageTypes.includes('lifestyle')">
      <div class="form-group">
        <label>使用场景描述</label>
        <a-textarea
          v-model:value="form.sceneDescription"
          :rows="2"
          placeholder="如：户外露营、厨房台面、办公桌前、旅行途中..."
          size="small"
        />
      </div>

      <div class="form-row">
        <div class="form-group flex-1">
          <label>背景环境</label>
          <a-select v-model:value="form.background" size="small" style="width: 100%">
            <a-select-option value="indoor">室内</a-select-option>
            <a-select-option value="outdoor">户外</a-select-option>
            <a-select-option value="studio-pure">纯色背景</a-select-option>
            <a-select-option value="natural">自然环境</a-select-option>
            <a-select-option value="urban">城市街景</a-select-option>
          </a-select>
        </div>
        <div class="form-group flex-1">
          <label>光线类型</label>
          <a-select v-model:value="form.lighting" size="small" style="width: 100%">
            <a-select-option value="natural-light">自然光</a-select-option>
            <a-select-option value="soft-box">柔光箱</a-select-option>
            <a-select-option value="dramatic">戏剧光</a-select-option>
            <a-select-option value="golden-hour">黄金时刻</a-select-option>
          </a-select>
        </div>
      </div>
    </template>

    <!-- 细节图专属选项 -->
    <template v-if="form.imageTypes.includes('detail')">
      <div class="form-group">
        <label>需要突出的细节部位</label>
        <a-select
          v-model:value="form.detailFocus"
          mode="multiple"
          size="small"
          style="width: 100%"
          placeholder="选择要展示的细节"
        >
          <a-select-option value="material">材质纹理</a-select-option>
          <a-select-option value="craftsmanship">工艺细节</a-select-option>
          <a-select-option value="button-interface">按键/接口</a-select-option>
          <a-select-option value="logo-branding">Logo/品牌标识</a-select-option>
          <a-select-option value="packaging">包装细节</a-select-option>
          <a-select-option value="size-comparison">尺寸对比</a-select-option>
          <a-select-option value="accessories">配件展示</a-select-option>
        </a-select>
      </div>
    </template>

    <!-- 生成参数 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">生成参数</div>

    <div class="form-row">
      <div class="form-group flex-1">
        <label>生成数量</label>
        <a-input-number
          v-model:value="form.quantity"
          :min="1"
          :max="8"
          size="small"
          style="width: 100%"
        />
      </div>
      <div class="form-group flex-1">
        <label>图片尺寸</label>
        <a-select v-model:value="form.dimension" size="small" style="width: 100%">
          <a-select-option value="2000x2000">正方形 2000×2000</a-select-option>
          <a-select-option value="3000x3000">高清方形 3000×3000</a-select-option>
          <a-select-option value="2000x1333">横向 3:2</a-select-option>
          <a-select-option value="1080x1920">竖版 9:16</a-select-option>
        </a-select>
      </div>
    </div>

    <div class="form-group">
      <label>额外要求（可选）</label>
      <a-textarea
        v-model:value="form.extraPrompt"
        :rows="2"
        placeholder="如：产品左侧45度角、露出包装盒、加入道具尺子做参照..."
        size="small"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <PictureOutlined /> 开始生成
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, inject, type Ref } from 'vue'
import {
  ReloadOutlined,
  PictureOutlined,
  CloudUploadOutlined,
  RedoOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const dragging = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// ====== 图片类型定义 ======
const imageTypes = [
  { id: 'white-bg', icon: '⬜', name: '白底图', desc: '纯白背景主图，符合平台规范' },
  { id: 'scene', icon: '🖼️', name: '场景图', desc: '生活化场景展示使用效果' },
  { id: 'detail', icon: '🔍', name: '细节图', desc: '局部特写突出工艺材质' },
  { id: 'lifestyle', icon: '✨', name: '生活方式图', desc: '情感化场景营造购买欲望' },
]

// ====== 表单数据 ======
const defaultForm = () => ({
  // 图生图核心：产品实拍原图
  sourceImage: '',
  sourceImageFile: null as File | null,
  // 图片类型（多选）
  imageTypes: ['white-bg'] as string[],
  // 补充产品信息（选填）
  productName: '',
  keywords: '',
  // 风格设置
  style: 'studio',
  colorTone: 'neutral',
  // 场景图/生活方式图
  sceneDescription: '',
  background: 'indoor',
  lighting: 'soft-box',
  // 细节图
  detailFocus: [] as string[],
  // 通用
  quantity: 4,
  dimension: '2000x2000',
  extraPrompt: '',
})

const form = reactive(defaultForm())

// 从产品库选择的产品
const pickedProduct = ref<any>(null)

const onProductSelect = (product: any) => {
  pickedProduct.value = product
  if (product) {
    form.productName = product.title || ''
    form.keywords = product.bullet_points?.join('、') || product.features?.join('、') || form.keywords
  }
}

// 从工作商品自动填充
watch(workingProduct, (product) => {
  if (product) {
    form.productName = product.title || ''
    form.keywords = product.bullet_points?.join('、') || product.features?.join('、') || ''
  }
}, { immediate: true })

// ====== 图片类型切换（多选） ======
const toggleImageType = (id: string) => {
  const idx = form.imageTypes.indexOf(id)
  if (idx >= 0) {
    // 至少保留一个类型
    if (form.imageTypes.length === 1) {
      message.info('至少保留一种图片类型')
      return
    }
    form.imageTypes.splice(idx, 1)
  } else {
    form.imageTypes.push(id)
  }
}

// ====== 图片上传 ======
const sourceImage = ref('')
const sourceFile = ref<File | null>(null)

function triggerUpload() {
  fileInputRef.value?.click()
}

function validateAndReadFile(file: File) {
  if (!file.type.startsWith('image/')) {
    message.error('请上传图片文件')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    message.error('图片大小不能超过 10MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    sourceImage.value = reader.result as string
  }
  reader.readAsDataURL(file)
  sourceFile.value = file
}

function handleFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  validateAndReadFile(file)
}

function handleDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) validateAndReadFile(file)
}

function removeImage() {
  sourceImage.value = ''
  sourceFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
}

// ====== 方法 ======
const handleSubmit = () => {
  if (!sourceImage.value) {
    message.warning('请先上传产品实拍原图')
    return
  }
  if (form.imageTypes.length === 0) {
    message.warning('请至少选择一种图片类型')
    return
  }
  loading.value = true
  emit('startAnalysis', {
    tool: 'product-image-gen',
    // 图生图模式标记
    mode: 'image-to-image',
    ...form,
    // 携带原图数据（base64）
    source_image: sourceImage.value,
    source_image_name: sourceFile.value?.name || '',
    _sourceProduct: workingProduct?.value,
  })
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
  pickedProduct.value = null
  removeImage()
}
</script>

<style scoped>
.product-image-config {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 工作商品横幅 */
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

/* 区块标题 */
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #262626;
  margin-top: 4px;
}

.required-mark { color: #ff4d4f; }
.optional-mark {
  font-size: 11px;
  font-weight: 400;
  color: #8c8c8c;
  margin-left: 4px;
}

/* 上传区域 */
.upload-area {
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: #fafafa;
}

.upload-area:hover { border-color: #1890ff; }
.upload-area.dragging { border-color: #1890ff; background: #e6f7ff; }

.upload-icon {
  font-size: 32px;
  color: #1890ff;
  margin-bottom: 8px;
}

.upload-hint {
  margin: 0;
  font-size: 13px;
  color: #595959;
}

.upload-sub {
  margin: 4px 0 0;
  font-size: 11px;
  color: #bfbfbf;
}

.upload-area.has-image {
  padding: 12px;
  cursor: default;
}

.preview-img {
  max-width: 100%;
  max-height: 200px;
  border-radius: 6px;
  object-fit: contain;
}

.preview-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 10px;
}

/* 图片类型网格 */
.image-type-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.type-card {
  padding: 10px 8px;
  border: 2px solid #f0f0f0;
  border-radius: 8px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}

.type-card:hover { border-color: #bae7ff; }

.type-card.active {
  border-color: #1890ff;
  background: #e6f7ff;
}

.type-emoji { font-size: 22px; display: block; margin-bottom: 4px; }
.type-name { font-size: 13px; font-weight: 600; color: #262626; display: block; }
.type-desc { font-size: 11px; color: #8c8c8c; margin-top: 2px; }

/* 表单 */
.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 3px;
  font-weight: 500;
}

.form-row {
  display: flex;
  gap: 8px;
}
.flex-1 { flex: 1; }

.product-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
}
</style>
