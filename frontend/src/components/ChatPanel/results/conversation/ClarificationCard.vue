<template>
  <!--
    澄清提问卡（HITL「问」的那一半，第 400 轮 P0-3）。

    数据来源：`ask_clarification` 在工具内部调 `interrupt()`，图停在**那一步**。
    店秘书的正文取口（`_digest_graph_state`）把中断读成：

      { display_type: "clarification_request",
        clarification: { type, question, options:[{label,description?,recommended?}],
                         missing_fields, agent, session_id } }

    正文（气泡）里已经是**那个问题**，所以这张卡只负责「怎么答」——
    不再重复一遍问题。这样即使卡片渲染不出来，老板也读得到要回答什么
    （「卡片没出来 ⇒ 什么都没显示」是最糟的降级）。

    ★ 回答回到的是 `POST /agents/{agent}/approval/resume`（与审批同一个通道）：
      「图停住了要人」是同一套机制，只有续跑值的形状不同 ——
      而形状由**服务端**看图判断（`_pending_kind`），不由前端声明。
  -->
  <ConversationCard
    icon="💬"
    title="需要你补充一句"
    :badge="badge"
    badge-color="blue"
    :note="done ? '已提交，正在继续' : ''"
  >
    <div class="cl-note">
      回答之后我会接着这一步继续做，不用你重新说一遍需求。
    </div>

    <!-- 候选项：后端给了才显示（能点选就别让老板手打） -->
    <div
      v-if="options.length"
      class="cl-options"
    >
      <button
        v-for="(o, i) in options"
        :key="i"
        type="button"
        class="cl-option"
        :class="{ 'is-active': answer === o.label, 'is-rec': o.recommended }"
        :disabled="done || submitting"
        @click="pick(o.label)"
      >
        <span class="cl-option-label">{{ o.label }}</span>
        <span
          v-if="o.recommended"
          class="cl-option-rec"
        >推荐</span>
        <span
          v-if="o.description"
          class="cl-option-desc"
        >{{ o.description }}</span>
      </button>
    </div>

    <a-textarea
      v-model:value="answer"
      class="cl-input"
      :rows="2"
      :maxlength="500"
      placeholder="也可以直接写你的答案…"
      :disabled="done || submitting"
      @press-enter.prevent="submit"
    />

    <div
      v-if="error"
      class="cl-error"
    >
      {{ error }}
    </div>

    <template #footer>
      <a-button
        type="primary"
        size="small"
        :loading="submitting"
        :disabled="done || !answer.trim()"
        @click="submit"
      >
        提交回答
      </a-button>
    </template>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'

import ConversationCard from './ConversationCard.vue'
import { submitClarificationAnswer } from '@/composables/useApprovalFlow'

const props = defineProps<{ data: any }>()

interface Opt { label: string; description?: string; recommended?: boolean }

/**
 * 选项归一。
 * ★ 后端已经统一成对象形态（`normalize_options`），但这里仍然容忍裸字符串：
 *   老 payload / 手写测试数据里还有字符串数组，渲染成 `[object Object]` 的反面
 *   —— 把字符串当对象读会得到 `undefined.label` ⇒ 三个空按钮。
 *   一处归一，两处都省心。
 */
const options = computed<Opt[]>(() =>
  (props.data?.options || [])
    .map((o: any) => (typeof o === 'string' ? { label: o } : o))
    .filter((o: any) => o && typeof o.label === 'string' && o.label.trim()),
)

const missing = computed<string[]>(() => props.data?.missing_fields || [])
const badge = computed<string>(() => (missing.value.length ? `缺 ${missing.value.join(' / ')}` : ''))
/** 会话 ID：后端下发在 data.session_id（服务端填，前端不猜） */
const sessionId = computed<string>(() => props.data?.session_id || '')

const answer = ref('')
const submitting = ref(false)
const done = ref(false)
const error = ref('')

function pick(label: string) {
  if (done.value || submitting.value) return
  answer.value = label
  error.value = ''
}

async function submit() {
  // ★ 幂等：一次提问只提交一次。重复提交会让同一张被冻结的图恢复两次
  //   （第二次必然拿到错的结果，而且界面上看不出发生过两次）。
  if (submitting.value || done.value) return
  const text = answer.value.trim()
  if (!text) {
    error.value = '请先写一句回答，或点上面的候选项。'
    return
  }
  submitting.value = true
  error.value = ''
  const res = await submitClarificationAnswer({
    sessionId: sessionId.value,
    agentId: props.data?.agent || undefined,
    answer: text,
  })
  submitting.value = false
  // ★ 只在**真的提交成功**时进入终态 —— 失败留在可重试的样子上。
  if (res.ok) {
    done.value = true
    message.success('已提交，继续处理中')
  } else {
    error.value = res.message
  }
}
</script>

<style scoped>
.cl-note {
  line-height: 1.6;
  color: var(--text-secondary);
}
.cl-options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
  margin-top: var(--space-8);
}
.cl-option {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-4) var(--space-10);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background: var(--bg-base);
  color: var(--text-primary);
  font-size: var(--font-size-12);
  cursor: pointer;
}
.cl-option:hover:not(:disabled) {
  border-color: var(--primary);
}
.cl-option.is-active {
  border-color: var(--primary);
  background: var(--info-bg);
}
.cl-option:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.cl-option-rec {
  font-size: var(--font-size-10);
  color: var(--primary-strong);
  border: 1px solid currentColor;
  border-radius: var(--radius-4);
  padding: 0 4px;
}
.cl-option-desc {
  color: var(--text-tertiary);
  font-size: var(--font-size-11);
}
.cl-input {
  margin-top: var(--space-8);
}
.cl-error {
  margin-top: var(--space-6);
  color: var(--danger-strong);
  font-size: var(--font-size-11);
}
</style>
