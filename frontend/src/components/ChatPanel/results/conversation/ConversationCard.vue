<template>
  <!--
    会话结论卡外壳。

    「和工具结果卡同区、同规则」的落点：两者都渲染在对话消息流里，
    都由 displayType 驱动（工具走 toolId、会话走 display_type），
    并共用同一个标题栏结构（图标 + 标题 + 数量徽标）。
    区别只在重量：工具卡带关闭按钮与密集表格，会话卡是只读的轻量结论。
  -->
  <div class="conversation-card">
    <div class="cc-head">
      <span class="cc-icon">{{ icon }}</span>
      <span class="cc-title">{{ title }}</span>
      <a-tag v-if="badge" :color="badgeColor" class="cc-badge">{{ badge }}</a-tag>
      <span v-if="note" class="cc-note">{{ note }}</span>
    </div>
    <div class="cc-body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    icon: string
    title: string
    badge?: string
    badgeColor?: string
    note?: string
  }>(),
  { badge: '', badgeColor: 'blue', note: '' },
)
</script>

<style scoped>
.conversation-card {
  margin-top: var(--space-10);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  padding: var(--space-10) var(--space-12);
  background: var(--bg-elevated);
}
.cc-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}
.cc-icon {
  font-size: var(--font-size-15);
  line-height: 1;
}
.cc-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.cc-badge {
  margin: 0;
}
.cc-note {
  margin-left: auto;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.cc-body {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
</style>
