<template>
  <div class="video-generator-config">
    <!-- 工作商品横幅 -->
    <div v-if="workingProduct" class="product-banner">
      <span class="banner-icon">📦</span>
      <span class="banner-text">{{ workingProduct.title?.slice(0, 30) }}{{ workingProduct.title?.length > 30 ? '…' : '' }}</span>
    </div>

    <!-- ====== 第一层：选择生成模式（2 张大卡片，互斥） ====== -->
    <div class="section-title">生成模式</div>
    <div class="mode-cards">
      <div
        class="mode-card"
        :class="{ active: form.mode === 'storyboard-pro' }"
        @click="switchMode('storyboard-pro')"
      >
        <span class="mode-icon">🎬</span>
        <span class="mode-name">分镜脚本专业模式</span>
        <small>完整带货视频 · AI 生成分镜表，每镜自由选素材来源</small>
      </div>
      <div
        class="mode-card"
        :class="{ active: form.mode === 'single-image' }"
        @click="switchMode('single-image')"
      >
        <span class="mode-icon">🖼️</span>
        <span class="mode-name">单图极速生成</span>
        <small>快速广告短片 · 挑一张图 + 产品文案，AI 全程自动绘制</small>
      </div>
    </div>

    <!-- ================================================================
         模式 A：分镜脚本专业模式
         AI 生成分镜表 → 每个镜头单独选择素材来源
    ================================================================ -->
    <template v-if="form.mode === 'storyboard-pro'">
      <a-divider style="margin: 12px 0" />

      <!-- 未生成：引导按钮 -->
      <div v-if="!storyboardGenerated" class="gen-storyboard-panel">
        <p class="panel-desc">
          由 AI 根据产品卖点自动生成 5-6 个镜头的分镜表；生成后可为每个镜头选择素材来源
          （<b>产品素材库 / 手动上传</b>）。
        </p>
        <a-button type="primary" block :loading="storyboardLoading" @click="generateStoryboard">
          <RobotOutlined /> AI 自动生成分镜表
        </a-button>

        <!-- 已有带货脚本 → 一键导入复用（避免重复生成） -->
        <div v-if="videoScriptsStore.lastScript" class="import-script-tip">
          <span>📄 检测到「短视频带货脚本」结果（{{ videoScriptsStore.sceneCount() }} 镜）</span>
          <a-button size="small" type="primary" ghost block @click="importScript" style="margin-top: 6px">
            <ImportOutlined /> 导入带货脚本
          </a-button>
          <a-button size="small" type="link" danger block @click="clearScriptImport">清除已有脚本</a-button>
        </div>
        <div v-else class="import-script-empty">
          💡 还没有带货脚本？可先到「短视频带货脚本」工具生成，再回来一键导入复用。
        </div>
      </div>

      <!-- 已生成：镜头编辑 -->
      <template v-else>
        <div class="section-head-row">
          <span class="section-title" style="margin-top: 0">分镜镜头（{{ form.storyboardScenes.length }}）</span>
          <a-button type="text" size="small" @click="resetStoryboard">重新生成</a-button>
        </div>

        <div class="frames-list">
          <div v-for="(scene, idx) in form.storyboardScenes" :key="idx" class="frame-card">
            <div class="frame-header">
              <span class="frame-num">镜头 {{ idx + 1 }}</span>
              <span v-if="scene.desc" class="scene-desc" :title="scene.desc">{{ scene.desc }}</span>
              <a-button
                v-if="form.storyboardScenes.length > 1"
                type="text"
                size="small"
                danger
                @click="removeScene(idx)"
              >删除</a-button>
            </div>

            <!-- 旁白文案（从带货脚本带入） -->
            <div v-if="scene.narration" class="scene-narration" :title="scene.narration">
              💬 {{ scene.narration }}
            </div>

            <!-- 该镜头的素材来源（子步骤） -->
            <div class="scene-source-row">
              <span class="src-label">素材来源</span>
              <a-radio-group
                :value="scene.source"
                size="small"
                @change="(e: any) => setSceneSource(idx, e.target.value)"
              >
                <a-radio-button value="library">📁 产品素材库</a-radio-button>
                <a-radio-button value="upload">📤 手动上传</a-radio-button>
              </a-radio-group>
            </div>

            <!-- 首帧图区 -->
            <div class="frame-image-area" @click="openSourcePicker('scene', idx)">
              <div v-if="!scene.imageUrl" class="frame-placeholder">
                <PlusOutlined style="font-size: 20px; color: #d9d9d9" />
                <span style="font-size: 11px; color: #bfbfbf">
                  点击从{{ scene.source === 'upload' ? '本地上传' : '产品素材库' }}选取
                </span>
              </div>
              <div v-else class="frame-image-wrapper">
                <img :src="scene.imageUrl" alt="首帧图" class="frame-preview-img" />
                <div class="frame-img-overlay">
                  <a-button type="text" size="small" @click.stop="openSourcePicker('scene', idx)">
                    <SwapOutlined /> 更换
                  </a-button>
                  <a-button type="text" size="small" danger @click.stop="clearSceneImage(idx)">
                    <DeleteOutlined />
                  </a-button>
                </div>
                <span class="frame-source-tag">{{ sourceLabel(scene.source) }}</span>
              </div>
            </div>

            <div class="form-row" style="margin-top: 6px">
              <div class="form-group flex-1">
                <label>运镜指令</label>
                <a-select
                  :model-value="scene.cameraMovement"
                  @change="(v: string) => updateScene(idx, 'cameraMovement', v)"
                  size="small"
                  style="width: 100%"
                >
                  <a-select-option value="static">固定机位</a-select-option>
                  <a-select-option value="push-in-slow">缓慢推近</a-select-option>
                  <a-select-option value="pull-out-reveal">拉远揭示</a-select-option>
                  <a-select-option value="pan-left-right">左右横扫</a-select-option>
                  <a-select-option value="rotate-360">环绕 360°</a-select-option>
                  <a-select-option value="zoom-dolly">变焦推轨</a-select-option>
                  <a-select-option value="ken-burns">Ken Burns</a-select-option>
                </a-select>
              </div>
              <div class="form-group flex-1">
                <label>时长（秒）</label>
                <a-input-number
                  :model-value="scene.duration"
                  @change="(v: number) => updateScene(idx, 'duration', v || 3)"
                  :min="1" :max="15" size="small" style="width: 100%"
                />
              </div>
            </div>
          </div>
        </div>

        <div class="frame-actions">
          <a-button size="small" block @click="addScene">
            <PlusOutlined /> 添加镜头
          </a-button>
        </div>
      </template>
    </template>

    <!-- ================================================================
         模式 B：单图极速生成
         挑一张图 + 产品文案 → AI 全程自动绘制画面生成视频
    ================================================================ -->
    <template v-else>
      <a-divider style="margin: 12px 0" />

      <!-- 底图（素材来源：素材库 / 手动上传 / AI 生成一张参考图） -->
      <div class="section-title">挑选一张底图</div>
      <p style="font-size: 11px; color: #8c8c8c; margin: 0 0 8px">
        选一张产品图作为起点，AI 将围绕它自动绘制全部画面
      </p>
      <div class="single-image-picker" @click="openSourcePicker('single', 0)">
        <img v-if="form.singleImageUrl" :src="form.singleImageUrl" alt="底图" class="single-img" />
        <div v-else class="single-placeholder">
          <PictureOutlined style="font-size: 22px; color: #d9d9d9" />
          <span>点击从{{ form.singleSource === 'upload' ? '本地上传' : '产品素材库' }}选取底图</span>
        </div>
        <span v-if="form.singleImageUrl" class="single-img-tag">{{ sourceLabel(form.singleSource) }}</span>
      </div>

      <!-- 产品文案 -->
      <div class="form-group" style="margin-top: 10px">
        <label>产品文案（AI 据此创作）</label>
        <a-textarea
          v-model:value="form.singleCopyText"
          :rows="3"
          placeholder="描述产品卖点与宣传角度..."
          size="small"
        />
      </div>
      <div class="form-group" style="margin-top: 6px">
        <label>一句话修正文案逻辑（可选）</label>
        <a-input
          v-model:value="form.copyRefine"
          placeholder="如：强调送礼场景 / 面向新手妈妈 / 语气更幽默"
          size="small"
        />
      </div>
    </template>

    <!-- ====== 视频参数（两种模式通用） ====== -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">视频参数</div>
    <div class="form-row">
      <div class="form-group flex-1">
        <label>目标平台</label>
        <a-select v-model:value="form.targetPlatform" size="small" style="width: 100%">
          <a-select-option value="tiktok">TikTok (9:16)</a-select-option>
          <a-select-option value="reels">Instagram Reels (9:16)</a-select-option>
          <a-select-option value="youtube-shorts">YouTube Shorts (9:16)</a-select-option>
          <a-select-option value="amazon-video">Amazon 视频 (16:9)</a-select-option>
        </a-select>
      </div>
      <div class="form-group flex-1">
        <label>BGM 风格</label>
        <a-select v-model:value="form.bgmStyle" size="small" style="width: 100%">
          <a-select-option value="auto">AI 自动匹配</a-select-option>
          <a-select-option value="upbeat">轻快节奏</a-select-option>
          <a-select-option value="cinematic">电影感</a-select-option>
          <a-select-option value="electronic">电子/科技</a-select-option>
          <a-select-option value="lo-fi">Lo-Fi 放松</a-select-option>
        </a-select>
      </div>
    </div>

    <!-- 字幕与文字 -->
    <a-divider style="margin: 12px 0" />
    <div class="section-title">字幕 & 文字叠加</div>
    <a-checkbox-group v-model:value="form.textOptions">
      <div class="text-options-row">
        <a-checkbox value="auto-subtitle">自动字幕</a-checkbox>
        <a-checkbox value="product-name">产品名</a-checkbox>
        <a-checkbox value="price-tag">价格标签</a-checkbox>
        <a-checkbox value="cta-button">CTA 按钮</a-checkbox>
        <a-checkbox value="brand-logo">品牌 Logo</a-checkbox>
      </div>
    </a-checkbox-group>

    <!-- 高级选项 -->
    <a-collapse ghost size="small" style="margin-top: 4px">
      <a-collapse-panel key="advanced" header="高级选项">
        <div class="form-row">
          <div class="form-group flex-1">
            <label>帧率 (FPS)</label>
            <a-select v-model:value="form.fps" size="small" style="width: 100%">
              <a-select-option value="24">24 FPS</a-select-option>
              <a-select-option value="30">30 FPS</a-select-option>
              <a-select-option value="60">60 FPS</a-select-option>
            </a-select>
          </div>
          <div class="form-group flex-1">
            <label>画面比例</label>
            <a-select v-model:value="form.aspectRatio" size="small" style="width: 100%">
              <a-select-option value="9:16">9:16 竖版</a-select-option>
              <a-select-option value="16:9">16:9 横版</a-select-option>
              <a-select-option value="1:1">1:1 方形</a-select-option>
            </a-select>
          </div>
        </div>
        <div class="form-group">
          <label>额外指令（可选）</label>
          <a-textarea
            v-model:value="form.extraPrompt"
            :rows="2"
            placeholder="如：开头前2秒强视觉冲击、结尾3秒循环引导关注..."
            size="small"
          />
        </div>
        <div class="archive-section">
          <a-checkbox v-model:checked="form.archiveToProduct">
            生成后由我确认再归档到素材库（绑定当前产品）
          </a-checkbox>
        </div>
      </a-collapse-panel>
    </a-collapse>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <VideoCameraAddOutlined /> 开始生成视频
      </a-button>
    </div>

    <!-- ================================================================
         素材来源面板（模式内的选图器，非顶层入口）
         仅两类：产品素材库（默认）/ 手动上传
         点击占位区 → 下方内联展开 → 单击图片直接选中
    ================================================================ -->
    <a-drawer
      v-model:open="pickerVisible"
      :title="pickerTitle"
      placement="right"
      :width="560"
      :closable="true"
      :mask-closable="true"
    >
      <a-tabs v-model:active-key="pickerTab" size="small">
        <!-- Tab1 产品素材库（默认）—— 进入即可点击图片直接选中 -->
        <a-tab-pane key="library" tab="📁 产品素材库">
          <div v-if="staticAssets.length" class="picker-asset-grid">
            <div
              v-for="asset in staticAssets"
              :key="asset.id"
              class="picker-asset"
              @click="pickFromLibrary(asset)"
            >
              <img :src="asset.url" :alt="asset.type" loading="lazy" @error="onImgError" />
              <span class="picker-asset-tag">{{ assetTypeLabel(asset.type) }}</span>
              <span class="picker-asset-check">✓</span>
            </div>
          </div>
          <a-empty v-else description="素材库暂无图片，请到「手动上传」" :image-style="{ height: '40px' }" />
        </a-tab-pane>

        <!-- Tab2 手动上传 -->
        <a-tab-pane key="upload" tab="📤 手动上传">
          <div class="upload-drop" @click="pickerFileRef?.click()">
            <input
              ref="pickerFileRef"
              type="file"
              accept="image/*"
              style="display: none"
              @change="handlePickerFileChange"
            />
            <CloudUploadOutlined style="font-size: 30px; color: #1890ff" />
            <p style="margin: 8px 0 0; font-size: 12px; color: #595959">点击选择本地图片</p>
            <p style="margin: 2px 0 0; font-size: 11px; color: #bfbfbf">JPG / PNG / WebP，建议 1080×1920</p>
          </div>
          <div v-if="pickerUploadPreview" class="upload-preview-row">
            <img :src="pickerUploadPreview" alt="" />
            <a-button type="primary" size="small" @click="confirmUpload">使用此图</a-button>
            <a-button size="small" @click="pickerUploadPreview = ''">重选</a-button>
          </div>
        </a-tab-pane>
      </a-tabs>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import { useAssetLibraryStore } from '@/stores/assetLibrary'
