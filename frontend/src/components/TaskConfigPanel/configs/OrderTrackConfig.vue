<template>
  <div class="order-track-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <div class="section-title">📦 订单查询方式（任选其一）</div>

      <!-- 订单号 -->
      <a-form-item label="订单号">
        <a-input
          v-model:value="formState.orderId"
          placeholder="输入订单号，如 ORD-20260101-12345"
          allowClear
        />
        <div class="form-hint">格式：ORD-XXXXXXXX 或纯数字订单号</div>
      </a-form-item>

      <a-divider style="margin: 12px 0;" />

      <!-- 或通过邮箱/手机 -->
      <a-form-item label="下单邮箱">
        <a-input
          v-model:value="formState.email"
          placeholder="example@email.com"
          allowClear
        />
      </a-form-item>

      <a-form-item label="手机后四位">
        <a-input
          v-model:value="formState.phoneLast4"
          placeholder="输入手机号后 4 位"
          :maxlength="4"
          allowClear
        />
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <SearchOutlined /> 查询订单
        </a-button>
      </div>
    </a-form>

    <!-- 快捷提示 -->
    <div class="quick-tips">
      <p class="tips-title">💡 查询结果包含</p>
      <ul>
        <li>订单状态与下单时间</li>
        <li>商品信息与金额</li>
        <li>物流跟踪信息（已发货时）</li>
        <li>预计送达时间</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

const formState = reactive({
  orderId: '',
  email: '',
  phoneLast4: '',
})

const handleStart = () => {
  if (!formState.orderId && !formState.email && !formState.phoneLast4) {
    return
  }
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      order_id: formState.orderId || undefined,
      email: formState.email || undefined,
      phone_last4: formState.phoneLast4 || undefined,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.order-track-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 12px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.section-title { font-size: 13px; font-weight: 600; color: #262626; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 2px solid #1890ff; display: inline-block; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #e6f7ff; border-radius: 8px; border: 1px solid #91d5ff; }
.tips-title { font-size: 12px; font-weight: 600; color: #0958d9; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>
