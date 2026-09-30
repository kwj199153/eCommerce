<template>
  <div class="video-generator-config" :class="{ 'data-mode': isDataMode }">
    <!-- ====== 内容区：对话模式单列平铺 / 大屏模式左右分栏（左完整表单 + 右视频预览） ======
         复用同一份表单，大屏不精简任何参数（此前 split-form 手工精简导致配置缺漏，已修复）。
         右侧预览仅在大屏模式渲染。 -->
    <div class="content" :class="{ 'data-layout': isDataMode }">
      <div class="form-body">
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
          <a-divider style="margin: 10px 0" />

          <!-- 工具栏：生成 / 导入 入口收成一行，纵向空间尽量留给脚本表 -->
          <div class="script-toolbar">
            <span class="section-title" style="margin: 0">
              分镜脚本<template v-if="form.storyboardScenes.length">（{{ form.storyboardScenes.length }} 镜）</template>
            </span>
            <div class="toolbar-actions">
              <a-button type="primary" size="small" :loading="storyboardLoading" @click="generateStoryboard">
                <RobotOutlined /> {{ form.storyboardScenes.length ? '重新生成' : 'AI 自动生成分镜表' }}
              </a-button>
              <a-tooltip v-if="videoScriptsStore.lastScript" title="复用「短视频带货脚本」最近一次结果">
                <a-button size="small" @click="importScript">
                  <ImportOutlined /> 导入带货脚本（{{ videoScriptsStore.sceneCount() }} 镜）
                </a-button>
              </a-tooltip>
            </div>
          </div>

          <!-- 分镜表：就地可编辑，形态对齐「短视频带货脚本」结果表 -->
          <a-table
            v-if="form.storyboardScenes.length"
            class="storyboard-table"
            :data-source="form.storyboardScenes"
            :columns="sceneColumns"
            size="small"
            :pagination="false"
            :scroll="{ x: 800 }"
            row-key="_uid"
          >
            <template #bodyCell="{ column, record, index }">
              <template v-if="column.key === 'idx'">
                <span class="scene-num">{{ index + 1 }}</span>
              </template>
              <template v-else-if="column.key === 'duration'">
                <a-input-number
                  v-model:value="record.duration"
                  :min="1" :max="15" size="small" style="width: 100%"
                  addon-after="s"
                />
              </template>
              <template v-else-if="column.key === 'desc'">
                <a-textarea
                  v-model:value="record.desc"
                  :auto-size="{ minRows: 1, maxRows: 3 }"
                  size="small" placeholder="画面描述"
                />
              </template>
              <template v-else-if="column.key === 'narration'">
                <a-textarea
                  v-model:value="record.narration"
                  :auto-size="{ minRows: 1, maxRows: 3 }"
                  size="small" placeholder="文案 / 旁白"
                />
              </template>
              <template v-else-if="column.key === 'source'">
                <a-select
                  :value="record.source"
                  size="small" style="width: 100%"
                  :options="SOURCE_OPTIONS"
                  @change="(v: any) => setSceneSource(index, v)"
                />
              </template>
              <template v-else-if="column.key === 'frame'">
                <div class="frame-pick">
                  <img
                    v-if="record.imageUrl"
                    :src="record.imageUrl"
                    class="frame-thumb"
                    title="点击更换首帧"
                    @error="onImgError"
                    @click="openSourcePicker('scene', index)"
                  />
                  <button
                    v-else
                    class="frame-folder-btn"
                    title="从素材库选取 / 本地上传"
                    @click="openSourcePicker('scene', index)"
                  ><FolderOpenOutlined /></button>
                </div>
              </template>
              <template v-else-if="column.key === 'camera'">
                <a-select
                  v-model:value="record.cameraMovement"
                  size="small" style="width: 100%"
                  :options="CAMERA_OPTIONS"
                />
              </template>
              <template v-else-if="column.key === 'ops'">
                <a-space :size="0">
                  <a-button
                    size="small" type="text" title="上移"
                    :disabled="index === 0"
                    @click="moveScene(index, -1)"
                  ><ArrowUpOutlined /></a-button>
                  <a-button
                    size="small" type="text" title="下移"
                    :disabled="index === form.storyboardScenes.length - 1"
                    @click="moveScene(index, 1)"
                  ><ArrowDownOutlined /></a-button>
                  <a-button
                    size="small" type="text" danger title="删除"
                    :disabled="form.storyboardScenes.length <= 1"
                    @click="removeScene(index)"
                  ><DeleteOutlined /></a-button>
                </a-space>
              </template>
            </template>
          </a-table>

          <!-- 空态：不放虚构默认数据（空状态优于虚构默认） -->
          <div v-else class="storyboard-empty">
            <span class="empty-icon">🎬</span>
            <span class="empty-text">
              由 AI 根据产品卖点自动生成 5-6 个镜头的分镜表；生成后可为每个镜头选择素材来源（产品素材库 / 手动上传）。
            </span>
            <span v-if="!videoScriptsStore.lastScript" class="empty-hint">
              💡 也可先到「短视频带货脚本」工具生成，再回来一键导入复用。
            </span>
          </div>

          <a-button size="small" type="dashed" block style="margin-top: 6px" @click="addScene">
            <PlusOutlined /> 添加镜头
          </a-button>

          <div v-if="form.storyboardScenes.length" class="table-foot-row">
            <a-button type="text" size="small" @click="resetStoryboard">清空分镜</a-button>
            <a-button
              v-if="videoScriptsStore.lastScript"
              type="text" size="small" danger
              @click="clearScriptImport"
            >清除脚本缓存</a-button>
          </div>
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
            <div class="form-group">
              <!-- 提示词增强：这段额外指令会直接拼进视频生成的要求里 -->
              <div class="label-row">
                <label>额外指令（可选）</label>
                <PromptEnhanceButton v-model="form.extraPrompt" context="aigc-video" size="sm" />
              </div>
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
      </div>

      <!-- ====== 大屏模式：右侧视频预览（仅 data 模式渲染）—— 复用 AIGCMediaResult：
           与对话流共用同一渲染真源，自带「归档到素材库」/ 逐项失败提示。 ====== -->
      <div v-if="isDataMode" class="split-preview">
        <div v-if="isGenerating" class="preview-loading">
          <a-spin size="large" />
          <p class="preview-loading-title">正在生成视频…</p>
          <p class="preview-loading-sub">逐镜头合成，耗时较长，请勿关闭页面</p>
        </div>
        <AIGCMediaResult
          v-else-if="latestResult"
          :data="latestResult"
          @close="latestResult = null"
        />
        <a-empty
          v-else
          description="暂无视频，点底部「开始生成视频」"
          :image-style="{ height: '48px' }"
        />
      </div>
    </div>

    <!-- 操作按钮：大屏/对话两态都在容器底部，不参与表单滚动 -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <VideoCameraAddOutlined /> {{ latestResult ? '重新生成视频' : '开始生成视频' }}
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
      :width="WINDOW_W.lg"
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
import { WINDOW_W } from '@/config/layout'
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import { useAigcResultsStore } from '@/stores/aigcResults'
import { useAssetLibraryStore } from '@/stores/assetLibrary'
import {
  ReloadOutlined,
  PictureOutlined,
  RobotOutlined,
  PlusOutlined,
  DeleteOutlined,
  VideoCameraAddOutlined,
  CloudUploadOutlined,
  ImportOutlined,
  FolderOpenOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useVideoScriptsStore } from '@/stores/videoScripts'
