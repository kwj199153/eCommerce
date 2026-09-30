"""
店秘书（主 Agent / 编排层）

定位：全局入口，把用户一句话翻译成「回复 + 动作」。
- 动作分两类：①路由（切到专职 Agent / 打开资料库 / 交接）②系统操作（切主题/店铺/产品、开账户菜单、查订阅）。
- 它**不产出业务结果本身**，只做路由与调度，业务专业实现全部下沉到各专职 Agent。

实现：
- 继承 `ai_infra.BaseAgent`，注入「导航/系统工具（约 9 个）」。
- 通过「bind_tools + LLM 调用」让 LLM 决定调哪个工具、填什么参。
- 业务 Agent 的工具**不注入主 Agent**（分层路由：主 Agent 管路由，子 Agent 管实现）。
"""

import json
import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger

from ai_infra.base_agent import BaseAgent
from ai_infra.budget import BUDGET_INTERACTIVE
from ai_infra.context import CONTEXT_INTERACTIVE
from ai_infra.plan import TODOS_STATE_KEY, plan_summary
from ai_infra.sse import ToolTrace, preview, progress
from modules.secretary import intent_shortcut
from modules.library import build_library_tools
from modules.secretary.navigation_tools import navigation_tools
from modules.secretary.subscription_tools import subscription_tools
from modules.secretary.product_tools import build_product_tools
from modules.secretary.shop_context import (
    ShopContext,
    render_shop_banner,
    render_shop_fact,
    sanitize_history,
)
from modules.secretary.shop_tools import build_shop_tools
# ★ 第 283 轮：提示词正文归位到 `modules/secretary/prompts.py`（键 `"secretary"`）。
#   这里保留 re-export：既有用例从 `modules.secretary.agent` 取这个名字。
from modules.secretary.prompts import SECRETARY_SYSTEM_PROMPT  # noqa: F401
from ai_infra.llm import get_prompt_template


def _fact_of(shop_context: Optional[ShopContext]) -> str:
    """从店铺上下文里取「要注入的事实段」（纯函数，空 ctx ⇒ 空串）。

    ★ 渲染口径收在 `shop_context.render_shop_fact`（唯一真源），这里只做
      「对象 → 那一段文本」的适配。调用方拿到的是**包裹**而不是裸字符串，
      所以不存在"传了事实却忘了传去污染名单"的半修状态。
    """
    return render_shop_fact(shop_context.brief if shop_context else None)


def _banner_of(shop_context: Optional[ShopContext]) -> str:
    """从店铺上下文里取「回复开头的当前店铺标注」（空 ctx ⇒ 空串）。

    ★ 与 `_fact_of` 同为"对象 → 文本"的适配层，渲染口径都收在 `shop_context`。
    """
    return render_shop_banner(shop_context.brief if shop_context else None)


def _with_shop_fact(base_prompt: str, shop_fact: str) -> str:
    """把「本轮店铺上下文」段**追加**在业务提示词之后（空 ⇒ 原样返回）。

    ★ 收敛成一个函数是为了让门禁只认这一处形态：事实必须以**追加**方式进入
      system prompt。若写成 `base + shop_fact` 直接拼，空串也会多出两个换行，
      `tests/test_secretary_agent.py` 那条
      `assert agent.system_prompt == SECRETARY_SYSTEM_PROMPT`（它守的正是
      「没绑定店铺时提示词一个字都不许变」）会因此转红。
    ★ 同理**不能**替换掉 `SECRETARY_SYSTEM_PROMPT`：替换会把规则 1–8 整段
      悄悄删掉，而且没有任何一处会报错。
    """
    text = (shop_fact or "").strip()
    return f"{base_prompt}\n\n{text}" if text else base_prompt


