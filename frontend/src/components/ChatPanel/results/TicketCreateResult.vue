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
.ticket-create-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

.ticket-header {
  display: flex; align-items: center; gap: var(--space-14);
  padding: var(--space-18) var(--space-20); background: linear-gradient(135deg, #f6ffed, #e6fffb);
  border-radius: var(--radius-12); margin-bottom: var(--space-14);
}
.ticket-icon { font-size: var(--font-size-36); }
.header-info h3 { margin: 0; font-size: var(--font-size-17); color: var(--text-primary); }
.ticket-id {
  display: inline-block; margin-top: var(--space-4); padding: var(--space-3) var(--space-10);
  background: var(--bg-elevated); border-radius: var(--radius-6); font-size: var(--font-size-13);
  color: var(--success); font-family: monospace; font-weight: 600;
}

.ticket-info-card {
  padding: var(--space-16); border: 1px solid var(--border-base); border-radius: var(--radius-10); margin-bottom: var(--space-14);
}
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-10); }
.info-item { display: flex; flex-direction: column; gap: var(--space-3); }
.info-item .label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.info-item .value { font-size: var(--font-size-13-5); color: var(--text-primary); font-weight: 500; }
.sla { color: var(--primary); font-weight: 600; }
.create-time { margin-top: var(--space-12); padding-top: var(--space-10); border-top: 1px solid var(--border-base); font-size: var(--font-size-11-5); color: var(--text-disabled); text-align: right; }

.auto-replies { margin-bottom: var(--space-14); padding: var(--space-12) var(--space-16); background: var(--orange-bg); border-radius: var(--radius-8); border: 1px solid var(--orange-border); }
.auto-replies h4 { margin: 0 0 var(--space-8); font-size: var(--font-size-13); color: var(--orange-strong); }
.auto-replies ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-12-5); line-height: 1.8; color: var(--text-secondary); }

.sla-timeline { padding: var(--space-14); background: var(--bg-base); border-radius: var(--radius-8); }
.sla-timeline h4 { margin: 0 0 var(--space-12); font-size: var(--font-size-13); color: var(--text-secondary); }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
