<template>
  <div class="video-script-config" :class="{ 'data-mode': isDataMode }">
    <!-- ====== 大屏模式 = 左右分栏：左半边精简配置 + 右半边分镜预览 ======
         触发条件：Workspace 顶栏 mode-switch 切到「大屏模式」（reviewMode==='data'）。
         与静态素材一致 —— AIGC 大屏是右栏内左右分栏（不是整页大屏）。
         左半边：载入产品 + 视频基本信息 + 脚本技巧（精简版，用户可调参数）。
         右半边：分镜卡片网格（脚本摘要 + 5 个镜头详情）。
         分镜表/首帧参考/额外要求在左侧隐藏（细节太多，分镜已在右侧预览）。 -->
    <div v-if="isDataMode" class="split-layout">
      <div class="split-form">
        <!-- ① 载入产品：2 选 1（产品库 / 不需要上传图片，脚本只要卖点痛点） -->
        <section class="cfg-section">
          <div class="section-title">
            <span class="title-icon">📦</span>
            <span class="title-text">载入产品</span>
            <span class="title-hint">脚本会从卖点/痛点自动生成</span>
            <ProductPickerButton
              :model-value="pickedProduct"
              :show-label="false"
              @select="onProductSelect"
            />
          </div>
          <div v-if="pickedProduct" class="product-info-line" :title="`卖点：${autoFilledSellingPoints || '—'}\n痛点：${autoFilledPainPoints || '—'}`">
            <span class="pi-label">卖点</span>
            <span class="pi-text">{{ autoFilledSellingPoints || '—' }}</span>
            <span class="pi-label">痛点</span>
            <span class="pi-text">{{ autoFilledPainPoints || '—' }}</span>
          </div>
          <div v-else class="picker-empty">
            <span>👆 点右上角文件夹按钮从产品库选</span>
          </div>
        </section>

        <!-- ② 视频基本信息（精简） -->
        <section class="cfg-section">
          <div class="section-title">
            <span class="title-icon">🎞️</span>
            <span class="title-text">视频基本信息</span>
          </div>
          <div class="form-row">
            <div class="form-group flex-1">
              <label>目标平台</label>
              <a-select v-model:value="form.platform" size="small" style="width: 100%">
                <a-select-option v-for="p in platforms" :key="p.id" :value="p.id">{{ p.icon }} {{ p.name }}</a-select-option>
              </a-select>
            </div>
            <div class="form-group flex-1">
              <label>视频时长</label>
              <a-select v-model:value="form.duration" size="small" style="width: 100%">
                <a-select-option value="15s">15 秒</a-select-option>
                <a-select-option value="30s">30 秒</a-select-option>
                <a-select-option value="45s">45 秒</a-select-option>
                <a-select-option value="60s">60 秒</a-select-option>
              </a-select>
            </div>
          </div>
          <div class="form-group">
            <label>脚本风格</label>
            <a-radio-group v-model:value="form.videoStyle" size="small">
              <a-radio-button value="problem-solution">痛点驱动</a-radio-button>
              <a-radio-button value="product-showcase">产品展示</a-radio-button>
              <a-radio-button value="story-telling">故事化</a-radio-button>
              <a-radio-button value="comparison">对比测评</a-radio-button>
            </a-radio-group>
          </div>
        </section>

        <!-- ③ 脚本技巧（精简） -->
        <section class="cfg-section">
          <div class="section-title">
            <span class="title-icon">✨</span>
            <span class="title-text">脚本技巧</span>
            <span class="title-hint">可多选</span>
          </div>
          <div class="checkbox-row">
            <a-checkbox
              v-for="opt in scriptOptions"
              :key="opt.value"
              :checked="form.scriptOptions.includes(opt.value)"
              @change="toggleScriptOption(opt.value)"
            >
              <span class="opt-label">{{ opt.label }}</span>
            </a-checkbox>
          </div>
        </section>

        <!-- 大屏下的「重新生成」按钮移到外层 action-bar，避免被 split-form 滚动带出视野 -->
      </div>

      <!-- 右半边：预览区 —— 复用 AIGCMediaResult（与对话流同一渲染真源，
           自带归档 / 逐项失败提示，避免本文件自己再维护一套分镜预览） -->
      <div class="split-preview">
        <div v-if="isGenerating" class="preview-loading">
          <a-spin size="large" />
          <p class="preview-loading-title">正在生成带货脚本…</p>
          <p class="preview-loading-sub">含分镜表与文案，约 10-20s，请勿关闭页面</p>
        </div>
        <AIGCMediaResult
          v-else-if="latestResult"
          :data="latestResult"
          @close="latestResult = null"
        />
        <a-empty
          v-else
          description="暂无脚本结果，点底部「生成带货脚本」"
          :image-style="{ height: '48px' }"
        />
      </div>
    </div>

    <!-- ====== 对话模式 = 平铺表单 ====== -->
    <div v-else class="form-body">
      <!-- ① 载入产品 -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">📦</span>
          <span class="title-text">载入产品</span>
          <span class="title-hint">从产品库选择已有商品</span>
        </div>
        <div class="product-load-row">
          <ProductPickerButton
            :model-value="pickedProduct"
            :show-label="false"
            @select="onProductSelect"
          />
          <span v-if="pickedProduct" class="product-loaded-hint">
            ✓ {{ pickedProduct.title?.slice(0, 18) }}{{ pickedProduct.title?.length > 18 ? '…' : '' }}
          </span>
        </div>
        <div v-if="pickedProduct" class="product-info-line" :title="`卖点：${autoFilledSellingPoints || '—'}\n痛点：${autoFilledPainPoints || '—'}`">
          <span class="pi-label">卖点</span>
          <span class="pi-text">{{ autoFilledSellingPoints || '—' }}</span>
          <span class="pi-label">痛点</span>
          <span class="pi-text">{{ autoFilledPainPoints || '—' }}</span>
        </div>
      </section>

      <!-- ② 视频基本信息 -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">🎞️</span>
          <span class="title-text">视频基本信息</span>
        </div>
        <div class="form-row">
          <div class="form-group flex-1">
            <label>目标平台</label>
            <a-select v-model:value="form.platform" size="small" style="width: 100%">
              <a-select-option v-for="p in platforms" :key="p.id" :value="p.id">{{ p.icon }} {{ p.name }}</a-select-option>
            </a-select>
          </div>
          <div class="form-group flex-1">
            <label>视频时长</label>
            <a-select v-model:value="form.duration" size="small" style="width: 100%">
              <a-select-option value="15s">15 秒（快节奏）</a-select-option>
              <a-select-option value="30s">30 秒（标准）</a-select-option>
              <a-select-option value="45s">45 秒（详细）</a-select-option>
              <a-select-option value="60s">60 秒（完整版）</a-select-option>
            </a-select>
          </div>
        </div>
        <div class="form-group">
          <label>脚本风格</label>
          <a-radio-group v-model:value="form.videoStyle" size="small">
            <a-radio-button value="problem-solution">痛点驱动</a-radio-button>
            <a-radio-button value="product-showcase">产品展示</a-radio-button>
            <a-radio-button value="story-telling">故事化</a-radio-button>
            <a-radio-button value="comparison">对比测评</a-radio-button>
          </a-radio-group>
        </div>
      </section>

      <!-- ③ 脚本技巧 -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">✨</span>
          <span class="title-text">脚本技巧</span>
          <span class="title-hint">可多选</span>
        </div>
        <div class="checkbox-row">
          <a-checkbox
            v-for="opt in scriptOptions"
            :key="opt.value"
            :checked="form.scriptOptions.includes(opt.value)"
            @change="toggleScriptOption(opt.value)"
          >
            <span class="opt-label">{{ opt.label }}</span>
            <span class="opt-desc">{{ opt.desc }}</span>
          </a-checkbox>
        </div>
      </section>

      <!-- ④ 分镜表（镜头列表：紧凑行，点击展开编辑，非「折叠分组」） -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">🎬</span>
          <span class="title-text">分镜表</span>
          <span class="title-hint">{{ form.scenes.length }} 个镜头</span>
          <a-space :size="4" class="title-actions">
            <a-button size="small" type="text" @click="toggleAllScenes">
              {{ allScenesExpanded ? '全部收起' : '全部展开' }}
            </a-button>
            <a-button size="small" type="text" @click="addScene"><PlusOutlined /></a-button>
            <a-button size="small" type="text" @click="resetToDefaultScenes"><ReloadOutlined /></a-button>
          </a-space>
        </div>
        <div class="scenes-list">
          <div v-for="(scene, idx) in form.scenes" :key="idx" class="scene-row" :class="{ expanded: isSceneExpanded(idx) }">
            <div class="scene-row-header" @click="toggleScene(idx)">
              <span class="scene-num-inline">镜头 {{ idx + 1 }}</span>
              <a-input-number
                :model-value="scene.duration"
                @update:value="(v: number) => updateScene(idx, 'duration', v)"
                :min="1" :max="30" size="small"
                style="width: 72px"
                addon-after="s"
                @click.stop
              />
              <span class="expand-toggle">{{ isSceneExpanded(idx) ? '收起 ▾' : '展开 ▸' }}</span>
              <a-button
                v-if="form.scenes.length > 1"
                size="small" type="text" danger
                @click.stop="removeScene(idx)"
              >删除</a-button>
            </div>
            <div v-show="isSceneExpanded(idx)" class="scene-body">
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
                  <label>运镜</label>
                  <a-select
                    :model-value="scene.cameraMovement"
                    @change="(v: string) => updateScene(idx, 'cameraMovement', v)"
                    size="small" style="width: 100%"
                  >
                    <a-select-option value="static">固定机位</a-select-option>
                    <a-select-option value="push-in">推近</a-select-option>
                    <a-select-option value="pull-out">拉远</a-select-option>
                    <a-select-option value="rotate">环绕旋转</a-select-option>
                    <a-select-option value="zoom-dolly">变焦推轨</a-select-option>
                    <a-select-option value="handheld">手持晃动</a-select-option>
                  </a-select>
                </div>
                <div class="form-group flex-1">
                  <label>景别</label>
                  <a-select
                    :model-value="scene.shotSize"
                    @change="(v: string) => updateScene(idx, 'shotSize', v)"
                    size="small" style="width: 100%"
                  >
                    <a-select-option value="extreme-closeup">大特写</a-select-option>
                    <a-select-option value="closeup">特写</a-select-option>
                    <a-select-option value="medium-shot">中景</a-select-option>
                    <a-select-option value="full-shot">全景</a-select-option>
                  </a-select>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ⑤ 首帧参考 -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">🖼️</span>
          <span class="title-text">首帧参考</span>
          <span class="title-hint">可选</span>
        </div>
        <p class="section-desc">从静态素材库选择已生成的图片作为镜头首帧；不选则由 AI 自动生成。</p>
        <div v-for="(scene, idx) in form.scenes" :key="idx" class="frame-row">
          <span class="frame-label">镜头 {{ idx + 1 }}</span>
          <a-input
            :model-value="scene.frameRef"
            @update:value="(v: string) => updateScene(idx, 'frameRef', v)"
            placeholder="输入素材库图片 URL 或留空由 AI 生成"
            size="small"
          />
          <a-button size="small" @click.stop="openAssetPicker(idx)">
            <FolderOpenOutlined /> 选素材
          </a-button>
        </div>
      </section>

      <!-- ⑥ 额外要求 -->
      <section class="cfg-section">
        <div class="section-title">
          <span class="title-icon">📝</span>
          <span class="title-text">额外要求</span>
          <span class="title-hint">可选</span>
        </div>
        <a-textarea
          v-model:value="form.extraScriptPrompt"
          :auto-size="{ minRows: 2, maxRows: 5 }"
          placeholder="如：开头 3 秒必须 hook 出痛点；结尾 CTA 引导点击购物车…"
          size="small"
        />
      </section>
    </div>

    <!-- 操作按钮：大屏/对话两态都在容器底部（flex column 第二项），不参与 split-form 滚动 -->
    <div class="action-bar">
      <a-button size="small" @click="handleReset"><ReloadOutlined /> 重置</a-button>
      <a-button type="primary" size="small" :loading="loading" @click="handleSubmit">
        <VideoCameraOutlined /> {{ latestResult ? '重新生成脚本' : '生成带货脚本' }}
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import { useAigcResultsStore } from '@/stores/aigcResults'
import {
  ReloadOutlined,
  VideoCameraOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import AIGCMediaResult from '@/components/ChatPanel/results/AIGCMediaResult.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// ====== 大屏/对话模式 ======
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ====== 最近结果（大屏预览数据源）======
// 结果存在全局 store 而非组件内 ref：TaskConfigPanel 用 v-else-if 挂载本组件，
// 切工具就会销毁重建 —— 存组件里必然出现「切走再切回，刚生成的就没了」。
// 读写都走 store，切工具只是换了个消费方，数据仍在（且是同一份对象引用）。
const AIGC_TOOL_ID = 'video-script-gen'
const aigcResults = useAigcResultsStore()
const latestResult = computed<any>({
  get: () => aigcResults.getResult(AIGC_TOOL_ID),
  set: (v: any) => (v ? aigcResults.setResult(AIGC_TOOL_ID, v) : aigcResults.clearResult(AIGC_TOOL_ID)),
})
// 生成中：由 orchestrator 的 aigc-generating 事件驱动（store 内统一监听，不随组件销毁）。
// 大屏模式下结果不进对话流，loading 就该在预览区转，而不是让对话区空转。
const isGenerating = computed<boolean>({
  get: () => aigcResults.isGenerating(AIGC_TOOL_ID),
  set: (v: boolean) => aigcResults.setGenerating(AIGC_TOOL_ID, v),
})

// 镜头展开状态（列表项交互，非折叠分组）
const sceneExpandedSet = ref<Set<number>>(new Set())
function isSceneExpanded(idx: number) { return sceneExpandedSet.value.has(idx) }
function toggleScene(idx: number) {
  const next = new Set(sceneExpandedSet.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  sceneExpandedSet.value = next
}
const allScenesExpanded = computed(() => sceneExpandedSet.value.size === form.scenes.length)
function toggleAllScenes() {
  if (allScenesExpanded.value) {
    sceneExpandedSet.value = new Set()
  } else {
    sceneExpandedSet.value = new Set(form.scenes.map((_, i) => i))
  }
}

const platforms = [
  { id: 'tiktok', name: 'TikTok', icon: '🎵' },
  { id: 'reels', name: 'Instagram Reels', icon: '📸' },
  { id: 'youtube-shorts', name: 'YouTube Shorts', icon: '▶️' },
  { id: 'amazon-post', name: 'Amazon Post', icon: '📦' },
]

const scriptOptions = [
  { value: 'hook-opening', label: '🔥 Hook 开头', desc: '前 3 秒抓眼球' },
  { value: 'pain-agitate', label: '😣 痛点放大', desc: '把痛点讲透' },
  { value: 'social-proof', label: '⭐ 社会证明', desc: '晒评价/销量' },
  { value: 'comparison', label: '⚖️ 对比测评', desc: 'vs 竞品/旧版' },
  { value: 'cta-strong', label: '📣 强 CTA 结尾', desc: '引导下单' },
  { value: 'subtitle-friendly', label: '📝 字幕友好', desc: '适配音/翻译' },
]

interface Scene {
  duration: number
  frameRef: string
  visual: string
  narration: string
  cameraMovement: string
  shotSize: string
  bgm: string
  subtitleStyle: string
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

const pickedProduct = ref<any>(null)
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

const onProductSelect = (product: any) => { pickedProduct.value = product }
watch(workingProduct, (product) => {
  if (product && !pickedProduct.value) pickedProduct.value = product
}, { immediate: true })

function toggleScriptOption(value: string) {
  const idx = form.scriptOptions.indexOf(value)
  if (idx >= 0) form.scriptOptions.splice(idx, 1)
  else form.scriptOptions.push(value)
}

function addScene() {
  form.scenes.push({ duration: 5, frameRef: '', visual: '', narration: '', cameraMovement: 'static', shotSize: 'medium-shot', bgm: 'upbeat', subtitleStyle: 'bold-bottom' })
}
function removeScene(idx: number) { form.scenes.splice(idx, 1) }
function resetToDefaultScenes() { form.scenes = JSON.parse(JSON.stringify(defaultScenes)) as Scene[] }
function updateScene(idx: number, field: keyof Scene, value: any) {
  ;(form.scenes[idx] as any)[field] = value
}

function openAssetPicker(sceneIdx: number) {
  message.info('素材库选择器开发中 — 可手动粘贴图片 URL')
}

// ====== 提交 ======
const handleSubmit = () => {
  if (!pickedProduct.value) { message.warning('请先载入产品'); return }
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
  height: 100%;
  min-height: 0;
}

/* ====== 大屏模式：左右分栏（左精简配置 + 右分镜预览） ======
   split-layout 是 flex 子项（flex:1 1 auto），容器外层 .action-bar 占第二项（flex:0 0 auto），
   操作栏始终在右栏底部、split-form 滚动不影响。 */
.video-script-config.data-mode .split-layout {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 1.3fr);
  gap: var(--space-12);
  overflow: hidden;
}
.video-script-config .split-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  overflow-y: auto;
  padding-right: var(--space-4);
  min-height: 0;
}
.video-script-config .split-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  overflow-y: auto;
  min-height: 0;
  border-left: 1px solid var(--border-base);
  padding-left: var(--space-10);
}
.picker-empty {
  padding: var(--space-10);
  background: var(--bg-sidebar);
  border-radius: var(--radius-6);
  color: var(--text-tertiary);
  font-size: var(--font-size-12);
  text-align: center;
}

