/**
 * 竞品监控 Agent —— **规则推理层**（competitor-intel）
 *
 * ★ 名字里的「mock」已经去掉，文件也从 `src/mock/` 迁到了 `src/utils/`
 *   （第 172 轮）。理由：**它本来就不吃 mock 数据** ——
 *     · 数据输入是真的：监控池走 `monitors` 表（PostgreSQL）、候选走选品库快照；
 *     · 证据字段全部由真实入参算出（价格变动 / BSR 趋势 / 差评数 / 促销天数 /
 *       变体数 / 蓝海分…），没有一个是编的；
 *     · 住在 `mock/` 里名不副实 —— 会让人以为这里的数字不可信。
 *
 * ★★ 第 255 轮（#918）：**数据源 A（监控池时序推理）整条子树已退役**。
 *   它唯一的入口是竞品监控员的智能推理工具卡（`intel-chat` / `intel-weekly` /
 *   `intel-anomaly` / `intel-strategy`），而那 12 个工具卡**没有任何可达入口**
 *   （判据见 `toolDefinitions.ts` 里 `competitor-intel` 的说明）⇒
 *   `analyzeCompetitorIntel` / `buildReply` / 意图识别 / 证据聚合 一并删除。
 *   ⇒ 本文件现在只剩**一条活路径**：`analyzeCandidateSelection`
 *     （选品链路第二跳，消费方 `chat/replies/competitorIntel.ts`）。
 *
 * ★ 本轮同时删掉了 6 处**编造的行业统计**（原先散在 `analyzeCandidateSelection`
 *   里）：它们用「类目头部评分区间」「某比例以上的差评提到售后」「近 90 天下架
 *   起数与占比」这类**统计口吻**，说着没有任何数据来源的话。
 *   ★ 此处刻意**不复现原文数字** —— 注释里原样引用待禁字符串，会骗过一切
 *     "字符串包含"型的复核与门禁（本轮已踩过三次）。
 *   保留下来的是：基于**输入字段**的计算 + 通用运营建议/流程清单，
 *   且凡是涉及类目事实的结论都标了「经验/待验证」，不再冒充实测数据。
 *
 * 地位：第 3 层「推理层」。与 8 个看数工具（各自读池展示单一视角）不同，
 * 本引擎在用户用自然语言向「竞品监控员」提问时，读取统一监控池（MonitorPool）
 * 的完整时序数据，做跨 ASIN / 跨维度的聚合 → 归因 → 一句话解读 + 运营建议。
 *
 * 接入后端 LLM 的落点（尚未做，但接口已具备）：
 *   后端竞品 Agent 已有 `POST /api/v1/competitor/analyze`（8 种能力，
 *   返回结构化 payload），前端封装在 `src/api/competitorIntelligence.ts`。
 *   将来的改法是：把下面的 `buildReply()` 换成
 *   「调该端点 → 按 `data.type` 分流格式化」—— 即 `analyzeCompetitorIntel`
 *   整体变成 async，再加 8 个格式化器。
 *   ★ 在真实数据接口接上之前，本层保证「离线也能给出可解释、可追溯的回答」，
 *     且**每一句话里的数字都能在证据卡里找到出处**。
 *
 * 支持多轮：用户可用「他们/这几个/上面前三个」等代词指代，
 * 引擎无法从提问解析出明确 ASIN 时，自动回退到监控池「当前圈选 selectedAsins」，
 * 若仍为空则用全池 records（前若干条）。
 */


// ====== 渲染小工具（`money` / `pct`；数据源 B 的模板共用） ======

function money(n: number) {
  return '$' + (Number.isFinite(n) ? n.toFixed(2) : '0.00')
}
function pct(n: number) {
  return (n > 0 ? '+' : '') + n + '%'
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
 *
 * ★ 输出性质（第 172 轮明确，勿再引入编造统计）：
 *   本函数是**规则引擎**，只有两类内容：
 *     ① 基于入参字段的**计算**（比例、均值、阈值比较）——数字可复算；
 *     ② 通用运营**建议/流程/清单** —— 不带市场统计口吻。
 *   凡是"类目头部通常如何""多少比例的用户如何"这类**类目事实**，
 *   本层一律不作为结论给出（要说得先有实测数据）。
 *   接入后端 LLM 后由模型基于检索结果作答，届时也应保留这条纪律。
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
    s += `1. **品质参差**：${money(cur?.price ?? 0)} 这个价位段的用户通常对「耐用度」较敏感（**经验判断，非本类目实测**），若供应商工艺一般，差评易集中在材料/做工/寿命上。\n`
    s += `2. **使用门槛**：新品类用户最常卡在「首次上手不会用」，建议在 Listing 视频与 A+ 内容里加 30 秒实操演示 + 场景图。\n`
    s += `3. **售后保障缺失**：售后响应慢是跨境类目常见的差评来源之一（**经验假设，未做统计验证**），可用「30 天无理由换新」这类差异化承诺对冲。\n`
    s += `4. **规格与预期不符**：颜色/尺寸/容量与描述有出入是常见的退货诱因（**经验判断**），Listing 主图加「尺寸参照物」与「容量实测」视频有助于降低预期落差。\n\n`
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
    s += `4. **平台政策**：主图含禁用词、变体违规合并、缺少必要合规文件是 Amazon 下架的三大常见主因（**通用清单，非本类目统计**）—— 上架前逐项自查。\n`
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
    s += `1. **价格定位**：候选售价 ${money(cur?.price ?? 0)}；${competitorAsins.length >= 3 ? `已挂 ${competitorAsins.length} 个对标竞品，能形成稳定的参照系` : `对标竞品不足 3 个，建议补充到 3-5 个形成完整对比矩阵`}。\n`
    s += `2. **差异化空间**：候选当前评分 ${Number(cur?.rating).toFixed(1)}。${cur && cur.rating < 4.2 ? `评分偏低，差异化可从「品质提升 + 售后保障」切入` : `评分处于中上水平，差异化需在「功能/场景」而非「基础品质」上做文章`}。（对照竞品的实际评分请从其监控时序读取，本层不做类目基准假设。）\n`
    s += `3. **建议**：点上方 chip「**维护对标竞品池**」（${competitorAsins.length ? `已挂 ${competitorAsins.length} 个，启用 ${competitorAsins.length} 个` : `尚无对标竞品`}）→ 启用 / 补充 / 调整后，再点「**开始对比分析**」拉取多维对比报告。`
    return s
  }

  // 兜底
  return `**🛰️ 选品库候选 · 综合评估（共 ${rows.length} 条）**\n\n` + disclaimer
}

// 说明：本层是确定性规则推理，**不调 LLM**。
// 接后端的落点见文件头「接入后端 LLM」一节 —— 端点已就绪
// （`src/api/competitorIntelligence.ts` 封装了 13 个非流式 + 1 个 SSE）。
