<template>
  <a-drawer
    :open="open"
    @update:open="$emit('update:open', $event)"
    title="记忆与进化"
    :width="640"
    placement="right"
    :closable="true"
    :maskClosable="true"
    class="memory-drawer"
  >
    <!-- 开关区：生成对话记忆 -->
    <div class="section-card">
      <div class="section-row">
        <div class="section-info">
          <div class="section-label">生成对话记忆</div>
          <div class="section-desc">允许 AI 从对话中提取并记住相关上下文，以便在未来对话中提供更连贯、个性化的响应。</div>
        </div>
        <a-switch v-model:checked="autoMemoryEnabled" @change="onToggleAutoMemory" />
      </div>
    </div>

    <!-- 管理记忆：查看 / 编辑 / 重置 / 导入 -->
    <div class="section-card">
      <div class="section-header">
        <span class="section-title">管理记忆</span>
        <span class="section-hint">每晚自动整理更新，可随时查看和编辑</span>
      </div>
      <div class="memory-actions">
        <a-button danger ghost size="small" @click="onResetMemory">
          <ReloadOutlined /> 重置
        </a-button>
        <a-button size="small" @click="isEditing = !isEditing">
          <EditOutlined /> {{ isEditing ? '取消编辑' : '编辑' }}
        </a-button>
        <a-button size="small" @click="onImportMemory">
          <ImportOutlined /> 导入
        </a-button>
      </div>

      <!-- 记忆内容展示/编辑 -->
      <div class="memory-content-wrapper">
        <div v-if="!isEditing" class="memory-view" v-html="renderedMemory"></div>
        <textarea
          v-else
          class="memory-editor"
          v-model="editingContent"
          spellcheck="false"
        />
      </div>

      <!-- 编辑态底部操作栏 -->
      <div v-if="isEditing" class="editor-footer">
        <span class="editor-hint">直接修改上方内容，点击保存生效</span>
        <a-space>
          <a-button size="small" @click="isEditing = false">取消</a-button>
          <a-button size="small" type="primary" @click="onSaveMemory">
            <CheckOutlined /> 保存修改
          </a-button>
        </a-space>
      </div>
    </div>

    <!-- 学习时间线 -->
    <div class="section-card">
      <div class="section-header">
        <span class="section-title">学习时间线</span>
        <span class="section-hint">{{ dailyLogs.length }} 条偏好记录，按时间倒序</span>
      </div>
      <a-timeline class="log-timeline">
        <a-timeline-item
          v-for="log in dailyLogs"
          :key="log.date"
          :color="log.color"
        >
          <div class="log-date">{{ log.date }}</div>
          <div class="log-content">{{ log.content }}</div>
        </a-timeline-item>
      </a-timeline>
      <a-empty v-if="!dailyLogs.length" description="暂无学习记录——继续对话后 AI 会自动归纳你的偏好" :image-style="{ height: '48px' }" />
    </div>

    <!-- 隐藏的文件输入（导入用） -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".md,.txt"
      style="display: none"
      @change="handleFileImport"
    />
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  ReloadOutlined,
  EditOutlined,
  ImportOutlined,
  CheckOutlined,
} from '@ant-design/icons-vue'

defineProps<{
  open: boolean
}>()
defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

