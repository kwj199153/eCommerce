<template>
  <div class="bullet-generator-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">✨</span>
        <div>
          <h3>五点描述生成</h3>
          <p class="subtitle">高转化的卖点提炼与情感触发</p>
        </div>
      </div>
      <div class="header-actions">
        <!-- 产品库模式：写回当前产品 listing 的五点描述 -->
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

    <!-- 五点描述列表 -->
    <div class="bullets-container">
      <div class="bullets-toolbar" v-if="editableBullets.length">
        <a-space>
          <a-button size="small" type="link" @click="addBullet">
            <PlusOutlined /> 新增一条
          </a-button>
          <a-button size="small" type="text" @click="resetBullets" :disabled="!isBulletsEdited" title="还原为 AI 生成内容">
            <UndoOutlined /> 还原
          </a-button>
        </a-space>
      </div>
      <div
        v-for="(bullet, idx) in editableBullets"
        :key="idx"
        class="bullet-card"
      >
        <div class="bullet-header">
          <span class="bullet-number">{{ idx + 1 }}</span>
          <div class="bullet-edit-head">
            <a-select
              v-model:value="bullet.category"
              size="small"
              :options="categoryOptions"
              style="width: 110px"
              placeholder="卖点分类"
            />
            <a-tag
              :color="bullet.emotion_trigger ? 'purple' : 'default'"
              size="small"
            >
              {{ bullet.emotion_trigger ? '情感触发' : '功能陈述' }}
            </a-tag>
          </div>
          <div class="bullet-header-actions">
            <a-button type="text" size="small" @click="copyBullet(idx)" title="复制本条">
              <CopyOutlined />
            </a-button>
            <a-button type="text" size="small" danger @click="removeBullet(idx)" title="删除本条">
              <DeleteOutlined />
            </a-button>
          </div>
        </div>
        <a-textarea
          v-model:value="bullet.title"
          class="bullet-title-editor"
          :auto-size="{ minRows: 1, maxRows: 3 }"
          placeholder="卖点标题（如：【超静音】...）"
        />
        <a-textarea
          v-model:value="bullet.content"
          class="bullet-content-editor"
          :auto-size="{ minRows: 2, maxRows: 6 }"
          placeholder="卖点正文"
        />
        <div class="bullet-footer">
          <span class="char-count">{{ (bullet.title + bullet.content).length }} 字符</span>
          <span class="keywords-used">
            <KeyOutlined /> {{ bullet.keywords_used?.length || 0 }} 关键词
          </span>
        </div>
      </div>
      <a-empty
        v-if="!editableBullets.length"
        description="暂无五点，点击上方「新增一条」开始编辑"
      />
    </div>

    <!-- 卖点分析总览 -->
    <div class="analysis-overview">
      <div class="overview-title">
        <BarChartOutlined /> 卖点策略分析
      </div>
      <div class="overview-grid">
        <div class="overview-item">
          <div class="item-label">核心卖点</div>
          <div class="item-value primary">{{ resultData.core_selling_points }}</div>
          <div class="item-desc">直接驱动购买决策</div>
        </div>
        <div class="overview-item">
          <div class="item-label">差异化卖点</div>
          <div class="item-value success">{{ resultData.differentiation_points }}</div>
          <div class="item-desc">区别于竞争对手</div>
        </div>
        <div class="overview-item">
          <div class="item-label">信任构建点</div>
          <div class="item-value warning">{{ resultData.trust_builders }}</div>
          <div class="item-desc">消除购买顾虑</div>
        </div>
        <div class="overview-item">
          <div class="item-label">场景化卖点</div>
          <div class="item-value info">{{ resultData.scenario_points }}</div>
          <div class="item-desc">激发使用想象</div>
        </div>
      </div>
    </div>

    <!-- 情感触发词统计 -->
    <div class="emotion-stats" v-if="resultData.emotion_triggers?.length">
      <div class="stats-title">
        <HeartOutlined /> 情感触发词库
      </div>
      <div class="emotion-cloud">
        <span
          v-for="(trigger, idx) in resultData.emotion_triggers"
          :key="idx"
          class="emotion-tag"
          :style="{ fontSize: trigger.size + 'px', opacity: 0.6 + trigger.impact * 0.4 }"
        >
          {{ trigger.word }}
        </span>
      </div>
    </div>

    <!-- A9 算法优化提示 -->
    <div class="a9-tips">
      <div class="tips-title">
        <ThunderboltOutlined /> A9 算法优化检查
      </div>
      <div class="tips-list">
        <div
          v-for="(tip, idx) in resultData.a9_checks"
          :key="idx"
          class="tip-item"
          :class="tip.status"
        >
          <CheckCircleFilled v-if="tip.status === 'pass'" class="tip-icon pass" />
          <WarningFilled v-else-if="tip.status === 'warn'" class="tip-icon warn" />
          <CloseCircleFilled v-else class="tip-icon fail" />
          <span class="tip-text">{{ tip.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  CloseOutlined, CopyOutlined, KeyOutlined, SaveOutlined,
  PlusOutlined, DeleteOutlined, UndoOutlined,
  BarChartOutlined, HeartOutlined, ThunderboltOutlined,
  CheckCircleFilled, WarningFilled, CloseCircleFilled,
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

// 数据来源模式（决定是否显示「应用到当前产品 Listing」）
const sourceMode = computed(() => props.data?._source || 'manual')
const productId = computed(() => props.data?.product_id)

const resultData = props.data || {
  bullets: [
    {
      category: '核心功能',
      emotion_trigger: true,
      title: '【超静音设计】近乎无声的加湿体验',
      content: '采用先进的超声波雾化技术，运行噪音低于 30dB，比图书馆还安静。无论是宝宝安睡、办公专注还是夜间休息，都不会被打扰。让您享受湿润空气的同时，保持宁静的生活环境。',
      char_count: 98,
      keywords_used: ['ultrasonic', 'quiet', 'noise level'],
    },
    {
      category: '便捷性',
      emotion_trigger: true,
      title: '【USB 便携】随时随地享受湿润空气',
      content: '支持 USB 供电，兼容笔记本、充电宝、车载充电器等多种电源。轻巧的机身设计方便携带，无论是出差旅行、办公室桌面还是卧室床头，都能轻松使用。300ml 大容量水箱可持续喷雾 8-10 小时。',
      char_count: 95,
      keywords_used: ['USB', 'portable', 'travel', '300ml'],
    },
    {
      category: '智能安全',
      emotion_trigger: false,
      title: '【智能保护】缺水自动断电更安心',
      content: '内置智能水位感应系统，当水量不足时会自动关闭电源，杜绝干烧隐患。过热保护装置确保长时间使用的安全性。通过 CE、FCC、RoHS 多项安全认证，让家人使用更放心。',
      char_count: 88,
      keywords_used: ['auto shut-off', 'safety', 'certified'],
    },
    {
      category: '氛围营造',
      emotion_trigger: true,
      title: '【梦幻夜灯】柔和光晕伴您入眠',
      content: '内置 7 色 LED 夜灯，可自由切换或固定喜欢的颜色。柔和的光线营造出温馨舒适的睡眠氛围，也可作为小夜灯使用。灯光亮度可调节，不刺眼不影响睡眠质量。',
      char_count: 78,
      keywords_used: ['night light', 'LED', '7 colors'],
    },
    {
      category: '品质承诺',
      emotion_trigger: false,
      title: '【品质保障】无忧售后 + 精美包装',
      content: '每台加湿器出厂前都经过严格的质量检测。提供 12 个月质保服务，30 天无理由退换。精美礼盒包装，是送礼自用的理想选择。如有任何问题，专业客服团队 24 小时内响应。',
      char_count: 86,
      keywords_used: ['warranty', 'gift box', 'customer service'],
    },
  ],
  core_selling_points: 2,
  differentiation_points: 1,
  trust_builders: 1,
  scenario_points: 1,
  emotion_triggers: [
    { word: '超静音', impact: 0.95, size: 18 },
    { word: '近乎无声', impact: 0.88, size: 16 },
    { word: '随时随地', impact: 0.82, size: 15 },
    { word: '安心', impact: 0.90, size: 17 },
    { word: '梦幻', impact: 0.75, size: 14 },
    { word: '温馨舒适', impact: 0.78, size: 14 },
    { word: '无忧', impact: 0.85, size: 16 },
    { word: '精致生活', impact: 0.70, size: 13 },
    { word: '呵护', impact: 0.87, size: 16 },
    { word: '宁静', impact: 0.83, size: 15 },
  ],
  a9_checks: [
    { status: 'pass', message: '全部 5 点均包含核心关键词' },
    { status: 'pass', message: '每个卖点都有明确的功能利益点' },
    { status: 'pass', message: '首字母大写格式正确' },
    { status: 'warn', message: '第 3 点字符数偏少（建议 90+）' },
    { status: 'pass', message: '避免使用特殊符号和表情' },
    { status: 'pass', message: '无夸大宣传用语（Best, #1 等）' },
  ],
}

// ====== 五点归一化：兼容 execute 返回的 {point,emoji} 与组件内置 {title,content} ======
const normalizeBullet = (b: any) => {
  if (!b) return { category: '', emotion_trigger: false, title: '', content: '', char_count: 0, keywords_used: [] }
  // 已结构化
  if (b.title != null && b.content != null) {
    return {
      category: b.category || '功能陈述',
      emotion_trigger: !!b.emotion_trigger,
      title: b.title,
      content: b.content,
      char_count: b.char_count || String(b.content).length,
      keywords_used: b.keywords_used || [],
    }
  }
  // point 形如【FEATURE】desc → title=【FEATURE】, content=desc
  if (b.point != null) {
    const m = String(b.point).match(/^(【[^】]*】)\s*(.*)$/s)
    const title = m ? m[1] : ''
    const content = m ? m[2] : String(b.point)
    return {
      category: b.category || '功能陈述',
      emotion_trigger: !!b.emotion_trigger,
      title,
      content,
      char_count: b.char_count || content.length,
      keywords_used: [],
    }
  }
  return { category: '', emotion_trigger: false, title: '', content: '', char_count: 0, keywords_used: [] }
}
// 基线（AI 生成原值），供还原使用
const getBaselineBullets = () => (resultData.bullets || []).map(normalizeBullet)

// ====== 可编辑五点数组 ======
// 每条 title/content/category 可改，可新增/删除；保存时用此编辑后的内容写回
const editableBullets = ref<any[]>([])
const categoryOptions = ['核心功能', '便捷性', '智能安全', '氛围营造', '品质承诺'].map(v => ({ label: v, value: v }))

function seedEditableBullets() {
  editableBullets.value = getBaselineBullets().map((b: any) => ({
    category: b.category,
    emotion_trigger: !!b.emotion_trigger,
    title: b.title,
    content: b.content,
    char_count: b.char_count,
    keywords_used: (b.keywords_used || []).slice(),
  }))
}

// props.data 首次就绪 / 重新生成时，以 AI 基线填充可编辑区
watch(
  () => props.data,
  () => seedEditableBullets(),
  { immediate: true }
)

// 是否相对基线被改动过（标题/正文/数量任一变化）
const isBulletsEdited = computed(() => {
  const base = getBaselineBullets()
  if (base.length !== editableBullets.value.length) return true
  return editableBullets.value.some((b, i) => b.title !== base[i]?.title || b.content !== base[i]?.content)
})

const resetBullets = () => seedEditableBullets()

const addBullet = () => {
  editableBullets.value.push({
    category: '核心功能',
    emotion_trigger: false,
    title: '',
    content: '',
    char_count: 0,
    keywords_used: [],
  })
}

const removeBullet = (idx: number) => {
  editableBullets.value.splice(idx, 1)
  message.success(`已删除第 ${idx + 1} 点`)
}

const copyBullet = (idx: number) => {
  const bullet = editableBullets.value[idx]
  navigator.clipboard.writeText(`${bullet.title}\n${bullet.content}`)
  message.success(`第 ${idx + 1} 点已复制`)
}

// ====== 应用到当前产品 Listing ======
const handleSaveToProduct = async () => {
  if (!productId.value) return
  // 过滤掉标题正文全空的无意义条目
  const bullets = editableBullets.value
    .filter((b: any) => (b.title || '').trim() || (b.content || '').trim())
    .map((b: any) => ({ title: (b.title || '').trim(), content: (b.content || '').trim() }))
  if (!bullets.length) return message.warning('请至少保留一条有效的五点描述')

  saving.value = true
  try {
    await productStore.updateListing(productId.value, {
      generated_bullets: bullets,
      generated_at: new Date().toISOString(),
      version: 1,
    })
    message.success(`已应用到当前产品 Listing（五点×${bullets.length}）`)
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.bullet-generator-result {
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
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
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

/* 五点列表 */
.bullets-container {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 500px;
  overflow-y: auto;
}

.bullet-card {
  background: var(--bg-base);
  border-radius: 8px;
  padding: 14px 16px;
  border-left: 3px solid #f5576c;
  transition: transform 0.2s, box-shadow 0.2s;
}

.bullet-card:hover {
  transform: translateX(4px);
  box-shadow: 0 2px 8px rgba(245, 87, 108, 0.15);
}

.bullet-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

/* 顶部新增/还原工具条 */
.bullets-toolbar {
  display: flex;
  justify-content: flex-end;
}

/* 每条头部：分类下拉靠左、操作按钮靠右 */
.bullet-edit-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.bullet-header-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

/* 卖点标题 / 正文可编辑 textarea */
.bullet-title-editor {
  background: var(--bg-elevated);
  border-radius: 4px;
  border: 1px dashed #d9d9d9;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  padding: 4px 8px;
  margin-bottom: 6px;
  line-height: 1.5;
}
.bullet-title-editor:focus-within {
  border: 1px solid #f5576c;
  box-shadow: 0 0 0 2px rgba(245, 87, 108, 0.1);
}

.bullet-content-editor {
  background: var(--bg-elevated);
  border-radius: 4px;
  border: 1px dashed #d9d9d9;
  font-size: 13px;
  color: var(--text-secondary);
  padding: 4px 8px;
  line-height: 1.6;
}
.bullet-content-editor:focus-within {
  border: 1px solid #f5576c;
  box-shadow: 0 0 0 2px rgba(245, 87, 108, 0.1);
}

.bullet-number {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5576c;
  color: #fff;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
}

.bullet-category {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.bullet-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.bullet-body {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

.bullet-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-disabled);
}

/* 分析概览 */
.analysis-overview {
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
  background: var(--bg-base);
}

.overview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.overview-item {
  text-align: center;
  padding: 10px;
  background: var(--bg-elevated);
  border-radius: 6px;
}

.item-label {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.item-value {
  font-size: 22px;
  font-weight: 700;
}

.item-value.primary { color: #f5576c; }
.item-value.success { color: #52c41a; }
.item-value.warning { color: #faad14; }
.item-value.info { color: #1890ff; }

.item-desc {
  font-size: 10px;
  color: var(--text-disabled);
  margin-top: 2px;
}

/* 情感词云 */
.emotion-stats {
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
}

.stats-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.emotion-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 12px;
  background: linear-gradient(135deg, #fef6f8 0%, #fff5f7 100%);
  border-radius: 8px;
}

.emotion-tag {
  color: #c41d7a;
  font-weight: 600;
  cursor: default;
  white-space: nowrap;
}

/* A9 提示 */
.a9-tips {
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
}

.tips-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.tips-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tip-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
}

.tip-icon {
  font-size: 14px;
}

.tip-icon.pass { color: #52c41a; }
.tip-icon.warn { color: #faad14; }
.tip-icon.fail { color: #ff4d4f; }

.tip-text { color: var(--text-secondary); }
</style>
