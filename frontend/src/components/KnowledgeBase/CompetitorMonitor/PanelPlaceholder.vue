<template>
  <div class="panel-placeholder">
    <!-- 面板顶部：说明 "读的是监控池选中的同一份数据" -->
    <div class="pp-intro">
      <div class="pp-title">{{ meta.icon }} {{ meta.title }}</div>
      <div class="pp-desc">{{ meta.desc }}</div>
      <a-tag color="blue" class="pp-src">数据源 = 监控池已圈选 {{ viewRecords.length }} 个 ASIN，与其它面板共用</a-tag>
    </div>

    <!-- 选中 ASIN 提示条（空时引导回池勾选） -->
    <div v-if="!viewRecords.length" class="pp-guide">
      <a-empty description="监控池中暂无可分析对象，请到「监控池」勾选或添加竞品 ASIN">
        <a-button type="primary" size="small" @click="$emit('goto-pool')">去监控池勾选</a-button>
      </a-empty>
    </div>

    <template v-else>
      <!-- 每个目标 ASIN 一个小卡，展示该面板视角下的派生预览（证明共用数据） -->
      <div class="pp-cards">
        <div v-for="r in viewRecords" :key="r.asin" class="pp-card">
          <div class="pc-head">
            <span class="pc-asin">{{ r.asin }}</span>
            <span class="pc-brand">{{ r.brand }}</span>
          </div>

          <!-- 价格历史预览 -->
          <template v-if="panel === 'price'">
            <div class="kv-row"><span>当前价</span><b>${{ r.latest_price.toFixed(2) }}</b></div>
            <div class="kv-row"><span>7 日变化</span><b :class="r.price_change_7d < 0 ? 'down' : 'up'">{{ r.price_change_7d }}%</b></div>
            <div class="kv-row"><span>近期促销</span><b>{{ recentDeals(r).length ? recentDeals(r).map(d => d.label).join('、') : '无' }}</b></div>
            <div class="mini-hist">
              <span v-for="p in r.price_history.slice(-20)" :key="p.date" class="bar" :style="{ height: barH(p.price, r.price_history), background: p.coupon || p.deal_type ? 'var(--danger)' : 'var(--primary)' }" :title="`${p.date} $${p.price}`"></span>
            </div>
            <a-tag class="pending-badge">📈 完整折线 + Coupon/Prime/LD 标记待渲染</a-tag>
          </template>

          <!-- BSR 趋势预览 -->
          <template v-else-if="panel === 'bsr'">
            <div class="kv-row"><span>当前 BSR</span><b>#{{ r.latest_bsr.toLocaleString() }}</b></div>
            <div class="kv-row"><span>7 日变化</span><b :class="r.bsr_change_7d < 0 ? 'up' : 'down'">{{ r.bsr_change_7d < 0 ? '上升 ' + Math.abs(r.bsr_change_7d) : '下滑 ' + r.bsr_change_7d }}</b></div>
            <div class="mini-hist-inv">
              <span v-for="b in r.bsr_history.slice(-20)" :key="b.date" class="bar-inv" :style="{ height: invBarH(b.bsr, r.bsr_history), background: 'var(--success)' }" :title="`${b.date} #${b.bsr}`"></span>
            </div>
            <a-tag class="pending-badge">📈 类目排名趋势图待渲染（起量/掉量/断货周期）</a-tag>
          </template>

          <!-- 评论星级预览 -->
          <template v-else-if="panel === 'review'">
            <div class="kv-row"><span>评分</span><b>★ {{ r.rating.toFixed(1) }}</b></div>
            <div class="kv-row"><span>总评论 / 7日新增</span><b>{{ r.review_count.toLocaleString() }} / +{{ r.reviews_added_7d }}</b></div>
            <div class="neg-list" v-if="recentNegatives(r).length">
              <div v-for="(e,i) in recentNegatives(r)" :key="i" class="neg-item">🔴 {{ e.date }} 新增差评：{{ e.snippet }}</div>
            </div>
            <div v-else class="neg-none">近 7 天无差评预警</div>
            <a-tag class="pending-badge">💬 星级曲线 / 差评原文 / 每日新增待渲染</a-tag>
          </template>

          <!-- 变体预览 -->
          <template v-else-if="panel === 'variation'">
            <div class="kv-row"><span>当前变体</span><b>{{ r.variations.length }} 个</b></div>
            <div class="var-chips">
              <span v-for="v in r.variations" :key="v.child_asin" class="var-chip" :class="v.in_stock ? 'ok' : 'out'" :title="v.child_asin">
                {{ v.color }} ${{ v.price.toFixed(2) }} {{ v.in_stock ? '' : '(缺)' }}
              </span>
            </div>
            <a-tag class="pending-badge">🧩 新增/删除变体、子 ASIN 价格销量对比待渲染</a-tag>
          </template>

          <!-- Listing 快照预览 -->
          <template v-else-if="panel === 'listing'">
            <div class="kv-row"><span>近期改动</span><b>{{ r.listing_changes.length }} 条</b></div>
            <div v-for="c in r.listing_changes.slice(0, 3)" :key="c.id" class="lc-row">
              <span class="lc-field">{{ c.field_name }}</span>
              <span class="lc-date">{{ c.changed_at }}</span>
              <span class="lc-prev">{{ c.new_preview.slice(0, 26) }}…</span>
            </div>
            <a-tag class="pending-badge">📄 标题/五点/A+/主图视频 diff 日志待渲染</a-tag>
          </template>

          <!-- 库存入仓预览 -->
          <template v-else-if="panel === 'inventory'">
            <div class="kv-row">
              <span>库存状态</span>
              <b :class="r.stock_status === 'out_of_stock' ? 'down' : r.stock_status === 'low_stock' ? 'warn' : 'up'">
                {{ r.stock_status === 'out_of_stock' ? '缺货' : r.stock_status === 'low_stock' ? '库存告急' : '在售' }}
              </b>
            </div>
            <div class="kv-row"><span>预估可售</span><b>{{ r.estimated_units_remaining === null ? '—（已断货）' : r.estimated_units_remaining.toLocaleString() + ' 件' }}</b></div>
            <div class="kv-row"><span>月销估算</span><b>{{ r.est_monthly_sales.toLocaleString() }} 件</b></div>
            <a-tag class="pending-badge">📦 断货周期判断 / 补货入仓估算待渲染</a-tag>
          </template>
        </div>
      </div>
    </template>

    <!-- 面板骨架底部提示 -->
    <div class="pp-foot">
      <a-alert
        type="info"
        show-icon
        message="这是工作台骨架原型"
        description="当前仅演示「一套监控池 → 多个查看面板」的共用数据模型。折线图 / 差评原文抓取 / Listing diff / 入仓建议等将在后续轮次逐个把面板做实。"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useMonitorPoolStore, type MonitorPoolRecord, type PricePoint, type BsrPoint } from '@/stores/monitorPool'

