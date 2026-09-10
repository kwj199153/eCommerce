<template>
  <div class="title-generator-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">📝</span>
        <div>
          <h3>{{ isSimplified ? '短标题生成' : '标题生成' }}</h3>
          <p class="subtitle">{{ sourceMode === 'product' ? '基于当前产品生成 / 修改标题' : '基于手动输入生成标题' }}</p>
        </div>
      </div>
      <div class="header-actions">
        <!-- 产品库模式：覆盖/更新当前产品的 Listing 字段 -->
        <a-button
          v-if="sourceMode === 'product' && productId"
          type="primary"
          size="small"
          @click="handleSaveToProduct"
          :loading="saving"
        >
          <SaveOutlined /> 应用到当前产品 Listing
        </a-button>
        <!-- 手动模式：保存为产品库草稿（无归属产品） -->
        <a-button
          v-else-if="sourceMode === 'manual'"
          size="small"
          @click="handleSaveAsDraft"
          :loading="saving"
        >
          <PlusOutlined /> 保存为草稿
        </a-button>
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 主标题推荐 -->
    <div class="main-title-section">
      <div class="section-label">
        <CrownOutlined /> {{ isSimplified ? '推荐短标题' : '推荐主标题' }}
        <a-tag v-if="isSimplified" color="orange">{{ platformLabel }}</a-tag>
        <a-tag v-else color="blue">A9 优化</a-tag>
      </div>
      <div class="title-display">
        <a-textarea
          v-model:value="editingTitle"
          :auto-size="{ minRows: 2, maxRows: 6 }"
          :maxlength="isSimplified ? 40 : 200"
          show-count
          placeholder="可直接修改主标题，保存后将写入当前产品 Listing"
          class="title-editor"
        />
        <div class="title-meta">
          <span :class="['char-count', editingTitle.length > (isSimplified ? 40 : 200) ? 'warning' : 'ok']">
            {{ editingTitle.length }} / {{ isSimplified ? 40 : 200 }} 字符
          </span>
          <span class="word-count">{{ editingTitle.split(/\s+/).filter(Boolean).length }} 词</span>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="title-actions">
        <a-button type="primary" size="small" ghost @click="copyTitle">
          <CopyOutlined /> 复制标题
        </a-button>
        <a-button size="small" @click="regenerateTitle">
          <ReloadOutlined /> 重新生成
        </a-button>
        <a-button size="small" @click="resetEditingTitle" :disabled="!isTitleEdited">
          <UndoOutlined /> 还原推荐
        </a-button>
      </div>
    </div>

    <!-- 商品详情（Temu/Shopee 简化模式） -->
    <div class="detail-desc-section" v-if="isSimplified && resultData.detail_desc">
      <div class="section-label">
        <FileTextOutlined /> 商品详情
      </div>
      <div class="detail-desc-list">
        <div v-for="(sec, idx) in resultData.detail_desc.sections" :key="idx" class="detail-desc-item">
          <div class="detail-desc-heading">{{ sec.heading }}</div>
          <div class="detail-desc-content">{{ sec.content }}</div>
        </div>
      </div>
    </div>

    <!-- 五点描述（如有，仅亚马逊模式） -->
    <div class="bullets-section" v-if="!isSimplified && resultData.bullets?.length">
      <div class="section-label">
        <OrderedListOutlined /> 五点描述 (Bullet Points)
      </div>
      <div class="bullets-list">
        <div v-for="(bullet, idx) in resultData.bullets" :key="idx" class="bullet-item">
          <div class="bullet-emoji">{{ getBulletEmoji(idx) }}</div>
          <div class="bullet-content">
            <div class="bullet-title">{{ bullet.title }}</div>
            <div class="bullet-text">{{ bullet.content }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- A+ Content（如有，仅亚马逊模式） -->
    <div class="aplus-section" v-if="!isSimplified && resultData.a_plus_content">
      <div class="section-label">
        <FileTextOutlined /> A+ Content / EBC
      </div>
      <div class="aplus-preview">
        <div class="aplus-header">{{ resultData.a_plus_content.header || '产品故事' }}</div>
        <div class="aplus-body" v-html="resultData.a_plus_content.body"></div>
      </div>
    </div>

    <!-- 标题变体 -->
    <div class="variants-section" v-if="resultData.variants?.length">
      <div class="section-label">
        <SwapOutlined /> {{ isSimplified ? '短标题变体' : '标题变体' }}（{{ resultData.variants.length }} 个备选）
        <a-tooltip title="备选参考，不会自动替换主标题。如需采纳请点击「采纳为主标题」">
          <QuestionCircleOutlined class="variants-hint" />
        </a-tooltip>
      </div>
      <div class="variant-list">
        <div
          v-for="(variant, idx) in resultData.variants"
          :key="idx"
          class="variant-item"
        >
          <div class="variant-rank">#{{ idx + 1 }}</div>
          <div class="variant-text">{{ variant.title }}</div>
          <div class="variant-score">
            <a-progress
              :percent="variant.seo_score"
              :stroke-color="getScoreColor(variant.seo_score)"
              :show-info="false"
              size="small"
            />
            <span>{{ variant.seo_score }}</span>
          </div>
          <a-button size="small" type="link" @click="adoptVariant(idx)">
            <DownloadOutlined /> 采纳为主标题
          </a-button>
        </div>
      </div>
    </div>

    <!-- SEO 分析卡片 -->
    <div class="seo-analysis-grid">
      <div class="analysis-card">
        <div class="card-title">关键词覆盖</div>
        <div class="card-value">{{ resultData.keyword_coverage }}%</div>
        <div class="card-detail">
          覆盖 {{ resultData.keywords_matched }} / {{ resultData.keywords_total }} 个目标词
        </div>
        <a-progress
          :percent="resultData.keyword_coverage"
          :stroke-color="'#52c41a'"
          :show-info="false"
        />
      </div>

      <div class="analysis-card">
        <div class="card-title">可读性评分</div>
        <div class="card-value">{{ resultData.readability_score }}/10</div>
        <div class="card-detail">{{ getReadabilityLabel(resultData.readability_score) }}</div>
        <a-rate :value="Math.round(resultData.readability_score / 2)" disabled />
      </div>

      <div class="analysis-card">
        <div class="card-title">搜索排名潜力</div>
        <div class="card-value" :style="{ color: getScoreColor(resultData.rank_potential) }">
          {{ getRankLabel(resultData.rank_potential) }}
        </div>
        <div class="card-detail">基于竞品对比分析</div>
        <a-badge
          :status="resultData.rank_potential >= 80 ? 'success' : resultData.rank_potential >= 60 ? 'warning' : 'error'"
          :text="resultData.rank_potential >= 80 ? '强' : resultData.rank_potential >= 60 ? '中' : '弱'"
        />
      </div>

      <div class="analysis-card">
        <div class="card-title">品牌露出</div>
        <div class="card-value">{{ resultData.brand_position === 'front' ? '前置' : '后置' }}</div>
        <div class="card-detail">{{ resultData.brand_position === 'front' ? '利于品牌认知' : '利于 SEO 权重' }}</div>
        <a-switch
          :checked="resultData.brand_position === 'front'"
          checked-children="前置"
          un-checked-children="后置"
          disabled
        />
      </div>
    </div>

    <!-- 关键词分布 -->
    <div class="keywords-section">
      <div class="section-label">
        <KeyOutlined /> 核心关键词分布
      </div>
      <div class="keyword-tags">
        <a-tooltip v-for="(kw, idx) in resultData.core_keywords" :key="idx" :title="`搜索量: ${kw.search_volume} | 竞争: ${kw.competition}`">
          <a-tag
            :color="kw.placed_in_title ? 'blue' : 'default'"
            :class="{ 'not-placed': !kw.placed_in_title }"
          >
            {{ kw.word }}
            <span v-if="kw.placed_in_title" class="check-icon">✓</span>
          </a-tag>
        </a-tooltip>
      </div>
    </div>

    <!-- 改进建议 -->
    <div class="suggestions-section" v-if="resultData.suggestions?.length">
      <div class="section-label">
        <BulbOutlined /> 优化建议
      </div>
      <a-collapse ghost>
        <a-collapse-panel
          v-for="(sug, idx) in resultData.suggestions"
          :key="idx"
          :header="sug.title"
        >
          <p>{{ sug.description }}</p>
          <a-tag :color="sug.priority === 'high' ? 'red' : sug.priority === 'medium' ? 'orange' : 'blue'">
            {{ sug.priority === 'high' ? '高优先级' : sug.priority === 'medium' ? '中优先级' : '建议' }}
          </a-tag>
        </a-collapse-panel>
      </a-collapse>
    </div>

    <!-- 保存成功提示 Modal -->
    <a-modal
      v-model:open="saveSuccessVisible"
      title="保存成功"
      :footer="null"
      :width="420"
    >
      <div class="save-success-content">
        <a-result
          status="success"
          :title="saveSuccessTitle"
          :sub-title="saveSuccessSubTitle"
        >
          <template #extra>
            <a-space>
              <a-button @click="saveSuccessVisible = false">继续编辑</a-button>
              <a-button type="primary" @click="goToProductLibrary">去产品库查看</a-button>
            </a-space>
          </template>
        </a-result>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  CloseOutlined, CopyOutlined, ReloadOutlined,
  CrownOutlined, SwapOutlined, KeyOutlined, BulbOutlined,
  SaveOutlined, PlusOutlined, OrderedListOutlined, FileTextOutlined,
  UndoOutlined, DownloadOutlined, QuestionCircleOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useProductLibraryStore } from '@/stores/productLibrary'

