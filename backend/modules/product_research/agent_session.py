# -*- coding: utf-8 -*-
"""选品 Agent 的**会话与状态层**（P0-6 第五刀：从 `agent_product_research.py` 外移）。

## 这一层是什么

「**这次请求属于哪个会话、它的状态放哪儿**」的全部实现：

    state_scope            状态作用域（唯一口径：有身份 ⇒ 走 thread_id 口径）
    state_key              返回 `(内存作用域, 落盘键)`；落盘键为 None ⇒ 不落库
    session                取（必要时创建）该会话的状态容器
    hydrate_state          入口：把该会话的状态从 PG 读回内存
    flush_state            出口：把内存里未落盘的改动写回 PG
    last_products          该会话上一轮蓝海产出的候选商品
    last_blue_ocean        默认会话的蓝海结果（兼容旧引用的只读别名）
    bind_context           把会话 ID / 已校验店铺 ID / 身份绑定到 ContextVar
    session_context_block  给「对话类」LLM 回复注入本轮会话语境

原先是 `ProductResearchAgent` 上的 8 个方法 + 1 个只读 property + 3 段类体注释。

## 为什么用显式传参（而不是 mixin / 继承）

与前四刀同一条方法论（见 `agent_routing.py` 的长注释）：**藏进基类只会让耦合从
「可以数的参数」变成「看不见的继承链」**，门禁再也数不出这个类实际依赖什么。
于是本模块的函数签名**就是依赖清单**：

    resolve_thread_id  作用域键的口径（原 `self.resolve_thread_id()`，来自 BaseAgent）
                       —— **传回调不传 self**：只声明「我用你的这一个方法」
    registry           有界 + 脏追踪的状态容器注册表（原 `self._session_states`）
                       —— 它是**实例状态**，按值传入

★ 为什么 `resolve_thread_id` 必须**作为回调**传入、而不是 `self.` 查找：
  业务侧只允许**一处**调它（本模块 `state_scope`）。两处各算一份键 ⇒ 状态与
  checkpoint 描述"同一个会话"却键不同 ⇒「历史还在、槽位没了」，两边都不报错。
  第 138 轮的 `X-Shop-ID` 事故正是"同一概念两套 ID 空间"。

## 反向依赖：3 个 ContextVar 与 2 个存储门面仍住主文件

`_current_context_id` / `_current_shop_id` / `_current_user_id` 的**真源**留在主文件：
生产侧 `modules/product_research/tools.py` 与 3 个测试文件都按**主文件路径**导入
它们 —— 搬走等于替第三方改契约。`_hydrate_session_state` / `_persist_session_state`
同理，且理由更硬：`tests/test_agent_session_state.py` 的 `_patch_store()` 用
`patch.object(主文件模块, "_hydrate_session_state", …)` 打桩；若本模块另取一份
`import`，那个补丁会**静默失效**（测试照绿、实测没打上）。

于是本模块取**模块别名** `_pr`（与 `tools.py` 取 `_current_context_id` 同款），且
**只在函数体内**访问它的属性：主文件顶层会 `import agent_session`，本模块顶层
`import` 主文件 ⇒ 成环；但环里只绑定**模块对象**、不取属性，运行期（函数被调用时）
主文件早已执行完，属性一定在。

## 什么**留在** Agent 本类（不是漏搬）

    `self._session_states`  它是**实例状态**（一个有界注册表），构造在 `__init__`
    9 个同名薄壳            `self.` 查找是 monkeypatch 的通道（见下）

★ 薄壳必须保留 `self.` 查找并把能力**作为参数**传进来：`tests/test_hitl_wiring.py`
  用 `singleton._last_products = lambda …` 打在**实例**上；若薄壳绕过 `self.`
  直接引用模块函数，补丁静默失效（测试照绿，但测的不是真路径）。
"""

from typing import List, Optional

from core.logger import get_logger

from modules.product_research import agent_product_research as _pr

logger = get_logger("product_research.session")

# 会话级状态的**默认作用域**（没有 context_id 时用它）。
#
# ★ 为什么这个字符串是常量而不是就地写的字面量：它同时出现在「取容器」
#   （`session`）与「算落盘键」（`state_key`）两处。两处各写一份字面量，
#   改名时漏一处就会让「有会话」与「无会话」两条路径撞进同一个容器 ——
#   而那种错误只在单会话场景下不显形。
_DEFAULT_STATE_SCOPE = "_default"


