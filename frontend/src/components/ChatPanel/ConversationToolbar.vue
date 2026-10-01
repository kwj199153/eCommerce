<template>
  <div class="conv-toolbar">
    <!-- ① 查找：在当前 Agent 的对话里按关键词定位消息，点结果即滚到那一条 -->
    <a-popover
      v-model:open="findOpen"
      trigger="click"
      placement="bottomRight"
      overlay-class-name="conv-toolbar-pop"
      :overlay-style="{ width: '380px' }"
    >
      <template #content>
        <div class="ctp">
          <div class="ctp-head">
            <SearchOutlined class="ctp-head-icon" />
            <input
              ref="findInputRef"
              v-model="findQuery"
              class="ctp-input"
              type="text"
              placeholder="在本次对话中查找…"
              @keydown.esc="findOpen = false"
            >
            <span
              v-if="findQuery.trim()"
              class="ctp-count"
            >{{ findRows.length }} 条</span>
          </div>
          <div class="ctp-list">
            <p
              v-if="!hasMessages"
              class="ctp-empty"
            >
              本次对话还没有内容
            </p>
            <p
              v-else-if="!findRows.length"
              class="ctp-empty"
            >
              没有包含「{{ findQuery.trim() }}」的消息
            </p>
            <template v-else>
              <button
                v-for="row in findRows"
                :key="row.index"
                type="button"
                class="ctp-row"
                @click="jumpTo(row.index)"
              >
                <span
                  class="ctp-role"
                  :class="row.role"
                >{{ row.role === 'user' ? '我' : 'AI' }}</span>
                <span
                  class="ctp-snippet"
                  v-html="row.snippet"
                />
              </button>
            </template>
          </div>
        </div>
      </template>
      <button
        type="button"
        class="ct-btn"
        :class="{ 'is-open': findOpen }"
        title="查找对话内容"
      >
        <SearchOutlined />
      </button>
    </a-popover>

    <!-- ② 分享：复制为 Markdown / 下载 .md（没有对话时禁用，不留一个点了没反应的按钮） -->
    <a-dropdown
      trigger="click"
      placement="bottomRight"
    >
      <template #overlay>
        <a-menu @click="onShare">
          <a-menu-item
            key="copy"
            :disabled="!hasMessages"
          >
            <CopyOutlined />
            <span class="ctm-label">复制为 Markdown</span>
          </a-menu-item>
          <a-menu-item
            key="download"
            :disabled="!hasMessages"
          >
            <DownloadOutlined />
            <span class="ctm-label">下载 .md 文件</span>
          </a-menu-item>
        </a-menu>
      </template>
      <button
        type="button"
        class="ct-btn"
        :disabled="!hasMessages"
        :title="hasMessages ? '分享对话记录' : '暂无对话可分享'"
      >
        <ShareAltOutlined />
      </button>
    </a-dropdown>

    <!-- ③ 历史提问：只列「我问过什么」，最新的在最上面 -->
    <a-popover
      v-model:open="historyOpen"
      trigger="click"
      placement="bottomRight"
      overlay-class-name="conv-toolbar-pop"
      :overlay-style="{ width: '380px' }"
    >
      <template #content>
        <div class="ctp">
          <div class="ctp-head">
            <HistoryOutlined class="ctp-head-icon" />
            <span class="ctp-head-title">历史提问</span>
            <span class="ctp-count">{{ questions.length }} 条</span>
          </div>
          <div class="ctp-list">
            <p
              v-if="!questions.length"
              class="ctp-empty"
            >
              本次对话还没有提问
            </p>
            <template v-else>
              <button
                v-for="q in questions"
                :key="q.index"
                type="button"
                class="ctp-row"
                @click="jumpTo(q.index)"
              >
                <span class="ctp-no">{{ q.no }}</span>
                <span class="ctp-q">{{ q.text }}</span>
                <span
                  v-if="q.time"
                  class="ctp-time"
                >{{ q.time }}</span>
              </button>
            </template>
          </div>
        </div>
      </template>
      <button
        type="button"
        class="ct-btn"
        :class="{ 'is-open': historyOpen }"
        title="历史提问"
      >
        <HistoryOutlined />
      </button>
    </a-popover>
  </div>
</template>

