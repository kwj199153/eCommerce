<template>
  <a-drawer
    :open="visible"
    @update:open="onOpenChange"
    title="记忆与进化"
    :width="640"
    placement="right"
    :closable="true"
    :maskClosable="true"
    class="memory-drawer"
  >
    <!-- 加载中（首次） -->
    <div v-if="loading && !snapshot" class="loading-box">
      <a-spin />
      <span class="loading-text">正在读取长期记忆…</span>
    </div>

    <!-- 读失败：失败必须回写到界面上 -->
    <div v-else-if="loadError" class="section-card error-card">
      <div class="error-title">
        <WarningOutlined /> 长期记忆加载失败
      </div>
      <div class="error-detail">{{ loadError.message }}</div>
      <a-space>
        <a-button size="small" @click="loadAll">
          <ReloadOutlined /> 重试
        </a-button>
        <a-button v-if="loadError.needLogin" size="small" type="primary" @click="goLogin">
          <LoginOutlined /> 去登录
        </a-button>
      </a-space>
    </div>

    <template v-else-if="snapshot">
      <!-- 开关区：生成对话记忆 -->
      <div class="section-card">
        <div class="section-row">
          <div class="section-info">
            <div class="section-label">生成对话记忆</div>
            <div class="section-desc">
              允许 AI 从对话中提取并记住相关上下文，以便在未来对话中提供更连贯、个性化的响应。
              关闭后每晚任务会跳过，注入到对话框的记忆块也会为空。
            </div>
          </div>
          <a-switch
            :checked="enabledLocal === true"
            :loading="savingProfile"
            @change="onToggleAutoMemory"
          />
        </div>
        <div class="section-sub">上次整理：{{ lastDistilledText }}</div>
      </div>

      <!-- 管理记忆：查看 / 编辑 / 重置 / 导入 / 立即整理 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">管理记忆</span>
          <span class="section-hint">每晚自动整理更新，可随时查看和编辑</span>
        </div>
        <div class="memory-actions">
          <a-button size="small" type="primary" ghost :loading="distilling" @click="onDistillNow">
            <SyncOutlined /> 立即整理
          </a-button>
          <a-button danger ghost size="small" :disabled="busy" @click="onResetMemory">
            <ReloadOutlined /> 重置
          </a-button>
          <a-button size="small" :disabled="busy" @click="toggleEdit">
            <EditOutlined /> {{ isEditing ? '取消编辑' : '编辑' }}
          </a-button>
          <a-button size="small" :disabled="busy" @click="onImportMemory">
            <ImportOutlined /> 导入
          </a-button>
          <span class="count-hint">{{ countHint }}</span>
        </div>

        <!-- 上一次「立即整理」的结论（三分支） -->
        <div v-if="distillOutcome" class="distill-panel" :class="distillOutcome.tone">
          <div class="distill-title">{{ distillOutcome.title }}</div>
          <div class="distill-body">{{ distillOutcome.body }}</div>
          <a-button
            v-if="distillOutcome.reason === 'disabled'"
            size="small"
            type="link"
            class="distill-action"
            @click="onToggleAutoMemory(true)"
          >
            去开启「生成对话记忆」
          </a-button>
        </div>

        <!-- 记忆内容展示 / 编辑 -->
        <div class="memory-content-wrapper">
          <textarea
            v-if="isEditing"
            class="memory-editor"
            v-model="editingContent"
            spellcheck="false"
          />
          <div v-else-if="snapshot.markdown" class="memory-view" v-html="renderedMemory"></div>
          <a-empty
            v-else
            class="memory-empty"
            description="还没有任何长期记忆——继续对话后 AI 会归纳你的偏好，也可以点「编辑」自己写"
            :image-style="{ height: '48px' }"
          />
        </div>

        <!-- 编辑态底部操作栏 -->
        <div v-if="isEditing" class="editor-footer">
          <div class="editor-left">
            <span class="editor-hint">直接修改上方内容，点击保存生效</span>
            <div v-if="saveError" class="save-error">
              <WarningOutlined /> {{ saveError }}
            </div>
          </div>
          <a-space>
            <a-button size="small" @click="cancelEdit">取消</a-button>
            <a-button size="small" type="primary" :loading="saving" @click="onSaveMemory">
              <CheckOutlined /> 保存修改
            </a-button>
          </a-space>
        </div>
      </div>

      <!-- 学习时间线 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">学习时间线</span>
          <span class="section-hint">{{ logs.length }} 条记录，按时间倒序</span>
        </div>
        <div v-if="logsError" class="logs-error">
          <WarningOutlined /> {{ logsError }}
          <a-button size="small" type="link" @click="loadLogs">重试</a-button>
        </div>
        <a-timeline v-if="logs.length" class="log-timeline">
          <a-timeline-item
            v-for="log in logs"
            :key="log.id"
            :color="log.is_failure ? 'red' : 'blue'"
          >
            <div class="log-date">
              {{ fmtTime(log.created_at) }}
              <span class="log-kind">{{ KIND_LABEL[log.kind] || log.kind }}</span>
            </div>
            <div class="log-content">{{ log.content }}</div>
            <div v-if="log.is_failure && log.detail && log.detail.error" class="log-error">
              {{ log.detail.error }}
            </div>
          </a-timeline-item>
        </a-timeline>
        <a-empty
          v-else-if="!logsError"
          description="暂无学习记录——继续对话后 AI 会自动归纳你的偏好"
          :image-style="{ height: '48px' }"
        />
      </div>
    </template>

    <!-- 隐藏的文件输入（导入用） -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".md,.txt"
      style="display: none"
      @change="handleFileImport"
    />
  </a-drawer>
