<template>
  <!--
    ★ 这个组件**全局只挂一次**（在 App.vue），它自己不带业务假设：
      · 不知道 Workspace 长什么样，只认 `data-tour` 锚点
      · 不知道界面处在哪个视图，只判断「锚点现在能不能被量到」
      · 需要布局配合时，发命令事件由属主（Workspace）自己去执行
  -->

  <!-- 首次进入的入口卡（右下角）。
       ★ 必须是一张**需要点击**的卡，不能自动开讲：
         在 Chrome 上，用户还没有任何手势之前调用 speechSynthesis.speak() 会**静默失败**
         （不发声、也不报错）—— 这正是本项目反复防过的「看着像坏了、其实是被拦了」的形态。
         点「开始」这个动作同时解封音频链路。
       ★ 位置刻意放在右下：左侧边栏与顶栏工具条是既有 CDP 几何探针的测量区，别去压它们。 -->
  <div v-if="offering" class="tour-offer" role="dialog" aria-label="新手引导入口">
    <div class="to-head">
      <span class="to-icon">👋</span>
      <span class="to-title">第一次来？</span>
      <button class="to-close" type="button" title="不再提示" @click="decline">×</button>
    </div>
    <div class="to-body">
      花一分钟，我把界面上各处功能指着讲一遍，还可以一边听语音解说。
    </div>
    <div class="to-foot">
      <button class="to-btn" type="button" @click="decline">跳过</button>
      <button class="to-btn to-primary" type="button" @click="begin">开始引导</button>
    </div>
  </div>

  <!-- 走完之后：把**被跳过的步骤**如实列出来。
       ★ 不能让用户自己去发现「好像有几块没讲过」——那样他只会以为是自己漏看了。 -->
  <div v-if="summaryOpen" class="tour-offer tour-summary" role="dialog" aria-label="引导小结">
    <div class="to-head">
      <span class="to-icon">✅</span>
      <span class="to-title">引导结束</span>
      <button class="to-close" type="button" title="关闭" @click="summaryOpen = false">×</button>
    </div>
    <div v-if="store.skips.length" class="to-body">
      有 {{ store.skips.length }} 步当时没讲（那一刻它们不在界面上）：
      <ul class="ts-list">
        <li v-for="s in store.skips" :key="s.stepId">
          <b>{{ s.title }}</b> —— {{ s.reason }}
        </li>
      </ul>
      <div class="ts-hint">等它们出现之后，随时可以从账户菜单里「重看新手引导」。</div>
    </div>
    <div v-else class="to-body">七处都讲到了。随时可以从账户菜单里「重看新手引导」。</div>
    <div class="to-foot">
      <button class="to-btn to-primary" type="button" @click="summaryOpen = false">知道了</button>
    </div>
  </div>

  <!-- 引导本体 -->
  <template v-if="store.running">
    <TourOverlay :rect="store.rect" />
    <TourTooltip
      v-if="store.current"
      :step="store.current"
      :rect="store.rect"
      :progress="store.progress"
      :can-prev="!store.isFirst"
      :is-last="store.isLast"
      :muted="narratorState.muted"
      :reason="narratorState.reason"
      :channel-label="narratorState.channelLabel"
      @prev="onPrev"
      @next="onNext"
      @skip="finish"
      @toggle-mute="toggleMute"
    />
  </template>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import TourOverlay from './TourOverlay.vue'
import TourTooltip from './TourTooltip.vue'
import { TOUR_STEPS, type TourPrepare, type TourRequire, type TourStep } from '@/config/tourSteps'
import { queryTourAnchor } from '@/config/tourAnchors'
import { useTourStore } from '@/stores/tour'
import { useAgentStore } from '@/stores/agent'
import {
  cancel as cancelNarration,
  setMuted,
  speak,
  prefetch,
  narratorState,
} from '@/composables/useTourNarrator'