// ====== 用户使用习惯与偏好记忆 ======
// 来源：AI 在对话中逐渐学习到的用户画像、工作习惯、沟通偏好
const rawMemory = ref(`# 工作背景

跨境电商卖家，主营 3C 数码配件和家居小家电品类。目前在 Amazon 美国站、欧洲站（德/法/意）以及 Shopee 东南亚（新加坡/马来西亚/菲律宾）多平台运营，团队规模 5 人（1 运营主管 + 2 Listing 专员 + 1 广告投手 + 1 客服）。日均处理 15-20 条Listing优化需求、3-5 个广告活动调整、竞品监控覆盖 TOP 20 ASIN。

常用工具：Helium 10 / Jungle Scout 做关键词调研，Seller Central 后台管理，ERP 系统对接库存和订单。每天早上先看昨日销售数据 + 广告 ACOS，再安排当日优化任务。

# 个人背景

- **角色**：店铺运营负责人，兼顾部分选品工作
- **经验**：3 年跨境经验，从单干到带小团队
- **工作节奏**：早 9 晚 11，周末轮班看广告
- **沟通风格**：直接高效，不喜欢长篇大论，要结论先行
- **决策习惯**：喜欢看数据对比（改前 vs 改后），对"改动大吗"很敏感——怕影响现有稳定Listing

# 运营偏好

- **Listing 优化**：标题重关键词覆盖（前端词+核心词+长尾词），五点描述卖点和场景并重，A+ 页面倾向图文搭配型模板
- **关键词策略**：优先低竞争高搜索量长尾词，不盲目追大词；关注搜索量变化趋势而非绝对值
- **广告投放**：自动广告跑词 + 手动广告精准打，ACOS 控制在 25% 以内算健康；新品期容忍 40%以内
- **竞品监控**：每周固定跟踪 5-8 个核心竞品，关注价格变动、新 Review、BSR 排名变化
- **客服话术**：模板化回复为主，差评第一时间联系客户尝试修改（合规前提下）

# 沟通偏好

- **语言**：中文交流，专业术语用英文（ASIN/ACOS/BSR/SKU 等）
- **格式**：数据说话，对比表格优于纯文字；关键指标加粗突出
- **决策风格**：先看方案预览再决定，常说"先不改""这个先放着"——说明阶段只看不动
- **纠错习惯**：会直接指出 AI 生成的Listing不符合平台规则（如标题超字符、五点全大写等）
- **数据观**：宁可显示"暂无数据"也不要编造搜索量或竞争度数值

# 当前关注重点

1. Q4 旺季备货和 Listing 优化冲刺（Prime Day 后复盘 + 黑五网一准备）
2. 新品线（智能插座）的 Listing 从 0 到 1 搭建
3. Shopee 新加坡站广告 ACOS 偏高，正在优化关键词和出价
4. 竞品近期频繁降价，需要监控并制定应对策略`)

// 学习到的用户偏好时间线（AI 在对话中逐步积累的认知）
const dailyLogs = ref([
  { date: '2026-09-08', content: '学习到：用户是跨境电商多平台卖家（Amazon美/欧 + Shopee东南亚），团队5人，日均处理15-20条Listing优化；偏好数据驱动的对比式输出', color: 'green' },
  { date: '2026-09-07', content: '学习到：用户对广告ACOS敏感——新品期容忍40%以内，稳定期控制在25%以下；关键词策略优先低竞争长尾词，不盲目追大词', color: 'blue' },
  { date: '2026-09-07', content: '学习到：用户决策模式是"先看预览再决定"，常说"先不改""这个先放着"；对Listing改动很谨慎，怕影响现有稳定排名', color: 'blue' },
  { date: '2026-09-06', content: '学习到：用户会直接指出AI生成的Listing不符合平台规则（标题超字符、五点全大写等）；差评第一时间尝试联系客户修改', color: 'orange' },
  { date: '2026-09-05', content: '学习到：用户工作节奏早9晚11，周末轮班看广告；每天早上固定流程：看昨日销售→看广告ACOS→安排当日优化任务', color: 'purple' },
  { date: '2026-09-04', content: '学习到：竞品监控覆盖TOP 20 ASIN，每周跟踪5-8个核心竞品；关注价格变动、新Review、BSR排名变化三个核心指标', color: 'cyan' },
  { date: '2026-09-03', content: '初始化用户画像：3年跨境经验卖家，主营3C数码+家居小家电，从单干到带5人小团队；Q4旺季备货期，重点冲刺黑五网一', color: 'gray' },
])

// 状态
const autoMemoryEnabled = ref(true)
const isEditing = ref(false)
const editingContent = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)

