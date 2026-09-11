<template>
  <div class="desc-generator-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">📄</span>
        <div>
          <h3>A+ Content 产品描述生成</h3>
          <p class="subtitle">{{ resultData.style }} 风格 · {{ resultData.word_count }} 字</p>
        </div>
      </div>
      <div class="header-actions">
        <!-- 产品库模式：写回当前产品 listing 的 A+ Content -->
        <a-button
          v-if="sourceMode === 'product' && productId"
          type="primary"
          size="small"
          @click="handleSaveToProduct"
          :loading="saving"
        >
          <SaveOutlined /> 应用到当前产品 Listing
        </a-button>
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 内容预览区 -->
    <div class="content-preview">
      <!-- 品牌横幅 -->
      <img v-if="resultData.brand_banner" :src="resultData.brand_banner" alt="" class="banner-img" />
      <div class="banner-placeholder" v-else>
        <span class="brand-name">{{ displayBrandName }}</span>
        <span class="brand-slogan">{{ displayBrandSlogan }}</span>
      </div>

      <!-- 模块化内容块（可直接编辑文案） -->
      <div class="content-modules">
        <div
          v-for="(module, idx) in displayModules"
          :key="idx"
          class="content-module"
          :class="module.type"
        >
          <div class="module-toolbar">
            <a-tag color="blue">{{ moduleTypeLabel(module.type) }}</a-tag>
            <div class="module-toolbar-actions">
              <a-button type="text" size="small" danger @click="removeModule(idx)" title="删除此模块">
                <DeleteOutlined /> 删除
              </a-button>
            </div>
          </div>

          <!-- 各模块统一先给「标题」输入 -->
          <div class="module-field">
            <label>模块标题</label>
            <a-textarea
              v-model:value="module.heading"
              :auto-size="{ minRows: 1, maxRows: 2 }"
              class="field-input"
              placeholder="模块标题（可编辑）"
            />
          </div>

          <!-- 标准文本模块：正文支持 HTML -->
          <template v-if="module.type === 'text'">
            <div class="module-field">
              <label>正文内容（支持 HTML）</label>
              <a-textarea
                v-model:value="module.content"
                :auto-size="{ minRows: 3, maxRows: 12 }"
                class="field-input"
                placeholder="模块正文，可编辑"
              />
            </div>
            <!-- 预览 -->
            <div class="module-body" v-html="module.content"></div>
          </template>

          <!-- 图文混排模块 -->
          <template v-else-if="module.type === 'image-text'">
            <div class="module-field">
              <label>图片说明文字</label>
              <a-textarea
                v-model:value="module.image_label"
                :auto-size="{ minRows: 1, maxRows: 2 }"
                class="field-input"
              />
            </div>
            <div class="module-field" v-for="(para, pidx) in module.paragraphs" :key="pidx">
              <label>段落 {{ pidx + 1 }}</label>
              <div class="para-row">
                <a-textarea
                  v-model:value="module.paragraphs[pidx]"
                  :auto-size="{ minRows: 1, maxRows: 5 }"
                  class="field-input"
                  placeholder="段落文字，可编辑"
                />
                <a-button type="text" size="small" danger @click="removeParagraph(module, pidx)">删</a-button>
              </div>
            </div>
            <a-button size="small" type="dashed" block @click="addParagraph(module)">
              <PlusOutlined /> 新增段落
            </a-button>
          </template>

          <!-- 对比表格模块：仅标题可编辑，数据为只读表格参考 -->
          <template v-else-if="module.type === 'comparison'">
            <table class="comp-table">
              <thead>
                <tr>
                  <th>特性</th>
                  <th v-for="(col, ci) in module.columns" :key="ci">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in module.rows" :key="ri">
                  <td class="feature-name">{{ row.feature }}</td>
                  <td v-for="(val, vi) in row.values" :key="vi" :class="{ highlight: val.highlight }">
                    {{ val.text }}
                    <CheckOutlined v-if="val.check" class="check-icon" />
                  </td>
                </tr>
              </tbody>
            </table>
          </template>

          <!-- 要点列表模块 -->
          <template v-else-if="module.type === 'highlights'">
            <div class="module-field" v-for="(item, iidx) in module.items" :key="iidx">
              <label>要点 {{ iidx + 1 }}</label>
              <a-input-group compact style="display: flex; gap: 6px; align-items: center">
                <a-input v-model:value="item.title" style="flex: 1" placeholder="要点标题" />
                <a-button type="text" size="small" danger @click="removeHighlight(module, iidx)">删</a-button>
              </a-input-group>
              <a-textarea
                v-model:value="item.description"
                :auto-size="{ minRows: 1, maxRows: 3 }"
                class="field-input"
                style="margin-top: 6px"
                placeholder="要点说明，可编辑"
              />
            </div>
            <a-button size="small" type="dashed" block @click="addHighlight(module)">
              <PlusOutlined /> 新增要点
            </a-button>
          </template>
        </div>

        <a-empty v-if="!displayModules.length" description="暂无内容模块" />

        <!-- 新增模块 -->
        <a-select
          v-model:value="newModuleType"
          placeholder="＋ 新增内容模块…"
          class="add-module-select"
          :options="addableModuleTypes"
          @change="addModule"
        />
      </div>

      <!-- 品牌故事底部 -->
      <div class="brand-footer" v-if="resultData.brand_story">
        <div class="footer-logo">{{ resultData.brand_name?.[0] || 'B' }}</div>
        <div class="footer-text">
          <h4>{{ resultData.brand_name }}</h4>
          <p>{{ resultData.brand_story }}</p>
        </div>
      </div>
    </div>

    <!-- 内容统计 -->
    <div class="content-stats">
      <div class="stat-item">
        <FileTextOutlined />
        <span class="s-label">总字数</span>
        <span class="s-value">{{ displayWordCount }}</span>
      </div>
      <div class="stat-item">
        <LayoutOutlined />
        <span class="s-label">内容模块</span>
        <span class="s-value">{{ displayModules.length }}</span>
      </div>
      <div class="stat-item">
        <KeyOutlined />
        <span class="s-label">SEO 关键词</span>
        <span class="s-value">{{ displaySeoKeywords.length }}</span>
      </div>
      <div class="stat-item">
        <EyeOutlined />
        <span class="s-label">预估阅读</span>
        <span class="s-value">{{ Math.ceil(displayWordCount / 200) }}分钟</span>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-space>
        <a-button type="primary" @click="copyFullContent">
          <CopyOutlined /> 复制全部内容
        </a-button>
        <a-button @click="exportHTML">
          <DownloadOutlined /> 导出 HTML
        </a-button>
        <a-button @click="regenerate">
          <ReloadOutlined /> 重新生成
        </a-button>
      </a-space>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  CloseOutlined, CopyOutlined, DownloadOutlined, ReloadOutlined,
  CheckOutlined, SaveOutlined, DeleteOutlined, PlusOutlined,
  FileTextOutlined, LayoutOutlined, KeyOutlined, EyeOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useProductLibraryStore } from '@/stores/productLibrary'