const props = defineProps<{ panel: string }>()
const emit = defineEmits<{ (e: 'goto-pool'): void }>()

const pool = useMonitorPoolStore()

const metaMap: Record<string, { icon: string; title: string; desc: string }> = {
  price: { icon: '📉', title: '价格历史追踪', desc: '历史售价、最低/最高价、优惠券 Coupon、Prime 折扣、LD/7DD 限时秒杀标记。' },
  bsr: { icon: '📈', title: 'BSR 类目排名趋势', desc: '每日 BSR 波动，识别竞品起量、掉量、断货周期。' },
  review: { icon: '💬', title: '评论 & 星级监控', desc: '每日新增评论、差评预警、星级变化曲线、抓取评论原文。' },
  variation: { icon: '🧩', title: '变体监控', desc: '竞品新增/删除变体、子 ASIN 价格与销量变化。' },
  listing: { icon: '📄', title: 'Listing 快照变更', desc: '标题、五点、A+ 页面、主图、视频的修改日志。' },
  inventory: { icon: '📦', title: '库存 / 入仓估算', desc: '可售数、断货预警、按销量估算补货入仓节点（P1）。' },
}

const meta = computed(() => metaMap[props.panel] || metaMap.price)
const panel = computed(() => props.panel)

/** 面板读的是监控池「已圈选」的 ASIN —— 核心共用数据演示 */
const viewRecords = computed(() => {
  const sel = pool.selectedAsins
  if (sel.length) return pool.records.filter(r => sel.includes(r.asin))
  return pool.records.slice(0, 3)
})

