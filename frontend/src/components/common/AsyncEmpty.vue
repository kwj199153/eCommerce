<script setup lang="ts">
/**
 * 异步取数口的「空态 / 失败态」统一呈现。
 *
 * ========
 * 为什么必须收成**一个**组件，而不是各页各写一份
 * ========
 *
 * 「读失败要说失败、不许说暂无」这条判定，若在 N 个页面各写一遍，
 * 后加的第 N+1 个页面必然漏掉 —— 本仓已有实测先例：mock 兜底从第 271 轮
 * （productLibrary / assetLibrary）一路漏到第 279 轮（candidateLibrary），
 * 靠人工全仓扫才补上。收成唯一真源之后：
 *   · 新增一个库只要用这个组件就自动合规；
 *   · 门禁只需守这一个文件 + 它的消费点（scripts/check-empty-state-honesty.cjs）。
 *
 * ========
 * 契约（两条**互斥**分支，不允许两个空态并存）
 * ========
 *
 *   error 非空 ⇒ **失败态**：文案 `${label}加载失败，请重试` + 「重试」按钮。
 *                此时**不显示** emptyDescription —— 「暂无数据」与「加载失败」
 *                同时出现是自相矛盾的：用户看到的不是「没有」，而是**没取到**，
 *                两者对应完全相反的操作（去添加 vs 去重试）。
 *   error 为空 ⇒ **空态**：文案 emptyDescription，无按钮。
 *
 * ★ 失败文案用**固定人话**，不把 error 的值直接铺到界面上：
 *   error 可能来自 axios（「Request failed with status code 500」）或后端 detail，
 *   那是给开发者看的。原始原因由各 store 的 `console.warn` 留痕（见
 *   `stores/*.ts` 的 catch），界面只说用户能懂的话。
 */
defineProps<{
  /** 失败原因（各 store 的 `loadError`，或页面本地的 `xxxError`）。非空即失败态。 */
  error?: string | null
  /** 资源名，与固定后缀拼成失败文案：label='账单' ⇒「账单加载失败，请重试」。 */
  label: string
  /** 空态文案（**无错**且无数据时展示）。 */
  emptyDescription: string
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <a-empty :description="error ? `${label}加载失败，请重试` : emptyDescription">
    <a-button v-if="error" size="small" type="primary" @click="emit('retry')">
      重试
    </a-button>
  </a-empty>
</template>