/* ====== 表单容器 ====== */
.form-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  padding-bottom: var(--space-4);
}

/* ====== 统一 section 标题层级 ====== */
.cfg-section {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  padding: var(--space-10) var(--space-12);
  background: var(--bg-elevated);
}
.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-10);
  padding-bottom: var(--space-8);
  border-bottom: 1px dashed var(--border-base);
}
.title-icon { font-size: var(--font-size-14); flex-shrink: 0; }
.title-text {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}
.title-hint {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.title-actions { margin-left: auto; flex-shrink: 0; }

/* ====== 载入产品 ====== */
.product-load-row { display: flex; align-items: center; gap: var(--space-8); flex-wrap: wrap; }
.product-loaded-hint {
  font-size: var(--font-size-11);
  color: var(--success);
  background: var(--success-bg);
  padding: var(--space-2) var(--space-8);
  border-radius: var(--radius-4);
  border: 1px solid var(--success-border);
}
.product-info-line {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-top: var(--space-8);
  padding: var(--space-6) var(--space-10);
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  font-size: var(--font-size-11);
  min-width: 0;
}
.pi-label { flex-shrink: 0; color: var(--text-tertiary); }
.pi-text { flex: 1 1 0; min-width: 0; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pi-text + .pi-label { margin-left: var(--space-4); }

/* ====== 表单 ====== */
.form-group > label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  font-weight: 500;
}
.form-group { margin-bottom: var(--space-10); }
.form-row { display: flex; gap: var(--space-10); }
.flex-1 { flex: 1; min-width: 0; }
.section-desc { font-size: var(--font-size-11); color: var(--text-tertiary); margin: 0 0 var(--space-8); }

/* ====== 脚本技巧 ====== */
.checkbox-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-6);
}
.checkbox-row :deep(.ant-checkbox-wrapper) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: var(--space-6) var(--space-8);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  transition: all 0.2s;
  margin: 0 !important;
}
.checkbox-row :deep(.ant-checkbox-wrapper:hover) { border-color: var(--primary); }
.opt-label { font-size: var(--font-size-12); color: var(--text-primary); font-weight: 500; }
.opt-desc { font-size: var(--font-size-11); color: var(--text-tertiary); }

