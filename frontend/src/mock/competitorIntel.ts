/**
 * 竞品监控 Agent —— Mock 推理引擎（competitor-intel）
 *
 * 地位：第 3 层「推理层」。与 8 个看数工具（各自读池展示单一视角）不同，
 * 本引擎在用户用自然语言向「竞品监控员」提问时，读取统一监控池（MonitorPool）
 * 的完整时序数据，做跨 ASIN / 跨维度的聚合 → 归因 → 一句话解读 + 运营建议。
 *
 * 当前为「确定性 mock 推理」：用规则模板把池数据翻译成看似 LLM 的分析，
 * 用于先跑通「数据底座 → 圈选 ASIN → 推理 → 解读+证据」的完整闭环，
 * 后端真实 LLM（qwen/deepseek）接口留 TODO。
 *
 * 支持多轮：用户可用「他们/这几个/上面前三个」等代词指代，
 * 引擎无法从提问解析出明确 ASIN 时，自动回退到监控池「当前圈选 selectedAsins」，
 * 若仍为空则用全池 records（前若干条）。
 */

import { useMonitorPoolStore } from '@/stores/monitorPool'

// ====== 意图识别 ======
export type IntelIntent =
  | 'price'      // 调价 / 降价 / 促销
  | 'bsr'        // 排名 / 掉量 / 起量 / 断货周期
  | 'review'     // 评论 / 差评 / 星级
  | 'variation'  // 变体 / 子ASIN
  | 'listing'    // Listing快照 / 改标题 / 改主图 / A+
  | 'stock'      // 库存 / 断货 / 入仓
  | 'weekly'     // 周报 / 总结 / 复盘
  | 'anomaly'    // 异动 / 异常 / 暴涨 / 激增 / 为什么
  | 'strategy'   // 策略 / 推演 / 该怎么办 / 建议
  | 'general'    // 兜底综合

const INTENT_RULES: Array<[RegExp, IntelIntent]> = [
  [/周报|总结|复盘|汇总|报告|weekly|review\b/i, 'weekly'],
  [/异动|异常|暴涨|骤降|激增|为什么|怎么回事|原因|归因|突发/i, 'anomaly'],
  [/策略|推演|反制|应对|该怎么办|如何|建议|判断|预测|会不会|会不会降|要不要/i, 'strategy'],
  [/调价|降价|涨价|价格|促销|秒杀|coupon|优惠券|prime|限时|定价/i, 'price'],
  [/排名|bsr|掉量|起量|涨到|跌到|排名趋势|类目排/i, 'bsr'],
  [/差评|好评|评论|星级|评分|review|feedback/i, 'review'],
  [/变体|子asin|子链接|款式|颜色|尺码|新增变体/i, 'variation'],
  [/快照|改标题|改主图|改五点|a\+|视频|改listing|变更记录|改了/i, 'listing'],
  [/库存|断货|入仓|补货|缺货|库存估算|剩余/i, 'stock'],
]

function detectIntent(q: string): IntelIntent {
  for (const [re, t] of INTENT_RULES) if (re.test(q)) return t
  return 'general'
}

// ====== 工具函数 ======

/** 从提问里尽量抠出 ASIN（B0 开头 10 位）；抠不到返回 null */
function extractAsins(q: string): string[] | null {
  const m = q.match(/B0[A-Z0-9]{7,8}/gi)
  return m && m.length ? [...new Set(m.map(s => s.toUpperCase()))] : null
}

function priceDeltaPct(cur: number, daysAgo: number): number {
  if (!daysAgo) return 0
  return +(((cur - daysAgo) / daysAgo) * 100).toFixed(1)
}

// ====== 证据聚合 ======
interface AnalysisEvidence {
  asins: string[]            // 实际参与分析的 ASIN
  pool_total: number
  per_asin: any[]            // 每条 ASIN 的该维度浓缩指标（供证据卡渲染）
  intent: IntelIntent
}

/** 从池拉取参与分析的记录（提问显式 ASIN → selectedAsins → 全池前 6） */
function pickRecords(q: string, opts?: IntelOpts) {
  const pool = useMonitorPoolStore()
  const explicit = opts?.scopeAsins?.length ? opts.scopeAsins : extractAsins(q)
  let list = pool.records
  if (explicit) {
    list = list.filter(r => explicit.includes(r.asin))
  } else if (pool.selectedAsins.length) {
    list = list.filter(r => pool.selectedAsins.includes(r.asin))
  }
  // 仍无 → 全池；避免过多截断
  return list.slice(0, 6)
}

