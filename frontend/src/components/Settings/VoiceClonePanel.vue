<template>
  <div class="voice-clone-panel">
    <!-- 模块不可用：总开关关闭 / 后端路由不存在 → 显示空态，不做任何兜底 -->
    <a-result
      v-if="configError"
      status="info"
      title="该功能未启用"
      :sub-title="configError"
    />

    <template v-else>
      <!-- ============ 音色状态条 ============ -->
      <a-alert
        v-if="record.status === 'ready'"
        type="success"
        show-icon
        class="vc-alert"
      >
        <template #message>
          音色已就绪
          <a-tag color="blue" class="vc-tag">{{ record.voice_id }}</a-tag>
        </template>
        <template #description>
          <div class="vc-meta">
            <span>驱动模型：{{ record.target_model || '—' }}</span>
            <span v-if="record.authorized_at">授权时间：{{ formatTime(record.authorized_at) }}</span>
          </div>
        </template>
      </a-alert>

      <a-alert
        v-else-if="record.status === 'pending'"
        type="warning"
        show-icon
        class="vc-alert"
        message="音色审核中"
        description="平台正在审核音色样本，通常几分钟内完成。可点击「刷新状态」重新查询。"
      >
        <template #action>
          <a-button size="small" :loading="statusLoading" @click="refreshStatus">刷新状态</a-button>
        </template>
      </a-alert>

      <a-alert
        v-else-if="record.status === 'failed'"
        type="error"
        show-icon
        class="vc-alert"
        message="上次创建失败"
        :description="record.error_msg || '未记录失败原因（请重新提交并保留错误信息）'"
      />

      <a-alert
        v-else-if="config?.sample_limits.require_public_url"
        type="warning"
        show-icon
        class="vc-alert"
        message="缺少公网访问地址"
        description="声音复刻要求音频样本公网可访问。请在后端配置 PUBLIC_BASE_URL（本地 localhost 地址平台侧取不到），否则创建音色会失败。"
      />

      <!-- ★ 错误一律就近显示在「触发它的那一步」：状态查询失败 → 状态条区 -->
      <a-alert
        v-if="lastError && errorScope === 'status'"
        type="error"
        show-icon
        class="vc-alert"
        :message="lastError"
      />

      <!-- ============ 步骤 1：录制 / 上传样本 ============ -->
      <a-card :bordered="false" class="vc-card">
        <template #title>
          <span class="vc-step">1</span> 录制音频样本
        </template>

        <!-- 通道 A：跟读录音（只在安全上下文 + 麦克风可用时出现） -->
        <div v-if="recorder.supported" class="vc-rec">
          <div class="vc-rec-label">
            跟着下面这段念，不用背（约 {{ scriptSeconds }} 秒，念完自动够长）
          </div>
          <div class="vc-rec-script">
            <span
              v-for="(s, i) in SCRIPT_SENTENCES"
              :key="i"
              class="vc-rec-sentence"
              :class="{
                'is-current': recorder.isRecording && i === currentSentence,
                'is-done': recorder.isRecording && i < currentSentence,
              }"
              >{{ s }}</span
            >
          </div>

          <div class="vc-rec-bar">
            <div class="vc-rec-meter">
              <div class="vc-rec-meter-fill" :style="{ width: meterPct + '%' }"></div>
            </div>
            <span class="vc-rec-time">{{ elapsedText }} / 建议 {{ suggestRange }}</span>
          </div>

          <div class="vc-rec-actions">
            <a-button v-if="!recorder.isRecording" type="primary" :loading="recordStarting" @click="startRecord">
              <AudioOutlined /> {{ recordedFile ? '重新录制' : '开始录制' }}
            </a-button>
            <a-button v-else danger @click="stopRecord">
              <StopOutlined /> 停止录制
            </a-button>
          </div>

          <!-- 录音失败必须显示原因，不做兜底 -->
          <div v-if="recorder.error" class="vc-hint vc-hint-warn">{{ recorder.error }}</div>
        </div>

        <!-- 通道 B：上传文件。录音不可用时这是唯一入口，因此**不可删**。 -->
        <div class="vc-upload-wrap">
          <div v-if="recorder.supported" class="vc-or">或上传已有音频文件</div>
          <div v-else class="vc-hint vc-hint-warn vc-hint-lead">
            当前环境无法浏览器录音：{{ recorder.unsupportedReason }}
          </div>

          <a-upload-dragger
            v-model:file-list="fileList"
            :max-count="1"
            :before-upload="beforeUpload"
            :accept="acceptExts"
            @remove="onRemove"
          >
            <p class="ant-upload-drag-icon"><InboxOutlined /></p>
            <p class="ant-upload-text">点击或拖拽音频文件到此处</p>
            <p class="ant-upload-hint">
              支持 {{ limitsText.exts }} · 建议 10~20 秒 · 至少 5 秒连续清晰朗读 ·
              ≤ {{ limitsText.maxMb }} MB
            </p>
          </a-upload-dragger>
        </div>

        <!-- 校验徽标：把硬要求逐条摆出来，用户一眼看出行不行 -->
        <div v-if="sample" class="vc-badges">
          <a-tag :color="extOk ? 'success' : 'error'">格式 {{ sampleExt || '未知' }}</a-tag>
          <a-tag :color="sizeOk ? 'success' : 'error'">
            大小 {{ (sample.size / 1024 / 1024).toFixed(2) }} MB
          </a-tag>
          <a-tag :color="durationOk === null ? 'default' : durationOk ? 'success' : 'error'">
            时长 {{ sampleDuration === null ? '未测到' : sampleDuration.toFixed(1) + 's' }}
          </a-tag>
          <a-tag v-if="sample.duration_verified === false" color="warning">未校验时长</a-tag>
        </div>

        <div v-if="sample" class="vc-sample-actions">
          <audio :src="sample.url" controls class="vc-audio" />
          <a-button size="small" danger type="text" @click="clearSample">清除</a-button>
        </div>

        <a-alert
          v-if="lastError && errorScope === 'sample'"
          type="error"
          show-icon
          class="vc-alert vc-alert-top"
          :message="lastError"
        />
      </a-card>

      <!-- ============ 步骤 2：授权确认 ============ -->
      <a-card :bordered="false" class="vc-card">
        <template #title>
          <span class="vc-step">2</span> 授权确认
        </template>

        <div class="vc-agreement">{{ AGREEMENT_TEXT }}</div>

        <a-checkbox v-model:checked="authorized" class="vc-checkbox">
          我已阅读并同意上述条款，确认对该声音拥有合法使用权
        </a-checkbox>
      </a-card>

      <!-- ============ 步骤 3：创建音色 ============ -->
      <a-card :bordered="false" class="vc-card">
        <template #title>
          <span class="vc-step">3</span> 创建音色
        </template>

        <a-form layout="vertical">
          <a-form-item label="驱动模型">
            <a-select v-model:value="targetModel" :options="modelOptions" />
            <div class="vc-hint">
              音色与模型**死绑**：创建后不可换模型，换模型需重新克隆。
            </div>
          </a-form-item>
        </a-form>

        <a-button
          type="primary"
          :loading="enrolling"
          :disabled="!canEnroll"
          @click="handleEnroll"
        >
          {{ record.status === 'ready' ? '已有可用音色' : '开始克隆' }}
        </a-button>
        <div v-if="!canEnroll && !enrolling" class="vc-hint vc-hint-warn">
          {{ enrollBlockReason }}
        </div>

        <!-- ★ 「删除音色」归步骤 3（音色生命周期管理），不归步骤 4（试听）。
             ★★ 硬证据：上面 enrollBlockReason 的文案就是「已有可用音色…请先删除」——
                按提示去找删除入口，却在上一步的另一张卡片里。
             与主操作分行 + 二次确认：紧邻 primary 的不可逆操作（连带释放远端配额）误点代价高。 -->
        <div v-if="record.exists" class="vc-danger-row">
          <a-popconfirm
            title="删除后远端配额一并释放，需重新录制样本并克隆"
            @confirm="handleDelete"
          >
            <a-button danger :loading="deleting">删除音色</a-button>
          </a-popconfirm>
        </div>

        <a-alert
          v-if="lastError && errorScope === 'enroll'"
          type="error"
          show-icon
          class="vc-alert vc-alert-top"
          :message="lastError"
        />
      </a-card>

      <!-- ============ 步骤 4：试听 ============ -->
      <a-card :bordered="false" class="vc-card">
        <template #title>
          <span class="vc-step">4</span> 试听
        </template>

        <a-form layout="vertical">
          <a-form-item label="试听文案">
            <a-textarea
              v-model:value="previewText"
              :rows="2"
              :maxlength="200"
              show-count
              placeholder="留空则使用默认文案"
            />
          </a-form-item>
        </a-form>

        <a-space>
          <a-button
            :loading="previewing"
            :disabled="!record.ready"
            @click="handlePreview"
          >
            <SoundOutlined /> 生成试听
          </a-button>
        </a-space>

        <div v-if="!record.ready" class="vc-hint vc-hint-warn">
          音色未就绪，暂不能试听{{ record.exists ? '（当前状态：' + statusText(record.status) + '）' : '' }}
        </div>

        <div v-if="previewUrl" class="vc-preview">
          <audio :src="previewUrl" controls class="vc-audio" />
          <div class="vc-hint">{{ previewHint }}</div>
        </div>

        <!-- 失败原因必须显式展示，不做兜底（只显示本卡片触发的） -->
        <a-alert
          v-if="lastError && errorScope === 'preview'"
          type="error"
          show-icon
          class="vc-alert vc-alert-top"
          :message="lastError"
        />
      </a-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { AudioOutlined, InboxOutlined, SoundOutlined, StopOutlined } from '@ant-design/icons-vue'
