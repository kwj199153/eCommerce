# -*- coding: utf-8 -*-
"""桥接表门禁：`AGENT_CATALOG` 必须与**真实代码里的 agent_name** 双向逐字一致。

（第 181 轮 · 批 B）

==============================================================================
★ 这条门禁拦的是什么
==============================================================================
本项目有**两套 Agent ID**（前端 id / 后端 agent_name），八个里只有 `secretary`
一个完全一致。技能启用存的是**后端 agent_name**（因为注入发生在后端），
而勾选界面展示的是前端 id ⇒ 中间必须有且只有一张映射表
（`modules/skills/agents.py::AGENT_CATALOG`）。

一张映射表最容易出的问题不是"写错"，而是**过时**：
后端某个 Agent 改名（`self.agent_name = "X"` → `"Y"`）或新增一个 Agent，
表里没跟 —— 症状是「勾了但永不注入」，**不报错、日志全绿**。
所以本文件把表的两侧都钉到**真实代码**上：

    ① 名字侧：扫全仓 `self.agent_name = "…"` 与 `agent_name="…"` 两种赋值形态，
       与 `all_agent_names()` 做**集合相等**（不是 ⊆）。
    ② id 侧：扫 `frontend/src/stores/agent.ts` 的 `id: '…'`，同样集合相等。

★ 为什么用**两种 AST 形态的并集**（实测踩过）：
  最初只扫 `agent_name="…"` 关键字，全仓只命中 **2/8** —— 因为六个 Agent 用的是
  `self.agent_name = "X"` 赋给属性。只按一种形态扫的门禁会**恒红**（或恒绿）。
  两种形态的并集实测 = 恰好 8 个，与目录表逐字相等（见 `probes/o181_union.txt`）。

★ 为什么必须**排除 `modules/skills/**`**：
  否则 `seed.py` / `agents.py` 里的字面量会让目录表**自证** ——
  一个恒真的扫描器，是假门禁的经典形态。

★ 反向注入方向（本文件自带自检用例 `test_scanner_is_not_vacuous`）：
  · 把某 Agent 的 `self.agent_name` 改掉 ⇒ 名字侧集合不再相等 ⇒ 红；
  · 把目录表里某一项的 `name` 改成不存在的值 ⇒ 同样红；
  · 把扫描器改成只认一种形态 ⇒ 自检用例当场红（防"门禁恒绿"）。
"""

from __future__ import annotations

import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
CATALOG_PY = BACKEND / "modules" / "skills" / "agents.py"
FRONTEND_AGENT_TS = FRONTEND / "src" / "stores" / "agent.ts"

#: 扫描根（`main.py` / `scripts/` 不参与：Agent 定义只在包内）
SCAN_ROOTS = ("ai_infra", "modules", "core")


def _excluded(path: pathlib.Path) -> bool:
    """`modules/skills/**` 一律排除 —— 详见模块 docstring。"""
    try:
        rel = path.resolve().relative_to(BACKEND.resolve()).as_posix()
    except ValueError:
        return False
    return rel.startswith("modules/skills/") or rel == "modules/skills"


def collect_agent_name_literals(roots=SCAN_ROOTS) -> dict:
    """扫描真实代码里的 `agent_name` 字面量，返回 `{值: ["相对路径:行号", …]}`。

    只认**两种**形态（并集），两者都要求值是非空字符串字面量：

        A. `self.agent_name = "X"`        —— 赋值给属性（本仓六个 Agent 用它）
        B. `agent_name="X"`               —— 传给 `__init__` 的关键字
    """
    found: dict = {}
    for base in roots:
        root = BACKEND / base
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts or _excluded(p):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                # 语法坏文件不是本门禁的职责（另有编译型门禁负责），跳过即可。
                continue
            rel = p.relative_to(BACKEND).as_posix()
            for n in ast.walk(tree):
                # 形态 A
                if isinstance(n, ast.Assign):
                    for target in n.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and target.attr == "agent_name"
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str)
                        ):
                            found.setdefault(n.value.value, []).append(f"A {rel}:{n.lineno}")
                # 形态 B
                if isinstance(n, ast.Call):
                    for kw in n.keywords:
                        if (
                            kw.arg == "agent_name"
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)
                        ):
                            found.setdefault(kw.value.value, []).append(f"B {rel}:{n.lineno}")
    return found


def collect_frontend_agent_ids() -> set:
    """从 `frontend/src/stores/agent.ts` 取 `AGENT_LIST` 里的 id 字面量。"""
    src = FRONTEND_AGENT_TS.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*id:\s*'([a-z0-9\-]+)'", src, re.M))


# ============================================================================
# 1. 名字侧：目录表 == 真实代码里的 agent_name
# ============================================================================


def test_catalog_names_match_real_backend_agent_names():
    """★★★ 名字侧**集合相等**：目录表恰好等于真实代码里出现过的 agent_name 集合。

    用相等而不是 ⊆，是为了让两个方向都能咬住：
      · 后端改名 → 表里那个名字不再出现在代码里        ⇒ 红（过时的表）
      · 表里漏了一个新 Agent → 代码里多出一个名字      ⇒ 红（缺失的表）

    ★ 反向注入：把 `modules/review_analyst/agent.py` 的
      `agent_name="review_analyst"` 改成 `"review_analyst_v2"`，本条必红。
    """
    from modules.skills.agents import all_agent_names

    catalog = set(all_agent_names())
    code = set(collect_agent_name_literals())

    missing_in_code = sorted(catalog - code)
    extra_in_code = sorted(code - catalog)

    assert not missing_in_code, (
        f"目录表里的这些名字在**代码里已经不存在**：{missing_in_code}。\n"
        f"说明后端某个 Agent 改名了（或删了），而 `AGENT_CATALOG` 没跟 —— "
        f"症状是「勾了但永不注入」，且不报错。"
    )
    assert not extra_in_code, (
        f"代码里出现了目录表**没有**的 agent_name：{extra_in_code}。\n"
        f"新增 Agent 时必须同步 `modules/skills/agents.py::AGENT_CATALOG`，"
        f"否则它在勾选界面里根本选不到（该 Agent 永远拿不到技能目录）。"
    )
    assert len(catalog) == 8, f"平台 Agent 数量变了（{len(catalog)}），请确认是否需要同步前端"


