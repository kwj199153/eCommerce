<template>
  <div class="static-asset-config" :class="{ 'data-mode': isDataMode }">
    <!-- ====== 大屏模式 = 左右分栏：左表单 + 右预览 ======
         触发条件：Workspace 顶栏 mode-switch 切到「大屏模式」（reviewMode==='data'）。
         表单唯一一份（content.data-layout），大屏下 grid 两列 + 右侧预览，对话下单列。
         CSS grid: 左 5fr（表单，可滚动）+ 右 7fr（预览，不可滚动），总宽约 528。 -->
    <div class="content" :class="{ 'data-layout': isDataMode }">
      <!-- ====== 唯一一份表单（对话平铺 / 大屏左列共用） ====== -->
      <div class="form-body">
        <!-- ① 载入产品：2 选 1（产品库主图 / 上传原图），共用一张预览图 -->
        <section class="cfg-section">
          <div class="section-title">
            <span class="title-icon">📦</span>
            <span class="title-text">载入产品</span>
            <span class="title-hint">从产品库选已有商品 或 上传原图给 AI</span>
            <ProductPickerButton
              :model-value="pickedProduct"
              :show-label="false"
              @select="onProductSelect"
            />
          </div>

          <!-- 未选任何参考图：显示拖拽上传落区 -->
          <div v-if="!sourceImage" class="upload-area" :class="{ dragging }" @click="triggerUpload" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="handleDrop">
            <input
              ref="fileInputRef"
              type="file"
              accept="image/*"
              style="display: none"
              @change="handleFileChange"
            />
            <CloudUploadOutlined class="upload-icon" />
            <div class="upload-text">
              <p class="upload-hint">拖拽或点击上传原图</p>
              <p class="upload-sub">JPG / PNG / WebP，≤10MB · 也可点击右上角文件夹从产品库选</p>
            </div>
          </div>

          <!-- 已选参考图：统一显示，不区分来源 -->
          <div v-else class="upload-area has-image">
            <img :src="sourceImage" alt="参考图" class="preview-img" />
            <div class="preview-info">
              <span class="pi-name">{{ pickedProduct ? pickedProduct.title?.slice(0, 18) + (pickedProduct.title?.length > 18 ? '…' : '') : (sourceFile?.name || '已上传原图') }}</span>
              <span class="pi-source">{{ pickedProduct ? '📁 来自产品库' : '📤 手动上传' }}</span>
            </div>
            <div class="preview-actions">
              <a-button size="small" @click="triggerUpload"><RedoOutlined /> 更换</a-button>
              <a-button size="small" danger @click="removeImage"><DeleteOutlined /> 删除</a-button>
            </div>
          </div>

          <!-- 选中产品后，自动从卖点/痛点提取提示文案给 AI -->
          <div v-if="pickedProduct" class="product-info-line" :title="`卖点：${autoFilledSellingPoints || '—'}\n痛点：${autoFilledPainPoints || '—'}`">
            <span class="pi-label">卖点</span>
            <span class="pi-text">{{ autoFilledSellingPoints || '—' }}</span>
            <span class="pi-label">痛点</span>
            <span class="pi-text">{{ autoFilledPainPoints || '—' }}</span>
          </div>
        </section>

        <!-- ③ 两个 Tab：素材类型+通用参数 / 自定义 prompt
             「载入产品」在 Tab 外，两个 Tab 共用（它是出图前提输入）。 -->
        <a-tabs v-model:active-key="paramTab" size="small" class="param-tabs">
          <!-- Tab1：素材类型 + 全部结构化参数（通用 / 场景 / 信息图要点） -->
          <a-tab-pane key="params" tab="素材类型与参数">
            <div class="tab-pane-body">
              <!-- 素材类型（必填核心） -->
              <section class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">🎨</span>
                  <span class="title-text">素材类型</span>
                  <span class="title-hint">单选（每种素材用途不同）</span>
                </div>
                <div class="image-type-grid">
                  <div
                    v-for="type in imageTypes"
                    :key="type.id"
                    class="type-chip"
                    :class="{ active: form.imageTypes.includes(type.id) }"
                    :title="`${type.desc}\n${type.use}\n${type.rule}`"
                    @click="toggleImageType(type.id)"
                  >
                    <span class="chip-emoji">{{ type.icon }}</span>
                    <span class="chip-name">{{ type.name }}</span>
                  </div>
                </div>
              </section>

              <!-- 通用参数 -->
              <section class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">⚙️</span>
                  <span class="title-text">通用参数</span>
                </div>
                <div class="form-row">
                  <div class="form-group flex-1">
                    <label>拍摄风格</label>
                    <a-select v-model:value="form.style" size="small" style="width: 100%">
                      <a-select-option value="studio">专业棚拍</a-select-option>
                      <a-select-option value="natural-light">自然光纪实</a-select-option>
                      <a-select-option value="minimalist">极简风</a-select-option>
                      <a-select-option value="luxury">奢华高端</a-select-option>
                      <a-select-option value="playful">活泼趣味</a-select-option>
                      <a-select-option value="tech">科技感</a-select-option>
                    </a-select>
                  </div>
                  <div class="form-group flex-1">
                    <label>生成数量</label>
                    <a-input-number v-model:value="form.quantity" :min="1" :max="12" size="small" style="width: 100%" />
                  </div>
                </div>
              </section>

              <!-- 场景设置（场景图 / 生活方式图 / 广告主图 选中时） -->
              <!-- 白底背景的样式由素材类型（SPU 主图/白底副图）的 prompt 决定，无需额外配置 -->
              <section v-if="needsScene" class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">🏞️</span>
                  <span class="title-text">场景设置</span>
                </div>
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
              </section>

              <!-- 信息图解图 选中时：提示卖点来源 -->
              <section v-if="form.imageTypes.includes('infographic')" class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">📊</span>
                  <span class="title-text">信息图要点</span>
                </div>
                <div class="form-group">
                  <label>要强调的参数 / 卖点（可留空，AI 从产品卖点自动提取）</label>
                  <a-textarea
                    v-model:value="form.infographicPoints"
                    :rows="2"
                    placeholder="如：3000mAh 大电池、IPX7 防水、Type-C 快充…"
                    size="small"
                  />
                </div>
              </section>
            </div>
          </a-tab-pane>

          <!-- Tab2：自定义 prompt（全权由文字限定） -->
          <a-tab-pane key="prompt" tab="自定义 prompt">
            <div class="tab-pane-body">
              <section class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">✍️</span>
                  <span class="title-text">自定义 prompt</span>
                  <span class="title-hint">全权由文字限定，覆盖参数配置</span>
                </div>
                <div class="form-group">
                  <label>完整提示词（可选）</label>
                  <a-textarea
                    v-model:value="form.extraPrompt"
                    :auto-size="{ minRows: 4, maxRows: 10 }"
                    placeholder="用自然语言描述你想要的画面，例如：产品斜 45 度悬浮在纯白背景，左侧 45 度暖光，右侧补光，底部投影柔和，画面干净无杂物…"
                    size="small"
                  />
                </div>
                <p class="prompt-note">
                  💡 填写后优先按你的文字出图；留空则按「素材类型与参数」里的结构化选项自动生成提示词。
                </p>
              </section>
            </div>
          </a-tab-pane>
        </a-tabs>
      </div>

      <!-- 右侧：预览区（仅大屏模式）—— 复用 AIGCMediaResult：
           与对话流共用同一渲染真源，自带「归档到素材库」/ 逐项失败提示 / 文生图说明。
           此前这里是本文件自己写的一套 canvas-grid，结果既缺归档按钮、又与对话流渲染分叉。 -->
      <div v-if="isDataMode" class="split-preview">
        <div v-if="isGenerating" class="preview-loading">
          <a-spin size="large" />
          <p class="preview-loading-title">正在生成素材…</p>
          <p class="preview-loading-sub">单张约 15-25s，数量越多越久，请勿关闭页面</p>
        </div>
        <AIGCMediaResult
          v-else-if="latestResult"
          :data="latestResult"
          @close="latestResult = null"
        />
        <a-empty
          v-else
          description="暂无生成结果，点底部「开始生成素材」出图"
          :image-style="{ height: '48px' }"
        />
      </div>
    </div>

    <!-- ====== 操作按钮 ====== 大屏/对话两态都在容器底部（flex column 第二项），不参与表单滚动 -->
    <div class="action-bar">
      <a-button size="small" @click="handleReset"><ReloadOutlined /> 重置</a-button>
      <a-button
        type="primary"
        size="small"
        :loading="loading"
        @click="handleSubmit"
      >
        <PictureOutlined /> {{ latestResult ? '重新生成素材' : '开始生成素材' }}
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import { useAigcResultsStore } from '@/stores/aigcResults'
import {
  ReloadOutlined,
  PictureOutlined,
  CloudUploadOutlined,
  RedoOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import AIGCMediaResult from '@/components/ChatPanel/results/AIGCMediaResult.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const dragging = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// ====== 大屏/对话模式：读 Workspace 注入的 reviewMode（与其他看板 Agent 一致） ======
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ====== 两个 Tab：素材类型与参数 / 自定义 prompt ======
const paramTab = ref('params')

// ====== 最近结果（大屏预览数据源）======
// 结果存在全局 store 而非组件内 ref：TaskConfigPanel 用 v-else-if 挂载本组件，
// 切工具就会销毁重建 —— 存组件里必然出现「切走再切回，刚生成的就没了」。
// 读写都走 store，切工具只是换了个消费方，数据仍在（且是同一份对象引用）。
const AIGC_TOOL_ID = 'static-asset-gen'
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

// ====== 素材类型定义（09-14 老板重定义六类体系；单选） ======
const imageTypes = [
  { id: 'spu-main', icon: '🖼️', name: 'SPU 主图', desc: 'Listing 第 1 张图 · 搜索缩略图', use: '抓点击、搜索展示', rule: '✅ 强制纯白底，严格合规' },
  { id: 'white-bg', icon: '⚪', name: '白底副图', desc: '副图 · 多角度白底', use: '展示产品不同面', rule: '✅ 白底，但不是搜索缩略图，规则略松' },
  { id: 'scene', icon: '🛋️', name: '场景图', desc: '副图 / A+ 图', use: '提升转化，展示使用场景', rule: '❌ 不需要白底' },
  { id: 'lifestyle', icon: '✨', name: '生活方式图', desc: '副图 / A+ 图', use: '提升转化，展示使用场景', rule: '❌ 不需要白底' },
  { id: 'infographic', icon: '📊', name: '信息图解图', desc: '副图 / A+ 图', use: '打消买家疑虑，讲参数卖点', rule: '❌ 不需要白底' },
  { id: 'ad-main', icon: '📣', name: '广告主图', desc: '广告素材（SP/SD 广告）', use: '广告点击率测试', rule: '可场景图，不用于商品详情首图' },
]

// ====== 产品载入 ======
const pickedProduct = ref<any>(null)
const onProductSelect = (product: any) => {
  pickedProduct.value = product
  // 选中产品即把主图作为参考图预览（未手动上传过时）——
  // 否则「选了产品却看不到图，要再点一次生成才发现用了主图」
  if (!sourceImage.value && product?.main_image) {
    sourceImage.value = product.main_image
    sourceFile.value = null
  }
}

// 自动回填字段（从产品库带出卖点 / 痛点，只做展示与提示词补充）
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

// ====== 表单数据 ======
const defaultForm = () => ({
  // 素材类型：单选（六类语义互斥），默认 SPU 主图
  imageTypes: ['spu-main'] as string[],
  // 通用
  style: 'studio',
  quantity: 4,
  // 场景类（场景图 / 生活方式图 / 广告主图）
  sceneDescription: '',
  background: 'indoor',
  lighting: 'soft-box',
  // 信息图解图
  infographicPoints: '',
  // 自定义 prompt（填写后优先，覆盖结构化参数）
  extraPrompt: '',
})

const form = reactive(defaultForm())

// 场景设置 section：仅场景图 / 生活方式图 / 广告主图需要
// （白底图由素材类型自身的 prompt 决定背景，不需要这项配置）
const needsScene = computed(() => form.imageTypes.some((t) => ['scene', 'lifestyle', 'ad-main'].includes(t)))
watch(workingProduct, (product) => {
  if (product && !pickedProduct.value) pickedProduct.value = product
}, { immediate: true })

// ====== 图片类型切换 ======
// 单选：6 类语义互斥（SPU 主图强制白底 ≠ 场景图需要场景 ≠ 信息图需要参数排版），
// 选中 A 后点 B 会自动取消 A。点击当前唯一选中项 = 无变化（避免误清空）。
const toggleImageType = (id: string) => {
  if (form.imageTypes.length === 1 && form.imageTypes[0] === id) {
    message.info('当前已选，至少保留一种素材类型')
    return
  }
  form.imageTypes = [id]
}

// ====== 上传 ======
const sourceImage = ref('')
const sourceFile = ref<File | null>(null)
function triggerUpload() { fileInputRef.value?.click() }
function validateAndReadFile(file: File) {
  if (!file.type.startsWith('image/')) { message.error('请上传图片文件'); return }
  if (file.size > 10 * 1024 * 1024) { message.error('图片大小不能超过 10MB'); return }
  const reader = new FileReader()
  reader.onload = () => { sourceImage.value = reader.result as string }
  reader.readAsDataURL(file)
  sourceFile.value = file
}
function handleFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) validateAndReadFile(file)
}
function handleDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) validateAndReadFile(file)
}
function removeImage() {
  sourceImage.value = ''; sourceFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
}

