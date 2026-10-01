<template>
  <div class="video-script-config">
    <!-- ====== 布局：唯一一份表单 + 大屏模式追加右半边预览 ======
         ★ 第 263 轮重构：消灭「v-if/v-else 两份模板」结构。
           本文件此前按 isDataMode 写了两套模板：大屏精简版（① ② ③）
           + 对话完整版（① ② ③ ④分镜表 ⑤首帧参考 ⑥额外要求）。
           两份模板必然漂移 —— 这正是「两个界面参数差别这么多」的根因。
           现收敛为与 StaticAssetConfig.vue 同一范式：
             ① 表单只写一遍（.form-body，两态共用）
             ② 大屏模式只是在 .content 上多加 .data-layout（两列 grid），右列挂预览
             ③ 自由文字（原「额外要求」）收进 <a-tabs> 第二个 Tab
           ⇒ 参数项 / 取值 / 文案天然只有一份，不存在「改一处要同步另一处」。
           原 ④分镜表 / ⑤首帧参考 已删除：分镜结构改由「分镜数」参数描述，
           逐镜细节在**生成结果表**里就地编辑（AIGCMediaResult.vue，已实现）。 -->
    <div
      class="content"
      :class="{ 'data-layout': isDataMode }"
    >
      <div class="form-body">
        <!-- ① 载入产品：脚本只要卖点/痛点，不需要上传图片 -->
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
          <div
            v-if="pickedProduct"
            class="product-info-line"
            :title="`产品：${pickedProduct.title || '—'}\n卖点：${autoFilledSellingPoints || '—'}\n痛点：${autoFilledPainPoints || '—'}`"
          >
            <span class="pi-label">卖点</span>
            <span class="pi-text">{{ autoFilledSellingPoints || '—' }}</span>
            <span class="pi-label">痛点</span>
            <span class="pi-text">{{ autoFilledPainPoints || '—' }}</span>
          </div>
          <div
            v-else
            class="picker-empty"
          >
            <span>👆 点右上角文件夹按钮从产品库选</span>
          </div>
        </section>

        <!-- ② 两个 Tab：视频参数（结构化选项）/ 自定义脚本要求（自由文字）
             对齐 StaticAssetConfig.vue 的「素材类型与参数 / 自定义 prompt」分法。 -->
        <a-tabs
          v-model:active-key="paramTab"
          size="small"
          class="param-tabs"
        >
          <a-tab-pane
            key="params"
            tab="视频参数"
          >
            <div class="tab-pane-body">
              <!-- ②-1 视频基本信息：视频时长 / 分镜数 / 单镜时长三者恒联动（时长 = 分镜数 × 单镜时长） -->
              <section class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">🎞️</span>
                  <span class="title-text">视频基本信息</span>
                </div>
                <div class="form-row">
                  <div class="form-group flex-1">
                    <label>目标平台</label>
                    <a-select
                      v-model:value="form.platform"
                      size="small"
                      style="width: 100%"
                    >
                      <a-select-option
                        v-for="p in platforms"
                        :key="p.id"
                        :value="p.id"
                      >
                        {{ p.icon }} {{ p.name }}
                      </a-select-option>
                    </a-select>
                  </div>
                  <div class="form-group flex-1">
                    <label>视频时长（秒）</label>
                    <a-input-number
                      :value="form.duration"
                      :min="MIN_DURATION"
                      :max="MAX_DURATION"
                      :step="1"
                      size="small"
                      style="width: 100%"
                      @change="onDurationChange"
                    />
                  </div>
                </div>
                <div class="form-row">
                  <div class="form-group flex-1">
                    <label>分镜数（个）</label>
                    <a-input-number
                      :value="form.sceneCount"
                      :min="MIN_SCENE_COUNT"
                      :max="MAX_SCENE_COUNT"
                      :step="1"
                      size="small"
                      style="width: 100%"
                      @change="onSceneCountChange"
                    />
                  </div>
                  <div class="form-group flex-1">
                    <label>单镜时长（秒）</label>
                    <a-input-number
                      :value="form.sceneDuration"
                      :min="MIN_SCENE_DURATION"
                      :max="MAX_SCENE_DURATION"
                      :step="1"
                      size="small"
                      style="width: 100%"
                      @change="onSceneDurationChange"
                    />
                  </div>
                </div>
                <p class="prompt-note scene-note">
                  💡 三项联动（视频时长 = 分镜数 × 单镜时长）：{{ form.sceneCount }} 个镜头 × 每镜 {{ form.sceneDuration }} 秒 ≈ {{ form.duration }} 秒；改任一项另两项自动换算，生成后可在结果的分镜表里逐项编辑。
                </p>
                <div class="form-group">
                  <label>脚本风格</label>
                  <a-radio-group
                    v-model:value="form.videoStyle"
                    size="small"
                  >
                    <a-radio-button value="problem-solution">
                      痛点驱动
                    </a-radio-button>
                    <a-radio-button value="product-showcase">
                      产品展示
                    </a-radio-button>
                    <a-radio-button value="story-telling">
                      故事化
                    </a-radio-button>
                    <a-radio-button value="comparison">
                      对比测评
                    </a-radio-button>
                  </a-radio-group>
                </div>
              </section>

              <!-- ②-2 脚本技巧 -->
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
                    <span
                      class="opt-label"
                      :title="opt.desc"
                    >{{ opt.label }}</span>
                  </a-checkbox>
                </div>
              </section>
            </div>
          </a-tab-pane>

          <!-- Tab2：自定义脚本要求（自由文字，全权限定脚本写法） -->
          <a-tab-pane
            key="prompt"
            tab="自定义脚本要求"
          >
            <div class="tab-pane-body">
              <section class="cfg-section">
                <div class="section-title">
                  <span class="title-icon">✍️</span>
                  <span class="title-text">自定义脚本要求</span>
                  <span class="title-hint">可选，优先于上方参数</span>
                </div>
                <div class="form-group">
                  <!-- 提示词增强：这段文字是「写脚本的硬约束」，整段会送进模型 ⇒ 最值得扩写的输入点 -->
                  <div class="label-row">
                    <label>完整脚本要求（可选）</label>
                    <PromptEnhanceButton
                      v-model="form.extraScriptPrompt"
                      context="video-script"
                      size="sm"
                    />
                  </div>
                  <a-textarea
                    v-model:value="form.extraScriptPrompt"
                    :auto-size="{ minRows: 4, maxRows: 10 }"
                    placeholder="如：开头 3 秒必须 hook 出痛点；结尾 CTA 引导点击购物车；每个镜头都要出现产品…"
                    size="small"
                  />
                </div>
                <p class="prompt-note">
                  💡 填写后优先按你的文字写脚本；留空则按「视频参数」里的结构化选项自动生成。
                </p>
              </section>
            </div>
          </a-tab-pane>
        </a-tabs>
      </div>

      <!-- 大屏模式右半边：预览区 —— 复用 AIGCMediaResult（与对话流同一渲染真源，
           自带归档 / 逐项失败提示，避免本文件自己再维护一套分镜预览） -->
      <div
        v-if="isDataMode"
        class="split-preview"
      >
        <div
          v-if="isGenerating"
          class="preview-loading"
        >
          <a-spin size="large" />
          <p class="preview-loading-title">
            正在生成带货脚本…
          </p>
          <p class="preview-loading-sub">
            含分镜表与文案，约 10-20s，请勿关闭页面
          </p>
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

    <!-- 操作按钮：大屏/对话两态都在容器底部（flex column 第二项），不参与 .form-body 滚动 -->
    <div class="action-bar">
      <a-button
        size="small"
        @click="handleReset"
      >
        <ReloadOutlined /> 重置
      </a-button>
      <a-button
        type="primary"
        size="small"
        :loading="loading"
        @click="handleSubmit"
      >
        <VideoCameraOutlined /> {{ latestResult ? '重新生成脚本' : '生成带货脚本' }}
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, inject, type Ref } from 'vue'
import { useAigcResultsStore } from '@/stores/aigcResults'
import { ReloadOutlined, VideoCameraOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import AIGCMediaResult from '@/components/ChatPanel/results/AIGCMediaResult.vue'
import PromptEnhanceButton from '@/components/common/PromptEnhanceButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// ====== 大屏/对话模式 ======
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// Tab 激活项（对齐 StaticAssetConfig.vue）
const paramTab = ref('params')

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

/** 每个分镜的默认时长（秒）—— 需求「每个分镜默认 5 秒」 */
const SCENE_DURATION = 5
/** 视频时长默认 30 秒（短视频主流档位） */
const DEFAULT_DURATION = 30

// ====== 视频时长 ⇄ 分镜数 ⇄ 单镜时长：三者恒满足 时长 = 分镜数 × 单镜时长 ======
// 需求：「选择视频时长，则单镜时长就要直接算；选择单镜时长，视频时长就要直接算（一一对应）」。
// 此前三项各选各的（默认 30 秒 / 5 镜 / 5 秒 → 25 ≠ 30），参数自相矛盾。
// 用 InputNumber 而非 Select：联动结果未必落在预设档位上（30 秒 ÷ 4 镜 = 7.5 秒），
// 硬用枚举会装不下算出来的值，只能丢精度或静默改掉用户刚选的那项。
const MIN_DURATION = 3
const MAX_DURATION = 600
const MIN_SCENE_COUNT = 1
const MAX_SCENE_COUNT = 30
const MIN_SCENE_DURATION = 0.5
const MAX_SCENE_DURATION = 60

/** 输入兜底：清空输入框时值为 null/''，不能让 NaN 进表单 */
const toNum = (v: any, fallback: number) => {
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return Number.isFinite(n) ? n : fallback
}
/** 秒数收尾到 2 位：既消掉 30.000000000000004 这类浮点尾巴，也让输入框不显示长小数 */
const round2 = (n: number) => Math.round(n * 100) / 100
const clampNum = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))

