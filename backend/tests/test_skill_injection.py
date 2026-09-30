"""技能注入与渐进披露 —— 门禁（第 181 轮 · 批 B）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
老板本轮要的技能，要害不是「多一张管理界面」，而是**技能真的会被 Agent 用上**。
而这条链路上有三个**静默**的失败点 —— 三处的共同特征是：

    代码看起来是对的、日志全绿、门禁全绿、数据库里也有数据，
    唯一的表现是「模型永远不知道有这个技能」。

① **注册永不发生**。`modules/skills/provider.py` 靠 import 副作用把
   「技能目录」段落与 `load_skill` 读取器登记进 `ai_infra` 的注册表；
   唯一触发它的是一行 `from modules.skills import provider`。
   删掉那一行 ⇒ 九个端点照常工作、技能仓库页照常能用、`collect_prompt_sections`
   对空注册表完全正常 ⇒ **什么都没注入，且没有任何一处报错**。

② **`load_skill` 被挂进审批面**。`has_side_effects()` 是 fail-closed
   （未声明 ⇒ 视为有副作用）⇒ 漏写 `metadata=READ_ONLY_METADATA` 的后果是
   「每加载一次技能就弹一次人工审批」。用户看到的是"这功能没法用"，
   而测试全绿。

③ **装配顺序敏感**。`build_skill_tools` 若在「没有读取器」时返回 `[]`，
   则 `BaseAgent.tools` 的内容取决于**本进程有没有 import 到业务模块** ——
   同一份代码单跑是 4 个工具、全量跑是 5 个。本仓明令禁止这种真值：
   那等于断言只能写"松"，或者变成「单跑绿 / 全量红」。

==============================================================================
★ 为什么 ① 必须用**子进程**验（这是本文件里唯一"重"的一条，别删）
==============================================================================
在测试会话内 `import modules.skills.router` 是**无法证伪**的：
`main.py` / 其它测试文件早已把它（或它的下游）import 过 ⇒ 那句 import
变成 no-op，而注册表里确实有那一段 —— 断言恒真，**删掉 router 顶部那行
依旧绿**。

所以那一条在**全新解释器**里做 before/after 对账：先确认注册表是空的
（证明不是别人替它注册的），再 import router，再看。这样才真正咬住
「那一行是功能性的」。
"""

import ast
import json
import os
import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SKILLS_INFRA_PY = BACKEND / "ai_infra" / "skills.py"

#: 段落名（契约的一部分：改名等于「旧名不再注入」）
SECTION_NAME = "skills_catalog"

#: 读取器名
READER_NAME = "db"


# ============================================================================
# A. 注册真的发生了（防「静默不注入」）
# ============================================================================


def test_facade_import_actually_registers_both_channels():
    """走门面 ⇒ 两条通道都在注册表里（第一级披露 + 第二级披露）。

    ★ 这一条是**便宜版的冒烟**，它不能替代下面的子进程用例 ——
      在测试会话里本断言可能因为别的模块先 import 过而恒真。子进程那条才是判据。
    """
    import modules.skills.router  # noqa: F401  —— import 本身就是要验证的动作
    from ai_infra.prompt_sections import registered_sections
    from ai_infra.skills import registered_skill_readers

    assert SECTION_NAME in registered_sections(), (
        f"import 了技能门面，但注册表里没有 {SECTION_NAME}：{registered_sections()}。"
        f"⇒ 技能目录永不注入（模型不知道有技能），且不会有任何报错。"
    )
    assert READER_NAME in registered_skill_readers(), (
        f"技能正文读取器没注册：{registered_skill_readers()}。"
        f"⇒ `load_skill` 永远返回「功能未启用」（第二级披露断链）。"
    )


