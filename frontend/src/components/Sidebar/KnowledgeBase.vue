<template>
  <div class="knowledge-base">
    <!-- 「竞品监控」独立入口已下线：看板并入竞品监控员的右侧边栏；
         旧入口（蓝海抽屉 / 选品库开启监控 / 店秘书导航）在 Workspace 统一重定向。 -->
    <div class="section-title">资料库</div>
    <a-menu
      mode="inline"
      :selectedKeys="selectedKeys"
      @click="handleMenuClick"
    >
      <a-menu-item key="candidates">
        <FilterOutlined />
        <span>选品库</span>
      </a-menu-item>
      <a-menu-item key="assets">
        <PictureOutlined />
        <span>营销素材库</span>
      </a-menu-item>
      <a-menu-item key="products">
        <DatabaseOutlined />
        <span>自有产品库</span>
      </a-menu-item>
      <a-menu-item key="competitors">
        <FundOutlined />
        <span>竞品监控池</span>
      </a-menu-item>
      <a-menu-item key="faq">
        <MessageOutlined />
        <span>业务话术库</span>
      </a-menu-item>
      <a-menu-item key="rules">
        <SafetyCertificateOutlined />
        <span>平台规则库</span>
      </a-menu-item>
    </a-menu>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  MessageOutlined,
  DatabaseOutlined,
  PictureOutlined,
  FilterOutlined,
  SafetyCertificateOutlined,
  FundOutlined,
} from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'navigate', key: string): void
}>()

const selectedKeys = ref<string[]>([])

const handleMenuClick = ({ key }: { key: string }) => {
  selectedKeys.value = [key]
  emit('navigate', key)
}

/** 外部可调用的切换方法（只同步高亮；视图切换由 'navigate' 的接收方决定） */
function navigateTo(key: string) {
  selectedKeys.value = [key]
}

defineExpose({ navigateTo })
</script>

<style scoped>
.knowledge-base {
  padding: var(--space-8) 0;
}

.section-title {
  padding: var(--space-12) var(--space-16) var(--space-8);
  font-size: var(--font-size-13);
  font-weight: 500;
  color: var(--text-tertiary);
}

:deep(.ant-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: var(--space-2) var(--space-8);
  border-radius: var(--radius-6);
}

:deep(.ant-menu-item .anticon) {
  font-size: var(--font-size-16);
  margin-right: var(--space-10);
}
</style>