import {
  ReloadOutlined,
  PictureOutlined,
  RobotOutlined,
  PlusOutlined,
  DeleteOutlined,
  VideoCameraAddOutlined,
  SwapOutlined,
  CloudUploadOutlined,
  ImportOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useVideoScriptsStore } from '@/stores/videoScripts'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))
const videoScriptsStore = useVideoScriptsStore()

// ====== 类型 ======
interface Scene {
  duration: number
  desc: string          // 画面描述（AI 生成画面用 / 展示用）
  narration: string     // 旁白文案（AI 生成）
  source: 'library' | 'upload'
  imageUrl: string
  cameraMovement: string
  transition: string
}

const sourceLabel = (s: string) => ({ library: '素材库', upload: '上传' })[s] || s

// ====== 表单 ======
const defaultForm = () => ({
  mode: 'storyboard-pro' as 'storyboard-pro' | 'single-image',
  // 分镜专业模式
  storyboardScenes: [] as Scene[],
  // 单图极速模式
  singleImageUrl: '',
  singleSource: 'library' as 'library' | 'upload',
  singleCopyText: '',
  copyRefine: '',
  // 通用视频参数
  targetPlatform: 'tiktok',
  bgmStyle: 'auto',
  textOptions: ['auto-subtitle'] as string[],
  fps: '30',
  aspectRatio: '9:16',
  extraPrompt: '',
  archiveToProduct: true,
})