class SecretaryAgent(BaseAgent):
    """店秘书主 Agent"""

    #: ★ 第 148 轮 批 C3：开启**自主规划器**（`ai_infra.plan`）。
    #:
    #: 为什么开在店秘书：它是唯一的**全局入口**，也是唯一会收到**复合意图**的地方
    #: ——「先选中第 2 个产品，再切到 Listing 优化师，带上这条诉求」这类请求天然
    #: 是**多步工具序列**，而本档位的 `max_iterations=6` 会在第 7 步硬截断。
    #: 开启后：① 计划存进 `state["todos"]`，随 checkpointer 落 PG，
    #: **不随历史裁剪丢失**（第 147 轮批 C4 的裁剪只作用于消息序列）；
    #: ② 调用方能拿到 `plan`（进度 N/M），被截断时也说得清「停在第几步」，
    #: 而不是只看到一句「处理完成」。
    #:
    #: ★ 它**不违反** `SECRETARY_SYSTEM_PROMPT` 的规则 8（「一次只做最贴合意图的
    #: 一件事，不要多调无关工具」）：那条防的是「乱调无关工具」，而规划描述的是
    #: **同一件事的多个必要步骤** —— 两者不冲突，且 `PLANNING_GUIDE` 会追加在
    #: 业务 prompt 之后（见 `BaseAgent._system_prompt_with_plan`）。
    #: ★ 两个规划工具声明为 `LOCAL_STATE_METADATA`（只写本地 state）⇒ **免 HITL
    #: 审批**，不会给老板多出「请批准规划」的确认步骤。
    ENABLE_PLANNING = True

    #: ★ 第 238 轮 P2：第一轮（"理解 + 决策"）走更快的 `config.llm_fallback_model`。
    #:
    #: 老板原话：「闲聊分流到更快的模型 / 收紧 max_tokens 缩短时长，不解决空窗」。
    #: 选在店秘书开，是因为它**同时**是高频入口与最长的等待方（实测闲聊 11.4s）。
    #: ★ 不影响任务质量：见 `BaseAgent.FAST_FIRST_ROUND` 的判据段 ——
    #:   任务型请求的正文来自**最后一条** AIMessage，那一轮一定是默认强模型。
    #: ★ 想关掉：把 `config.llm_fast_first_round` 置 False（无需改代码）。
    FAST_FIRST_ROUND = True

    def __init__(
        self,
        llm=None,
        shop_id: Optional[str] = None,
        checkpointer=None,
        shop_context: Optional[ShopContext] = None,
        **kwargs,
    ):
        """构造店秘书。

        Args:
            shop_id: 当前店铺 ID（供 select_product / 资料库只读工具按店铺绑定）。
            shop_context: **本轮店铺上下文**（服务端构造，唯一入口
                `modules.secretary.shop_context.build_shop_context`）—— 它同时带着
                ① 要注入 system prompt 的事实段、② 要从历史里抹掉的其它店铺名。
                为 `None` ⇒ 两件事都不做，`system_prompt` 与
                `SECRETARY_SYSTEM_PROMPT` **逐字相同**（既有用例钉住）。
        """
        # 产品选择工具按店铺动态构建（shop_id 为空时返回空标记，由前端提示）
        product_tools = build_product_tools(shop_id)
        shop_tools = build_shop_tools()
        # ★ 第 205 轮：资料库只读工具（选品库 / 产品库）。
        #   本 Agent 是**按请求重建**的（模块级 `_agent` 不含店铺绑定），
        #   所以能在构造期就拿到**已校验**的 shop_id —— 这正是 `shop_id=`
        #   这条注入通道存在的理由（选品分析师那侧走 `resolve=`，
        #   因为它的路由子层是会被缓存的，见 `modules/library/tools.py`）。
        library_tools = build_library_tools(shop_id=shop_id)

        # ★ 第 242 轮下半：**历史去污染**用的其它店铺名（见 `_sanitize_history_for_model`）。
        #   从同一个包裹里取 ⇒ 与事实段**同生共死**，不会出现"注入了事实但没抹历史"。
        self._shop_foreign_names: tuple = tuple(
            shop_context.foreign_names if shop_context else ()
        )
        super().__init__(
            agent_name="secretary",
            # ★ 第 242 轮：把「当前店铺」权威事实**追加**在业务提示词之后。
            #   为什么必须有：修复前模型只能从**对话历史**里取店名，于是切店后
            #   仍写「当前店铺（虾皮1）」（实测事故：数据已经是亚马逊1 的、
            #   自称还是虾皮1；见 `modules/secretary/shop_context.py` 头注释）。
            system_prompt=_with_shop_fact(get_prompt_template("secretary"), _fact_of(shop_context)),
            tools=navigation_tools + subscription_tools + product_tools + shop_tools
            + library_tools,
            llm=llm,
            # ★ 第 145 轮 批 C5：裸数字 `max_iterations=6` → 具名档位。
            #   此前没有任何地方解释「为什么是 6」；现在它是「多轮对话型
            #   Agent（边问边查）」这一档的取值，且同档位一次说清三个维度
            #   （迭代 / token / 墙钟）—— 见 `ai_infra/budget.py`。
            budget=BUDGET_INTERACTIVE,
            # ★ 第 147 轮 批 C4：上下文档位与预算档位**同档**（INTERACTIVE）。
            #   多轮对话型主 Agent：历史最长，但裁得最轻（48k / 保底 8 轮）。
            #   两者管的是不同维度 —— 预算管「跑多久」，上下文管「这一次发出去多大」；
            #   同档只是让「为什么是这个数」在一处说得清（见 `ai_infra/context.py`）。
            context_policy=CONTEXT_INTERACTIVE,
            checkpointer=checkpointer,
            **kwargs,
        )

    def _sanitize_history_for_model(self, messages: list) -> list:
        """覆写基类钩子：把**发给模型的历史副本**里的其它店铺名抹掉。

        ★ 为什么这一半不可省（第 242 轮实测）：只注入事实时，模型仍照抄历史里
          那条现成的错误自称 —— 三组措辞全无效；把历史里的旧店名换成占位符，
          它就把占位符当店名抄下来。只有"历史里不存在旧店名"才稳定改口，
          而**只抹历史不注入**又会让它干脆不提店名（信息缺失）。
        ★ 名单为空（没绑店铺 / 只有一家店）⇒ 原样返回：零开销，且保证
          "没绑店铺时一切不变"这条既有判据继续成立。
        """
        if not self._shop_foreign_names:
            return messages
        return sanitize_history(messages, self._shop_foreign_names)


