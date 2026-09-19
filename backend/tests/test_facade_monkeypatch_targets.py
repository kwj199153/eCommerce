"""门面 re-export 与 monkeypatch 打桩目标的**一致性**门禁（第 140 轮）。

━━━ 缺陷形态（本轮实测，一次真的把全量回归打红）━━━

`modules/<pkg>/__init__.py` 成为门面（re-export）之后：

    modules.candidates.create_candidate           ← 门面里的绑定（re-export 拷贝）
    modules.candidates.service.create_candidate   ← 定义处的绑定

**这是两份独立的名字绑定。** 生产代码按 G-1 门禁**只从门面取名字**，
于是测试若把桩打在 `modules.candidates.service` 上 ⇒ **桩永远不被查到** ⇒
真函数照常执行。

━━━ 实测症状 ━━━

`tests/test_hitl_wiring.py::test_save_candidate_tool_passes_shop_id`：

  · 桩完全没生效，真 `create_candidate` 拿一个**不存在的 shop_id** 去写库
  · 撞外键 → 被上层 `_write_candidates` 吞成「写入选品库失败（数据库不可用）」
  · 断言红，但报错**指向数据库** —— 与真因（打桩目标错）隔了十万八千里

━━━ 为什么必须用门禁钉住，而不是「下次注意」 ━━━

打桩目标错有两种后果，其中一种**不会红**：

  · **红**：用例断言「桩被调用过」⇒ 立刻暴露（本轮算走运，是这种）
  · **静默**：用例只断言「返回了一个可读的失败文案」⇒
    生产的硬拒绝恰好满足它 ⇒ **测试因为错误的原因通过**，
    而它想守的那条防线**一次都没被验证**（实测：`test_shop_id_guard.py` 两处即此形态）

第二类是本门禁存在的理由：**它不会自己暴露。**

━━━ 判据（作用域：`tests/**`）━━━

对每处 `monkeypatch.setattr(<obj>, "<name>", ...)`：

  若 `<name>` 被某个门面包 `modules.<pkg>` 的 `__all__` 导出（= 跨模块契约面），
  则 `<obj>` 解析出的模块**必须是门面本身**（`modules.<pkg>`），
  不得是它的子模块（`modules.<pkg>.<sub>`）。

★ **反向不成立**：`<name>` 不在门面 `__all__` 里时**放行** ——
  那说明它不是跨模块契约面（包内自用），打在子模块上是正常的。
  实测全仓 102 处 `setattr`，本判据只命中 6 处，无误报。
"""
from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_TESTS = _BACKEND / "tests"
_CP_SKIP = {"__pycache__", ".venv", "venv"}


# ============================ 判据实现（纯函数，便于自检） ============================


def facade_exports(modules_dir: Path) -> dict[str, frozenset[str]]:
    """`modules.<pkg>` -> 该门面**从子模块 re-export** 出去的名字集合。

    只把「`__all__` 里列了、且确实由顶层 `ImportFrom` 绑定进来的」算作契约面。
    `__all__` 里但**没有对应绑定**的名字（笔误 / 漏 import）不算 ——
    那种情况由 G-1 门禁的另一条去管。
    """
    out: dict[str, frozenset[str]] = {}
    for init in sorted(modules_dir.glob("*/__init__.py")):
        src = init.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        tree = ast.parse(src)
        declared: set[str] = set()
        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    declared |= {
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    }
            elif isinstance(node, ast.ImportFrom):
                bound |= {a.asname or a.name for a in node.names}
        kept = declared & bound
        if kept:
            out[f"modules.{init.parent.name}"] = frozenset(kept)
    return out