const form = reactive(defaultForm())

const storyboardGenerated = ref(false)
const storyboardLoading = ref(false)

// 素材来源弹窗状态
const pickerVisible = ref(false)
const pickerTab = ref('library')  // 默认进入素材库
const pickerTarget = ref<{ kind: 'scene' | 'single'; idx: number } | null>(null)
const pickerFileRef = ref<HTMLInputElement | null>(null)
const pickerUploadPreview = ref('')
const pickerTitle = computed(() =>
  pickerTarget.value?.kind === 'scene'
    ? `镜头 ${pickerTarget.value.idx + 1} · 选择素材`
    : '选择底图'
)

// ====== 素材库（store） ======
interface StaticAsset { id: string; url: string; type: string }
const staticAssets = computed<StaticAsset[]>(() => {
  const assetStore = useAssetLibraryStore()
  return assetStore.items
    .filter(a => a.kind === 'image' && a.url)
    .map(a => ({ id: a.id, url: a.url, type: a.category || 'other' }))
})

// ====== 模式切换 ======
function switchMode(mode: 'storyboard-pro' | 'single-image') {
  form.mode = mode
  // 切到单图时自动预填产品文案
  if (mode === 'single-image' && !form.singleCopyText && workingProduct?.value) {
    const p = workingProduct.value
    form.singleCopyText = p.selling_points || (p.bullet_points || []).join('；') || `新品上架，欢迎了解 ${p.title || '本产品'} 的亮点与优惠！`
  }
}

