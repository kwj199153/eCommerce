<template>
  <div class="knowledge-base">
    <div class="section-title">监控</div>
    <a-menu
      mode="inline"
      :selectedKeys="monitorSelectedKeys"
      @click="handleMonitorClick"
    >
      <a-menu-item key="monitor">
        <FundOutlined />
        <span>竞品监控</span>
      </a-menu-item>
    </a-menu>

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
const monitorSelectedKeys = ref<string[]>([])

const handleMenuClick = ({ key }: { key: string }) => {
  selectedKeys.value = [key]
  monitorSelectedKeys.value = []
  emit('navigate', key)
}

const handleMonitorClick = ({ key }: { key: string }) => {
  monitorSelectedKeys.value = [key]
  selectedKeys.value = []
  emit('navigate', key)
}

/** 外部可调用的切换方法 */
function navigateTo(key: string) {
  if (key === 'monitor') {
    monitorSelectedKeys.value = [key]
    selectedKeys.value = []
  } else {
    selectedKeys.value = [key]
    monitorSelectedKeys.value = []
  }
}

defineExpose({ navigateTo })
</script>

<style scoped>
.knowledge-base {
  padding: 8px 0;
}

.section-title {
  padding: 12px 16px 8px;
  font-size: 13px;
  font-weight: 500;
  color: #8c8c8c;
}

:deep(.ant-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: 2px 8px;
  border-radius: 6px;
}

:deep(.ant-menu-item .anticon) {
  font-size: 16px;
  margin-right: 10px;
}
</style>