// ====== 源图规范化 ======
/**
 * 把参考图转成后端能直接吃的形态。
 *
 * - **上传图**：`readAsDataURL` 出来已经是 base64 data URI ✓
 * - **产品库主图**：是 `/mock/products/xxx.png` 这类**本地相对路径**，
 *   万相服务端拉不到 → 必须在前端先读成 base64 再传。
 *   （万相 `base_image_url` 原生支持 base64 直传，**不需要图床**。）
 *
 * 读失败返回空串，调用方据此退回文生图 —— 绝不假装原图参与了生成。
 */
async function toDataUri(src: string): Promise<string> {
  if (!src) return ''
  if (src.startsWith('data:')) return src
  try {
    const resp = await fetch(src)
    if (!resp.ok) return ''
    const blob = await resp.blob()
    return await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(String(r.result || ''))
      r.onerror = () => reject(r.error)
      r.readAsDataURL(blob)
    })
  } catch {
    return ''
  }
}

// ====== 提交 ======
const handleSubmit = async () => {
  if (!pickedProduct.value) { message.warning('请先载入产品'); return }
  if (!sourceImage.value && pickedProduct.value?.main_image) {
    sourceImage.value = pickedProduct.value.main_image; sourceFile.value = null
  }
  if (!sourceImage.value) { message.warning('请上传产品实拍原图（或使用产品库主图）'); return }
  if (form.imageTypes.length === 0) { message.warning('请至少选择一种素材类型'); return }

  loading.value = true
  const sourceForApi = await toDataUri(sourceImage.value)
  if (!sourceForApi) {
    message.warning('参考图读取失败，本次将退回文生图（原图不参与生成）')
  }
  emit('startAnalysis', {
    tool: 'static-asset-gen',
    // mode 如实反映实际通道：拿到可用源图才是图生图，否则文生图
    mode: sourceForApi ? 'image-to-image' : 'text-to-image',
    ...form,
    source_image: sourceForApi,
    source_image_name: sourceFile.value?.name || 'product-main-image',
    _sourceProduct: pickedProduct.value,
    selling_points: autoFilledSellingPoints.value,
    pain_points: autoFilledPainPoints.value,
  })
  setTimeout(() => (loading.value = false), 500)
}
const handleReset = () => {
  Object.assign(form, defaultForm())
  pickedProduct.value = null
  removeImage()
  paramTab.value = 'params'
}
</script>