const props = defineProps<{
  data: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const productStore = useProductLibraryStore()
const saving = ref(false)
// 数据来源模式
const sourceMode = computed(() => props.data?._source || 'manual')
const productId = computed(() => props.data?.product_id)

const resultData = props.data || {
  brand_name: 'AeroLife',
  brand_slogan: 'Breathe Better, Live Better',
  style: '专业科技',
  word_count: 1250,
  modules: [
    {
      type: 'image-text',
      layout: 'standard',
      image_position: 'left',
      heading: '为什么选择 AeroLife 加湿器？',
      image_label: '产品全景图',
      paragraphs: [
        'AeroLife 便携式迷你加湿器采用先进的超声波雾化技术，将水分子转化为微米级细腻水雾，瞬间提升室内湿度至舒适范围。无论是干燥的冬季空调房还是炎夏的冷气环境，都能为您提供持续、健康的湿润空气。',
        '我们相信好的产品设计应该融入生活的每一个细节。从超静音运作到智能断电保护，每一个功能都经过精心设计，只为给您带来最舒适的使用体验。',
      ],
    },
    {
      type: 'highlights',
      layout: 'full-width',
      heading: '核心优势一览',
      items: [
        { icon: '🔇', title: '近乎无声', description: '运行噪音低于 30dB，比翻书声还轻柔，不会打扰您的工作和休息。' },
        { icon: '🔋', title: '超长续航', description: '300ml 大容量水箱可持续喷雾 8-10 小时，一整晚的湿润呵护无需中途加水。' },
        { icon: '🛡️', title: '智能安全', description: '内置水位感应系统，水量不足时自动断电，杜绝干烧隐患，让您使用更安心。' },
        { icon: '✨', title: '梦幻氛围', description: '7 色 LED 夜灯自由切换，柔和光晕营造温馨睡眠环境，也是完美的床头小夜灯。' },
      ],
    },
    {
      type: 'comparison',
      layout: 'standard',
      heading: 'AeroLife vs 普通加湿器',
      columns: ['普通加湿器', 'AeroLife 加湿器'],
      rows: [
        { feature: '噪音水平', values: [{ text: '> 45dB', check: false }, { text: '< 30dB', check: true, highlight: true }] },
        { feature: '续航时间', values: [{ text: '4-6 小时', check: false }, { text: '8-10 小时', check: true, highlight: true }] },
        { feature: '安全保护', values: [{ text: '仅基本', check: false }, { text: '智能断电+过热保护', check: true }] },
        { feature: '便携性', values: [{ text: '需插电', check: false }, { text: 'USB 兼容', check: true, highlight: true }] },
        { feature: '附加功能', values: [{ text: '单一模式', check: false }, { text: '双模式+夜灯', check: true }] },
      ],
    },
    {
      type: 'text',
      layout: 'full-width',
      heading: '适用场景',
      content: `<p><strong>🏠 卧室：</strong>超静音设计确保您的睡眠不受干扰，配合柔和夜灯营造舒适入睡环境。</p>
<p><strong>💼 办公室：</strong>小巧机身不占桌面空间，USB 供电随时可用，缓解空调房的干燥不适。</p>
<p><strong>👶 婴儿房：</strong>无任何化学添加物，纯物理加湿方式，给宝宝最纯净的湿润空气。</p>
<p><strong>✈️ 旅行出差：</strong>轻巧便携，兼容充电宝供电，酒店房间也能享受家的湿润舒适。</p>`,
    },
    {
      type: 'image-text',
      layout: 'standard',
      image_position: 'right',
      heading: '技术规格',
      image_label: '参数信息图',
      paragraphs: [
        '容量：300ml | 尺寸：140×85×85mm | 重量：280g',
        '电源：USB 5V/1A | 功率：5W | 噪音：<30dB',
        '材质：ABS 环保塑料 | 水箱：食品级硅胶',
        '认证：CE / FCC / RoHS | 质保：12个月',
      ],
    },
  ],
  seo_keywords: ['portable humidifier', 'mini humidifier', 'quiet humidifier', 'usb humidifier', 'bedroom humidifier', 'cool mist humidifier'],
  brand_story: 'AeroLife 成立于 2020 年，致力于通过创新科技改善人们的居家生活环境。我们的每一款产品都经过严格的质量检测和用户体验优化，只为让全球用户享受到更健康、更舒适的日常生活。',
}

// ====== A+ 描述归一化：兼容 execute 返回的 {description.sections} 与组件内置 {modules[]} ======
const normalizeModules = (): any[] => {
  // 优先直接模块结构
  if (Array.isArray(resultData.modules) && resultData.modules.length) return resultData.modules
  // executeDescGen 旧结构：description.sections[{heading,content}] → text 模块
  const sections = resultData.description?.sections
  if (Array.isArray(sections) && sections.length) {
    return sections.map((s: any) => ({ type: 'text', layout: 'full-width', heading: s.heading, content: s.content }))
  }
  return []
}

// ====== 响应式编辑宿主 ======
// 把 AI 生成模块深拷贝进响应式数组，供就地 v-model 编辑；保存时从该数组写回
const modules = ref<any[]>([])
function seedModules() {
  modules.value = JSON.parse(JSON.stringify(normalizeModules()))
}
watch(() => props.data, () => seedModules(), { immediate: true })
// 渲染/统计统一走响应式 modules（ref 在模板自动解包）
const displayModules = modules

// 顶层品牌/字数（execute 结构无时用默认）
const displayBrandName = computed(() => resultData.brand_name || 'YOUR BRAND')
const displayBrandSlogan = computed(() => resultData.brand_slogan || 'Quality You Can Trust')
const displayWordCount = computed(() => {
  const arr = displayModules.value || []
  return resultData.word_count || arr.reduce((n: number, m: any) => n + String(m.content || m.heading || '').length, 0) || 800
})
const displaySeoKeywords = computed(() => resultData.seo_keywords || [])

// ====== 模块编辑方法 ======
const moduleTypeLabel = (t: string) => (
  { text: '文本', 'image-text': '图文混排', comparison: '对比表格', highlights: '要点列表' }[t] || t
)
const addableModuleTypes = [
  { label: '＋ 文本模块', value: 'text' },
  { label: '＋ 图文混排', value: 'image-text' },
  { label: '＋ 要点列表', value: 'highlights' },
  { label: '＋ 对比表格', value: 'comparison' },
]
const newModuleType = ref<string | undefined>(undefined)

const addModule = (type: string) => {
  const empty: any = { type, layout: 'standard', heading: '' }
  if (type === 'text') empty.content = '<p></p>'
  else if (type === 'image-text') { empty.image_position = 'left'; empty.image_label = ''; empty.paragraphs = [''] }
  else if (type === 'highlights') { empty.items = [{ icon: '✨', title: '', description: '' }] }
  else if (type === 'comparison') { empty.columns = ['本产品']; empty.rows = [{ feature: '', values: [{ text: '', check: true, highlight: true }] }] }
  displayModules.value.push(empty)
  newModuleType.value = undefined
  message.success('已新增模块，可直接编辑')
}

const removeModule = (idx: number) => {
  displayModules.value.splice(idx, 1)
  message.success('已删除该模块')
}

const addParagraph = (module: any) => {
  if (!module.paragraphs) module.paragraphs = []
  module.paragraphs.push('')
}
const removeParagraph = (module: any, idx: number) => {
  module.paragraphs.splice(idx, 1)
}
const addHighlight = (module: any) => {
  if (!module.items) module.items = []
  module.items.push({ icon: '✨', title: '', description: '' })
}
const removeHighlight = (module: any, idx: number) => {
  module.items.splice(idx, 1)
}


const copyFullContent = () => {
  let text = ''
  displayModules.value.forEach((m: any) => {
    if (m.type === 'text') {
      text += `## ${m.heading}\n${m.content.replace(/<[^>]*>/g, '')}\n\n`
    } else if (m.type === 'image-text') {
      text += `## ${m.heading}\n${m.paragraphs.join('\n')}\n\n`
    }
  })
  navigator.clipboard.writeText(text)
  message.success('内容已复制到剪贴板')
}

const exportHTML = () => {
  message.info('导出功能开发中...')
}

const regenerate = () => {
  message.info('正在重新生成...')
}

// ====== 应用到当前产品 Listing（写回 A+ Content）======
const handleSaveToProduct = async () => {
  if (!productId.value) return
  saving.value = true
  try {
    // 将整个 A+ 描述结构写回产品的 generated_a_plus
    const aPlus = {
      brand_name: displayBrandName.value,
      modules: displayModules.value,
      style: resultData.style,
      word_count: displayWordCount.value,
      seo_keywords: displaySeoKeywords.value,
    }
    await productStore.updateListing(productId.value, {
      generated_a_plus: aPlus,
      generated_at: new Date().toISOString(),
      version: 1,
    })
    message.success(`已应用到当前产品 Listing（A+ Content ${displayModules.value.length} 模块）`)
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.desc-generator-result {
  background: var(--bg-elevated);
  border-radius: 8px;
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: #fff;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.result-icon { font-size: 28px; }
.header-info h3 { margin: 0; font-size: 16px; font-weight: 600; }
.subtitle { margin: 2px 0 0; font-size: 12px; opacity: 0.85; }

/* 内容预览 */
.content-preview {
  padding: 20px;
  max-height: 600px;
  overflow-y: auto;
}

/* 品牌横幅 */
.brand-banner {
  margin-bottom: 20px;
  border-radius: 8px;
  overflow: hidden;
}

.banner-placeholder {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  padding: 24px;
  text-align: center;
  color: #fff;
}

.brand-name {
  display: block;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 4px;
  margin-bottom: 4px;
}

.brand-slogan {
  font-size: 12px;
  opacity: 0.7;
  letter-spacing: 2px;
}

/* 内容模块 */
.content-modules {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 模块编辑工具栏 + 字段区 */
.module-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: var(--bg-base);
  border-bottom: 1px solid #f0f0f0;
}
.module-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.module-field {
  padding: 10px 16px 0;
}
.module-field label {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}
.field-input {
  border: 1px dashed #d9d9d9 !important;
  border-radius: 4px;
}
.field-input:focus-within,
.field-input:focus {
  border: 1px solid #1890ff !important;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.1);
}
.para-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.add-module-select {
  width: 100%;
  border-style: dashed;
}

.content-module {
  background: var(--bg-elevated);
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: hidden;
}

.module-header {
  padding: 14px 18px;
  background: var(--bg-base);
  border-bottom: 1px solid #f0f0f0;
}

.module-header h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.module-body {
  padding: 16px 18px;
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-secondary);
}

.module-body :deep(p) {
  margin: 0 0 10px;
}

.module-body :deep(p:last-child) {
  margin-bottom: 0;
}

/* 图文混排 */
.it-layout {
  display: grid;
  gap: 0;
}

.it-layout.left { grid-template-columns: 180px 1fr; }
.it-layout.right { grid-template-columns: 1fr 180px; }

.it-image {
  background: var(--bg-base);
  display: flex;
  align-items: center;
  justify-content: center;
}

.it-layout.right .it-image {
  order: 2;
}

.img-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: var(--text-disabled);
  font-size: 11px;
  padding: 20px;
}

.it-text {
  padding: 18px;
}

.it-text h4 {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.it-text p {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.it-text p:last-child {
  margin-bottom: 0;
}

/* 对比表格 */
.comp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.comp-table th {
  background: var(--bg-base);
  padding: 10px 12px;
  text-align: center;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid #f0f0f0;
}

.comp-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
  text-align: center;
}

.feature-name {
  text-align: left !important;
  font-weight: 500;
  color: var(--text-primary);
}

.comp-table td.highlight {
  background: #f6ffed;
  color: #389e0d;
  font-weight: 600;
}

.check-icon {
  color: #52c41a;
  margin-left: 4px;
}

/* 要点列表 */
.hl-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.hl-list li {
  display: flex;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid #f5f5f5;
}

.hl-list li:last-child {
  border-bottom: none;
}

.hl-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.hl-content strong {
  display: block;
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.hl-content p {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

/* 品牌底部 */
.brand-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  border-radius: 8px;
  margin-top: 20px;
}

.footer-logo {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  border-radius: 50%;
  font-size: 20px;
  font-weight: 700;
  color: #1890ff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.footer-text h4 {
  margin: 0 0 4px;
  font-size: 15px;
  color: var(--text-primary);
}

.footer-text p {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* 统计栏 */
.content-stats {
  display: flex;
  justify-content: space-around;
  padding: 14px 20px;
  background: var(--bg-base);
  border-top: 1px solid #f0f0f0;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.stat-item .anticon {
  font-size: 16px;
  color: #1890ff;
}

.s-label { font-size: 11px; }
.s-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

/* 操作栏 */
.action-bar {
  padding: 14px 20px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  justify-content: center;
}
</style>