</template>

<script setup lang="ts">
/**
 * 记忆与进化（长期记忆）
 *
 * ★★ 这个文件此前是**假页面**（r141 §2.4）
 * ========================================
 * 34 行硬编码的「跨境电商卖家画像」+ 7 条编造的学习日志 + 四个操作全部只改本地
 * `ref` ——「保存」零 API 调用、「重置」只是把 `rawMemory` 赋成一句占位文案、
 * 「开关」只弹一个 toast。而它上方的文案写着**「每晚自动整理更新」**：
 * 界面承诺了一件后端根本没实现的事。
 *
 * 现在六件事都接后端（真源 `backend/modules/memory/router.py`）：
 *   读快照 / 保存整份 / 开关 / 重置 / 时间线 / 立即整理
 *
 * ★★ 四条必须守住的判据（`frontend/scripts/check-memory-reality.cjs` 逐条钉死）
 * =====================================================================
 *  1. **契约对账**：本页调的路径集合必须与后端 router 的端点集合一致。
 *     少一条 = 某个后端能力永远没人用；多一条 = 在调一个不存在的端点。
 *  2. **没有本地假数据**：页面里不得再出现长段编造记忆 / 编造日志。
 *  3. **五个写口都真的发请求**：开关 / 保存 / 导入 / 重置 / 立即整理。
 *  4. **失败必须回写界面状态**：`loadError` / `saveError` / `logsError` 三个
 *     出口各有渲染位置。只弹 toast 是不行的 —— 抽屉里会显示"没有记忆"，
 *     而"没有记忆"与"读不到记忆"对用户是两件完全不同的事
 *     （这条不是洁癖：`/accounts/*` 那次就是"后端有端点、前端零报错"）。
 *
 * ★★ 为什么是抽屉、又为什么默认打开
 * ================================
 * 本组件只有两个挂载方式：`Workspace.vue` 的 `<MemoryEvolution v-model:open>`，
 * 以及路由 `/memory`。后者不传 `open` ⇒ 若按"没传就是关"处理，那条路由
 * 渲染出来是**一张白页**（`a-drawer` 关闭时什么都不显示）。
 * 所以：显式传入 `open` ⇒ 听父组件的（抽屉）；没传 ⇒ 自行打开（页面）。
 *
 * ★ 不写上限常量、不写失败类型名单、不写"每晚几点"：
 *   上限走 `GET /memory` 的 `limits`（后端真源，见 `ai_infra/memory/limits.py`），
 *   失败与否走时间线记录的 `is_failure`（后端算的），"上次整理"走
 *   `profile.last_distilled_at`。前端各抄一份的话，改了后端忘改前端不会有
 *   任何东西变红，而界面会安静地显示错的数字。
 */

