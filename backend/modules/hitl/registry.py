# -*- coding: utf-8 -*-
"""审批 resume 通道的**分发表** —— 把「哪个 Agent 能续跑审批」收成一张可对账的表。

## 为什么需要一张表

第 399 轮发现：`POST /api/v1/product-research/approval/resume` 是**唯一**的
resume 端点。于是「有审批工具」与「能点批准」这两件事，在客服身上是脱节的：
`create_ticket` 会 `interrupt()` 把图画停，而没有任何端点能把它放行 ⇒
生产上永远抛 `HITLPrerequisiteError`。

改成通用端点 `POST /api/v1/agents/{agent}/approval/resume` 后，服务端必须回答
「这个 agent 由谁续跑」。三种做法：

  · 注册表（`register(agent_id, fn)` + 各模块 import 时副作用注册）——
    注册点必须住包 `__init__`，而这里要注册的是**业务模块**，
    必然反向依赖 `modules.*` ⇒ 循环 import；
  · 反射（按 agent 名拼模块路径）—— 名字一改就静默 404，
    且拼错时看起来像"这个 agent 不支持审批"；
  · **静态表 + 惰性 import**（本文件的做法）—— 表是唯一真源，
    漏写会在**启动后第一次点击**时暴露成 501，且能被门禁静态扫出来。

## 门禁（这是本表存在的另一半理由）

`tests/test_hitl_layer_shape.py` 断言：

    「装配了含副作用工具（`EXPECTED_GATED`）的 Agent 集合」
        ==  「本表覆盖的 agent 集合」

⇒ 以后谁给某个 Agent 加了写工具、却没在这里登记 resume 通道，
  门禁直接红。这正是第 399 轮那条洞（客服有写工具、无 resume）的**可执行版本**。
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

__all__ = [
    "ResumeSpec",
    "RESUME_SPECS",
    "canonical_agent_id",
    "get_resumer",
    "supported_agents",
]


@dataclass(frozen=True)
class ResumeSpec:
    """一个 Agent 的 resume 能力登记。

    Attributes:
        module: service 模块的**完整路径**（惰性 import，避免启动期拉起全部业务）。
        attr:   该模块里可直接 await 的 callable；签名统一为
                `(context_id, decision, *, shop_id, user_id, reason, args, feedback)`。
        aliases: 客户端可能使用的其它写法（前端 id / 业务类名 / 中文名）。
                 ★ 别名只做**输入归一化**，不是权限：都指向同一个 spec。
    """

    agent_id: str
    module: str
    attr: str
    aliases: Tuple[str, ...] = ()


#: ★ 唯一真源。加一个 Agent 的审批能力 = 在 service 里实现 `resume_approval`
#:   再在这里加一行；两处都对不上时，门禁会在 `test_hitl_layer_shape.py` 里红。
RESUME_SPECS: Tuple[ResumeSpec, ...] = (
    ResumeSpec(
        agent_id="product-research",
        # ★ `attr` 支持点号路径：这两个 Agent 的 resume 都不是**模块级函数** ——
        #   选品放在模块级单例 `product_research_service` 上，
        #   客服是 `CustomerServiceService` 的 staticmethod。
        #   写成模块级函数名会得到 AttributeError，而那要到**用户点批准那一刻**
        #   才炸（惰性 import），所以 `test_hitl_closed_loop.py` 里有一条
        #   「真 import 一次并检查签名」的判据把它提前到 CI。
        module="modules.product_research.service",
        attr="product_research_service.resume_approval",
        aliases=("product_research", "ProductResearcher"),
    ),
    ResumeSpec(
        agent_id="customer-service",
        module="modules.customer_service.service",
        attr="CustomerServiceService.resume_approval",
        aliases=("customer_service", "智能客服", "agent_cs"),
    ),
    ResumeSpec(
        # ★ 第 400 轮 P0-3：店秘书没有**写工具**，但有 `ask_clarification` ——
        #   它的 `interrupt()` 停的是同一张图。批不批是另一回事，
        #   「图停住了要人」这件事是同一套机制 ⇒ 同一个 resume 通道。
        #   （`test_gated_tools_owner_has_resume_channel` 只要求"有写工具的
        #     Agent 必须有通道"，不禁止"没写工具但有提问工具的也有通道"。）
        agent_id="secretary",
        module="modules.secretary.agent",
        attr="resume_clarification",
        aliases=("店秘书", "orchestrator"),
    ),
)

_ALIAS_INDEX: Dict[str, ResumeSpec] = {}
for _spec in RESUME_SPECS:
    _ALIAS_INDEX[_spec.agent_id] = _spec
    for _a in _spec.aliases:
        _ALIAS_INDEX.setdefault(_a, _spec)


def canonical_agent_id(raw: str) -> Optional[str]:
    """把客户端传来的 agent 标识归一成 `RESUME_SPECS` 的 `agent_id`。

    归一规则：去空白 → 精确命中别名表 → 否则把 `_` 换成 `-` 再试一次
    （前端惯用 kebab-case、后端惯用 snake_case）。

    返回 `None` 表示**这个 agent 没有登记 resume 通道** —— 调用方必须把它
    区分为 404/501，而不是当成"内部错误"。
    """
    if not raw:
        return None
    key = raw.strip()
    if not key:
        return None
    spec = _ALIAS_INDEX.get(key) or _ALIAS_INDEX.get(key.replace("_", "-"))
    return spec.agent_id if spec else None


def get_resumer(agent_id: str) -> Optional[Callable[..., Any]]:
    """按 `agent_id` 取到可 await 的 resume callable（惰性 import）。

    ★ 为什么不在模块顶层 import：`modules.product_research.service` 会拉起
      整个选品链（含 LLM 客户端与平台取数）。本条路径在**启动期**不该触发它。
    ★ import 失败**不吞**：让调用方看到 500 与真实异常，
      而不是伪装成"这个 agent 不支持审批"。
    """
    spec = _ALIAS_INDEX.get(agent_id) or _ALIAS_INDEX.get(agent_id.replace("_", "-"))
    if spec is None:
        return None
    mod = importlib.import_module(spec.module)
    # `attr` 可以是点号路径（`instance.method` —— 见 `RESUME_SPECS` 的注释）
    obj: Any = mod
    for part in spec.attr.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            raise AttributeError(
                f"{spec.module}.{spec.attr} 不存在 —— resume 登记表与实现已经漂移"
            )
    return obj


def supported_agents() -> Iterable[str]:
    """本表覆盖的规范 agent_id（门禁与 `GET /agents` 用）。"""
    return (s.agent_id for s in RESUME_SPECS)
