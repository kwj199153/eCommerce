/**
 * Agent 工具定义
 * 每个 Agent 拥有一组工具卡片，点击后在 ChatPanel 下方展示对应表单
 *
 * 排序（按真实业务流）：
 *   1. 选品分析师 → 2. 竞品监控员 → 3. AIGC媒体生成器
 *   4. Listing 优化师 → 5. 广告分析师 → 6. 智能客服 → 7. 运营复盘师
 */

export interface ToolDefinition {
  id: string
  name: string
  icon: string // emoji or icon name
  description: string
  mode: 'form' | 'chat' | 'page' // form=表单输入, chat=聊天触发, page=独立页面
  status: 'active' | 'coming_soon'
  category?: string // 分组标签
}

// 按 Agent 分组的工具集（业务流排序）
export const AGENT_TOOLS: Record<string, ToolDefinition[]> = {
  // ====== 1. 选品分析师 ======
  // 顶部工具栏只保留「产出报表」类 form 工具（蓝海挖掘 / 利润测算）。
  // 痛点分析 / 选品避坑 / 竞品对比 移入对话框上方的候选评估 chip 区，由 AI 推理模板针对载入候选输出。
  'product-research': [
    {
      id: 'blue-ocean',
      name: '蓝海挖掘',
      icon: '🌊',
      description: '挖掘低竞争高需求品类机会',
      mode: 'form',
      status: 'active',
      category: '市场分析',
    },
    {
      id: 'profit-calc',
      name: '利润测算',
      icon: '💰',
      description: 'FBA费用+ROI+盈亏平衡计算',
      mode: 'form',
      status: 'active',
      category: '财务分析',
    },
  ],

  // ====== 2. 竞品监控员 ======
  'competitor-intel': [
    // —— 第 3 层：Agent 推理工具（读统一监控池 → 归因/总结/建议 + 证据表）——
    { id: 'intel-chat', name: '竞品智能问答', icon: '💬', description: '自然语言提问竞品池：调价/排名/差评/上新，自动归因给建议', mode: 'form', status: 'active', category: '推理' },
    { id: 'intel-weekly', name: '竞品周报', icon: '📋', description: '自动总结监控周期内谁降价/爆发差评/改Listing抢流量/促销节奏', mode: 'form', status: 'active', category: '推理' },
    { id: 'intel-anomaly', name: '异动洞察', icon: '🚨', description: '检测 BSR 暴涨/差评激增/价格骤降并自动归因，一句话业务解读', mode: 'form', status: 'active', category: '推理' },
    { id: 'intel-strategy', name: '策略推演', icon: '🧠', description: '基于竞品池推演反制/定价/上新节奏应对', mode: 'form', status: 'active', category: '推理' },
    { id: 'monitor-dashboard', name: '监控仪表盘', icon: '📊', description: '所有竞品价格/排名/库存状态一览', mode: 'form', status: 'active', category: '监控' },
    { id: 'price-track', name: '价格追踪', icon: '📉', description: '竞品价格变动趋势与预警', mode: 'form', status: 'active', category: '监控' },
    { id: 'market-share', name: '市场份额', icon: '🌍', description: '类目竞争格局与品牌份额分析', mode: 'form', status: 'active', category: '分析' },
    { id: 'pricing-analysis', name: '定价策略', icon: '💵', description: '竞品定价模式与促销节奏分析', mode: 'form', status: 'active', category: '分析' },
    { id: 'review-spy', name: '评论侦探', icon: '🔎', description: '深度挖掘竞品评论优劣势', mode: 'chat', status: 'active', category: '洞察' },
    { id: 'intruder-alert', name: '入侵者警报', icon: '🚨', description: '新进入市场竞争者威胁检测', mode: 'form', status: 'active', category: '预警' },
    { id: 'buy-box-analysis', name: 'Buy Box 分析', icon: '🛒', description: '购物车竞争格局与赢取策略', mode: 'form', status: 'active', category: '竞争' },
    { id: 'compare-grid', name: '多维对比', icon: '⚔️', description: '多维度全面对比多个竞品', mode: 'form', status: 'active', category: '对比' },
  ],

  // ====== 3. AIGC 媒体生成器 ======
  'aigc-media': [
    {
      id: 'static-asset-gen',
      name: '静态素材生成',
      icon: '🎨',
      description: '白底三视图、细节图、场景图、分镜首帧图（载入产品自动回填）',
      mode: 'form',
      status: 'active',
      category: '图片生成',
    },
    {
      id: 'video-script-gen',
      name: '短视频带货脚本',
      icon: '🎬',
      description: '基于卖点/痛点自动生成带货脚本与结构化分镜表（支持人工编辑）',
      mode: 'form',
      status: 'active',
      category: '视频脚本',
    },
    {
      id: 'ai-video-generator',
      name: 'AI 短视频生成',
      icon: '🎥',
      description: '基于分镜首帧+运镜指令分段生成短视频镜头（支持素材库选帧）',
      mode: 'form',
      status: 'active',
      category: '视频生成',
    },
  ],

  // ====== 4. Listing 优化师 ======
  // 顶部工具栏 4 个「生成类」form 工具（关键词 / 标题 / 五点 / 长描述）。
  // 点击工具 → 跳转到右侧「文案工作区」对应模块并高亮；SEO 诊断已下线。
  'listing-generator': [
    {
      id: 'keyword-miner',
      name: '关键词',
      icon: '🔑',
      description: '长尾词挖掘与搜索词扩展 · 竞品词源分析',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'title-gen',
      name: '标题',
      icon: '📝',
      description: '多版本标题生成 + 关键词覆盖（仅改标题；五点/长描述请用各自工具）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'bullet-gen',
      name: '五点',
      icon: '✨',
      description: '卖点提炼与五点撰写（仅改五点）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'desc-gen',
      name: '长描述',
      icon: '📄',
      description: 'A+ Content 风格产品长描述（仅改长描述模块）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
  ],

  // ====== 5. 广告分析师 ======
  'ad-analysis': [
    { id: 'ad-diagnosis', name: '广告诊断', icon: '🩺', description: '广告账户健康检查 A-F评级', mode: 'form', status: 'active', category: '诊断' },
    { id: 'keyword-report', name: '词报告', icon: '📈', description: '搜索词效果分析 高低效词识别', mode: 'form', status: 'active', category: '报告' },
    { id: 'bid-suggest', name: '出价建议', icon: '💡', description: '智能出价策略推荐', mode: 'form', status: 'active', category: '优化' },
    { id: 'competitor-ad', name: '竞品广告', icon: '🎯', description: '竞争对手广告策略 SOV分析', mode: 'form', status: 'active', category: '竞品' },
    { id: 'budget-alloc', name: '预算分配', icon: '💳', description: '多Campaign预算优化', mode: 'form', status: 'active', category: '优化' },
    { id: 'anomaly-detect', name: '异常检测', icon: '🚨', description: '花费突增/转化骤降预警', mode: 'chat', status: 'active', category: '监控' },
  ],

  // ====== 6. 智能客服 ======
  'customer-service': [
    { id: 'faq-search', name: '话术检索', icon: '💬', description: '业务话术库快速匹配（售后/客服/政策问答）', mode: 'chat', status: 'active', category: '知识库' },
    { id: 'order-track', name: '订单追踪', icon: '📦', description: '订单状态与物流查询', mode: 'form', status: 'active', category: '订单' },
    { id: 'ticket-create', name: '创建工单', icon: '🎫', description: '客户问题工单创建', mode: 'form', status: 'active', category: '工单' },
    { id: 'sentiment', name: '情感分析', icon: '😊', description: '客户反馈情感识别与升级判断', mode: 'chat', status: 'active', category: '分析' },
    { id: 'reply-draft', name: '回复草稿', icon: '✍️', description: '客户邮件/消息回复建议', mode: 'chat', status: 'coming_soon', category: '效率' },
  ],

  // ====== 7. 运营复盘师 ======
  'review-analyst': [
    {
      id: 'weekly-report',
      name: '经营概览',
      icon: '📋',
      description: '自动汇总本周销售、广告、库存、客诉数据，生成结构化周报',
      mode: 'form',
      status: 'active',
      category: '周期报告',
    },
    {
      id: 'monthly-review',
      name: '月度数据',
      icon: '📊',
      description: '全维度月度经营分析：GMV/ACOS/转化率/退货率趋势对比',
      mode: 'form',
      status: 'active',
      category: '周期报告',
    },
    {
      id: 'ad-review',
      name: '广告数据',
      icon: '📈',
      description: '广告投放效果深度回顾：ROAS/ACOS/CPC/CTR 多维度归因分析',
      mode: 'form',
      status: 'active',
      category: '广告分析',
    },
    {
      id: 'product-performance',
      name: '商品表现',
      icon: '🏆',
      description: 'SKU级表现排名：销量/利润率/周转天数/好评率，识别爆款与滞销品',
      mode: 'form',
      status: 'active',
      category: '商品分析',
    },
    {
      id: 'inventory-health',
      name: '库存健康',
      icon: '📦',
      description: '库存周转分析：滞销预警/断货风险/补货建议/FBA长期仓储费预估',
      mode: 'form',
      status: 'active',
      category: '供应链',
    },
    {
      id: 'profit-audit',
      name: '利润分析',
      icon: '💰',
      description: '全链路利润核算：销售额-平台佣金-FBA-广告-退货-仓储=净利润',
      mode: 'form',
      status: 'active',
      category: '财务分析',
    },
  ],
}

// 获取指定 Agent 的工具列表
export const getAgentTools = (agentId: string): ToolDefinition[] => {
  return AGENT_TOOLS[agentId] || []
}

// 获取工具定义
export const getToolDefinition = (agentId: string, toolId: string): ToolDefinition | undefined => {
  return AGENT_TOOLS[agentId]?.find(t => t.id === toolId)
}

/** Agent 显示顺序（用于侧边栏/顶部导航排列） */
export const AGENT_ORDER = [
  'product-research',     // 1. 选品分析师
  'competitor-intel',     // 2. 竞品监控员
  'aigc-media',           // 3. AIGC 媒体生成器
  'listing-generator',    // 4. Listing 优化师
  'ad-analysis',          // 5. 广告分析师
  'customer-service',     // 6. 智能客服
  'review-analyst',       // 7. 运营复盘师（新增）
]