# 单例（不含店铺绑定；店铺相关工具按请求动态重建）
_agent: Optional[SecretaryAgent] = None


# ★ 第 159 轮（批 D3）：预算截断时给用户的提示前缀。
#   由 `route()` 在读到 `structured_response["status"] == "budget_truncated"` 时拼上。
#   这是 `structured_response` 的**第一个真消费者** —— 此前全仓生产代码 0 读点，
#   于是「被预算截断」与「正常答完」在调用方看来完全一样（C5 的承诺只做了一半）。
TRUNCATED_NOTICE = "（提示：本轮回答因预算限制被截断，结果可能不完整。）\n\n"


def get_secretary_agent(
    shop_id: Optional[str] = None,
    shop_context: Optional[ShopContext] = None,
) -> SecretaryAgent:
    """获取店秘书实例。

    因为 select_product 工具需要按店铺绑定 shop_id，而单例无法感知每个请求的
    店铺上下文，所以：
    - shop_id 为空：返回共享单例（工具集不含产品选择，或含空 shop 的产品工具）
    - shop_id 非空：每次新建实例（开销可接受，agent 初始化很轻）

    Args:
        shop_id: 当前店铺 ID（**已由依赖层校验**，见
            `core.tenant.middleware.get_current_shop_id*`）。
        shop_context: 本轮店铺上下文（见 `modules.secretary.shop_context`）。
            ★ 只在 `shop_id` 非空这条分支上有意义 —— 没有店铺就没有店铺上下文，
              单例（`shop_id` 为空时那条路）刻意不携带任何店铺绑定。

    决策层 C：优先尝试绑定全局 checkpointer（跨轮持久化）；若未初始化（如
    测试环境 / DB 未连），退化为无 checkpointer 的内存态，不抛错。
    """
    global _agent
    from core.checkpoint import get_checkpointer
    cp = get_checkpointer()
    if shop_id is None:
        # ★ 没有店铺就没有店铺上下文（单例刻意不携带任何店铺绑定）。
        if _agent is None:
            _agent = SecretaryAgent(checkpointer=cp)
        return _agent
    return SecretaryAgent(shop_id=shop_id, checkpointer=cp, shop_context=shop_context)


# --------------------------------------------------------------------------- #
# 图调用的**共用口径**（`route` 非流式 / `route_stream` 流式都走这里）
# --------------------------------------------------------------------------- #
#
# ★ 为什么必须共用：这两条路之间的差别**只该有一个** —— 「过程能不能边跑边看」。
#   若「怎么拼输入」与「怎么读结果」各抄一份，两条路的正文 / 动作 / 计划必然
#   缓慢漂移，而且**没有任何红灯**（本仓反复出现的形态：同一判定两份实现
#   ⇒ 至少一份永远测不到）。所以下面这几个函数是唯一真源。


def _shortcut_result(shortcut: dict) -> dict:
    """短路命中时的结果 dict —— 两条路共用（保证产出**同构**）。"""
    return {
        "reply": intent_shortcut.build_reply(shortcut),
        "actions": [shortcut],
        "action": shortcut,
        "tool_calls": intent_shortcut.to_tool_calls(shortcut),
        "route_mode": "shortcut",
        "shortcut_rule": shortcut.get("action", ""),
    }


def _log_shortcut(
    result: dict,
    started: float,
    query: str,
    shop_id: Optional[str],
    session_id: Optional[str],
) -> None:
    """短路路径的日志 —— 两条路共用（否则同一次请求在两条路上的读数口径不同）。"""
    logger.info(
        f"[secretary] 决策层B 短路命中 rule={result.get('shortcut_rule')} "
        f"shop={shop_id or '-'} session={session_id or '-'} "
        f"cost={(time.perf_counter() - started) * 1000:.1f}ms query={query[:40]!r}"
    )