// ====== 工作商品自动填充 ======
watch(workingProduct, (product) => {
  if (product) {
    form.singleCopyText = product.selling_points || (product.bullet_points || []).join('；') || ''
  }
}, { immediate: true })

// ====== AI 生成分镜表（内置按钮 → mock） ======
function generateStoryboard() {
  if (!workingProduct?.value) {
    message.warning('请先载入产品（顶部「载入产品」按钮）')
    return
  }
  const p = workingProduct.value
  const name = p.title || '产品'
  storyboardLoading.value = true
  // Mock：模拟 AI 生成分镜表耗时
  setTimeout(() => {
    const selling = p.selling_points?.split(' | ').filter(Boolean) || []
    const bullets = p.bullet_points || []
    const featLine = selling[0] || bullets[0]?.title || ''
    const scenes: Scene[] = [
      { duration: 3, desc: '开篇钩子：产品特写 + 痛点字幕（前3秒抓住注意力）', narration: '', source: 'library', imageUrl: '', cameraMovement: 'push-in-slow', transition: 'fade' },
      { duration: 4, desc: '产品外观 360° 展示（白底三视图氛围）', narration: `${name} 惊艳登场`, source: 'library', imageUrl: '', cameraMovement: 'rotate-360', transition: 'fade' },
      { duration: 4, desc: '核心卖点场景演示（自动运镜跟随产品）', narration: featLine ? `核心亮点：${featLine}` : '', source: 'library', imageUrl: '', cameraMovement: 'zoom-dolly', transition: 'slide' },
      { duration: 4, desc: '使用场景 / 生活方式画面', narration: '怎么用都顺手', source: 'library', imageUrl: '', cameraMovement: 'pan-left-right', transition: 'slide' },
      { duration: 3, desc: '细节/材质特写（Ken Burns 缩放营造质感）', narration: '', source: 'library', imageUrl: '', cameraMovement: 'ken-burns', transition: 'fade' },
      { duration: 3, desc: '结尾 CTA：价格 + 行动号召', narration: '限时优惠，快来下单！', source: 'library', imageUrl: '', cameraMovement: 'static', transition: 'fade' },
    ]
    form.storyboardScenes = scenes
    storyboardGenerated.value = true
    storyboardLoading.value = false
    message.success(`已生成 ${scenes.length} 镜分镜表，请为每个镜头选择素材来源`)
  }, 900)
}