// Markdown → 简单 HTML 渲染
const renderedMemory = computed(() => {
  let html = rawMemory.value
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
  html = html.replace(/\n\n/g, '</p><p>')
  html = '<p>' + html + '</p>'
  html = html.replace(/<p><\/p>/g, '')
  return html
})

// 操作
const onToggleAutoMemory = (checked: boolean) => {
  message.success(checked ? '已开启自动生成对话记忆' : '已关闭自动生成对话记忆')
}

const onResetMemory = () => {
  Modal.confirm({
    title: '确认重置记忆？',
    content: '将清空所有项目长期记忆内容，恢复为默认模板。此操作不可撤销。',
    okText: '确认重置',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => {
      rawMemory.value = '# 用户偏好记忆\n\n*(记忆已重置，AI 将在后续对话中重新学习你的习惯和偏好)*'
      message.success('已重置记忆')
    },
  })
}

const onImportMemory = () => {
  fileInputRef.value?.click()
}

const handleFileImport = (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    rawMemory.value = reader.result as string
    message.success(`已导入记忆文件：${file.name}`)
  }
  reader.readAsText(file)
  input.value = ''
}

const onSaveMemory = () => {
  rawMemory.value = editingContent.value
  isEditing.value = false
  message.success('记忆已保存')
}

watch(isEditing, (val) => {
  if (val) editingContent.value = rawMemory.value
})
</script>

<style scoped>
/* 区块卡片 */
.section-card {
  background-color: var(--bg-hover-light);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
html.dark .section-card {
  background-color: var(--bg-hover-dark);
}

/* 开关行 */
.section-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.section-info { flex: 1; min-width: 0; }
.section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}
.section-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* 管理记忆头部 */
.section-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.section-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 操作按钮行 */
.memory-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

/* 记忆内容区 */
.memory-content-wrapper {
  border: 1px solid var(--border-base);
  border-radius: 6px;
  overflow: hidden;
}
.memory-view {
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-primary);
  max-height: 380px;
  overflow-y: auto;
  word-break: break-word;
}
.memory-view :deep(h1) {
  font-size: 15px; font-weight: 700; margin: 6px 0 3px;
  color: var(--text-primary);
}
.memory-view :deep(h2) {
  font-size: 14px; font-weight: 600; margin: 8px 0 3px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-base); padding-bottom: 3px;
}
.memory-view :deep(h3) {
  font-size: 13px; font-weight: 600; margin: 6px 0 2px;
  color: var(--text-secondary);
}
.memory-view :deep(code) {
  background: var(--bg-card-pill); padding: 1px 4px; border-radius: 3px;
  font-size: 11.5px; font-family: SFMono-Regular, Consolas, monospace;
}
.memory-view :deep(li) { margin-left: 14px; margin-bottom: 1px; }
.memory-view :deep(p) { margin-bottom: 3px; }

.memory-editor {
  width: 100%;
  min-height: 300px;
  max-height: 420px;
  padding: 12px 14px;
  border: none;
  outline: none;
  resize: vertical;
  font-size: 12.5px;
  line-height: 1.65;
  font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
  background: transparent;
  color: var(--text-primary);
  box-sizing: border-box;
}

/* 编辑器底栏 */
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-base);
}
.editor-hint { font-size: 11px; color: var(--text-tertiary); }

/* 工作日志时间线 */
.log-timeline { margin-top: 2px; padding-left: 2px; }
.log-date { font-size: 11.5px; font-weight: 600; color: var(--text-primary); }
.log-content { font-size: 12px; color: var(--text-secondary); line-height: 1.5; margin-top: 1px; }

/* Drawer 标题样式覆盖 */
:deep(.ant-drawer-header) {
  border-bottom: 1px solid var(--border-base);
  padding: 14px 20px;
}
:deep(.ant-drawer-title) {
  font-size: 16px;
  font-weight: 600;
}
:deep(.ant-drawer-body) {
  padding: 16px 18px;
  background-color: var(--bg-base);
}
</style>
