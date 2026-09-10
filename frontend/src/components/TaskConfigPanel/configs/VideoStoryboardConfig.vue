<template>
  <div class="video-storyboard-config">
    <!-- 工作商品横幅 -->
    <div v-if="workingProduct" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.title?.slice(0, 30) }}{{ workingProduct.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <!-- 平台选择 -->
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
    <div class="section-title">视频信息</div>

    <div class="form-group">
      <label>产品名称</label>
      <a-input
        v-model:value="form.productName"
        placeholder="输入要展示的产品名称"
        size="small"
      />
    </div>

    <div class="form-group">
      <label>核心卖点 / USP</label>
      <a-textarea
        v-model:value="form.usp"
        :rows="2"
        placeholder="视频要突出的核心卖点，每行一个..."
        size="small"
      />
    </div>

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

    <!-- 分镜结构 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">
      分镜脚本结构
      <a-button type="link" size="small" @click="addScene">+ 添加镜头</a-button>
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
            v-if="form.scenes.length > 3"
            type="text"
            size="small"
            danger
            @click="removeScene(idx)"
          >删除</a-button>
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
          <a-input
            :model-value="scene.narration"
            @update:value="(v: string) => updateScene(idx, 'narration', v)"
            placeholder="如：这就是你的下一件必备好物"
            size="small"
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
            <label>BGM 建议</label>
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
        <VideoCameraOutlined /> 生成分镜脚本
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, type Ref } from 'vue'
import {
  ReloadOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { inject } from 'vue'

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
  visual: string
  narration: string
  cameraMovement: string
  shotSize: string
  bgm: string
  subtitleStyle: string
}

const defaultScenes: Scene[] = [
  { duration: 3, visual: '', narration: '', cameraMovement: 'push-in', shotSize: 'closeup', bgm: 'upbeat', subtitleStyle: 'bold-bottom' },
  { duration: 5, visual: '', narration: '', cameraMovement: 'rotate', shotSize: 'medium-shot', bgm: 'upbeat', subtitleStyle: 'bold-bottom' },
  { duration: 5, visual: '', narration: '', cameraMovement: 'pull-out', shotSize: 'full-shot', bgm: 'upbeat', subtitleStyle: 'highlight' },
]

const defaultForm = () => ({
  platform: 'tiktok',
  productName: '',
  usp: '',
  duration: '30s',
  videoStyle: 'product-showcase',
  scenes: JSON.parse(JSON.stringify(defaultScenes)) as Scene[],
})

const form = reactive(defaultForm())

// 从工作商品自动填充
watch(workingProduct, (product) => {
  if (product) {
    form.productName = product.title || ''
    const bullets = product.bullet_points || product.features || []
    if (bullets.length > 0) {
      form.usp = bullets.slice(0, 3).join('\n')
    }
  }
}, { immediate: true })

function addScene() {
  form.scenes.push({
    duration: 5,
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

function updateScene(idx: number, field: keyof Scene, value: any) {
  ;(form.scenes[idx] as any)[field] = value
}

const handleSubmit = () => {
  if (!form.productName.trim()) {
    message.warning('请输入产品名称')
    return
  }
  loading.value = true
  emit('startAnalysis', {
    tool: 'video-storyboard',
    ...form,
    _sourceProduct: workingProduct?.value,
  })
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
}
</script>

<style scoped>
.video-storyboard-config {
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

/* 平台网格 */
.platform-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.platform-card {
  padding: 10px 6px;
  border: 2px solid #f0f0f0;
  border-radius: 8px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.platform-card:hover { border-color: #bae7ff; }
.platform-card.active {
  border-color: #1890ff;
  background: #e6f7ff;
}

.platform-emoji { font-size: 20px; display: block; margin-bottom: 4px; }
.platform-name { font-size: 11px; font-weight: 600; display: block; }
.platform-spec { font-size: 10px; color: #8c8c8c; }

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

/* 分镜列表 */
.scenes-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

.scene-card {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 10px;
  background: #fff;
}

.scene-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px dashed #f0f0f0;
}

.scene-num {
  font-size: 12px;
  font-weight: 700;
  color: #1890ff;
  background: #e6f7ff;
  padding: 1px 8px;
  border-radius: 10px;
}

.scene-time {
  font-size: 11px;
  color: #8c8c8c;
  margin-left: auto;
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