function resetStoryboard() {
  storyboardGenerated.value = false
  form.storyboardScenes = []
}
function addScene() {
  form.storyboardScenes.push({
    duration: 4, desc: '', narration: '',
    source: 'library', imageUrl: '', cameraMovement: 'static', transition: 'fade',
  })
}
function removeScene(idx: number) { form.storyboardScenes.splice(idx, 1) }
function updateScene(idx: number, field: keyof Scene, value: any) {
  ;(form.storyboardScenes[idx] as any)[field] = value
}
function setSceneSource(idx: number, source: Scene['source']) {
  form.storyboardScenes[idx].source = source
  form.storyboardScenes[idx].imageUrl = ''   // 换来源后需重新选取
}
function clearSceneImage(idx: number) { form.storyboardScenes[idx].imageUrl = '' }

// 脚本运镜值 → 视频组件下拉可选项的映射（兼容脚本里的简短写法）
const CAMERA_COMPAT: Record<string, string> = {
  rotate: 'rotate-360',
  orbit: 'rotate-360',
  'camera-shake': 'static',
}

/** 从「短视频带货脚本」最近结果一键导入分镜 */
function importScript() {
  const script = videoScriptsStore.lastScript
  if (!script || !script.storyboard?.length) {
    message.warning('还没有可导入的带货脚本，请先到「短视频带货脚本」工具生成')
    return
  }
  form.storyboardScenes = script.storyboard.map((s) => ({
    duration: s.duration || 3,
    desc: s.visual || '',
    narration: s.narration || '',
    source: 'library' as Scene['source'],
    imageUrl: '',
    cameraMovement: CAMERA_COMPAT[s.cameraMovement] || s.cameraMovement || 'static',
    transition: 'fade',
  }))
  storyboardGenerated.value = true
  message.success(`已导入「${script.productName}」的 ${form.storyboardScenes.length} 镜分镜表，下一步为每个镜头选素材来源`)
}