// ====== 主入口 ======
export interface IntelResult {
  reply: string
  evidence: AnalysisEvidence
}

/** 可选入参：供输入框上方 chip（周报/异动/策略）驱动，强制意图 + 指定范围 + 周期 */
export interface IntelOpts {
  /** 强制意图（chip 点按时不靠自然语言猜） */
  forceIntent?: IntelIntent
  /** 指定参与分析的 ASIN（看板带入的勾选集），优先级最高 */
  scopeAsins?: string[]
  /** 分析周期（天），仅用于文案标注；mock 数据为 30 天快照 */
  days?: number
}

/**
 * mock 推理：依据意图对不同维度做规则聚合，输出「解读 + 建议」+ 结构化证据。
 * @param question  用户自然语言提问（chip 场景可传语义化问题）
 * @param opts      可选：forceIntent / scopeAsins / days
 */
export function analyzeCompetitorIntel(question: string, opts?: IntelOpts): IntelResult {
  const pool = useMonitorPoolStore()
  const intent = opts?.forceIntent || detectIntent(question)
  const picked = pickRecords(question, opts)

  // —— 构造浓缩证据 ——
  const per_asin = picked.map(r => {
    const ph = r.price_history
    const p30 = ph[0]?.price ?? r.latest_price
    const p7 = ph[ph.length - 8]?.price ?? r.latest_price
    const cur = r.latest_price
    const neg30 = r.review_events.filter(e => e.negative).length
    const neg7 = r.review_events.slice(-7).filter(e => e.negative).length
    const add7 = r.review_events.slice(-7).reduce((s, e) => s + e.added, 0)
    const bsr30 = r.bsr_history[0]?.bsr ?? r.latest_bsr
    const changes30 = r.listing_changes
    const low = r.price_history.filter(p => p.coupon || p.is_prime_deal || p.deal_type).length
    return {
      asin: r.asin,
      brand: r.brand,
      title: r.title,
      group_ids: r.group_ids,
      rating: r.rating,
      review_count: r.review_count,
      stock_status: r.stock_status,
      est_monthly_sales: r.est_monthly_sales,
      latest_price: cur,
      price_change_7d: r.price_change_7d,
      price_change_30d: priceDeltaPct(cur, p30),
      price_drops_30d: r.price_history.reduce((n, p, i) => (i > 0 && p.price < r.price_history[i - 1].price ? n + 1 : n), 0),
      promo_days_30d: low,
      latest_bsr: r.latest_bsr,
      bsr_change_7d: r.bsr_change_7d,
      bsr_trend_30d: r.latest_bsr - bsr30, // 负=整体上升(更好)
      reviews_added_7d: add7,
      negative_7d: neg7,
      negative_30d: neg30,
      listing_changes: changes30.map(c => ({ field: c.field_name, changed_at: c.changed_at })),
      variation_count: r.variations.length,
    }
  })

  const evidence: AnalysisEvidence = {
    asins: per_asin.map(a => a.asin),
    pool_total: pool.totalCount,
    per_asin,
    intent,
  }

  const reply = buildReply(intent, per_asin, picked.length, pool.selectedAsins.length > 0, opts?.days || 30)
  return { reply, evidence }
}

// ====== 模板生成「解读 + 建议」 ======

function money(n: number) {
  return '$' + (Number.isFinite(n) ? n.toFixed(2) : '0.00')
}
function pct(n: number) {
  return (n > 0 ? '+' : '') + n + '%'
}

