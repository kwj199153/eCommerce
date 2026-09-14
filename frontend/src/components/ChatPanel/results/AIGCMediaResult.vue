<template>
  <div class="aigc-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">{{ headerIcon }}</span>
        <span class="result-title">{{ headerTitle }}</span>
        <a-tag color="blue">{{ result.product_name || '-' }}</a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- ====== 静态素材生成结果 ====== -->
    <template v-if="result.type === 'static_asset_gen'">
      <!-- 整批失败：绝不出「成功」提示，把后端给的原因原样透出 -->
      <a-alert
        v-if="result.degraded"
        type="error"
        show-icon
        style="margin-bottom: var(--space-10)"
        message="素材生成失败"
        :description="result.degraded_reason || '出图服务未返回任何图片'"
      />
      <template v-else>
        <a-alert
          type="success"
          show-icon
          style="margin-bottom: var(--space-10)"
          :message="`素材生成完成，共 ${(result.generated_assets || []).length} 张。确认无误后可手动归档到营销素材库`"
        />
        <!-- 部分失败：整批仍算成功，但必须逐项说明哪一类没出来 -->
        <a-alert
          v-if="result.failed?.length"
          type="warning"
          show-icon
          style="margin-bottom: var(--space-10)"
          :message="`其中 ${result.failed.length} 类素材未生成成功`"
        >
          <template #description>
            <div v-for="(f, i) in result.failed" :key="i">
              {{ f.type_label || f.type }}：{{ f.error }}
            </div>
          </template>
        </a-alert>
        <!-- 生成方式说明（当前为文生图，原图未参与）—— 不假装用了原图 -->
        <a-alert
          v-if="result.notice"
          type="info"
          show-icon
          style="margin-bottom: var(--space-10)"
          :message="result.notice"
        />
      </template>

      <div v-if="(result.generated_assets || []).length" class="asset-preview-grid">
        <div
          v-for="(a, i) in result.generated_assets || []"
          :key="a.id || i"
          class="asset-preview-item pickable"
          :class="{ selected: isSelected(a), archived: isArchived(a) }"
          @click="toggleSelect(a)"
        >
          <img :src="a.url" :alt="a.desc" loading="lazy" @error="onImgError" />
          <!-- 左上角勾选：只有勾中的才会进归档 -->
          <span class="asset-pick" :class="{ on: isSelected(a), done: isArchived(a) }">
            <CheckOutlined v-if="isSelected(a)" />
            <CheckCircleFilled v-else-if="isArchived(a)" />
          </span>
          <div class="asset-preview-meta">
            <span class="asset-type-chip">{{ typeLabel(a.type) }}</span>
            <span class="asset-desc">{{ a.desc }}</span>
          </div>
        </div>
      </div>
      <!-- 空态：不放任何占位图（空状态优于虚构默认） -->
      <div v-else-if="!result.degraded" class="asset-empty">
        <span class="asset-empty-icon">🖼️</span>
        <span>本次未生成任何素材，可调整素材类型后重试</span>
      </div>
      <div class="result-footer">
        <a-button type="primary" :disabled="!selectedAssets.length" @click="openArchive">
          <SaveOutlined /> 归档到素材库<template v-if="selectedAssets.length">（已选 {{ selectedAssets.length }} 张）</template>
          <template v-else-if="archivedCount">（已归档 {{ archivedCount }}）</template>
        </a-button>
        <a-button
          v-if="(result.generated_assets || []).length"
          type="link"
          size="small"
          @click="toggleAll"
        >{{ allSelected ? '取消全选' : '全选' }}</a-button>
        <span class="footer-hint">勾选要保留的素材后归档，保存后可在「资料库 → 营销素材库」统一分组管理</span>
      </div>
    </template>

    <!-- ====== 短视频带货脚本结果（分镜表就地可编辑） ======
         表格改的是 props.data.storyboard 那份**共享对象**：对话区结果卡与大屏预览
         读的是同一个引用，改一处两端自动同步，无需额外同步逻辑。 -->
    <template v-else-if="result.type === 'video_script_gen'">
      <div class="script-overview">
        <a-space :size="12" wrap>
          <a-tag color="cyan">{{ result.platform_label }}</a-tag>
          <a-tag>{{ styleLabel(result.video_style) }}</a-tag>
          <a-tag color="blue">总时长 {{ result.total_duration }}s</a-tag>
          <a-tag>{{ (result.storyboard || []).length }} 个镜头</a-tag>
        </a-space>
        <div class="script-summary" v-html="renderMarkdown(result.script_summary)"></div>
      </div>

      <a-table
        :data-source="result.storyboard || []"
        :columns="storyboardColumns"
        size="small"
        :pagination="false"
        :scroll="{ x: 980 }"
        row-key="scene"
      >
        <template #bodyCell="{ column, record, index }">
          <template v-if="column.key === 'scene'">
            <span class="scene-num">{{ record.scene }}</span>
          </template>
          <template v-else-if="column.key === 'duration'">
            <a-input-number
              v-model:value="record.duration"
              :min="1" :max="60" size="small" style="width: 100%"
              addon-after="s"
              @change="touchScript"
            />
          </template>
          <template v-else-if="column.key === 'visual'">
            <a-textarea
              v-model:value="record.visual"
              :auto-size="{ minRows: 1, maxRows: 3 }"
              size="small" placeholder="画面描述"
              @change="touchScript"
            />
          </template>
          <template v-else-if="column.key === 'narration'">
            <a-textarea
              v-model:value="record.narration"
              :auto-size="{ minRows: 1, maxRows: 3 }"
              size="small" placeholder="文案 / 旁白"
              @change="touchScript"
            />
          </template>
          <template v-else-if="column.key === 'frame'">
            <!-- 有图：显示缩略图，点图可换；无图：文件夹图标，点击选/传 -->
            <div class="frame-pick">
              <img
                v-if="record.frameRef"
                :src="record.frameRef"
                class="frame-thumb"
                title="点击更换首帧"
                @error="onImgError"
                @click="openFramePicker(index)"
              />
              <button v-else class="frame-folder-btn" title="从素材库选取 / 上传图片" @click="openFramePicker(index)">
                <FolderOpenOutlined />
              </button>
            </div>
          </template>
          <template v-else-if="column.key === 'camera'">
            <a-select
              v-model:value="record.cameraMovement"
              size="small" style="width: 100%"
              :options="CAMERA_OPTIONS"
              @change="touchScript"
            />
          </template>
          <template v-else-if="column.key === 'shot'">
            <a-select
              v-model:value="record.shotSize"
              size="small" style="width: 100%"
              :options="SHOT_OPTIONS"
              allow-clear
              @change="touchScript"
            />
          </template>
          <template v-else-if="column.key === 'subtitle'">
            <a-select
              v-model:value="record.subtitleStyle"
              size="small" style="width: 100%"
              :options="SUBTITLE_OPTIONS"
              @change="touchScript"
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
                :disabled="index === (result.storyboard || []).length - 1"
                @click="moveScene(index, 1)"
              ><ArrowDownOutlined /></a-button>
              <a-button
                size="small" type="text" danger title="删除"
                :disabled="(result.storyboard || []).length <= 1"
                @click="removeScene(index)"
              ><DeleteOutlined /></a-button>
            </a-space>
          </template>
        </template>
      </a-table>

      <a-button size="small" type="dashed" block @click="addScene">
        <PlusOutlined /> 添加镜头
      </a-button>

      <div class="result-footer">
        <span class="footer-hint">表格可直接编辑：改动即时同步「对话区 / 大屏」两处，并写回脚本供「AI 短视频生成 · 分镜脚本专业模式」导入；首帧可点文件夹图标从素材库选取或本地上传</span>
      </div>
    </template>

    <!-- ====== AI 短视频生成结果 ====== -->
    <template v-else-if="result.type === 'ai_video_generator'">
      <div class="video-result">
        <div class="video-main">
          <div class="video-player">
            <img :src="result.thumbnail_url || fallbackThumb" alt="视频封面" @error="onImgError" />
            <span class="play-badge"><PlayCircleFilled /></span>
          </div>
          <div class="video-meta">
            <div class="meta-row">
              <span class="meta-label">模式</span>
              <span>{{ modeLabel }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">时长</span>
              <span>{{ result.metadata?.duration }}s</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">分辨率</span>
              <span>{{ result.metadata?.resolution }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">格式</span>
              <span>{{ result.metadata?.format }} · {{ result.metadata?.fps }}fps</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">镜头</span>
              <span>{{ result.clip_count }} 个</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="(result.preview_frames || []).length" class="frames-section">
        <div class="frames-title">关键帧预览</div>
        <div class="asset-preview-grid">
          <div v-for="(f, i) in result.preview_frames" :key="i" class="asset-preview-item frame-item">
            <img :src="f.url" :alt="f.desc" loading="lazy" @error="onImgError" />
            <div class="asset-preview-meta">
              <span class="asset-type-chip">{{ f.timestamp }}</span>
              <span class="asset-desc">{{ f.desc }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="result-footer">
        <a-button type="primary" @click="openArchive">
          <SaveOutlined /> 归档到素材库<template v-if="archivedCount">（已归档 {{ archivedCount }}）</template>
        </a-button>
        <span class="footer-hint">确认后视频与关键帧可保存到营销素材库并绑定产品</span>
      </div>
    </template>

    <!-- ===== 通用归档确认弹窗 ===== -->
    <AssetArchiveModal
      v-model:open="archiveVisible"
      :candidates="archiveCandidates"
      :locked-product-name="result.product_name"
      :archived-urls="archivedUrls"
      @archived="handleArchived"
    />

    <!-- ===== 分镜首帧选图抽屉（素材库选取 / 本地上传） ===== -->
    <a-drawer
      v-model:open="framePickerVisible"
      :title="framePickerTitle"
      placement="right"
      :width="520"
      :closable="true"
    >
      <a-tabs v-model:active-key="framePickerTab" size="small">
        <a-tab-pane key="library" tab="📁 产品素材库">
          <div v-if="frameLibraryAssets.length" class="frame-picker-grid">
            <div
              v-for="asset in frameLibraryAssets"
              :key="asset.id"
              class="frame-picker-item"
              :title="asset.name"
              @click="pickFrameFromLibrary(asset)"
            >
              <img :src="asset.url" :alt="asset.name" loading="lazy" @error="onImgError" />
              <span class="frame-picker-label">{{ asset.name }}</span>
            </div>
          </div>
          <a-empty v-else description="素材库暂无图片，可切到「本地上传」" :image-style="{ height: '40px' }" />
        </a-tab-pane>

        <a-tab-pane key="upload" tab="📤 本地上传">
          <div class="frame-upload-drop" @click="frameFileRef?.click()">
            <input
              ref="frameFileRef"
              type="file"
              accept="image/*"
              style="display: none"
              @change="handleFrameFileChange"
            />
            <CloudUploadOutlined class="frame-upload-icon" />
            <p class="frame-upload-title">点击选择本地图片</p>
            <p class="frame-upload-sub">JPG / PNG / WebP，≤20MB</p>
          </div>
          <div v-if="frameUploadPreview" class="frame-upload-preview">
            <img :src="frameUploadPreview" alt="" />
            <a-space :size="8">
              <a-button type="primary" size="small" @click="confirmFrameUpload">使用此图</a-button>
              <a-button size="small" @click="frameUploadPreview = ''">重选</a-button>
            </a-space>
          </div>
        </a-tab-pane>
      </a-tabs>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  CloseOutlined, SaveOutlined, PlayCircleFilled, CheckOutlined, CheckCircleFilled,
  ArrowUpOutlined, ArrowDownOutlined, DeleteOutlined, PlusOutlined,
  FolderOpenOutlined, CloudUploadOutlined,
} from '@ant-design/icons-vue'
import AssetArchiveModal from '@/components/KnowledgeBase/AssetArchiveModal.vue'
import type { ArchiveCandidate } from '@/components/KnowledgeBase/AssetArchiveModal.vue'
import { useVideoScriptsStore } from '@/stores/videoScripts'
import { useAssetLibraryStore } from '@/stores/assetLibrary'

const props = defineProps<{
  data: any
}>()

defineEmits<{
  (e: 'close'): void
}>()

const result = computed(() => props.data || {})

const fallbackThumb = 'https://picsum.photos/seed/aigc-video-thumb/480/270'

const headerMeta: Record<string, { icon: string; title: string }> = {
  static_asset_gen: { icon: '🎨', title: '静态素材生成结果' },
  video_script_gen: { icon: '🎬', title: '短视频带货脚本' },
  ai_video_generator: { icon: '🎥', title: 'AI 短视频生成结果' },
}

const headerIcon = computed(() => headerMeta[result.value.type]?.icon || '🛠️')
const headerTitle = computed(() => headerMeta[result.value.type]?.title || '工具结果')

const storyboardColumns = [
  { title: '镜', dataIndex: 'scene', key: 'scene', width: 40 },
  { title: '时长', dataIndex: 'duration', key: 'duration', width: 86 },
  { title: '画面描述', dataIndex: 'visual', key: 'visual', width: 200 },
  { title: '文案/旁白', dataIndex: 'narration', key: 'narration', width: 170 },
  { title: '首帧', dataIndex: 'frameRef', key: 'frame', width: 60 },
  { title: '运镜', dataIndex: 'cameraMovement', key: 'camera', width: 120 },
  { title: '景别', dataIndex: 'shotSize', key: 'shot', width: 100 },
  { title: '字幕', dataIndex: 'subtitleStyle', key: 'subtitle', width: 100 },
  { title: '操作', key: 'ops', width: 92 },
]

// 运镜 / 景别 / 字幕 下拉选项 —— 覆盖后端与 mock 会产出的全部取值
const CAMERA_OPTIONS = [
  { value: 'static', label: '固定机位' },
  { value: 'push-in', label: '推近' },
  { value: 'push-in-slow', label: '缓慢推近' },
  { value: 'pull-out', label: '拉远' },
  { value: 'pull-out-reveal', label: '拉远揭示' },
  { value: 'rotate', label: '环绕旋转' },
  { value: 'rotate-360', label: '360° 旋转' },
  { value: 'zoom-dolly', label: '推拉变焦' },
  { value: 'ken-burns', label: 'Ken Burns' },
  { value: 'pan-left-right', label: '横摇' },
  { value: 'handheld', label: '手持晃动' },
  { value: 'camera-shake', label: '手持抖动' },
  { value: 'orbit', label: '轨道环绕' },
  { value: 'top-down', label: '俯拍' },
]
const SHOT_OPTIONS = [
  { value: 'extreme-closeup', label: '大特写' },
  { value: 'closeup', label: '特写' },
  { value: 'medium-shot', label: '中景' },
  { value: 'full-shot', label: '全景' },
  { value: 'wide-angle', label: '广角' },
]
const SUBTITLE_OPTIONS = [
  { value: 'bold-bottom', label: '底部加粗' },
  { value: 'highlight', label: '高亮' },
  { value: 'typewriter', label: '打字机' },
  { value: 'none', label: '无' },
]

// ====== 素材勾选（默认不勾：只有主动选中的才进归档） ======

const selectedUrls = ref<string[]>([])

// 换一批结果就清空勾选，避免上一批的选择串到下一批
watch(
  () => result.value.generated_assets,
  () => { selectedUrls.value = [] },
)

// 已归档素材 url（防重复归档）
const archivedUrls = ref<string[]>([])

function isArchived(a: any): boolean {
  return archivedUrls.value.includes(a.url)
}
function isSelected(a: any): boolean {
  return selectedUrls.value.includes(a.url)
}
function toggleSelect(a: any) {
  if (isArchived(a)) return
  const i = selectedUrls.value.indexOf(a.url)
  if (i >= 0) selectedUrls.value.splice(i, 1)
  else selectedUrls.value.push(a.url)
}

const pickableAssets = computed<any[]>(() =>
  (result.value.generated_assets || []).filter((a: any) => !isArchived(a))
)
const allSelected = computed(() =>
  pickableAssets.value.length > 0 && pickableAssets.value.every((a: any) => isSelected(a))
)
function toggleAll() {
  selectedUrls.value = allSelected.value ? [] : pickableAssets.value.map((a: any) => a.url)
}

//: 勾选中的素材 → 归档候选的唯一来源
const selectedAssets = computed<any[]>(() =>
  (result.value.generated_assets || []).filter((a: any) => isSelected(a))
)

// ====== 归档候选构建 ======

const archiveCandidates = computed<ArchiveCandidate[]>(() => {
  const type = result.value.type
  if (type === 'static_asset_gen') {
    return selectedAssets.value.map((a: any) => ({
      url: a.url,
      name: `${result.value.product_name || '素材'} - ${a.desc || '生成图'}`,
      kind: 'image' as const,
      category: a.type || 'other',
      prompt: a.prompt_hint,
      source: 'aigc',
      tags: [typeLabel(a.type), 'AI生成'],
      productId: result.value.params?._sourceProduct?.id,
      productName: result.value.params?._sourceProduct?.title || result.value.product_name,
      asin: result.value.params?._sourceProduct?.asin,
    }))
  }
  if (type === 'ai_video_generator') {
    const list: ArchiveCandidate[] = []
    const prodName = result.value.product_name || '视频素材'
    // 视频本体
    list.push({
      url: result.value.thumbnail_url || fallbackThumb,
      name: `${prodName} - 短视频`,
      kind: 'video',
      category: 'video',
      videoUrl: result.value.video_url,
      source: 'video-gen',
      tags: ['AI短视频'],
      productId: result.value.params?._sourceProduct?.id,
      productName: result.value.params?._sourceProduct?.title || result.value.product_name,
      asin: result.value.params?._sourceProduct?.asin,
    })
    // 关键帧（可选归档为图片素材）
    ;(result.value.preview_frames || []).forEach((f: any, i: number) => {
      list.push({
        url: f.url,
        name: `${prodName} - 关键帧 ${i + 1}`,
        kind: 'image',
        category: 'storyboard-frame',
        source: 'video-gen',
        tags: ['视频帧'],
        productId: result.value.params?._sourceProduct?.id,
        productName: result.value.params?._sourceProduct?.title || result.value.product_name,
        asin: result.value.params?._sourceProduct?.asin,
      })
    })
    return list
  }
  return []
})

const archiveVisible = ref(false)
const archivedCount = computed(() => archivedUrls.value.length)

//: 归档完成后，把已归档的从勾选中摘掉（它们已变成「已归档」态）
watch(archivedUrls, () => {
  selectedUrls.value = selectedUrls.value.filter(u => !archivedUrls.value.includes(u))
})

function openArchive() {
  archiveVisible.value = true
}
function handleArchived(items: ArchiveCandidate[]) {
  // 收集本次确认归档的素材 url（防止重复归档）
  const newUrls = items.map(i => i.url).filter(u => !archivedUrls.value.includes(u))
  if (newUrls.length) {
    archivedUrls.value = [...archivedUrls.value, ...newUrls]
  }
  // 广播事件让素材库刷新
  window.dispatchEvent(new CustomEvent('asset-library-updated', { detail: { count: newUrls.length } }))
}

// ====== 标签映射 ======

const MODE_LABELS: Record<string, string> = {
  'single-image': '🖼️ 单图极速生成',
  'storyboard-pro': '🎬 分镜脚本专业模式',
}
const modeLabel = computed(() =>
  result.value.mode_label || MODE_LABELS[result.value.mode] || 'AI 短视频'
)

const TYPE_LABELS: Record<string, string> = {
  'spu-main': 'SPU 主图', 'white-bg': '白底副图', scene: '场景',
  lifestyle: '生活方式', infographic: '信息图解', 'ad-main': '广告主图',
}
function typeLabel(t: string): string {
  return TYPE_LABELS[t] || t
}

const STYLE_LABELS: Record<string, string> = {
  'problem-solution': '痛点驱动', 'product-showcase': '产品展示',
}
function styleLabel(s: string): string {
  return STYLE_LABELS[s] || s
}

// ====== 分镜表就地编辑 ======
// 改的就是 props.data.storyboard 那份共享对象 —— 对话区结果卡与大屏预览读的是同一个引用，
// 所以这里改一处，两端自动同步，无需额外的跨组件同步逻辑。
// 每次改动同时：① 重排镜号 / 重算累计起始秒 ② 刷新总时长 ③ 防抖写回脚本 store
//（供「AI 短视频生成 · 分镜脚本专业模式」导入最新版）。
let scriptSyncTimer: ReturnType<typeof setTimeout> | null = null
function touchScript() {
  const r = result.value
  if (!r || r.type !== 'video_script_gen') return
  const arr: any[] = r.storyboard || []
  let acc = 0
  arr.forEach((s: any, i: number) => {
    s.scene = i + 1
    s.time = acc
    acc += Number(s.duration) || 0
  })
  r.total_duration = acc
  if (scriptSyncTimer) clearTimeout(scriptSyncTimer)
  scriptSyncTimer = setTimeout(() => {
    try {
      useVideoScriptsStore().saveLastScript(r)
    } catch (e) {
      console.warn('分镜编辑写回脚本 store 失败：', e)
    }
  }, 350)
}
// ====== 分镜首帧选图（素材库选取 / 本地上传）======
// 复刻 VideoGeneratorConfig 的选图交互：抽屉内两个 Tab，选中即写回 record.frameRef。
// 写回走同一份 props.data.storyboard 引用 → 对话区与大屏两端自动同步。
const framePickerVisible = ref(false)
const framePickerTab = ref('library')
const frameTargetIndex = ref<number>(-1)
const frameFileRef = ref<HTMLInputElement | null>(null)
const frameUploadPreview = ref('')
const framePickerTitle = computed(() =>
  frameTargetIndex.value >= 0 ? `镜头 ${frameTargetIndex.value + 1} · 选择首帧` : '选择首帧'
)

/** 素材库里的图片素材（只取 image 且有 url 的） */
const assetLib = useAssetLibraryStore()
const frameLibraryAssets = computed(() => {
  try {
    return assetLib.items.filter((a) => a.kind === 'image' && a.url)
  } catch (e) {
    console.warn('[AIGC] 读取素材库失败：', e)
    return []
  }
})

function openFramePicker(index: number) {
  frameTargetIndex.value = index
  framePickerTab.value = 'library'
  frameUploadPreview.value = ''
  framePickerVisible.value = true
  // 结果卡可能在素材库页面从未打开过 → 进来到店时才拉，避免空列表误判「素材库没图」
  if (!assetLib.items.length && !assetLib.isLoading) {
    assetLib.fetchItems().catch((e: any) => console.warn('[AIGC] 素材库拉取失败：', e))
  }
}

/** 写入首帧并触发脚本重算 / 写回 store */
function applyFrame(url: string) {
  const arr: any[] = result.value?.storyboard || []
  const row = arr[frameTargetIndex.value]
  if (row) {
    row.frameRef = url
    touchScript()
  }
  framePickerVisible.value = false
}

function pickFrameFromLibrary(asset: { url: string }) {
  if (!asset?.url) return
  applyFrame(asset.url)
}

function handleFrameFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 20 * 1024 * 1024) {
    message.error('文件超过 20MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => { frameUploadPreview.value = reader.result as string }
  reader.readAsDataURL(file)
}

function confirmFrameUpload() {
  if (!frameUploadPreview.value) {
    message.warning('请先选择图片')
    return
  }
  applyFrame(frameUploadPreview.value)
}

function addScene() {
  const r = result.value
  if (!r || r.type !== 'video_script_gen') return
  if (!Array.isArray(r.storyboard)) r.storyboard = []
  r.storyboard.push({
    scene: r.storyboard.length + 1,
    time: 0,
    duration: 3,
    visual: '',
    narration: '',
    cameraMovement: 'static',
    shotSize: 'medium-shot',
    bgm: '',
    subtitleStyle: 'bold-bottom',
    frameRef: '',
  })
  touchScript()
}
function removeScene(index: number) {
  const arr: any[] = result.value?.storyboard || []
  if (arr.length <= 1) return
  arr.splice(index, 1)
  touchScript()
}
function moveScene(index: number, dir: -1 | 1) {
  const arr: any[] = result.value?.storyboard || []
  const j = index + dir
  if (j < 0 || j >= arr.length) return
  const [item] = arr.splice(index, 1)
  arr.splice(j, 0, item)
  touchScript()
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  // 简单 markdown 加粗转换
  return text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>')
}

function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.opacity = '0.3'
  el.style.background = 'var(--bg-hover-light)'
}
</script>

<style scoped>
.aigc-result {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}

.result-icon {
  font-size: var(--font-size-16);
}

.result-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
}