import {
  type SampleUploadResult,
  type VoiceConfig,
  type VoiceRecord,
  deleteVoice,
  enrollVoice,
  fetchVoiceConfig,
  fetchVoiceStatus,
  previewVoice,
  uploadVoiceSample,
} from '@/api/voiceClone'
import { useUserStore } from '@/stores/user'
import { useVoiceRecorder } from '@/composables/useVoiceRecorder'

/**
 * 语音克隆面板 —— 附加模块，可插拔
 *
 * ★ 隔离约定：本组件**不 import 任何既有业务组件 / store**（只读 userStore 拿用户 ID）。
 *   宿主 Settings.vue 只加一个 <a-tab-pane> + 一行 import，不碰既有 Tab 代码。
 * ★ 空状态优于虚构默认：拿不到数据就显示空态 / 报错原因，绝不编造音色。
 */

/** ★ 授权条款原文。勾选时**原样**发给后端做快照 —— 日后改了措辞也能证明当时授权的是哪一版。 */
const AGREEMENT_TEXT =
  '我确认本人对该音频样本中的声音拥有合法使用权或已获得声音权利人的明确授权，' +
  '并同意将该声音用于本店铺的客服语音回复。我理解并承担因授权不实产生的一切法律责任。'

const userStore = useUserStore()

