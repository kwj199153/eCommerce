/**
 * 回复链路 · 店秘书（全局入口 · 编排层）
 *
 * 一个大脑：既能导航（切 Agent / 开资料库 / 切店铺 / 切主题）又能执行（调工具出结果）。
 * 首选后端主 Agent（LLM + bind_tools，导航与执行统一用 tool_calls 表达），
 * 失败才降级到本地正则识别 —— 而且**必须显式告诉用户降级了**（见下方注释）。
 *
 * ★ 第 212 轮：主链路从非流式 `POST /orchestrator/chat` 换成 **SSE**
 *   （`POST /orchestrator/chat/stream`）。非流式那张图跑完才吐响应、中途
 *   **一个事件都不发**，而店秘书是 `AGENT_LIST[0]`（打开应用默认选中）
 *   ⇒「思考过程」恰好在**默认入口**上缺席。现在过程（`progress` / `step`）
 *   实时可见，出结果后折叠回看；正文与结构化字段仍与 `/chat` **同源**
 *   （后端两条端点共用 `route_stream` / `_digest_graph_state`）。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import type { SecretaryMeta } from '@/api/secretary'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ReplyOutcome } from '../types'

export async function replySecretary(ctx: ChatCtx, userMessage: string): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  // ★ 第 212 轮切流式后新增的三个入口：阶段文案 / 正文增量 / 工具轨迹。
  //   它们都是 `ChatCtx` 上的**稳定 thunk**，与其余 5 条流式链路解构的是同三个。
  const { scrollToBottom, loadingStatus, setLoading, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince } = ctx

    // 店秘书（全局入口 · 编排层）：一个大脑，既能导航（切 Agent / 开资料库）又能执行（调工具出结果）
    if (agentStore.currentAgent?.id === 'secretary') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      const { dispatchAppAction } = await import('@/utils/appActions')

      // 首选：后端主 Agent（LLM + bind_tools，导航与执行统一用 tool_calls 表达）
      //
      // ★ 第 212 轮：改走 **SSE 流式**（`POST /orchestrator/chat/stream`）。
      //   原来走非流式 `/chat` —— 整张图（含工具调用）跑完才吐响应，中途
      //   **一个事件都不发**；而店秘书是 `AGENT_LIST[0]`（打开应用默认选中），
      //   于是"思考过程"恰好在**默认入口**上缺席（界面上只有转圈）。
      //   两条端点在后端**共用实现**（`route_stream` 与 `route` 都调
      //   `_digest_graph_state` / `_resolve_session`）⇒ 正文、动作、计划、会话
      //   与非流式**同源**，换通道不改变语义。
      // ★ `streamed` 必须声明在 `try` **之外**：它要给下面的 `finally` 用，
      //   也要给外层 `catch` 的取消判定用 —— `let` 写在 `try{}` 里时 `catch` 看不见它。
      let streamed = false
      try {
        const { streamSSE } = await import('@/api/stream')

        // 会话级记忆：取本 Agent（secretary）对话区的历史消息，排除刚 push 的当前这条，
        // 截取最近 N 条传给后端，让 LLM 感知多轮上下文（如「再切换」能理解上一轮主题）。
        const HISTORY_LIMIT = 10
        const currentHistory = chatStore.getMessages('secretary')
        const history = currentHistory
          .slice(0, -1) // 去掉最后一条（= 当前 userMessage）
          .slice(-HISTORY_LIMIT)
          .filter((m: any) => m.content && typeof m.content === 'string')
          .map((m: any) => ({ role: m.role, content: m.content }))

        // 决策层 B：跨会话记忆 —— 取持久化的 sessionId（若有），后端据此从 DB 恢复历史
        const sessionId = chatStore.getSessionId('secretary')

        // ★ 先落一条**空的** assistant 消息再开流。
        //   理由：「思考过程」（`thinkingSteps`）与正文都写在**最后一条消息**上
        //   （`stores/chat.ts::appendThinkingStep` / `appendToLastMessage` 取的都是
        //   `list[list.length - 1]`）。若沿用旧写法「等响应齐了再 addMessage」，
        //   流式期间到达的 `step` 就没有宿主 ⇒ 过程**整段丢掉**，而且**零报错**
        //   —— 那正是老板抱怨的「转圈几秒 → 直接出结果」。
        // ★ 取消若发生在上面的 await 期间 ⇒ 连占位气泡都别建（建了也没人收）
        if (isCancelledSince(epoch0)) return 'handled'
        chatStore.addMessage({ role: 'assistant', content: '' })

        // meta（结构化字段）**晚于**正文到达（后端 `route_stream` 先 yield 正文、
        // 再 yield meta），所以这里只把它攒下来，流结束后再走下面那段**原有的**
        // 后处理 —— 那段逻辑（session_id / setPlan / actions 延时 dispatch）本轮的
        // 唯一改动就是 res 的来源从 HTTP 响应换成了 meta 事件。
        const metaHolder: { value: SecretaryMeta | null } = { value: null }
        // ★ 第 238 轮：预览的**当前段号**（后端那次模型调用的 run_id）。
        //   换段 ⇒ 上一段预览作废、屏上清零重来（ReAct 中间轮的碎话不该留下）。
        let previewSegment = ''
        // ★ 权威正文的累积（口径 = 后端的 `delta` / `done`：**整段替换**预览）
        let authoritativeText = ''
        const signal = beginStream()
        try {
          await streamSSE(
            '/orchestrator/chat/stream',
            { message: userMessage, history, session_id: sessionId },
            {
              // 阶段提示（会被覆盖的单行文案）：解决"第一秒零输出"
              onProgress: (text) => { loadingStatus.value = text },
              // 工具轨迹：逐条追加、结果到达后折叠保留 —— 这就是"思考过程"
              onStep: handleThinkingStep,
              // ★★ 第 238 轮：模型 token 的**预览**增量 —— 治「十几秒零输出」。
              //   ⚠️ 它不是正文（正文走下面的 `onDelta`）。一个工具都没调时，
              //   `step` 面板必然是空的，屏上唯一能显示的就是它。
              onPreview: (text, segment) => {
                setLoading(false, 'sse-delta-secretary')
                // 换段即清零：ReAct 中间轮那句"我先查一下…"不该留在屏上
                if (segment !== previewSegment) {
                  previewSegment = segment
                  chatStore.setLastMessageContent('')
                }
                chatStore.appendToLastMessage(text)
              },
              // 正文（权威）：后端在图跑完后**整段**下发 `_digest_graph_state` 的产物
              // ⇒ 这里用**整段替换**而不是追加，把上面的预览一并收口。
              //   追加会让屏上变成「预览 + 正文」拼两遍 —— 与后端 `done` / 落库
              //   用同一份正文的口径对齐：屏上正文 == done 正文 == 落库正文。
              onDelta: (text) => {
                setLoading(false, 'sse-delta-secretary')
                authoritativeText += text
                chatStore.setLastMessageContent(authoritativeText)
              },
              // 收口：以流结束时后端给的完整正文为准（它 = delta 累积 = done）
              onDone: (full) => {
                if (full) chatStore.setLastMessageContent(full)
              },
              // ★ 载荷是**整份 `/chat` 响应对象**（+ session_id），不是其余 5 家的
              //   `{display_type, data}` 信封 —— 见 `api/secretary.ts::SecretaryMeta`。
              //   这里标注类型而不是用 any：里面装着 actions / plan / session_id，
              //   字段名写错就是"前端少一种能力"，而 TS 是唯一的发现口。
              onMeta: (meta) => { metaHolder.value = meta as SecretaryMeta },
            },
            { signal },
          )
          streamed = true
        } finally {
          endStream(signal)
          if (!streamed) {
            // 流没起来 / 中途断：撤掉那条空的 assistant 消息，把控制流交回下面的
            // 降级链（本地正则 + 显式提示）。不撤的话界面上会留一个空气泡
            // （"回复了个寂寞"），而且零报错。
            const list = chatStore.getMessages(chatStore.activeAgentId)
            const last = list[list.length - 1]
            if (last && last.role === 'assistant' && !last.content) {
              chatStore.removeMessage(list.length - 1)
            }
          }
        }

        const res = metaHolder.value
        if (!res) {
          // ★ 流是通的、却一条 meta 都没来 —— 后端契约破了（例如只发了 `event: error`
          //   就收尾）。**显式抛**，让它走降级链，不要假装这一轮成功了。
          //   （本仓铁律：禁止静默假装成功。）
          throw new Error('流式响应缺少 meta 事件（拿不到 actions / plan / session_id）')
        }

        // 保存后端返回的 sessionId（跨会话记忆的关键：刷新后凭它恢复历史）
        if (res.session_id) {
          chatStore.setSessionId('secretary', res.session_id)
        }

        // ★ 第 155 轮：把子任务计划写进**会话级状态**（不是挂在某条消息上）。
        //   后端的计划存在图状态里、刻意不放进消息序列 ⇒ 对话变长、历史被裁剪
        //   它都不会丢；前端若把它当成某条消息的附件，那条消息一变历史就
        //   '看起来没了'，与后端语义矛盾。渲染端见 ChatPanel/PlanChecklist.vue。
        //   ★ 短路路径（route_mode='shortcut'，如「打开设置」）**根本没走图**，
        //   响应里不带 plan ⇒ 传下去的是 undefined，setPlan 会**保留旧值**
        //   （三态语义见 stores/chat.ts 的 setPlan）。
        chatStore.setPlan('secretary', res.plan)

        // 动作：交给 dispatchAppAction 按顺序落地（切 Agent / 打开资料库 / 选中产品）
        // 后端返回有序 actions 列表（如「先选产品，再切 Agent」），依次执行；
        // 向后兼容：无 actions 时退回单个 action。
        const actionList = (res.actions && res.actions.length > 0)
          ? res.actions
          : (res.action ? [res.action] : [])

        const hasHandoff = actionList.some((a: any) => a?.action === 'handoff')

        // ★ 店铺切换必须**同步**落地并检查结果：
        //   它是「环境切换」而非异步副作用 —— 用户说完就该看到左上角变了。
        //   若只把它塞进下面的 setTimeout 里、又不看返回值，就会出现
        //   「回复说已切换、左上角却没换」——用户读到的是 AI 撒谎，实际是动作被静默丢弃。
        //   所以：先同步执行 → 拿到成败 → 再决定回复文案。
        //   注：`switch_shop` 本身只依赖 id（无前置依赖），正常恒成功；
        //   失败路径仅兜底「后端给了空 id」这种畸形数据。
        const shopAction: any = actionList.find((a: any) => a?.action === 'switch_shop' && a?.shop?.id)
        let shopSwitchFailed = false
        let shopSwitchName = ''
        if (shopAction) {
          shopSwitchName = shopAction.shop?.name || ''
          shopSwitchFailed = !dispatchAppAction({
            type: 'switch_shop',
            shopId: shopAction.shop.id,
            shopName: shopAction.shop?.name,
            platform: shopAction.shop?.platform,
          })
        }

        // 渲染回复文本
        // 若有 handoff 动作：LLM 的 reply 通常会复述字段名/工具名，对用户不友好，
        // 这里覆盖为简洁的"已交接"模板，详细追问交给子 Agent 对话区渲染。
        let displayReply = res.reply || '处理完成'
        // 流式下正文**早已经渲染上屏**了，所以下面若改写了文案，要显式替换它
        // （旧的非流式实现是"改完再 addMessage"，流式做不到）。
        // ★ 第 238 轮：屏上此刻的正文**就是** `res.reply` —— 预览由 `onPreview`
        //   上屏、由权威正文（`onDelta` / `onDone`）整段收口，收口用的正是
        //   `meta.reply` 同一个值。所以基线仍取后端 reply，不必回读 store。
        const streamReply = displayReply
        if (shopSwitchFailed) {
          // 显式降级 + 给原因（项目铁律：禁止静默假装成功）
          displayReply = shopSwitchName
            ? `> ⚠️ 没能切换到「${shopSwitchName}」——后端未给出有效的店铺标识。请在左上角「店铺群」里手动选择。`
            : '> ⚠️ 没能切换店铺——后端未给出有效的店铺标识，请在左上角「店铺群」里手动选择。'
        } else if (hasHandoff) {
          const handoffAct: any = actionList.find((a: any) => a?.action === 'handoff')
          const targetAgent = agentStore.agentList.find(a => a.id === handoffAct?.agentId)
          const agentLabel = targetAgent?.name || '专业助手'
          // ★ 第 215 轮改口吻：原文案是「他会在自己的对话里跟你确认几个细节」——
          //   它把**前端模板的追问**说成了子 Agent 的行为，而 handoff 只切页、不续跑。
          //   改成店秘书第一人称（确实是它在问），与子 Agent 对话区的来源标注对齐。
          displayReply = `好嘞，这事儿交给 **${agentLabel}** 处理。它还缺几项信息，我先替你问出来 —— 你补齐就能直接开干。`
        }
        if (displayReply !== streamReply) {
          // 就地替换最后一条的正文（**不删不加**）：过程（thinkingSteps）与结论卡
          // （data / displayType）都留在同一条消息上 —— 这两条分支恰恰最需要过程
          // 来解释"为什么没切成功 / 交给谁了"。
          chatStore.setLastMessageContent(displayReply)
        }
        await scrollToBottom()

        actionList.forEach((act, i) => {
          // 每个动作稍作错开（700ms + 序号），让前一个动作先落地
          setTimeout(() => {
            const { action, agentId, view, product, drawer, target, intent, missing_fields, mode, shop, query } = act as any
            if (action === 'switch_agent' && agentId) {
              // query 非空 → 路由带参：dispatchAppAction 会派发 agent-auto-task 事件，
              // 由 handleAgentAutoTask 把老板原话注入子 Agent 对话区并自动续跑。
              dispatchAppAction({ type: 'switch_agent', agentId, query })
            } else if (action === 'navigate' && view) {
              dispatchAppAction({ type: 'navigate', view })
            } else if (action === 'select_product' && product?.id) {
              dispatchAppAction({ type: 'select_product', productId: product.id })
            } else if (action === 'open_drawer' && drawer) {
              dispatchAppAction({ type: 'open_drawer', drawer })
            } else if (action === 'account_menu' && target) {
              dispatchAppAction({ type: 'account_menu', target })
            } else if (action === 'set_theme' && mode) {
              dispatchAppAction({ type: 'set_theme', mode })
            } else if (action === 'switch_shop') {
              // 已在上方同步执行（含失败回报），此处跳过，避免重复 dispatch。
            } else if (action === 'handoff' && agentId) {
              dispatchAppAction({
                type: 'handoff',
                agentId,
                intent: intent || '',
                missingFields: Array.isArray(missing_fields) ? missing_fields : [],
                // ★ 第 215 轮：原话透传给交接事件，子 Agent 对话区会回显它。
                //   不传 = 链接 / ASIN 这类只在原话里的信息随交接丢失（实测事故）。
                query,
              })
            }
          }, 700 + i * 300)
        })
        return 'handled'
      } catch (error) {
        // ★ 用户点了「停止生成」⇒ 这**不是**失败。一旦落进下面的降级链，屏上会补一句
        //   「⚠️ 后端服务暂时不可用，已切换到本地简易识别」—— 用户自己按的停止，
        //   却被告知后端挂了，而且本地正则还会「接着演」一遍。
        if (absorbStreamCancel(chatStore, streamed, error)) return 'handled'
        // 后端不可用（演示模式 401 / 后端未启动）→ 降级到前端正则识别
        console.warn('[店秘书] 后端 orchestrator 不可用，降级到本地正则识别:', error)
      }

      // 降级：前端正则识别（规则式，覆盖常见说法）
      try {
        const { recognizeSecretaryIntent } = await import('@/mock/secretaryBrain')
        const out = recognizeSecretaryIntent(userMessage)
        // 显式提示降级原因：静默降级会让用户误以为「AI 变笨了 / React 没做好」，
        // 实际是后端服务不可用（未启动 / 500）。提示后用户能自行判断是否需要排查服务。
        chatStore.addMessage({
          role: 'assistant',
          content: `> ⚠️ 后端服务暂时不可用，已切换到本地简易识别（能力有限）\n\n${out.reply}`,
        })
        await scrollToBottom()
        const fallbackAction = out.action
        if (fallbackAction) {
          setTimeout(() => dispatchAppAction(fallbackAction), 700)
        }
      } catch (error) {
        console.error('店秘书调度失败:', error)
        chatStore.addMessage({ role: 'assistant', content: '❌ 调度执行失败，请重试。' })
      }
      return 'handled'
    }
  // 本分支没接住（API 挂了 / 前置不满足）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}