<script setup lang="ts">
/**
 * 对话窗口右上角的「查找 / 分享 / 历史提问」工具条（第 283 轮）。
 *
 * ★ 为什么是一个独立组件、而不是在 `Workspace.vue` 的 header 里内联三块：
 *   三者的**数据源是同一个** —— 当前 Agent 的对话消息（`chatStore.messages`）。
 *   内联会让「消息怎么取、怎么转文本、怎么跳转」这三件事散进 1,139 行的布局文件里；
 *   而它们与布局无关，只与对话有关。
 *
 * ★ 数据不经过 props：工具栏渲染在 Workspace 的顶栏，而 `chatStore` 是全局单例，
 *   `messages` 又是按 `activeAgentId` 分片的 computed ⇒ 直接读就是**同一份**，
 *   不需要再开一条 props 通道（多一条通道就多一处会漂移的拷贝）。
 *
 * ★ 「跳转到某条消息」必须走 window 事件：滚动容器与消息 DOM 都住在 `ChatPanel`，
 *   那才是唯一能算准落点的地方。这里只负责**说清楚要跳哪一条**（消息在数组里的下标），
 *   与 `view-navigate` / `tool-analysis` 的既有风格一致。
 *   ⚠️ 下标必须用**消息数组的下标**，不能用 DOM 序号 —— 工具结果消息与文本消息
 *   在模板里是两套分支，按 DOM 数会错位。
 *
 * ★ 高亮片段一律 `escapeHtml` 之后再插 `<mark>`：消息正文里可能有 `<img onerror=…>`，
 *   直接 `v-html` 就是自造 XSS 通道（内容来源是用户输入 + 模型输出，都不可信）。
 */
import { ref, computed, watch, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import {
  SearchOutlined,
  ShareAltOutlined,
  HistoryOutlined,
  CopyOutlined,
  DownloadOutlined,
} from '@ant-design/icons-vue'

import { useAgentStore } from '@/stores/agent'
import { useChatStore, type Message } from '@/stores/chat'

const agentStore = useAgentStore()
const chatStore = useChatStore()

const findOpen = ref(false)
const historyOpen = ref(false)
const findQuery = ref('')
const findInputRef = ref<HTMLInputElement>()

/** 当前 Agent 的对话消息（与 ChatPanel 同源：同一 store、同一分片规则） */
const messages = computed<Message[]>(() => chatStore.messages)
const hasMessages = computed(() => messages.value.length > 0)

/** Agent 名：分享内容与文件名都要带，避免导出多个 Agent 的对话后分不清 */
const agentName = computed(() => agentStore.currentAgent?.name || '对话')

// ===== 文本工具（转义 / 摘要 / 高亮）=====

const HTML_ESCAPE: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => HTML_ESCAPE[c] ?? c)
}

