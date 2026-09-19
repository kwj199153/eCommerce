# -*- coding: utf-8 -*-
"""读口门禁：长期记忆**真的**进了 system prompt（第 152 轮 · 批 C2 读口）。

背景（r141 的逐字判词）
======================
> C2 `MemoryEvolution` 落实 | 要么接真后端，要么下线；**不能留一个假页面承诺
> 「每晚自动整理」**

第 149 轮把写入侧补齐（三张表 + 服务 + HTTP + 每晚 Celery 任务），但
**「记了」与「用了」是两件事**：一份每晚更新、却从不影响模型回答的记忆，
与一份不存在的记忆，对用户完全等价 —— 只是前者更贵。
本文件把「真的被用了」钉成可执行断言。

四类判据
========
A. **机制层不带内容** —— 注册表在 `ai_infra` 的定义处必须是空 dict；
   全仓 `register_prompt_section(...)` 的**调用点**恰好 1 个，且在业务模块里。
B. **接线不能断** —— ① 门面 import 那一行必须在（注册是 import 副作用，
   没有它注册永不发生）；② `_llm_call_node` 真的 await 收集、且结果经
   `_system_prompt_with_plan(sections=...)` 进 `SystemMessage`；
   ③ **关规划时附加段落也必须注入**（第 152 轮修掉的真缺陷）。
C. **三态真跑（真库）** —— 匿名 ⇒ 不注入；开关关闭 ⇒ 不注入；有条目 ⇒ 注入，
   且**只注入自己的**（读口是一条新的读取通道 ⇒ 新的越权面）。
D. **失败隔离且可观测** —— 单段 provider 抛异常不拖垮整轮、其余段落照常、
   `failed` 里**点名**；重名注册必须当场报错。

★ 为什么 B 组用 AST 而不是运行时断言
  「import modules.memory 之后注册表里有它」在全量跑里**恒真**（别的用例早就
  import 过了）—— 顺序敏感的真值等于没有判据。运行时断言只保留一条
  （`test_facade_import_actually_registers`），机制由 AST 钉。
  ★ 本仓已被 docstring / 注释骗过四次 ⇒ 形态判据一律走 AST，不数字符串。

★ 反向注入已验（`.workbuddy/probes/r152_reverse_inject.py`，6 条变异 + 1 条
  「不该红」对照）。对照那一侧证明：本文件与 `test_memory_distill.py` 的
  分层门禁**互补而非重复** —— 把提示词换成「中性默认值」不会触发业务词扫描。
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SECTIONS_MOD = BACKEND / "ai_infra" / "prompt_sections.py"
BASE_AGENT_PY = BACKEND / "ai_infra" / "base_agent.py"
MEMORY_PKG = BACKEND / "modules" / "memory"
FACADE_PY = MEMORY_PKG / "__init__.py"
PROMPT_SECTION_PY = MEMORY_PKG / "prompt_section.py"

SECTION_NAME = "long_term_memory"


def _src(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==========================================================================
# A. 机制层不带内容
# ==========================================================================


def test_prompt_section_registry_is_empty_by_default():
    """★ 注册表在机制层的**定义处**必须是空 dict（内容全归业务模块）。

    ★ 为什么扫 AST 而不是运行时读 `_SECTIONS`：运行时值取决于
      「本进程里谁先 import 了业务模块」—— 那是一条顺序敏感的假判据。
      判据形态与 `ai_infra.llm.PROMPT_TEMPLATES` 那条完全同源。
    """
    tree = ast.parse(_src(SECTIONS_MOD))
    for n in tree.body:
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "_SECTIONS":
            assert isinstance(n.value, ast.Dict) and not n.value.keys, (
                "ai_infra 的段落注册表不得预置内容 —— 语料住进基础设施层就是 L3 泄漏"
            )
            return
    pytest.fail("prompt_sections 里没有 `_SECTIONS` 的定义")


def registration_calls_in(source: str) -> list:
    """源码里 `register_prompt_section(...)` 的**调用**行号（不数 import）。"""
    out = []
    for n in ast.walk(ast.parse(source)):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "register_prompt_section"
        ):
            out.append(n.lineno)
    return out


def test_registration_has_exactly_one_call_site_in_business_layer():
    """注册只允许发生在**一个**业务模块里。

    ★ 为什么必须唯一：注册是 import 副作用，散落多处就「谁注册了什么」不可数；
      而且重名会被第二次注册撞成 `ValueError` —— 那意味着**进程启动失败**，
      代价远大于「少注入一段」。
    """
    sites = []
    for base in (BACKEND / "ai_infra", BACKEND / "modules"):
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            # ★ 用 as_posix() 归一化分隔符：Windows 上 `relative_to` 给的是
            #   `modules\memory\x.py`，下面那条 startswith 会**假红**。
            rel = p.relative_to(BACKEND).as_posix()
            for line in registration_calls_in(_src(p)):
                sites.append(f"{rel}:{line}")

    assert len(sites) == 1, f"注册调用点必须恰好 1 个，实测 {sites}"
    assert sites[0].startswith("modules/memory/prompt_section.py:"), (
        f"注册必须落在业务模块 modules/memory/prompt_section.py，实测 {sites[0]}"
    )


def test_registration_scanner_is_not_vacuous():
    """★ 门禁自检：扫描函数必须能报出违规，也必须**不把 import 当调用**。

    只 import 不调用 = 「挂端点」的前一步，还没接线 —— 若把它算成调用点，
    这条门禁就会在「只是导入了但没注册」的实现上**恒绿**。
    """
    assert registration_calls_in("register_prompt_section('a', p)\n") == [1]
    assert registration_calls_in("from x import register_prompt_section\n") == [], (
        "只 import 不调用被算成了调用点 ⇒ 门禁会在未接线时恒绿"
    )
    assert registration_calls_in("def register_prompt_section(a, b):\n    pass\n") == [], (
        "函数定义被算成了调用点"
    )


# ==========================================================================
# B. 接线不能断
# ==========================================================================


def test_facade_imports_the_prompt_section_module():
    """★ 「谁负责 import，从而触发注册」必须是**可查的一行**。

    注册是 import 副作用 ⇒ 这一行没了，注入就静默失效：不报错、日志全绿、
    模型只是永远不知道用户的偏好。所以它必须被一条断言钉住。
    """
    tree = ast.parse(_src(FACADE_PY))
    found = any(
        isinstance(n, ast.ImportFrom)
        and n.level == 1
        and not (n.module or "")
        and any(a.name == "prompt_section" for a in n.names)
        for n in ast.walk(tree)
    )
    assert found, (
        "modules/memory/__init__.py 没有 import prompt_section ⇒ 注册永不发生。"
        "（放在门面而不是 router：任何不走 HTTP 的进程也要能注册）"
    )


def test_facade_import_actually_registers():
    """运行时对账：走门面 ⇒ 注册表里真的有那一段。"""
    import modules.memory  # noqa: F401  —— import 本身就是要验证的动作
    from ai_infra.prompt_sections import registered_sections

    assert SECTION_NAME in registered_sections(), (
        f"import 了门面但注册表里没有 {SECTION_NAME}：{registered_sections()}"
    )


def _func(tree: ast.AST, name: str):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def test_llm_call_node_collects_and_passes_sections_into_system_message():
    """★★ 「收集了」与「用了」是两件事 —— 必须同时钉住。

    只 await 收集而不把结果拼进 prompt，是最容易发生的一种**假接线**：
    代码看起来做了这件事（有调用点），行为上什么都没变（模型看不到）。
    """
    fn = _func(ast.parse(_src(BASE_AGENT_PY)), "_llm_call_node")
    assert fn is not None, "找不到 _llm_call_node"

    collected_var = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Await):
            call = n.value.value
            if (
                isinstance(call, ast.Call)
                and getattr(call.func, "id", "") == "collect_prompt_sections"
            ):
                collected_var = getattr(n.targets[0], "id", None)
    assert collected_var, (
        "_llm_call_node 里没有 `x = await collect_prompt_sections(...)` ⇒ 段落没被收集"
    )

    ok = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "SystemMessage":
            un = ast.unparse(n)
            if collected_var in un and "sections=" in un:
                ok = True
    assert ok, (
        f"collect 的结果（{collected_var}）没有经 "
        f"`_system_prompt_with_plan(state, sections=...)` 进 SystemMessage "
        f"⇒ 收集了却没用（假接线）"
    )


def test_user_identity_comes_from_server_context_not_state():
    """★ 身份只能取自服务端上下文，不得出自 `state` / 工具入参。

    工具入参由 LLM 生成，塞不进身份；`state` 里的东西可被调用方影响。
    读口的归属若走错源，就是一条新的越权面（同族教训：`X-Shop-ID` 曾指两种 ID 空间）。
    """
    fn = _func(ast.parse(_src(BASE_AGENT_PY)), "_llm_call_node")
    src = ast.unparse(fn)
    assert "current_user_id()" in src, "注入用的身份不是从 current_user_id() 取的"
    assert "PromptContext(" in src, "没有构造 PromptContext"


def test_sections_survive_without_planning():
    """★★ 第 152 轮修掉的真缺陷：**未开规划时附加段落也必须注入**。

    原实现是 `if not self.enable_planning: return self.system_prompt` ——
    任何后来加的段落都会在那个早退分支上**静默消失**：未开规划的 Agent 上
    记忆永远不注入，而日志全绿、门禁全绿（这正是「静默」最难发现的地方）。

    ★ 反面也钉住：没有段落时不得凭空多出内容（否则等于给每个 Agent
      加了一段空标题）。`test_agent_plan.py` 已有「关闭规划时原样返回」的断言，
      这里补的是**关规划 + 有段落**这一档。
    """
    from ai_infra.base_agent import BaseAgent

    biz = "你是助手。"
    off = BaseAgent(agent_name="r152-off", system_prompt=biz, enable_planning=False)
    marker = "【长期记忆】偏好：报价一律按到岸价口径"

    got = off._system_prompt_with_plan({}, sections=marker)
    assert marker in got, "关规划时附加段落被丢掉了（早退分支又回来了）"
    assert biz in got and got.index(biz) < got.index(marker), "段落必须排在业务提示词之后"

    assert off._system_prompt_with_plan({}, sections="") == biz, (
        "没有段落时不该凭空多出内容"
    )


# ==========================================================================
# C. 三态真跑（真库）
# ==========================================================================


@pytest_asyncio.fixture
async def mem_owner():
    """一个干净的 `owner_id`；用完清掉三张表。

    ★ 三张表对 `users` 都**没有外键**、也从不带 `shop_id` ⇒ 仓里那两把
      「按 user / 按 shop」的清理扫帚都扫不到它们。不自己清，开发库里会越堆越多。
    """
    created: list = []

    def _make(tag: str = "") -> str:
        oid = f"r152{uuid.uuid4().hex[:18]}{tag}"
        assert len(oid) <= 36, "owner_id 列是 String(36)"
        created.append(oid)
        return oid

    yield _make

    if not created:
        return
    from core.database import get_async_session

    async with get_async_session() as db:
        for oid in created:
            for table in ("memory_entries", "memory_logs", "memory_profiles"):
                await db.execute(
                    text(f"DELETE FROM {table} WHERE owner_id = :o"), {"o": oid}
                )
        await db.commit()


async def test_no_identity_means_no_injection():
    """匿名 ⇒ 不注入，且**不抛错**。

    ★ 这里是读口与 HTTP 面的**有意分歧**：`_require_owner` 对 HTTP 面抛 401
      （用户点保存必须知道为什么没存上）；读口跑在图节点里，抛异常 ⇒
      整轮对话挂掉。而"这个人没有记忆"是完全正常的状态。
    """
    from ai_infra.prompt_sections import PromptContext
    from modules.memory.prompt_section import memory_prompt_section
    from modules.memory.service import load_injectable_entries

    for empty in (None, "", "   "):
        got = await load_injectable_entries(empty)
        assert got.injectable is False and got.entries == [], f"{empty!r} 竟然可注入"
        assert await memory_prompt_section(PromptContext(user_id=empty)) == ""


async def test_switch_off_means_no_injection(mem_owner):
    """★★ 开关必须真的管住注入。

    本包 docstring 承诺「关掉之后**任务跳过**、**注入块为空**」——
    前半句在 `tasks` 里，后半句在**读口出现之前根本没有实现**。
    只调 `load_entries`（不过开关）的实现会在这里转红。
    """
    from ai_infra.prompt_sections import PromptContext
    from modules.memory import service as S
    from modules.memory.prompt_section import memory_prompt_section

    oid = mem_owner()
    await S.save_memory(
        oid, "# 运营偏好\n\n- 定价按 25% 毛利倒推，不参与低价内卷\n",
        source=S.SOURCE_MANUAL,
    )

    on = await S.load_injectable_entries(oid)
    assert on.injectable is True and len(on.entries) == 1, on
    assert "25% 毛利" in await memory_prompt_section(PromptContext(user_id=oid))

    await S.set_enabled(oid, False)
    off = await S.load_injectable_entries(oid)
    assert off.injectable is False and off.entries == [], "开关关了却仍然「可注入」"
    assert await memory_prompt_section(PromptContext(user_id=oid)) == "", (
        "开关关了却仍然注入了内容 —— 那个开关就是装饰品"
    )

    await S.set_enabled(oid, True)
    back = await S.load_injectable_entries(oid)
    assert back.injectable is True and len(back.entries) == 1, (
        "重新打开开关后条目必须还在（关开关不该删数据）"
    )


async def test_injection_is_scoped_to_its_owner(mem_owner):
    """★★ 只注入自己的记忆。

    读口是一条**新的读取通道** ⇒ 新的越权面。本仓最贵的教训就是
    「按 `owner_id` 过滤必须在服务端做、且只允许有一处实现」。
    """
    from ai_infra.prompt_sections import PromptContext
    from modules.memory import service as S
    from modules.memory.prompt_section import memory_prompt_section

    a, b = mem_owner("-a"), mem_owner("-b")
    await S.save_memory(a, "# 运营偏好\n\n- 甲只做北美站\n", source=S.SOURCE_MANUAL)
    await S.save_memory(b, "# 运营偏好\n\n- 乙只做东南亚站\n", source=S.SOURCE_MANUAL)

    block_a = await memory_prompt_section(PromptContext(user_id=a))
    block_b = await memory_prompt_section(PromptContext(user_id=b))

    assert "甲只做北美站" in block_a and "乙只做东南亚站" not in block_a, (
        "A 的注入块里出现了 B 的记忆"
    )
    assert "乙只做东南亚站" in block_b and "甲只做北美站" not in block_b


async def test_injection_block_respects_the_char_budget(mem_owner, monkeypatch):
    """注入块必须走**机制层的硬上限**，而不是把整份记忆塞进 prompt。

    ★ 判据用**注入式**（把上限改小）而不是手工造 60 条：
      造数据只能证明「这一次没超」，把上限调小才能证明
      「上限真的被传下去了」—— 后者才是接线判据。
    """
    from ai_infra.prompt_sections import PromptContext
    from modules.memory import prompt_section as PS
    from modules.memory import service as S

    oid = mem_owner()
    body = "# 运营偏好\n\n" + "\n".join(
        f"- 第 {i} 条长期偏好，内容是刻意写长的一段描述" + "长" * 30 for i in range(12)
    )
    await S.save_memory(oid, body + "\n", source=S.SOURCE_MANUAL)

    monkeypatch.setattr(PS, "MAX_PROMPT_CHARS", 120)
    block = await PS.memory_prompt_section(PromptContext(user_id=oid))

    assert block, "上限调小后不该整块消失（机制层有「连一条都放不下」的显式说明）"
    assert len(block) <= 200, f"注入块没有遵守传下去的上限：{len(block)} 字"
    assert ("只注入前" in block) or ("未能注入" in block), (
        "截断了却不说 —— 模型与排查者都会以为这就是全部记忆"
    )


# ==========================================================================
# D. 失败隔离 / 重名
# ==========================================================================


async def test_provider_failure_is_isolated_and_visible():
    """★★ 单段失败 ⇒ 不抛给上层、其余段落照常、`failed` 里**点名**。

    ★ 为什么这不算「静默失败」：`failed` 是**返回给调用方**的，
      `BaseAgent` 据此记一条带 agent 名的 WARNING ⇒
      「注入了几段 / 失败了几段」在日志里是可读的差异。
      反过来说：如果这里吞掉异常又只返回空元组，那才是静默失败。
    """
    from ai_infra.prompt_sections import PromptContext, collect_prompt_sections

    async def _boom(_ctx):
        raise RuntimeError("provider 炸了")

    async def _ok(_ctx):
        return "某段正常内容"

    got = await collect_prompt_sections(
        PromptContext(), registry={"z_bad": _boom, "a_ok": _ok}
    )
    assert got.blocks == ("某段正常内容",), "一段失败把整次收集带崩了"
    assert got.failed == ("z_bad",), "失败没有被点名 ⇒ 与「本来就没有内容」不可分"


async def test_duplicate_registration_is_rejected():
    """重名注册必须当场报错，不能静默覆盖。

    静默覆盖的后果是「先注册的那一段**不再注入**」，且两边都不报错、
    没有任何日志 —— 正是本仓反复出现的那类缺陷。
    """
    import modules.memory  # noqa: F401  —— 确保业务层已注册
    from ai_infra.prompt_sections import register_prompt_section

    async def _p(_ctx):
        return "x"

    with pytest.raises(ValueError):
        register_prompt_section(SECTION_NAME, _p)

    with pytest.raises(ValueError):
        register_prompt_section("   ", _p)

    with pytest.raises(TypeError):
        register_prompt_section("r152-not-callable", "字符串不是提供者")


# ==========================================================================
# E. 端到端：唯一一条「整条链路接在一起」的证据
# ==========================================================================


async def test_llm_call_node_actually_injects_memory(mem_owner, monkeypatch):
    """★★ 真库 + 假 LLM：记忆**真的到了**模型的 system prompt 里。

    前面各条分别证明「注册了」「读得到」「收集了」「拼得进去」；
    只有这一条证明它们**接在一起**（历史上真实出现过「每一环都有测试、
    连起来却什么都没发生」的形态）。

    ★ 假 LLM 只替换**最外层**（`_llm_with_tools`），采集节点与身份链路都走真的。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from ai_infra import base_agent as BA
    from modules.memory import service as S

    oid = mem_owner()
    await S.save_memory(
        oid, "# 沟通偏好\n\n- 回复一律先给结论、再给依据\n", source=S.SOURCE_MANUAL
    )

    captured: dict = {}

    class _CapturingLLM:
        async def ainvoke(self, messages, **kwargs):
            captured["system"] = messages[0].content
            captured["n"] = len(messages)
            return AIMessage(content="好的")

    agent = BA.BaseAgent(agent_name="r152-e2e", system_prompt="你是助手。")
    monkeypatch.setattr(agent, "_llm_with_tools", lambda: _CapturingLLM())
    monkeypatch.setattr(BA, "current_user_id", lambda: oid)

    await agent._llm_call_node(
        {"messages": [HumanMessage(content="在吗")], "todos": [], "budget": {}}
    )

    system = captured.get("system", "")
    assert system, "假 LLM 没被调用 ⇒ 用例空跑"
    assert "先给结论、再给依据" in system, (
        f"记忆没有进 system prompt。实际收到：{system[:200]!r}"
    )
    assert "你是助手。" in system, "业务提示词丢了"


async def test_llm_call_node_does_not_inject_for_anonymous(monkeypatch):
    """★ 端到端反面：匿名时 system prompt 里**不能**出现任何注入块。

    ★ 这条防的是「把归属判空写错方向」：一旦 provider 在拿不到身份时
      回退到某个默认 owner（或空串 owner 也有数据），匿名用户就会看到
      别人的记忆 —— 那是数据泄漏，而且不会有任何报错。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from ai_infra import base_agent as BA

    captured: dict = {}

    class _CapturingLLM:
        async def ainvoke(self, messages, **kwargs):
            captured["system"] = messages[0].content
            return AIMessage(content="好的")

    agent = BA.BaseAgent(agent_name="r152-anon", system_prompt="你是助手。")
    monkeypatch.setattr(agent, "_llm_with_tools", lambda: _CapturingLLM())
    monkeypatch.setattr(BA, "current_user_id", lambda: "")

    await agent._llm_call_node(
        {"messages": [HumanMessage(content="在吗")], "todos": [], "budget": {}}
    )

    system = captured.get("system", "")
    assert system
    assert "【长期记忆】" not in system, "匿名请求被注入了记忆"
