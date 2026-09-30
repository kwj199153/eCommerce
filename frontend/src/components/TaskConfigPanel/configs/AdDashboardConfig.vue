<template>
  <div class="ad-dashboard">
    <!-- 顶部 Tab 导航（仅大屏模式显示） -->
    <div v-if="isDataMode" class="ad-tabs">
      <button
        v-for="tab in AD_TABS"
        :key="tab.key"
        class="ad-tab"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        <span class="ad-tab-icon">{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- ══════════ 状态层 ══════════
         ★ 加载 / 空 / 错误三态都必须**显式**占屏。
         后端这 4 个端点取不到数据时是 fail-closed：HTTP 仍是 200，但
         `success=false` + `data_status='no_data'`。若不显式处理，界面会渲染出
         一片空白或 `NaN` —— 而空白会被读成「加载失败」，`NaN` 会被读成真数据。 -->
    <div v-if="state !== 'ready'" class="ad-state">
      <template v-if="state === 'loading'">
        <a-spin />
        <div class="ad-state-title">正在读取广告数据…</div>
        <div class="ad-state-reason">{{ TAB_HINT[activeTab] }}</div>
      </template>
      <template v-else-if="state === 'empty'">
        <div class="ad-state-title">暂无可用数据</div>
        <div class="ad-state-reason">{{ stateReason }}</div>
        <div class="ad-state-reason">
          广告数据按<strong>当前店铺</strong>取：请先在左上角选择店铺；
          若已选店铺，则说明它在所选周期内没有对应的投放记录。
        </div>
      </template>
      <template v-else-if="state === 'error'">
        <div class="ad-state-title" style="color: var(--danger)">读取失败</div>
        <div class="ad-state-reason">{{ stateReason }}</div>
        <a-button size="small" @click="loadTab(activeTab, true)">重试</a-button>
      </template>
      <template v-else>
        <a-spin />
      </template>
    </div>

    <template v-else>
    <!-- ══════════ ① 账户总览 ══════════ -->
    <section v-if="activeTab === 'overview'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">账户总览 <a-tag color="default" class="mini-tag">近 30 天</a-tag></div>
          <div class="pane-sub">核心效益指标 + Campaign 健康状态 + 花费/销售趋势 + Top 问题</div>
        </div>
      </div>

      <!-- 综合评分 + KPI -->
      <div class="score-kpi-row">
        <div class="score-card" :class="'grade-' + (diag?.grade || 'F')">
          <span class="score-val">{{ diag?.overall_score ?? 0 }}</span>
          <span class="grade-label">{{ diag?.grade || '—' }}</span>
        </div>
        <div class="kpi-grid flex-1">
          <div v-for="m in diag?.metrics || []" :key="m.name" class="kpi-card">
            <div class="kpi-label">{{ m.name }}</div>
            <div class="kpi-value" :class="m.status === 'good' ? 'success' : m.status === 'critical' ? 'danger' : 'warning'">
              {{ fmtMetric(m) }}
            </div>
            <div class="kpi-change">
              <!-- ★ 后端 change_pct 目前一律 0.0（没有上一期对比口径）。
                   `0` 的语义是「没有环比数据」，**不是**「与上期持平」——
                   渲染成「▲ 0.0% 环比」就是一条看着像真数的假持平。 -->
              <span v-if="m.change_pct" :class="m.change_pct >= 0 ? 'up' : 'down'">
                {{ m.change_pct >= 0 ? '▲' : '▼' }} {{ Math.abs(m.change_pct).toFixed(1) }}% <em>环比</em>
              </span>
              <span v-else class="kpi-nodata">基准 {{ m.benchmark }}{{ m.unit }} · 无环比</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 诊断结论（后端 LLM 生成；缺则退到规则摘要） -->
      <div v-if="diag?.summary" class="panel-card">
        <div class="card-head">诊断结论</div>
        <p class="rationale">{{ diag.summary }}</p>
      </div>

      <!-- 趋势图 -->
      <div class="panel-card chart-card">
        <div class="card-head">每日花费 / 销售额趋势</div>
        <LineChart v-if="trendSeries" :series="trendSeries" :labels="diag?.daily_trend?.labels || []" :legend="true" />
        <!-- ★ 单点也是真实结果：SP-API 拿不到按天拆分时后端把整段活动写在 date_to 当天
             （已明示、不做随机插值）⇒ 这里只呈现事实，不补点。 -->
        <div v-else class="ad-empty-inline">后端未返回日粒度序列（该数据源没有按天拆分）</div>
      </div>

      <!-- 两栏: Campaign 表 + 问题列表 -->
      <div class="two-col">
        <div class="panel-card">
          <div class="card-head">Campaign 健康状态</div>
          <div class="tbl sm">
            <div class="tbl-head">
              <span class="c-role">Campaign</span><span class="c-num">花费</span><span class="c-num">销售</span><span class="c-num">ACoS</span><span class="c-num">RoAS</span><span class="c-badge">状态</span>
            </div>
            <div v-for="c in diag?.campaigns || []" :key="c.campaign_name" class="tbl-row">
              <span class="c-role"><a-tag size="small" :color="campaignTagColor(c.campaign_type)">{{ c.campaign_type }}</a-tag> {{ c.campaign_name }}</span>
              <span class="c-num">${{ fmtMoney(c.spend) }}</span>
              <span class="c-num">${{ fmtMoney(c.sales) }}</span>
              <span class="c-num" :class="bandOf('acos', c.acos)">{{ c.acos }}%</span>
              <span class="c-num" :class="bandOf('roas', c.roas)">{{ c.roas }}x</span>
              <span class="c-badge"><a-tag size="small" :color="ACOS_TAG[bandOf('acos', c.acos)]">{{ ACOS_LABEL[bandOf('acos', c.acos)] }}</a-tag></span>
            </div>
            <div v-if="!(diag?.campaigns || []).length" class="ad-empty-inline">该周期内没有 Campaign 记录</div>
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head danger">Top 问题</div>
          <div class="issue-list">
            <div v-for="(issue, idx) in diag?.top_issues || []" :key="idx" class="issue-item" :class="'priority-' + (issue.priority || 'medium')">
              <span class="issue-rank">{{ idx + 1 }}</span>
              <div class="issue-content">
                <span class="issue-title">{{ issue.title }}</span>
                <span class="issue-desc">{{ issue.description }}</span>
              </div>
            </div>
            <div v-if="!(diag?.top_issues || []).length" class="ad-empty-inline">未识别出问题</div>
          </div>
          <!-- 优化建议：与 Top 问题同源同卡，不在页面上另起一块 -->
          <template v-if="(diag?.recommendations || []).length">
            <div class="card-head" style="margin-top: var(--space-12)">优化建议</div>
            <ul class="suggestion-list">
              <li v-for="(r, i) in diag?.recommendations || []" :key="i">{{ r }}</li>
            </ul>
          </template>
        </div>
      </div>
    </section>

    <!-- ══════════ ② 搜索词分析 ══════════ -->
    <section v-else-if="activeTab === 'searchterms'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">搜索词分析 <a-tag color="default" class="mini-tag">{{ terms?.period || '—' }}</a-tag></div>
          <div class="pane-sub">高效词 / 低效词 / 浪费词分类 + 新机会挖掘</div>
        </div>
      </div>

      <!-- 效率分布（★ 原来是模板里写死的 42 / 3 / 2 / 2，连 mock 都没走） -->
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">总搜索词</div><div class="kpi-value">{{ terms?.total_terms ?? 0 }}</div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:var(--success)">高效词</div><div class="kpi-value success">{{ (terms?.high_performers || []).length }}</div><div class="kpi-change"><span class="up">ACoS ≤ 20%</span></div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:var(--warning)">低效词</div><div class="kpi-value warning">{{ (terms?.low_performers || []).length }}</div><div class="kpi-change"><span class="down">ACoS &gt; 35%</span></div></div>
        <div class="kpi-card"><div class="kpi-label" style="color:var(--danger)">浪费词</div><div class="kpi-value danger">{{ (terms?.waste_terms || []).length }}</div><div class="kpi-change"><span class="down">零转化</span></div></div>
      </div>

      <!-- 高效词 -->
      <div class="panel-card">
        <div class="card-head ok">高效词（提高预算 / 扩量）</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">搜索词</span><span class="c-num">展示</span><span class="c-num">点击</span><span class="c-num">花费</span><span class="c-num">销售</span><span class="c-num">ACoS</span><span class="c-badge">匹配</span></div>
          <div v-for="t in terms?.high_performers || []" :key="t.term" class="tbl-row">
            <span class="c-role">{{ t.term }}</span>
            <span class="c-num">{{ t.impressions.toLocaleString() }}</span>
            <span class="c-num">{{ t.clicks }}</span>
            <span class="c-num">${{ t.spend.toFixed(2) }}</span>
            <span class="c-num ok">${{ t.sales.toFixed(2) }}</span>
            <span class="c-num ok">{{ t.acos }}%</span>
            <span class="c-badge"><a-tag size="small" color="blue">{{ t.match_type }}</a-tag></span>
          </div>
          <div v-if="!(terms?.high_performers || []).length" class="ad-empty-inline">本周期没有达到高效阈值的搜索词</div>
        </div>
      </div>

      <!-- 新机会词 -->
      <div class="panel-card">
        <div class="card-head">新机会词（小规模试投）</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">搜索词</span><span class="c-num">展示</span><span class="c-num">点击</span><span class="c-num">花费</span><span class="c-num">销售</span><span class="c-num">ACoS</span><span class="c-badge">匹配</span></div>
          <div v-for="t in terms?.new_opportunities || []" :key="t.term" class="tbl-row">
            <span class="c-role">{{ t.term }}</span>
            <span class="c-num">{{ t.impressions.toLocaleString() }}</span>
            <span class="c-num">{{ t.clicks }}</span>
            <span class="c-num">${{ t.spend.toFixed(2) }}</span>
            <span class="c-num ok">${{ t.sales.toFixed(2) }}</span>
            <span class="c-num ok">{{ t.acos }}%</span>
            <span class="c-badge"><a-tag size="small" color="blue">{{ t.match_type }}</a-tag></span>
          </div>
          <div v-if="!(terms?.new_opportunities || []).length" class="ad-empty-inline">本周期没有新机会词</div>
        </div>
      </div>

      <!-- 低效 + 浪费词 -->
      <div class="two-col">
        <div class="panel-card">
          <div class="card-head warn">低效词（降低出价 / 改匹配）</div>
          <div class="term-list">
            <div v-for="t in terms?.low_performers || []" :key="t.term" class="term-row">
              <span class="term-name">{{ t.term }}</span>
              <span class="term-acos warn">{{ t.acos }}%</span>
              <span class="term-spend">${{ t.spend.toFixed(2) }}</span>
            </div>
            <div v-if="!(terms?.low_performers || []).length" class="ad-empty-inline">无</div>
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head danger">浪费词（建议否定）</div>
          <div class="term-list">
            <div v-for="t in terms?.waste_terms || []" :key="t.term" class="term-row">
              <span class="term-name">{{ t.term }}</span>
              <span class="term-acos danger">∞</span>
              <span class="term-spend danger">${{ t.spend.toFixed(2) }}</span>
            </div>
            <div v-if="!(terms?.waste_terms || []).length" class="ad-empty-inline">无</div>
          </div>
          <div class="waste-total">合计浪费: ${{ wasteSpend.toFixed(2) }}</div>
        </div>
      </div>

      <!-- 建议 -->
      <div class="panel-card">
        <div class="card-head">优化建议</div>
        <ul class="suggestion-list">
          <li v-for="(s, i) in terms?.suggestions || []" :key="i">{{ s }}</li>
        </ul>
        <div v-if="!(terms?.suggestions || []).length" class="ad-empty-inline">无</div>
      </div>
    </section>

    <!-- ══════════ ③ 出价优化 ══════════ -->
    <section v-else-if="activeTab === 'bid'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">出价优化 <a-tag color="default" class="mini-tag">{{ STRATEGY_LABEL[bids?.strategy_type || ''] || bids?.strategy_type || '—' }}</a-tag></div>
          <div class="pane-sub">基于近30天转化的智能出价建议，预计 ACoS {{ fmtPct(bids?.expected_acos_change ?? 0) }}</div>
        </div>
      </div>

      <!-- 汇总 -->
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">分析关键词</div><div class="kpi-value">{{ bids?.total_keywords ?? 0 }}</div></div>
        <div class="kpi-card"><div class="kpi-label">预算影响</div><div class="kpi-value" :class="(bids?.budget_impact ?? 0) >= 0 ? 'danger' : 'success'">${{ (bids?.budget_impact ?? 0) >= 0 ? '+' : '' }}{{ (bids?.budget_impact ?? 0).toFixed(2) }}/词</div></div>
        <div class="kpi-card"><div class="kpi-label">预计 ACoS 变化</div><div class="kpi-value success">{{ fmtPct(bids?.expected_acos_change ?? 0) }}</div></div>
      </div>

      <!-- 出价建议表 -->
      <div class="panel-card">
        <div class="card-head">关键词出价调整</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">关键词</span><span class="c-badge">匹配</span><span class="c-num">当前出价</span><span class="c-num">建议出价</span><span class="c-num">调整</span><span class="c-role">原因</span><span class="c-badge">优先级</span></div>
          <div v-for="b in bids?.recommendations || []" :key="b.keyword" class="tbl-row">
            <span class="c-role">{{ b.keyword }}</span>
            <span class="c-badge"><a-tag size="small" color="blue">{{ b.match_type }}</a-tag></span>
            <span class="c-num">${{ b.current_bid.toFixed(2) }}</span>
            <span class="c-num" :class="bidClass(b)">${{ b.suggested_bid.toFixed(2) }}</span>
            <span class="c-num" :class="bidChangeClass(b)">{{ b.bid_change_pct > 0 ? '+' : '' }}{{ b.bid_change_pct }}%</span>
            <span class="c-role reason-text">{{ b.reason }}</span>
            <span class="c-badge"><a-tag size="small" :color="b.priority === 'high' ? 'red' : b.priority === 'medium' ? 'orange' : 'default'">{{ b.priority === 'high' ? '高' : b.priority === 'medium' ? '中' : '低' }}</a-tag></span>
          </div>
          <div v-if="!(bids?.recommendations || []).length" class="ad-empty-inline">本周期没有需要调整出价的关键词</div>
        </div>
      </div>

      <div class="panel-card">
        <div class="card-head">策略说明</div>
        <p class="rationale">{{ bids?.rationale }}</p>
      </div>
    </section>

    <!-- ══════════ ④ 竞品广告 ══════════ -->
    <section v-else-if="activeTab === 'competitor'" class="ad-pane">
      <div class="pane-head">
        <div>
          <div class="pane-title">竞品广告 <a-tag color="default" class="mini-tag">SOV 分析</a-tag></div>
          <div class="pane-sub">你的 SOV: {{ comp?.your_share_of_voice ?? 0 }}% | 市场定位: {{ MARKET_POSITION_LABEL[comp?.market_position || ''] || '—' }} | Top {{ topCompetitors.length }} 竞品广告策略对比</div>
        </div>
      </div>

      <!-- SOV 饼图 + 你的位置 -->
      <div class="two-col">
        <div class="panel-card chart-card">
          <div class="card-head">SOV 占比</div>
          <DonutChart
            v-if="sovSegments"
            :segments="sovSegments"
            :center-value="(comp?.your_share_of_voice ?? 0) + '%'"
            center-title="你的 SOV"
          />
          <!-- ★ 实测后端 `your_share_of_voice = 0`、竞品 `share_of_voice` 同一 asin 多快照
               ⇒ 全 0 时画一个没有扇区的饼图没有意义，直接说明缺口。 -->
          <div v-else class="ad-empty-inline">
            后端未提供展示份额（SOV）数据 —— `amazon_competitor_snapshots` 里没有这个维度
          </div>
        </div>
        <div class="panel-card">
          <div class="card-head">可执行洞察</div>
          <ul class="suggestion-list">
            <li v-for="(insight, i) in comp?.actionable_insights || []" :key="i">{{ insight }}</li>
          </ul>
          <div v-if="!(comp?.actionable_insights || []).length" class="ad-empty-inline">无</div>
        </div>
      </div>

      <!-- 竞品详情表 -->
      <div class="panel-card">
        <div class="card-head">竞品广告详情</div>
        <div class="tbl sm">
          <div class="tbl-head"><span class="c-role">竞品</span><span class="c-num">SOV</span><span class="c-num">重叠词</span><span class="c-num">BSR</span><span class="c-num">预估花费</span><span class="c-role">优势</span><span class="c-role">劣势</span></div>
          <div v-for="c in topCompetitors" :key="c.asin || c.competitor_name" class="tbl-row">
            <span class="c-role"><strong>{{ c.competitor_name }}</strong><br><span class="rev">{{ c.asin }}</span></span>
            <span class="c-num"><strong>{{ c.share_of_voice }}%</strong></span>
            <span class="c-num">{{ c.overlap_keywords }}</span>
            <span class="c-num">{{ c.avg_position }}</span>
            <span class="c-num">${{ c.estimated_spend }}</span>
            <span class="c-role ok-text">{{ (c.strengths || []).join(' / ') }}</span>
            <span class="c-role warn-text">{{ (c.weaknesses || []).join(' / ') }}</span>
          </div>
          <div v-if="!topCompetitors.length" class="ad-empty-inline">该店铺没有竞品快照记录</div>
        </div>
        <div class="pane-sub" style="margin-top: var(--space-8)">
          注：「重叠词 / 预估花费」恒为 0、「劣势」显示"数据不足"，源自后端刻意不编造 ——
          竞品快照表里没有这三个维度。「BSR」是竞品排名（越小越好），不是广告位。
        </div>
      </div>
    </section>

    <!-- ★ 第 316 轮：⑤ 预算分配 / ⑥ 异常检测 两个 Tab 整段退役
         （老板「广告分析师删除异常检测、广告预算再平衡」）。 -->
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 广告分析师 · 大屏看板
 *
 * ★ 第 169 轮（#737）：从 `@/mock/adDashboard`（289 行硬编码假数据，27 个常量）
 *   切到后端 6 个结构化端点（第 316 轮起 4 个）。此前这个"看板"其实是一张**静态图片**：
 *   · 组件**从不发任何请求**（原文件里 `defineEmits` 声明了 `startAnalysis`，
 *     但模板里一次都没 emit）；
 *   · 搜索词 Tab 的 4 个 KPI 是模板里写死的 `42 / 3 / 2 / 2`，**连 mock 都没走**；
 *   · "近 30 天""平衡策略""市场定位: 利基玩家"全是硬编码文案。
 *   而对应端点在 `modules/ad_analysis/router.py` 里早已就绪 —— 本仓那条
 *   「后端有端点 ≠ 前端在用」的又一现场。
 *
 * ★ 为什么按 Tab 懒加载：每个端点都是一次完整的 Agent 调用（含 LLM），
 *   一次性全打会白烧 N 轮 token 且首屏要等最慢的那个（第 316 轮起剩 4 个）。
 */
import { chartVar } from '@/theme/semantic'
import { bandOf } from '@/theme/bands'
import { ref, computed, watch, inject, type Ref } from 'vue'
import LineChart from '@/components/charts/LineChart.vue'
import DonutChart from '@/components/charts/DonutChart.vue'
import { useShopStore } from '@/stores/shop'
import {
  diagnoseAdAccount, analyzeSearchTerms, optimizeBids, analyzeCompetitors,
  isAdDataOk,
  type AdDiagnosisData, type AdSearchTermData, type AdBidStrategyData,
  type AdCompetitorData, type AdCompetitorItem,
} from '@/api/adAnalysis'

/** ACoS 档位 → antd 预设色 / 中文标签（阈值见 bands.ts `acos`） */
const ACOS_TAG: Record<string, string> = { ok: 'green', warn: 'orange', danger: 'red' }
const ACOS_LABEL: Record<string, string> = { ok: '健康', warn: '关注', danger: '预警' }

/** 竞品列表在界面上最多展示几家（后端逐快照行返回，实测 90 条） */
const COMPETITOR_TOP_N = 6

const STRATEGY_LABEL: Record<string, string> = {
  aggressive: '激进策略', conservative: '保守策略', balanced: '平衡策略',
}
const MARKET_POSITION_LABEL: Record<string, string> = {
  leader: '市场领导者', challenger: '挑战者', nicher: '利基玩家',
}
const TAB_HINT: Record<string, string> = {
  overview: '账户诊断是一次完整的 Agent 调用，首次通常需要几秒。',
  searchterms: '正在按关键词聚合搜索词报告…',
  bid: '正在根据转化与竞争强度推算建议出价…',
  competitor: '正在整理竞品快照…',
}

const props = defineProps<{ currentToolId?: string }>()
defineEmits<{ (e: 'startAnalysis', params: any): void }>()

// 从 Workspace 注入「对话/大屏」模式
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ──── Tab 定义 ────
const AD_TABS = [
  { key: 'overview', label: '账户总览', icon: '📊' },
  { key: 'searchterms', label: '搜索词', icon: '🔍' },
  { key: 'bid', label: '出价优化', icon: '💡' },
  { key: 'competitor', label: '竞品广告', icon: '🎯' },
]

const TOOL_TAB_MAP: Record<string, string> = {
  'ad-diagnosis': 'overview',
  'keyword-report': 'searchterms',
  'bid-suggest': 'bid',
  'competitor-ad': 'competitor',
}
const activeTab = ref<string>(TOOL_TAB_MAP[props.currentToolId || ''] || 'overview')
watch(
  () => props.currentToolId,
  (tid) => { const m = TOOL_TAB_MAP[tid || '']; if (m) activeTab.value = m }
)
function switchTab(key: string) { activeTab.value = key }

// ──── 取数状态（按 Tab 各自持有，同一时刻只有一个可见）────
type TabKind = 'idle' | 'loading' | 'ready' | 'empty' | 'error'
interface TabStatus { kind: TabKind; reason?: string }

const statuses = ref<Record<string, TabStatus>>({})
const state = computed<TabKind>(() => statuses.value[activeTab.value]?.kind ?? 'idle')
const stateReason = computed(() => statuses.value[activeTab.value]?.reason ?? '')

const diag = ref<AdDiagnosisData | null>(null)
const terms = ref<AdSearchTermData | null>(null)
const bids = ref<AdBidStrategyData | null>(null)
const comp = ref<AdCompetitorData | null>(null)

const shopStore = useShopStore()

/** `silentError: true` —— 本看板自带**常驻**失败面：`fail()` 把原因写进
 *  `statuses`，模板渲染成内联横幅（含原因 + 重试按钮），比会消失的 toast 清楚。
 *  ⇒ 声明它，避免同一个失败原因在横幅与 toast 各报一次。
 *  注：这 4 个端点都是 POST + fail-closed，失败时回 **HTTP 200 + `success:false`**
 *  （`ad_analysis/router.py` 四处 `ApiResponse(success=False, message=e.reason)`）。 */
const QUIET = { silentError: true }

function fail(tab: string, kind: 'empty' | 'error', reason: string) {
  statuses.value = { ...statuses.value, [tab]: { kind, reason } }
}

async function loadTab(tab: string, force = false) {
  if (!force && statuses.value[tab]?.kind === 'ready') return
  statuses.value = { ...statuses.value, [tab]: { kind: 'loading' } }
  try {
    if (tab === 'overview') {
      const res = await diagnoseAdAccount({ time_range: '30d' }, QUIET)
      if (!isAdDataOk(res)) return fail(tab, 'empty', res?.message || res?.data?.data_reason || '后端未返回可用数据')
      diag.value = res.data as AdDiagnosisData
    } else if (tab === 'searchterms') {
      const res = await analyzeSearchTerms({ time_range: '30d', sort_by: 'spend' }, QUIET)
      if (!isAdDataOk(res)) return fail(tab, 'empty', res?.message || res?.data?.data_reason || '后端未返回可用数据')
      terms.value = res.data as AdSearchTermData
    } else if (tab === 'bid') {
      const res = await optimizeBids({ strategy: 'balanced' }, QUIET)
      if (!isAdDataOk(res)) return fail(tab, 'empty', res?.message || res?.data?.data_reason || '后端未返回可用数据')
      bids.value = res.data as AdBidStrategyData
    } else if (tab === 'competitor') {
      const res = await analyzeCompetitors({ auto_detect: true, time_range: '30d' }, QUIET)
      if (!isAdDataOk(res)) return fail(tab, 'empty', res?.message || res?.data?.data_reason || '后端未返回可用数据')
      comp.value = res.data as AdCompetitorData    }
    statuses.value = { ...statuses.value, [tab]: { kind: 'ready' } }
  } catch (e: any) {
    const status = e?.response?.status
    const detail = e?.response?.data?.detail
    // ★ 400 = 后端 `get_current_shop_id` 的空值守卫。它是**按 HTTP 方法分流**的：
    //   写方法（POST/PUT/PATCH/DELETE）缺 X-Shop-ID ⇒ 直接 400；
    //   读方法才返回 None（端点自己回空列表）。
    //   而本模块这 4 个分析端点**全是 POST** ⇒ 「还没选店铺」在这里就长成 400。
    //   ★ 它是**可解释的业务结论**（去选个店铺即可），不是故障 ⇒ 必须归 empty 态。
    //   给「重试」按钮反而误导：重试一百次也还是没选店铺。
    if (status === 400) return fail(tab, 'empty', detail || '请先在左上角选择店铺')
    fail(tab, 'error', detail || e?.message || '请求失败')
  }
}

// 切 Tab ⇒ 首次进入该 Tab 时拉一次
watch(activeTab, (t) => { loadTab(t) }, { immediate: true })

// 店铺切换 ⇒ 全部作废重拉（否则会把 A 店的数字留在 B 店的界面上）
watch(() => shopStore.currentShopId, () => {
  statuses.value = {}
  diag.value = null; terms.value = null; bids.value = null
  comp.value = null
  loadTab(activeTab.value, true)
})

// ──── 账户总览派生 ────
/** 只有两条序列都非空才画图 —— 后端拿不到日粒度时 `daily_trend` 是空 dict */
const trendSeries = computed(() => {
  const dt = diag.value?.daily_trend
  if (!dt || !dt.labels?.length) return null
  return [
    { name: '花费', color: '#ff6b6b', data: dt.spend || [] },
    { name: '销售额', color: '#51cf66', data: dt.sales || [] },
  ]
})

// ──── 搜索词派生 ────
const wasteSpend = computed(() =>
  (terms.value?.waste_terms || []).reduce((s, t) => s + (t.spend || 0), 0))

// ──── 竞品派生 ────
/**
 * 按 ASIN 去重后取 SOV 最高的 N 家。
 *
 * ★ 为什么必须去重：后端 `_competitor_data_from_rows` 是**逐快照行**映射 ——
 *   同一个竞品（同 asin）会按不同 BSR 快照出现多次（实测 90 条里 TP-Link 占十几条）。
 *   直接喂给饼图会画出几十个扇区、喂给表格会拉到几百行。
 * ★ 取「最大值」而不是「首次出现」：不依赖后端的排序恰好是降序（这个前提没人保证）。
 */
const topCompetitors = computed<AdCompetitorItem[]>(() => {
  const best = new Map<string, AdCompetitorItem>()
  for (const c of comp.value?.competitors || []) {
    const key = c.asin || c.competitor_name
    if (!key) continue
    const prev = best.get(key)
    if (!prev || (c.share_of_voice || 0) > (prev.share_of_voice || 0)) best.set(key, c)
  }
  return [...best.values()]
    .sort((a, b) => (b.share_of_voice || 0) - (a.share_of_voice || 0))
    .slice(0, COMPETITOR_TOP_N)
})

const sovSegments = computed(() => {
  const you = comp.value?.your_share_of_voice ?? 0
  const rows = topCompetitors.value
  const total = rows.reduce((s, c) => s + (c.share_of_voice || 0), 0) + you
  // 全 0（实测后端 SOV 维度缺失）时不画一个空饼图
  if (total <= 0) return null
  return [
    ...rows.map((c, i) => ({ name: c.competitor_name, value: c.share_of_voice, color: chartVar(i) })),
    { name: '你', value: you, color: '#69c0ff' },
  ]
})

// ──── 格式化（原先住在 mock/adDashboard.ts 里，随它一起退场）────
function fmtMoney(v: number): string { return Math.round(v).toLocaleString() }
function fmtPct(v: number): string { return (v >= 0 ? '+' : '') + v.toFixed(1) + '%' }
function fmtMetric(m: { value: number; unit: string }): string {
  if (m.unit === '%') return m.value.toFixed(1) + '%'
  if (m.unit === '$') return '$' + m.value.toFixed(2)
  if (m.unit === 'x') return m.value.toFixed(2) + 'x'
  return String(m.value)
}
function campaignTagColor(t: string): string {
  return t === 'SP' ? 'blue' : t === 'SB' ? 'purple' : 'orange'
}

// ──── 模板辅助函数（避免在模板内写 > 比较，防止 HTML 解析问题）────
function bidClass(b: { bid_change_pct: number }): string { return b.bid_change_pct > 0 ? 'ok' : 'warn' }
function bidChangeClass(b: { bid_change_pct: number }): string { return b.bid_change_pct > 0 ? 'up' : 'down' }
</script>

<style scoped>
/* ====== 布局（复用 ReviewConfig 的 CSS 体系）====== */
.ad-dashboard { display: flex; flex-direction: column; gap: var(--space-10); height: 100%; min-height: 0; }

/* Tab */
.ad-tabs { display: flex; flex-wrap: wrap; gap: var(--space-4); padding: var(--space-4); background: var(--bg-hover-light); border-radius: var(--radius-10); flex-shrink: 0; }
.ad-tab { display: inline-flex; align-items: center; gap: var(--space-5); padding: var(--space-8) 13px; border: none; background: transparent; border-radius: var(--radius-8); cursor: pointer; font-size: var(--font-size-12-5); font-weight: 500; white-space: nowrap; color: var(--text-secondary); transition: all .15s; }
.ad-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.ad-tab.active { background: var(--bg-elevated); color: var(--primary); box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.ad-tab-icon { font-size: var(--font-size-14); }

/* Pane */
.ad-pane { display: flex; flex-direction: column; gap: var(--space-10); flex: 1; min-height: 0; overflow: hidden; }
.ad-pane > .pane-head { flex-shrink: 0; }
.ad-pane > .kpi-grid { flex-shrink: 0; }
.ad-pane > .chart-card { flex: 1.2; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.chart-card > :deep(.chart-root) { flex: 1; min-height: 0; }
.ad-pane > .two-col { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-10); }
.ad-pane > .two-col > .panel-card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }

.pane-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-8); }
.pane-title { font-size: var(--font-size-15); font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: var(--space-6); }
.pane-sub { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); line-height: 1.5; }
.mini-tag { font-size: var(--font-size-10); margin: 0; }

