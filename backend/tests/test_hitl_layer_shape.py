# -*- coding: utf-8 -*-
"""`modules/hitl/` 的**形态**门禁（第 400 轮 P0-2）。

## 这一层为什么需要形态门禁

它的全部价值在于「与具体业务无关」。一旦某个函数体内出现
`from modules.customer_service import ...`，它立刻退化成"两个业务模块的
公共依赖"，而下一个想复用它的人会绕开它再抄一份 ——
第 399 轮的洞就是这样长出来的（审批逻辑住在选品模块里，客服就用不上）。

## 三条判据

1. `test_no_business_imports` —— AST 扫 import，除 `core.*` / `langgraph.*` /
   `langchain_core.*` / 同包相对导入外一律违规。
   ★ `registry.py` 里的业务模块路径是**字符串常量**（惰性 import 用），
     AST 的 import 节点里看不到它们 —— 这正是"分发表与实现解耦"的形态，
     下面第 3 条单独钉住它。
2. `test_public_surface_is_frozen` —— `hitl.py` 的公开函数集合冻结。
   增删都要改这份清单（否则"少了一个函数"会静默变成"某处审批静默不弹卡"）。
3. `test_registry_paths_are_lazy_strings` —— `RESUME_SPECS` 的 `module`
   必须指向**真实存在**的模块，且 `modules/hitl` 里不许真 import 它。
   前者防拼错（拼错只在点批准那一刻 500），后者防退化。

## 反向注入

`r400i_inject_hitl_layer.py`：
  · 往 `hitl.py` 加一行 `from modules.customer_service import service` ⇒ 判据 1 红
  · 从 `REGISTRY`/`RESUME_SPECS` 删一项 ⇒ 判据 2 或 3 红
"""
import ast
import importlib
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PKG = BACKEND / "modules" / "hitl"

#: 允许的**绝对** import 前缀（同包相对导入另行放行）
ALLOWED_PREFIXES = (
    "core.",
    "langgraph.",
    "langchain_core.",
    "modules.hitl",   # 同包内部（`router.py` 用 `from modules.hitl.registry import ...`）
    "__future__",     # `from __future__ import annotations`
    "typing",
    "json",
    "importlib",
    "dataclasses",
    "fastapi",
    "pydantic",
)

#: `hitl.py` 必须导出的公开函数（集合相等，增删都要改这里）
HITL_PUBLIC_FUNCS = frozenset({
    "pending_approval_payload",
    "build_resume_payload",
    "unwrap_hitl_tool_output",
    "detect_pending_approval",
    "resume_approval",
})


def _py_files():
    return sorted(p for p in PKG.glob("*.py"))


def _absolute_imports(tree: ast.Module):
    """本模块里出现的**绝对** import 目标（忽略相对导入）。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入：`from .x import y` —— 同包内部，放行
                continue
            if node.module:
                out.append(node.module)
                for a in node.names:
                    out.append(f"{node.module}.{a.name}")
    return out


def test_no_business_imports():
    """★ 中立层不许 import 任何业务模块。

    它唯一的"业务知识"是 `RESUME_SPECS` 里的**字符串**路径（惰性 import），
    AST 的 import 节点里看不到 —— 若哪天变成真 import，本判据立刻红。
    """
    bad = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for target in _absolute_imports(tree):
            if not target.startswith(ALLOWED_PREFIXES):
                bad.append(f"{path.name}: import {target}")
    assert not bad, (
        "modules/hitl 出现了业务/第三方依赖 —— 这一层的价值就是「与业务无关」：\n  "
        + "\n  ".join(sorted(set(bad)))
        + "\n  需要业务能力时，把它作为 **callable 参数**传进来（本层不 import）。"
    )


def test_public_surface_is_frozen():
    """★ `hitl.py` 的公开函数集合冻结。

    ★ 为什么冻结而不是"至少包含"：少一个函数的后果是**静默的** ——
      比如 `detect_pending_approval` 消失，所有审批卡都不再出现，
      而每一轮对话都"正常"返回一段文本，任何端到端测试都不会红。
    """
    tree = ast.parse((PKG / "hitl.py").read_text(encoding="utf-8"))
    funcs = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    }
    assert funcs == HITL_PUBLIC_FUNCS, (
        "modules/hitl/hitl.py 的公开函数集合变了：\n"
        f"  多了：{sorted(funcs - HITL_PUBLIC_FUNCS) or '无'}\n"
        f"  少了：{sorted(HITL_PUBLIC_FUNCS - funcs) or '无'}\n"
        "  增删都要同步本清单，并说明调用方怎么跟着改。"
    )


def test_registry_paths_are_lazy_strings():
    """★ 登记表指向的模块必须真实存在，且本包没有 import 它们。

    前半句防拼错：`get_resumer()` 是惰性 import，路径拼错时**启动不报错**，
    只有用户点下"批准"那一刻 500 —— 那是"审批点了没反应"最贵的失败方式。
    后半句防退化：一旦本包 import 了某个业务模块，`registry` 就从"分发表"
    变成"聚合器"，循环 import 与启动期拉全业务都会随之而来。
    """
    import modules.hitl.hitl  # noqa: F401 —— 确保包能导入（否则下面的断言无意义）
    from modules.hitl.registry import RESUME_SPECS

    assert RESUME_SPECS, "RESUME_SPECS 为空 —— 审批闭环失去全部入口"

    for spec in RESUME_SPECS:
        mod = importlib.import_module(spec.module)  # 不存在会直接抛 ImportError
        assert mod is not None

    # 反向：本包源码里除了同包（`modules.hitl.*`）之外，不许出现任何 `modules.…` import。
    # ★ 用 AST 而不是字符串匹配 —— 上一版用 `"from modules." not in src` 判，
    #   把**同包**的 `from modules.hitl.registry import ...` 也算成了违规
    #   （假红），而且注释里提到 `from modules.xxx` 同样会误判。
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        foreign = [
            t for t in _absolute_imports(tree)
            if t.startswith("modules.") and not t.startswith("modules.hitl")
        ]
        assert not foreign, (
            f"{path.name} 里出现了对**其它业务模块**的 import —— 中立层开始依赖业务了：\n  "
            + "\n  ".join(sorted(set(foreign)))
        )