/* 素材预览网格 */
.asset-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--space-8);
}

.asset-preview-item {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  overflow: hidden;
  position: relative;
}

/* 可勾选的素材项：点一下切换选中 */
.asset-preview-item.pickable {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.asset-preview-item.pickable:hover {
  border-color: var(--border-strong);
}

.asset-preview-item.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.asset-preview-item.archived {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 左上角勾选圆点 */
.asset-pick {
  position: absolute;
  left: 4px;
  top: 4px;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-circle);
  border: 1.5px solid rgba(255, 255, 255, 0.95);
  background: rgba(0, 0, 0, 0.32);
  color: #fff;
  font-size: var(--font-size-11);
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  z-index: 2;
  transition: background 0.15s, border-color 0.15s;
}

.asset-pick.on {
  background: var(--primary);
  border-color: var(--primary);
}

.asset-pick.done {
  background: var(--success);
  border-color: var(--success);
}

.asset-preview-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}

.asset-preview-meta {
  padding: var(--space-4) var(--space-6);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.asset-type-chip {
  font-size: var(--font-size-10);
  background: var(--info-bg);
  color: var(--primary);
  border-radius: var(--radius-4);
  padding: var(--space-1) var(--space-5);
  flex-shrink: 0;
}

.asset-desc {
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 空态：不放占位图（空状态优于虚构默认） */
.asset-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  padding: var(--space-20) var(--space-10);
  color: var(--text-tertiary);
  font-size: var(--font-size-12);
  background: var(--bg-sidebar);
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-8);
}
.asset-empty-icon { font-size: var(--font-size-20); opacity: 0.6; line-height: 1; }

