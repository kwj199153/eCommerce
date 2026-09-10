<template>
  <div class="compact-toolbar" v-if="tools.length > 0">
    <!-- 左侧标签 -->
    <span class="toolbar-label">{{ agentName }}</span>

    <!-- 分隔线 -->
    <a-divider type="vertical" :margin="8" />

    <!-- 工具按钮列表（平铺） -->
    <div class="tool-list">
      <a-tooltip
        v-for="tool in tools"
        :key="tool.id"
        :title="`${tool.name} — ${tool.description}`"
        placement="bottom"
        mouseEnterDelay="0.3"
      >
        <button
          :class="['tool-btn', {
            active: selectedToolId === tool.id,
            disabled: tool.status === 'coming_soon',
          }]"
          :disabled="tool.status === 'coming_soon'"
          @click="handleToolClick(tool)"
        >
          <span class="tool-icon">{{ tool.icon }}</span>
          <span class="tool-name">{{ tool.name }}</span>
        </button>
      </a-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ToolDefinition, getAgentTools } from './toolDefinitions'

const props = defineProps<{
  agentId: string
  agentName: string
  selectedToolId?: string | null
}>()

const emit = defineEmits<{
  (e: 'selectTool', tool: ToolDefinition): void
}>()

// 获取当前 Agent 的工具列表
const tools = computed(() => getAgentTools(props.agentId))

// 处理工具点击
const handleToolClick = (tool: ToolDefinition) => {
  if (tool.status === 'coming_soon') return
  emit('selectTool', tool)
}
</script>

<style scoped>
.compact-toolbar {
  display: flex;
  align-items: center;
  height: 42px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border-base);
  background-color: var(--bg-hover-light);
  flex-shrink: 0;
  gap: 4px;
}

.toolbar-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  flex-shrink: 0;
}

/* ========== 工具按钮列表 ========== */
.tool-list {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  overflow-y: hidden;
  flex: 1;

  /* 隐藏滚动条 */
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.tool-list::-webkit-scrollbar {
  display: none;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 10px;
  border: none;
  border-radius: 6px;
  background-color: transparent;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
  position: relative;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1;
}

.tool-btn:hover:not(.disabled) {
  background-color: #e6f7ff;
  color: var(--primary);
}

.tool-btn.active {
  background-color: var(--primary);
  color: var(--bg-elevated);
  font-weight: 500;
}

.tool-btn.active .tool-icon {
  filter: none; /* emoji 在蓝色背景上保持原色 */
}

.tool-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool-icon {
  font-size: 14px;
  line-height: 1;
  flex-shrink: 0;
}

.tool-name {
  font-size: 12px;
  line-height: 1;
}
</style>
