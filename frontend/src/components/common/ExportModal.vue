<template>
  <a-modal
    :open="open"
    :title="title"
    :width="520"
    :mask-closable="false"
    :confirm-loading="exporting"
    ok-text="选择位置并导出"
    cancel-text="取消"
    @ok="handleExport"
    @cancel="handleCancel"
    @update:open="(v: boolean) => $emit('update:open', v)"
  >
    <div class="export-modal">
      <!-- 数据概要 -->
      <div class="em-summary">
        <span>📦 共 <b>{{ count }}</b> 条{{ unit }}</span>
        <a-tag color="blue" v-if="canPicker">已选「另存为」模式</a-tag>
        <a-tag color="orange" v-else>将下载到默认下载目录</a-tag>
      </div>

      <!-- 格式选择 -->
      <div class="em-field">
        <div class="em-label">导出格式</div>
        <div class="em-formats">
          <div
            v-for="f in formatList"
            :key="f.key"
            class="em-format-card"
            :class="{ active: format === f.key }"
            @click="format = f.key"
          >
            <div class="em-f-icon">{{ f.icon }}</div>
            <div class="em-f-label">{{ f.label }}</div>
            <div class="em-f-ext">.{{ f.ext }}</div>
          </div>
        </div>
      </div>

      <!-- 文件名（可改，用于另存为建议名） -->
      <div class="em-field">
        <div class="em-label">文件名</div>
        <a-input
          v-model:value="fileName"
          :addon-after="'.' + EXPORT_FORMAT_META[format].ext"
          placeholder="输入文件名"
        />
      </div>

      <!-- 保存方式说明 -->
      <a-alert
        v-if="canPicker"
        type="info"
        show-icon
        message="点击下方按钮将弹出系统「另存为」对话框，可选择任意目标文件夹后保存。"
        style="margin-top: 8px"
      />
      <a-alert
        v-else
        type="warning"
        show-icon
        message="当前浏览器（非 Chrome / Edge）不支持选择保存位置，将自动下载到浏览器默认下载目录。建议使用 Chrome 或 Edge 以支持选择目标文件夹。"
        style="margin-top: 8px"
      />
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  EXPORT_FORMAT_META,
  canUseSavePicker,
  saveExportFile,
  type ExportFormat,
} from '@/utils/download'

const props = defineProps<{
  open: boolean
  title: string
  /** 导出数据单元名，如"话术" */
  unit: string
  count: number
  /** 文件名前缀（不含扩展名，用户可改） */
  baseName: string
  /** JSON 格式导出数据 */
  jsonData: unknown
  /** Excel/CSV/TXT 表格列头 */
  columns: string[]
  /** Excel/CSV/TXT 表格行 */
  rows: (string | number)[][]
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'done', filename?: string): void
}>()

const format = ref<ExportFormat>('json')
const fileName = ref(props.baseName)
const exporting = ref(false)

/** 当前浏览器是否支持 File System Access（另存为对话框） */
const canPicker = computed(() => canUseSavePicker())

const formatList = computed(() =>
  (Object.keys(EXPORT_FORMAT_META) as ExportFormat[]).map(k => ({
    key: k,
    ...EXPORT_FORMAT_META[k],
  }))
)

// 打开时重置
watch(
  () => props.open,
  v => {
    if (v) {
      format.value = 'json'
      fileName.value = props.baseName
    }
  }
)

async function handleExport() {
  const name = fileName.value.trim() || props.baseName
  exporting.value = true
  try {
    const res = await saveExportFile({
      format: format.value,
      jsonData: props.jsonData,
      table:
        format.value === 'excel' || format.value === 'csv' || format.value === 'txt'
          ? { headers: props.columns, rows: props.rows }
          : undefined,
      baseName: name,
    })
    if (res.status === 'cancelled') {
      message.info('已取消导出')
      return
    }
    if (res.status === 'fallback') {
      message.success(`已导出 ${res.filename}（保存至下载目录）`)
    } else {
      message.success(`已导出 ${res.filename}`)
    }
    emit('done', res.filename)
    emit('update:open', false)
  } catch (e) {
    message.error(`导出失败：${e instanceof Error ? e.message : '未知错误'}`)
  } finally {
    exporting.value = false
  }
}

function handleCancel() {
  emit('update:open', false)
}
</script>

<style scoped>
.export-modal {
  padding-top: 4px;
}
.em-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.em-field {
  margin-bottom: 12px;
}
.em-label {
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
}
.em-formats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.em-format-card {
  border: 1px solid #d9d9d9;
  border-radius: 8px;
  padding: 10px 6px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}
.em-format-card:hover {
  border-color: #1677ff;
}
.em-format-card.active {
  border-color: #1677ff;
  background: #e6f4ff;
  box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.1);
}
.em-f-icon {
  font-size: 20px;
}
.em-f-label {
  font-size: 12px;
  margin-top: 4px;
  color: #333;
}
.em-f-ext {
  font-size: 10px;
  color: #999;
}
</style>