<style scoped>
.static-asset-config {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* ====== 内容容器：对话单列 / 大屏左右分栏 ====== */
.content {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content.data-layout {
  display: grid;
  /* 左：配置（最小 280px，弹性增长）
     右：预览（最小 280px，弹性增长，比例 1.3x 让预览更舒展） */
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 1.3fr);
  gap: var(--space-12);
}

/* ====== 表单容器（唯一一份，对话平铺 / 大屏左列） ====== */
.form-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  padding-bottom: var(--space-4);
}

/* ====== 统一 section 标题层级（平铺，无折叠箭头） ====== */
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
  margin-left: auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ====== 卖点 / 痛点行（选中产品后才显示） ====== */
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
.pi-text {
  flex: 1 1 0;
  min-width: 0;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pi-text + .pi-label { margin-left: var(--space-4); }

/* ====== 载入产品区（2 选 1 统一预览：拖拽上传 或 产品库主图） ====== */
.upload-area {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  border: 2px dashed var(--border-strong);
  border-radius: var(--radius-8);
  padding: var(--space-10) var(--space-12);
  cursor: pointer;
  background: var(--bg-sidebar);
  transition: border-color 0.2s;
}
.upload-area:hover { border-color: var(--primary); }
.upload-area.dragging { border-color: var(--primary); background: var(--info-bg); }
.upload-icon { font-size: 22px; color: var(--primary); flex-shrink: 0; }
.upload-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }
.upload-hint { margin: 0; font-size: var(--font-size-12); color: var(--text-primary); font-weight: 500; }
.upload-sub { margin: 0; font-size: var(--font-size-11); color: var(--text-tertiary); }