/** 改「视频时长」：分镜数不动，单镜时长 = 时长 ÷ 分镜数（30 ÷ 4 = 7.5）。
 *  正常情况**不回写 duration** —— 用户选的时长是平台约束，不能被偷偷改成 28 或 32。 */
const onDurationChange = (v: any) => {
  const d = round2(clampNum(toNum(v, form.duration), MIN_DURATION, MAX_DURATION))
  const per = round2(d / form.sceneCount)
  form.duration = d
  form.sceneDuration = clampNum(per, MIN_SCENE_DURATION, MAX_SCENE_DURATION)
  // 仅当单镜时长被上下限顶住时（如 3 秒 ÷ 20 镜 = 0.15 → 0.5）才回写时长，保证框里两项不打架
  if (form.sceneDuration !== per) form.duration = round2(form.sceneDuration * form.sceneCount)
}
/** 改「单镜时长」：视频时长 = 分镜数 × 单镜时长 */
const onSceneDurationChange = (v: any) => {
  const per = round2(clampNum(toNum(v, form.sceneDuration), MIN_SCENE_DURATION, MAX_SCENE_DURATION))
  form.sceneDuration = per
  form.duration = round2(clampNum(per * form.sceneCount, MIN_DURATION, MAX_DURATION))
}
/** 改「分镜数」：分镜数是结构意图，以「单镜时长」为节奏基准（每镜默认 5 秒），重算总时长 */
const onSceneCountChange = (v: any) => {
  form.sceneCount = Math.round(clampNum(toNum(v, form.sceneCount), MIN_SCENE_COUNT, MAX_SCENE_COUNT))
  form.duration = round2(clampNum(form.sceneDuration * form.sceneCount, MIN_DURATION, MAX_DURATION))
}