/* 状态层：加载 / 空 / 错误 —— 三态都要显式占屏 */
.ad-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-10); padding: var(--space-30) var(--space-16); text-align: center; }
.ad-state-title { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); }
.ad-state-reason { font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; max-width: 440px; }
.ad-empty-inline { padding: var(--space-12) var(--space-10); text-align: center; font-size: var(--font-size-11-5); color: var(--text-tertiary); line-height: 1.7; }

/* KPI */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: var(--space-8); }
.kpi-grid.flex-1 { flex: 1; }
.kpi-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: var(--radius-10); padding: var(--space-10) var(--space-12); }
.kpi-label { font-size: var(--font-size-11); color: var(--text-tertiary); }
.kpi-value { font-size: var(--font-size-17); font-weight: 700; color: var(--text-primary); margin-top: var(--space-2); }
.kpi-value.warning { color: var(--warning); }
.kpi-value.danger { color: var(--danger); }
.kpi-value.success { color: var(--success); }
.kpi-change { font-size: var(--font-size-10); margin-top: var(--space-2); }
.kpi-change .up { color: var(--success); }
.kpi-change .down { color: var(--danger); }
.kpi-change em { font-style: normal; color: var(--text-disabled); }
.kpi-nodata { color: var(--text-disabled); }

/* 评分卡片 */
.score-kpi-row { display: flex; gap: var(--space-10); align-items: stretch; }
.score-card { width: 72px; border-radius: var(--radius-12); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); flex-shrink: 0; }
.score-card.grade-A { background: linear-gradient(135deg, #52c41a, #73d13d); }
.score-card.grade-B { background: linear-gradient(135deg, #faad14, #ffc53d); }
.score-card.grade-C { background: linear-gradient(135deg, #fa8c16, #ffa940); }
.score-card.grade-D { background: linear-gradient(135deg, #ff4d4f, #ff7875); }
/* ★ 后端 `_score_to_grade` 返回 A/B/C/D/F **五档**，原先只写了四档 ⇒ 真实评分
   落到 F（分数 < 60）时这张卡**没有背景色**，白字白底直接看不见。 */
.score-card.grade-F { background: linear-gradient(135deg, #a8071a, #cf1322); }
.score-val { font-size: var(--font-size-24); font-weight: 800; color: #fff; }
.grade-label { font-size: var(--font-size-14); font-weight: 700; color: rgba(255,255,255,.9); }

/* 卡片 */
.panel-card { background: var(--bg-elevated); border: 1px solid var(--border-base); border-radius: var(--radius-10); padding: var(--space-12) var(--space-14); }
.card-head { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-8); }
.card-head.ok { color: var(--success); }
.card-head.warn { color: var(--warning); }
.card-head.danger { color: var(--danger); }

/* 表格 */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-12); }
@media (max-width: 480px) { .two-col { grid-template-columns: 1fr; } }
.tbl { border: 1px solid var(--border-base); border-radius: var(--radius-8); overflow: hidden; font-size: var(--font-size-12); }
.tbl.sm { font-size: var(--font-size-11-5); }
.tbl-head, .tbl-row { display: flex; align-items: center; gap: var(--space-6); padding: 7px var(--space-10); }
.tbl-head { background: var(--bg-hover-light); font-size: var(--font-size-11); font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border-base); }
.tbl-row { border-bottom: 1px solid var(--border-base); }
.tbl-row:last-child { border-bottom: none; }
.c-role { flex: 2.2; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.c-num { flex: 1; text-align: right; color: var(--text-primary); white-space: nowrap; }
.c-badge { flex: 0.8; text-align: right; }
.ok, .ok-text { color: var(--success); }
.warn, .warn-text { color: var(--warning); }
.danger, .danger-text { color: var(--danger); }
.rev { color: var(--text-tertiary); font-size: var(--font-size-10); }
.reason-text { font-size: var(--font-size-11); color: var(--text-secondary); }

/* 问题列表 */
.issue-list { display: flex; flex-direction: column; gap: var(--space-8); }
.issue-item { display: flex; align-items: flex-start; gap: var(--space-8); padding: var(--space-8); border-radius: var(--radius-8); border-left: 3px solid; }
.issue-item.priority-high { background: rgba(255,77,79,.06); border-color: var(--danger); }
.issue-item.priority-medium { background: rgba(250,173,20,.06); border-color: var(--warning); }
.issue-rank { width: 20px; height: 20px; border-radius: var(--radius-circle); background: var(--bg-hover-light); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; font-size: var(--font-size-11); font-weight: 700; flex-shrink: 0; }
.issue-content { flex: 1; min-width: 0; }
.issue-title { display: block; font-size: var(--font-size-12-5); font-weight: 600; color: var(--text-primary); }
.issue-desc { display: block; font-size: var(--font-size-11); color: var(--text-secondary); margin-top: var(--space-2); line-height: 1.4; }

/* 搜索词列表 */
.term-list { display: flex; flex-direction: column; gap: var(--space-6); }
.term-row { display: flex; align-items: center; gap: var(--space-8); font-size: var(--font-size-12); padding: var(--space-5) 0; border-bottom: 1px dashed var(--border-base); }
.term-row:last-child { border-bottom: none; }
.term-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.term-acos { width: 42px; text-align: right; font-weight: 600; }
.term-spend { width: 70px; text-align: right; color: var(--text-secondary); }
.waste-total { margin-top: var(--space-8); padding-top: var(--space-8); border-top: 1px solid var(--border-base); font-size: var(--font-size-12); font-weight: 600; color: var(--danger); text-align: right; }

/* 建议列表 */
.suggestion-list { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.9; }
.suggestion-list li { color: var(--text-primary); }

/* 策略说明 */
.rationale { font-size: var(--font-size-12); color: var(--text-secondary); line-height: 1.7; margin: 0; }
</style>
