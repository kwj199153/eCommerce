<template>
  <!--
    人工审批卡（HITL，第 131 轮 · item2-C）。

    数据来源：后端在被 `interrupt()` 挂起时通过 SSE `meta` 下发
    `display_type = "pending_approval"`，data 形如：

      { type: "pending_approval",
        approval: { interrupt_id, action, args, require_reason,
                    timeout_seconds, description },
        session_id }

    契约的**唯一真源**是后端 `_pending_approval_from_interrupt()`。
    这里只消费，不推断、不编造缺失字段（缺失就退化隐藏对应区块）。

    ★ 刻意不显示 / 不使用 thread_id：服务端按（命名空间, 用户, 会话）重算，
      客户端只要把同一个 session_id 交回来即可。
  -->
  <ConversationCard
    icon="⚠️"
    title="需要人工审批"
    :badge="actionLabel"
    badge-color="orange"
    :note="decidedText"
  >
    <div class="pa-note">
      {{
        description ||
        `这一步会真正执行「${actionLabel}」，在批准之前它不会被执行。`
      }}
    </div>

    <!-- 将写入的参数：后端真有才显示，没有就整块隐藏 -->
    <div v-if="argEntries.length" class="pa-args">
      <div class="pa-args-title">将执行的参数</div>
      <div v-for="[k, v] in argEntries" :key="k" class="pa-arg">
        <span class="pa-arg-k">{{ k }}</span>
        <span class="pa-arg-v">{{ formatValue(v) }}</span>
      </div>
    </div>

    <!-- 决策区：做出决策后收起，改为终态文案 -->
    <div v-if="!decided" class="pa-actions">
      <a-button
        type="primary"
        size="small"
        :loading="submitting"
        :disabled="submitting"
        @click="decide('accept')"
      >
        批准执行
      </a-button>
      <a-button size="small" danger :disabled="submitting" @click="toggle('reject')">
        拒绝
      </a-button>
      <a-button size="small" :disabled="submitting" @click="toggle('edit')">
        改写后执行
      </a-button>
      <a-button size="small" :disabled="submitting" @click="toggle('response')">
        直接回复
      </a-button>
    </div>

    <!-- 拒绝原因（decision=reject） -->
    <div v-if="panel === 'reject' && !decided" class="pa-panel">
      <a-textarea
        v-model:value="reason"
        :rows="2"
        placeholder="拒绝原因（会展示给模型与用户）"
      />
      <a-button type="primary" size="small" danger :loading="submitting" @click="decide('reject')">
        确认拒绝
      </a-button>
    </div>

    <!-- 改写入参（decision=edit）：args 是双层，后端会把它当工具入参再执行 -->
    <div v-if="panel === 'edit' && !decided" class="pa-panel">
      <a-textarea v-model:value="argsDraft" :rows="5" placeholder="改写后的工具入参（JSON）" />
      <a-button type="primary" size="small" :loading="submitting" @click="decide('edit')">
        确认并执行
      </a-button>
    </div>

    <!-- 直接回复（decision=response）：不执行操作，把 feedback 当回复 -->
    <div v-if="panel === 'response' && !decided" class="pa-panel">
      <a-textarea
        v-model:value="feedback"
        :rows="3"
        placeholder="不执行该操作，改为直接回复这段内容"
      />
      <a-button type="primary" size="small" :loading="submitting" @click="decide('response')">
        确认回复
      </a-button>
    </div>

    <div v-if="formError" class="pa-err">{{ formError }}</div>
    <div v-if="decided" class="pa-decided">{{ decidedText }}</div>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'

import ConversationCard from './ConversationCard.vue'
import { submitApprovalDecision, type ApprovalDecision } from '@/composables/useApprovalFlow'

const props = defineProps<{ data: any }>()

