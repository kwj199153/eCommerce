<template>
  <div class="ticket-create-result" v-if="data">
    <!-- 工单确认头部 -->
    <div class="ticket-header">
      <span class="ticket-icon">🎫</span>
      <div class="header-info">
        <h3>工单创建成功</h3>
        <code class="ticket-id">{{ data.ticket?.ticket_id || '-' }}</code>
      </div>
    </div>

    <!-- 工单信息卡片 -->
    <div class="ticket-info-card">
      <div class="info-grid">
        <div class="info-item">
          <span class="label">标题</span>
          <span class="value">{{ data.ticket?.subject || '-' }}</span>
        </div>
        <div class="info-item">
          <span class="label">分类</span>
          <a-tag :color="categoryColor(data.ticket?.category)">{{ categoryLabel(data.ticket?.category) }}</a-tag>
        </div>
        <div class="info-item">
          <span class="label">优先级</span>
          <a-tag :color="priorityColor(data.ticket?.priority)">{{ data.ticket?.priority || 'medium' }}</a-tag>
        </div>
        <div class="info-item">
          <span class="label">状态</span>
          <a-tag color="processing">{{ data.ticket?.status || 'open' }}</a-tag>
        </div>
        <div class="info-item">
          <span class="label">预计响应</span>
          <span class="value sla">{{ estimatedResponseTime || '24h' }}</span>
        </div>
        <div class="info-item" v-if="data.ticket?.order_id">
          <span class="label">关联订单</span>
          <code>{{ data.ticket.order_id }}</code>
        </div>
      </div>

      <div v-if="data.ticket?.created_at" class="create-time">
        创建时间: {{ formatTime(data.ticket.created_at) }}
      </div>
    </div>

    <!-- 自动回复 -->
    <div v-if="data.auto_replies?.length" class="auto-replies">
      <h4>📨 自动回复</h4>
      <ul><li v-for="(reply, i) in data.auto_replies" :key="i">{{ reply }}</li></ul>
    </div>

    <!-- SLA 时间线 -->
    <div class="sla-timeline">
      <h4>⏱️ 处理流程</h4>
      <a-steps :current="0" size="small" direction="vertical">
        <a-step title="工单已创建" :description="formatTime(data.ticket?.created_at)" />
        <a-step title="客服团队处理中" :description="'预计 ' + (estimatedResponseTime || '24小时内') + ' 响应'" />
        <a-step title="问题解决 / 需补充信息" />
        <a-step title="工单关闭" />
      </a-steps>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const estimatedResponseTime = computed(() => {
  const p = props.data.ticket?.priority as keyof typeof priorityMap | undefined
  return (priorityMap[p as keyof typeof priorityMap]) || '24h'
})

const priorityMap = { urgent: '2小时', high: '4小时', medium: '24小时', low: '48小时' } as const

const categoryLabel = (c: string) => ({
  order: '订单', logistics: '物流', return: '退换货',
  quality: '售后质量', payment: '支付', consultation: '咨询', complaint: '投诉', general: '其他',
}[c] || c)

const categoryColor = (c: string) => ({ order: 'blue', logistics: 'green', return: 'orange', quality: 'red', payment: 'purple' }[c] || 'default')
const priorityColor = (p: string) => ({ urgent: 'red', high: 'orange', medium: 'gold', low: 'blue' }[p] || 'default')

const formatTime = (t: string) => {
  if (!t) return '-'
  try { return new Date(t).toLocaleString('zh-CN') } catch { return t }
}
</script>

<style scoped>
.ticket-create-result { padding: 16px; background: #fff; border-radius: 8px; }

.ticket-header {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px; background: linear-gradient(135deg, #f6ffed, #e6fffb);
  border-radius: 12px; margin-bottom: 14px;
}
.ticket-icon { font-size: 36px; }
.header-info h3 { margin: 0; font-size: 17px; color: #262626; }
.ticket-id {
  display: inline-block; margin-top: 4px; padding: 3px 10px;
  background: #fff; border-radius: 6px; font-size: 13px;
  color: #389e0d; font-family: monospace; font-weight: 600;
}

.ticket-info-card {
  padding: 16px; border: 1px solid #f0f0f0; border-radius: 10px; margin-bottom: 14px;
}
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.info-item { display: flex; flex-direction: column; gap: 3px; }
.info-item .label { font-size: 11px; color: #8c8c8c; }
.info-item .value { font-size: 13.5px; color: #262626; font-weight: 500; }
.sla { color: #1890ff; font-weight: 600; }
.create-time { margin-top: 12px; padding-top: 10px; border-top: 1px solid #f0f0f0; font-size: 11.5px; color: #bfbfbf; text-align: right; }

.auto-replies { margin-bottom: 14px; padding: 12px 16px; background: #fff7e6; border-radius: 8px; border: 1px solid #ffd591; }
.auto-replies h4 { margin: 0 0 8px; font-size: 13px; color: #d46b08; }
.auto-replies ul { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.8; color: #434343; }

.sla-timeline { padding: 14px; background: #fafafa; border-radius: 8px; }
.sla-timeline h4 { margin: 0 0 12px; font-size: 13px; color: #595959; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>