.upload-area.has-image {
  padding: var(--space-6) var(--space-10);
  cursor: default;
  border-style: solid;
  border-color: var(--border-base);
  background: var(--bg-elevated);
}
.preview-img {
  width: 56px; height: 56px;
  flex: 0 0 56px;
  border-radius: var(--radius-6);
  object-fit: cover;
}
.preview-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 auto;
  min-width: 0;
}
.pi-name {
  font-size: var(--font-size-12);
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pi-source {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.preview-actions { display: flex; gap: var(--space-8); flex: 0 0 auto; }

/* ====== 素材类型网格 ====== */
.image-type-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-6);
}
.type-chip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-8) var(--space-6);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  cursor: pointer;
  transition: all 0.2s;
  background: var(--bg-elevated);
  min-width: 0;
}
.type-chip:hover { border-color: var(--primary); }
.type-chip.active { border-color: var(--primary); background: var(--info-bg); }
.chip-emoji { font-size: var(--font-size-16); flex-shrink: 0; line-height: 1; }
.chip-name {
  font-size: var(--font-size-12);
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.type-chip.active .chip-name { color: var(--primary); }

/* ====== 两个 Tab：素材类型与参数 / 自定义 prompt ====== */
.param-tabs {
  flex: 1 1 auto;
  min-height: 0;
}
.param-tabs :deep(.ant-tabs-content-holder) {
  overflow: visible;
}
.tab-pane-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  padding-top: var(--space-4);
}
.prompt-note {
  margin: 0;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1.6;
}

/* ====== 表单 ====== */
.form-group > label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  font-weight: 500;
}
.form-row { display: flex; gap: var(--space-10); }
.flex-1 { flex: 1; min-width: 0; }

/* ====== 操作栏 ====== 大屏/对话两态统一固定在容器底部（flex:0 0 auto），
   表单滚动不影响操作栏可见。 */
.action-bar {
  flex: 0 0 auto;
  display: flex;
  gap: var(--space-10);
  margin-top: var(--space-10);
  padding-top: var(--space-10);
  border-top: 1px solid var(--border-base);
}
.action-bar :deep(.ant-btn) { flex: 1; }

/* ====== 预览画布 ====== */
.split-preview {
  /* 右侧预览：固定高度，自带滚动 */
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
  flex: 0 0 auto;
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--border-base);
}
.canvas-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.canvas-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-10);
}
.canvas-item {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  overflow: hidden;
  background: var(--bg-elevated);
}
.canvas-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}
.canvas-meta {
  padding: var(--space-6) var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.canvas-desc {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
