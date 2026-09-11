/**
 * 店秘书 · 意图识别（全局调度）
 *
 * 定位：
 *   店秘书是「全局入口 Agent」，本身不产出业务结果，只做一件事：
 *   把用户的一句话翻译成「切到某个 Agent」或「打开某个资料库视图」。
 *   这是 AI 原生 SaaS 的编排（Orchestrator）层。
 *
 * 实现选择：
 *   第一版走**前端规则识别**（关键词/正则），零后端改动、立即可用。
 *   后续若长尾说法覆盖不足，再把 recognizeSecretaryIntent 换成后端 LLM 意图分类，
 *   对外契约（返回 { reply, action }）保持不变，调用方无需改动。
 *
 * 规则顺序：先「资料库视图」（更具体），再「业务 Agent」（更泛），
 *   以避免「竞品」这类既可能是 Agent 又可能是视图的词产生歧义。
 */

import type { AppAction } from '@/utils/appActions'

export interface SecretaryResult {
  /** 面向用户的回复文本（Markdown） */
  reply: string
  /** 需要执行的动作（未识别到则不返回） */
  action?: AppAction
}

interface Rule {
  test: RegExp
  action: AppAction
  /** 回复文案（可用 {label} 占位目标名） */
  reply: string
}

const RULES: Rule[] = [
  // ====== 第一优先级：资料库 / 内容区视图（更具体的「库 / 看板」说法）======
  {
    test: /产品库|我的产品|上架产品|商品库|listing\s*库/i,
    action: { type: 'navigate', view: 'products' },
    reply: '好的，正在为你打开 **产品库**，你可以查看和管理所有上架商品。',
  },
  {
    test: /选品库|候选库|候选池|待评审/,
    action: { type: 'navigate', view: 'candidates' },
    reply: '好的，正在为你打开 **选品库**，待评审的候选选品都在这里。',
  },
  {
    test: /素材库|图片库|视频库|营销素材库/,
    action: { type: 'navigate', view: 'assets' },
    reply: '好的，正在为你打开 **营销素材库**。',
  },
  {
    test: /平台规则|规则库|平台政策/,
    action: { type: 'navigate', view: 'rules' },
    reply: '好的，正在为你打开 **平台规则库**。',
  },
  {
    test: /话术库|业务话术|\bfaq\b|知识库|问答库/i,
    action: { type: 'navigate', view: 'faq' },
    reply: '好的，正在为你打开 **业务话术库**。',
  },
  {
    test: /监控看板|监控页|监控工作台|监控大屏|竞品看板|竞争看板/,
    action: { type: 'navigate', view: 'monitor' },
    reply: '好的，正在为你打开 **竞品监控看板**。',
  },

  // ====== 第二优先级：业务 Agent（留在对话视图，切到专职 Agent）======
  {
    test: /listing|标题|五点|描述|关键词|文案|优化文案/i,
    action: { type: 'switch_agent', agentId: 'listing-generator' },
    reply: '好的，正在为你切换到 **Listing 优化师**，你可以直接开始优化标题 / 五点 / 描述等文案。',
  },
  {
    test: /选品|蓝海|利润测算|找产品|挖掘|潜力品|市场机会/,
    action: { type: 'switch_agent', agentId: 'product-research' },
    reply: '好的，正在为你切换到 **选品分析师**，可以开始蓝海挖掘 / 利润测算。',
  },
  {
    test: /竞品|对手|同行|竞争分析/,
    action: { type: 'switch_agent', agentId: 'competitor-intel' },
    reply: '好的，正在为你切换到 **竞品监控员**，可以先在右侧圈选竞品再发起分析。',
  },
  {
    test: /做图|出图|生成图|图片|生成素材|做素材|素材生成|视频|短视频|脚本|aigc|绘图/i,
    action: { type: 'switch_agent', agentId: 'aigc-media' },
    reply: '好的，正在为你切换到 **AIGC 媒体生成器**，可以做商品图 / 短视频。',
  },
  {
    test: /广告|acos|roas|出价|投放|推广|cpc|ctr/i,
    action: { type: 'switch_agent', agentId: 'ad-analysis' },
    reply: '好的，正在为你切换到 **广告分析师**。',
  },
  {
    test: /客服|工单|买家|订单|售后|差评回复/,
    action: { type: 'switch_agent', agentId: 'customer-service' },
    reply: '好的，正在为你切换到 **智能客服**。',
  },
  {
    test: /复盘|周报|月报|经营|报表|业绩|总结/,
    action: { type: 'switch_agent', agentId: 'review-analyst' },
    reply: '好的，正在为你切换到 **运营复盘师**，查看经营 / 广告 / 库存 / 利润看板。',
  },
]

/** 未识别时的兜底提示（把可用能力明确告诉用户，而不是死循环「没听懂」） */
const FALLBACK_REPLY = [
  '抱歉，我还没听懂你想做什么 🤔 你可以试试这样说：',
  '',
  '**切换到业务 Agent**',
  '- 「帮我改下这个 listing」→ Listing 优化师',
  '- 「找找蓝海产品」→ 选品分析师',
  '- 「看看竞品动向」→ 竞品监控员',
  '- 「做张商品图 / 视频」→ AIGC 媒体生成器',
  '- 「分析下广告」→ 广告分析师',
  '- 「本周经营复盘」→ 运营复盘师',
  '',
  '**打开资料库**',
  '- 「打开产品库 / 选品库 / 素材库 / 平台规则库 / 竞品监控看板」',
].join('\n')

/**
 * 识别用户一句话的调度意图。
 * @param text 用户输入
 * @returns { reply, action? } —— action 缺省表示仅回复、不跳转
 */
export function recognizeSecretaryIntent(text: string): SecretaryResult {
  const q = (text || '').trim()
  if (!q) {
    return { reply: '你想做什么？可以直接告诉我，比如「帮我改 listing」「打开产品库」「看看竞品」。' }
  }

  for (const rule of RULES) {
    if (rule.test.test(q)) {
      return { reply: rule.reply, action: rule.action }
    }
  }

  return { reply: FALLBACK_REPLY }
}