function buildReply(intent: IntelIntent, rows: any[], n: number, usedSelected: boolean, days = 30): string {
  const scope = rows.length
    ? `${usedSelected ? '你当前圈选的' : ''}${n} 个竞品`
    : '监控池'
  if (rows.length === 0) {
    return `监控池里暂无竞品。请先在「竞品监控」工作台添加 ASIN 并圈选，我才能基于真实数据帮你分析。`
  }

  // 通用头部（mock 历史为 30 天快照，周期用于文案标注）
  const periodLabel = days >= 90 ? '近 90 天' : days >= 30 ? '近 30 天' : days >= 14 ? '近 14 天' : '近 7 天'
  const head = `已基于 ${scope} ${periodLabel}监控数据（统一竞品池）完成分析。\n\n`

  switch (intent) {
    case 'price': {
      const sorted = [...rows].sort((a, b) => b.price_change_7d - a.price_change_7d)
      const dropper = rows.find(r => r.price_change_7d < -5)
      const riser = sorted[sorted.length - 1]
      const promo = rows.filter(r => r.promo_days_30d >= 3)
      let s = head + `**📉 调价/促销格局（30 天）**\n\n`
      rows.forEach(r => {
        s += `- **${r.brand}**(${r.asin}) 现价 ${money(r.latest_price)}，7 日 ${pct(r.price_change_7d)} / 30 日 ${pct(r.price_change_30d)}，30 天内 ${r.promo_days_30d} 天有促销、${r.price_drops_30d} 次降价\n`
      })
      s += `\n**一句话解读**：`
      if (dropper) s += `${dropper.brand} 近 7 日已降价 ${pct(dropper.price_change_7d)}，是当前最激进的降价者，大概率在冲 BSR 排名或清库存`
      else if (promo.length) s += `${promo.map(p => p.brand).join('、')} 促销频率偏高（30 天 ≥3 天），价格战风险在累积`
      else s += `各竞品价格基本稳定，暂无主动降价冲量的信号`
      s += `。\n\n**运营建议**：`
      if (dropper) s += `短期（1–2 周）不要正面跟价，优先核对对方是否处于秒杀窗口（LD/7DD 结束后常回价）；同时盯住其库存水位判断是清仓还是冲排名，决定你要不要跟进。`
      else s += `维持当前定价，把省下的利润投入广告抢占其松动期的流量。`
      return s
    }
    case 'bsr': {
      const riser = [...rows].filter(r => r.bsr_trend_30d < 0).sort((a, b) => a.bsr_trend_30d - b.bsr_trend_30d)[0] // 涨最多(负最多)
      const faller = [...rows].sort((a, b) => b.bsr_trend_30d - a.bsr_trend_30d)[0]
      let s = head + `**📈 BSR 类目排名趋势（30 天）**\n\n`
      rows.forEach(r => {
        const up = r.bsr_trend_30d < 0
        s += `- **${r.brand}**(${r.asin}) 现 BSR #${r.latest_bsr}，30 天${up ? '↑' : '↓'} ${Math.abs(r.bsr_trend_30d)} 位（7 日 ${r.bsr_change_7d >= 0 ? '↓' : '↑'} ${Math.abs(r.bsr_change_7d)}）\n`
      })
      s += `\n**一句话解读**：`
      if (riser) s += `${riser.brand} 30 天排名上升最多（BSR 回落 ${Math.abs(riser.bsr_trend_30d)} 位），正处于起量通道，需重点盯防其手法`
      else s += `本周期内各竞品排名整体平稳`
      if (faller && faller !== riser && faller.bsr_trend_30d > 100) s += `；而 ${faller.brand} 明显掉量（排名后移 ${faller.bsr_trend_30d} 位），可能断货或转化下滑`
      s += `。\n\n**运营建议**：` + (riser ? `优先反查 ${riser.brand} 是否同步做了调价/变体上新/改主图，若三管齐下说明其在系统化打法，你需要在广告或差异化上做对冲，而非硬拼价格。` : `维持现有排名维护节奏即可。`)
      return s
    }
    case 'review': {
      const neg = rows.filter(r => r.negative_7d > 0)
      const worst = [...rows].sort((a, b) => a.rating - b.rating)[0]
      let s = head + `**⭐ 评论 & 星级（30 天）**\n\n`
      rows.forEach(r => {
        s += `- **${r.brand}**(${r.asin}) 星级 ${r.rating.toFixed(1)}，近 7 日新增 ${r.reviews_added_7d} 条、差评 ${r.negative_7d} 条（30 天累计差评 ${r.negative_30d}）\n`
      })
      s += `\n**一句话解读**：`
      if (neg.length) s += `${neg.map(x => x.brand).join('、')} 近 7 天集中出现差评预警，可能是品质或物流问题集中爆发`
      else s += `近 7 天各竞品暂无差评预警`
      if (worst.rating < 4.0) s += `；其中 ${worst.brand} 整体星级仅 ${worst.rating.toFixed(1)}，差评已形成转化天花板`
      s += `。\n\n**运营建议**：` + (neg.length ? `趁对方差评窗口，在广告上加大对该 ASIN 词位的抢占，并用「品质稳定」卖点做差异化文案截流。` : `当前无系统性差评机会，保持正常节奏。`)
      return s
    }
    case 'variation': {
      let s = head + `**🧩 变体监控**\n\n`
      rows.forEach(r => {
        s += `- **${r.brand}**(${r.asin}) 当前 ${r.variation_count} 个变体\n`
      })
      s += `\n**一句话解读**：变体数量反映其覆盖款式的宽度；扩张 = 吃更多搜索词与流量入口，收缩 = 聚焦爆款。`
      s += `\n\n**运营建议**：建议在变体面板横向对比各竞品子 ASIN 价格/库存，若头部竞品变体数在一周内净增，说明其正用多子体抢占类目流量，你可评估自身是否缺对应款式。`
      return s
    }
    case 'listing': {
      const active = rows.filter(r => r.listing_changes.length)
      let s = head + `**🖼️ Listing 快照变更（30 天）**\n\n`
      if (!active.length) { s += `本周期内各竞品均无重大 Listing 改动记录。`; return s }
      active.forEach(r => {
        s += `- **${r.brand}**(${r.asin}) 改动 ${r.listing_changes.length} 处：${r.listing_changes.map((c: any) => c.field).join('、')}\n`
      })
      s += `\n**一句话解读**：频繁改标题/五点/主图通常是为贴合新搜索词或调整卖点主攻方向，是抢流量的信号。`
      s += `\n\n**运营建议**：到 Listing 快照面板查看具体 diff 与时间点，结合其当天的 BSR/销量判断改动是有效还是试错，避免盲目照抄。`
      return s
    }
    case 'stock': {
      const risk = rows.filter(r => r.stock_status === 'low_stock' || r.stock_status === 'out_of_stock')
      let s = head + `**📦 库存 / 断货监测**\n\n`
      rows.forEach(r => {
        const label = r.stock_status === 'in_stock' ? '充足' : r.stock_status === 'low_stock' ? '低库存' : '已断货'
        const est = r.estimated_units_remaining
        s += `- **${r.brand}**(${r.asin}) ${label}${est != null ? `（估余 ${est} 件）` : ''}\n`
      })
      s += `\n**一句话解读**：`
      if (risk.length) s += `${risk.map(x => x.brand).join('、')} 存在库存告急/断货，短期会出现排名回落与流量缺口`
      else s += `各竞品库存均健康`
      s += `。\n\n**运营建议**：` + (risk.length ? `这是抢占对方市场份额的窗口期，可适当加大广告预算并放出 Coupon，在对方断货期承接其流失的搜索流量；同时给对方断货时间点做记录，推算其补货/复购节奏。` : `暂无库存机会，维持节奏。`)
      return s
    }
    case 'anomaly': {
      // 跨维度找最「异常」的一个：降价多 / BSR 大涨 / 差评 / 快照 都算
      const events: string[] = []
      rows.forEach(r => {
        if (r.price_change_7d < -6) events.push(`**${r.brand}**(${r.asin}) 7 日降价 ${pct(r.price_change_7d)}（可能秒杀或价格战）`)
        if (r.bsr_change_7d > 200) events.push(`**${r.brand}**(${r.asin}) BSR 7 日骤降 ${r.bsr_change_7d} 位（掉量/断货风险）`)
        if (r.bsr_change_7d < -200) events.push(`**${r.brand}**(${r.asin}) BSR 7 日上升 ${-r.bsr_change_7d} 位（起量异动）`)
        if (r.negative_7d > 0) events.push(`**${r.brand}**(${r.asin}) 近 7 日差评 ${r.negative_7d} 条预警`)
        if (r.listing_changes.length) events.push(`**${r.brand}**(${r.asin}) 修改了 Listing（${r.listing_changes.map((c: any) => c.field).join('、')}）`)
        if (r.stock_status === 'out_of_stock') events.push(`**${r.brand}**(${r.asin}) 已断货`)
      })
      if (!events.length) return head + `近 7 天 ${scope} 未检测到明显异常：价格、BSR、评论、变体、Listing、库存均处正常波动区间。一切平稳，继续观察即可。`
      let s = head + `**🚨 检测到的异动事件**\n\n` + events.map(e => `- ${e}`).join('\n')
      s += `\n\n**一句话业务解读**：`
      s += `上述异动多为「主动进攻」（降价+改Listing+变体上新=系统化抢量）或「被动暴露」（断货/差评=守不住阵地）两类。若同一竞品同时命中多条，基本可判定其在做一次有组织的推广动作，而非偶发。`
      s += `\n\n**建议**：请到对应追踪面板核对事件时间线，判断是秒杀、改图还是上新引发的，再决定是否在广告/价格上做出反制。`
      return s
    }
    case 'weekly':
    case 'general': {
      // 周报 = 综合总结
      const neg = rows.filter(r => r.negative_7d > 0)
      const dropper = rows.filter(r => r.price_change_7d < -5)
      const riser = [...rows].filter(r => r.bsr_trend_30d < 0).sort((a, b) => a.bsr_trend_30d - b.bsr_trend_30d)[0]
      const lisAct = rows.filter(r => r.listing_changes.length)
      const stockRisk = rows.filter(r => r.stock_status !== 'in_stock')
      let s = head + `**📋 竞品动态周报（${scope}）**\n\n`
      s += `- **调价**：${dropper.length ? dropper.map(d => `${d.brand}${pct(d.price_change_7d)}`).join('、') + ' 明显降价' : '基本稳定'}\n`
      s += `- **BSR**：${riser ? `${riser.brand} 起量（排名上升）` : '整体平稳'}\n`
      s += `- **评论**：${neg.length ? `${neg.map(x => x.brand).join('、')} 现差评预警` : '无差评预警'}\n`
      s += `- **Listing**：${lisAct.length ? `${lisAct.map((x: any) => x.brand).join('、')} 有改动（${[...new Set(lisAct.flatMap((x: any) => x.listing_changes.map((c: any) => c.field)))].join('、')}）` : '无改动'}\n`
      s += `- **库存**：${stockRisk.length ? `${stockRisk.map(x => x.brand).join('、')} 库存告急/断货` : '健康'}\n`
      s += `\n**一句话总结**：` + (dropper.length || riser || neg.length || stockRisk.length
        ? `本周期竞品动作偏活跃，存在降价冲量、差评窗口与库存缺口等多重信号，建议优先处理库存/差评类确定性机会，再决定是否跟价。`
        : `本周期竞品整体平稳，暂无可操作的重大机会，建议维持防守并留意下周变体上新。`)
      s += `\n\n> 💡 你可以继续追问，例如：“分别讲讲这几家 30 天的调价节点”“谁最快可能断货”。`
      return s
    }
    case 'strategy':
    default: {
      let s = head + `**🧠 策略推演**\n\n`
      s += `围绕 ${scope} 的综合攻防建议：\n`
      s += `1. **差异化**：避开与头部（${rows[0]?.brand}）在纯价格上硬拼，从功能/场景卖点或赠品组合上拉开差距。\n`
      s += `2. **时机**：盯住${rows.filter(r => r.stock_status !== 'in_stock').map(x => x.brand).join('、') || '各竞品'}的库存与促销窗口，在其空窗期抢广告位。\n`
      s += `3. **证据驱动**：任何结论都建议我先调对应时序数据交叉验证，避免单日波动误导判断。`
      return s
    }
  }
}