#: 子进程探针：**纯 ASCII**（避免 `-c` / 源码编码随机器变化带来的假红）。
#: 逻辑就是「before / import / after」—— 少了 before 就无法排除"别人替它注册"。
_CHILD_PROBE = """\
import json

from ai_infra.prompt_sections import registered_sections
from ai_infra.skills import registered_skill_readers

before_sections = list(registered_sections())
before_readers = list(registered_skill_readers())

import modules.skills.router  # noqa: F401,E402  -- import triggers registration

payload = {
    "before_sections": before_sections,
    "before_readers": before_readers,
    "after_sections": list(registered_sections()),
    "after_readers": list(registered_skill_readers()),
}
print("VERDICT:" + json.dumps(payload))
"""


@pytest.mark.timeout(300)
def test_router_top_level_import_is_load_bearing(tmp_path):
    """★★★ 全新解释器里做 before/after 对账：`router.py` 顶部那行 import 是**功能性**的。

    反向注入：删掉 `modules/skills/router.py` 里的
    `from modules.skills import provider` ⇒ 本用例必须转红
    （`after_sections` 会是 `[]`）。

    ★ 为什么必须开子进程：见模块 docstring 的论证。在会话内做这件事，
      那句 import 早已被 `main.py` 触发过，断言恒真。
    """
    script = tmp_path / "child_probe_181.py"
    script.write_text(_CHILD_PROBE, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(BACKEND),          # `.env` 相对 CWD ⇒ 必须落在 backend/
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )

    lines = [
        ln for ln in (proc.stdout or "").splitlines() if ln.startswith("VERDICT:")
    ]
    assert lines, (
        f"子进程没有输出 VERDICT 行 ⇒ 探针本身没跑起来。\n"
        f"  returncode = {proc.returncode}\n"
        f"  stdout[:1200] = {(proc.stdout or '')[:1200]!r}\n"
        f"  stderr[:1200] = {(proc.stderr or '')[:1200]!r}"
    )
    verdict = json.loads(lines[-1][len("VERDICT:"):])

    assert verdict["before_sections"] == [], (
        f"全新解释器里注册表**本应为空**，实际 {verdict['before_sections']} —— "
        f"说明有别处抢先注册了。本用例因此无法证明 router 那行 import 是必需的，"
        f"请先查清是谁注册的（`tests/test_memory_injection.py` 有调用点白名单）。"
    )
    assert verdict["before_readers"] == [], (
        f"全新解释器里技能读取器**本应为空**，实际 {verdict['before_readers']}"
    )

    assert SECTION_NAME in verdict["after_sections"], (
        f"import `modules/skills/router.py` 之后，注册表里仍然没有 {SECTION_NAME}"
        f"（after={verdict['after_sections']}）。\n"
        f"⇒ `router.py` 顶部那句 `from modules.skills import provider` 被删了（或挪走了）。\n"
        f"  后果：九个端点全部正常、技能仓库页全部正常、数据库全部正常，"
        f"**但技能永远不注入 system prompt**，且没有任何一处会报错。"
    )
    assert READER_NAME in verdict["after_readers"], (
        f"import `modules/skills/router.py` 之后，读取器仍然没注册"
        f"（after={verdict['after_readers']}）⇒ `load_skill` 永远说「功能未启用」。"
    )


def test_install_is_idempotent():
    """`provider.install()` 重复调用不得抛错。

    ★ 为什么单列一条：两个注册表都对**重名直接报错**（那是刻意的，防静默覆盖）。
      而 pytest 里 `importlib.reload()` 会让模块被 import 第二次 ⇒ 若 `install()`
      不做「已装好就别再装」，重载会直接炸。这条钉住那个前置判断。
    """
    from modules.skills import provider

    provider.install()
    provider.install()   # 第二次、第三次都必须是 no-op

    from ai_infra.prompt_sections import registered_sections
    from ai_infra.skills import registered_skill_readers

    assert list(registered_sections()).count(SECTION_NAME) == 1, (
        f"重复 install 造出了重复段落：{registered_sections()}"
    )
    assert list(registered_skill_readers()).count(READER_NAME) == 1, (
        f"重复 install 造出了重复读取器：{registered_skill_readers()}"
    )