.result-footer {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  padding-top: var(--space-8);
  border-top: 1px dashed var(--border-base);
}

.footer-hint {
  font-size: var(--font-size-11);
  color: var(--text-disabled);
}

/* 脚本 */
.script-overview {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.script-summary {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-8) var(--space-10);
  line-height: 1.7;
}

/* 分镜表就地编辑：单元格内控件铺满宽度、纵向居中（addon 后置会包一层 group-wrapper） */
.aigc-result :deep(.ant-table-cell) { vertical-align: middle; }
.aigc-result :deep(.ant-input-number),
.aigc-result :deep(.ant-input-number-group-wrapper) { width: 100%; }

.scene-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-circle);
  background: var(--purple);
  color: #fff;
  font-size: var(--font-size-11);
  font-weight: 600;
}

.camera-chip {
  font-size: var(--font-size-11);
  color: var(--purple);
  background: var(--purple-bg);
  padding: var(--space-1) var(--space-6);
  border-radius: var(--radius-4);
  margin-right: var(--space-4);
}

.shot-size {
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
}

.frame-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: var(--radius-4);
  border: 1px solid var(--border-base);
}

/* 首帧列：文件夹图标占位（点击从素材库选取 / 本地上传） */
.frame-pick {
  display: flex;
  align-items: center;
  justify-content: center;
}
.frame-pick .frame-thumb {
  cursor: pointer;
  transition: opacity 0.15s;
}
.frame-pick .frame-thumb:hover { opacity: 0.75; }
.frame-folder-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  cursor: pointer;
  color: var(--text-tertiary);
  font-size: 18px;
  background: var(--bg-hover-light, transparent);
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-4);
  transition: all 0.15s;
}
.frame-folder-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}
.frame-folder-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

