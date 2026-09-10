<template>
  <div class="ab-test-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-info">
        <span class="result-icon">🧪</span>
        <div>
          <h3>A/B 测试变体生成</h3>
          <p class="subtitle">{{ resultData.variants.length }} 个 Listing 版本 · {{ resultData.test_variable }} 为测试变量</p>
        </div>
      </div>
      <div class="header-actions">
        <a-button size="small" @click="$emit('close')">
          <CloseOutlined /> 关闭
        </a-button>
      </div>
    </div>

    <!-- 变体对比视图 -->
    <div class="variants-comparison">
      <div
        v-for="(variant, idx) in resultData.variants"
        :key="idx"
        class="variant-card"
        :class="{ 'is-control': idx === 0 }"
      >
        <div class="variant-badge">
          {{ idx === 0 ? '对照组 A' : `测试组 ${String.fromCharCode(65 + idx)}` }}
        </div>

        <!-- 标题对比 -->
        <div class="compare-section">
          <div class="section-label">标题</div>
          <div class="content-text">{{ variant.title }}</div>
          <div class="char-badge">{{ variant.title.length }} 字符</div>
        </div>

        <!-- 五点描述对比 -->
        <div class="compare-section">
          <div class="section-label">五点描述</div>
          <div class="bullets-list">
            <div v-for="(bullet, bidx) in variant.bullets" :key="bidx" class="mini-bullet">
              <span class="b-num">{{ bidx + 1 }}</span>
              {{ bullet }}
            </div>
          </div>
        </div>

        <!-- 价格对比 -->
        <div class="compare-section" v-if="variant.price">
          <div class="section-label">价格</div>
          <div class="price-display">${{ variant.price }}</div>
        </div>

        <!-- 主图策略 -->
        <div class="compare-section" v-if="variant.image_strategy">
          <div class="section-label">主图策略</div>
          <a-tag color="blue">{{ variant.image_strategy }}</a-tag>
        </div>

        <!-- 预测指标 -->
        <div class="variant-metrics">
          <div class="metric">
            <span class="m-label">预计 CTR</span>
            <span class="m-value" :style="{ color: getMetricColor(variant.predicted_ctr) }">
              {{ variant.predicted_ctr }}%
            </span>
          </div>
          <div class="metric">
            <span class="m-label">预计 CVR</span>
            <span class="m-value" :style="{ color: getMetricColor(variant.predicted_cvr * 10) }">
              {{ (variant.predicted_cvr * 100).toFixed(1) }}%
            </span>
          </div>
          <div class="metric">
            <span class="m-label">差异化度</span>
            <span class="m-value">{{ variant.differentiation_score }}/10</span>
          </div>
        </div>

        <!-- 操作 -->
        <div class="variant-actions">
          <a-button size="small" type="primary" ghost @click="applyVariant(idx)">
            应用此版本
          </a-button>
          <a-button size="small" @click="exportVariant(idx)">
            <DownloadOutlined /> 导出
          </a-button>
        </div>
      </div>
    </div>

    <!-- 差异高亮 -->
    <div class="diff-highlight">
      <div class="highlight-title">
        <DiffOutlined /> 版本差异分析
      </div>
      <table class="diff-table">
        <thead>
          <tr>
            <th>差异维度</th>
            <th>对照 A</th>
            <th v-for="(v, idx) in resultData.variants.slice(1)" :key="idx">
              测试 {{ String.fromCharCode(66 + idx) }}
            </th>
            <th>假设</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(diff, idx) in resultData.differences" :key="idx">
            <td class="dim-label">{{ diff.dimension }}</td>
            <td>{{ diff.control }}</td>
            <td v-for="(val, vi) in diff.test_values" :key="vi" class="changed-cell">
              {{ val }}
            </td>
            <td><a-tag :color="diff.hypothesis === 'positive' ? 'green' : 'orange'" size="small">
              {{ diff.hypothesis === 'positive' ? '正向' : '中性' }}
            </a-tag></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 测试建议 -->
    <div class="test-recommendation">
      <div class="rec-title">
        <ExperimentOutlined /> 测试执行建议
      </div>
      <div class="rec-content">
        <a-steps :current="0" size="small" direction="vertical">
          <a-step title="选择主变量" :description="`建议优先测试: ${resultData.recommended_test}`" />
          <a-step title="设置运行周期" description="建议至少运行 14 天以获得统计显著性" />
          <a-step title="确定样本量" description="每个版本至少需要 1000 次曝光 / 50 次转化" />
          <a-step title="监控指标" description="主要看 CTR 和转化率，次要看加购率和跳出率" />
          <a-step title="结果判定" description="置信度 >95% 时可判定胜出版本并全量上线" />
        </a-steps>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CloseOutlined, DownloadOutlined, DiffOutlined, ExperimentOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const props = defineProps<{
  data: any
}>()

