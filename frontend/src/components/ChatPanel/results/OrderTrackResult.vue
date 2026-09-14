<template>
  <div class="order-track-result" v-if="data">
    <!-- 订单头部 -->
    <div class="order-header" :class="'status-' + (data.order?.status || 'unknown')">
      <span class="status-icon">{{ statusIcon(data.order?.status) }}</span>
      <div class="header-info">
        <h3>订单 {{ data.order?.order_id || '-' }}</h3>
        <span class="status-text">{{ data.order?.status_text || '未知状态' }}</span>
      </div>
    </div>

    <!-- 订单详情 -->
    <div class="order-details">
      <div class="detail-grid">
        <div class="detail-item">
          <span class="label">下单时间</span>
          <span class="value">{{ data.order?.created_at || '-' }}</span>
        </div>
        <div class="detail-item">
          <span class="label">商品</span>
          <span class="value product-name">{{ data.order?.product_name || '-' }}</span>
        </div>
        <div class="detail-item">
          <span class="label">数量</span>
          <span class="value">{{ data.order?.quantity || 1 }} 件</span>
        </div>
        <div class="detail-item">
          <span class="label">金额</span>
          <span class="value amount">${{ Number(data.order?.total || 0).toFixed(2) }}</span>
        </div>
      </div>
    </div>

    <!-- 物流信息（已发货时显示） -->
    <div v-if="data.order?.tracking_number" class="logistics-section">
      <h4>🚚 物流信息</h4>
      <div class="logistics-card">
        <div class="log-row">
          <span class="log-label">快递单号</span>
          <code class="log-value tracking-code">{{ data.order.tracking_number }}</code>
        </div>
        <div class="log-row">
          <span class="log-label">承运商</span>
          <span class="log-value">{{ data.order.carrier || '-' }}</span>
        </div>
        <div class="log-row">
          <span class="log-label">预计送达</span>
          <span class="log-value delivery-date">{{ data.order.estimated_delivery || '-' }}</span>
        </div>
        <a-button type="link" size="small" style="padding: 0;">查看详细物流轨迹 →</a-button>
      </div>
    </div>

    <!-- 操作提示 -->
    <div class="action-hints">
      <p>💡 还有其他关于这个订单的问题吗？可以直接在对话框中继续提问。</p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const statusIcon = (s: string) => ({
  delivered: '✅',
  shipped: '🚚',
  processing: '⏳',
}[s] || '📦')
</script>

<style scoped>
.order-track-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

.order-header {
  display: flex; align-items: center; gap: var(--space-14);
  padding: var(--space-16) var(--space-20); border-radius: var(--radius-12); margin-bottom: var(--space-14);
}
.status-delivered { background: var(--success-bg); border: 1px solid var(--success-border); }
.status-shipped { background: var(--info-bg); border: 1px solid var(--info-border); }
.status-processing { background: var(--warning-bg); border: 1px solid var(--warning-border); }
.status-unknown { background: var(--bg-base); border: 1px solid var(--border-base); }

.status-icon { font-size: var(--font-size-32); }
.header-info h3 { margin: 0; font-size: var(--font-size-16); color: var(--text-primary); font-family: monospace; }
.status-text { font-size: var(--font-size-13); font-weight: 500; margin-top: var(--space-2); }
.status-delivered .status-text { color: var(--success); }
.status-shipped .status-text { color: var(--primary); }
.status-processing .status-text { color: var(--warning); }

.order-details { margin-bottom: var(--space-14); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-10); }
.detail-item {
  padding: var(--space-10) var(--space-12); background: var(--bg-base); border-radius: var(--radius-8);
}
.detail-item .label { display: block; font-size: var(--font-size-11); color: var(--text-tertiary); margin-bottom: var(--space-3); }
.detail-item .value { font-size: var(--font-size-13-5); color: var(--text-primary); font-weight: 500; }
.product-name { font-weight: 600; }
.amount { font-size: var(--font-size-17) !important; font-weight: 700; color: var(--primary); }

.logistics-section { margin-bottom: var(--space-14); }
.logistics-section h4 { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-8); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }
.logistics-card { padding: var(--space-14); background: var(--info-bg); border-radius: var(--radius-8); border: 1px solid var(--info-border); }
.log-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-8); }
.log-row:last-of-type { margin-bottom: 0; }
.log-label { font-size: var(--font-size-12); color: var(--text-secondary); }
.log-value { font-size: var(--font-size-13); color: var(--text-primary); font-weight: 500; }
.tracking-code { font-family: monospace; background: var(--bg-elevated); padding: var(--space-2) var(--space-6); border-radius: var(--radius-4); font-size: var(--font-size-12-5); }
.delivery-date { color: var(--primary); font-weight: 600; }

.action-hints { padding: var(--space-10) var(--space-14); background: var(--bg-base); border-radius: var(--radius-8); font-size: var(--font-size-12-5); color: var(--text-secondary); line-height: 1.5; }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