/** 默认值必须自洽：30 秒 = 6 镜 × 5 秒（此前默认 30 秒 / 5 镜 / 5 秒 = 25 秒，三项互相打架） */
const defaultForm = () => ({
  platform: 'tiktok',
  duration: DEFAULT_DURATION,
  videoStyle: 'problem-solution',
  scriptOptions: ['hook-opening', 'pain-agitate', 'cta-strong', 'subtitle-friendly'] as string[],
  sceneCount: Math.round(DEFAULT_DURATION / SCENE_DURATION),
  sceneDuration: SCENE_DURATION,
  extraScriptPrompt: '',
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

// ====== 提交 ======
const handleSubmit = () => {
  if (!pickedProduct.value) { message.warning('请先载入产品'); return }
  // 三项已联动 → form.duration 恒等于「分镜数 × 单镜时长」，
  // 原先那句「分镜总时长超出目标时长」的告警随之删除：它能被触发的原因，
  // 恰恰就是三项自相矛盾（30 秒 / 5 镜 / 5 秒）——联动后这种状态不存在了。
  loading.value = true
  emit('startAnalysis', {
    tool: 'video-script-gen',
    ...form,
    _sourceProduct: pickedProduct.value,
    selling_points: autoFilledSellingPoints.value,
    pain_points: autoFilledPainPoints.value,
    total_scene_duration: form.duration,
  })
  setTimeout(() => (loading.value = false), 500)
}
const handleReset = () => {
  Object.assign(form, defaultForm())
  pickedProduct.value = null
  paramTab.value = 'params'
}
</script>

<style scoped>
.video-script-config {
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

/* ====== 预览画布 ====== */
.split-preview {
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

/* ====== 载入产品 ====== */
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

/* ====== 两个 Tab：视频参数 / 自定义脚本要求 ====== */
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
/* 分镜数 / 单镜时长的换算提示：单独给下间距，别紧贴下面的「脚本风格」 */
.scene-note { margin: var(--space-2) 0 var(--space-10); }

/* ====== 表单 ====== */
.form-group > label,
.label-row > label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  font-weight: 500;
}
/* 字段名 + 右侧「提示词增强」按钮同排。
   ★ 别把按钮塞进 <label>：button 是 labelable 元素 ⇒ 点标签文字会一并触发增强。 */
.label-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-6); }
.label-row > label { margin-bottom: 0; }
.form-group { margin-bottom: var(--space-10); }
.form-row { display: flex; gap: var(--space-10); }
.flex-1 { flex: 1; min-width: 0; }

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