# ============================================================================
# B. 机制层的注册表默认必须为空（AST：运行时值会被业务注册污染）
# ============================================================================


def _assigned_value_of(tree: ast.AST, name: str):
    """模块顶层 `NAME = ...` / `NAME: T = ...` 的右值（取不到返回 None）。"""
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if isinstance(target, ast.Name) and target.id == name:
            return node.value
    return None


def test_skill_reader_registry_is_empty_by_default():
    """★★ `_READERS` 在**定义处**必须是空字典 —— 机制层不自带任何内容。

    ★ 为什么扫 AST 而不是运行时读 `_READERS`：运行时值取决于本进程 import 过
      哪些业务模块（`modules/skills/provider.py` 一注册就有内容了）——
      读运行时值等于什么都没验。定义处才是判据。
      （同判据见 `test_memory_injection.py::test_prompt_section_registry_is_empty_by_default`。）

    ★ 这不是洁癖：机制层自带内容 = 基础设施层开始认识业务。
      本仓真实发生过（`AgentState.metadata` 曾硬编码 tenant/shop 四个键，只写不读），
      而 `tests/test_infra_layering.py` 的反向依赖门禁会连带变红。
    """
    tree = ast.parse(SKILLS_INFRA_PY.read_text(encoding="utf-8"))
    value = _assigned_value_of(tree, "_READERS")
    assert value is not None, "`ai_infra/skills.py` 里找不到 `_READERS` 的定义"
    assert isinstance(value, ast.Dict) and not value.keys, (
        f"`_READERS` 的定义处不是空字典（{ast.unparse(value)}）—— "
        f"机制层不许自带技能内容，它必须由业务层 `register_skill_reader()` 注入。"
    )


# ============================================================================
# C. `load_skill` 的装配形态（防顺序敏感 + 防回流到审批面）
# ============================================================================


def test_build_skill_tools_always_returns_exactly_one(monkeypatch):
    """★★★ `build_skill_tools()` **恒返回 1 个** `load_skill`，与读取器注册状态无关。

    ★ 这条钉的是「装配确定性」。原始写法是「未注册读取器 ⇒ 返回 `[]`」，
      那个写法让 `BaseAgent.tools` 的内容取决于**本进程有没有 import 到业务模块**：
      单跑某个测试文件时 4 个工具、全量跑时 5 个 ⇒ 断言只能写"松"，
      或者变成「单跑绿 / 全量红」。本仓明令禁止这种顺序敏感的真值。

    ★ 反向注入：把 `build_skill_tools` 的 `return [...]` 改回
      `if not _READERS: return []` ⇒ 本条必须转红。
    """
    import ai_infra.skills as skills_infra

    with_registry = [t.name for t in skills_infra.build_skill_tools("some-agent")]

    monkeypatch.setattr(skills_infra, "_READERS", {})   # 模拟「业务模块尚未 import」
    without_registry = [t.name for t in skills_infra.build_skill_tools("some-agent")]
    no_reader_reply = _run_tool(
        skills_infra.build_skill_tools("some-agent")[0], "任意技能"
    )

    assert with_registry == ["load_skill"], (
        f"工具装配面 = {with_registry}，应恰好是 ['load_skill']"
    )
    assert without_registry == ["load_skill"], (
        f"没有读取器时装配面变成了 {without_registry} —— "
        f"工具的存在与否**不允许**依赖本进程的 import 完成度（顺序敏感真值）。"
        f"「有没有技能可加载」应该是**运行期返回值**问题，不是装配形态问题。"
    )
    assert "未启用" in no_reader_reply, (
        f"没有读取器时应当**显式回话**说功能未启用，实际：{no_reader_reply!r} —— "
        f"说清「未启用」而不是「技能不存在」才是对的：前者该放弃这条路径，"
        f"后者会让模型换个名字反复重试。"
    )


def _run_tool(tool, skill_name: str) -> str:
    """同步跑一次 `load_skill`（用例里不引入 pytest-asyncio 的额外约束）。"""
    import asyncio

    return asyncio.run(tool.ainvoke({"skill_name": skill_name}))