defineEmits<{
  (e: 'close'): void
}>()

const resultData = props.data || {
  test_variable: '标题+首图',
  variants: [
    {
      title: 'Portable Mini Humidifier for Bedroom - USB Cool Mist Ultrasonic Air Humidifier with Night Light, Quiet Operation for Home Office Baby Room Travel, Auto Shut-Off, 2 Mist Modes, 300ml Water Tank',
      bullets: [
        '【超静音设计】近乎无声的加湿体验，噪音低于30dB',
        '【USB便携】支持多种电源，300ml大容量续航8-10小时',
        '【智能保护】缺水自动断电，多重安全认证',
        '【梦幻夜灯】7色LED柔和光晕，营造温馨氛围',
        '【品质保障】12个月质保，精美礼盒包装',
      ],
      price: 24.99,
      image_strategy: '白底主图+场景副图',
      predicted_ctr: 3.2,
      predicted_cvr: 0.145,
      differentiation_score: 7.5,
    },
    {
      title: 'USB Mini Humidifier Quiet for Bedroom & Office - Portable Cool Mist Humidifier with LED Night Light, Auto Shut-Off, Perfect for Baby Room Travel, 300ml Tank, 2 Mist Modes',
      bullets: [
        '【图书馆级静音】<30dB超低噪音，宝宝安睡不扰人',
        '【全能便携】USB/充电宝双供电，差旅办公必备',
        '【安全无忧】智能感应断电，CE/FCC/RoHS三重认证',
        '【氛围神器】7色呼吸灯+固定模式，夜间小帮手',
        '【送礼首选】12月质保+精美包装，开箱即惊喜',
      ],
      price: 26.99,
      image_strategy: '生活场景主图',
      predicted_ctr: 3.8,
      predicted_cvr: 0.138,
      differentiation_score: 8.5,
    },
    {
      title: 'Quiet Mini Humidifier for Bedroom - Small USB Personal Humidifier with Night Light & Auto Shut-Off, Cool Mist Air Moisturizer for Office Home Baby Travel, 300ml Water Tank, 2 Modes',
      bullets: [
        '比图书馆还安静——30dB以下超声波加湿技术',
        '一个充电宝就能用——真正的随身加湿伴侣',
        '忘记关机也不怕——智能水位感应自动断电保护',
        '夜晚的小确幸——柔和LED夜灯伴你入眠',
        '买得放心用得安心——12个月质保+30天无理由退换',
      ],
      price: 24.99,
      image_strategy: '人物使用图主图',
      predicted_ctr: 4.1,
      predicted_cvr: 0.152,
      differentiation_score: 9.2,
    },
  ],
  differences: [
    { dimension: '标题结构', control: '关键词堆叠', test_values: ['场景导向', '口语化'], hypothesis: 'positive' as const },
    { dimension: '品牌位置', control: '无品牌', test_values: ['无品牌', '无品牌'], hypothesis: 'neutral' as const },
    { dimension: '五点风格', control: '功能陈述', test_values: ['数字量化', '情感共鸣'], hypothesis: 'positive' as const },
    { dimension: '定价', control: '$24.99', test_values: ['$26.99', '$24.99'], hypothesis: 'neutral' as const },
    { dimension: '主图类型', control: '白底', test_values: ['场景', '人物'], hypothesis: 'positive' as const },
  ],
  recommended_test: '主图类型（白底 vs 场景 vs 人物使用）',
}

