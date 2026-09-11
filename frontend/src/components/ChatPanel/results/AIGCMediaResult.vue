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
      <a-alert type="success" show-icon style="margin-bottom: 10px"
        message="素材生成完成，确认无误后可手动归档到营销素材库" />
      <div class="asset-preview-grid">
        <div v-for="(a, i) in result.generated_assets || []" :key="a.id || i" class="asset-preview-item">
          <img :src="a.url" :alt="a.desc" loading="lazy" @error="onImgError" />
          <div class="asset-preview-meta">
            <span class="asset-type-chip">{{ typeLabel(a.type) }}</span>
            <span class="asset-desc">{{ a.desc }}</span>
          </div>
        </div>
      </div>
      <div class="result-footer">
        <a-button type="primary" :disabled="!archiveCandidates.length" @click="openArchive">
          <SaveOutlined /> 归档到素材库<template v-if="archivedCount">（已归档 {{ archivedCount }}）</template>
        </a-button>
        <span class="footer-hint">归档需手动确认，保存后可在「资料库 → 营销素材库」统一分组管理</span>
      </div>
    </template>

    <!-- ====== 短视频带货脚本结果 ====== -->
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
        :scroll="{ x: 640 }"
        row-key="scene"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'scene'">
            <span class="scene-num">{{ record.scene }}</span>
          </template>
          <template v-else-if="column.key === 'frame'">
            <img v-if="record.frameRef" :src="record.frameRef" class="frame-thumb" @error="onImgError" />
            <span v-else class="text-muted">待生成</span>
          </template>
          <template v-else-if="column.key === 'camera'">
            <span class="camera-chip">{{ cameraLabel(record.cameraMovement) }}</span>
            <span class="shot-size">{{ shotSizeLabel(record.shotSize) }}</span>
          </template>
        </template>
      </a-table>

      <div class="result-footer">
        <span class="footer-hint">脚本确认后可切换「AI 短视频生成」，按首帧+运镜逐镜头生成视频</span>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { CloseOutlined, SaveOutlined, PlayCircleFilled } from '@ant-design/icons-vue'
import AssetArchiveModal from '@/components/KnowledgeBase/AssetArchiveModal.vue'
import type { ArchiveCandidate } from '@/components/KnowledgeBase/AssetArchiveModal.vue'

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
  { title: '镜', dataIndex: 'scene', key: 'scene', width: 44 },
  { title: '时长', dataIndex: 'duration', key: 'duration', width: 56, customRender: ({ text }: any) => `${text}s` },
  { title: '画面描述', dataIndex: 'visual', key: 'visual', width: 240, ellipsis: true },
  { title: '文案/旁白', dataIndex: 'narration', key: 'narration', width: 180, ellipsis: true },
  { title: '首帧', dataIndex: 'frameRef', key: 'frame', width: 64 },
  { title: '运镜', dataIndex: 'cameraMovement', key: 'camera', width: 130 },
  { title: '字幕', dataIndex: 'subtitleStyle', key: 'subtitle', width: 90 },
]

// ====== 归档候选构建 ======

const archiveCandidates = computed<ArchiveCandidate[]>(() => {
  const type = result.value.type
  if (type === 'static_asset_gen') {
    return (result.value.generated_assets || []).map((a: any) => ({
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
// 已归档素材 url（防重复归档）
const archivedUrls = ref<string[]>([])
const archivedCount = computed(() => archivedUrls.value.length)

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
  'three-view': '三视图', detail: '细节', scene: '场景',
  lifestyle: '生活方式', character: '人物', 'storyboard-frame': '分镜首帧',
  'white-bg': '白底图',
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

const CAMERA_LABELS: Record<string, string> = {
  static: '固定机位', rotate: '环绕旋转', 'rotate-360': '360°旋转',
  'zoom-dolly': '推拉变焦', 'push-in-slow': '缓慢推近', 'pull-out-reveal': '拉远揭示',
  'ken-burns': 'Ken Burns', 'pan-left-right': '横摇', 'camera-shake': '手持抖动',
  orbit: '轨道环绕', 'top-down': '俯拍',
}
function cameraLabel(c: string): string {
  return CAMERA_LABELS[c] || c
}

const SHOT_LABELS: Record<string, string> = {
  closeup: '特写', 'extreme-closeup': '大特写', 'medium-shot': '中景',
  'full-shot': '全景', 'wide-angle': '广角',
}
function shotSizeLabel(s: string): string {
  return s ? SHOT_LABELS[s] || s : ''
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
  gap: 10px;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-icon {
  font-size: 16px;
}

.result-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 素材预览网格 */
.asset-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}

.asset-preview-item {
  border: 1px solid var(--border-base);
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.asset-preview-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}

.asset-preview-meta {
  padding: 4px 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.asset-type-chip {
  font-size: 10px;
  background: var(--info-bg);
  color: var(--primary);
  border-radius: 4px;
  padding: 1px 5px;
  flex-shrink: 0;
}

.asset-desc {
  font-size: 10px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-base);
}

.footer-hint {
  font-size: 11px;
  color: var(--text-disabled);
}

/* 脚本 */
.script-overview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.script-summary {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-hover-light);
  border-radius: 6px;
  padding: 8px 10px;
  line-height: 1.7;
}

.scene-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #722ed1;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.camera-chip {
  font-size: 11px;
  color: var(--purple);
  background: var(--purple-bg);
  padding: 1px 6px;
  border-radius: 4px;
  margin-right: 4px;
}

.shot-size {
  font-size: 10px;
  color: var(--text-tertiary);
}

.frame-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--border-base);
}

.text-muted {
  color: var(--text-disabled);
}

/* 视频结果 */
.video-result {
  display: flex;
}

.video-main {
  display: flex;
  gap: 12px;
  width: 100%;
}

.video-player {
  position: relative;
  width: 200px;
  flex-shrink: 0;
  border-radius: 8px;
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
  font-size: 36px;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.video-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-primary);
}

.meta-label {
  width: 56px;
  color: var(--text-tertiary);
  font-size: 11px;
  flex-shrink: 0;
}

.frames-section {
  margin-top: 4px;
}

.frames-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
</style>