/** 布局命令事件名（由 Workspace 侧监听并执行；本组件不认识它们的实现） */
const EVT_ENSURE_SIDEBAR = 'tour:ensure-sidebar'
const EVT_ENSURE_RIGHT_PANEL = 'tour:ensure-right-panel'
/** 切回对话视图复用**既有**的事件：Workspace 的 onMounted 已经在监听它了 */
const EVT_VIEW_NAVIGATE = 'view-navigate'
/** 重播入口（账户菜单发） */
const EVT_REPLAY = 'tour:replay'

const store = useTourStore()
const agentStore = useAgentStore()

const offering = ref(false)
const summaryOpen = ref(false)

/** 等 n 帧：Vue 渲染 + antd 布局都是异步的，量早了会拿到错的盒子 */
function nextFrames(n: number): Promise<void> {
  return new Promise((resolve) => {
    let left = n
    const step = () => (left-- > 0 ? requestAnimationFrame(step) : resolve())
    step()
  })
}

function runPrepare(p?: TourPrepare) {
  if (!p) return
  if (p === 'ensure-sidebar') window.dispatchEvent(new CustomEvent(EVT_ENSURE_SIDEBAR))
  else if (p === 'ensure-right-panel') window.dispatchEvent(new CustomEvent(EVT_ENSURE_RIGHT_PANEL))
  else if (p === 'goto-chat')
    window.dispatchEvent(new CustomEvent(EVT_VIEW_NAVIGATE, { detail: { view: 'chat' } }))
}

/**
 * 前置判定的**唯一实现**。
 *
 * ★ 这里刻意只剩一个 `agent-selected`：
 *   曾经还写过一条 `'chat-view'`，但 `currentView` 是 Workspace 的 `<script setup>` 局部 ref，
 *   外部根本读不到 —— 那就是一条**永远评估不了**的假门禁，比没有更糟（它看着像有）。
 *   视图有没有切回去，改由下面「锚点元素在不在」这个**直接事实**来判，不问状态变量。
 */
const REQUIRE_TEXT: Record<TourRequire, string> = {
  'agent-selected':
    '当前选中的是店秘书——它是纯对话入口、没有右侧参数面板。选中其它专员之后重看这一步即可。',
}

function requireOk(id: TourRequire): boolean {
  if (id === 'agent-selected') {
    const a = agentStore.currentAgent
    return !!a && a.id !== 'secretary'
  }
  return false
}

/**
 * 走到第 i 步。
 *
 * ★ 递归**向前**推进（遇到不满足的直接试下一步），而不是「渲染一个没盒子的空步骤」：
 *   对着空气讲一步，用户看到的是「高亮消失了但气泡还在讲」，完全无法归因。
 */
async function goto(i: number) {
  if (i >= TOUR_STEPS.length) {
    finish()
    return
  }
  const step: TourStep = TOUR_STEPS[i]
  store.index = i
  store.setRect(null)

  runPrepare(step.prepare)
  await nextFrames(2)

  // ① 声明了前置却没过 ⇒ 跳过，并给出**具体**原因
  if (step.requires && !requireOk(step.requires)) {
    store.markSkip(step.id, step.title, REQUIRE_TEXT[step.requires])
    await goto(i + 1)
    return
  }

  // ② 锚点此刻没挂载 ⇒ 跳过
  const el = queryTourAnchor(step.anchor)
  if (!el) {
    store.markSkip(step.id, step.title, '这一块当时没有出现在界面上')
    await goto(i + 1)
    return
  }

  // ③ 存在但宽高为 0（收起态 / 被 flex 压扁）⇒ 跳过，不能对着一个空盒讲
  el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  await nextFrames(1)
  const r = el.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) {
    store.markSkip(step.id, step.title, '这一块当时是收起状态（宽度为零）')
    await goto(i + 1)
    return
  }

  store.setRect({ top: r.top, left: r.left, width: r.width, height: r.height })
  void speak(step.narration)
  // 克隆通道要联网合成，现用现合会在「下一步」上卡一下 ⇒ 提前把下一句合成好。
  // ★ 只是提速：预取失败不报错，真正播报时会再走一遍并如实说明。
  const nxt = TOUR_STEPS[i + 1]
  if (nxt) void prefetch(nxt.narration)
}