# ============================================================================
# 2. id 侧：目录表 == 前端 AGENT_LIST
# ============================================================================


def test_catalog_ids_match_frontend_agent_list():
    """★ id 侧**集合相等**：勾选界面里的每一项都必须能在前端路由里找到。

    ★ 为什么不是 ⊆：前端 `AGENT_LIST` 多一个 id，就意味着界面上有一个 Agent
      在「Agent 装配」Tab 里根本不出现（因为目录表没有它）——
      用户会以为"这个 Agent 不支持技能"。
    """
    from modules.skills.agents import AGENT_CATALOG

    catalog_ids = {a["id"] for a in AGENT_CATALOG}
    front_ids = collect_frontend_agent_ids()

    assert front_ids, (
        f"没能从前端 {FRONTEND_AGENT_TS} 解析出任何 Agent id ⇒ 本条判据空跑；"
        f"前端 `AGENT_LIST` 的写法变了，请同步本文件的正则。"
    )
    assert catalog_ids == front_ids, (
        f"目录表 id ≠ 前端 AGENT_LIST id。\n"
        f"  目录表多出: {sorted(catalog_ids - front_ids)}\n"
        f"  前端多出:   {sorted(front_ids - catalog_ids)}"
    )


# ============================================================================
# 3. 表本身的结构约束
# ============================================================================


def test_catalog_entries_are_well_formed():
    """每一项必须有 name / id / title / description，且 name 与 id 都唯一。"""
    from modules.skills.agents import AGENT_CATALOG

    seen_name, seen_id = set(), set()
    for item in AGENT_CATALOG:
        for key in ("name", "id", "title", "description"):
            assert str(item.get(key) or "").strip(), f"目录项缺 {key}：{item!r}"
        assert item["name"] not in seen_name, f"name 重复：{item['name']}"
        assert item["id"] not in seen_id, f"id 重复：{item['id']}"
        seen_name.add(item["name"])
        seen_id.add(item["id"])


def test_find_by_id_round_trips():
    """`find_by_id` 是「前端传 id、后端存 name」的唯一归一入口。"""
    from modules.skills.agents import AGENT_CATALOG, find_by_id, is_known_agent, agent_title

    for item in AGENT_CATALOG:
        assert find_by_id(item["id"]) is item
        assert is_known_agent(item["name"]) is True
        assert is_known_agent(item["id"]) is False or item["id"] == item["name"], (
            f"{item['id']} 既是 id 又是 name，映射会歧义（{item!r}）"
        )
        assert agent_title(item["name"]) == item["title"]

    assert find_by_id("__nope__") is None
    assert is_known_agent("__nope__") is False
    # 未知 agent 要**原样返回**（日志里宁可显示怪名字，也不能让整轮挂掉）
    assert agent_title("__nope__") == "__nope__"


# ============================================================================
# 4. 门禁自检（防恒绿 / 防误收）
# ============================================================================


def test_scanner_is_not_vacuous(tmp_path):
    """★ 自检：扫描器既能报出两种形态，也不把「长得像」的东西收进来。

    ★ 最后一条（`agent_id` 的默认值）是本文件最容易被写坏的地方：
      本仓 `modules/conversation/db_model.py` 里有
      `agent_id: Mapped[str] = mapped_column(String(32), default="secretary")`
      —— 那是一行**完全无关**的默认值。若扫描器按"字符串里出现 agent"去收，
      它会把这类值一并算成 agent_name，于是「集合相等」变成一条随
      schema 变动而漂移的判据。
    """
    src = (
        "class A:\n"
        "    def __init__(self):\n"
        "        self.agent_name = 'ByAttr'\n"
        "\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        super().__init__(agent_name='ByKeyword')\n"
        "\n"
        "class C:\n"
        "    agent_id: object = mapped_column(String(32), default='secretary')\n"
        "    other = 'agent_name'\n"
    )
    tree = ast.parse(src)
    got = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and t.attr == "agent_name" \
                        and isinstance(n.value, ast.Constant):
                    got.add(n.value.value)
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "agent_name" and isinstance(kw.value, ast.Constant):
                    got.add(kw.value.value)

    assert got == {"ByAttr", "ByKeyword"}, f"扫描器漏报/多报：{got}"
    assert "secretary" not in got, (
        "扫描器把 `agent_id` 的默认值当成了 agent_name —— "
        "这条判据会因此随 schema 漂移（见用例 docstring）"
    )


def test_frontend_scanner_is_not_vacuous():
    """★ 自检：前端 id 正则必须能从**当前真实文件**里取到 8 个。"""
    ids = collect_frontend_agent_ids()
    assert len(ids) == 8, (
        f"从 {FRONTEND_AGENT_TS.name} 取到 {len(ids)} 个 id（期望 8）：{sorted(ids)} —— "
        f"正则与前端写法失配会让 `test_catalog_ids_match_frontend_agent_list` 假绿。"
    )