import AIGCMediaResult from '@/components/ChatPanel/results/AIGCMediaResult.vue'
import PromptEnhanceButton from '@/components/common/PromptEnhanceButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))
const videoScriptsStore = useVideoScriptsStore()

// ====== 大屏/对话模式：读 Workspace 注入的 reviewMode（与其他看板 Agent 一致） ======
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ====== 最近结果（大屏预览数据源）======
// 结果存在全局 store 而非组件内 ref：TaskConfigPanel 用 v-else-if 挂载本组件，
// 切工具就会销毁重建 —— 存组件里必然出现「切走再切回，刚生成的就没了」。
// 读写都走 store，切工具只是换了个消费方，数据仍在（且是同一份对象引用）。
const AIGC_TOOL_ID = 'ai-video-generator'
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

// ====== 类型 ======
interface Scene {
  _uid: string          // 行标识（表格 row-key；增删/排序时保证 Vue 复用正确，不会串行）
  duration: number
  desc: string          // 画面描述（AI 生成画面用 / 展示用）
  narration: string     // 旁白文案（AI 生成）
  source: 'library' | 'upload'
  imageUrl: string
  cameraMovement: string
  transition: string
}

const sourceLabel = (s: string) => ({ library: '素材库', upload: '上传' })[s] || s

// 分镜表列定义 —— 形态对齐「短视频带货脚本」结果表（竞品对话流的同一范式）
const sceneColumns = [
  { title: '镜', dataIndex: '_uid', key: 'idx', width: 40 },
  { title: '时长', dataIndex: 'duration', key: 'duration', width: 74 },
  { title: '画面描述', dataIndex: 'desc', key: 'desc', width: 170 },
  { title: '文案/旁白', dataIndex: 'narration', key: 'narration', width: 142 },
  { title: '素材来源', dataIndex: 'source', key: 'source', width: 100 },
  { title: '首帧', dataIndex: 'imageUrl', key: 'frame', width: 54 },
  { title: '运镜', dataIndex: 'cameraMovement', key: 'camera', width: 114 },
  { title: '操作', key: 'ops', width: 106 },
]

