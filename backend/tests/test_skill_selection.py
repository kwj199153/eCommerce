# -*- coding: utf-8 -*-
"""点名通道：用户点了一条技能，Agent 必须**按它执行**（第 188 轮）。

==============================================================================
★★★ 这条通道补的是什么
==============================================================================
第 181 轮建的技能机制只有**一条**取用路径：把「技能目录」注入 system prompt，
由**模型自己**判断该用哪条、再调 `load_skill(name)` 取全文（渐进披露两级）。

那条路径的前提是「模型自己挑」。但界面上还给了一个能力：用户直接点一张快捷
卡片 —— 那意味着**他已经挑好了**。此时若仍只走目录那条路，等于把用户的显式
选择降级成一条建议：模型完全可能挑另一条，或者干脆不加载。

本文件把「点名的技能真的按用户所愿生效」钉成可执行断言。

==============================================================================
★★★ 这条链路上的四个**静默**失败点（本文件的判据就是逐个封它们）
==============================================================================
    四处共同特征：代码看起来对、日志全绿、门禁全绿，唯一表现是
    「用户点了技能，但模型根本没按它做」。

① **注册永不发生** —— `skills_selected` 段落靠 import 副作用登记
   （`provider.py` 末尾 import `selected_skill_section`）。删掉那一行 ⇒
   十三个端点照常、技能仓库页照常、目录注入照常，**但点名永不生效**，
   且没有任何一处报错。（对应 A 组，必须开**子进程**才证得动。）

② **取不到却静默退回空串** —— 这是本通道**特有**的失败模式。长期记忆那边
   「取不到 ⇒ 不注入」是对的（少一段增益）；点名这边「取不到 ⇒ 不注入」
   等于把用户的指令**悄悄丢掉**。所以三态必须分明：没点名 ⇒ 空串；
   点名且命中 ⇒ 抬头 + 正文；点名但取不到 ⇒ **显式说明**（对应 B 组）。

③ **写入点漏在生成器外** —— 流式端点的 body 是个 `async generator`，
   在路由里返回 `StreamingResponse` 时**还没被迭代**。把 `async with`
   包在外层，它在生成器第一次迭代之前就退出了 ⇒ 等于没设。
   判据用**代码形态**：`bind_requested_skill` 必须与它守护的那次对话调用
   **处在同一个最小包围函数**内（对应 D 组，反向注入可证会红）。

④ **两条通道各写一份过滤** —— `load_skill` 与点名段落都按名字取正文。
   两份实现 ⇒ 至少一份永远测不到；而漏掉的那份就是「知道名字就能读到
   未授权正文」。⇒ 必须共用 `provider.read_skill_text`（对应 C 组）。

==============================================================================
★ 为什么 D 组用「代码形态」而不是端点名单
==============================================================================
「13 个端点」是**当下的数字**，不是判据。名单式断言在两种真实改动下都会失效：
  · 新增一个对话端点、忘了接线 ⇒ 名单里没有它 ⇒ **恒绿**（正是要防的事）；
  · 重命名一个端点 ⇒ 名单对不上 ⇒ 红，但红的是"改名"而不是"漏接线"。
所以 D 组先从**代码形态**里把「谁是对话端点」推出来
（体内发起了 `<X>Service.chat` / `<X>.stream_chat` / `agent.invoke` /
`service.general_analysis` 这类调用），再断言**这些端点一个不漏地都接了线**。
另配一条数量断言防 detector 空转（空集会让"漏接线"这条恒绿）。
"""

from __future__ import annotations

import ast
import contextlib
import pathlib
import sys

import pytest
import pytest_asyncio

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SKILLS_INFRA = BACKEND / "ai_infra" / "skills.py"
PROVIDER_PY = BACKEND / "modules" / "skills" / "provider.py"
SELECTED_PY = BACKEND / "modules" / "skills" / "selected_skill_section.py"
SERVICE_PY = BACKEND / "modules" / "skills" / "service.py"

#: 段落名（契约的一部分：改名等于「旧名不再注入」）
SECTION_NAME = "skills_selected"

#: 端到端用例用的 Agent（必须是 `modules/skills/agents.py` 认得的名字，
#: 否则 `create_skill` 的 `enabledAgents` 校验会拒绝）。
AGENT = "ProductResearcher"