const props = defineProps<{
  data: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'navigateTo', view: string): void
}>()

const productStore = useProductLibraryStore()
const saving = ref(false)
const saveSuccessVisible = ref(false)

// 判断数据来源模式
const sourceMode = computed(() => props.data?._source || 'manual')
const productId = computed(() => props.data?.product_id)

// 平台简化模式（Temu/Shopee）
const isSimplified = computed(() => props.data?.is_simplified === true)
const platformLabel = computed(() => {
  const mode = props.data?.platform_mode
  if (mode === 'temu') return 'Temu'
  if (mode === 'shopee') return 'Shopee'
  return '简化 Listing'
})

// Mock 数据（实际使用时从 props.data 获取）
const resultData = ref(props.data || generateMockResult())

// ====== 主标题可编辑 ======
// 推荐标题 = resultData.recommended_title；用户可编辑 editingTitle，保存时用 editingTitle
const editingTitle = ref(resultData.value.recommended_title || '')
// props.data 变化（例如重新生成）时同步基线
watch(() => resultData.value.recommended_title, (newVal) => {
  editingTitle.value = newVal || ''
})
// 还原按钮可用性：仅在用户改过且与基线不同时启用
const isTitleEdited = computed(() => editingTitle.value !== (resultData.value.recommended_title || ''))