const approval = computed<any>(() => props.data?.approval || {})
const actionLabel = computed<string>(() => approval.value?.action || '未知操作')
const description = computed<string>(() => approval.value?.description || '')
/** 会话 ID：后端下发在 data.session_id（兼容 camelCase 以防后端改名） */
const sessionId = computed<string>(() => props.data?.session_id || props.data?.sessionId || '')
const requireReason = computed<boolean>(() => !!approval.value?.require_reason)

const argEntries = computed<Array<[string, any]>>(() =>
  Object.entries(approval.value?.args || {}) as Array<[string, any]>,
)

const submitting = ref(false)
const decided = ref<ApprovalDecision | null>(null)
const panel = ref<'' | ApprovalDecision>('')
const reason = ref('')
const feedback = ref('')
const argsDraft = ref('')
const formError = ref('')

/** 决策 → 终态文案（与后端四档一一对应） */
const DECIDED_TEXT: Record<ApprovalDecision, string> = {
  accept: '已批准执行',
  reject: '已拒绝执行',
  edit: '已改写并执行',
  response: '已直接回复',
}
const decidedText = computed(() => (decided.value ? DECIDED_TEXT[decided.value] : ''))

function formatValue(v: any): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function toggle(p: ApprovalDecision) {
  if (submitting.value || decided.value) return
  formError.value = ''
  if (p === 'edit' && panel.value !== 'edit') {
    argsDraft.value = JSON.stringify(approval.value?.args || {}, null, 2)
  }
  panel.value = panel.value === p ? '' : p
}

async function decide(d: ApprovalDecision) {
  // ★ 幂等：一次审批只提交一次。
  //   重复点击会让同一张被冻结的图被恢复两次（第二次必然拿到错的结果）。
  if (submitting.value || decided.value) return
  formError.value = ''

  let payloadArgs: Record<string, any> | undefined
  if (d === 'edit') {
    try {
      payloadArgs = JSON.parse(argsDraft.value || '{}')
    } catch {
      formError.value = '入参不是合法 JSON，请修正后再提交。'
      return
    }
    if (!payloadArgs || !Object.keys(payloadArgs).length) {
      formError.value = '改写后的入参不能为空。'
      return
    }
  }
  if (d === 'response' && !feedback.value.trim()) {
    formError.value = '直接回复的内容不能为空。'
    return
  }
  if (d === 'reject' && requireReason.value && !reason.value.trim()) {
    formError.value = '这次操作要求填写拒绝原因。'
    return
  }

  submitting.value = true
  const res = await submitApprovalDecision({
    sessionId: sessionId.value,
    decision: d,
    reason: d === 'reject' ? reason.value.trim() || undefined : undefined,
    args: payloadArgs,
    feedback: d === 'response' ? feedback.value.trim() : undefined,
  })
  submitting.value = false

  // ★ 只在**真的提交成功**时进入终态。
  //   失败时留在可重试的样子上 —— 否则卡片显示「已批准」而操作没执行。
  if (res.ok) {
    decided.value = d
    panel.value = ''
    message.success(DECIDED_TEXT[d])
  } else {
    message.error(res.message)
  }
}
</script>

<style scoped>
.pa-note {
  line-height: 1.6;
  color: var(--text-secondary);
}
.pa-args {
  margin-top: var(--space-8);
  border-top: 1px dashed var(--border-base);
  padding-top: var(--space-6);
}
.pa-args-title {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-bottom: var(--space-4);
}
.pa-arg {
  display: flex;
  gap: var(--space-8);
  font-size: var(--font-size-11);
  line-height: 1.7;
}
.pa-arg-k {
  flex: 0 0 auto;
  min-width: 96px;
  color: var(--text-tertiary);
}
.pa-arg-v {
  flex: 1 1 auto;
  color: var(--text-primary);
  word-break: break-all;
}
.pa-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
  margin-top: var(--space-10);
}
.pa-panel {
  margin-top: var(--space-10);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  align-items: flex-start;
}
.pa-err {
  margin-top: var(--space-6);
  font-size: var(--font-size-11);
  color: var(--danger);
}
.pa-decided {
  margin-top: var(--space-8);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
</style>
