<template>
  <div class="prompt-tab">
    <button
      type="button"
      class="prompt-toggle"
      @click="open = !open"
    >
      <span>⚙️ 自定义 prompt</span>
      <span
        class="prompt-arrow"
        :class="{ open }"
      >▾</span>
      <a-tag
        v-if="hasLocal"
        color="purple"
        class="mini-tag"
      >
        已覆盖
      </a-tag>
    </button>
    <div
      v-if="open"
      class="prompt-body"
    >
      <a-textarea
        :value="modelValue"
        :rows="3"
        :placeholder="placeholder"
        @update:value="onInput"
      />
      <div class="prompt-hint">
        留空则沿用<strong>全局指令</strong>；填写后<strong>完全替换</strong>本模块的默认生成指令
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  modelValue: string
  placeholder?: string
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const open = ref(false)
const hasLocal = computed(() => !!props.modelValue.trim())

function onInput(v: string) {
  emit('update:modelValue', v)
}
</script>

<style scoped>
.prompt-tab {
  margin-top: var(--space-8);
}
.prompt-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-4) var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  border-radius: var(--radius-4);
}
.prompt-toggle:hover {
  color: var(--primary);
  background: var(--bg-hover-light);
}
.prompt-arrow {
  font-size: var(--font-size-10);
  transition: transform 0.18s ease;
}
.prompt-arrow.open {
  transform: rotate(180deg);
}
.mini-tag { transform: scale(0.8); margin-left: var(--space-2); }
.prompt-body {
  margin-top: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.prompt-hint {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1.5;
}
</style>