def state_scope(context_id: Optional[str] = None, *, resolve_thread_id) -> str:
    """
    当前请求的**状态作用域** —— 唯一一份口径，`session()` 与
    `hydrate_state()` / `flush_state()` 三方共用它。

    · 有会话 + 有身份 ⇒ `resolve_thread_id()`（= checkpointer 的 thread_id）
    · 只有会话（单测 / 未登录）⇒ 会话 ID 本身，**纯内存、不落库**
    · 无会话 ⇒ `_default`，同样不落库

    ★★ 为什么不自己拼一份键：状态与 checkpoint 描述的是"同一个会话"。
       两处各拼一份必然漂移，而漂移的表现是「历史还在、槽位没了」——
       两边都不报错。第 138 轮的 `X-Shop-ID` 事故正是"同一概念两套 ID 空间"。

    ★ 只读 ContextVar（由 `bind_context` 写入），不接受 user_id 入参：
       入参与 ContextVar 是**两个真源**，测试把 `bind_context` 换掉之后
       两者就会分叉（hydrate 读 A、业务写 B），而那种错不报错、只丢状态。
    """
    if not context_id:
        return _DEFAULT_STATE_SCOPE
    user_id = _pr._current_user_id.get()
    if user_id:
        return resolve_thread_id(context_id, user_id)
    return context_id


def state_key(context_id: Optional[str] = None, *, resolve_thread_id) -> tuple:
    """
    返回 `(内存作用域, 落盘键)`；落盘键为 `None` ⇒ 本次不落库。

    ★ 把「作用域」与「要不要落库」放在**同一个函数**里算：它们必须同源。
      分两处判断迟早出现「hydrate 用 A 键、flush 用 B 键」—— 同样不报错。
    """
    scope = state_scope(context_id, resolve_thread_id=resolve_thread_id)
    persistable = bool(context_id and _pr._current_user_id.get())
    return scope, (scope if persistable else None)


def session(context_id: Optional[str] = None, *, registry, resolve_thread_id):
    """
    取（必要时创建）该会话的状态容器（`ai_infra.session_state.SessionState`）。

    没有 context_id 时退化为 `_default` —— 单会话场景（含既有测试）仍可用；
    多会话并发下**必须由调用方传 context_id**，否则还是会串。

    ★ 作用域里带上身份：同一个 session_id 在不同身份下必须是两份状态。
      只按 context_id 分片，在"会话归谁"这件事上就完全依赖上游校验 ——
      而这条路径上没有第二道防线。
    """
    return registry.scope(state_scope(context_id, resolve_thread_id=resolve_thread_id))


async def hydrate_state(
    context_id: Optional[str] = None, *, registry, resolve_thread_id
) -> None:
    """
    入口：把该会话的状态从 PG 读回内存（无身份 / 无会话 ⇒ 空操作，零 DB 往返）。

    ★ 先补写、再读：上一轮可能**没写成功**（落盘失败，或流式生成器被客户端
      中断而 finally 里的 await 被取消）。那笔改动仍在内存容器里且标记为脏，
      而 `hydrate_state()` 对脏容器是"不覆盖"的 ⇒ 若不在入口先补写，
      这次请求就一直拿着内存那份，库里那份（更早的）永远回不来，
      而这笔改动也永远不出门。补写把两个方向都堵上。
    """
    scope, thread_id = state_key(context_id, resolve_thread_id=resolve_thread_id)
    state = registry.scope(scope)
    if thread_id is not None and state.is_dirty:
        await flush_state(
            context_id, registry=registry, resolve_thread_id=resolve_thread_id
        )
    await _pr._hydrate_session_state(
        state, owner_id=_pr._current_user_id.get(), thread_id=thread_id
    )


async def flush_state(
    context_id: Optional[str] = None, *, registry, resolve_thread_id
) -> None:
    """
    出口：把内存里未落盘的改动写回 PG（无改动 ⇒ 空操作）。

    ★ 这里再包一层 try/except：`persist_state()` 自己已经吞掉了 DB 异常，
      但**生成器被关闭**（客户端断流 / `aclose()`）时，`finally` 里的 await
      还可能抛 `RuntimeError`（事件循环正在关）。那种异常不该从 finally 里
      冒出来，把一次已经生成完的回答变成错误页 —— 状态没写上是小损失，
      把回答炸掉是大的。
    """
    scope, thread_id = state_key(context_id, resolve_thread_id=resolve_thread_id)
    if thread_id is None:
        return
    try:
        await _pr._persist_session_state(
            registry.scope(scope),
            owner_id=_pr._current_user_id.get(),
            thread_id=thread_id,
            session_id=context_id,
        )
    except Exception as e:  # noqa: BLE001 —— 见 docstring
        logger.warning(f"[product_research] 会话状态落盘跳过：{e}")