const config = ref<VoiceConfig | null>(null)
const configError = ref('')
const record = ref<VoiceRecord>({ exists: false, status: 'none', ready: false })

const fileList = ref<any[]>([])
const sample = ref<SampleUploadResult | null>(null)
const sampleDuration = ref<number | null>(null)
const recordedFile = ref<File | null>(null)
const recordStarting = ref(false)
const authorized = ref(false)
const targetModel = ref('')
const previewText = ref('')
const previewUrl = ref('')
const previewHint = ref('')
const lastError = ref('')
/**
 * ★ 错误必须显示在「触发它的那一步」的卡片里，不能全塞到最后一张卡。
 * 改前：lastError 是共用槽、6 个动作都往里写、却只渲染在步骤 4 底部
 * ⇒ 在步骤 3 点「开始克隆」失败，原因要滚到步骤 4 才看得见。
 */
type ErrorScope = 'status' | 'sample' | 'enroll' | 'preview'
const errorScope = ref<ErrorScope>('enroll')
function setError(scope: ErrorScope, msg: string): void {
  errorScope.value = scope
  lastError.value = msg
}

const enrolling = ref(false)
const previewing = ref(false)
const deleting = ref(false)
const statusLoading = ref(false)

const limitsText = computed(() => ({
  exts: (config.value?.sample_limits.exts || ['.wav', '.mp3', '.m4a'])
    .map((e) => e.replace('.', '').toUpperCase())
    .join(' / '),
  maxMb: ((config.value?.sample_limits.max_bytes || 10485760) / 1024 / 1024).toFixed(0),
}))

const acceptExts = computed(() =>
  (config.value?.sample_limits.exts || ['.wav', '.mp3', '.m4a']).join(','),
)