function clearScriptImport() {
  videoScriptsStore.clearLastScript()
  message.success('已清除最近脚本缓存')
}

// ====== 素材来源弹窗操作 ======
function openSourcePicker(kind: 'scene' | 'single', idx: number) {
  pickerTarget.value = { kind, idx }
  // 默认打开素材库 Tab（除非当前镜头已标记为 upload）
  const cur = kind === 'scene' ? form.storyboardScenes[idx]?.source : form.singleSource
  pickerTab.value = cur === 'upload' ? 'upload' : 'library'
  pickerUploadPreview.value = ''
  pickerVisible.value = true
}

function applyPicked(url: string, source: Scene['source']) {
  if (pickerTarget.value?.kind === 'scene') {
    const scene = form.storyboardScenes[pickerTarget.value.idx]
    if (scene) { scene.imageUrl = url; scene.source = source }
  } else {
    form.singleImageUrl = url
    form.singleSource = source
  }
  pickerVisible.value = false
}

function pickFromLibrary(asset: StaticAsset) {
  applyPicked(asset.url, 'library')
}

function handlePickerFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 20 * 1024 * 1024) { message.error('文件超过 20MB'); return }
  const reader = new FileReader()
  reader.onload = () => { pickerUploadPreview.value = reader.result as string }
  reader.readAsDataURL(file)
}

function confirmUpload() {
  if (!pickerUploadPreview.value) { message.warning('请先选择图片'); return }
  applyPicked(pickerUploadPreview.value, 'upload')
}