/* ====== 分镜表（镜头列表） ====== */
.scenes-list { display: flex; flex-direction: column; gap: var(--space-6); }
.scene-row {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  background: var(--bg-elevated);
  overflow: hidden;
  transition: all 0.2s;
}
.scene-row.expanded { border-color: var(--primary); }
.scene-row-header {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-10);
  background: var(--bg-sidebar);
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}
.scene-row-header:hover { background: var(--info-bg); }
.scene-row.expanded .scene-row-header { border-bottom: 1px dashed var(--border-base); }
.scene-num-inline {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--primary);
  background: var(--info-bg);
  padding: var(--space-2) var(--space-8);
  border-radius: var(--radius-4);
}
.expand-toggle {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-left: auto;
}
.scene-body { padding: var(--space-8) var(--space-10) var(--space-4); }

/* ====== 首帧参考 ====== */
.frame-row { display: flex; align-items: center; gap: var(--space-8); margin-bottom: var(--space-6); }
.frame-label { font-size: var(--font-size-12); color: var(--text-tertiary); width: 60px; flex-shrink: 0; }

/* ====== 操作栏 ====== */
.action-bar {
  flex: 0 0 auto;
  display: flex;
  gap: var(--space-10);
  margin-top: var(--space-10);
  padding-top: var(--space-10);
  border-top: 1px solid var(--border-base);
}
.action-bar :deep(.ant-btn) { flex: 1; }

/* ====== 大屏预览 ====== */
.preview-canvas {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  overflow-y: auto;
}
.canvas-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--border-base);
}
.canvas-title { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); }
.canvas-summary {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-10);
  line-height: 1.7;
}
.canvas-scenes {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-10);
}
.scene-card {
  position: relative;
  padding: var(--space-10);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.scene-num-badge {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-circle);
  background: var(--primary);
  color: #fff;
  font-size: var(--font-size-11);
  font-weight: 600;
}
.scene-meta-top { display: flex; gap: var(--space-4); flex-wrap: wrap; }
.scene-thumb, .scene-thumb-placeholder {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-6);
  object-fit: cover;
}
.scene-thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-sidebar);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.scene-visual { font-size: var(--font-size-12); color: var(--text-primary); margin: 0; }
.scene-narration {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  font-style: italic;
  margin: 0;
}

/* ====== 大屏预览区 loading（生成中）======
   AIGC 大屏模式下结果不进对话流，loading 归右栏预览区。 */
.preview-loading {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-10);
  padding: var(--space-40) var(--space-16);
  color: var(--text-secondary);
}
.preview-loading-title {
  margin: 0;
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.preview-loading-sub {
  margin: 0;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
</style>
