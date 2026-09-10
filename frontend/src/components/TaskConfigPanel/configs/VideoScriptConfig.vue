<template>
  <div class="video-script-config">
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

    <!-- 平台选择 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">目标平台</div>
    <div class="platform-grid">
      <div
        v-for="p in platforms"
        :key="p.id"
        class="platform-card"
        :class="{ active: form.platform === p.id }"
        @click="form.platform = p.id"
      >
        <span class="platform-emoji">{{ p.icon }}</span>
        <span class="platform-name">{{ p.name }}</span>
        <span class="platform-spec">{{ p.spec }}</span>
      </div>
    </div>

    <!-- 视频基本信息 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">视频参数</div>

    <div class="form-row">
      <div class="form-group flex-1">
        <label>视频时长</label>
        <a-select v-model:value="form.duration" size="small" style="width: 100%">
          <a-select-option value="15s">15 秒（快节奏）</a-select-option>
          <a-select-option value="30s">30 秒（标准）</a-select-option>
          <a-select-option value="45s">45 秒（详细）</a-select-option>
          <a-select-option value="60s">60 秒（完整版）</a-select-option>
        </a-select>
      </div>
      <div class="form-group flex-1">
        <label>视频风格</label>
        <a-select v-model:value="form.videoStyle" size="small" style="width: 100%">
          <a-select-option value="product-showcase">产品展示型</a-select-option>
          <a-select-option value="problem-solution">痛点解决型</a-select-option>
          <a-select-option value="unboxing">开箱体验型</a-select-option>
          <a-select-option value="comparison">对比测评型</a-select-option>
          <a-select-option value="storytelling">故事叙事型</a-select-option>
          <a-select-option value="asmr">ASMR 沉浸型</a-select-option>
          <a-select-option value="tutorial">教程演示型</a-select-option>
        </a-select>
      </div>
    </div>

    <!-- 脚本生成选项 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">脚本生成选项</div>

    <a-checkbox-group v-model:value="form.scriptOptions" style="width: 100%">
      <div class="script-options-row">
        <a-checkbox value="hook-opening">黄金3秒钩子开头</a-checkbox>
        <a-checkbox value="pain-agitate">痛点煽动</a-checkbox>
        <a-checkbox value="social-proof">社会证明</a-checkbox>
        <a-checkbox value="cta-strong">强 CTA 结尾</a-checkbox>
        <a-checkbox value="subtitle-friendly">字幕友好（短句）</a-checkbox>
      </div>
    </a-checkbox-group>

    <div class="form-group" style="margin-top: 8px">
      <label>额外脚本要求（可选）</label>
      <a-textarea
        v-model:value="form.extraScriptPrompt"
        :rows="2"
        placeholder="如：强调性价比、突出与竞品差异、加入限时优惠话术..."
        size="small"
      />
    </div>

    <!-- ====== 分镜结构表（可编辑） ====== -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">
      分镜脚本
      <div class="storyboard-actions">
        <a-button type="link" size="small" @click="addScene">+ 添加镜头</a-button>
        <a-button type="link" size="small" @click="resetToDefaultScenes">重置默认</a-button>
      </div>
    </div>

    <div class="scenes-list">
      <div
        v-for="(scene, idx) in form.scenes"
        :key="idx"
        class="scene-card"
      >
        <div class="scene-header">
          <span class="scene-num">镜头 {{ idx + 1 }}</span>
          <span class="scene-time">{{ scene.duration }}s</span>
          <a-button
            v-if="form.scenes.length > 2"
            type="text"
            size="small"
            danger
            @click="removeScene(idx)"
          >删除</a-button>
        </div>

        <!-- 首帧图片引用（从静态素材库选） -->
        <div class="form-group">
          <label>首帧参考图 <span class="optional-mark">可选</span></label>
          <div class="frame-ref-row">
            <a-input
              :model-value="scene.frameRef"
              @update:value="(v: string) => updateScene(idx, 'frameRef', v)"
              placeholder="输入素材库图片 URL 或留空由 AI 生成"
              size="small"
              style="flex: 1"
            />
            <a-button size="small" @click="openAssetPicker(idx)">
              <FolderOpenOutlined /> 选素材
            </a-button>
          </div>
          <img
            v-if="scene.frameRef"
            :src="scene.frameRef"
            class="frame-thumb"
            alt="首帧预览"
          />
        </div>

        <div class="form-group">
          <label>画面描述</label>
          <a-input
            :model-value="scene.visual"
            @update:value="(v: string) => updateScene(idx, 'visual', v)"
            placeholder="如：特写产品正面，缓慢旋转360度"
            size="small"
          />
        </div>

        <div class="form-group">
          <label>文案 / 旁白</label>
          <a-textarea
            :model-value="scene.narration"
            @update:value="(v: string) => updateScene(idx, 'narration', v)"
            placeholder="如：这就是你的下一件必备好物"
            size="small"
            :rows="2"
          />
        </div>

        <div class="form-row">
          <div class="form-group flex-1">
            <label>运镜方式</label>
            <a-select
              :model-value="scene.cameraMovement"
              @change="(v: string) => updateScene(idx, 'cameraMovement', v)"
              size="small"
              style="width: 100%"
            >
              <a-select-option value="static">固定机位</a-select-option>
              <a-select-option value="push-in">推近</a-select-option>
              <a-select-option value="pull-out">拉远</a-select-option>
              <a-select-option value="pan-left/right">横移</a-select-option>
              <a-select-option value="tilt-up/down">俯仰</a-select-option>
              <a-select-option value="rotate">环绕旋转</a-select-option>
              <a-select-option value="zoom-dolly">变焦推轨</a-select-option>
              <a-select-option value="handheld">手持晃动</a-select-option>
            </a-select>
          </div>
          <div class="form-group flex-1">
            <label>镜头景别</label>
            <a-select
              :model-value="scene.shotSize"
              @change="(v: string) => updateScene(idx, 'shotSize', v)"
              size="small"
              style="width: 100%"
            >
              <a-select-option value="extreme-closeup">大特写</a-select-option>
              <a-select-option value="closeup">特写</a-select-option>
              <a-select-option value="medium-shot">中景</a-select-option>
              <a-select-option value="full-shot">全景</a-select-option>
              <a-select-option value="wide-angle">广角/环境</a-select-option>
            </a-select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group flex-1">
            <label>BGM / 音效</label>
            <a-select
              :model-value="scene.bgm"
              @change="(v: string) => updateScene(idx, 'bgm', v)"
              size="small"
              style="width: 100%"
              allow-clear
            >
              <a-select-option value="upbeat">轻快节奏</a-select-option>
              <a-select-option value="cinematic">电影感</a-select-option>
              <a-select-option value="lo-fi">Lo-Fi 放松</a-select-option>
              <a-select-option value="electronic">电子/科技感</a-select-option>
              <a-select-option value="acoustic">原声吉他</a-select-option>
              <a-select-option value="silence">静音（仅旁白）</a-select-option>
              <a-select-option value="asmr">ASMR 音效</a-select-option>
              <a-select-option value="swoosh">转场音效</a-select-option>
            </a-select>
          </div>
          <div class="form-group flex-1">
            <label>字幕样式</label>
            <a-select
              :model-value="scene.subtitleStyle"
              @change="(v: string) => updateScene(idx, 'subtitleStyle', v)"
              size="small"
              style="width: 100%"
            >
              <a-select-option value="bold-bottom">底部粗体</a-select-option>
              <a-select-option value="typewriter">打字机效果</a-select-option>
              <a-select-option value="highlight">关键词高亮</a-select-option>
              <a-select-option value="none">无字幕</a-select-option>
            </a-select>
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <VideoCameraOutlined /> 生成带货脚本
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import {
  ReloadOutlined,
  VideoCameraOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// ====== 平台定义 ======
const platforms = [
  { id: 'tiktok', name: 'TikTok', icon: '🎵', spec: '9:16 竖版' },
  { id: 'reels', name: 'Instagram Reels', icon: '📸', spec: '9:16 竖版' },
  { id: 'youtube-shorts', name: 'YouTube Shorts', icon: '▶️', spec: '9:16 竖版' },
  { id: 'amazon-post', name: 'Amazon Post', icon: '📦', spec: '1:1 方形' },
]

interface Scene {
  duration: number
  frameRef: string       // 首帧参考图 URL（来自静态素材库）
  visual: string          // 画面描述
  narration: string       // 文案/旁白
  cameraMovement: string // 运镜方式
  shotSize: string        // 镜头景别
  bgm: string             // BGM/音效
  subtitleStyle: string   // 字幕样式
}

const defaultScenes: Scene[] = [
  { duration: 3, frameRef: '', visual: '', narration: '', cameraMovement: 'push-in', shotSize: 'closeup', bgm: 'upbeat', subtitleStyle: 'bold-bottom' },
  { duration: 5, frameRef: '', visual: '', narration: '', cameraMovement: 'rotate', shotSize: 'medium-shot', bgm: 'upbeat', subtitleStyle: 'bold-bottom' },
  { duration: 5, frameRef: '', visual: '', narration: '', cameraMovement: 'pull-out', shotSize: 'full-shot', bgm: 'upbeat', subtitleStyle: 'highlight' },
  { duration: 4, frameRef: '', visual: '', narration: '', cameraMovement: 'static', shotSize: 'closeup', bgm: 'cinematic', subtitleStyle: 'bold-bottom' },
  { duration: 3, frameRef: '', visual: '', narration: '', cameraMovement: 'zoom-dolly', shotSize: 'medium-shot', bgm: 'swoosh', subtitleStyle: 'highlight' },
]

const defaultForm = () => ({
  platform: 'tiktok',
  duration: '30s',
  videoStyle: 'problem-solution',
  scriptOptions: ['hook-opening', 'pain-agitate', 'cta-strong', 'subtitle-friendly'] as string[],
  extraScriptPrompt: '',
  scenes: JSON.parse(JSON.stringify(defaultScenes)) as Scene[],
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
  return pickedProduct.value.description?.slice(0, 100) || ''
})

const onProductSelect = (product: any) => {
  pickedProduct.value = product
}

// 从工作商品自动填充
watch(workingProduct, (product) => {
  if (product && !pickedProduct.value) {
    pickedProduct.value = product
  }
}, { immediate: true })

// ====== 分镜操作 ======
function addScene() {
  form.scenes.push({
    duration: 5,
    frameRef: '',
    visual: '',
    narration: '',
    cameraMovement: 'static',
    shotSize: 'medium-shot',
    bgm: 'upbeat',
    subtitleStyle: 'bold-bottom',
  })
}

function removeScene(idx: number) {
  form.scenes.splice(idx, 1)
}

function resetToDefaultScenes() {
  form.scenes = JSON.parse(JSON.stringify(defaultScenes)) as Scene[]
}

function updateScene(idx: number, field: keyof Scene, value: any) {
  ;(form.scenes[idx] as any)[field] = value
}

// 打开素材库选择器（TODO: 接静态素材库弹窗）
function openAssetPicker(sceneIdx: number) {
  message.info('素材库选择器开发中 — 可手动粘贴图片 URL')
}

// ====== 提交 ======
const handleSubmit = () => {
  if (!pickedProduct.value) {
    message.warning('请先载入产品')
    return
  }
  const totalDuration = form.scenes.reduce((sum, s) => sum + s.duration, 0)
  const maxDuration = parseInt(form.duration) || 30
  if (totalDuration > maxDuration + 10) {
    message.warning(`分镜总时长 ${totalDuration}s 超出目标时长 ${maxDuration}s 较多，请调整`)
  }
  loading.value = true
  emit('startAnalysis', {
    tool: 'video-script-gen',
    ...form,
    _sourceProduct: pickedProduct.value,
    // 自动回填的字段
    selling_points: autoFilledSellingPoints.value,
    pain_points: autoFilledPainPoints.value,
    total_scene_duration: totalDuration,
  })
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
  pickedProduct.value = null
}
</script>

<style scoped>
.video-script-config {
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
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.required-mark { color: #ff4d4f; }
.optional-mark { font-size: 11px; font-weight: 400; color: #8c8c8c; margin-left: 4px; }

/* 产品载入 */
.product-load-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.product-loaded-hint {
  font-size: 11px; color: #52c41a; background: #f6ffed;
  padding: 2px 8px; border-radius: 4px; border: 1px solid #b7eb8f;
}

/* 产品信息预览 */
.product-info-preview {
  display: flex; flex-direction: column; gap: 4px;
  padding: 8px 10px; background: #fafafa; border: 1px solid #f0f0f0; border-radius: 6px;
}
.preview-field { display: flex; gap: 6px; font-size: 11px; }
.preview-label { color: #8c8c8c; flex-shrink: 0; min-width: 56px; }
.preview-value { color: #262626; word-break: break-all; }

/* 平台网格 */
.platform-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.platform-card {
  padding: 10px 6px; border: 2px solid #f0f0f0; border-radius: 8px;
  text-align: center; cursor: pointer; transition: all 0.2s;
}
.platform-card:hover { border-color: #bae7ff; }
.platform-card.active { border-color: #1890ff; background: #e6f7ff; }
.platform-emoji { font-size: 20px; display: block; margin-bottom: 4px; }
.platform-name { font-size: 11px; font-weight: 600; display: block; }
.platform-spec { font-size: 10px; color: #8c8c8c; }

/* 表单 */
.form-group > label { display: block; font-size: 12px; color: #595959; margin-bottom: 3px; font-weight: 500; }
.form-row { display: flex; gap: 8px; }
.flex-1 { flex: 1; }

/* 脚本选项 */
.script-options-row { display: flex; flex-wrap: wrap; gap: 8px; }

/* 分镜列表 */
.storyboard-actions { display: flex; gap: 4px; }
.scenes-list {
  display: flex; flex-direction: column; gap: 10px;
  max-height: 420px; overflow-y: auto; padding-right: 4px;
}
.scene-card { border: 1px solid #f0f0f0; border-radius: 8px; padding: 10px; background: #fff; }
.scene-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  padding-bottom: 6px; border-bottom: 1px dashed #f0f0f0;
}
.scene-num {
  font-size: 12px; font-weight: 700; color: #1890ff;
  background: #e6f7ff; padding: 1px 8px; border-radius: 10px;
}
.scene-time { font-size: 11px; color: #8c8c8c; margin-left: auto; }

/* 首帧引用行 */
.frame-ref-row { display: flex; align-items: center; gap: 4px; }
.frame-thumb {
  max-width: 100%; max-height: 80px; border-radius: 4px;
  margin-top: 4px; object-fit: contain; border: 1px solid #f0f0f0;
}

.action-bar {
  display: flex; flex-direction: column; gap: 6px;
  margin-top: 8px; padding-top: 10px; border-top: 1px solid #f0f0f0;
}
</style>
