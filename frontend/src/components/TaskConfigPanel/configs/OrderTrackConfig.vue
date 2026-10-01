<template>
  <div class="order-track-config">
    <a-form
      layout="vertical"
      :model="formState"
      class="config-form"
    >
      <div class="section-title">
        📦 订单查询
      </div>

      <!-- 订单号 -->
      <a-form-item label="订单号">
        <a-input
          v-model:value="formState.orderId"
          placeholder="输入订单号，如 112-1234567-8901234"
          allow-clear
        />
        <div class="form-hint">
          Amazon 订单号格式：123-1234567-1234567
        </div>
      </a-form-item>

      <a-divider style="margin: var(--space-12) 0;" />

      <!-- 按邮箱/手机检索：后端尚未开放（需卖家后台授权）⇒ 置灰，
           避免用户填了却永远查不到，还以为是自己输错了 -->
      <a-form-item label="下单邮箱">
        <a-input
          v-model:value="formState.email"
          placeholder="example@email.com"
          disabled
          allow-clear
        />
      </a-form-item>

      <a-form-item label="手机后四位">
        <a-input
          v-model:value="formState.phoneLast4"
          placeholder="输入手机号后 4 位"
          :maxlength="4"
          disabled
          allow-clear
        />
      </a-form-item>
      <div class="form-hint">
        按邮箱 / 手机号检索需要卖家后台授权，暂未开放 —— 请用订单号查询。
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button
          type="primary"
          block
          :loading="loading"
          @click="handleStart"
        >
          <SearchOutlined /> 查询订单
        </a-button>
      </div>
    </a-form>

    <!-- 快捷提示
         ★ 第 292 轮：这一块从前是**手写的第 4 份字段清单**（4 条），后端加了
           运单号 / 承运商 / 轨迹之后它没跟着改，还写着「运单号与承运商不在 Orders
           接口中」—— 而自有订单库那条链（`_map_order_from_trade`）**是给的**，
           这句话把用户指去了错的地方。现在从唯一真源 `orderFieldPreview()` 派生。 -->
    <div class="quick-tips">
      <p class="tips-title">
        💡 查询结果包含
      </p>
      <ul>
        <li
          v-for="f in fieldPreview"
          :key="f.key"
        >
          {{ f.label }}<span
            v-if="f.ownDbOnly"
            class="tips-sub"
          >（自有订单库才有）</span>
        </li>
      </ul>
      <p class="form-hint">
        运单号 / 承运商 / 轨迹来自<b>本店自有订单库</b>；平台 Orders 接口不返回这类数据。
        取不到时对应的行<b>直接不显示</b>，不编造。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
import { orderFieldPreview } from '@/utils/orderTracking'

/** 「查询结果包含」的清单 —— 从唯一真源派生，不再手写第二份 */
const fieldPreview = orderFieldPreview()

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
.order-track-config { padding: var(--space-4) 0; }
.config-form :deep(.ant-form-item) { margin-bottom: var(--space-12); }
.config-form :deep(.ant-form-item-label) { font-size: var(--font-size-13); font-weight: 500; }
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-4); }
.section-title { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-10); padding-bottom: var(--space-8); border-bottom: 2px solid var(--primary); display: inline-block; }
.action-bar { margin-top: var(--space-16); padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
.quick-tips { margin-top: var(--space-16); padding: var(--space-12); background: var(--info-bg); border-radius: var(--radius-8); border: 1px solid var(--info-border); }
.tips-sub { color: var(--text-tertiary); }
.tips-title { font-size: var(--font-size-12); font-weight: 600; color: var(--primary-strong); margin-bottom: var(--space-6); }
.quick-tips ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; }
</style>