def _log_llm_turn(
    result: dict,
    started: float,
    query: str,
    shop_id: Optional[str],
    session_id: Optional[str],
) -> None:
    """LLM 兜底路径的日志 —— 两条路共用。"""
    logger.info(
        f"[secretary] 决策层B LLM 兜底 shop={shop_id or '-'} "
        f"session={session_id or '-'} "
        f"cost={(time.perf_counter() - started) * 1000:.1f}ms "
        f"tools={result.get('tool_calls') or '-'} "
        f"actions={len(result.get('actions') or [])} query={query[:40]!r}"
    )


def _input_messages(
    query: str,
    history: Optional[list],
    agent: "SecretaryAgent",
    session_id: Optional[str],
    user_id: Optional[str],
) -> list:
    """拼本轮输入消息 —— 历史口径的**唯一实现**。

    - 有 checkpointer（会话 + 身份 + 图确实绑了 cp）：只传当前 query，
      历史由 checkpointer 自动恢复
    - 否则：手动拼 history（决策层 A 的会话级记忆）

    ★ 2026-09-17：thread_id 的生成 + 「没有会话怎么办」收进 `BaseAgent` 唯一实现
      （`graph_for_session()` / `resolve_thread_id()`）。改前这里有两个隐患：
        ① 无 session_id 时仍把 `"secretary-default"` 填进 config，而本图是**绑了
           checkpointer 的** ⇒ 所有无会话请求（含匿名）共用同一段消息历史，
           互相看得见对方说过什么（跨用户串记忆，且不报任何错）。
        ② 那个默认值是**全进程共享的常量**，不是"每个人一个"。
      `graph_for_session(None, None)` 改为返回**不带 checkpointer 的图 +
      空 config** ⇒ 没有会话就真的不留记忆（原则同 accounts：没有身份 ⇒
      没有数据）。
    ★ 第 131 轮再补一条：**有会话还不够，必须有身份** —— thread_id 里
      不带 `user_id` 时，两个用户拿到同一个 session_id 就会共享记忆。
    """
    use_checkpoint = (
        bool(session_id) and bool(user_id) and agent.checkpointer is not None
    )

    # 拼接输入消息：
    # - 有 checkpointer：只传当前 query，历史由 checkpointer 自动恢复
    # - 无 checkpointer：手动拼 history（决策层 A 的会话级记忆）
    messages: list = []
    if not use_checkpoint and history:
        for h in history:
            role = (h or {}).get("role")
            content = (h or {}).get("content", "")
            if not content:
                continue
            if role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


