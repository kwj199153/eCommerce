/**
 * 对话编排层 · 工具结果摘要（第 169 轮 #664）
 *
 * 把工具的结构化出参翻译成一句人话，追加在结果卡上方。
 *
 * ★ 为什么值得单独一个文件（329 行，是本次拆出的最大单块）：
 *   它是一张**纯函数映射表** —— 入参 `(toolId, result)`、出参字符串、无副作用、无 store。
 *   单独成文件后可以直接对「真实后端出参」写用例，不必先把整个编排器跑起来。
 *
 * ★ 第 169 轮只做搬运，**不动任何一行取数口径**。已知的历史疙瘩（登记不改）：
 *   · `order-track` 的 fail-closed 分支已修（`order` 为 null 时不再解引用）。
 *   · `ticket-create` 那条已随工具卡退役（第 284 轮）一并删除 —— 它的旧实现
 *     直接解引用 `result.ticket`，创建失败时会抛（当时靠调用方的 try/catch 兜住）。
 */
import { orderSummaryLines } from '@/utils/orderTracking'

// 添加结果摘要到对话区
export function buildResultSummary(toolId: string, result: any): string {
  let content = ''
  switch (toolId) {
    case 'blue-ocean':
      content = `✅ **蓝海挖掘完成** - 发现 ${result.products?.length || 0} 个候选商品\n\n` +
        `- 优质蓝海（≥70分）：${result.summary?.high_potential || 0} 个\n` +
        `- 一般潜力（40-69分）：${result.summary?.medium_potential || 0} 个\n` +
        `- 高竞争（<40分）：${result.summary?.high_competition || 0} 个\n\n` +
        `详细结果已展示在上方表格中，可在此继续提问或调整参数重新分析。`
      break
    case 'pain-points':
      content = `🔍 **痛点分析完成** - 发现 ${result.pain_points?.length || 0} 个核心痛点\n\n` +
        `- 分析评论：${result.total_reviews_analyzed || 0} 条（差评 ${result.negative_review_count || 0} 条）\n` +
        `- 市场空白评分：${result.market_gap_score || 0}/100\n\n` +
        `详细报告已展示在上方。`
      break
    case 'competitor':
      content = `⚔️ **竞品对比完成** - 对比 ${result.competitors?.length || 0} 个竞品\n\n` +
        `- 价格区间：$${result.price_range?.min || 0} - $${result.price_range?.max || 0}\n` +
        `- 平均评分：${result.avg_rating?.toFixed(1) || '-'} ⭐\n\n` +
        `${result.recommendation || ''}`
      break
    case 'profit-calc':
      content = `💰 **利润测算完成**\n\n` +
        `- 售价：$${result.calculation?.selling_price}\n` +
        `- 总成本：$${result.calculation?.total_cost}\n` +
        `- 净利润：$${result.calculation?.net_profit}\n` +
        `- ROI：${result.calculation?.roi}%\n\n` +
        `费用明细已展示在上方。`
      break
    case 'bid-suggest':
      content = `💡 **出价建议完成** — 策略：${({ aggressive: '激进', balanced: '平衡', conservative: '保守' } as Record<string, string>)[result.strategy_type] || '平衡'}\n\n` +
        `- 分析关键词：${result.total_keywords || 0} 个\n` +
        `- 预计预算变动：$${result.budget_impact > 0 ? '+' : ''}${result.budget_impact}\n` +
        `- 预期 ACoS 变化：${result.expected_acos_change > 0 ? '+' : ''}${result.expected_acos_change.toFixed(1)}%\n\n` +
        `调价详情已展示在上方。`
      break
    case 'order-track':
      // ★ 第 292 轮：字段清单收归 `utils/orderTracking.ts` —— 与工具卡
      //   （`OrderTrackResult.vue`）、对话正文（`replies/customerService.ts`）
      //   **同一份真源**。此前这里又硬编码了一份 bullet，三份清单靠人肉同步。
      content = orderSummaryLines(result).join('\n')
      break
    // ===== Listing 优化师 =====
    case 'keyword-miner':
      content = `🔑 **关键词挖掘完成** — 基于 **${result.seed_keywords?.join('、') || '-'}** 种子词\n\n` +
        `- 挖掘候选词：**${result.total_found || 0}** 个\n` +
        `- 🎯 高相关低竞争：${result.keywords?.filter((k: any) => k.competition === 'low' && k.relevance >= 85).length || 0} 个\n` +
        `- 📊 推荐立即投放：${result.keywords?.filter((k: any) => k.relevance >= 90).length || 0} 个\n\n` +
        `完整关键词列表和搜索量数据已展示在上方。`
      break
    case 'title-gen':
      if (result.is_simplified) {
        content = `📝 **短标题生成完成** — 为「**${result.product_name || '-'}**」生成 **${result.short_titles?.length || 0}** 个短标题方案\n\n` +
          `- 🥇 最佳方案：${result.short_titles?.[0]?.title || '-'}（${result.short_titles?.[0]?.char_count || 0} 字符）\n` +
          `- 商品详情章节：${result.detail_desc?.sections?.length || 0} 个\n\n` +
          `优化建议已展示在上方，可直接复制使用。`
      } else {
        content = `📝 **标题生成完成** — 为「**${result.product_name || '-'}**」生成 **${result.titles?.length || 0}** 个标题方案\n\n` +
          `- 🥇 最佳方案评分：${result.titles?.[0]?.score || 0} 分（SEO ${result.titles?.[0]?.seo_score || 0}）\n` +
          `- 字符范围：${Math.min(...(result.titles?.map((t: any) => t.char_count) || [0]))}-${Math.max(...(result.titles?.map((t: any) => t.char_count) || [0]))} 字符\n\n` +
          `优化建议已展示在上方，可直接复制使用。`
      }
      break
    case 'bullet-gen':
      content = `✨ **五点描述生成完成** — 共 **${result.bullets?.length || 0}** 条卖点\n\n` +
        `- 总字符数：${result.bullets?.reduce((s: number, b: any) => s + (b.char_count || 0), 0) || 0}\n` +
        `- 平均每条：${Math.round((result.bullets?.reduce((s: number, b: any) => s + (b.char_count || 0), 0) || 0) / (result.bullets?.length || 1))} 字符\n` +
        `- 格式规范：全大写括号关键词开头 ✅\n\n` +
        `每条 Bullet 已按 Amazon 最佳实践格式化。`
      break
    case 'desc-gen':
      content = `📄 **A+ 描述生成完成** — 「**${result.product_name || '-'}**」\n\n` +
        `- 包含模块：${result.description?.sections?.length || 0} 个章节\n` +
        `- 标题：${result.description?.title?.slice(0, 40) || '-'}...\n` +
        `- A+ 优化建议：${result.aplus_tips?.length || 0} 条\n\n` +
        `富文本描述内容已展示在上方，支持复制到后台。`
      break
    case 'seo-audit':
      content = `📊 **SEO 诊断完成** — 综合评分 **${result.grade}**（${result.overall_score || 0}/100）\n\n` +
        `- 🟢 优秀项：${result.categories?.filter((c: any) => c.status === 'good' || c.status === 'excellent').length || 0}\n` +
        `- 🟡 需改进：${result.categories?.filter((c: any) => c.status === 'warning').length || 0}\n` +
        `- 🔴 急需处理：${result.categories?.filter((c: any) => c.status === 'poor').length || 0}\n\n` +
        `${result.top_recommendations?.[0] || ''}`
      break
    case 'ab-test':
      content = `🧪 **A/B 测试方案生成完成** — 测试 ID：**${result.test_id}**\n\n` +
        `- 变体数量：${result.variants?.length || 0} 个\n` +
        `- 测试周期：${result.test_config?.duration_days || 14} 天\n` +
        `- 流量分配：${Object.entries(result.test_config?.traffic_split || {}).map(([k, v]) => `${k}=${v}%`).join(' / ')}\n` +
        `- 预计完成：${result.test_config?.estimated_completion || '-'}\n\n` +
        `假设：${result.hypothesis || '-'}`
      break
    // ===== 选品分析师 — 风险评估报告 =====
    case 'pitfalls_report':
      const rpt = result
      const sm = rpt.summary
      content = `## ${rpt.report_title}\n\n` +
        `> 🏪 目标平台：**${rpt.platform}** | 生成时间：${rpt.generated_at}\n\n` +
        `### 📋 基础产品信息\n\n` +
        `- **产品名称**：${rpt.product_info.name}\n` +
        `- **ASIN**：${rpt.product_info.asin}\n` +
        `- **核心关键词**：${(rpt.product_info.keywords || []).join(' / ') || '-'}\n` +
        `- **参考竞品**：${(rpt.product_info.competitor_asins || []).join('、') || '-'}\n\n` +
        `### ⚠️ 风险汇总总览\n\n` +
        `| 等级 | 数量 | 说明 |\n` +
        `|:---:|:---:|:---|\n` +
        `| 🔴 高危 | **${sm.high_count}** | 不建议开发，存在下架/封店/巨额赔偿风险 |\n` +
        `| 🟡 中风险 | **${sm.medium_count}** | 可做，但必须提前准备方案，评估额外成本 |\n` +
        `| 🟢 低风险 | **${sm.low_count}** | 风险可控，正常推进 |\n` +
        `| **综合评分** | **${sm.risk_score}/100** | ${sm.verdict}\n\n` +
        `---\n\n` +
        `### 🔍 逐条风险详情\n\n` +
        rpt.risks.map((r: any) =>
          `#### ${r.level_label} ${r.title}\n\n` +
          `> **类别**：${r.category_name}\n\n` +
          `**📌 风险说明**：${r.description}\n\n` +
          `**🔎 风险原因**：${r.reason}\n\n` +
          `**✅ 规避方案**：${r.solution}\n`
        ).join('\n\n---\n\n') +
        `\n\n---\n\n### 💡 最终建议\n\n${sm.verdict}`
      break
    // ===== AIGC 媒体生成器 =====
    case 'video-script-gen': {
      const platformLabel: Record<string, string> = { tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' }
      const styleLabelMap: Record<string, string> = { 'problem-solution': '痛点驱动', 'product-showcase': '产品展示' }
      content = `🎬 **带货脚本 + 分镜表已生成** — 「**${result.product_name || '-'}**」\n\n` +
        `- 平台：${platformLabel[result.platform] || result.platform}｜风格：${styleLabelMap[result.video_style] || result.video_style}｜总时长 ${result.total_duration || 0}s\n` +
        `- 分镜数：**${result.storyboard?.length || 0}** 个镜头（每个镜头含画面/旁白/运镜/字幕，可人工编辑）\n\n` +
        `> 完整分镜表见上方卡片。脚本确认后，可切换到「AI 短视频生成」按首帧 + 运镜逐镜头出片。`
      break
    }
    case 'ai-video-generator':
      const modeLabelsMap: Record<string, string> = { 'single-image': '🖼️ 单图极速生成', 'storyboard-pro': '🎬 分镜脚本专业模式' }
      const avMode = result.mode || result.params?.mode || 'storyboard-pro'
      content = `🎥 **短视频生成完成** ✅ — ${modeLabelsMap[avMode] || result.mode_label || 'AI 短视频'}\n\n` +
        `- 生成模式：${result.mode_label || (avMode === 'single-image' ? '单图极速生成' : '分镜脚本专业模式')}\n` +
        (avMode === 'single-image'
          ? `- 底图 → 全自动绘制画面成片\n`
          : `- 镜头数：${result.clip_count || result.params?.storyboardScenes?.length || 0} 个片段（各镜独立生成后拼接）\n`) +
        `- 时长：${result.metadata?.duration || 0}s | 分辨率：${result.metadata?.resolution || '-'}\n` +
        `- 文件大小：${result.metadata?.file_size || '-'}\n\n` +
        `可点上方结果卡片的「归档到素材库」手动保存视频与关键帧。` +
        `视频已就绪，可预览或一键分发到各平台。`
      break
  }

  return content
}