function recentDeals(r: MonitorPoolRecord) {
  const out: Array<{ label: string }> = []
  for (const p of r.price_history.slice(-14)) {
    if (p.coupon) out.push({ label: 'Coupon' })
    if (p.is_prime_deal) out.push({ label: 'Prime' })
    if (p.deal_type === 'ld') out.push({ label: 'LD 秒杀' })
    if (p.deal_type === '7dd') out.push({ label: '7DD' })
    if (out.length >= 3) break
  }
  return Array.from(new Set(out.map(o => o.label))).map(l => ({ label: l }))
}

function recentNegatives(r: MonitorPoolRecord) {
  return r.review_events.filter(e => e.negative).slice(-3)
}

function maxOf(list: PricePoint[] | BsrPoint[]) {
  let m = 0
  for (const p of list as any[]) if (p.price ? p.price > m : p.bsr > m) m = p.price || p.bsr
  return m || 1
}
function barH(price: number, all: PricePoint[]) {
  return Math.max(6, Math.round((price / maxOf(all)) * 44)) + 'px'
}
function invBarH(bsr: number, all: BsrPoint[]) {
  // BSR 越小越好，反向：越小柱子越高
  const m = maxOf(all)
  return Math.max(6, Math.round(((m - bsr) / m) * 44) + 6) + 'px'
}
</script>

<style scoped>
.panel-placeholder { padding: 14px; height: 100%; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }
.pp-intro { }
.pp-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.pp-desc { font-size: 12px; color: var(--text-tertiary); margin: 4px 0 6px; line-height: 1.5; }
.pp-src { font-size: 11px; }
.pp-guide { flex: 1; display: flex; align-items: center; justify-content: center; }
.pp-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.pp-card { border: 1px solid var(--border-base); border-radius: 10px; padding: 12px; background: var(--bg-sidebar); }
.pc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.pc-asin { font-family: monospace; font-weight: 600; color: var(--primary); }
.pc-brand { font-size: 12px; color: var(--text-tertiary); }
.kv-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; }
.kv-row span { color: var(--text-tertiary); }
.kv-row b { color: var(--text-primary); }
.up { color: var(--success); }
.down { color: var(--danger); }
.warn { color: var(--warning); }
.mini-hist { display: flex; align-items: flex-end; gap: 2px; height: 50px; margin: 8px 0; }
.bar { width: 7px; border-radius: 2px 2px 0 0; }
.mini-hist-inv { display: flex; align-items: flex-end; gap: 2px; height: 50px; margin: 8px 0; }
.bar-inv { width: 7px; border-radius: 2px 2px 0 0; }
.neg-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.neg-item { font-size: 11px; color: var(--danger); background: var(--danger-bg); padding: 4px 8px; border-radius: 4px; }
.neg-none { font-size: 12px; color: var(--success); margin: 6px 0; }
.var-chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
.var-chip { font-size: 11px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-strong); }
.var-chip.ok { color: var(--success); background: var(--success-bg); border-color: var(--success-border); }
.var-chip.out { color: var(--danger); background: var(--danger-bg); border-color: var(--danger-border); }
.lc-row { display: flex; gap: 8px; align-items: center; font-size: 11px; padding: 3px 0; }
.lc-field { color: var(--primary); background: var(--bg-active-light); padding: 0 5px; border-radius: 3px; flex-shrink: 0; }
.lc-date { color: var(--text-tertiary); flex-shrink: 0; }
.lc-prev { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pending-badge { display: block; margin-top: 8px; font-size: 11px; color: var(--text-tertiary); }
.pp-foot { margin-top: auto; }
</style>