def test_load_skill_is_declared_read_only():
    """★★★ `load_skill` 必须显式声明**只读**，否则每次加载技能都要人工审批。

    `ai_infra/tools/side_effects.py::has_side_effects()` 是 **fail-closed**：
    未声明 `side_effects` 的工具一律判为「有副作用」⇒ 一律获得审批包装。
    加载一段技能说明是**可逆的只读动作**，把它挂进审批面等于这个能力事实上不可用。

    ★ 反向注入：去掉 `build_skill_tools` 里的 `metadata=dict(READ_ONLY_METADATA)`
      ⇒ 本条必须转红（`declared_side_effects` 会变成 `None`，
      `derive_hitl_tools` 会变成 `['load_skill']`）。
    """
    from ai_infra.skills import build_skill_tools
    from ai_infra.tools.side_effects import (
        declared_local_state,
        declared_side_effects,
        derive_hitl_tools,
        is_declared,
        local_state_violations,
        write_verb_violations,
    )

    tools = build_skill_tools("some-agent")
    tool = tools[0]

    assert is_declared(tool) is True, (
        "`load_skill` 没有显式声明副作用 —— fail-closed 会把它判成有副作用"
    )
    assert declared_side_effects(tool) is False, (
        f"`load_skill` 的副作用声明 = {declared_side_effects(tool)!r}，应为 False（只读）。"
        f"否则每加载一次技能都会弹一次人工审批。"
    )
    assert declared_local_state(tool) is False, (
        "`load_skill` 不该声明 `writes_local_state` —— 它根本不写图状态，"
        "那是规划器两个工具的档位（受控集合之外声明会触发 local_state_violations）。"
    )
    assert derive_hitl_tools(tools) == [], (
        f"`load_skill` 进了审批名单：{derive_hitl_tools(tools)} —— "
        f"「加载技能说明」不该需要人工批准。"
    )
    assert write_verb_violations(tools) == [], (
        f"名字像写操作却被声明成只读：{write_verb_violations(tools)}"
    )
    assert local_state_violations(tools) == [], (
        f"越界的 local_state 声明：{local_state_violations(tools)}"
    )


def test_load_skill_metadata_is_a_private_copy():
    """★ 工具拿到的是 `READ_ONLY_METADATA` 的**副本**，不是那个模块级常量本身。

    ★ 为什么要钉：`bind_tools` / 中间件链上真有人会往 `tool.metadata` 里塞东西。
      若 `StructuredTool.from_function(metadata=READ_ONLY_METADATA)` 直接传引用，
      一处改写就会**污染全局常量** ⇒ 之后所有只读工具（几十个）的声明一起变，
      而症状完全无法归因。
    """
    from ai_infra.skills import build_skill_tools
    from ai_infra.tools.side_effects import READ_ONLY_METADATA

    tool = build_skill_tools("some-agent")[0]
    assert tool.metadata is not READ_ONLY_METADATA, (
        "`load_skill` 的 metadata 是全局常量的**同一个 dict** ⇒ 改写它会污染全仓只读工具"
    )
    assert tool.metadata == READ_ONLY_METADATA, (
        f"metadata 内容与 `READ_ONLY_METADATA` 不一致：{tool.metadata}"
    )

    tool.metadata["污染探针"] = True
    assert "污染探针" not in READ_ONLY_METADATA, (
        "改写工具的 metadata 污染了模块级常量 `READ_ONLY_METADATA`"
    )


def test_load_skill_tools_are_independent_per_agent():
    """每个 Agent 拿到**独立**的工具对象（`agent_name` 在构造期绑定成闭包）。

    ★ 若工具对象被跨 Agent 共享，`load_skill` 里的 `bound_agent` 就会是
      「最后一个构造它的 Agent」⇒ 技能启用判定（`enabled_agents`）会张冠李戴，
      而且只在"同一进程里跑了多个 Agent"时才显形 —— 单测通常只跑一个。
    """
    from ai_infra.skills import build_skill_tools

    a = build_skill_tools("agent-a")
    b = build_skill_tools("agent-b")

    assert a[0] is not b[0], "两个 Agent 共用了同一个工具对象"
    assert a[0].metadata is not b[0].metadata, "两个 Agent 共用了同一个 metadata dict"
    assert a[0].name == b[0].name == "load_skill"