const resetEditingTitle = () => {
  editingTitle.value = resultData.value.recommended_title || ''
  message.info('已还原为推荐标题')
}

// 采纳备选为主标题
const adoptVariant = (idx: number) => {
  const v = resultData.value.variants?.[idx]
  if (!v) return
  editingTitle.value = v.title
  message.success(`已采纳 #${idx + 1} 备选为主标题`)
}

function generateMockResult() {
  return {
    _source: 'manual',
    recommended_title: 'Portable Mini Humidifier for Bedroom - USB Cool Mist Ultrasonic Air Humidifier with Night Light, Quiet Operation for Home Office Baby Room Travel, Auto Shut-Off, 2 Mist Modes, 300ml Water Tank',
    char_count: 189,
    word_count: 32,
    keyword_coverage: 92,
    keywords_matched: 11,
    keywords_total: 12,
    readability_score: 8.5,
    rank_potential: 85,
    brand_position: 'back',
    bullets: [
      { title: '超静音设计', content: '采用先进的超声波雾化技术，运行噪音低于30dB，确保您和家人的睡眠不受干扰，非常适合卧室、婴儿房和办公室使用。' },
      { title: '双档雾量调节', content: '提供细腻雾量和强劲雾量两种模式，可根据季节和个人需求自由调节，满足不同湿度环境要求。' },
      { title: '七彩夜灯氛围', content: '内置柔和LED夜灯，提供7种颜色可选，营造温馨舒适的睡眠氛围，同时可作为小夜灯使用。' },
      { title: '智能安全保护', content: '配备缺水自动断电功能，当水箱水位过低时自动关闭电源，确保使用安全无忧。' },
      { title: '便携大容量', content: '300ml大容量水箱可持续工作8-12小时，USB供电设计方便携带，适合旅行、车内等多场景使用。' },
    ],
    a_plus_content: null,
    core_keywords: [
      { word: 'Portable Humidifier', search_volume: 45000, competition: 'high', placed_in_title: true },
      { word: 'Mini Humidifier', search_volume: 32000, competition: 'medium', placed_in_title: true },
      { word: 'Bedroom Humidifier', search_volume: 18000, competition: 'low', placed_in_title: true },
      { word: 'USB Humidifier', search_volume: 12000, competition: 'low', placed_in_title: true },
      { word: 'Cool Mist', search_volume: 28000, competition: 'high', placed_in_title: true },
      { word: 'Ultrasonic', search_volume: 15000, competition: 'medium', placed_in_title: true },
      { word: 'Quiet Humidifier', search_volume: 9500, competition: 'low', placed_in_title: true },
      { word: 'Auto Shut-Off', search_volume: 8000, competition: 'low', placed_in_title: true },
      { word: 'Night Light', search_volume: 22000, competition: 'medium', placed_in_title: true },
    ],
    variants: [
      { title: 'USB Portable Humidifier - Small Cool Mist Humidifier for Bedroom with LED Night Light & Auto Shut Off', seo_score: 88 },
      { title: 'Mini Cool Mist Humidifier Portable for Bedroom - USB Personal Humidifier with Night Light, Auto Shut-Off', seo_score: 85 },
      { title: 'Quiet Portable Humidifier for Bedroom & Office - USB Ultrasonic Cool Mist Humidifier with Night Light', seo_score: 82 },
    ],
    suggestions: [
      { title: '字符数接近上限', description: '当前 189/200 字符，移动端可能被截断。建议精简形容词或移至五点描述。', priority: 'high' as const },
      { title: '添加 "Large Capacity" 关键词', description: '竞品分析显示 500ml+ 容量的产品转化率高出 23%。', priority: 'medium' as const },
    ],
  }
}

