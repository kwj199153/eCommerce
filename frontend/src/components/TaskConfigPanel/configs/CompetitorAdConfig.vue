<template>
  <div class="competitor-ad-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 竞品 ASIN 输入 -->
      <a-form-item label="竞品 ASIN 列表">
        <a-select
          v-model:value="formState.competitorAsins"
          mode="tags"
          placeholder="输入 ASIN，回车添加（如 B08XXXXXX1）"
          :token-separators="tokenSeparators"
          style="width: 100%"
        />
        <div class="form-hint">已添加 {{ formState.competitorAsins.length }} 个竞品</div>
      </a-form-item>

      <!-- 自动检测 -->
      <a-form-item label="检测方式">
        <a-checkbox v-model:checked="formState.autoDetect">自动检测主要竞品</a-checkbox>
        <div class="form-hint">开启后系统将基于关键词重叠自动识别竞品</div>
      </a-form-item>

      <!-- 关键词重叠分析 -->
      <a-form-item label="分析维度">
        <a-checkbox v-model:checked="formState.includeKeywords">包含关键词重叠分析</a-checkbox>
      </a-form-item>

      <!-- 时间范围 -->
      <a-form-item label="时间范围">
        <a-select v-model:value="formState.timeRange" :options="timeRangeOptions" />
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 分析竞品广告
        </a-button>
      </div>
    </a-form>

    <!-- 快捷提示 -->
    <div class="quick-tips">
      <p class="tips-title">🎯 竞品分析将输出</p>
      <ul>
        <li>展示份额 (SOV) 对比</li>
        <li>重叠关键词数量与排名</li>
        <li>竞品出价策略推测</li>
        <li>优劣势分析与可执行洞察</li>
      </ul>
    </div>
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
  competitorAsins: [] as string[],
  autoDetect: true,
  includeKeywords: true,
  timeRange: '30d',
})

const timeRangeOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天（推荐）', value: '30d' },
  { label: '近 90 天', value: '90d' },
]

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      competitor_asins: formState.competitorAsins.length > 0 ? formState.competitorAsins : undefined,
      auto_detect: formState.autoDetect,
      include_keywords: formState.includeKeywords,
      time_range: formState.timeRange,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.competitor-ad-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #fff7e6; border-radius: 8px; border: 1px solid #ffd591; }
.tips-title { font-size: 12px; font-weight: 600; color: #d46b08; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>