const getMetricColor = (value: number) => {
  if (value >= 4) return '#52c41a'
  if (value >= 3) return '#1890ff'
  return '#faad14'
}

const applyVariant = (idx: number) => {
  message.success(`已应用版本 ${idx === 0 ? 'A（对照）' : String.fromCharCode(65 + idx)}`)
}

const exportVariant = (idx: number) => {
  message.info(`正在导出版本 ${String.fromCharCode(65 + idx)}...`)
}
</script>

<style scoped>
.ab-test-result {
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
.result-icon { font-size: 28px; }
.header-info h3 { margin: 0; font-size: 16px; font-weight: 600; }
.subtitle { margin: 2px 0 0; font-size: 12px; opacity: 0.85; }

/* 变体卡片 */
.variants-comparison {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 20px;
  background: #fafbfc;
}

.variant-card {
  background: #fff;
  border-radius: 8px;
  border: 2px solid #f0f0f0;
  overflow: hidden;
  transition: border-color 0.2s;
}

.variant-card:hover {
  border-color: #1890ff;
}

.variant-card.is-control {
  border-color: #d9d9d9;
  position: relative;
}

.variant-card.is-control::after {
  content: '当前版本';
  position: absolute;
  top: 8px;
  right: -24px;
  background: #d9d9d9;
  color: #fff;
  font-size: 10px;
  padding: 2px 8px;
  transform: rotate(45deg);
}

.variant-badge {
  text-align: center;
  padding: 8px;
  font-size: 13px;
  font-weight: 600;
  background: #f5f5f5;
  color: #595959;
}

.compare-section {
  padding: 12px 14px;
  border-bottom: 1px dashed #f0f0f0;
}

.section-label {
  font-size: 11px;
  color: #8c8c8c;
  font-weight: 600;
  margin-bottom: 6px;
  text-transform: uppercase;
}

.content-text {
  font-size: 12px;
  line-height: 1.55;
  color: #434343;
  max-height: 60px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.char-badge {
  display: inline-block;
  margin-top: 4px;
  font-size: 10px;
  padding: 1px 6px;
  background: #f0f0f0;
  border-radius: 4px;
  color: #8c8c8c;
}

.bullets-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mini-bullet {
  font-size: 11px;
  line-height: 1.5;
  color: #595959;
  display: flex;
  gap: 4px;
}

.b-num {
  width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  background: #e6f7ff;
  color: #1890ff;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.price-display {
  font-size: 22px;
  font-weight: 700;
  color: #1890ff;
}

.variant-metrics {
  display: flex;
  justify-content: space-around;
  padding: 12px;
  background: #fafafa;
  border-top: 1px solid #f0f0f0;
}

.metric {
  text-align: center;
}

.m-label {
  display: block;
  font-size: 10px;
  color: #bfbfbf;
  margin-bottom: 2px;
}

.m-value {
  font-size: 16px;
  font-weight: 700;
}

.variant-actions {
  display: flex;
  gap: 6px;
  padding: 10px 14px;
  justify-content: center;
}

/* 差异表格 */
.diff-highlight {
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
}

.highlight-title {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
  margin-bottom: 12px;
}

.diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.diff-table th {
  background: #fafafa;
  padding: 8px;
  text-align: left;
  font-weight: 600;
  color: #595959;
  border-bottom: 2px solid #f0f0f0;
}

.diff-table td {
  padding: 8px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 11px;
}

.dim-label {
  font-weight: 500;
  color: #262626;
}

.changed-cell {
  background: #fffbe6;
  color: #d48806;
  font-weight: 500;
}

/* 测试建议 */
.test-recommendation {
  padding: 16px 20px;
  background: #fafbfc;
}

.rec-title {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
  margin-bottom: 12px;
}

.rec-content {
  max-width: 400px;
}
</style>