// ====== 写回产品库（产品库模式）=======
const handleSaveToProduct = async () => {
  if (!productId.value) return

  saving.value = true
  try {
    // 标题取自用户编辑后的 editingTitle（v-model 主标题 textarea）
    const finalTitle = (editingTitle.value || '').trim()
    if (!finalTitle) {
      message.warning('主标题不能为空')
      saving.value = false
      return
    }
    // 重新计算字符/词数（用户编辑后元数据同步）
    const charCount = finalTitle.length
    const wordCount = finalTitle.split(/\s+/).filter(Boolean).length

    // 构建要更新的 Listing 数据
    const listingData = {
      generated_title: finalTitle,
      generated_bullets: resultData.value.bullets,
      generated_a_plus: resultData.value.a_plus_content,
      seo_score: resultData.value.keyword_coverage,
      generated_at: new Date().toISOString(),
      version: 1,
      // 同步写入字符/词数（前端展示与后端持久化对齐）
      title_char_count: charCount,
      title_word_count: wordCount,
    }

    // 调用 store 更新产品
    await productStore.updateListing(productId.value, listingData)

    saveSuccessTitle.value = '已应用到当前产品 Listing'
    saveSuccessSubTitle.value = `标题、五点描述已更新到「${props.data?.product_name || props.data?.product_title || '该商品'}」，可在产品库中查看`
    saveSuccessVisible.value = true
    message.success('已保存到产品档案')
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}

// ====== 保存为草稿（手动模式）======
const handleSaveAsDraft = async () => {
  saving.value = true
  try {
    // 从生成结果构建草稿数据
    const draftProduct = {
      title: extractProductName(resultData.value.recommended_title),
      asin: generateTempASIN(),
      brand: props.data?.brand || '',
      category: props.data?.category || '',
      site: props.data?.site || 'Amazon US',
      cost_price: props.data?.cost_price || 0,
      selling_price: props.data?.selling_price || 0,
      keywords: resultData.value.core_keywords.map((k: any) => k.word),
      listing_status: 'draft' as const,
      generated_title: resultData.value.recommended_title,
      generated_bullets: resultData.value.bullets,
      tags: ['AI生成'],
    }

    await productStore.addItem(draftProduct)

    saveSuccessTitle.value = '已保存为草稿'
    saveSuccessSubTitle.value = '商品已加入产品库（草稿状态），可前往完善 Listing 素材后上架'
    saveSuccessVisible.value = true
    message.success('已保存到产品库')
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}

const saveSuccessTitle = ref('')
const saveSuccessSubTitle = ref('')

const goToProductLibrary = () => {
  saveSuccessVisible.value = false
  emit('navigateTo', 'products')
}

// 辅助：从标题提取产品名
const extractProductName = (title: string): string => {
  return title.split('-')[0].trim().substring(0, 80)
}

// 辅助：生成临时 ASIN
const generateTempASIN = (): string => {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
  let asin = 'B0'
  for (let i = 0; i < 8; i++) asin += chars[Math.floor(Math.random() * chars.length)]
  return asin
}

const copyTitle = () => {
  const text = editingTitle.value || resultData.value.recommended_title
  navigator.clipboard.writeText(text)
  message.success('标题已复制到剪贴板')
}

const regenerateTitle = () => {
  message.info('正在重新生成...')
}

const getScoreColor = (score: number) => {
  if (score >= 80) return '#52c41a'
  if (score >= 60) return '#faad14'
  return '#ff4d4f'
}

const getReadabilityLabel = (score: number) => {
  if (score >= 8) return '优秀'
  if (score >= 6) return '良好'
  if (score >= 4) return '一般'
  return '需优化'
}

const getRankLabel = (potential: number) => {
  if (potential >= 80) return '强'
  if (potential >= 60) return '中'
  return '弱'
}

const getBulletEmoji = (idx: number) => {
  const emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
  return emojis[idx] || `${idx + 1}`
}
</script>

<style scoped>
.title-generator-result {
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-icon {
  font-size: 28px;
}

.header-info h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  opacity: 0.85;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.main-title-section {
  padding: 20px;
  border-bottom: 1px solid #f0f0f0;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #262626;
  margin-bottom: 12px;
}

.title-display {
  background: #f6f8fa;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}

/* 主标题可编辑 textarea：白底+蓝边，与背景区分 */
.title-editor {
  background: #fff;
  border-radius: 6px;
  border: 1px solid #d9e3f0;
  font-size: 15px;
  line-height: 1.6;
  color: #1a1a1a;
  font-weight: 500;
  padding: 4px 0;
}
.title-editor:focus-within {
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.15);
}

.title-meta {
  display: flex;
  gap: 16px;
  margin-top: 10px;
  font-size: 12px;
  color: #8c8c8c;
}

.char-count.ok { color: #52c41a; }
.char-count.warning { color: #faad14; }

.title-actions {
  display: flex;
  gap: 8px;
}

/* 五点描述 */
.bullets-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

/* 商品详情（Temu/Shopee 简化模式） */
.detail-desc-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.detail-desc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-desc-item {
  padding: 10px 12px;
  background: #fafafa;
  border-radius: 6px;
  border-left: 3px solid #fa8c16;
}

.detail-desc-heading {
  font-weight: 600;
  font-size: 13px;
  color: #262626;
  margin-bottom: 4px;
}

.detail-desc-content {
  font-size: 12px;
  color: #595959;
  line-height: 1.6;
  white-space: pre-wrap;
}

.bullets-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bullet-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: #fafafa;
  border-radius: 6px;
  border-left: 3px solid #1890ff;
}

.bullet-emoji {
  font-size: 16px;
  flex-shrink: 0;
}

.bullet-title {
  font-weight: 600;
  font-size: 13px;
  color: #262626;
  margin-bottom: 2px;
}

.bullet-text {
  font-size: 12px;
  color: #595959;
  line-height: 1.5;
}

/* A+ Content */
.aplus-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.aplus-preview {
  background: linear-gradient(135deg, #fef6e4 0%, #ffecd2 100%);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #ffe58f;
}

.aplus-header {
  font-size: 15px;
  font-weight: 600;
  color: #d48806;
  margin-bottom: 8px;
}

.aplus-body {
  font-size: 13px;
  color: #595959;
  line-height: 1.6;
}

/* 变体列表 */
.variants-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.variant-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.variant-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  transition: border-color 0.2s;
}
/* 备选区不再可点击切换 selected，仅浅灰边不再加 hover 蓝边避免暗示可点 */
.variant-item:hover {
  border-color: #e8e8e8;
}

/* 删除 .variant-item.selected 与 .variant-item.selected .variant-rank 误导样式 */

.variant-rank {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f0f0;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.variant-text {
  flex: 1;
  font-size: 13px;
  color: #434343;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.variant-score {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 100px;
  font-size: 12px;
  font-weight: 600;
}

.variants-hint {
  margin-left: 4px;
  color: #8c8c8c;
  font-size: 13px;
  cursor: help;
}

/* SEO 分析网格 */
.seo-analysis-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.analysis-card {
  background: #fafafa;
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}

.card-title {
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 8px;
}

.card-value {
  font-size: 20px;
  font-weight: 700;
  color: #262626;
  margin-bottom: 4px;
}

.card-detail {
  font-size: 11px;
  color: #bfbfbf;
  margin-bottom: 8px;
}

/* 关键词标签 */
.keywords-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.keyword-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.keyword-tags .ant-tag {
  margin: 0;
  cursor: default;
}

.not-placed {
  opacity: 0.5;
  text-decoration: line-through;
}

.check-icon {
  margin-left: 4px;
  color: #52c41a;
}

/* 建议区 */
.suggestions-section {
  padding: 16px 20px;
}

/* 保存成功弹窗 */
.save-success-content {
  padding: 16px 0;
}
</style>
