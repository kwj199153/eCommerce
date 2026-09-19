<template>
  <div v-if="plan && plan.total" class="plan-bar" :class="{ 'is-open': expanded }">
    <!-- 头：一行摘要 + 进度，点一下折叠/展开 -->
    <div class="plan-head" @click="expanded = !expanded">
      <span class="plan-label">
        <UnorderedListOutlined />
        当前计划
      </span>
      <span class="plan-progress">{{ plan.completed }} / {{ plan.total }} 已完成</span>
      <span class="plan-track" aria-hidden="true">
        <span class="plan-fill" :style="{ width: pctText }" />
      </span>
      <span class="plan-toggle">{{ expanded ? '收起' : '展开' }}</span>
    </div>

    <!-- 明细：状态图标 + 编号 + 内容 +（可选）补充说明 -->
    <ul v-if="expanded" class="plan-items">
      <li
        v-for="item in plan.items"
        :key="item.id"
        class="plan-item"
        :class="`tone-${viewOf(item.status).tone}`"
      >
        <component
          :is="viewOf(item.status).icon"
          class="plan-icon"
          :title="viewOf(item.status).label"
        />
        <span class="plan-id">{{ item.id }}</span>
        <span class="plan-content">{{ item.content }}</span>
        <span v-if="item.note" class="plan-note">—— {{ item.note }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
/**
 * 「当前计划」条 —— 店秘书规划器（第 148 轮批 C3 后端机制）的**前端消费端**。
 *
 * ★★ 这个组件为什么必须存在（第 155 轮的教训）
 * ============================================
 * 批 C3 当时完成了后端全部机制（`plan_tasks` / `update_task` 工具、计划落图状态、
 * `OrchestratorResponse.plan` 回传、以及一条门禁），并在交付说明里写了
 * **「子任务状态可在 UI 展示」**。但实测（第 155 轮侦察）：
 *   · 前端 `SecretaryResponse` **没有声明 `plan` 字段**；
 *   · 编排层**从不读** `res.plan`；
 *   · 全仓**没有任何**计划/待办渲染组件。
 * 也就是说 —— 计划出了后端就消失了，而**门禁恰好停在断点前一步**
 * （只断言"端点回填了 `plan` 字段"，没断言"有界面在渲染它"）。
 * 这正是本仓反复出现的形态：**「后端有 ⇒ 前端在用」是个未经检验的假设**。
 * 所以本组件同时配了一条门禁（`scripts/check-plan-consumption.cjs`），
 * 把「API 类型 → store → 组件 → 编排层」四环逐环钉住。
 *
 * ★ 渲染什么、不渲染什么
 * ======================
 * · `completed` / `total` **直接读后端**（`PlanSummary`），**不**在这里
 *   `items.filter(x => x.status === 'completed').length` —— 那会变成第二份
 *   计数实现：后端哪天改了判据（例如把 `blocked` 也算完成），它不会跟着变，
 *   而界面会安静地显示错的进度。
 * · 状态**图标/配色**是纯展示层职责（后端 `plan.py` 的 `STATUS_MARKS` 是给
 *   模型看的 `[ ]` 文本，不是给 UI 的），所以这里有一张映射表；但
 *   `viewOf()` 对未知状态**必须有兜底**，否则后端新增一个状态会让整条计划
 *   渲染崩掉（而那正是"界面上什么都没有、控制台里一个红字"的经典形态）。
 * · `by_status` 提供了各状态计数，本组件目前不展示（避免与进度条重复），
 *   但类型上保留 —— 它是"状态全集"的唯一权威来源。
 */
import { computed, ref, type Component } from 'vue'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  MinusCircleOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons-vue'
import type { PlanSummary } from '@/api/secretary'

const props = defineProps<{
  /** 后端 `OrchestratorResponse.plan` / `GET /orchestrator/plan`。`null` = 没有计划。 */
  plan?: PlanSummary | null
}>()

/** 默认展开：计划的全部意义就是"一眼看到现在走到哪了"。长计划靠 CSS 限高滚动。 */
const expanded = ref(true)

const pctText = computed(() => {
  const p = props.plan
  if (!p || !p.total) return '0%'
  const done = Math.max(0, Math.min(p.completed, p.total))
  return `${Math.round((done / p.total) * 100)}%`
})

/**
 * 状态 → 展示三要素。
 *
 * ★ 显式 `interface` 而不是 `as const`：`as const` 会把 `label` 收窄成字面量
 *   联合（`"待办" | "进行中" | ...`），于是 `viewOf()` 的**兜底分支**赋一个
 *   普通 `string` 就编译不过（TS2322）—— 而兜底恰恰是这条设计里最该存在的东西。
 *   （第 155 轮实测踩到，`vue-tsc` 直接报出来的。）
 * ★ 表里**只列后端 `TASK_STATUSES` 的四个取值**；多出来的状态走 `viewOf` 兜底。
 *   `Record<string, ...>` 而不是穷尽键，是为了让"表里没有"这件事在运行期可见，
 *   同时不让 TS 把新增状态当成编译错误（后端先上、前端后跟是正常节奏）。
 */
interface StatusView {
  /** 状态图标组件（ant-design-vue） */
  icon: Component
  /** CSS 类后缀 → `.plan-item.tone-<tone>` */
  tone: 'pending' | 'active' | 'done' | 'blocked'
  /** 中文状态名（图标 title，也供屏幕阅读器） */
  label: string
}

const STATUS_VIEW: Record<string, StatusView> = {
  pending: { icon: MinusCircleOutlined, tone: 'pending', label: '待办' },
  in_progress: { icon: ClockCircleOutlined, tone: 'active', label: '进行中' },
  completed: { icon: CheckCircleOutlined, tone: 'done', label: '已完成' },
  blocked: { icon: ExclamationCircleOutlined, tone: 'blocked', label: '受阻' },
}

function viewOf(status: string): StatusView {
  // ★ 兜底而不是断言：后端将来加一个状态时，界面应该"少一个图标"，
  //   而不是整块白掉。
  return (
    STATUS_VIEW[status] || {
      icon: MinusCircleOutlined,
      tone: 'pending',
      label: status || '未知',
    }
  )
}
</script>

<style scoped>
.plan-bar {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background-color: var(--bg-hover-light);
  margin-bottom: var(--space-10);
  overflow: hidden;
}

/* ---- 头部 ---- */
.plan-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-12);
  cursor: pointer;
  user-select: none;
}
.plan-head:hover {
  background-color: var(--bg-card-pill);
}
.plan-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}
.plan-progress {
  font-size: var(--font-size-11-5);
  color: var(--text-secondary);
  flex-shrink: 0;
}
.plan-track {
  flex: 1;
  min-width: 40px;
  height: 4px;
  border-radius: var(--radius-2);
  background-color: var(--border-base);
  overflow: hidden;
}
.plan-fill {
  display: block;
  height: 100%;
  background-color: var(--success);
  transition: width 0.25s ease;
}
.plan-toggle {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  flex-shrink: 0;
}