def _digest_graph_state(state: dict, *, banner: str = "") -> dict:
    """把**图最终状态**读成面向调用方的结果 dict —— **唯一取口**。

    ★ `route()`（非流式）与 `route_stream()`（流式）都调它。这不是洁癖：
      「流式版正文与非流式**逐字相同**」是本轮改动的回归判据，而它只有在
      两边读同一份状态、走同一段提取逻辑时才可能成立。

    ★★ 第 242 轮：`banner`（服务端渲染的「当前店铺」标注）也在这里拼 ——
      正因为这里是**唯一取口**，两条路才能自动同源。若让两条路各自拼一次，
      同一句话在流式与非流式下就会漂移（本仓判据：同一判定两份实现 ⇒
      至少一份永远测不到）。
    """
    messages = state.get("messages", [])

    # 只提取「本轮新增」的消息：定位最后一条 HumanMessage（= 本轮输入），其后的即为本轮产出。
    #
    # 为什么不用 aget_state 取调用前的历史长度（旧实现）：
    #   ① 多一次 DB 往返；② 连接池紧张时会 PoolTimeout，而当时的
    #   `except Exception: prev_count = 0` 会把它静默吞掉 → prev_count=0 →
    #   历史里的动作被当作本轮新增重复提取 → 前端重复切 Agent（切到 A 又切到 B）。
    # 用「最后一条 HumanMessage 之后」切分不依赖 DB，天然免疫该问题；
    # LLM 只产出 AIMessage / ToolMessage，不会再产生 HumanMessage，
    # 因此最后一条 HumanMessage 必然是本轮输入。
    last_human_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last_human_idx = i
    new_messages = messages[last_human_idx + 1:]

    # 1) 按顺序收集所有动作标记（导航/选择工具的 ToolMessage 内容）
    actions: list[dict] = []
    # 2) 提取工具调用名
    tool_calls: list[str] = []
    # 3) 最终回复文本（最后一条 AIMessage 的非空 content）
    reply = "处理完成"
    # 动作去重：LLM 偶尔会在一次回复里重复调用同一工具（如两次 switch_agent 同名同参），
    # 重复执行对前端无意义（切两次同一 Agent），这里按「动作签名」去重，保留首次出现。
    _seen_actions: set[str] = set()

    for m in new_messages:
        cls = m.__class__.__name__
        if cls == "ToolMessage":
            content = str(m.content)
            # 业务工具的 JSON 结果里也可能有 "action" 字段，需精确匹配导航/选择标记
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("action") in (
                    "switch_agent",
                    "navigate",
                    "select_product",
                    "account_menu",
                    "handoff",
                    "set_theme",
                    "switch_shop",
                ):
                    sig = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
                    if sig not in _seen_actions:
                        _seen_actions.add(sig)
                        actions.append(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        elif cls == "AIMessage":
            # 记录 tool_calls
            if getattr(m, "tool_calls", None):
                tool_calls.extend(tc.get("name") for tc in m.tool_calls if tc.get("name"))
            # 最后一条有内容的 AIMessage 作为回复
            content = m.content
            if isinstance(content, str) and content.strip():
                reply = content
            elif isinstance(content, list):
                # content 可能是多模态块列表
                text = "".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")
                )
                if text.strip():
                    reply = text

    # ★ 第 148 轮 批 C3：把子任务计划透出给调用方（前端按 `plan.items` 展示进度）。
    #   从 `state` 读、**不**从 messages 里解析：计划不在消息序列里 ——
    #   这正是它能跨上下文压缩存活的原因，所以只能从图状态取。
    #   ★ 只在真有计划时才带上这个键：恒返回 `{"total": 0}` 会让消费方分不清
    #   「这个 Agent 没开启规划」与「开启了但这一轮还没规划」。
    #   ★★ 这个「有才带、没有就不带」的形态是**前端三态语义的前提**
    #     （`stores/chat.ts::setPlan`：`undefined` ⇒ 保留旧值）。
    #     改成恒发 `null` 会让短路路径**误清**老板的计划条。
    _plan = plan_summary(state.get(TODOS_STATE_KEY) or [])
    result: dict = {
        "reply": reply,
        "actions": actions,
        "action": actions[-1] if actions else None,
        "tool_calls": tool_calls,
        "route_mode": "llm",
        "shortcut_rule": "",
    }
    if _plan["total"]:
        result["plan"] = _plan

    # ★ 第 159 轮（批 D3）：读 `structured_response` —— 兑现 C5 的承诺。
    #   `_respond_node` 一直把「本轮是否被预算截断」写进
    #   `structured_response["status"]`，但**没有任何调用方读它** ⇒ 截断与正常
    #   答完在调用方看来完全一样。这里读它，并且在截断时把提示**拼进 reply**：
    #   这样即使前端不渲染 `truncated` 字段，用户也已经看得到。
    #   ★ 为什么从图状态读而不是解析 messages：这条结论本就不在消息里
    #     （它由 `_respond_node` 写进状态），解析消息只会得到「模型说了什么」，
    #     得不到「模型是否被截断」。
    #   ★ 无读者 = 死重量，门禁见 `tests/test_agent_state_fields_have_readers.py`。
    _structured = state.get("structured_response") or {}
    if _structured.get("status") == "budget_truncated":
        result["truncated"] = True
        result["truncated_reason"] = (_structured.get("budget") or {}).get("reason")
        result["reply"] = TRUNCATED_NOTICE + reply

    # ★★★ 第 242 轮：服务端的「当前店铺」标注 —— **不过 LLM**，切店后必然跟随。
    #   为什么不让模型自称：实测四连（禁令文本被回显 / 模板句式让它从老板原话里
    #   挑名字 / 不要求就干脆不写）证明那条通道在措辞层面不可稳定。
    #   为什么拼在这：这里是正文**唯一取口**，两条路一并覆盖。
    #   空 reply 不拼（否则会出现一条只有标注、没有内容的回复）。
    if banner and result.get("reply"):
        result["reply"] = banner + result["reply"]

    return result


def _meta_event(result: dict, session_id: Optional[str]) -> dict:
    """结构化字段的**唯一出口**（`event: meta`）。

    ★ 为什么整份 `result` 原样下发、而不是逐字段挑：挑就会漏，而漏一个
      **不报错** —— 只是前端少一种能力（少个动作 / 计划不落库 / 会话不持久化）。
      `result` 的键本身就是「本轮到底产出了什么」的权威描述，例如 `plan`
      只在真有计划时才在（见 `_digest_graph_state` 的注释）。
    """
    return {"event": "meta", "data": {**result, "session_id": session_id}}


