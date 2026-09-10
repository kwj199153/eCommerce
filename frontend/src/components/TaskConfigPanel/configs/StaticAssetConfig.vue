<template>
  <div class="static-asset-config">
    <!-- 工作商品横幅 -->
    <div v-if="workingProduct" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.title?.slice(0, 30) }}{{ workingProduct.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <!-- ====== 载入产品（核心入口） ====== -->
    <div class="section-title">载入产品 <span class="required-mark">*</span></div>
    <div class="product-load-row">
      <ProductPickerButton
        :model-value="pickedProduct"
        :show-label="false"
        @select="onProductSelect"
      />
      <span v-if="pickedProduct" class="product-loaded-hint">已载入：{{ pickedProduct.title?.slice(0, 20) }}…</span>
    </div>

    <!-- 产品信息自动回填预览 -->
    <div v-if="pickedProduct" class="product-info-preview">
      <div class="preview-field">
        <span class="preview-label">卖点关键词</span>
        <span class="preview-value">{{ autoFilledSellingPoints || '—' }}</span>
      </div>
      <div class="preview-field">
        <span class="preview-label">痛点文案</span>
        <span class="preview-value">{{ autoFilledPainPoints || '—' }}</span>
      </div>
    </div>

    <!-- 上传产品实拍原图（必填）—— 载入产品后自动回填 main_image -->
    <div class="section-title">
      产品实拍原图 <span class="required-mark">*</span>
      <span v-if="!sourceImage && pickedProduct?.main_image" class="auto-fill-hint">检测到产品库有主图，可自动填充</span>
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
        <a-button
          v-if="pickedProduct?.main_image && !sourceImage"
          size="small"
          type="link"
          @click.stop="useProductMainImage"
        >使用产品库主图</a-button>
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

    <!-- 图片类型（扩展版） -->
    <div class="section-title">生成素材类型 <span class="required-mark">*</span></div>
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

    <!-- 白底三视图专属选项 -->
    <template v-if="form.imageTypes.includes('three-view')">
      <a-divider style="margin: 12px 0" />
      <div class="section-title">三视图设置</div>
      <div class="form-row">
        <div class="form-group flex-1">
          <label>视角组合</label>
          <a-select
            v-model:value="form.threeViewAngles"
            mode="multiple"
            size="small"
            style="width: 100%"
          >
            <a-select-option value="front">正面 0°</a-select-option>
            <a-select-option value="front-45">正面 45°</a-select-option>
            <a-select-option value="side">侧面 90°</a-select-option>
            <a-select-option value="back">背面</a-select-option>
            <a-select-option value="top">俯视图</a-select-option>
            <a-select-option value="detail-closeup">细节特写</a-select-option>
          </a-select>
        </div>
        <div class="form-group flex-1">
          <label>背景样式</label>
          <a-select v-model:value="form.bgStyle" size="small" style="width: 100%">
            <a-select-option value="pure-white">纯白 #FFF</a-select-option>
            <a-select-option value="light-gray">浅灰渐变</a-select-option>
            <a-select-option value="shadow">带阴影纯白</a-select-option>
            <a-select-option value="infinity">无限背景（立体感）</a-select-option>
          </a-select>
        </div>
      </div>
    </template>

    <!-- 场景图 / 生活方式图 / 人物场景图 共享选项 -->
    <template v-if="form.imageTypes.some(t => ['scene', 'lifestyle', 'character'].includes(t))">
      <a-divider style="margin: 12px 0" />
      <div class="section-title">场景设置</div>
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

    <!-- 分镜首帧图专属选项 -->
    <template v-if="form.imageTypes.includes('storyboard-frame')">
      <a-divider style="margin: 12px 0" />
      <div class="section-title">分镜首帧设置</div>
      <div class="form-group">
        <label>关联脚本镜头（可选）</label>
        <a-select
          v-model:value="form.linkedSceneIdx"
          size="small"
          style="width: 100%"
          allow-clear
          placeholder="选择已生成的带货脚本中的镜头序号"
        >
          <a-select-option
            v-for="(scene, idx) in availableScenes"
            :key="idx"
            :value="idx"
          >镜头 {{ idx + 1 }}：{{ scene.visual?.slice(0, 20) }}…</a-select-option>
        </a-select>
      </div>
      <div class="form-row">
        <div class="form-group flex-1">
          <label>画面比例</label>
          <a-select v-model:value="form.storyboardAspect" size="small" style="width: 100%">
            <a-select-option value="9:16">9:16 竖版（TikTok/Reels）</a-select-option>
            <a-select-option value="16:9">16:9 横版（YouTube）</a-select-option>
            <a-select-option value="1:1">1:1 方形（Amazon Post）</a-select-option>
          </a-select>
        </div>
        <div class="form-group flex-1">
          <label>风格</label>
          <a-select v-model:value="form.storyboardStyle" size="small" style="width: 100%">
            <a-select-option value="realistic">写实摄影风</a-select-option>
            <a-select-option value="cinematic">电影质感</a-select-option>
            <a-select-option value="3d-render">3D 渲染风</a-select-option>
            <a-select-option value="illustration">插画风格</a-select-option>
          </a-select>
        </div>
      </div>
    </template>

    <!-- 风格与通用参数 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">通用参数</div>
    <div class="form-row">
      <div class="form-group flex-1">
        <label>拍摄风格</label>
        <a-select v-model:value="form.style" size="small" style="width: 100%">
          <a-select-option value="studio">专业棚拍</a-select-option>
          <a-select-option value="lifestyle">生活方式</a-select-option>
          <a-select-option value="minimalist">极简风</a-select-option>
          <a-select-option value="luxury">奢华高端</a-select-option>
          <a-select-option value="playful">活泼趣味</a-select-option>
          <a-select-option value="tech">科技感</a-select-option>
        </a-select>
      </div>
      <div class="form-group flex-1">
        <label>生成数量</label>
        <a-input-number
          v-model:value="form.quantity"
          :min="1"
          :max="12"
          size="small"
          style="width: 100%"
        />
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
        <PictureOutlined /> 开始生成素材
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
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

// ====== 图片类型定义（扩展版） ======
const imageTypes = [
  { id: 'three-view', icon: '📐', name: '白底三视图', desc: '正/侧/背/俯多角度白底图' },
  { id: 'detail', icon: '🔍', name: '细节特写', desc: '局部特写突出工艺材质' },
  { id: 'scene', icon: '🖼️', name: '场景图', desc: '生活化场景展示使用效果' },
  { id: 'lifestyle', icon: '✨', name: '生活方式图', desc: '情感化场景营造购买欲望' },
  { id: 'character', icon: '🧑', name: '人物场景图', desc: '含人物的产品使用场景' },
  { id: 'storyboard-frame', icon: '🎬', name: '分镜首帧图', desc: '视频关键分镜画面（可关联脚本镜头）' },
]

// ====== 表单数据 ======
const defaultForm = () => ({
  // 图生图核心：产品实拍原图
  sourceImage: '',
  sourceImageFile: null as File | null,
  // 图片类型（多选）
  imageTypes: ['three-view'] as string[],
  // 三视图专属
  threeViewAngles: ['front-45', 'side', 'detail-closeup'] as string[],
  bgStyle: 'pure-white',
  // 场景图/生活方式图/人物场景图共享
  sceneDescription: '',
  background: 'indoor',
  lighting: 'soft-box',
  // 分镜首帧专属
  linkedSceneIdx: null as number | null,
  storyboardAspect: '9:16',
  storyboardStyle: 'realistic',
  // 通用
  style: 'studio',
  quantity: 4,
  extraPrompt: '',
})

const form = reactive(defaultForm())

// 从产品库选择的产品
const pickedProduct = ref<any>(null)

// 自动回填字段
const autoFilledSellingPoints = computed(() => {
  if (!pickedProduct.value) return ''
  const sp = pickedProduct.value.selling_points
  if (Array.isArray(sp)) return sp.join('、')
  if (typeof sp === 'string') return sp
  return pickedProduct.value.bullet_points?.slice(0, 5).join('、') || ''
})

const autoFilledPainPoints = computed(() => {
  if (!pickedProduct.value) return ''
  const pp = pickedProduct.value.pain_points
  if (Array.isArray(pp)) return pp.join('；')
  if (typeof pp === 'string') return pp
  // 从 bullet_points 或 description 中提取
  return pickedProduct.value.description?.slice(0, 100) || ''
})

// 可用分镜场景列表（从全局静态素材库读取已生成的脚本）
interface StaticScene {
  visual: string
  narration: string
}
const availableScenes = computed<StaticScene[]>(() => {
  // TODO: 从 Pinia store 或 inject 获取已生成的视频脚本分镜
  return []
})

const onProductSelect = (product: any) => {
  pickedProduct.value = product
  if (product) {
    // 自动尝试填充主图
    if (product.main_image && !sourceImage.value) {
      // 延迟一 tick 让用户看到「使用产品库主图」提示
    }
  }
}

// 从工作商品自动填充
watch(workingProduct, (product) => {
  if (product && !pickedProduct.value) {
    pickedProduct.value = product
  }
}, { immediate: true })

// ====== 图片类型切换（多选） ======
const toggleImageType = (id: string) => {
  const idx = form.imageTypes.indexOf(id)
  if (idx >= 0) {
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

// 使用产品库主图
function useProductMainImage() {
  const img = pickedProduct.value?.main_image
  if (img) {
    sourceImage.value = img
    sourceFile.value = null
    message.success('已使用产品库主图')
  }
}

function removeImage() {
  sourceImage.value = ''
  sourceFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
}

// ====== 提交 ======
const handleSubmit = () => {
  if (!pickedProduct.value) {
    message.warning('请先载入产品')
    return
  }
  // 若用户未上传原图但已载入产品，自动 fallback 使用产品库主图，让 mock 能直接跑起来
  if (!sourceImage.value && pickedProduct.value?.main_image) {
    sourceImage.value = pickedProduct.value.main_image
    sourceFile.value = null
  }
  if (!sourceImage.value) {
    message.warning('请上传产品实拍原图（或使用产品库主图）')
    return
  }
  if (form.imageTypes.length === 0) {
    message.warning('请至少选择一种素材类型')
    return
  }
  loading.value = true
  emit('startAnalysis', {
    tool: 'static-asset-gen',
    mode: 'image-to-image',
    ...form,
    // 携带原图数据
    source_image: sourceImage.value,
    source_image_name: sourceFile.value?.name || 'product-main-image',
    // 携带产品完整数据
    _sourceProduct: pickedProduct.value,
    // 自动回填的字段
    selling_points: autoFilledSellingPoints.value,
    pain_points: autoFilledPainPoints.value,
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
.static-asset-config {
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
.optional-mark { font-size: 11px; font-weight: 400; color: #8c8c8c; margin-left: 4px; }
.auto-fill-hint { font-size: 11px; color: #1890ff; margin-left: 6px; }

/* 产品载入行 */
.product-load-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.product-loaded-hint {
  font-size: 11px;
  color: #52c41a;
  background: #f6ffed;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #b7eb8f;
}

/* 产品信息预览 */
.product-info-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
}
.preview-field {
  display: flex;
  gap: 6px;
  font-size: 11px;
}
.preview-label {
  color: #8c8c8c;
  flex-shrink: 0;
  min-width: 56px;
}
.preview-value {
  color: #262626;
  word-break: break-all;
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

.upload-icon { font-size: 32px; color: #1890ff; margin-bottom: 8px; }
.upload-hint { margin: 0; font-size: 13px; color: #595959; }
.upload-sub { margin: 4px 0 0; font-size: 11px; color: #bfbfbf; }

.upload-area.has-image { padding: 12px; cursor: default; }

.preview-img {
  max-width: 100%;
  max-height: 200px;
  border-radius: 6px;
  object-fit: contain;
}
.preview-actions { display: flex; justify-content: center; gap: 8px; margin-top: 10px; }

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
.type-card.active { border-color: #1890ff; background: #e6f7ff; }
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
.form-row { display: flex; gap: 8px; }
.flex-1 { flex: 1; }

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
}
</style>
