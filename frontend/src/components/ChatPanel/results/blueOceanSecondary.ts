/**
 * 蓝海结果「悬浮次要指标卡」的非类目项
 * ====================================
 * r371h 从 `BlueOceanResult.vue` **外移**。
 *
 * 为什么外移：宿主文件已在**体量棘轮**冻结表内（上限 1324 行，
 * `backend/tests/test_source_size_ratchet.py`），而「类目中文化」那处改动
 * 使它涨到 1330 ⇒ 撞 R2「只许降不许升」。棘轮注释对这种情况给的指引是
 * 「**拆出独立模块**，而不是继续往上加」——这里把与中文化**无关**的四项
 * （星级 / 变体 / BSR / 评论）搬出来，让宿主净减。
 *
 * ★ 类目那一项**刻意留在宿主里**，不搬：
 *   `tests/unit/categoryZh.test.ts` 末尾有一条**枚举型**源码形态判据
 *   （`expect(readSrc('…/BlueOceanResult.vue')).toContain('displayCategory')`）。
 *   整体搬走会把那条判据**静默打红**，而「改判据去迁就代码」是本仓
 *   反复警告的形态 ⇒ 保留 `displayCategory` 在宿主内的真实调用。
 *
 * ★ `ratingClass` 一并搬进来，而不是复制一份：它在宿主内**只被这里**
 *   调用（已核：全仓无门禁依赖该符号，`grep -rn ratingClass scripts/ tests/` 为空）。
 *   落地后宿主不再需要它 ⇒ 这是**移动唯一实现**，不是「同名多份」。
 */

/** 综合评分跳色：星级、蓝海分通用 */
export function ratingClass(r: number): string {
  if (r >= 4.2) return 'good'
  if (r >= 3.8) return ''
  return 'warn'
}

/** 悬浮次要指标卡的一项 */
export interface SecondaryItem {
  label: string
  value: string
  cls?: string
}

/**
 * 星级 / 变体 / BSR / 评论 —— **不含类目**（类目由宿主渲染，见文件头）。
 *
 * 返回值顺序即界面顺序；`cls` 供宿主样式表按类名上色（`.good` / `.warn` /
 * `.variation-few` / `.variation-many`，样式仍在宿主 `<style scoped>` 里）。
 */
export function secondaryMetrics(record: any): SecondaryItem[] {
  const rating = record.rating ? Number(record.rating).toFixed(1) : '-'
  const variation = record.variation_count ?? 1
  const bsr = record.bsr_rank ? Number(record.bsr_rank).toLocaleString() : '-'
  const review = record.review_count ? Number(record.review_count).toLocaleString() : '-'
  return [
    { label: '星级', value: `★ ${rating}`, cls: ratingClass(record.rating || 0) },
    {
      label: '变体',
      value: `${variation} 个`,
      cls: variation <= 3 ? 'variation-few' : 'variation-many',
    },
    { label: 'BSR', value: `#${bsr}` },
    { label: '评论', value: review },
  ]
}