const modelOptions = computed(() =>
  (config.value?.target_models || []).map((m) => ({
    value: m.value,
    label: m.note ? `${m.label}（${m.note}）` : m.label,
  })),
)

// ---- 样本校验徽标 ----
const sampleExt = computed(() => {
  const n = sample.value?.name || ''
  const i = n.lastIndexOf('.')
  return i >= 0 ? n.slice(i).toLowerCase() : ''
})
const extOk = computed(() =>
  (config.value?.sample_limits.exts || []).includes(sampleExt.value),
)
const sizeOk = computed(() => {
  if (!sample.value || !config.value) return false
  return sample.value.size > 0 && sample.value.size <= config.value.sample_limits.max_bytes
})
const durationOk = computed(() => {
  if (sampleDuration.value === null || !config.value) return null
  return (
    sampleDuration.value >= config.value.sample_limits.min_seconds &&
    sampleDuration.value <= config.value.sample_limits.max_seconds
  )
})

const enrollBlockReason = computed(() => {
  if (config.value?.sample_limits.require_public_url) {
    return '后端未配置 PUBLIC_BASE_URL，样本无法公网回源，创建会失败。'
  }
  if (!sample.value) return '请先上传音频样本。'
  if (!authorized.value) return '请先勾选授权确认。'
  if (record.value.status === 'ready') return '当前店铺已有可用音色（单店铺单音色），请先删除。'
  return ''
})

const canEnroll = computed(
  () =>
    !!sample.value &&
    authorized.value &&
    !config.value?.sample_limits.require_public_url &&
    record.value.status !== 'ready',
)

// ---- 工具 ----
function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function statusText(s: string): string {
  return (
    { none: '未创建', pending: '审核中', ready: '已就绪', failed: '创建失败' }[s] || s
  )
}

/** 用 Audio 元素测时长（浏览器原生，零依赖） */
function probeDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const audio = new Audio()
    let done = false
    const finish = (v: number | null) => {
      if (done) return
      done = true
      URL.revokeObjectURL(url)
      resolve(v)
    }
    audio.addEventListener('loadedmetadata', () => {
      const d = audio.duration
      finish(Number.isFinite(d) && d > 0 ? d : null)
    })
    audio.addEventListener('error', () => finish(null))
    // 兜底超时：3 秒测不到就当未测到（不阻塞上传）
    setTimeout(() => finish(null), 3000)
    audio.src = url
  })
}

// ---- 跟读录音 ----
/**
 * 跟读稿：电商客服语境，78 字 ≈ 17 秒，声母全覆盖
 * （b p m f d t n l g k h j q x zh ch sh r z c s y w）。
 * 念的就是商品文案口吻 → 克隆出的音色也更适合念商品。
 */
const SCRIPT_SENTENCES = [
  '您好，欢迎光临我们的店铺。',
  '今天为您推荐一款热销商品，',
  '它的材质柔软舒适，颜色有浅灰、米白和藏青三种可选。',
  '现在下单还可以享受包邮服务，',
  '有任何问题随时联系我们，感谢您的支持与信任。',
]

const recorder = useVoiceRecorder()

/** 普通话朗读约 4.5 字/秒，用来估算跟读稿需要多久念完 */
const scriptSeconds = computed(() => Math.round(SCRIPT_SENTENCES.join('').length / 4.5))

/**
 * 按「已录秒数 ÷ 预计时长」的字数比例定位当前念到第几句。
 * 不用语音识别：那条链路既慢又不可靠（国内网络下经常直接失败），做进度纯属自找麻烦。
 */
const currentSentence = computed(() => {
  const total = SCRIPT_SENTENCES.join('').length
  const spoken = Math.floor((recorder.elapsed / Math.max(1, scriptSeconds.value)) * total)
  let acc = 0
  for (let i = 0; i < SCRIPT_SENTENCES.length; i += 1) {
    acc += SCRIPT_SENTENCES[i].length
    if (spoken < acc) return i
  }
  return SCRIPT_SENTENCES.length - 1
})

const suggestRange = computed(() => {
  const lim = config.value?.sample_limits
  return lim ? `${Math.round(lim.min_seconds)}~${Math.round(lim.max_seconds)} 秒` : '10~20 秒'
})