import { computed, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import {
  CheckOutlined,
  EditOutlined,
  ImportOutlined,
  LoginOutlined,
  ReloadOutlined,
  SyncOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import {
  distillMemoryNow,
  fetchMemory,
  fetchMemoryLogs,
  resetMemory,
  saveMemory,
  setMemoryEnabled,
  type DistillResult,
  type MemoryLog,
  type MemoryLogKind,
  type MemorySnapshot,
} from '@/api/memory'

const props = defineProps<{
  /** 抽屉可见性。★ 不传（路由模式）时本组件自行打开，见文件头注释。 */
  open?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const router = useRouter()

/**
 * markdown 渲染器。
 *
 * ★ 用本仓**已有**的依赖 `markdown-it`（另有 3 处在用），不是我手写正则替换 ——
 *   手写那版有两个真问题：`- item` 只替换成裸 `<li>`（缺 `<ul>`，是非法 HTML），
 *   而且**完全不转义**。`v-html` 拿到 `import` 进来的 `.md` 或 AI 归纳的文本时，
 *   内容里一个 `<img onerror=...>` 就直接执行了。
 * ★ `html: false` 是显式写出来的默认值：三条来路（手写 / 导入 / AI 归纳）
 *   都不可信，允许裸 HTML 就是给 `v-html` 递刀子。
 */
const md = new MarkdownIt({ html: false })

// ====== 状态 ======

const visible = ref(props.open ?? true)
const snapshot = ref<MemorySnapshot | null>(null)
const logs = ref<MemoryLog[]>([])

const loading = ref(false)
const loadError = ref<{ message: string; needLogin: boolean } | null>(null)
const logsError = ref('')

/** 开关的本地显示值。★ 只由**服务端权威值**写，不由用户点击写。 */
const enabledLocal = ref<boolean | null>(null)
const savingProfile = ref(false)
const saving = ref(false)
const resetting = ref(false)
const importing = ref(false)
const distilling = ref(false)

const isEditing = ref(false)
const editingContent = ref('')
const saveError = ref('')
const distillResult = ref<DistillResult | null>(null)

const fileInputRef = ref<HTMLInputElement | null>(null)

const busy = computed(
  () => saving.value || resetting.value || importing.value || distilling.value,
)

/** 时间线类型的**展示名**。★ 只影响文案，不参与"是不是失败"的判断。 */
const KIND_LABEL: Record<MemoryLogKind, string> = {
  distill: '自动整理',
  distill_failed: '整理失败',
  manual: '手动编辑',
  import: '导入',
  reset: '重置',
}

// ====== 派生 ======

/** ★ 正文必须来自后端快照（空串 = 真的没有内容），不在这里编任何占位文案。 */
const renderedMemory = computed(() => md.render(snapshot.value?.markdown || ''))

const countHint = computed(() => {
  const s = snapshot.value
  if (!s) return ''
  const cap = s.limits?.max_entries
  return cap ? `${s.entry_count} / ${cap} 条` : `${s.entry_count} 条`
})

const lastDistilledText = computed(() => {
  const t = snapshot.value?.profile?.last_distilled_at
  return t ? fmtTime(t) : '尚未整理过'
})

/**
 * 「立即整理」的**三分支**渲染。
 *
 * ★ 后端刻意把三种结局都用 200 返回、靠字段区分（`ran` / `ok`），
 *   因为失败**不是**"请求错误"而是这次整理的**业务结论**：
 *   用 5xx 会让界面落进通用错误分支，用户就只剩一个 toast，
 *   而他需要同时看到"跑过了 + 失败了 + 时间线里有一条记录"。
 * ★ `reason` 是机器可读的原因代码，必须真的用它分支：
 *   开关关着要引导去打开开关（不同结局要给不同的下一步）。
 */
const distillOutcome = computed(() => {
  const r = distillResult.value
  if (!r) return null
  if (!r.ran) {
    return { tone: 'warn', title: '本次没有整理', body: r.content, reason: r.reason }
  }
  if (r.ok) {
    return { tone: 'ok', title: '整理完成', body: r.content, reason: r.reason }
  }
  return { tone: 'bad', title: '整理失败', body: r.error || r.content, reason: r.reason }
})

// ====== 工具 ======

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 后端错误文案优先（400 时是「第几条超了」的人话清单），其次兜底。 */
function detailOf(e: any, fallback: string): string {
  return e?.response?.data?.detail || e?.message || fallback
}

function applySnapshot(snap: MemorySnapshot) {
  snapshot.value = snap
  // ★ 开关值来自服务端权威值，不来自用户点的那一下。
  enabledLocal.value = snap.profile.enabled
}

// ====== 读 ======

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [snap, logResp] = await Promise.all([fetchMemory(), fetchMemoryLogs(30)])
    applySnapshot(snap)
    logs.value = logResp.logs ?? []
  } catch (e: any) {
    loadError.value = {
      message: detailOf(e, '长期记忆加载失败'),
      // 长期记忆按账号归属、fail-closed ⇒ 401 时的下一步是**登录**，要有出口。
      needLogin: e?.response?.status === 401,
    }
    snapshot.value = null
    enabledLocal.value = null
    logs.value = []
  } finally {
    loading.value = false
  }
}

async function loadLogs() {
  try {
    const resp = await fetchMemoryLogs(30)
    logs.value = resp.logs ?? []
    logsError.value = ''
  } catch (e: any) {
    logsError.value = detailOf(e, '学习时间线读取失败')
  }
}

/** 每次写操作都会**新增一条时间线记录**（后端 `_write_log`）⇒ 写后必须重读。 */
async function afterWrite(snap: MemorySnapshot) {
  applySnapshot(snap)
  await loadLogs()
}

// ====== 写：开关 ======

async function onToggleAutoMemory(checked: boolean | string | number) {
  if (typeof checked !== 'boolean' || savingProfile.value) return
  const prev = enabledLocal.value
  savingProfile.value = true
  // 先给即时反馈，但**真正的值**等后端说了算。
  enabledLocal.value = checked
  try {
    const resp = await setMemoryEnabled(checked)
    enabledLocal.value = resp.profile.enabled
    if (snapshot.value) {
      snapshot.value = { ...snapshot.value, profile: resp.profile }
    }
    message.success(
      resp.profile.enabled ? '已开启自动生成对话记忆' : '已关闭自动生成对话记忆',
    )
  } catch (e: any) {
    message.error(detailOf(e, '开关保存失败'))
    // ★ 写失败：不猜。向服务端要一次权威状态；要不到就退回**已知的**上一个值。
    try {
      const snap = await fetchMemory()
      applySnapshot(snap)
    } catch {
      enabledLocal.value = prev
    }
  } finally {
    savingProfile.value = false
  }
}

// ====== 写：保存 / 导入 ======

async function onSaveMemory() {
  if (saving.value) return
  saving.value = true
  saveError.value = ''
  try {
    const snap = await saveMemory(editingContent.value, 'manual')
    await afterWrite(snap)
    isEditing.value = false
    message.success('记忆已保存')
  } catch (e: any) {
    // ★ 400 的 `detail` 是「第几条超了」的人话清单 —— 一个 toast 会把它丢掉，
    //   所以要**留在编辑器里**并内联展示，让用户能照着改。
    saveError.value = detailOf(e, '保存失败')
  } finally {
    saving.value = false
  }
}

function onImportMemory() {
  fileInputRef.value?.click()
}

function handleFileImport(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async () => {
    importing.value = true
    saveError.value = ''
    try {
      // ★ `source='import'`：只有客户端知道这次是"导入文件"还是"手打"，
      //   而后端按来源算权重（手写/导入 = 10，AI 归纳 = 1），
      //   「满了先挤掉谁」取决于它。
      const snap = await saveMemory(reader.result as string, 'import')
      await afterWrite(snap)
      message.success(`已导入记忆文件：${file.name}`)
    } catch (err: any) {
      saveError.value = detailOf(err, '导入失败')
      message.error(detailOf(err, '导入失败'))
    } finally {
      importing.value = false
    }
  }
  reader.readAsText(file)
  input.value = ''
}

function toggleEdit() {
  if (isEditing.value) {
    cancelEdit()
    return
  }
  saveError.value = ''
  editingContent.value = snapshot.value?.markdown || ''
  isEditing.value = true
}

function cancelEdit() {
  isEditing.value = false
  editingContent.value = ''
  saveError.value = ''
}

// ====== 写：重置 ======

function onResetMemory() {
  const n = snapshot.value?.entry_count ?? 0
  Modal.confirm({
    title: '确认重置记忆？',
    content: `将清空当前全部 ${n} 条长期记忆。开关状态会保留（要停止学习请用开关）。此操作不可撤销。`,
    okText: '确认重置',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      resetting.value = true
      try {
        const snap = await resetMemory()
        await afterWrite(snap)
        distillResult.value = null
        message.success('已重置记忆')
      } catch (e: any) {
        message.error(detailOf(e, '重置失败'))
      } finally {
        resetting.value = false
      }
    },
  })
}

