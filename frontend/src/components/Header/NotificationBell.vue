<script setup lang="ts">
/**
 * 右上角通知铃铛 · 每日经营简报入口（第 371 轮）
 * =============================================
 *
 * 前身是 `Workspace.vue` 里写死 `<a-badge :count="0" dot>` 的**死铃铛** ——
 * 它连点都没得点（而且 `dot` 配 `count=0` 在 antd 里是**隐藏**的：
 * `showAsDot = dot && !isZero` ⇒ 那颗点从来没显示过）。
 * 本组件把它做成真入口：未读数徽标 + 点开抽屉看简报明细 + 展开即标记已读。
 *
 * ★ 为什么抽成独立组件，而不是就地改 `Workspace.vue`：
 *   ① `Workspace.vue` 在**体量棘轮冻结表**里（1466 行，只许降不许升）——
 *      任何净增都会撞 R2。抽出来反而能净减（7 行铃铛块 → 1 行 + 1 行 import）。
 *   ② 铃铛的取数 / 呈现与 Workspace 的布局职责无关；混在一起会让
 *      「加一个入口」变成「改一个 1466 行的文件」，而这正是棘轮想防的事。
 *
 * ★ 「展开才算读过」，不是「打开抽屉就全部已读」：
 *   后者会把徽标清零，而用户一条都没看 —— 徽标从此不可信（下次真有事他不点）。
 *   展开是「用户确实看了这条」的唯一证据，标记点落在这里才诚实。
 *   （**不做「全部已读」按钮**：后端没有批量端点，客户端 for 循环一旦中途失败
 *    就会让徽标与服务端状态分叉，而那正是本仓明令禁止的「伪成功」。）
 *
 * ★ 低频轮询 + 可见性判定，而不是秒级轮询：
 *   简报一天只在 beat 时刻（08:37）生成一次，秒级轮询纯属白跑。
 *   这里取数靠三个**真实事件**：挂载 / 打开抽屉 / 标签页重新可见；
 *   另加一个 5 分钟定时器只兜「页面一直开着」这一种场景。
 *   标签页隐藏时直接跳过（`document.hidden`）—— 后台标签不该占着网络。
 */

import { onMounted, onUnmounted, ref } from 'vue'
import { BellOutlined } from '@ant-design/icons-vue'

import { WINDOW_W } from '@/config/layout'
import { SEM } from '@/theme/semantic'
import { useBriefingStore } from '@/stores/briefing'
import AsyncEmpty from '@/components/common/AsyncEmpty.vue'
import type { BriefingItem } from '@/api/briefings'

/** 兜底轮询间隔。理由见文件头：一天一次的产出，5 分钟足够。 */
const POLL_MS = 5 * 60 * 1000

const store = useBriefingStore()
const visible = ref(false)
/** 当前展开的简报 id。同一时刻只展开一份：抽屉要能一眼读完。 */
const expandedId = ref<string | null>(null)
let timer: number | null = null

/** 严重度 → 圆点颜色。取主题语义色，**不写死色值**（深色 / 马卡龙主题要能翻转）。 */
function severityColor(s: BriefingItem['severity']): string {
  if (s === 'high') return SEM.danger
  if (s === 'medium') return SEM.warning
  return SEM.primary
}

function reload(): void {
  void store.load()
}

function openDrawer(): void {
  visible.value = true
  // 每次打开都取一次：一天只生成一次，这次往返的成本可以忽略，
  // 换来「打开看到的就是当下最新的」。
  reload()
}

/** 展开 / 收起一份简报；**展开时**才标记已读。 */
async function toggle(id: string): Promise<void> {
  const next = expandedId.value === id ? null : id
  expandedId.value = next
  if (next) {
    // 失败时**不动界面已读态**：store 只在服务端确认后才改 read_at / unread，
    // 所以徽标不会说谎（代价是用户可能再点一次，比徽标骗人便宜）。
    await store.markRead(id)
  }
}

/** 定时兜底取数：标签页隐藏时跳过。 */
function tick(): void {
  if (document.hidden) return
  void store.load()
}

/** 标签页重新可见 ⇒ 立刻取一次（切走一整天再切回来时不用等定时器）。 */
function onVisible(): void {
  if (!document.hidden) void store.load()
}

onMounted(() => {
  reload()
  timer = window.setInterval(tick, POLL_MS)
  document.addEventListener('visibilitychange', onVisible)
})

onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
  timer = null
  document.removeEventListener('visibilitychange', onVisible)
})
</script>

