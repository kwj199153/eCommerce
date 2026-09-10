<template>
  <div class="ticket-create-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 工单标题 -->
      <a-form-item label="工单标题" required>
        <a-input
          v-model:value="formState.subject"
          placeholder="简要描述问题（2-200字）"
          :maxlength="200"
          showCount
          allowClear
        />
      </a-form-item>

      <!-- 问题描述 -->
      <a-form-item label="问题描述" required>
        <a-textarea
          v-model:value="formState.description"
          placeholder="详细描述问题，越具体越好..."
          :rows="4"
          :maxlength="5000"
          showCount
        />
      </a-form-item>

      <!-- 分类 -->
      <a-form-item label="问题分类">
        <a-select v-model:value="formState.category" :options="categoryOptions" />
      </a-form-item>

      <!-- 关联订单号 -->
      <a-form-item label="关联订单号（可选）">
        <a-input
          v-model:value="formState.orderId"
          placeholder="如有相关订单请填写"
          allowClear
        />
      </a-form-item>

      <!-- 优先级 -->
      <a-form-item label="优先级（可选）">
        <a-select v-model:value="formState.priority" :options="priorityOptions" allowClear placeholder="自动判断" />
        <div class="form-hint">留空则根据内容自动计算优先级</div>
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <EditOutlined /> 创建工单
        </a-button>
      </div>
    </a-form>

    <!-- SLA 说明 -->
    <div class="sla-info">
      <p class="sla-title">⏱️ 预计响应时间</p>
      <div class="sla-grid">
        <div class="sla-item"><span class="label">紧急</span><span class="time">2 小时</span></div>
        <div class="sla-item"><span class="label">高</span><span class="time">4 小时</span></div>
        <div class="sla-item"><span class="label">中</span><span class="time">24 小时</span></div>
        <div class="sla-item"><span class="label">低</span><span class="time">48 小时</span></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { EditOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

const formState = reactive({
  subject: '',
  description: '',
  category: 'general',
  orderId: '',
  priority: undefined as string | undefined,
})

const categoryOptions = [
  { label: '📦 订单问题', value: 'order' },
  { label: '🚚 物流配送', value: 'logistics' },
  { label: '🔄 退换货', value: 'return' },
  { label: '🔧 售后质量', value: 'quality' },
  { label: '💳 支付问题', value: 'payment' },
  { label: '💬 咨询建议', value: 'consultation' },
  { label: '📝 投诉反馈', value: 'complaint' },
  { label: '📋 其他', value: 'general' },
]

const priorityOptions = [
  { label: '🔴 紧急 - 需立即处理', value: 'urgent' },
  { label: '🟠 高优先级', value: 'high' },
  { label: '🟡 中等', value: 'medium' },
  { label: '🟢 低优先级', value: 'low' },
]

const handleStart = () => {
  if (!formState.subject.trim() || !formState.description.trim()) {
    return
  }
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      subject: formState.subject,
      description: formState.description,
      category: formState.category,
      order_id: formState.orderId || undefined,
      priority: formState.priority,
      customer_id: '',
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.ticket-create-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 12px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }

.sla-info { margin-top: 16px; padding: 12px; background: #fff7e6; border-radius: 8px; border: 1px solid #ffd591; }
.sla-title { font-size: 12px; font-weight: 600; color: #d46b08; margin-bottom: 10px; }
.sla-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.sla-item { display: flex; justify-content: space-between; font-size: 11.5px; padding: 4px 8px; background: #fff; border-radius: 4px; }
.sla-item .label { color: #595959; }
.sla-item .time { font-weight: 600; color: #d46b08; }
</style>