/* ---- 明细 ---- */
.plan-items {
  list-style: none;
  margin: 0;
  padding: var(--space-4) var(--space-12) var(--space-10);
  border-top: 1px solid var(--border-base);
  max-height: 220px;
  overflow-y: auto;
}
.plan-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-6);
  padding: var(--space-3) 0;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  line-height: 1.5;
}
.plan-icon {
  flex-shrink: 0;
  font-size: var(--font-size-12);
  transform: translateY(1px);
}
.plan-id {
  flex-shrink: 0;
  font-family: SFMono-Regular, Consolas, monospace;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.plan-content {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}
.plan-note {
  flex-shrink: 0;
  max-width: 45%;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  word-break: break-word;
}

/* ---- 状态配色（四态各一档，与后端 TASK_STATUSES 一一对应）---- */
.plan-item.tone-pending .plan-icon { color: var(--text-tertiary); }
.plan-item.tone-active .plan-icon { color: var(--primary); }
.plan-item.tone-done .plan-icon { color: var(--success); }
.plan-item.tone-blocked .plan-icon { color: var(--danger); }

.plan-item.tone-active .plan-content { color: var(--text-primary); }
.plan-item.tone-done .plan-content { color: var(--text-tertiary); text-decoration: line-through; }
.plan-item.tone-blocked .plan-content { color: var(--danger); }
</style>