def _aliases(source: str) -> dict[str, str]:
    """本文件里 `名字 -> 它指向的点分模块名`（用于把 setattr 的第一个实参解析成模块）。"""
    alias: dict[str, str] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    alias[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    alias[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name == "*":
                    continue
                alias[a.asname or a.name] = f"{node.module}.{a.name}"
    return alias


def _expr_to_dotted(node: ast.AST) -> str:
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _resolve(oexpr: str, alias: dict[str, str]) -> str:
    head, *rest = oexpr.split(".")
    base = alias.get(head, head)
    return ".".join([base] + rest) if rest else base


def scan_source(
    source: str, label: str, exports: dict[str, frozenset[str]]
) -> list[str]:
    """返回违规说明列表；空列表 = 该文件没有「打在门面子模块上」的桩。"""
    alias = _aliases(source)
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "setattr"):
            continue
        if len(node.args) < 2:
            continue
        name = node.args[1]
        if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            continue
        oexpr = _expr_to_dotted(node.args[0])
        if not oexpr:
            continue
        modname = _resolve(oexpr, alias)
        if not modname.startswith("modules."):
            continue
        parts = modname.split(".")
        pkg = ".".join(parts[:2])
        if pkg not in exports:
            continue
        if name.value not in exports[pkg]:
            continue
        if len(parts) > 2:
            bad.append(
                f"{label}:{node.lineno}  打桩错目标：setattr({oexpr!r}, {name.value!r})\n"
                f"        实际作用于 {modname}.{name.value}\n"
                f"        但生产代码从**门面**取名字 ⇒ 应改为 setattr({pkg}, {name.value!r})"
            )
    return bad


def _all_violations() -> list[str]:
    exports = facade_exports(_BACKEND / "modules")
    out: list[str] = []
    for p in sorted(_TESTS.rglob("test_*.py")):
        if any(part in _CP_SKIP for part in p.parts):
            continue
        src = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        out += scan_source(src, p.relative_to(_BACKEND).as_posix(), exports)
    return out


# ==================================== 用例 ====================================


def test_no_monkeypatch_targets_a_facade_submodule():
    """★ 打桩必须打在**门面**上 —— 打在子模块上的桩永远不被查到。"""
    bad = _all_violations()
    assert not bad, (
        "以下 monkeypatch 打桩打在**门面子模块**上，而该名字由门面导出 ⇒ "
        "生产代码走门面、桩永不生效（症状：真函数照跑；轻则断言红、"
        "重则**测试因错误的原因通过**）：\r\n\r\n"
        + "\r\n".join(bad)
        + "\r\n\r\n修法：把 import 的模块从 `modules.<pkg>.<sub>` 改成 `modules.<pkg>`，"
          "别名可保持不变。"
    )


def test_facade_exports_are_discovered():
    """非空自检：门面索引不能是空的，否则上面的断言恒真。"""
    exports = facade_exports(_BACKEND / "modules")
    assert len(exports) >= 5, f"只识别出 {len(exports)} 个门面，判据可疑：{sorted(exports)}"
    # 抽一个有代表性的门面，断言它的出口被正确识别
    assert "create_candidate" in exports.get("modules.candidates", frozenset()), (
        f"modules.candidates 的出口识别失败：{exports.get('modules.candidates')}"
    )
    total = sum(len(v) for v in exports.values())
    assert total >= 15, f"门面出口总数只有 {total}，疑似只扫到部分门面"


def test_setattr_scanner_is_not_vacuous():
    """★ 反向注入自检：扫描器必须能报出违规样本，也必须放过合法形态。

    三组，缺任一组这个门禁都可能是恒绿的：
      ① 打桩在**子模块**上 + 名字由门面导出      ⇒ 必须报
      ② 打桩在**门面**上                          ⇒ 必须放过
      ③ 打桩在子模块上但名字**不由门面导出**      ⇒ 必须放过（包内自用的正常形态）
    """
    exports = {"modules.demo": frozenset({"do_write"})}

    bad = scan_source(
        "import modules.demo.service as svc\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(svc, 'do_write', lambda *a, **k: None)\n",
        "<synthetic-bad>",
        exports,
    )
    assert len(bad) == 1, f"① 未报出违规样本：{bad}"

    ok_facade = scan_source(
        "import modules.demo as svc\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(svc, 'do_write', lambda *a, **k: None)\n",
        "<synthetic-ok-facade>",
        exports,
    )
    assert ok_facade == [], f"② 合法形态被误报：{ok_facade}"

    ok_internal = scan_source(
        "import modules.demo.service as svc\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(svc, 'internal_helper', lambda *a, **k: None)\n",
        "<synthetic-ok-internal>",
        exports,
    )
    assert ok_internal == [], f"③ 非契约面名字被误报：{ok_internal}"

    # ④ 属性链形态（无别名）也要认出来
    bad_chain = scan_source(
        "import modules.demo.service\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(modules.demo.service, 'do_write', lambda *a, **k: None)\n",
        "<synthetic-bad-chain>",
        exports,
    )
    assert len(bad_chain) == 1, f"④ 属性链形态未报出：{bad_chain}"


def test_scanner_actually_covers_the_test_tree():
    """非空自检：确认真扫到了 tests/ 且解析出了足够多的 setattr 调用。

    ★ 只断言「违规为空」是恒真的 —— 一个 `rglob` 都匹配不到时它也是空。
      所以这里断言的是**扫描量**。
    """
    files = [
        p for p in sorted(_TESTS.rglob("test_*.py"))
        if not any(part in _CP_SKIP for part in p.parts)
    ]
    assert len(files) >= 20, f"只扫到 {len(files)} 个测试文件，路径解析可疑"

    calls = 0
    for p in files:
        src = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "setattr" and len(node.args) >= 2:
                calls += 1
    assert calls >= 50, f"只解析出 {calls} 处 setattr，扫描器可能没真正工作"
