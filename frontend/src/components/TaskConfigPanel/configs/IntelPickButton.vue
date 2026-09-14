<template>
  <!--
    竞品圈选入口（顶部按钮 + 弹出面板）
    ====================================
    形态对齐「载入选品」按钮（CandidateLoaderButton）：默认只占工具栏一个按钮位，
    点开才展开圈选清单。这样右侧边栏可以完整让给监控大屏，不再被常驻选择器占掉。

    面板本体仍由 IntelCompetitorPick 提供（分组过滤 / 批量勾选 / 池内清单），
    这里只负责外壳与按钮读数 —— 原组件一行未改。
  -->
  <a-popover
    v-model:open="popoverOpen"
    trigger="click"
    placement="bottomLeft"
    :overlayStyle="{ width: '460px', maxHeight: '560px' }"
  >
    <template #content>
      <IntelCompetitorPick />
    </template>

    <a-button
      type="primary"
      size="small"
      :class="['pick-trigger-btn', { loaded: selectedCount > 0 }]"
    >
      <template #icon>
        <FundOutlined />
      </template>
      {{ selectedCount ? `已圈选 ${selectedCount}` : '圈选竞品' }}
    </a-button>
  </a-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { FundOutlined } from '@ant-design/icons-vue'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import IntelCompetitorPick from './IntelCompetitorPick.vue'

const pool = useMonitorPoolStore()
const popoverOpen = ref(false)

/** 按钮读数。0 个时也允许点开 —— 用户正是要进去勾选。 */
const selectedCount = computed(() => pool.selectedAsins.length)
</script>

<style scoped>
.pick-trigger-btn {
  display: inline-flex;
  align-items: center;
}

/* 已圈选时用视觉重量提示「分析对象已就位」，与未选状态区分 */
.pick-trigger-btn.loaded {
  box-shadow: 0 0 0 2px var(--info-border, #91d5ff);
}
</style>