// ====== 提交 ======
const handleSubmit = () => {
  if (!workingProduct?.value) {
    message.warning('请先载入产品（顶部「载入产品」按钮）')
    return
  }
  if (form.mode === 'storyboard-pro') {
    if (!storyboardGenerated.value || form.storyboardScenes.length === 0) {
      message.warning('请先点击「AI 自动生成分镜表」')
      return
    }
    const emptyScenes = form.storyboardScenes.filter(s => !s.imageUrl)
    if (emptyScenes.length > 0) {
      message.warning(`有 ${emptyScenes.length} 个镜头还没选素材来源，请逐个补全`)
      return
    }
  } else {
    if (!form.singleImageUrl) {
      message.warning('请先选择一张底图')
      return
    }
    if (!form.singleCopyText.trim()) {
      message.warning('请填写产品文案')
      return
    }
  }

  loading.value = true
  emit('startAnalysis', {
    tool: 'ai-video-generator',
    mode: form.mode,
    // 分镜专业模式
    storyboardScenes: form.storyboardScenes.map(s => ({
      duration: s.duration,
      desc: s.desc,
      narration: s.narration,
      source: s.source,
      imageUrl: s.imageUrl,
      cameraMovement: s.cameraMovement,
      transition: s.transition,
    })),
    // 单图极速
    singleImageUrl: form.singleImageUrl,
    singleCopyText: form.singleCopyText,
    copyRefine: form.copyRefine,
    // 通用
    targetPlatform: form.targetPlatform,
    bgmStyle: form.bgmStyle,
    textOptions: form.textOptions,
    fps: form.fps,
    aspectRatio: form.aspectRatio,
    extraPrompt: form.extraPrompt,
    archiveToProduct: form.archiveToProduct,
    _sourceProduct: workingProduct?.value,
  })
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
  storyboardGenerated.value = false
}

function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.opacity = '0.3'
  el.style.background = '#fafafa'
}

function assetTypeLabel(type: string): string {
  const map: Record<string, string> = {
    'white-bg': '白底图', 'three-view': '三视图', detail: '细节', scene: '场景',
    lifestyle: '生活方式', character: '人物', 'storyboard-frame': '分镜', other: '其他',
  }
  return map[type] || type
}
</script>