def _src(p: pathlib.Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


# ==========================================================================
# A. 注册真的发生了（防静默不注入）
# ==========================================================================


def _parent_map(tree: ast.AST) -> dict:
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_fn(parents: dict, node: ast.AST):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parents.get(cur)
    return None


def _find(tree: ast.AST, name: str, kind=(ast.FunctionDef, ast.AsyncFunctionDef)):
    for n in ast.walk(tree):
        if isinstance(n, kind) and n.name == name:
            return n
    return None


def _providing_fn(source: str, target: str):
    """在 `source` 里找「哪一行 import/注册了 `target`」，返回所在函数名或 'module'。"""
    tree = ast.parse(source)
    parents = _parent_map(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == target:
                    fn = _enclosing_fn(parents, n)
                    return fn.name if fn is not None else "module"
    return None


@pytest.mark.timeout(300)
def test_registration_trigger_is_load_bearing():
    """★★★ `provider.py` 末尾那行 import 是**功能性**的 —— 而不是风格问题。

    ★ 必须在**全新解释器**里做 before/after 对账。在测试会话内 import
      `modules.skills.router` 是**无法证伪**的：别的用例早就把它 import 过
      ⇒ 那句 import 变成 no-op 而注册表里确实有那一段，断言恒真。
      （同 `test_skill_injection.py::test_router_top_level_import_is_load_bearing`。）
    """
    which = _providing_fn(_src(PROVIDER_PY), "selected_skill_section")
    assert which == "module", (
        f"`modules/skills/provider.py` 里触发 `selected_skill_section` import 的位置是 "
        f"{which!r} —— 必须在**模块级**：注册是 import 副作用，藏在函数里就只在"
        f"被调到时才发生（而没人会调它）⇒ 点名通道静默失效。"
    )

    import json
    import os
    import subprocess

    probe = (
        "import json, os\n"
        "from ai_infra.prompt_sections import registered_sections\n"
        "before = list(registered_sections())\n"
        "import modules.skills.router  # noqa: F401,E402\n"
        "print('VERDICT:' + json.dumps({'before': before,\n"
        "                               'after': list(registered_sections())}))\n"
    )
    script = pathlib.Path(os.environ.get("TEMP", ".")) / "p188_child_probe.py"
    script.write_text(probe, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.startswith("VERDICT:")]
    assert lines, (
        f"子进程没有输出 VERDICT ⇒ 探针没跑起来。rc={proc.returncode}\n"
        f"stdout={(proc.stdout or '')[:800]!r}\nstderr={(proc.stderr or '')[:800]!r}"
    )
    v = json.loads(lines[-1][len("VERDICT:"):])

    assert v["before"] == [], (
        f"全新解释器里注册表**本应为空**，实际 {v['before']} —— 说明有别处抢先注册，"
        f"本用例无法证明那行 import 是必需的。请查 `test_memory_injection.py` 的调用点白名单。"
    )
    assert SECTION_NAME in v["after"], (
        f"import `modules/skills/router.py` 之后注册表里仍然没有 {SECTION_NAME}"
        f"（after={v['after']}）。\n"
        f"⇒ `provider.py` 末尾那句 import 被删了（或挪进函数里了）。\n"
        f"  后果：13 个端点、技能仓库页、目录注入全部照常，**但用户点名的技能永不生效**，"
        f"且没有任何一处会报错。"
    )


def test_install_also_registers_the_selected_channel():
    """`provider.install()` 幂等，且三条注册都只出现一次。

    ★ 为什么单列：两个注册表都对重名 raise（那是刻意的），而 `importlib.reload`
      是本仓测试的常规手段 ⇒ 少了"已装好就别再装"的判断，重载直接炸。
    """
    import modules.skills.provider as provider
    from ai_infra.prompt_sections import registered_sections
    from ai_infra.skills import registered_skill_readers

    provider.install()
    provider.install()

    assert list(registered_sections()).count(SECTION_NAME) == 1, registered_sections()
    assert list(registered_sections()).count("skills_catalog") == 1, registered_sections()
    assert list(registered_skill_readers()).count("db") == 1, registered_skill_readers()


# ==========================================================================
# B. 三态：没点名 / 命中 / 取不到（★ 取不到必须**显式**）
# ==========================================================================


def test_render_three_states():
    """★★★ 渲染层三态分明 —— 尤其「点名了但取不到」**绝不返回空串**。

    ★ 为什么这条是本文件最要紧的判据之一：返回空串等于把用户的指令悄悄丢掉。
      用户的观察是"点了技能，回答却跟没点一样"，而界面、日志、测试全绿。
    """
    from ai_infra.skills import SELECTED_SKILL_GUIDE, render_selected_skill_block

    # ① 没点名 ⇒ 空串（= 本次不需要这一段，注册表会丢掉它）
    assert render_selected_skill_block("", "正文") == ""
    assert render_selected_skill_block(None, "正文") == ""
    assert render_selected_skill_block("   ", "正文") == ""

    # ② 命中 ⇒ 抬头 + 正文原样
    hit = render_selected_skill_block("alpha", "# 技能：Alpha\n\n第一步：……")
    assert "第一步：……" in hit
    assert SELECTED_SKILL_GUIDE in hit
    assert hit.count("# 技能：Alpha") == 1, "正文自带标题，不应再叠一层标题"

    # ③ 取不到 ⇒ **非空** + 点名了技能名 + 含可读的不可用说明
    for empty in ("", "   ", None):
        miss = render_selected_skill_block("alpha", empty)
        assert miss.strip(), (
            f"点名了技能但取不到（text={empty!r}），渲染结果却是空 —— "
            f"用户的选择被静默丢弃，且没有任何一处会报错。"
        )
        assert "alpha" in miss, "取不到时没有点名是哪个技能，模型无法如实告知用户"
        assert SELECTED_SKILL_GUIDE in miss
        assert miss != hit

    # ④ 三态互不相等（防"三态被压成两态"）
    assert len({render_selected_skill_block("", "x"),
                render_selected_skill_block("a", "x"),
                render_selected_skill_block("a", "")}) == 3


async def test_contextvar_bind_and_restore():
    """★★ ContextVar 的绑定语义：作用域内可见、退出无条件复位、空值归一化。

    ★ 「退出复位」不是洁癖：ContextVar 会顺着任务继承下去 —— 一次请求设过之后
      不复位，**同进程后续请求会继续沿用上一个人的选择**（本仓真实咬过人的形态）。
    """
    from ai_infra.skills import bind_requested_skill, current_requested_skill

    assert current_requested_skill() is None

    async with bind_requested_skill("  alpha  "):
        assert current_requested_skill() == "alpha", "作用域内没读到（或没 strip）"
        async with bind_requested_skill("beta"):
            assert current_requested_skill() == "beta", "嵌套内层没有覆盖"
        assert current_requested_skill() == "alpha", "嵌套退出后没有还原"
    assert current_requested_skill() is None, "最外层退出后没有复位"

    for empty in ("", "   ", None):
        async with bind_requested_skill(empty):
            assert current_requested_skill() is None, f"{empty!r} 不等于「没点名」"

    with pytest.raises(RuntimeError):
        async with bind_requested_skill("boom"):
            raise RuntimeError("路由里炸了")
    assert current_requested_skill() is None, (
        "异常退出后没有复位 ⇒ 上一次的选择会泄漏给下一个请求"
    )


# ==========================================================================
# C. 单真源：两条通道共用同一个解析器（不新建第二份过滤）
# ==========================================================================


def test_both_channels_share_one_resolver():
    """★★★ `load_skill` 与点名段落**共用** `provider.read_skill_text`。

    ★ 为什么必须共用：两条通道都做「按名字取正文」。两份实现 ⇒ 至少一份永远
      测不到；而漏掉的那份就是「知道名字就能读到未授权正文」——
      比不披露更糟。判据取**代码形态**：点名段落必须 import 那个函数，
      且**不得**自己出现任何判权符号。
    """
    src = _src(SELECTED_PY)
    which = _providing_fn(src, "read_skill_text")
    assert which is not None, (
        "`selected_skill_section.py` 没有 import `provider.read_skill_text` ⇒ "
        "它要么自己写了一份取数（第二份过滤 = 第二条越权面），要么根本没取数。"
    )
    assert which != "module", (
        f"`read_skill_text` 的 import 落在 {which!r} —— 应放在**函数体内**："
        f"`provider.py` 末尾会 import 本模块，模块级再反向 import 会形成环。"
    )

    # 不得自己判权（判权只有一处入口）
    for banned in ("filter_accessible_skills", "read_skill_for_agent", "ensure_can_access"):
        assert banned not in src, (
            f"`selected_skill_section.py` 里出现了 {banned!r} ⇒ "
            f"点名通道自己写了一份归属判定（本仓判据：同一判定两份实现 ⇒ "
            f"至少一份永远测不到）。它应当只调 `read_skill_text`。"
        )

    # provider 注册的读取器必须**就是**那个函数（不是同名包装）
    tree = ast.parse(_src(PROVIDER_PY))
    found = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "register_skill_reader"):
            assert len(n.args) == 2, ast.unparse(n)
            assert getattr(n.args[1], "id", "") == "read_skill_text", (
                f"`register_skill_reader` 的第二个参数是 {ast.unparse(n.args[1])!r}，"
                f"不是 `read_skill_text` ⇒ `load_skill` 与点名段落走的**不是**同一条解析路径。"
            )
            found = True
    assert found, "`provider.py` 里找不到 `register_skill_reader(...)` 调用"


def _row_attrs(fn: ast.AST) -> set:
    """函数体里所有 `row.<attr>` 形态的 **属性名精确集合**。

    ★★★ 这里**必须**用 AST 的属性名相等，而不是 `"row.enabled" in 源码`：
      那个写法有一个致命的子串陷阱 —— `row.enabled` 是 `row.enabled_agents`
      的**前缀**，于是把「全局启用」那道过滤整段删掉之后，字符串包含照样成立，
      断言**恒真**。第 188 轮反向注入（M7）就是在这里抓到它的：
      变异把 `if not bool(row.enabled)` 换成 `if False:`，本用例当时**没有转红**。
    """
    return {
        n.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "row"
    }


def _called_names(fn: ast.AST) -> set:
    """函数体里被调用的**裸函数名**（`f(...)` 形态，不含 `a.b(...)`）。"""
    return {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_three_filters_live_in_exactly_one_place():
    """★★ 三重过滤（归属 / 全局启用 / 对该 Agent 启用）只在 `service` 里实现一次。

    ★ 判据取 **AST 精确形态**（见 `_row_attrs` 的注释：字符串包含会被
      `enabled_agents` 骗过）。任何一处被摘掉，要么越权可读、要么名字对上了
      却读不到。
    """
    fn = _find(ast.parse(_src(SERVICE_PY)), "read_skill_for_agent")
    assert fn is not None, "`service.py` 里找不到 `read_skill_for_agent`"

    attrs = _row_attrs(fn)
    called = _called_names(fn)

    assert "filter_accessible_skills" in called, (
        "归属过滤没了 ⇒ 知道名字就能读到别人的技能"
    )
    assert "enabled" in attrs, (
        f"`read_skill_for_agent` 里没有 `row.enabled`（全局启用开关）⇒ "
        f"关掉的技能照样能被加载。实测属性：{sorted(attrs)}"
    )
    assert "enabled_agents" in attrs, (
        f"「对该 Agent 启用」没了 ⇒ 没给这个 Agent 开的技能也能加载。"
        f"实测属性：{sorted(attrs)}"
    )
    assert "render_skill_body" in called, "正文渲染不在唯一取数点里"


def test_three_filter_scanner_is_not_vacuous():
    """★ 门禁自检：`_row_attrs` 必须是**属性名精确匹配**，不是子串包含。

    ★ 这条钉的是 M7 反向注入暴露出来的缺陷本身：把 `row.enabled` 换成
      `row.enabled_agents` 之后，子串式判据仍然"看得见" enabled。
    """
    only_agents = ast.parse(
        "def f(row):\n"
        "    return list(row.enabled_agents or [])\n"
    )
    fn = [n for n in only_agents.body if isinstance(n, ast.FunctionDef)][0]
    assert _row_attrs(fn) == {"enabled_agents"}, (
        f"`_row_attrs` 把 `enabled_agents` 里的子串也算成了 `enabled` ⇒ "
        f"「全局启用过滤被摘掉」这件事将**永远测不出来**。实测：{_row_attrs(fn)}"
    )


# ==========================================================================
# D. 调用点门禁：**代码形态**完备性（不是端点名单）
# ==========================================================================

#: 「这次调用是不是在发起一次 Agent 对话」的形态判据。
#: 被调属性名 + 调用者名字里含有 service / agent 这类层名。
_CONV_ATTRS = {"chat", "stream_chat", "invoke", "ainvoke", "astream"}
_CONV_BASES = ("service", "agent", "svc")


def conversation_calls(fn: ast.AST) -> list:
    """函数体内（含嵌套）发起 agent 对话的调用（返回可读描述）。"""
    out = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        base = ast.unparse(n.func.value)
        if not any(k in base.lower() for k in _CONV_BASES):
            continue
        attr = n.func.attr
        if attr in _CONV_ATTRS or attr.endswith("_analysis"):
            out.append("%s.%s" % (base, attr))
    return sorted(set(out))


def _has_bind(fn: ast.AST) -> bool:
    return any(
        isinstance(x, ast.AsyncWith)
        and any(
            isinstance(it.context_expr, ast.Call)
            and getattr(it.context_expr.func, "id", "") == "bind_requested_skill"
            for it in x.items
        )
        for x in ast.walk(fn)
    )


def scan_conversation_endpoints() -> list:
    """扫 `modules/**/router.py` 的全部 POST 端点，产出 (相对路径, 函数名, 调用, 是否已接线)。

    ★ 只看**顶层**函数（FastAPI 端点就是顶层函数）—— 不递归进辅助函数的定义处，
      避免把"某个 helper 恰好调了 service.chat"算成一个端点。
    """
    rows = []
    for p in sorted((BACKEND / "modules").rglob("router.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(BACKEND).as_posix()
        src = _src(p)
        tree = ast.parse(src)
        parents = _parent_map(tree)
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any("router.post" in ast.unparse(d) for d in n.decorator_list):
                continue
            calls = conversation_calls(n)
            if not calls:
                continue
            # ★ 写入点的**位置**判据：必须与它守护的调用处在**同一个最小包围函数**内。
            #   流式端点的对话调用住在 `_wrapped`（生成器）里，写入点也必须在
            #   `_wrapped` 里 —— 包在外层的话，`async with` 会在生成器被第一次
            #   迭代**之前**就退出 ⇒ 等于根本没设。
            ok = True
            for call in ast.walk(n):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                desc = "%s.%s" % (ast.unparse(call.func.value), call.func.attr)
                if desc not in calls:
                    continue
                owner = _enclosing_fn(parents, call) or n
                if not _has_bind(owner):
                    ok = False
            rows.append((rel, n.name, tuple(calls), ok))
    return rows


def test_every_conversation_endpoint_binds_the_named_skill():
    """★★★ 每一个「会发起 Agent 对话」的端点都必须接上点名通道。

    ★ 这条是**防漏**的那一侧：新增一个对话端点、忘了接线 ⇒
      代码照跑、测试全绿，用户点名技能却无效。
    ★ 写入点还必须与其守护的调用在**同一个最小包围函数**内 ——
      这正是"流式端点的 async with 包在外层 ⇒ 等于没设"那条坑的判据。
    ★ 反向注入：把某个流式端点的 `async with` 从 `_wrapped` 提到外层函数 ⇒ 本用例转红。
    """
    rows = scan_conversation_endpoints()
    unbound = [(rel, fn, calls) for rel, fn, calls, ok in rows if not ok]
    assert not unbound, (
        "以下端点会发起 Agent 对话，但**没有**接上点名通道"
        "（或写入点不在守护它的那个最小包围函数内 —— 流式端点务必放进 `_wrapped`）：\n"
        + "\n".join(f"  {rel}::{fn}  调用={calls}" for rel, fn, calls in unbound)
    )


def test_conversation_endpoint_inventory_is_not_vacuous():
    """★ 防 detector 空转：形态判据必须真的认出这些端点（否则上面那条恒绿）。

    ★ 为什么给"恰好 13"这个数字：它同时防两种反向失效 ——
      · 有人新增对话端点却改成了 detector 认不出的写法 ⇒ 数量掉了 ⇒ 红；
      · detector 的形态判据被放宽到误报 ⇒ 数量涨了 ⇒ 红。
      数量变化本身不是问题，**必须回来核对这条判据是否还咬得住**才是重点。
    """
    rows = scan_conversation_endpoints()
    assert len(rows) == 13, (
        f"形态判据认出 {len(rows)} 个对话端点，期望 13：\n"
        + "\n".join(f"  {r[0]}::{r[1]} {r[2]}" for r in rows)
        + "\n（数量变化请核对：是新增/重命名了对话端点，还是 detector 的形态判据失效了？）"
    )

    # 反向注入自检：detector 必须能发现「没接线」的样本
    fake = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/chat')\n"
        "async def chat(request):\n"
        "    return await SomeService.chat(request)\n"
    )
    tree = ast.parse(fake)
    fn = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)][0]
    assert conversation_calls(fn) == ["SomeService.chat"], "detector 认不出对话调用"
    assert not _has_bind(fn), "未接线的样本被判成了已接线 ⇒ 这条门禁恒绿"


def test_streaming_write_point_must_be_inside_the_generator():
    """★★★ 流式端点的写入点必须在**生成器体内** —— 用真代码形态钉住。

    ★ 这条与 `_has_bind(owner)` 是同一判据的**正面对照**：确认被检的
      `owner` 真的是内层生成器（而不是端点本身），否则上一条会**偶然**通过。
    """
    streaming = [
        ("modules/ad_analysis/router.py", "chat_stream"),
        ("modules/aigc_media/router.py", "aigc_chat_stream"),
        ("modules/competitor_intel/router.py", "chat_stream"),
        ("modules/customer_service/router.py", "chat_stream"),
        ("modules/listing_generator/router.py", "chat_with_listing_agent_stream"),
        ("modules/product_research/router.py", "chat_stream"),
    ]
    for rel, fname in streaming:
        src = _src(BACKEND / rel)
        tree = ast.parse(src)
        parents = _parent_map(tree)
        ep = _find(tree, fname)
        assert ep is not None, f"找不到 {rel}::{fname}"

        inner = [n for n in ast.walk(ep)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_wrapped"]
        assert inner, (
            f"{rel}::{fname} 里没有内层 `_wrapped` 生成器 —— 若换了名字，"
            f"请同步本用例（它是「写入点在生成器内」这条判据的定位锚）。"
        )
        assert _has_bind(inner[0]), (
            f"{rel}::{fname} 的 `_wrapped` **体内**没有 `bind_requested_skill`。\n"
            f"⇒ 它八成被包在了返回 StreamingResponse 的外层：那个 `async with` 会在"
            f"生成器被第一次迭代**之前**退出 ⇒ 等于根本没设。"
        )


# ==========================================================================
# E. 端到端（真库 + 假 LLM）：点名的技能**真的到了** system prompt
# ==========================================================================


async def _make_skill(owner, *, name: str, content: str, agents, enabled: bool = True):
    """走**生产同一条写路径**（`service.create_skill`）在真库里建一条技能。"""
    from sqlalchemy import select

    from core.database import async_session_factory
    from core.identity.models import User
    from modules.skills import service as SK

    async with async_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.id == owner["user_id"]))
        ).scalar_one()
        return await SK.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "点名测试技能",
                "description": "第 188 轮点名通道用",
                "content": content,
                "enabled": enabled,
                "enabledAgents": list(agents),
            },
            account_id=None,
        )