// ====== 写：立即整理 ======

async function onDistillNow() {
  if (distilling.value) return
  distilling.value = true
  try {
    const resp = await distillMemoryNow()
    // ★ 后端同时返回了「做完之后的快照」⇒ 直接用它，不再补一次 GET。
    //   补 GET 的那段时间里界面是旧的，用户会以为没成功而再点一次（= 再烧一次钱）。
    snapshot.value = resp.memory
    enabledLocal.value = resp.memory.profile.enabled
    distillResult.value = resp.result
    await loadLogs()
    const r = resp.result
    if (!r.ran) message.warning(r.content || '本次没有整理')
    else if (r.ok) message.success(r.content || '整理完成')
    else message.error(r.error || '整理失败')
  } catch (e: any) {
    // 真正的请求级失败（网络 / 配额 429 / 401）：这一条也要说出来，
    // 否则用户看到的是"点了没反应"。
    message.error(detailOf(e, '整理请求失败'))
  } finally {
    distilling.value = false
  }
}

function goLogin() {
  router.push({ name: 'Login', query: { redirect: '/memory' } })
}

function onOpenChange(val: boolean) {
  visible.value = val
  emit('update:open', val)
}

// ====== 生命周期 ======

// 抽屉模式：父组件给 `open` ⇒ 打开时才请求（关着也请求会白烧一次往返）。
watch(
  () => props.open,
  (v) => {
    if (typeof v === 'boolean') visible.value = v
  },
)