/** 压平换行 + 截断：列表行只做「认得出是哪条」，完整内容点进去看 */
function preview(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

/** 关键词高亮：先转义**原文**，再插 `<mark>`（顺序反了就是把用户输入当 HTML 执行） */
function highlight(text: string, kw: string): string {
  const safe = escapeHtml(text)
  if (!kw) return safe
  const pattern = escapeHtml(kw).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return safe.replace(new RegExp(pattern, 'gi'), (m) => `<mark class="ctp-mark">${m}</mark>`)
}

/** 消息的可搜索文本：工具结果卡没有正文，给一个可识别的占位而不是空串 */
function msgText(m: Message): string {
  if (m.content) return m.content
  if (m.displayType === 'tool_result') return '（工具结果卡）'
  return ''
}

// ===== ① 查找 =====

interface FindRow {
  index: number
  role: 'user' | 'assistant'
  snippet: string
}

/** 空关键词 = 列出全部消息（可当"跳转到某条"的目录用），有关键词才过滤 */
const findRows = computed<FindRow[]>(() => {
  const kw = findQuery.value.trim()
  const rows: FindRow[] = []
  messages.value.forEach((m, index) => {
    const text = msgText(m)
    if (!text) return
    if (!kw) {
      rows.push({ index, role: m.role, snippet: escapeHtml(preview(text, 56)) })
      return
    }
    const at = text.toLowerCase().indexOf(kw.toLowerCase())
    if (at < 0) return
    // 命中处前后各留一段上下文，命中的词本身一定在窗口内
    const start = Math.max(0, at - 20)
    const slice = (start > 0 ? '…' : '') + text.slice(start, at + kw.length + 48)
    rows.push({ index, role: m.role, snippet: highlight(slice, kw) })
  })
  return rows
})

watch(findOpen, (open) => {
  if (open) nextTick(() => findInputRef.value?.focus())
  else findQuery.value = ''
})

// ===== ③ 历史提问 =====

interface QuestionRow {
  index: number
  no: number
  text: string
  time: string
}

/** 倒序（最新的在最上面）：找"我刚才问的那句"永远是从上往下找 */
const questions = computed<QuestionRow[]>(() => {
  const rows: QuestionRow[] = []
  let no = 0
  messages.value.forEach((m, index) => {
    if (m.role !== 'user') return
    const text = (m.content || '').trim()
    if (!text) return
    no += 1
    rows.push({
      index,
      no,
      text: preview(text, 64),
      time: m.timestamp ? dayjs(m.timestamp).format('HH:mm') : '',
    })
  })
  return rows.reverse()
})

// ===== 跳转 =====

/** 先关面板再跳：面板挡住对话区时滚动看不出来，用户会以为点了没反应 */
function jumpTo(index: number) {
  findOpen.value = false
  historyOpen.value = false
  nextTick(() => {
    window.dispatchEvent(new CustomEvent('chat-scroll-to-message', { detail: { index } }))
  })
}

// ===== ② 分享 =====

/** 导出成 Markdown：能直接粘进周报 / 工单，比截图更可检索 */
function buildMarkdown(): string {
  const lines = [
    `# ${agentName.value} · 对话记录`,
    '',
    `> 导出时间：${dayjs().format('YYYY-MM-DD HH:mm')} · 共 ${messages.value.length} 条`,
    '',
  ]
  for (const m of messages.value) {
    lines.push(m.role === 'user' ? '## 我' : `## ${agentName.value}`)
    lines.push('')
    lines.push(msgText(m) || '（无正文）')
    lines.push('')
  }
  return lines.join('\n')
}

/**
 * 复制到剪贴板：`navigator.clipboard` 只在安全上下文（https / localhost）可用，
 * 局域网 IP 访问的部署下它是 `undefined` ⇒ 必须留 execCommand 这条降级路，
 * 否则「点了没反应」而调用方还以为成功了。
 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 落到下面的降级实现
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function downloadMarkdown() {
  const blob = new Blob([buildMarkdown()], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${agentName.value}-对话记录-${dayjs().format('YYYYMMDD-HHmm')}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function onShare({ key }: { key: string | number }) {
  if (key === 'copy') {
    const ok = await copyText(buildMarkdown())
    // 成功提示归调用点（拦截器不发）；失败必须说清楚，不能静默
    if (ok) message.success('对话已复制为 Markdown')
    else message.error('复制失败（当前环境不允许访问剪贴板），请改用「下载 .md 文件」')
    return
  }
  if (key === 'download') {
    downloadMarkdown()
    message.success('已开始下载对话记录')
  }
}
</script>

<style scoped>
.conv-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  /* 与右侧既有的面板按钮 / 模式切换拉开距离：这三个是「对话操作」，
     后面那些是「面板 / 通知」，挤在一起会被读成同一组。 */
  margin-right: var(--space-12);
  flex-shrink: 0;
}

/* 图标按钮：无边框、hover 才出底 —— 与顶栏既有的 text 按钮同一种安静风格 */
.ct-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-8);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-16);
  line-height: 1;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.ct-btn:hover:not(:disabled) {
  background: var(--bg-hover-light);
  color: var(--text-primary);
}

/* 打开态：面板开着时按钮要"亮着"，否则用户不知道这个气泡是从哪冒出来的 */
.ct-btn.is-open {
  background: var(--bg-active-light);
  color: var(--primary);
}

.ct-btn:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

/* 分享菜单项图标与文字的间距（antd 默认只给图标的右边距，中文标签下太挤） */
.ctm-label {
  margin-left: var(--space-6);
}

/* 面板内部样式住在 styles/popup.css —— popover 被 teleport 到 body，
   scoped 的 [data-v-*] 选择器够不到，写在这里会**静默失效**。 */
</style>