# ============================================================================
# D. `load_skill` 的运行期回话（每种"取不到"都必须说清，且绝不抛）
# ============================================================================


def test_load_skill_replies_are_explicit(monkeypatch):
    """★★★ 四种取数结果各有**明确文案**，且一律不抛异常。

    ★ 为什么文案是判据而不是装饰：
      · 「技能名空」 ⇒ 模型该去看目录挑一个，而不是自己拼一个名字；
      · 「功能未启用」⇒ 模型该**放弃**这条路径（文案里明说"不要重复调用"）；
      · 「没有找到」 ⇒ 模型该换成目录里的名字，且**不许编造**技能内容
        （不说这句，模型会自己"补"出一份技能正文 —— 那是纯幻觉）；
      · 都含糊成一样 ⇒ 模型只能靠猜，而猜的表现是"反复调用同一个工具"。

    ★ 还钉住「一个来源坏了不该拖垮本工具」：读取器抛异常时工具**照常返回字符串**，
      绝不把异常抛回 LangGraph 沙箱（那会打断整轮对话，而技能只是**增益**）。
    """
    import ai_infra.skills as skills_infra

    tool = skills_infra.build_skill_tools("some-agent")[0]

    # ① 空技能名
    empty_reply = _run_tool(tool, "")
    assert isinstance(empty_reply, str) and "技能名" in empty_reply, (
        f"空技能名的回话不对：{empty_reply!r}"
    )
    assert "目录" in empty_reply, (
        f"空技能名时应当引导模型去看目录，实际：{empty_reply!r}"
    )

    # ② 没有任何读取器
    monkeypatch.setattr(skills_infra, "_READERS", {})
    no_reader_reply = _run_tool(tool, "某个技能")
    assert "未启用" in no_reader_reply and "不要重复调用" in no_reader_reply, (
        f"没有读取器时的回话不对：{no_reader_reply!r} —— "
        f"必须说清是**功能未启用**（而不是「技能不存在」），并劝模型别重复调用。"
    )

    # ③ 读取器命中
    async def _hit(_user_id, _agent, _name):
        return "BODY-MARKER-181"

    monkeypatch.setattr(skills_infra, "_READERS", {"probe-hit": _hit})
    hit_reply = _run_tool(tool, "某个技能")
    assert hit_reply == "BODY-MARKER-181", (
        f"读取器命中时应当原样返回正文，实际：{hit_reply!r}"
    )

    # ④ 读取器返回 None（未启用 / 不存在 / 不属于本账号 —— 三者**不可分**）
    async def _miss(_user_id, _agent, _name):
        return None

    monkeypatch.setattr(skills_infra, "_READERS", {"probe-miss": _miss})
    miss_reply = _run_tool(tool, "某个技能")
    assert "没有找到" in miss_reply and "编造" in miss_reply, (
        f"读取器返回 None 时的回话不对：{miss_reply!r} —— "
        f"必须明说「找不到」并**禁止编造**，否则模型会自己补出一份技能内容（纯幻觉）。"
    )
    assert "BODY-MARKER-181" not in miss_reply, "未命中的回话里混进了上一次的结果"

    # ⑤ 读取器抛异常 ⇒ 工具照常返回字符串（不把异常抛回图）
    async def _boom(_user_id, _agent, _name):
        raise RuntimeError("来源炸了")

    monkeypatch.setattr(skills_infra, "_READERS", {"probe-boom": _boom})
    boom_reply = _run_tool(tool, "某个技能")
    assert isinstance(boom_reply, str) and boom_reply.strip(), (
        f"读取器抛异常时 `load_skill` 必须降级返回文案（技能是增益不是门禁），"
        f"实际拿到：{boom_reply!r}"
    )


