<template>
  <div class="price-track-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- ASIN 列表 -->
      <a-form-item label="追踪 ASIN 列表" required>
        <a-select
          v-model:value="formState.asins"
          mode="tags"
          placeholder="输入ASIN，回车添加（1-20个）"
          :token-separators="tokenSeparators"
          style="width: 100%"
        />
        <div class="form-hint">已添加 {{ formState.asins.length }} / 20 个</div>
      </a-form-item>

      <!-- 历史数据 -->
      <a-form-item label="历史趋势">
        <a-switch v-model:checked="formState.includeHistory" checked-children="包含" un-checked-children="不含" />
        <div class="form-hint">开启后返回价格/排名历史趋势图数据</div>
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">📉 价格追踪将输出</p>
        <ul>
          <li>各竞品当前价格与历史对比</li>
          <li>价格变动时间线（含涨跌幅度）</li>
          <li>排名变化趋势</li>
          <li>对比矩阵与综合得分排名</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 开始追踪
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
const tokenSeparators = [','] as const

const formState = reactive({
  asins: [] as string[],
  includeHistory: true,
})

const handleStart = () => {
  if (formState.asins.length === 0) return
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      asins: formState.asins,
      include_history: formState.includeHistory,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.price-track-config { padding: var(--space-4) 0; }
.config-form :deep(.ant-form-item) { margin-bottom: var(--space-14); }
.config-form :deep(.ant-form-item-label) { font-size: var(--font-size-13); font-weight: 500; }
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-4); }
.action-bar { margin-top: var(--space-16); padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
.quick-tips { margin-top: var(--space-16); padding: var(--space-12); background: var(--orange-bg); border-radius: var(--radius-8); border: 1px solid var(--orange-border); }
.tips-title { font-size: var(--font-size-12); font-weight: 600; color: var(--orange-strong); margin-bottom: var(--space-6); }
.quick-tips ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; }
</style>
