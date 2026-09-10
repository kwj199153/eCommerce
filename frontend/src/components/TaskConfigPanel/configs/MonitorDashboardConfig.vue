<template>
  <div class="monitor-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 目标 ASIN（可选） -->
      <a-form-item label="目标 ASIN（可选）">
        <a-input
          v-model:value="formState.asin"
          placeholder="输入竞品ASIN，如 B08XXXXXX1"
          :maxlength="10"
          allow-clear
        />
        <div class="form-hint">留空则返回所有竞品概览</div>
      </a-form-item>

      <!-- 分析时间范围 -->
      <a-form-item label="分析时间范围">
        <a-select v-model:value="formState.days" :options="dayOptions" />
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">📊 监控仪表盘将输出</p>
        <ul>
          <li>所有竞品价格/排名/库存状态一览</li>
          <li>近期价格变动与排名趋势</li>
          <li>库存异常警报</li>
          <li>综合健康评分</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 开始监控
        </a-button>
      </div>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

const formState = reactive({
  asin: '',
  days: 30,
})

const dayOptions = [
  { label: '近 7 天', value: 7 },
  { label: '近 30 天（推荐）', value: 30 },
  { label: '近 90 天', value: 90 },
]

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      asin: formState.asin || undefined,
      days: formState.days,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.monitor-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #e6f7ff; border-radius: 8px; border: 1px solid #91d5ff; }
.tips-title { font-size: 12px; font-weight: 600; color: #0958d9; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>