/* 首帧选图抽屉 */
.frame-picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: var(--space-10);
}
.frame-picker-item {
  position: relative;
  cursor: pointer;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  overflow: hidden;
  background: var(--bg-elevated);
  transition: border-color 0.15s;
}
.frame-picker-item:hover { border-color: var(--primary); }
.frame-picker-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}
.frame-picker-label {
  display: block;
  padding: var(--space-4) var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frame-upload-drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-24) var(--space-12);
  cursor: pointer;
  border: 1px dashed var(--border-secondary);
  border-radius: var(--radius-8);
}
.frame-upload-icon { font-size: 30px; color: var(--primary); }
.frame-upload-title { margin: 0; font-size: var(--font-size-12); color: var(--text-primary); }
.frame-upload-sub { margin: 0; font-size: var(--font-size-11); color: var(--text-tertiary); }
.frame-upload-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-10);
  margin-top: var(--space-12);
}
.frame-upload-preview img {
  max-width: 100%;
  max-height: 240px;
  object-fit: contain;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
}

/* 视频结果 */
.video-result {
  display: flex;
}

.video-main {
  display: flex;
  gap: var(--space-12);
  width: 100%;
}

.video-player {
  position: relative;
  width: 200px;
  flex-shrink: 0;
  border-radius: var(--radius-8);
  overflow: hidden;
  border: 1px solid var(--border-base);
}

.video-player img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  display: block;
}

.play-badge {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  font-size: var(--font-size-36);
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.video-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  font-size: var(--font-size-12);
  color: var(--text-primary);
}

.meta-label {
  width: 56px;
  color: var(--text-tertiary);
  font-size: var(--font-size-11);
  flex-shrink: 0;
}

.frames-section {
  margin-top: var(--space-4);
}

.frames-title {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-8);
}
</style>