const elapsedText = computed(() => {
  const s = Math.floor(recorder.elapsed)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

const meterPct = computed(() => Math.round(recorder.level * 100))

async function startRecord(): Promise<void> {
  lastError.value = ''
  recordedFile.value = null
  clearSample()
  recordStarting.value = true
  try {
    const ok = await recorder.start()
    // ★ 失败原因由 recorder.error 承载（权限 / 无设备 / 被占用 / 非安全上下文各不相同）
    if (!ok) message.warning(recorder.error || '无法启动录音')
  } finally {
    recordStarting.value = false
  }
}

async function stopRecord(): Promise<void> {
  const file = await recorder.stop()
  if (!file) {
    if (recorder.error) message.warning(recorder.error)
    return
  }
  recordedFile.value = file
  recorder.reset()
  // ★ 复用既有上传链路：产出的就是标准 WAV，落在后端白名单内，后端零改动
  await handleUpload(file)
}

// ---- 上传流程 ----
function beforeUpload(file: File): boolean {
  fileList.value = [{ name: file.name, status: 'done' } as any]
  void handleUpload(file)
  return false // 阻止 antd 自动上传，走自定义
}

async function handleUpload(file: File): Promise<void> {
  lastError.value = ''
  try {
    const duration = await probeDuration(file)
    sampleDuration.value = duration
    sample.value = await uploadVoiceSample(file, duration)
    message.success(sample.value.message || '样本已上传')
  } catch (e: any) {
    sample.value = null
    fileList.value = []
    setError('sample', e?.response?.data?.detail || e?.message || '样本上传失败')
  }
}

function onRemove(): void {
  clearSample()
}

function clearSample(): void {
  sample.value = null
  sampleDuration.value = null
  fileList.value = []
  recordedFile.value = null
  recorder.reset()
}

// ---- 创建音色 ----
async function handleEnroll(): Promise<void> {
  if (!sample.value || !canEnroll.value) return
  enrolling.value = true
  lastError.value = ''
  try {
    record.value = await enrollVoice({
      sample_url: sample.value.url,
      filename: sample.value.name,
      duration: sampleDuration.value,
      authorized_by: userStore.user?.id || '',
      // ★ 原文快照，不做任何改写
      agreement_snapshot: AGREEMENT_TEXT,
      target_model: targetModel.value,
      language_hint: 'zh',
    })
    if (record.value.ready) {
      message.success('音色创建成功')
      previewText.value = record.value.preview_text || config.value?.default_preview_text || ''
    } else {
      message.warning('音色已提交，平台审核中，请稍后刷新状态')
    }
  } catch (e: any) {
    setError('enroll', e?.response?.data?.detail || e?.message || '创建音色失败')
  } finally {
    enrolling.value = false
  }
}

// ---- 状态刷新 / 试听 / 删除 ----
async function refreshStatus(): Promise<void> {
  statusLoading.value = true
  try {
    record.value = await fetchVoiceStatus(true)
    message.success(
      record.value.ready ? '音色已就绪' : `当前远端状态：${record.value.remote_status || '未知'}`,
    )
  } catch (e: any) {
    setError('status', e?.response?.data?.detail || e?.message || '查询状态失败')
  } finally {
    statusLoading.value = false
  }
}

async function handlePreview(): Promise<void> {
  previewing.value = true
  lastError.value = ''
  try {
    const r = await previewVoice(previewText.value, targetModel.value)
    previewUrl.value = r.audio_url
    previewHint.value = r.expires_hint || ''
    previewText.value = r.text
  } catch (e: any) {
    setError('preview', e?.response?.data?.detail || e?.message || '试听合成失败')
  } finally {
    previewing.value = false
  }
}

async function handleDelete(): Promise<void> {
  deleting.value = true
  lastError.value = ''
  try {
    await deleteVoice()
    record.value = { exists: false, status: 'none', ready: false }
    previewUrl.value = ''
    clearSample()
    authorized.value = false
    message.success('音色已删除')
  } catch (e: any) {
    setError('enroll', e?.response?.data?.detail || e?.message || '删除音色失败')
  } finally {
    deleting.value = false
  }
}

// ---- 初始化 ----
onMounted(async () => {
  try {
    config.value = await fetchVoiceConfig()
    targetModel.value = config.value.default_target_model
    previewText.value = config.value.default_preview_text
    record.value = await fetchVoiceStatus()
    if (record.value.preview_text) previewText.value = record.value.preview_text
  } catch (e: any) {
    // ★ 总开关关闭 → 后端 404。这不是「错误」，是模块未启用 → 显示空态
    const status = e?.response?.status
    configError.value =
      status === 404
        ? '语音克隆模块未启用（后端 VOICE_CLONE_ENABLED=false）'
        : e?.response?.data?.detail || e?.message || '模块配置加载失败'
  }
})
</script>

<style scoped>
.voice-clone-panel {
  padding: 0 4px 16px;
}
.vc-alert {
  margin-bottom: 16px;
}
.vc-alert-top {
  margin-top: 12px;
  margin-bottom: 0;
}
.vc-tag {
  margin-left: 8px;
  font-family: monospace;
}
.vc-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
}
.vc-card {
  margin-bottom: 16px;
  background: var(--bg-elevated, transparent);
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: var(--radius-md, 8px);
}
.vc-step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-right: 8px;
  border-radius: 50%;
  background: var(--primary, #1677ff);
  color: #fff;
  font-size: 12px;
}
.vc-badges {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.vc-sample-actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.vc-danger-row {
  /* 与主操作分行摆放：不可逆操作不紧贴 primary，降低误点概率 */
  margin-top: 12px;
}
.vc-audio {
  /* ★ 不要写 `flex: 1`（等价 flex-basis:0%）：本 class 被两个容器复用 ——
     `.vc-sample-actions` 是横向 row（basis 指宽度 ⇒ 正常拉伸），
     `.vc-preview` 是纵向 column（basis 指**高度**）⇒ 播放器被压成 0px 完全隐形。
     实测：音频 HTTP 206 已取到，但 rect.h=0 —— 用户只看到一行文字，读作「没有展示语音」。
     改成 basis:auto + min-height 双保险：横向仍拉伸占满，纵向不再塌。 */
  flex: 1 1 auto;
  min-width: 0;
  min-height: 32px;
  height: 32px;
}
.vc-agreement {
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: var(--radius-sm, 6px);
  background: var(--bg-layout, #fafafa);
  border-left: 3px solid var(--warning, #faad14);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary, #666);
}
.vc-checkbox {
  font-weight: 500;
}
.vc-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary, #999);
  line-height: 1.6;
}
.vc-hint-warn {
  color: var(--warning, #faad14);
}
.vc-preview {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
/* ★ 纵向 column 容器里 `align-items: stretch` 对 audio 这类**替换元素**不生效：
   不加 width 时播放器只有固有宽度 300px，右侧留一大片空白（实测 576 宽容器里只占 300）。 */
.vc-preview .vc-audio {
  width: 100%;
}
/* ---- 跟读录音 ---- */
.vc-rec {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: var(--radius-md, 8px);
  background: var(--bg-layout, #fafafa);
  border: 1px solid var(--border-color, #f0f0f0);
}
.vc-rec-label {
  font-size: 12px;
  color: var(--text-tertiary, #999);
  margin-bottom: 8px;
}
.vc-rec-script {
  font-size: 14px;
  line-height: 2;
  color: var(--text-secondary, #666);
}
.vc-rec-sentence {
  transition: color 0.15s ease;
}
.vc-rec-sentence.is-current {
  color: var(--text-primary, #222);
  font-weight: 500;
  background: var(--primary-bg, rgba(22, 119, 255, 0.12));
  border-radius: 3px;
  padding: 1px 3px;
}
.vc-rec-sentence.is-done {
  color: var(--text-tertiary, #bbb);
}
.vc-rec-bar {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.vc-rec-meter {
  flex: 1;
  min-width: 0;
  height: 6px;
  border-radius: 99px;
  background: var(--border-color, #f0f0f0);
  overflow: hidden;
}
.vc-rec-meter-fill {
  height: 100%;
  border-radius: 99px;
  background: var(--primary, #1677ff);
  transition: width 0.1s linear;
}
.vc-rec-time {
  font-size: 12px;
  font-family: monospace;
  color: var(--text-secondary, #666);
  white-space: nowrap;
}
.vc-rec-actions {
  margin-top: 12px;
}
.vc-upload-wrap {
  margin-top: 4px;
}
.vc-or {
  margin: 14px 0 8px;
  font-size: 12px;
  color: var(--text-tertiary, #999);
  text-align: center;
}
.vc-hint-lead {
  margin: 0 0 8px;
}
</style>