watch(
  visible,
  (v) => {
    if (v) loadAll()
  },
  { immediate: true },
)
</script>

<style scoped>
/* 加载中 */
.loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-40) 0;
}
.loading-text {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

/* 区块卡片 */
.section-card {
  background-color: var(--bg-hover-light);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  padding: var(--space-14) var(--space-16);
  margin-bottom: var(--space-12);
}
/* 开关行 */
.section-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-12);
}
.section-info { flex: 1; min-width: 0; }
.section-label {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}
.section-desc {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  line-height: 1.5;
}
.section-sub {
  margin-top: var(--space-10);
  padding-top: var(--space-8);
  border-top: 1px solid var(--border-base);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* 管理记忆头部 */
.section-header {
  display: flex;
  align-items: baseline;
  gap: var(--space-8);
  margin-bottom: var(--space-10);
}
.section-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.section-hint {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* 操作按钮行 */
.memory-actions {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-10);
  flex-wrap: wrap;
}
.count-hint {
  margin-left: auto;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* 「立即整理」结论面板 */
.distill-panel {
  border-radius: var(--radius-6);
  padding: var(--space-10) var(--space-12);
  margin-bottom: var(--space-10);
  border: 1px solid var(--border-base);
  background: var(--bg-base);
}
.distill-panel.ok { border-color: var(--success-border); background: var(--success-bg); }
.distill-panel.bad { border-color: var(--danger-border); background: var(--danger-bg); }
.distill-panel.warn { border-color: var(--warning-border); background: var(--warning-bg); }
.distill-title {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-3);
}
.distill-body {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  line-height: 1.6;
  word-break: break-word;
}
.distill-action { padding: 0; height: auto; margin-top: var(--space-4); }

/* 记忆内容区 */
.memory-content-wrapper {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  overflow: hidden;
}
.memory-view {
  padding: var(--space-12) var(--space-14);
  font-size: var(--font-size-12-5);
  line-height: 1.7;
  color: var(--text-primary);
  max-height: 380px;
  overflow-y: auto;
  word-break: break-word;
}
.memory-view :deep(h1) {
  font-size: var(--font-size-15); font-weight: 700; margin: var(--space-6) 0 var(--space-3);
  color: var(--text-primary);
}
.memory-view :deep(h2) {
  font-size: var(--font-size-14); font-weight: 600; margin: var(--space-8) 0 var(--space-3);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-base); padding-bottom: var(--space-3);
}
.memory-view :deep(h3) {
  font-size: var(--font-size-13); font-weight: 600; margin: var(--space-6) 0 var(--space-2);
  color: var(--text-secondary);
}
.memory-view :deep(ul) { margin: var(--space-2) 0 var(--space-4); padding-left: var(--space-20); }
.memory-view :deep(li) { margin-bottom: var(--space-1); }
.memory-view :deep(p) { margin-bottom: var(--space-3); }
.memory-view :deep(code) {
  background: var(--bg-card-pill); padding: var(--space-1) var(--space-4); border-radius: var(--radius-3);
  font-size: var(--font-size-11-5); font-family: SFMono-Regular, Consolas, monospace;
}
.memory-empty { padding: var(--space-20) 0; }