// ==========================================================================
// 数据源 B：选品库候选（静态快照，无历史时序）→ 新品市场/可行性评估
// 说明：候选是"尚未上架、正在评估"的新品，无价格/BSR/评论走势，
//       因此不套用监控周报/异动那套时序分析，而是基于静态快照给可行性研判。
// ==========================================================================

/** 把选品库候选归一化为可展示的静态评估条目 */
interface CandidateAssessRow {
  asin: string
  brand: string
  title: string
  price: number
  rating: number
  review_count: number
  est_monthly_sales: number
  blue_ocean_score: number
  roi_estimated: number
  bsr?: number | null
}

function scoreBand(n: number): { label: string; color: string } {
  if (n >= 70) return { label: '优质蓝海', color: '🟢' }
  if (n >= 40) return { label: '中等机会', color: '🟡' }
  return { label: '竞争偏高', color: '🔴' }
}

/**
 * 对一批"选品库候选/筛选结果"做新品评估（数据源='candidate'）。
 * 评估对象为「选品分析师」对话框上方 chip 触发的 AI 推理，根据 intent 走不同分析维度。
 * 五个意图分别覆盖从候选静态快照出发的不同关注点：市场可行性 / 上架建议 / 痛点分析 / 选品避坑 / 竞品对比。
 *
 * @param cands 候选快照（已含筛选后的列表）
 * @param intent 评估意图：
 *   - 'feasibility' 市场可行性（默认）：综合蓝海分/ROI/竞争压力给优先级排序
 *   - 'launch'      上架建议：价格定位/Listing 准备/合规/物流建议
 *   - 'pain'        痛点分析：基于当前竞品/评论数推断用户痛点与改进机会
 *   - 'pitfall'     选品避坑：专利/认证/合规/品牌侵权/红海品类风险扫描
 *   - 'compare'     竞品对比：列出已挂在该候选身上的对标竞品 ASIN
 */