async def route(
    query: str,
    shop_id: Optional[str] = None,
    history: Optional[list[dict]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    shop_context: Optional[ShopContext] = None,
) -> dict:
    """一次路由调用，返回结构化结果。

    直接执行图并捕获消息流，从中提取：
    - reply：最终 LLM 回复文本
    - actions：有序的动作列表（switch_agent / navigate / select_product），
      前端按顺序依次 dispatch（例如「先选产品，再切 Agent」）
    - action：向后兼容，取 actions 里最后一个（单动作场景等价）
    - tool_calls：本次实际调用的工具名列表

    Args:
        query: 用户当前这一句话。
        shop_id: 当前店铺 ID（供 select_product 等按店铺过滤）。
        shop_context: **本轮店铺上下文**（服务端构造；`None` = 不注入、不抹历史）。
            ★ 为什么由调用方传进来、而不在本函数里取：本函数是**同步签名**、
              拿不到 DB 会话。真源与构造口径收在 `modules.secretary.shop_context`。
        history: 本会话的历史消息（[{role, content}]，role ∈ user/assistant），
            用于让 LLM 感知多轮上下文（如「再切换」能理解上一轮在说主题）。
            历史里**不应**包含当前 query（前端取的是「当前消息之前」的最近 N 条）。
        session_id: 会话 ID。与 `user_id` **同时**非空时才作为 checkpointer
            的 thread_id，实现跨轮持久化（决策层 C）；同时优先于前端显式传的
            history。
        user_id: **服务端身份**（`current_user.id`），不接受任何自报字段。
            与会话同样必需 —— 只有会话没有身份时，两个用户撞上同一个
            session_id 就会共享记忆（见 `BaseAgent.graph_for_session`）。

    Returns:
        {"reply": str, "actions": [dict], "action": dict|None, "tool_calls": [str],
         "route_mode": "shortcut"|"llm", "shortcut_rule": str}
    """
    started = time.perf_counter()

    # ===== 决策层 B：意图预判短路 =====
    # 高置信度的「纯导航 / 纯系统操作」直接产出动作，**跳过整次 LLM 调用**。
    # 判据在 intent_shortcut 里是「否定优先」：只要疑似复合意图就放行给 LLM。
    shortcut = intent_shortcut.match(query)
    if shortcut is not None:
        result = _shortcut_result(shortcut)
        _log_shortcut(result, started, query, shop_id, session_id)
        return result

    agent = get_secretary_agent(shop_id, shop_context=shop_context)

    # 决策层 C：会话 / 身份的语义（thread_id 怎么算、「没有会话怎么办」）
    # 收在 `BaseAgent.graph_for_session` / `resolve_thread_id` 里，拼输入消息的
    # 口径收在 `_input_messages` —— 两者都是唯一实现，流式路径走同一份。
    messages = _input_messages(query, history, agent, session_id, user_id)

    _graph, _cfg = agent.graph_for_session(session_id, user_id)
    state = await _graph.ainvoke({"messages": messages}, config=_cfg)

    result = _digest_graph_state(state, banner=_banner_of(shop_context))
    _log_llm_turn(result, started, query, shop_id, session_id)
    return result


async def route_stream(
    query: str,
    shop_id: Optional[str] = None,
    history: Optional[list[dict]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    shop_context: Optional[ShopContext] = None,
):
    """`route()` 的**流式版**：过程实时可见，正文与结构化字段与 `route()` 同源。

    ★ 与非流式的差别**只有一个**：过程能不能边跑边看。它由四件事保证，
      缺任何一条就退化成「转圈几秒 → 直接出结果」（= 老板第 212 / 238 轮
      抱怨的同一个现状）：

        ① 工具调用**逐条**下发成 `event: step`（`ToolTrace` 翻译 `astream_events`）；
        ② **模型 token 实时下发成 `event: preview`**（第 238 轮）—— 治的是
           「一个工具都没调、纯生成也要十几秒」那段**零输出**：工具轨迹再好，
           没工具可看时面板必然是空的，屏上唯一能显示的就是正在生成的 token。
           ⚠️ 它是**预览**：不进 `done`、不落库，随时会被后一段或最终正文替换；
        ③ 正文在图跑完后吐出，且与 `route()` **逐字同源** —— 两边都调
           `_digest_graph_state`（唯一取口），而不是靠"看起来一样"；
           ★ ②③ 是**两个级别**的东西：前端先拿 ② 上屏，再用 ③ 整段收口 ——
           这就是"不动正文唯一取口"的具体含义；
        ④ 结构化字段（actions / plan / session_id / route_mode / truncated）
           走 `event: meta` 一次性下发，前端据此切 Agent、落计划、存会话。

    ★ 为什么**没有**直接用 `StreamDigest`：它把「取工具轨迹」与「取最终答复」
      捆在同一趟遍历里，而本 Agent 的答复**必须从图状态读** —— `actions`
      （来自 ToolMessage）、`plan`（来自 `state["todos"]`）、`truncated`
      （来自 `state["structured_response"]`）与 `reply` 是同一次"读状态"的
      四个产物。若这里改用 `digest.reply`，本 Agent 就有了**两条**答复取法，
      而它们在「被预算截断」这一档上给出的文本不同（`route()` 会给 reply 拼
      `TRUNCATED_NOTICE` 前缀）⇒ 同一个 Agent 的两条链路正文不一样。
      所以这里只用 `ToolTrace`（`StreamDigest` 内部用的正是它），
      答复一律走 `_digest_graph_state`。

    Yields:
        dict —— 结构化事件（`progress` / `preview` / `step` / `meta`），交给
        `sse_event_stream` 按 `event` 字段分发；
        str —— **正文**（本 Agent 只有一段，即整条答复）。★ `preview` 不是正文。
    """
    started = time.perf_counter()

    # ===== 决策层 B：意图预判短路（与非流式**同一张表**、同一个判据） =====
    shortcut = intent_shortcut.match(query)
    if shortcut is not None:
        # 短路路径**不跑图** ⇒ 本来就没有过程可发。保持这个形态是有意的：
        # 「省掉整次 LLM 调用」正是它存在的全部价值 —— 为了"有过程"去跑一次
        # 假图，等于把加速器拆掉。
        result = _shortcut_result(shortcut)
        _log_shortcut(result, started, query, shop_id, session_id)
        yield result["reply"]
        yield _meta_event(result, session_id)
        return

    agent = get_secretary_agent(shop_id, shop_context=shop_context)
    messages = _input_messages(query, history, agent, session_id, user_id)

    # ★ 第一秒的反馈：图里要先跑 LLM 再跑工具，期间一个字节都不发就是"转圈"。
    #   注意它与 `step` 的分工（见 `ai_infra/sse.py::step`）：`progress` 是
    #   **会被覆盖**的单行提示，`step` 才是逐条追加、可折叠回看的轨迹。
    # ★ 第 238 轮 P1：把这段等待**分开报**（成本极低，但如实）。
    #   实测（238k：真 uvicorn + 真 HTTP 流式）：0.11s 出本条 → 3.20s 出首帧 token
    #   → 11.40s 结束。两段等待**性质不同** —— 这一段是"解析会话 + 组装
    #   system prompt"（我们自己的活），下一段是"模型首 token 延迟 TTFT"（对端的活）。
    #   一句笼统的「正在理解你的意图…」把两段混成一句，用户无从判断是卡住了
    #   还是在思考；而这两段的处置方式完全不同（前者查我们、后者换模型）。
    yield progress("正在准备上下文…")

    # ★ 工具人话标题走**注入**（与第 211 轮那 5 家同形）：真源在业务侧
    #   `modules/skills/tools_catalog.py::tool_title`，而 `ai_infra` 不许依赖
    #   业务（分层硬红线）⇒ 只能把查询口传进去。惰性 import：Agent 的
    #   **模块导入期**无需把 `modules.skills` 拉进依赖图。
    # 走**包门面**（本仓条款 1：跨模块引用不得伸手进包内部）。
    from modules.skills import tool_title

    # ★★ 第 238 轮：把 `on_chat_model_stream`（模型 token 增量）实时下发给前端，
    #    治「十几秒零输出」。形态是 `event: preview`（**预览**，不是正文）——
    #    为什么不能直接发 `delta`：本 Agent 的权威正文**必须**走
    #    `_digest_graph_state`（唯一取口），把 token 也发成 `delta` 会让 `done`
    #    与落库都变成「预览 + 正文」拼两遍。对照表见 `ai_infra/sse.py::preview`。
    #
    #    为什么用 `pending` 队列中转：`ToolTrace.feed` 是**同步**方法，它的回调
    #    不能 `yield`（同步函数没有 yield 口）。所以回调只入队，回到下面这个
    #    异步循环里再吐；每喂一条事件就排空一次 ⇒ 预览与触发它的事件**同序**
    #    到达前端（顺序乱了会看到"先出正文、再补预览"）。
    pending: list[dict] = []

    #: 第一轮模型调用的进度只报一次（见下面的 `on_chat_model_start` 分支）
    announced_first_call = False

    def _on_model_stream(text: str, segment: str) -> None:
        #: `segment` = 本次模型调用的 `run_id`，前端据此**换段即清零**
        #: （ReAct 中间轮那句"我先查一下…"不该留在屏上）。
        pending.append(preview(text, segment=segment))

    trace = ToolTrace(title_resolver=tool_title, on_model_stream=_on_model_stream)

    final_state: dict = {}
    # ★ 走 `stream_session`（而不是自己拼 `astream_events` 循环）：它顺带把
    #   **墙钟预算**也套上（同 `run_session`）—— 自己拼会静默漏掉预算，
    #   而漏掉不报错，只是"超时保护"悄悄消失。
    async for ev in agent.stream_session(
        {"messages": messages}, session_id=session_id, user_id=user_id
    ):
        # ★ 第 238 轮 P1：**模型开始被调用**时再报一条进度。
        #   它覆盖的正是最长的那段"静默"（实测 ≈3s 的 TTFT，比前一段长一个
        #   数量级）—— 在此之前屏上只有一句「正在准备上下文…」，而那已经
        #   不成立了：上下文早准备好了，此刻在等对端。
        #   ★ 只在**第一次**调用时报：ReAct 后续轮次由 `event: step` 的
        #     running 态覆盖（"正在调用工具"），再报一次只会让 tip 反复闪。
        #   ★ 接线点不是猜的：238d 实测真图会发 `on_chat_model_start`
        #     （闲聊场景 1 条）。
        if (ev or {}).get("event") == "on_chat_model_start" and not announced_first_call:
            announced_first_call = True
            yield progress("正在向模型提问…")

        s = trace.feed(ev)

        # 预览增量（来自 `on_chat_model_stream`）：先排空队列，再吐 step。
        # 两者**互斥**（同一条事件不可能既是 token 又是工具调用），顺序只影响可读性。
        while pending:
            yield pending.pop(0)         # → event: preview（实时）

        if s is not None:
            yield s                      # → event: step（实时）

        # 根图的 `on_chain_end` 排在所有子事件之后 ⇒ 最后写进来的是整张图的
        # **最终 state**（子节点的中间态会被它覆盖）。这与 `StreamDigest.feed`
        # 取答复用的是同一个判据。
        if (ev or {}).get("event") == "on_chain_end":
            out = (ev.get("data") or {}).get("output")
            if isinstance(out, dict) and out.get("messages"):
                final_state = out

    result = _digest_graph_state(final_state, banner=_banner_of(shop_context))
    _log_llm_turn(result, started, query, shop_id, session_id)
    yield result["reply"]
    yield _meta_event(result, session_id)

async def current_plan(
    session_id: Optional[str],
    user_id: Optional[str],
    shop_id: Optional[str] = None,
) -> Optional[dict]:
    """只读：取当前会话的子任务计划（**不推进图、不调 LLM、不写任何东西**）。

    为什么需要一个「读口」
    ----------------------
    `route()` 确实每次都把计划带在响应里，但那是**对话的副产品**：老板刷新
    页面之后，前端手上没有任何"最近一次响应"，计划条就只能空着 —— 直到他
    再随便说一句话。而计划是**跨轮持续的状态**（后端刻意把它放在图状态而不是
    消息序列里，正是为了让它不随上下文裁剪消失），所以它也该有一个不依赖
    「刚好聊过一句」的读取方式。

    ★ 这里**只 `aget_state`**，绝不 `ainvoke`：读一次计划不该产生 LLM 费用，
      也不该在图里留下任何痕（它连一条消息都不写）。

    归属（为什么读到的只可能是你自己的）
    ------------------------------------
    ① `thread_id = ns:user_id:session_id`（`BaseAgent.resolve_thread_id`），
       而 `user_id` 来自**服务端身份**、不接受任何自报字段 ⇒ 物理上隔开
       不同用户。别人拿着你的 session_id 来读，算出的是**他自己**的键。
    ② 缺 `session_id` 或 `user_id` ⇒ 直接返回 None，**不去猜**一个默认线程
       （原则同 `graph_for_session`：没有会话 ⇒ 不留记忆）。
    ③ 读不到与"没有计划"返回**同一个东西**（`None`），不区分原因
       —— 一旦区分，这个端点就成了"这个 session_id 是否存在"的探针。

    Args:
        session_id: 会话 ID（客户端提供）。
        user_id: **服务端**身份（`current_user.id`）。
        shop_id: 当前店铺（只用于挑 agent 实例，不影响归属）。

    Returns:
        与 `route()` 的 `plan` 字段同形状的 dict；没有计划 / 没有会话 / 读失败
        一律返回 `None`。
    """
    if not session_id or not user_id:
        return None

    agent = get_secretary_agent(shop_id)
    if agent.checkpointer is None:
        return None

    graph, cfg = agent.graph_for_session(session_id, user_id)
    try:
        snapshot = await graph.aget_state(cfg)
    except Exception as e:
        # ★ 读失败**不抛**：这个端点是"锦上添花"的读口，它挂掉不该把
        #   前端的整个计划区变成错误页。返回 None = 没有计划，界面自己
        #   决定要不要提示（前端有 `planError` 出口时再区分）。
        logger.warning(f"[secretary] 读计划失败 session={session_id or '-'}: {e}")
        return None

    values = getattr(snapshot, "values", None) or {}
    plan = plan_summary(values.get(TODOS_STATE_KEY) or [])
    return plan if plan["total"] else None