@contextlib.asynccontextmanager
async def _capture_system_prompt(monkeypatch, *, user_id, agent_name):
    """跑一次 `_llm_call_node`，把送进模型的 system prompt 抓出来。

    ★ 只替换**最外层**（`_llm_with_tools`）：采集节点、段落注册表、身份链路
      与业务读取器全走真的 —— 否则验的是桩而不是接线。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from ai_infra import base_agent as BA

    captured: dict = {}

    class _CapturingLLM:
        async def ainvoke(self, messages, **kwargs):
            captured["system"] = messages[0].content
            return AIMessage(content="好的")

    agent = BA.BaseAgent(agent_name=agent_name, system_prompt="你是助手。")
    monkeypatch.setattr(agent, "_llm_with_tools", lambda *a, **kw: _CapturingLLM())
    monkeypatch.setattr(BA, "current_user_id", lambda: user_id)

    async def _run():
        await agent._llm_call_node(
            {"messages": [HumanMessage(content="开始")], "todos": [], "budget": {}}
        )

    yield _run, captured


async def test_named_skill_reaches_the_system_prompt(skill_owner, monkeypatch):
    """★★★ 整条链路接在一起：点名 ⇒ 正文进 system prompt。

    前面各组分别证明「注册了」「读得到」「渲染对」「端点接了线」；
    只有这一条证明它们**连起来真的发生了**（本仓出现过"每一环都有测试、
    连起来却什么都没发生"的形态）。
    """
    from ai_infra.skills import bind_requested_skill

    marker = "点名技能正文标记-188-MARKER"
    name = skill_owner["prefix"] + "-nominate"
    await _make_skill(skill_owner, name=name, content=marker, agents=[AGENT])

    async with _capture_system_prompt(
        monkeypatch, user_id=skill_owner["user_id"], agent_name=AGENT
    ) as (run, captured):
        async with bind_requested_skill(name):
            await run()

    system = captured.get("system", "")
    assert system, "假 LLM 没被调用 ⇒ 用例空跑"
    assert marker in system, (
        f"点名技能的**正文**没有进 system prompt。实际收到：{system[:300]!r}"
    )
    assert "本次对话指定的技能" in system, "点名段的抬头不在 ⇒ 注入的是别的东西"


async def test_without_naming_nothing_is_injected(skill_owner, monkeypatch):
    """★ 反面：没点名 ⇒ 正文**不能**出现（只允许出现目录里的名字/描述）。

    ★ 这条防的是「ContextVar 残留」：把上一次请求的选择泄漏给下一个请求，
    表现是"我没点技能，它却按某条技能做了" —— 而没有任何报错。
    """
    marker = "未点名不该出现的正文-188-MARKER"
    name = skill_owner["prefix"] + "-unused"
    await _make_skill(skill_owner, name=name, content=marker, agents=[AGENT])

    async with _capture_system_prompt(
        monkeypatch, user_id=skill_owner["user_id"], agent_name=AGENT
    ) as (run, captured):
        await run()

    system = captured.get("system", "")
    assert system, "假 LLM 没被调用 ⇒ 用例空跑"
    assert marker not in system, "没点名却把技能正文注入了（ContextVar 残留？）"
    assert "本次对话指定的技能" not in system, "没点名却出现了点名段的抬头"


async def test_unavailable_named_skill_is_visible_not_silent(skill_owner, monkeypatch):
    """★★★ 点名了但取不到 ⇒ system prompt 里必须有**显式说明**。

    ★ 这是本通道与长期记忆的**有意分歧**：记忆取不到可以不注入（少一段增益），
      点名取不到必须留痕 —— 否则用户点了技能、模型按默认方式回答，
      而界面、日志、测试全绿；用户只会觉得"这功能没用"。
    """
    from ai_infra.skills import bind_requested_skill

    bogus = skill_owner["prefix"] + "-never-created"
    async with _capture_system_prompt(
        monkeypatch, user_id=skill_owner["user_id"], agent_name=AGENT
    ) as (run, captured):
        async with bind_requested_skill(bogus):
            await run()

    system = captured.get("system", "")
    assert system, "假 LLM 没被调用 ⇒ 用例空跑"
    assert "本次对话指定的技能" in system, "点名段整段没注入 ⇒ 用户的选择被静默丢弃"
    assert bogus in system, "没有点名是哪个技能，模型无法如实告知用户"
    assert "取不到" in system, "没有写出「取不到」⇒ 模型会以为技能正文就是空"


# ==========================================================================
# F. 归属：四种「取不到」在 resolver 边界上**不可分**
# ==========================================================================


@pytest_asyncio.fixture
async def other_owner(make_user):
    """另一个真实用户（用来验证「不属于我的技能读不到」）。"""
    info = await make_user("otherowner188")
    yield info


async def test_unavailable_causes_are_indistinguishable(skill_owner, other_owner):
    """★★★ 「不存在 / 不属于我 / 未启用 / 没给本 Agent 开」四种原因**同返回值、同文案**。

    ★ 为什么必须不可分：可分就等于给出一条**可枚举的探测通道** ——
      攻击者可以逐个名字试出"这条技能存在但不属于我"，进而枚举出别人的技能名。
      （同族判据：「不存在」与「不属于你」必须给出同一响应。）

    ★ 判据取**逐字相等**而不是"都非空"：渲染文案里带着请求的技能名，
      所以只要同一名字的四种原因产出的文本**逐字相同**，就证明没有任何
      原因专属的措辞漏出去。
    """
    from sqlalchemy import select

    from ai_infra.prompt_sections import PromptContext
    from ai_infra.skills import bind_requested_skill

    from core.database import async_session_factory
    from modules.skills import provider as P
    from modules.skills import selected_skill_section as SSS
    from modules.skills.db_model import SkillRecord

    name = skill_owner["prefix"] + "-causes"
    await _make_skill(skill_owner, name=name, content="正文-CAUSES", agents=[AGENT])

    a_id, b_id = skill_owner["user_id"], other_owner["user_id"]

    # ① 不属于我（技能对 A 可见、对 B 读不到）
    r_not_mine = await P.read_skill_text(b_id, AGENT, name)
    async with bind_requested_skill(name):
        t_not_mine = await SSS.selected_skill_prompt_section(
            PromptContext(agent_name=AGENT, user_id=b_id)
        )

    # ② 未启用
    async with async_session_factory() as db:
        row = (await db.execute(select(SkillRecord).where(SkillRecord.name == name))).scalar_one()
        row.enabled = False
        await db.commit()
    r_disabled = await P.read_skill_text(a_id, AGENT, name)
    async with bind_requested_skill(name):
        t_disabled = await SSS.selected_skill_prompt_section(
            PromptContext(agent_name=AGENT, user_id=a_id)
        )

    # ③ 没给本 Agent 启用
    async with async_session_factory() as db:
        row = (await db.execute(select(SkillRecord).where(SkillRecord.name == name))).scalar_one()
        row.enabled = True
        row.enabled_agents = ["SomeOtherAgent"]
        await db.commit()
    r_wrong_agent = await P.read_skill_text(a_id, AGENT, name)
    async with bind_requested_skill(name):
        t_wrong_agent = await SSS.selected_skill_prompt_section(
            PromptContext(agent_name=AGENT, user_id=a_id)
        )

    # ④ 完全不存在（名字换成没建过的）
    missing = skill_owner["prefix"] + "-causes-missing"
    r_missing = await P.read_skill_text(a_id, AGENT, missing)

    # —— resolver 层：四种原因要么 None 要么空，**没有可区分的信号** ——
    for tag, got in (
        ("①不属于我", r_not_mine), ("②未启用", r_disabled),
        ("③没给本Agent启用", r_wrong_agent), ("④不存在", r_missing),
    ):
        assert not got, f"{tag} 竟然读到了正文：{got!r}"

    # —— 文案层：同一名字（①②③）必须**逐字相同** ——
    assert t_not_mine == t_disabled == t_wrong_agent, (
        f"三种原因产出了**不同文案** ⇒ 存在可枚举的探测通道：\n"
        f"  ①不属于我: {t_not_mine[-120:]!r}\n"
        f"  ②未启用:   {t_disabled[-120:]!r}\n"
        f"  ③没开给本Agent: {t_wrong_agent[-120:]!r}"
    )

    # ④ 用另一个名字 ⇒ 文案差异只应来自"被回显的技能名"本身
    from ai_infra.skills import render_selected_skill_block

    assert t_not_mine == render_selected_skill_block(name, None), (
        "取不到的文案里混进了原因专属的措辞（或混进了别的内容）"
    )


# ==========================================================================
# G. 失败隔离：读取器抛异常 ⇒ 转成显式文案，**不是**静默丢段
# ==========================================================================


async def test_resolver_failure_becomes_explicit_text(monkeypatch):
    """★★★ 读取器抛异常时，点名段落**不向上抛**，而是给出显式「取不到」。

    ★ 为什么不能让它抛出去：注册表 `collect_prompt_sections` 对单段失败是
      「隔离 + 丢弃」—— 那对长期记忆是对的（少一段增益），但点名是**用户的
      显式指令**，整段丢掉 ⇒ 模型完全不知道用户点过技能。所以这里必须
      把异常**转成文案**（降级值必须能被识别）。
    """
    from ai_infra.prompt_sections import PromptContext

    from modules.skills import provider as P
    from modules.skills import selected_skill_section as SSS
    from ai_infra.skills import bind_requested_skill

    async def _boom(*_a, **_kw):
        raise RuntimeError("DB 炸了")

    monkeypatch.setattr(P, "read_skill_text", _boom)

    async with bind_requested_skill("alpha"):
        text = await SSS.selected_skill_prompt_section(
            PromptContext(agent_name=AGENT, user_id="u-188")
        )

    assert text.strip(), "读取器炸了 ⇒ 段落变成空 ⇒ 用户的选择静默失效"
    assert "alpha" in text and "取不到" in text, (
        f"读取器炸了却没有给出可识别的降级文案：{text[:160]!r}"
    )


async def test_section_is_isolated_by_the_registry(skill_owner):
    """★ 段落经注册表收集时，失败要能被 `failed` **点名**（与「本来就没内容」可分）。

    ★ 这条与上一条互补：上一条保证"异常被转成文案"，这一条保证注册表那层
      的隔离机制对本段同样生效（不依赖 provider 自己是否吞异常）。
    """
    from ai_infra.prompt_sections import PromptContext, collect_prompt_sections

    async def _boom(_ctx):
        raise RuntimeError("本段炸了")

    async def _ok(_ctx):
        return "别的内容"

    got = await collect_prompt_sections(
        PromptContext(agent_name=AGENT, user_id=skill_owner["user_id"]),
        registry={"z_bad": _boom, "a_ok": _ok},
    )
    assert got.blocks == ("别的内容",), "一段炸了把整次收集带崩了"
    assert got.failed == ("z_bad",), "失败没有被点名 ⇒ 与「本来就没内容」不可分"