const CAMERA_OPTIONS = [
  { value: 'static', label: '固定机位' },
  { value: 'push-in-slow', label: '缓慢推近' },
  { value: 'pull-out-reveal', label: '拉远揭示' },
  { value: 'pan-left-right', label: '左右横扫' },
  { value: 'rotate-360', label: '环绕 360°' },
  { value: 'zoom-dolly', label: '变焦推轨' },
  { value: 'ken-burns', label: 'Ken Burns' },
]

const SOURCE_OPTIONS = [
  { value: 'library', label: '📁 产品素材库' },
  { value: 'upload', label: '📤 手动上传' },
]

// 镜头工厂：三处创建点（AI 生成 / 导入脚本 / 手动添加）共用，保证 _uid 唯一
let _sceneSeq = 0
function makeScene(partial: Partial<Omit<Scene, '_uid'>> = {}): Scene {
  return {
    _uid: `scene-${++_sceneSeq}`,
    duration: 4,
    desc: '',
    narration: '',
    source: 'library',
    imageUrl: '',
    cameraMovement: 'static',
    transition: 'fade',
    ...partial,
  }
}

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
      makeScene({ duration: 3, desc: '开篇钩子：产品特写 + 痛点字幕（前3秒抓住注意力）', cameraMovement: 'push-in-slow' }),
      makeScene({ duration: 4, desc: '产品外观 360° 展示（白底三视图氛围）', narration: `${name} 惊艳登场`, cameraMovement: 'rotate-360' }),
      makeScene({ duration: 4, desc: '核心卖点场景演示（自动运镜跟随产品）', narration: featLine ? `核心亮点：${featLine}` : '', cameraMovement: 'zoom-dolly', transition: 'slide' }),
      makeScene({ duration: 4, desc: '使用场景 / 生活方式画面', narration: '怎么用都顺手', cameraMovement: 'pan-left-right', transition: 'slide' }),
      makeScene({ duration: 3, desc: '细节/材质特写（Ken Burns 缩放营造质感）', cameraMovement: 'ken-burns' }),
      makeScene({ duration: 3, desc: '结尾 CTA：价格 + 行动号召', narration: '限时优惠，快来下单！', cameraMovement: 'static' }),
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
  form.storyboardScenes.push(makeScene())
}
function removeScene(idx: number) { form.storyboardScenes.splice(idx, 1) }
function moveScene(idx: number, dir: -1 | 1) {
  const arr = form.storyboardScenes
  const target = idx + dir
  if (target < 0 || target >= arr.length) return
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
}
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
  form.storyboardScenes = script.storyboard.map((s) => makeScene({
    duration: s.duration || 3,
    desc: s.visual || '',
    narration: s.narration || '',
    cameraMovement: CAMERA_COMPAT[s.cameraMovement] || s.cameraMovement || 'static',
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
    'spu-main': 'SPU 主图', 'white-bg': '白底副图', scene: '场景',
    lifestyle: '生活方式', infographic: '信息图解', 'ad-main': '广告主图', other: '其他',
  }
  return map[type] || type
}
</script>

<style scoped>
.video-generator-config {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* ====== 内容区：对话单列 / 大屏左右分栏 ====== */
.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
/* 左栏（配置 + 分镜表）吃主要宽度：分镜表要 8 列才装得下（第 248 轮实测）。
   右栏只放视频结果，窄一点够用；窄屏由 minmax 保底不塌陷。 */
.content.data-layout {
  display: grid;
  grid-template-columns: minmax(380px, 2fr) minmax(240px, 1fr);
  gap: var(--space-12);
}

/* ====== 表单容器（唯一一份，两模式共用） ====== */
.form-body {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: var(--space-4);
  min-height: 0;
}

/* ====== 大屏右侧预览 ====== */
.split-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  overflow-y: auto;
  min-height: 0;
  border-left: 1px solid var(--border-base);
  padding-left: var(--space-10);
}
.canvas-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.canvas-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.canvas-video { border-radius: var(--radius-8); overflow: hidden; }
.video-player { width: 100%; max-height: 320px; background: #000; display: block; }
.video-placeholder {
  min-height: 200px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-8); color: var(--text-tertiary); font-size: 12px;
  background: var(--bg-elevated); border: 1px dashed var(--border-base); border-radius: var(--radius-8);
}
.canvas-frames { display: flex; flex-direction: column; gap: var(--space-8); }
.frames-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.frames-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: var(--space-8); }
.frame-item { border: 1px solid var(--border-base); border-radius: var(--radius-6); overflow: hidden; }
.frame-item img { width: 100%; aspect-ratio: 9/16; object-fit: cover; display: block; }
.frame-meta { padding: 4px 6px; display: flex; align-items: center; gap: 4px; }
.frame-desc { font-size: 10px; color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ★ 第 319 轮 · 真机探针实测补漏：原为写死 `#262626`。
   本会话早前的深色改造把它的**容器底**换成了 `var(--bg-elevated)` /
   `var(--bg-hover-light)`（见未提交 diff 里 `- background: #fff` → `+ var(--bg-elevated)`），
   却没动这里的字色 ⇒ 深色下 `#262626` 压在 `rgb(31,31,31)` 上 = **1.09:1**
   （实测：`div.section-title`「生成模式」「分镜脚本」「视频参数」「字幕 & 文字叠加」，
   4 条同时命中 P1 与 P2）。这就是判据里那条「**只改底会把写死的深字落在暗底 = 当场造新缺陷**」。
   ⇒ 成对改成 `--text-primary`：浅色 `--text-primary` 就是 `#262626`（逐字相同，浅色零变化），
     深色自动变 `rgba(255,255,255,.92)`。 */
.section-title { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-top: 4px; }
.section-head-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }

