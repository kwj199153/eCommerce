import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useChatStore } from '@/stores/chat'
import {
  SearchOutlined,
  EyeOutlined,
  PictureOutlined,
  FileTextOutlined,
  BarChartOutlined,
  CustomerServiceOutlined,
  LineChartOutlined,
  RobotOutlined,
} from '@ant-design/icons-vue'

export interface Agent {
  id: string
  name: string
  icon: any
  description?: string
  status?: 'active' | 'coming_soon' | 'beta'
}

// 预定义的 Agent 列表（按真实业务流排序）
const AGENT_LIST: Agent[] = [
  // 0. 店秘书（全局入口 · 编排层）：不产出业务结果，负责把用户一句话调度到对应 Agent / 资料库
  {
    id: 'secretary',
    name: '店秘书',
    icon: RobotOutlined,
    description: '全局调度：一句话直达对应 Agent 或打开资料库',
    status: 'active',
  },
  // 1. 选品分析师
  {
    id: 'product-research',
    name: '选品分析师',
    icon: SearchOutlined,
    description: '蓝海挖掘、利润计算、竞品分析',
    status: 'active',
  },
  // 2. 竞品监控员
  {
    id: 'competitor-intel',
    name: '竞品监控员',
    icon: EyeOutlined,
    description: '价格追踪、上新监控、舆情分析',
    status: 'active',
  },
  // 3. AIGC 媒体生成器
  {
    id: 'aigc-media',
    name: 'AIGC 媒体生成器',
    icon: PictureOutlined,
    description: 'AI商品绘图、主图诊断、短视频分镜、AI视频生成',
    status: 'active',
  },
  // 4. Listing 优化师
  {
    id: 'listing-generator',
    name: 'Listing 优化师',
    icon: FileTextOutlined,
    description: '标题、五点、描述、关键词生成优化',
    status: 'active',
  },
  // 5. 广告分析师
  {
    id: 'ad-analysis',
    name: '广告分析师',
    icon: BarChartOutlined,
    description: '广告诊断、词报告、出价优化、竞品监控',
    status: 'active',
  },
  // 6. 智能客服
  {
    id: 'customer-service',
    name: '智能客服',
    icon: CustomerServiceOutlined,
    description: 'FAQ问答、订单追踪、工单管理',
    status: 'active',
  },
  // 7. 运营复盘师（新增）
  {
    id: 'review-analyst',
    name: '运营复盘师',
    icon: LineChartOutlined,
    description: '周报/月度复盘、广告归因、商品表现、利润审计、行动计划',
    status: 'active',
  },
]

export const useAgentStore = defineStore('agent', () => {
  // 当前选中的 Agent（默认进入「店秘书」全局入口，形态 B：AI 原生的默认首页）
  const currentAgent = ref<Agent | null>(AGENT_LIST[0])

  // Agent 列表（计算属性，可后续从 API 获取）
  const agentList = computed(() => AGENT_LIST)

  // 点击计数器（用于在 currentAgent 引用未变时仍能触发响应）
  // 场景：在产品库视图下点击"当前已选中的 agent"，currentAgent 引用不变，
  //       但用户期望视图切回 chat。用计数器作为附加触发信号
  const agentClickCounter = ref(0)

  // 设置当前 Agent
  const setCurrentAgent = (agent: Agent) => {
    currentAgent.value = agent
    // 同步切换对话区：让 chatStore 的 addMessage 路由到当前 Agent
    const chatStore = useChatStore()
    chatStore.setActiveAgent(agent.id)
    // 触发点击计数（即便 agent 没变，watch 也能响应）
    agentClickCounter.value++
    console.log('✅ 切换 Agent:', agent.name)
  }

  // 初始化：把默认 Agent（店秘书）同步到 chatStore，保证首屏消息路由正确
  useChatStore().setActiveAgent(AGENT_LIST[0].id)

  return {
    currentAgent,
    agentList,
    agentClickCounter,
    setCurrentAgent,
  }
})
