<template>
  <!--
    提示词增强（星星按钮）—— 全站唯一实现。

    ★ 为什么必须是唯一实现：这个按钮的**语义**（怎么判「能不能点」、失败了要不要覆盖、
      成功文案说什么）全在后端 `_ENHANCE_PROMPT_SYSTEM` 的契约上。复制一份到别处，
      两份就会各自漂移（典型：一处判 degraded、一处直接赋值 ⇒ 后端降级时把用户原稿清空）。
    ★ `context` 是**活参数**：后端把它拼进 LLM 提示词（`业务上下文：{context}`），
      所以同一个按钮可以服务不同业务域 —— 传业务名，别传 UI 位置名。
  -->
  <a-tooltip :title="tip">
    <button
      class="prompt-enhance-btn"
      :class="[`is-${size}`]"
      :disabled="busy || !draft"
      :aria-label="tip"
      @click="handleEnhance"
    >
      <LoadingOutlined v-if="busy" />
      <svg
        v-else
        class="sparkle-icon"
        viewBox="0 0 22 22"
        :width="iconSize"
        :height="iconSize"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M9 3 C9.36 7.2 9.8 7.64 14 8 C9.8 8.36 9.36 8.8 9 13 C8.64 8.8 8.2 8.36 4 8 C8.2 7.64 8.64 7.2 9 3 Z" />
        <path d="M17 12.5 C17.2 14.8 17.45 15.05 19.75 15.25 C17.45 15.45 17.2 15.7 17 18 C16.8 15.7 16.55 15.45 14.25 15.25 C16.55 15.05 16.8 14.8 17 12.5 Z" />
      </svg>
    </button>
  </a-tooltip>
</template>

<script setup lang="ts">
/**
 * 提示词增强按钮（星星）—— 输入框 / 文本框旁的「把草稿扩写得更可执行」入口。
 *
 * 契约（与后端 `AIGCAgent.enhance_prompt` 对齐，改动前先看后端）：
 * 1. **不替用户做决定**：只改文案，不自动提交、不触发任何任务。
 * 2. **降级不覆盖**：后端 `degraded=true` 或 `enhanced` 为空 ⇒ 保留用户原稿 + 给 warning。
 *    「空状态优于虚构默认」是老板定的口径，这里不许改成「清空输入框」。
 * 3. **失败要说人话**：网络异常同样走 warning，不静默吞掉。
 */
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { LoadingOutlined } from '@ant-design/icons-vue'

import { enhancePrompt } from '@/api/aigcMedia'

const props = withDefaults(
  defineProps<{
    /** 当前草稿（v-model） */
    modelValue: string
    /**
     * 业务上下文，拼进 LLM 提示词。默认 `ecommerce`（与原对话框行为一致）。
     * 例：`ecommerce` / `aigc-image` / `video-script` / `skill-authoring`。
     */
    context?: string
    /** md = 28px（对话框内）；sm = 22px（表单 label 旁） */
    size?: 'md' | 'sm'
  }>(),
  {
    context: 'ecommerce',
    size: 'md',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  /** 增强成功，便于调用方做后续处理（如高亮 / 计数） */
  (e: 'enhanced', value: string): void
}>()

const busy = ref(false)

const draft = computed(() => (props.modelValue || '').trim())

const iconSize = computed(() => (props.size === 'sm' ? 13 : 16))

const tip = computed(() => {
  if (busy.value) return '正在增强…'
  if (!draft.value) return '先写一句需求，再点这里增强'
  return '增强提示词：补齐任务目标 / 约束条件 / 输出形式'
})

async function handleEnhance() {
  const current = draft.value
  if (!current || busy.value) return
  busy.value = true
  try {
    const res = await enhancePrompt({ draft: current, context: props.context })
    const data = res?.response
    // 后端 LLM 不可用时显式给 degraded —— 此时**保持用户输入原样**，不覆盖
    if (data?.degraded || !data?.enhanced) {
      message.warning('提示词增强暂不可用，请稍后重试')
      return
    }
    emit('update:modelValue', data.enhanced)
    emit('enhanced', data.enhanced)
    message.success('已增强，可直接使用或继续修改')
  } catch (e) {
    message.warning('提示词增强暂不可用，请稍后重试')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
/* 图标按钮：无边框圆形，hover 才出底色，保持输入区安静 */
.prompt-enhance-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  padding: 0;
  border: none;
  border-radius: var(--radius-circle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s, opacity 0.2s;
}

.prompt-enhance-btn.is-md {
  width: 28px;
  height: 28px;
  font-size: var(--font-size-16);
}

.prompt-enhance-btn.is-sm {
  width: 22px;
  height: 22px;
  font-size: var(--font-size-13);
}

.prompt-enhance-btn:hover:not(:disabled) {
  background: var(--bg-hover-light);
  color: var(--primary);
}

.prompt-enhance-btn:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

/* 星芒图标：路径不填色，跟随 button 的 color */
.sparkle-icon {
  fill: currentColor;
}
</style>
