<template>
  <table class="rd-table">
    <thead>
      <tr>
        <th>归因</th>
        <th>规则代号</th>
        <th>名称</th>
        <th class="num">
          优先级
        </th>
        <th>命中条件</th>
        <th>补偿方案</th>
        <th class="num">
          单笔上限
        </th>
        <th>启用</th>
        <th class="rd-table-act" />
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="r in rules"
        :key="r.id"
        :class="{ 'rd-rule-off': !r.enabled }"
      >
        <td><a-tag>{{ r.cause_label }}</a-tag></td>
        <td><code>{{ r.code }}</code></td>
        <td>{{ r.name || '—' }}</td>
        <td class="num">
          {{ r.priority }}
        </td>
        <td class="rd-rule-cond">
          {{ ruleCondText(r) }}
        </td>
        <td class="rd-rule-action">
          {{ ruleActionText(r) }}
        </td>
        <td class="num">
          {{ r.budget_cap > 0 ? r.budget_cap : '未设' }}
        </td>
        <td>
          <a-switch
            :checked="r.enabled"
            size="small"
            @click="emit('toggle', r)"
          />
        </td>
        <td class="rd-table-act">
          <a-button
            type="link"
            size="small"
            @click="emit('edit', r)"
          >
            编辑
          </a-button>
          <a-popconfirm
            title="确定删除这条规则？已生成的处置不受影响（存的是方案快照）。"
            @confirm="emit('remove', r)"
          >
            <a-button
              type="link"
              size="small"
              danger
            >
              删除
            </a-button>
          </a-popconfirm>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<script setup lang="ts">
/**
 * 补偿规则表（第 341 轮第四刀，从 `ReviewDeskConfig.vue` 拆出）。
 *
 * ★ 为什么只搬「表格」、不搬「整块视图」：
 *   `.rd-rules` 容器里还有 `.rd-rules-bar`（含【新建规则】按钮）与 `rulesError` 提示；
 *   而【新建规则】等动作最终打的是**写门禁名单里的补偿规则 CRUD**。本仓铁律 +
 *   门禁 `check-disposition-write-exit.cjs` C1/C2 要求那些写 API 的 `.vue` 出口
 *   **唯一且在本面板**，所以本组件只做「只读展示 + 把动作 emit 回父组件」，
 *   **不 import 任何 api**。
 *
 * ★ 事件契约（父组件按名字接线，改名即断）：
 *   · `edit(r)`   —— 打开规则编辑
 *   · `toggle(r)` —— 启用 / 停用
 *   · `remove(r)` —— 删除（父侧是 popconfirm 的 @confirm）
 *
 * ★ 样式：`<style scoped src="./rdTable.css">` 复用**与台账表同一份**表格样式；
 *   规则表独有的 `.rd-rule-*` 写在下面自己的 scoped 块里。
 */
import type { CompensationRule } from '@/api/trade'
import { ruleCondText, ruleActionText } from './reviewDeskVocabulary'

defineProps<{ rules: CompensationRule[] }>()

const emit = defineEmits<{
  (e: 'edit', r: CompensationRule): void
  (e: 'toggle', r: CompensationRule): void
  (e: 'remove', r: CompensationRule): void
}>()
</script>

<style scoped src="./rdTable.css"></style>

<style scoped>
/* 规则表**独有**：停用行压暗 + 长文案列允许换行（`.rd-table` 的 nowrap 会被 td 继承） */
.rd-rule-off {
  opacity: 0.55;
}
.rd-rule-cond,
.rd-rule-action {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  white-space: normal;
}
</style>