def last_products(
    context_id: Optional[str] = None, *, registry, resolve_thread_id
) -> List[dict]:
    """该会话上一轮蓝海产出的候选商品（没有则空列表）。"""
    cached = session(
        context_id, registry=registry, resolve_thread_id=resolve_thread_id
    ).get("last_blue_ocean") or {}
    return cached.get("products") or []


def last_blue_ocean(*, registry, resolve_thread_id) -> Optional[dict]:
    """
    默认会话的蓝海结果（**兼容旧引用的只读别名**；新代码请用 `last_products(context_id)`）。

    保留它是因为既有测试与 `session_context_block` 按「单会话」语义书写。
    """
    return session(
        None, registry=registry, resolve_thread_id=resolve_thread_id
    ).get("last_blue_ocean")


def bind_context(
    context_id: Optional[str],
    shop_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    把会话 ID、**已校验的**店铺 ID 与**身份**绑定到 ContextVar。

    三个值都由**服务端**在入口写入，用途各不相同：
      · `context_id` —— tools.py 靠它找到本会话的状态（`session()`）；
      · `shop_id`    —— `_write_candidates` 的写入归属，必须是已校验的值；
      · `user_id`    —— 会话状态的**作用域**键（`state_scope()`）。
        漏传的后果不是「少记一点」，而是状态落到另一个作用域下 ——
        表现为「刚补的槽位下一轮又不见了」，且没有任何报错。

    `shop_id` 绝不能是原始请求头 —— 详见 `_current_shop_id` 的注释。

    **有意不 reset**：每个请求是独立的 asyncio Task，ContextVar 天然按 Task 隔离，
    且下一次调用会覆盖 —— 这样可省掉「用 try/finally 缩进整个 async 生成器体」。
    """
    _pr._current_context_id.set(context_id)
    _pr._current_shop_id.set(shop_id)
    _pr._current_user_id.set(user_id)


def session_context_block(
    context_id: Optional[str] = None, *, registry, resolve_thread_id
) -> str:
    """
    给「对话类」LLM 回复注入**本轮会话语境**。

    为什么必须注入：general 分支原先把 query 裸丢给 LLM —— 只给了角色提示词，
    既没有上下文也没有工具。LLM 手里没有任何真实数据，只能照着 system prompt 里
    「数据驱动 / 趋势洞察 / 风险意识」的骨架**编通用知识**：实测编出了
    「Google Trends 搜索热度较高」「CE、FCC 认证」「液体容器国际运输限制」
    这类放之四海皆准的套话，读起来像通用聊天机器人而不是选品助手。

    注意这跟「有没有接 LLM」无关 —— LLM 接了，但没给它干活的条件。
    把真实候选商品摆到它面前，它才答得出「你要入库的是不是这个」。
    """
    lines: List[str] = []
    products = last_products(
        context_id, registry=registry, resolve_thread_id=resolve_thread_id
    )

    if products:
        lines.append("")
        lines.append("【本轮会话上下文】")
        lines.append("上一轮蓝海挖掘产出的候选商品（用户说「这个 / 那个 / 第 N 个」时指的是这些）：")
        for i, p in enumerate(products[:10], 1):
            lines.append(
                f"  {i}. {p.get('title') or '未命名'}（{p.get('asin') or '无 ASIN'}）"
                f" 售价 ${float(p.get('price') or 0):.2f}"
                f" ｜ 预估 ROI {p.get('roi') or 0}%"
            )

    lines.append("")
    lines.append("【输出约束】")
    lines.append(
        "1. 只依据上面的真实数据和用户原话回答；"
        "**严禁编造**搜索趋势、销量、专利、认证、物流限制等外部数据。"
        "拿不到的数据就说拿不到，并告诉用户该走哪个分析动作。"
    )
    lines.append(
        "2. 你**没有执行任何写操作**。若用户想入库但目标商品不在上面、也没给 ASIN，"
        "直接追问要入库哪一个（让他给 ASIN 或商品标题），不要替他猜、也不要假装已完成。"
    )
    return "\n".join(lines)