# ============================================================================
# E. 两级披露的渲染契约
# ============================================================================


def test_catalog_carries_no_body():
    """★★★ 第一级披露**只能**带 `name` / `title` / `description`，绝不能带正文。

    ★ 这条是渐进披露的**全部价值**所在：目录要注入**每一次** LLM 调用，
      正文只在模型真的要用时才付 token。一旦有人「顺手」把 `content` 也渲染进
      目录，机制就退化成「全量常驻 system prompt」——
      功能完全正常、测试全绿、只有账单能看出来。

    ★ 反向注入：在 `render_skill_catalog` 里加一行 `body = _pick(item, "content")`
      并拼进 `rows` ⇒ 本条必须转红。
    """
    from ai_infra.skills import render_skill_catalog

    body_marker = "BODY-MUST-NOT-LEAK-INTO-CATALOG-181"
    rows = [
        {
            "name": "alpha",
            "title": "阿尔法",
            "description": "描述一",
            "content": body_marker,
            "body": body_marker,
        }
    ]
    txt = render_skill_catalog(rows)

    assert "alpha" in txt and "描述一" in txt, f"目录没带上名称/描述：{txt!r}"
    assert body_marker not in txt, (
        "★ 技能正文被渲染进了目录 —— 渐进披露退化成「全量常驻」，"
        "每次 LLM 调用都在为没人用到的技能正文付 token。"
    )


def test_catalog_is_empty_when_nothing_to_disclose():
    """没有可披露的技能时返回**空串**，而不是一段光秃秃的标题。

    ★ 空标题会白占 token，还会暗示模型「你有技能但都是空的」⇒ 它可能去调
      `load_skill` 试探。空串让 `collect_prompt_sections` 直接跳过这一段。
    """
    from ai_infra.skills import render_skill_catalog

    assert render_skill_catalog([]) == ""
    assert render_skill_catalog(None) == ""
    # 有行但没有名字 ⇒ 同样不披露（一条没有名字的技能在对话里毫无用处）
    assert render_skill_catalog([{"description": "没有名字"}]) == ""


def test_body_render_accepts_content_or_body_key():
    """第二级披露的渲染对 `content` / `body` 两种键名都认。

    ★ 为什么单列：目录表渲染走 ORM 行（字段名 `content`），
      而 `SkillDocument` 解析出来的字段叫 `body`。两者都真实存在 ——
      只认其中一个 ⇒ 走那条路径的技能正文**永远是空的**，而"加载成功但正文为空"
      与"加载失败"在模型侧完全不可分。
    """
    from ai_infra.skills import render_skill_body

    from_content = render_skill_body(
        {"name": "a", "title": "甲", "version": "1.0.0", "content": "正文A"}
    )
    from_body = render_skill_body({"name": "a", "title": "甲", "body": "正文A"})
    assert "正文A" in from_content, f"`content` 键没被认到：{from_content!r}"
    assert "正文A" in from_body, f"`body` 键没被认到：{from_body!r}"

    # 「加载成功但正文为空」必须与「加载失败」可分
    empty = render_skill_body({"name": "a", "title": "甲", "content": ""})
    assert empty.strip() and "没有配置正文" in empty, (
        f"正文为空时返回了空/含糊内容（{empty!r}）—— 模型会以为工具坏了并放弃这个技能。"
    )