<style scoped>
.video-generator-config {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.product-banner {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px; background: #e6f7ff; border: 1px solid #91d5ff;
  border-radius: 6px; font-size: 12px; color: #1890ff;
}
.banner-icon { font-size: 14px; }
.banner-text { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.section-title { font-size: 12px; font-weight: 600; color: #262626; margin-top: 4px; }
.section-head-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }

/* ===== 第一层：模式大卡片 ===== */
.mode-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mode-card {
  display: flex; flex-direction: column; align-items: flex-start;
  padding: 12px 10px; border: 2px solid #f0f0f0; border-radius: 10px;
  cursor: pointer; transition: all 0.2s; text-align: left;
  background: #fff;
}
.mode-card:hover { border-color: #bae7ff; box-shadow: 0 2px 8px rgba(24,144,255,0.08); }
.mode-card.active { border-color: #1890ff; background: #e6f7ff; }
.mode-icon { font-size: 22px; }
.mode-name { font-size: 13px; font-weight: 700; margin: 4px 0 2px; color: #262626; }
.mode-card small { font-size: 11px; color: #8c8c8c; line-height: 1.5; }

/* ===== 生成分镜引导 ===== */
.gen-storyboard-panel {
  border: 1px dashed #d9d9d9; border-radius: 8px; padding: 12px;
  background: #fafafa; display: flex; flex-direction: column; gap: 10px;
}
.panel-desc { margin: 0; font-size: 12px; color: #595959; line-height: 1.7; }
.panel-desc b { color: #262626; }

/* ===== 镜头列表 ===== */
.frames-list { display: flex; flex-direction: column; gap: 10px; max-height: 420px; overflow-y: auto; padding-right: 4px; }
.frame-card { border: 1px solid #f0f0f0; border-radius: 8px; padding: 10px; background: #fff; }
.frame-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  padding-bottom: 6px; border-bottom: 1px dashed #f0f0f0;
}
.frame-num {
  font-size: 12px; font-weight: 700; color: #1890ff;
  background: #e6f7ff; padding: 1px 8px; border-radius: 10px; flex-shrink: 0;
}
.scene-desc {
  flex: 1; font-size: 11px; color: #8c8c8c; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.scene-narration {
  font-size: 11px; color: #595959; background: #f6ffed; border-radius: 4px;
  padding: 3px 6px; margin-bottom: 6px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; border-left: 2px solid #52c41a;
}

/* 导入脚本提示 */
.import-script-tip {
  margin-top: 10px; padding: 8px 10px; background: #fff7e6;
  border: 1px solid #ffd591; border-radius: 6px;
  font-size: 12px; color: #d48806;
}
.import-script-empty {
  margin-top: 8px; font-size: 11px; color: #8c8c8c; line-height: 1.6;
  text-align: center; padding: 8px; background: #fafafa; border-radius: 6px;
}

/* 素材来源（子步骤） */
.scene-source-row {
  display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
}
.src-label { font-size: 11px; color: #8c8c8c; flex-shrink: 0; }
.scene-source-row :deep(.ant-radio-button-wrapper) { font-size: 11px; padding: 0 7px; }

.frame-image-area { min-height: 80px; cursor: pointer; }
.frame-placeholder {
  border: 2px dashed #d9d9d9; border-radius: 6px; height: 80px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; transition: border-color 0.2s;
}
.frame-placeholder:hover { border-color: #1890ff; }
.frame-image-wrapper { position: relative; }
.frame-preview-img {
  width: 100%; max-height: 120px; object-fit: contain;
  border-radius: 6px; border: 1px solid #f0f0f0;
}
.frame-img-overlay {
  position: absolute; inset: 0; background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center; gap: 4px;
  opacity: 0; transition: opacity 0.2s; border-radius: 6px;
}
.frame-image-wrapper:hover .frame-img-overlay { opacity: 1; }
.frame-source-tag {
  position: absolute; top: 4px; left: 4px; background: rgba(24,144,255,0.85);
  color: #fff; font-size: 10px; padding: 1px 6px; border-radius: 4px;
}

.frame-actions { display: flex; gap: 6px; margin-top: 8px; }

/* ===== 单图极速 ===== */
.single-image-picker {
  border: 2px dashed #d9d9d9; border-radius: 10px; overflow: hidden;
  position: relative; cursor: pointer; transition: border-color 0.2s;
  min-height: 150px;
}
.single-image-picker:hover { border-color: #1890ff; }
.single-img { width: 100%; max-height: 220px; object-fit: contain; display: block; }
.single-placeholder {
  min-height: 150px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; color: #bfbfbf; font-size: 12px;
}
.single-img-tag {
  position: absolute; top: 6px; right: 6px; background: rgba(24,144,255,0.85);
  color: #fff; font-size: 10px; padding: 2px 8px; border-radius: 4px;
}

/* ===== 表单通用 ===== */
.form-group > label { display: block; font-size: 12px; color: #595959; margin-bottom: 3px; font-weight: 500; }
.form-row { display: flex; gap: 8px; }
.flex-1 { flex: 1; }
.text-options-row { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.archive-section { margin-top: 8px; padding: 8px; background: #f6ffed; border-radius: 6px; border: 1px solid #b7eb8f; }
.action-bar { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; padding-top: 10px; border-top: 1px solid #f0f0f0; }

/* ===== 素材库选择网格（弹窗内） ===== */
.picker-asset-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; max-height: 300px; overflow-y: auto; }
.picker-asset {
  position: relative; border-radius: 6px; overflow: hidden; aspect-ratio: 1;
  cursor: pointer; border: 2px solid transparent; transition: border-color 0.15s;
}
.picker-asset:hover { border-color: #1890ff; }
.picker-asset img { width: 100%; height: 100%; object-fit: cover; display: block; }
.picker-asset-tag {
  position: absolute; bottom: 2px; left: 2px; background: rgba(0,0,0,0.65);
  color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 3px;
}

/* 上传 */
.upload-drop {
  border: 2px dashed #d9d9d9; border-radius: 8px; padding: 18px;
  text-align: center; cursor: pointer; transition: border-color 0.2s;
}
.upload-drop:hover { border-color: #1890ff; }
.upload-preview-row {
  display: flex; align-items: center; gap: 12px; margin-top: 12px;
}
.upload-preview-row img { width: 72px; height: 72px; object-fit: cover; border-radius: 6px; border: 1px solid #f0f0f0; }
</style>