.memory-editor {
  width: 100%;
  min-height: 300px;
  max-height: 420px;
  padding: var(--space-12) var(--space-14);
  border: none;
  outline: none;
  resize: vertical;
  font-size: var(--font-size-12-5);
  line-height: 1.65;
  font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
  background: transparent;
  color: var(--text-primary);
  box-sizing: border-box;
}

/* 编辑器底栏 */
.editor-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-12);
  margin-top: var(--space-8);
  padding-top: var(--space-8);
  border-top: 1px solid var(--border-base);
}
.editor-left { flex: 1; min-width: 0; }
.editor-hint { font-size: var(--font-size-11); color: var(--text-tertiary); }
.save-error {
  margin-top: var(--space-4);
  font-size: var(--font-size-11-5);
  color: var(--danger);
  line-height: 1.5;
  word-break: break-word;
}

/* 工作日志时间线 */
.log-timeline { margin-top: var(--space-2); padding-left: var(--space-2); }
.log-date { font-size: var(--font-size-11-5); font-weight: 600; color: var(--text-primary); }
.log-kind {
  margin-left: var(--space-6);
  font-weight: 400;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.log-content { font-size: var(--font-size-12); color: var(--text-secondary); line-height: 1.5; margin-top: var(--space-1); }
.log-error {
  margin-top: var(--space-3);
  font-size: var(--font-size-11-5);
  color: var(--danger);
  line-height: 1.5;
  word-break: break-word;
}
.logs-error {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  font-size: var(--font-size-11-5);
  color: var(--danger);
  margin-bottom: var(--space-8);
}

/* 读失败卡片 */
.error-card { border-color: var(--danger-border); background: var(--danger-bg); }
.error-title {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--danger);
  margin-bottom: var(--space-6);
}
.error-detail {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: var(--space-10);
  word-break: break-word;
}

/* Drawer 标题样式覆盖 */
:deep(.ant-drawer-header) {
  border-bottom: 1px solid var(--border-base);
  padding: var(--space-14) var(--space-20);
}
:deep(.ant-drawer-title) {
  font-size: var(--font-size-16);
  font-weight: 600;
}
:deep(.ant-drawer-body) {
  padding: var(--space-16) var(--space-18);
  background-color: var(--bg-base);
}
</style>