/* ===== 第一层：模式大卡片 ===== */
/* 模式卡片：图标与名称同行、说明单行省略 —— 高度压到 ~44px，把纵向空间留给脚本表 */
.mode-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.mode-card {
  display: grid; grid-template-columns: auto 1fr; align-items: center;
  column-gap: 6px; row-gap: 2px;
  padding: 6px 8px; border: 2px solid var(--border-base); border-radius: 8px;
  cursor: pointer; transition: all 0.2s; text-align: left;
  /* ★ 这一块的底色与字色必须**成对**改成主题变量：只把 #fff 换掉的话，
     写死的 #262626 深字会落在深色卡上 ⇒ 当场造出一个新的「看不见」。 */
  background: var(--bg-elevated);
}
.mode-card:hover { border-color: var(--info-border); box-shadow: 0 2px 8px rgba(24,144,255,0.08); }
.mode-card.active { border-color: var(--primary); background: var(--info-bg); }
.mode-icon { font-size: 15px; grid-row: 1; }
.mode-name { font-size: 12px; font-weight: 700; color: var(--text-primary); grid-row: 1; }
.mode-card small {
  grid-column: 1 / -1; font-size: 10px; color: var(--text-tertiary); line-height: 1.35;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* ===== 脚本工具栏（生成 / 导入 入口收成一行） ===== */
.script-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-8); flex-wrap: wrap; margin-bottom: var(--space-6);
}
.toolbar-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.toolbar-actions :deep(.ant-btn) { font-size: var(--font-size-11); }

/* ===== 分镜表（形态对齐「短视频带货脚本」结果表） ===== */
.storyboard-table :deep(.ant-table-cell) { vertical-align: middle; }
.storyboard-table :deep(.ant-input-number),
.storyboard-table :deep(.ant-input-number-group-wrapper) { width: 100%; }
.scene-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: var(--radius-circle);
  background: var(--purple); color: #fff;
  font-size: var(--font-size-11); font-weight: 600;
}
.frame-pick { display: flex; align-items: center; justify-content: center; }
.frame-thumb {
  width: 40px; height: 40px; object-fit: cover;
  border-radius: var(--radius-4); border: 1px solid var(--border-base);
  cursor: pointer; transition: opacity 0.15s;
}
.frame-thumb:hover { opacity: 0.75; }
.frame-folder-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; padding: 0; cursor: pointer;
  color: var(--text-tertiary); font-size: 18px;
  background: var(--bg-hover-light, transparent);
  border: 1px dashed var(--border-base); border-radius: var(--radius-4);
}
.frame-folder-btn:hover { color: var(--primary); border-color: var(--primary); }

/* 空态：不放虚构默认数据 */
.storyboard-empty {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 18px 14px; text-align: center;
  background: var(--bg-hover-light, #fafafa);
  border: 1px dashed var(--border-base); border-radius: var(--radius-8);
}
.storyboard-empty .empty-icon { font-size: 22px; }
.storyboard-empty .empty-text { font-size: var(--font-size-12); color: var(--text-secondary); line-height: 1.7; }
.storyboard-empty .empty-hint { font-size: var(--font-size-11); color: var(--text-tertiary); }

.table-foot-row { display: flex; align-items: center; justify-content: flex-end; gap: 4px; margin-top: 2px; }
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
.form-group > label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 3px; font-weight: 500; }
/* 字段名 + 右侧「提示词增强」按钮同排（★ 别放进 <label>：button 是 labelable ⇒ 点标签会触发增强） */
.label-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.label-row > label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 0; font-weight: 500; }
.form-row { display: flex; gap: 8px; }
.flex-1 { flex: 1; }
.text-options-row { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.archive-section { margin-top: 8px; padding: 8px; background: var(--success-bg); border-radius: 6px; border: 1px solid var(--success-border); }
.action-bar { flex: 0 0 auto; display: flex; flex-direction: column; gap: 6px; margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--border-base); }

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