def test_body_render_carries_bound_tools():
    """★★★ 绑定的工具必须随正文一起交给模型（第 185 轮）。

    ★ 为什么这条是「工具绑定」这件事**唯一有意义的证据**：

      第 185 轮之前，`skills.tools` 只被写进数据库、下发到界面，
      **没有任何执行侧消费者** —— `build_skill_tools()` 恒返回 1 个 `load_skill`，
      与有没有绑定完全无关。于是用户在界面上勾了工具，实际效果是**零**。
      本用例钉住它真的出现在 `load_skill` 的返回文本里。

    ★ 为什么必须附清单（而不是让模型自己挑）：模型的 `bind_tools` 清单
      **比技能声明的更宽**（同一 Agent 上挂着 5–9 个工具）。技能正文若只写
      "去设置主题"而没写"用 `set_theme`"，模型会在自己的工具表里**猜**一个名字
      —— 猜错就是一次无效调用。附上清单 = 把"用哪个工具"从猜测变成给定。

    ★ 反向注入：把 `render_skill_body` 末尾的 `render_skill_tools(...)` 调用
      去掉（或让其恒返回空串）⇒ 本条转红。
    """
    from ai_infra.skills import render_skill_body, render_skill_tools

    # ① 有工具 ⇒ 正文里带清单
    with_tools = render_skill_body(
        {"name": "a", "title": "甲", "content": "正文A", "tools": ["tool_x", "tool_y"]}
    )
    assert "tool_x" in with_tools and "tool_y" in with_tools, (
        f"绑定的工具没有随正文交给模型：{with_tools!r}\n"
        f"⇒ 界面上勾了工具、执行侧零效果 —— 「工具技能」变成纯装饰。"
    )
    assert "本技能配套工具" in with_tools, (
        "工具段缺少可识别的标题，模型难以把它与正文步骤关联起来"
    )

    # ② 没有工具 ⇒ **不加**这一段（一段空宣告只是白占 token）
    without = render_skill_body({"name": "a", "title": "甲", "content": "正文A", "tools": []})
    assert "本技能配套工具" not in without, "纯提示词技能也渲染了工具段（空宣告）"
    assert render_skill_tools(None) == ""
    assert render_skill_tools([]) == ""
    assert render_skill_tools("   ") == ""

    # ③ 输入形态：字符串 / 中文逗号 / 去重
    #    ★ DB 行给的是 `list`，而手写的技能文档可能写成 `tools: a, b`（字符串）。
    #      只认一种 ⇒ 另一种路径下工具**静默丢失**。
    assert "tool_x" in render_skill_tools("tool_x"), "字符串形态没被认到"
    both = render_skill_tools("tool_x，tool_y")
    assert "tool_x" in both and "tool_y" in both, f"中文逗号分隔没被拆开：{both!r}"
    dedup = render_skill_tools(["tool_x", "tool_x"])
    assert dedup.count("tool_x") == 1, f"重复项渲染了两遍：{dedup!r}"

    # ④ 正文为空时工具段**照样**出现（两件事正交）
    empty_body = render_skill_body(
        {"name": "a", "title": "甲", "content": "", "tools": ["tool_x"]}
    )
    assert "没有配置正文" in empty_body and "tool_x" in empty_body, (
        "正文缺失时把工具清单也一起丢了 —— "
        "一个只登记了绑定、还没写正文的技能，不该连工具提示都没了"
    )


# ============================================================================
# F. 读取器注册表的守卫（`register_skill_reader` 侧，此前无任何覆盖）
# ============================================================================


def test_duplicate_skill_reader_is_rejected():
    """重名注册必须当场报错，不能静默覆盖。

    ★ `register_skill_reader` 此前**没有任何用例覆盖**（`test_memory_injection.py`
      只覆盖了 `register_prompt_section`）。而它的静默覆盖后果更隐蔽：
      `_combined_reader()` 按注册顺序取第一个非空结果 ⇒ 被覆盖掉的那个来源
      **永远取不到**，而两边都不报错。
    """
    import modules.skills.router  # noqa: F401  —— 确保 READER_NAME 已注册
    from ai_infra.skills import register_skill_reader

    async def _r(_user_id, _agent, _name):
        return "x"

    with pytest.raises(ValueError):
        register_skill_reader(READER_NAME, _r)

    with pytest.raises(ValueError):
        register_skill_reader("   ", _r)

    with pytest.raises(TypeError):
        register_skill_reader("r181-not-callable", "字符串不是读取器")
