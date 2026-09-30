<template>
  <div class="rv-unsupported">
    <span class="rv-unsupported-icon">⊘</span>
    <span class="rv-unsupported-text">
      后端暂未提供「{{ label }}」—— 该图位保留占位，不再用内联数字填充。
    </span>
  </div>
</template>

<script setup lang="ts">
/**
 * 复盘看板的「后端不提供该维度」占位。
 *
 * ★ 为什么要有一个**显式**占位而不是干脆把图位删掉（第 167 轮 #725）：
 *   旧 `ReviewConfig.vue` 的这些图位画的是 `@/mock/reviewDashboard` 里的内联常量
 *   —— 逐日销量、30 天 GMV、周对比、7 天广告趋势、流量占比、关键词明细、
 *   评价变动、逐 ASIN 采购成本。这 8 类数据在**真后端没有任何数据源**
 *   （`backend/modules/review_analyst/service.py` 只产出汇总型 metrics + details）。
 *
 *   删掉图位会让「这里本该有东西」这件事消失，下一个人无从判断是没做还是不做；
 *   留着假数字则是最糟的选项（用户会当成自己店铺的数据）。占位是中间态里
 *   唯一诚实的那个：**说清楚缺什么、为什么缺**。
 *
 * 归宿（`frontend/src/api/review.ts` 的 `REVIEW_UNAVAILABLE_DIMENSIONS` 有同一份清单）：
 *   要么后端补数据源（独立的后端轮次），要么这些图位永久保持占位。
 *   **不要**再把编造的数字填回来。
 */
defineProps<{ label: string }>()
</script>

<style scoped>
.rv-unsupported {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  min-height: 56px;
  padding: 12px 14px;
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-10);
  background: var(--bg-hover-light);
  color: var(--text-tertiary);
  font-size: var(--font-size-11-5);
  line-height: 1.6;
}
.rv-unsupported-icon { font-size: var(--font-size-15); opacity: .7; flex-shrink: 0; }
.rv-unsupported-text { flex: 1; min-width: 0; }
</style>