/** 只重算当前这一步的盒子：resize / 滚动 / 图表重排都会让旧矩形过期 */
function remeasure() {
  if (!store.running || !store.current) return
  const el = queryTourAnchor(store.current.anchor)
  if (!el) return
  const r = el.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) return
  store.setRect({ top: r.top, left: r.left, width: r.width, height: r.height })
}

function begin() {
  offering.value = false
  summaryOpen.value = false
  store.start()
  void goto(0)
}

/** 「跳过 / 不再提示」：也算见过一次，不反复骚扰 */
function decline() {
  offering.value = false
  store.abandon()
}

function finish() {
  cancelNarration()
  const hadSkips = store.skips.length > 0
  store.finish()
  summaryOpen.value = hadSkips
}

function onPrev() {
  if (store.prev()) void goto(store.index)
}

function onNext() {
  cancelNarration()
  if (store.isLast) {
    finish()
    return
  }
  if (store.next()) void goto(store.index)
}

function toggleMute() {
  setMuted(!narratorState.muted)
  // 解除静音时立刻把当前这步补念一遍：否则用户会以为那个开关没生效
  if (!narratorState.muted && store.current) void speak(store.current.narration)
}

function onEscape(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (store.running) finish()
  else if (offering.value) decline()
}

/** 外部（账户菜单）触发重播：它在 Ui 上的那个按钮发 `tour:replay`，本组件只认这一个入口 */
function onReplay() {
  summaryOpen.value = false
  offering.value = false
  store.start()
  void goto(0)
}

onMounted(() => {
  store.hydrate()
  window.addEventListener('keydown', onEscape)
  window.addEventListener('resize', remeasure)
  // capture=true：真正滚动的往往是页面的内部 scroll 容器，冒泡阶段监听不到它们
  window.addEventListener('scroll', remeasure, true)
  window.addEventListener(EVT_REPLAY, onReplay)
  // 首帧别抢：店铺列表与账户上下文都还在 Workspace 的异步里加载，
  // 立刻弹卡会出现「卡已弹出、左上角店名还是空的」的观感
  if (!store.seen) window.setTimeout(() => (offering.value = !store.running), 900)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onEscape)
  window.removeEventListener('resize', remeasure)
  window.removeEventListener('scroll', remeasure, true)
  window.removeEventListener(EVT_REPLAY, onReplay)
  cancelNarration()
})
</script>

<style scoped>
.tour-offer {
  position: fixed;
  right: var(--space-24);
  bottom: var(--space-24);
  z-index: 1902;
  width: 300px;
  padding: var(--space-14) var(--space-16) var(--space-12);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-12);
  box-shadow: var(--shadow-overlay);
  color: var(--text-primary);
}

.to-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}

.to-icon { font-size: var(--font-size-18); line-height: 1; }
.to-title { font-size: var(--font-size-14); font-weight: 600; }
.to-close {
  margin-left: auto;
  width: 22px;
  height: 22px;
  border: 0;
  background: transparent;
  color: var(--text-disabled);
  font-size: var(--font-size-16);
  line-height: 1;
  border-radius: var(--radius-6);
  cursor: pointer;
}
.to-close:hover { background: var(--bg-hover-light); color: var(--primary); }

.to-body {
  font-size: var(--font-size-12);
  line-height: 1.7;
  color: var(--text-secondary);
}

.tour-summary { width: 340px; }

.ts-list {
  margin: var(--space-8) 0 0;
  padding-left: var(--space-16);
}

.ts-list li { margin-bottom: var(--space-4); }

.ts-hint {
  margin-top: var(--space-8);
  color: var(--text-tertiary);
}

.to-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-8);
  margin-top: var(--space-12);
}

.to-btn {
  height: 30px;
  padding: 0 var(--space-14);
  font-size: var(--font-size-13);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.16s ease;
}

.to-btn:hover { color: var(--primary); border-color: var(--primary); }

.to-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 600;
}

.to-primary:hover { background: var(--primary-hover); border-color: var(--primary-hover); color: #fff; }
</style>