export function analyzeCandidateSelection(
  cands: any[],
  intent: 'feasibility' | 'launch' | 'pain' | 'pitfall' | 'compare' = 'feasibility',
): string {
  if (!cands || cands.length === 0) {
    return `当前没有可评估的候选。请先在顶部点击 **【载入选品】** 选定一个候选后重试。`
  }

  const rows: CandidateAssessRow[] = cands.map(c => ({
    asin: c.asin,
    brand: c.brand || '—',
    title: c.title || c.asin,
    price: c.price || 0,
    rating: c.rating || 0,
    review_count: c.review_count || 0,
    est_monthly_sales: c.estimated_monthly_sales || 0,
    blue_ocean_score: c.blue_ocean_score || 0,
    roi_estimated: c.roi_estimated || 0,
    bsr: c.bsr ?? null,
  }))

  const avgScore = rows.reduce((s, r) => s + r.blue_ocean_score, 0) / rows.length
  const best = [...rows].sort((a, b) => b.blue_ocean_score - a.blue_ocean_score)[0]
  const highRoi = rows.filter(r => r.roi_estimated >= 100)
  const goodRating = rows.filter(r => r.rating >= 4.2)
  const heavyCompete = rows.filter(r => r.review_count >= 1000)
  const candidate = cands[0] // 主评估对象（多数场景是单选）
  const competitorAsins: string[] = Array.isArray(candidate?.competitor_asins) ? candidate.competitor_asins : []
  const keywords: string[] = Array.isArray(candidate?.keywords) ? candidate.keywords : []
  const category = candidate?.category || '—'

  const disclaimer = `> ⚠️ 候选为未上架新品，无历史时序；以下基于价格/评分/评论/销量/蓝海分做静态研判，不作为长期趋势依据。\n\n`

  // ===== 意图 1：市场可行性（综合）=====
  if (intent === 'feasibility') {
    let s = `**🛰️ 选品库候选 · 市场可行性评估（静态快照，共 ${rows.length} 条）**\n\n`
    s += disclaimer
    s += `**📋 逐条画像**\n`
    rows.forEach(r => {
      const band = scoreBand(r.blue_ocean_score)
      s += `- **${r.brand}** (${r.asin}) · ${band.color}${band.label}（蓝海 ${r.blue_ocean_score} 分）· 售价 ${money(r.price)} · 评分 ★${Number(r.rating).toFixed(1)} · 评论 ${r.review_count.toLocaleString()} · 估月销 ${r.est_monthly_sales.toLocaleString()}${r.roi_estimated ? ` · ROI ${r.roi_estimated}%` : ''}\n`
    })
    s += `\n**🧭 综合研判**\n`
    s += `1. **最优切入**：${best ? `「${best.brand} ${best.title.slice(0, 22)}」蓝海分最高（${best.blue_ocean_score}），${best.roi_estimated >= 100 ? `且 ROI ${best.roi_estimated}%` : ''}，建议优先做深度成本/侵权排查后小批量试款` : '无可评估项'}。\n`
    s += `2. **利润信号**：${highRoi.length ? `${highRoi.map(r => r.brand).join('、')} ROI 达标（≥100%），有开款价值` : '暂无明显高 ROI 项，需复核成本结构'}。\n`
    s += `3. **竞争压力**：平均蓝海分 ${Math.round(avgScore)}，${scoreBand(avgScore).color}${scoreBand(avgScore).label}；建议避开评论壁垒高（头部>5000 条）的类目。\n`
    s += `4. **上架前置**：评分≥4.2 的成熟标（${goodRating.length ? goodRating.map(r => r.brand).join('、') : '暂无'}）更利于新品期转化，可优先借势。`
    s += `\n\n**💡 下一步建议**`
    s += `\n选中你倾向的 1–2 条 → 点「**加入监控**」开启该 SKU 竞品跟踪（待评估候选），或用「评审通过」迁入产品库做上架准备。`
    return s
  }

  // ===== 意图 2：上架建议（运营前置）=====
  if (intent === 'launch') {
    const cur = best
    const curBrand = cur ? `${cur.brand} ${cur.title.slice(0, 18)}` : '—'
    let s = `**🚀 选品库候选 · 上架前置建议（共 ${rows.length} 条）**\n\n`
    s += disclaimer
    s += `**📋 目标对象画像**\n`
    s += `- **${curBrand}**（${cur?.asin}）· 蓝海 ${cur?.blue_ocean_score} · 售价 ${money(cur?.price ?? 0)} · 估月销 ${cur?.est_monthly_sales.toLocaleString()} · ROI ${cur?.roi_estimated}%\n\n`
    s += `**🛠️ 上架清单**\n`
    s += `1. **价格定位**：建议以 ${money((cur?.price ?? 0) * 0.95)} 作为首发价（低于参考 5% 形成新客吸引力），1 个月后视转化回升到 ${money(cur?.price ?? 0)}；预留 10% 利润空间做 Coupon/Deal。\n`
    s += `2. **Listing 准备**：标题前置 2-3 个高搜索量关键词（${keywords.slice(0, 3).join('、') || '待补'}），五点描述按「场景-痛点-方案-对比-保障」结构写，主图必须白底 + 卖点文案 + 尺寸参照。\n`
    s += `3. **合规与认证**：类目「${category}」需提前确认 ① FCC/PSE 等强电认证 ② 平台类目准入资质 ③ 品牌备案（自有商标 / 授权链），可走服务商加急 7-10 工作日。\n`
    s += `4. **物流与库存**：FBA 头程建议首批 500-800 件分两批发海运/快递对冲；预留 30% 缓冲库存以应对上线期 2 周内的退换与 Listing 改图。\n`
    s += `5. **节奏与广告**：上架首周 0 评无星级，建议开 VINE + 站外小额 Deal 同步冲前 5 条评论；广告 30% 预算放精准长尾词（CTR 高的差异化词），70% 走广泛匹配拓流。\n\n`
    s += `**⚠️ 风险提示**：${heavyCompete.length ? `${heavyCompete.map(r => r.brand).join('、')} 头部评论量 ${heavyCompete[0].review_count.toLocaleString()}+，需差异化卖点破壁；` : `当前评论量级在可承受区间，专注转化率优化即可；`}同期 1-2 个月内不建议同店铺再开同款变体，避免内部竞争。`
    return s
  }

  // ===== 意图 3：痛点分析（基于当前评论量/评分解构用户痛点）=====
  if (intent === 'pain') {
    const cur = best
    let s = `**🔍 选品库候选 · 潜在用户痛点分析（基于静态字段推断，共 ${rows.length} 条）**\n\n`
    s += disclaimer
    s += `**📋 目标对象画像**\n`
    s += `- **${cur?.brand} ${cur?.title.slice(0, 18)}**（${cur?.asin}）· 售价 ${money(cur?.price ?? 0)} · 评分 ★${Number(cur?.rating).toFixed(1)} · 评论 ${cur?.review_count.toLocaleString()}\n\n`
    s += `**🩹 推断的常见痛点（按可能性排序）**\n`
    s += `1. **品质参差**：售价 ${money(cur?.price ?? 0)} 区间是用户对「耐用度」最敏感的段位，差评关键词多集中在「材料薄/做工粗/寿命短」。\n`
    s += `2. **使用门槛**：新品类用户最常卡在「首次上手不会用」，建议在 Listing 视频与 A+ 内容里加 30 秒实操演示 + 场景图。\n`
    s += `3. **售后保障缺失**：同类目头部 ${heavyCompete.length ? heavyCompete[0].brand : '竞品'} 评论中 2-3 星差评 30% 以上提到「售后回复慢/不解决问题」，可做差异化承诺（30 天无理由换新）。\n`
    s += `4. **规格与预期不符**：颜色/尺寸/容量差 1-2cm 或少 5% 容量是 Top 差评来源，Listing 主图加「尺寸参照物」与「容量实测」视频能显著降低退货率。\n\n`
    s += `**💡 改进机会**\n`
    s += `- 主图与 A+ 内容把「解决具体痛点」前置（不只讲卖点）\n`
    s += `- 包装内附 1 张「30 天无忧」卡片，引导好评同时降低客服压力\n`
    s += `- 五点描述第 1 条写「针对 X 类用户的 Y 痛点 → 我们怎么解决」，让搜索词与购买动机对齐`
    return s
  }

  // ===== 意图 4：选品避坑（合规/专利/红海/品牌）=====
  if (intent === 'pitfall') {
    const cur = best
    let s = `**⚠️ 选品库候选 · 多维风险扫描（专利/认证/合规/红海，共 ${rows.length} 条）**\n\n`
    s += disclaimer
    s += `**📋 目标对象画像**\n`
    s += `- **${cur?.brand} ${cur?.title.slice(0, 18)}**（${cur?.asin}）· 类目「${category}」· 蓝海 ${cur?.blue_ocean_score} · 售价 ${money(cur?.price ?? 0)} · ROI ${cur?.roi_estimated}%\n\n`
    s += `**🛡️ 风险扫描结果**\n`
    s += `1. **品牌侵权风险**：${cur?.brand && cur.brand !== '—' ? `候选关联品牌「${cur.brand}」需先确认是否自有商标 / 合法授权；非授权则需 OEM 重贴牌或更换供应商品牌链路。` : `无关联品牌，侵权风险相对可控，但需确保供应商不挂他人注册商标。`}\n`
    s += `2. **外观专利风险**：类目「${category}」是 Amazon Design Patent 高发区，建议查 USPTO / EUIPO 近 12 个月同类目专利，必要时做一次专利律师 FTO 报告（3000-5000 元）。\n`
    s += `3. **认证合规**：电子/电类 → FCC/CE/PSE 必做；母婴/食品接触类 → CPC/FDALFGB；玩具类 → ASTM F963/CPSIA；化妆品/护肤类 → FDA 注册 + 产品成分备案。\n`
    s += `4. **平台政策**：Amazon 近 90 天对「${category}」类目有 3 起下架记录（占该类目 8%），主因是 ① 主图含禁用词 ② 变体违规合并 ③ 缺少必要合规文件 —— 上架前自查这 3 项。\n`
    s += `5. **红海预警**：${heavyCompete.length ? `头部竞品评论量 ${heavyCompete[0].review_count.toLocaleString()}+，新店进入前 3 个月需投入 ≥${money(8000)} 广告 + 站外流量；` : `当前类目评论量级中等，差异化定位即可破局；`}蓝海分 ${cur?.blue_ocean_score} < 40 时建议直接放弃，避免无效投入。\n\n`
    s += `**💡 行动建议**\n`
    s += `- 上架前完成「3 查」：① 商标查询 ② 外观专利查询 ③ 平台合规自查表\n`
    s += `- 与供应商签订「无侵权」条款与赔偿协议，把风险前置转移\n`
    s += `- 准备 2 套备选 SKU，避免单一供应商断货/侵权被下架导致 Listing 直接报废`
    return s
  }

  // ===== 意图 5：竞品对比（基于已挂的对标竞品 ASIN）=====
  if (intent === 'compare') {
    const cur = best
    let s = `**⚔️ 选品库候选 · 对标竞品对比（共 ${rows.length} 条候选）**\n\n`
    s += disclaimer
    s += `**📋 目标对象画像**\n`
    s += `- **${cur?.brand} ${cur?.title.slice(0, 18)}**（${cur?.asin}）· 售价 ${money(cur?.price ?? 0)} · 评分 ★${Number(cur?.rating).toFixed(1)} · 蓝海 ${cur?.blue_ocean_score}\n\n`
    s += `**🆚 已挂对标竞品（${competitorAsins.length} 个）**\n`
    if (competitorAsins.length) {
      s += competitorAsins.slice(0, 5).map((a, i) => `- **#${i + 1}** ${a}`).join('\n') + '\n'
      s += competitorAsins.length > 5 ? `… 共 ${competitorAsins.length} 个对标 ASIN，前 5 个可在「维护对标竞品池」中查看与启停\n\n` : '\n'
    } else {
      s += `该候选尚未挂任何对标竞品。\n\n`
    }
    s += `**🧭 对比分析**\n`
    s += `1. **价格定位**：候选售价 ${money(cur?.price ?? 0)}，类目头部多在 ${money((cur?.price ?? 0) * 0.7)}-${money((cur?.price ?? 0) * 1.3)} 区间；${competitorAsins.length >= 3 ? `已挂 ${competitorAsins.length} 个对标竞品，能形成稳定的参照系` : `对标竞品不足 3 个，建议补充到 3-5 个形成完整对比矩阵`}。\n`
    s += `2. **差异化空间**：当前评分 ${Number(cur?.rating).toFixed(1)}，头部竞品多在 4.2-4.5，${cur && cur.rating < 4.2 ? `候选评分偏低，差异化可从「品质提升 + 售后保障」切入` : `评分与头部持平，差异化需在「功能/场景」而非「基础品质」上做文章`}。\n`
    s += `3. **建议**：点上方 chip「**维护对标竞品池**」（${competitorAsins.length ? `已挂 ${competitorAsins.length} 个，启用 ${competitorAsins.length} 个` : `尚无对标竞品`}）→ 启用 / 补充 / 调整后，再点「**开始对比分析**」拉取多维对比报告。`
    return s
  }

  // 兜底
  return `**🛰️ 选品库候选 · 综合评估（共 ${rows.length} 条）**\n\n` + disclaimer
}

// 说明：真实 LLM 推理接口（调用后端 qwen/deepseek）留 TODO，见 api/ 层。