<template>
  <a-badge
    :count="store.unread"
    :offset="[-2, 2]"
  >
    <button
      type="button"
      class="nb-bell"
      aria-label="每日经营简报"
      title="每日经营简报"
      @click="openDrawer"
    >
      <BellOutlined />
    </button>
  </a-badge>

  <a-drawer
    v-model:open="visible"
    title="每日经营简报"
    placement="right"
    :width="WINDOW_W.lg"
  >
    <!-- 取数失败但**手上还有旧值**：画一条横幅说明"这不是最新的"。
         不静默展示旧数据（那会让人以为是今天的），也不清空（清空等于
         说"今天没有变化"，是另一句假话）。见 store 文件头。 -->
    <a-alert
      v-if="store.loadError && store.items.length"
      type="warning"
      show-icon
      :message="`简报刷新失败：${store.loadError}`"
      class="nb-alert"
    >
      <template #action>
        <a-button
          size="small"
          @click="reload"
        >
          重试
        </a-button>
      </template>
    </a-alert>

    <a-skeleton
      v-if="store.loading && !store.items.length"
      active
      :paragraph="{ rows: 4 }"
    />

    <div
      v-else-if="store.items.length"
      class="nb-list"
    >
      <div
        v-for="row in store.items"
        :key="row.id"
        class="nb-card"
      >
        <button
          type="button"
          class="nb-card-head"
          :aria-expanded="expandedId === row.id"
          @click="toggle(row.id)"
        >
          <span
            class="nb-dot"
            :class="{ 'nb-dot--unread': !row.read_at }"
          />
          <span class="nb-date">{{ row.brief_date }}</span>
          <span class="nb-summary">{{ row.summary }}</span>
          <span class="nb-count">{{ row.item_count }} 项</span>
        </button>

        <div
          v-if="expandedId === row.id"
          class="nb-items"
        >
          <p
            v-if="!row.items.length"
            class="nb-items-empty"
          >
            这一天没有需要你处理的变化。
          </p>
          <div
            v-for="(it, i) in row.items"
            :key="`${it.type}-${it.asin}-${i}`"
            class="nb-item"
          >
            <span
              class="nb-item-dot"
              :style="{ background: severityColor(it.severity) }"
            />
            <span class="nb-item-text">{{ it.text }}</span>
            <span class="nb-item-metric">{{ it.metric }}</span>
          </div>
        </div>
      </div>
    </div>

    <div
      v-else
      class="nb-empty"
    >
      <AsyncEmpty
        :error="store.loadError"
        label="简报"
        empty-description="还没有简报 —— 每天早 8 点自动生成一份"
        @retry="reload"
      />
    </div>
  </a-drawer>
</template>

<style scoped>
/* 铃铛本体：与紧邻的语音开关（VoiceSpeakerButton）同为 30px 点击区，
   但**不加边框** —— 原样保留它在头部的观感。 */
.nb-bell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  font-size: var(--font-size-18);
  color: var(--text-secondary);
  background: transparent;
  border: 0;
  cursor: pointer;
  transition: color 0.18s ease;
}
.nb-bell:hover {
  color: var(--primary);
}

.nb-alert {
  margin-bottom: var(--space-12);
}

.nb-card + .nb-card {
  margin-top: var(--space-4);
}

/* 卡片头 = 一行摘要（点击展开明细） */
.nb-card-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  padding: var(--space-10) var(--space-4);
  font: inherit;
  text-align: left;
  color: var(--text-primary);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--border-base);
  cursor: pointer;
}
.nb-card-head:hover {
  background: var(--bg-hover-light);
}

/* 未读圆点：灰 = 已读，红 = 未读（与徽标同色系，一眼对得上） */
.nb-dot {
  flex: 0 0 auto;
  width: var(--space-6);
  height: var(--space-6);
  border-radius: var(--radius-circle);
  background: var(--border-base);
}
.nb-dot--unread {
  background: var(--danger);
}

.nb-date {
  flex: 0 0 auto;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.nb-summary {
  flex: 1 1 auto;
  overflow: hidden;
  font-size: var(--font-size-13);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nb-count {
  flex: 0 0 auto;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.nb-items {
  padding: var(--space-6) 0 var(--space-10) var(--space-14);
}
.nb-item {
  display: flex;
  gap: var(--space-8);
  align-items: flex-start;
  padding: var(--space-4) 0;
}
/* 严重度圆点：色值由 `severityColor()` 从主题语义色给（不写死 hex） */
.nb-item-dot {
  flex: 0 0 auto;
  width: var(--space-6);
  height: var(--space-6);
  margin-top: var(--space-6);
  border-radius: var(--radius-circle);
}
.nb-item-text {
  flex: 1 1 auto;
  font-size: var(--font-size-13);
  line-height: 1.6;
  color: var(--text-primary);
}
.nb-item-metric {
  flex: 0 0 auto;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
.nb-items-empty {
  margin: 0;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.nb-empty {
  padding-top: var(--space-40);
}
</style>
