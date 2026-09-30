<template>
  <!-- 思考过程轨迹（第 210 轮）。
       ★ 渲染规则只有两条：
         ① 流光期间**默认展开** —— 老板要的是「看到它一步步推进」，不是为了留档；
         ② 结果到达后**默认折叠** —— 老板原话「然后有结果出结果（过程折叠掉）」。
         用户手动干预过就尊重用户（`manual`），不再被 loading 自动翻回来。 -->
  <div v-if="steps.length" class="thinking-trace" :class="{ 'is-live': loading }">
    <button type="button" class="tt-head" @click="toggle">
      <span class="tt-caret">{{ open ? '▾' : '▸' }}</span>
      <span class="tt-label">思考过程</span>
      <span class="tt-count">{{ steps.length }} 步</span>
      <span v-if="totalMs" class="tt-total">{{ fmtMs(totalMs) }}</span>
      <span v-if="loading" class="tt-pulse" aria-hidden="true"></span>
    </button>

    <div v-show="open" class="tt-body">
      <div v-for="(s, i) in steps" :key="s.id || i" :class="['tt-step', `st-${statusOf(s)}`]">
        <span class="tt-dot" aria-hidden="true"></span>
        <span class="tt-text">{{ s.title }}</span>
        <code v-if="s.tool && s.tool !== s.title" class="tt-tool">{{ s.tool }}</code>
        <span v-if="s.ms != null" class="tt-ms">{{ fmtMs(s.ms) }}</span>
        <span v-if="statusOf(s) === 'stale'" class="tt-state">未完成</span>
        <span v-else-if="statusOf(s) === 'error'" class="tt-state">失败</span>

        <!-- 入参与返回**分两行**：踩过的坑是挤进一个字段，合成一行后必然丢一半。 -->
        <div v-if="s.detail || s.result" class="tt-io">
          <div v-if="s.detail" class="tt-io-line">
            <span class="tt-io-tag">入参</span><span class="tt-io-text">{{ s.detail }}</span>
          </div>
          <div v-if="s.result" class="tt-io-line">
            <span class="tt-io-tag">返回</span><span class="tt-io-text">{{ s.result }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 思考过程轨迹组件（第 210 轮）
 *
 * 消费后端 `event: step`（见 `ai_infra/sse.py::step` / `ToolTrace`）：
 * 一条工具调用由「开始 + 结束」两条事件组成，`stores/chat.ts::appendThinkingStep`
 * 已按 `id`(run_id) 把它们**合成一行**，所以这里拿到的每条 = 一次工具调用。
 *
 * ★ 第 211 轮：`title` 现在是**工具人话名**（如「出价优化建议」）。
 *   人话标题的**唯一真源**在后端业务侧（`tools_catalog.tool_title`），由
 *   `ToolTrace` 的 `title_resolver` **注入**得到 —— **前端不抄那张表**
 *   （抄了就是第二份真源，必然与工具目录漂移）。后端拿不到标题时回落
 *   「正在调用工具」，是**可见的降级**（过程不会被静默丢掉）。
 *   `tool` 仍是**原始英文名**，保留渲染供排查；但当它与 `title` 相同时
 *   （名字没登记进目录 ⇒ `tool_title()` 原样返回它）不再重复渲染一遍。
 *
 * ★ 为什么 `status` 要经过 `statusOf()` 映射，而不是直接用：
 *   后端只知道「有没有收到 `on_tool_end`」。**没收到不等于还在跑** ——
 *   典型情形是工具触发了人工审批、图在此处**暂停**，本轮流就这么结束了。
 *   若照原样渲染成「进行中」，界面上会留一个永远转圈的假象。
 *   所以：流光结束后仍是 running 的步骤 → `stale`（「未完成」），如实显示。
 *
 * ★ 配色全部走主题变量：本仓有「硬编码颜色」门禁，且深浅两套主题靠变量切换，
 *   写死 hex 会让本组件在深色主题下变成一块看不清的浅色补丁。
 */
import { computed, ref, watch } from 'vue'

import type { ThinkingStep } from '@/api/stream'

const props = defineProps<{
  /** 按发生顺序排列的步骤；由 store 按 id 合并，故一条 = 一次工具调用 */
  steps: ThinkingStep[]
  /** 本轮是否仍在流式中（决定默认展开折叠、以及 running 的语义） */
  loading?: boolean
}>()

/** 用户是否手动干预过展开态。`null` = 跟随 loading 自动开合 */
const manual = ref<boolean | null>(null)
const open = computed(() => manual.value ?? !!props.loading)
function toggle() {
  manual.value = !open.value
}

// 新一轮开始（false → true）时清掉上一轮的手动干预。
// 正常情况下每条消息各自持有本组件、状态天然隔离；这条 watch 是防御性的：
// 一旦哪天消息被复用（`v-for` 的 key 退化），手动折叠态会跨轮残留，且零报错。
watch(
  () => props.loading,
  (now, prev) => {
    if (now && !prev) manual.value = null
  },
)

/** 有耗时的步骤耗时之和 —— 只统计拿得到耗时的，不拿 0 充数 */
const totalMs = computed(() =>
  props.steps.reduce((sum, s) => sum + (typeof s.ms === 'number' ? s.ms : 0), 0),
)

/**
 * 界面态：`running` / `done` / `error` / `stale`。
 * 见文件头 —— `stale` = 流光已结束但仍停在 running（多半是卡在人工审批）。
 */
function statusOf(s: ThinkingStep): 'running' | 'done' | 'error' | 'stale' {
  if (s.status === 'running' && !props.loading) return 'stale'
  return s.status
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<style scoped>
.thinking-trace {
  margin: 0 0 8px;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  background: var(--bg-elevated);
  overflow: hidden;
}

.tt-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
.tt-head:hover {
  background: var(--bg-hover-light);
}

.tt-caret {
  font-size: 10px;
  color: var(--text-tertiary);
}
.tt-label {
  color: var(--text-primary);
  font-weight: 600;
}
.tt-count,
.tt-total {
  color: var(--text-tertiary);
}

/* 流光中的呼吸点：用不透明度动效，不依赖颜色 —— 换主题也不用改 */
.tt-pulse {
  width: 6px;
  height: 6px;
  margin-left: 2px;
  border-radius: var(--radius-8);
  background: var(--primary);
  animation: tt-breathe 1.2s ease-in-out infinite;
}
@keyframes tt-breathe {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}

.tt-body {
  padding: 2px 10px 8px;
  border-top: 1px solid var(--border-base);
}

.tt-step {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 4px 0 4px 10px;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
/* 左侧竖线 + 圆点：让它读起来像一条时间线，而不是一堆并列的句子 */
.tt-step::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-base);
}
.tt-dot {
  position: absolute;
  left: -1px;
  top: 9px;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-8);
  background: var(--text-disabled);
}
.tt-step.st-running .tt-dot { background: var(--primary); }
.tt-step.st-done .tt-dot { background: var(--success); }
.tt-step.st-error .tt-dot { background: var(--danger); }

.tt-text {
  color: var(--text-primary);
}
.tt-tool {
  padding: 0 4px;
  border-radius: var(--radius-2);
  background: var(--bg-active-light);
  color: var(--text-secondary);
  font-size: var(--font-size-12);
}
.tt-ms {
  color: var(--text-tertiary);
}
.tt-state {
  padding: 0 4px;
  border-radius: var(--radius-2);
  font-size: var(--font-size-12);
}
.tt-step.st-error .tt-state {
  background: var(--danger-bg);
  color: var(--danger);
}
.tt-step.st-stale .tt-state {
  background: var(--warning-bg);
  color: var(--warning-strong);
}

.tt-io {
  flex-basis: 100%;
  padding-left: 2px;
}
.tt-io-line {
  display: flex;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: var(--font-size-12);
}
.tt-io-tag {
  flex: 0 0 auto;
}
/* 摘要可能很长（后端已截断到 200 字符），换行而不是撑破容器 */
.tt-io-text {
  word-break: break-all;
}
</style>
