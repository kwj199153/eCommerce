# -*- coding: utf-8 -*-
"""源码读取的**唯一真源**：单文件 ⇄ 包，双态（第 355 轮引入）。

## 为什么需要它（这不是「抽象美观」，是本仓踩了两次的坑）
把 `X.py` 拆成 `X/` 包时，所有**按路径读源码**的判据都会失配 ——
而且失配形态有三种，全都不好定位（详见 `.workbuddy/memory/_pending/第355轮.md` §6）：

1. 测试里写 `(BACKEND / "modules" / "a" / "x.py").read_text()` ⇒ **收集期**
   `FileNotFoundError`，表现成「非红非绿」（连用例都没跑起来）；
2. 登记表里存的路径（`{"modules/a/x.py": ...}`）⇒ 同上；
3. AST 棘轮按单文件数调用点 ⇒ 不崩，但**口径悄悄变窄**（棘轮基线失去意义）。

`modules/trade/service.py`（第 355 轮拆包）、`modules/customer_service/agent_cs.py`
（待拆）各点出 4~5 处。**同一个「怎么读一坨源码」的判定若多处实现，
必然至少一份永远测不到**（本仓明令禁止两份实现）⇒ 收口到这里。

## 契约
- `source_files(rel)`：`rel` 指向**文件** ⇒ `[该文件]`；
  指向**包目录** ⇒ 目录内 `*.py`（按文件名排序 ⇒ 顺序稳定）；
  两者都不存在 ⇒ 抛 `FileNotFoundError`（**显式报错，绝不返回空列表**——
  空集合会让所有 AST 判据变成「什么都没找到」的假绿）。
- `read_source(rel)`：把上述文件拼成一段文本，行尾**统一归一化为 LF**
  （既有判据全都自己 `.replace("\\r\\n", "\\n")`，在这里做一次，消费方不必各自再做）。
- 消费方**不得依赖行号**：判据一律按**符号名**定位（`ast.walk` + `n.name`），
  拼接顺序不影响它们。

★ `rel` 同时接受 `str` 与 `Path`：调用点既有仓库相对路径
  （登记表里存的形态：`"modules/customer_service/agent_cs.py"`），
  也有已解析的绝对路径（`BACKEND / ...`）。两种既有写法都要能用，
  否则每个调用点都得自己先拼一遍路径 —— 那又是各写一份。
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]


def _abs(rel: str | Path) -> Path:
    """把仓库相对路径 / 绝对路径统一成绝对路径（不校验存在性）。"""
    p = Path(rel)
    return p if p.is_absolute() else _BACKEND / p


def _py_files_in(directory: Path) -> list[Path]:
    files = sorted(p for p in directory.glob("*.py") if p.is_file())
    if not files:
        raise FileNotFoundError(
            f"{directory} 是目录，但里面没有任何 .py 文件 —— "
            "判据会恒真（什么都扫不到），拒绝静默放过"
        )
    return files


def source_files(rel: str | Path) -> list[Path]:
    """解析 `rel` → 源码文件列表（单文件 1 项 / 包内全部 `.py`）。

    Raises:
        FileNotFoundError: 既不是文件、也不是（同名）包目录，或包目录为空。
    """
    base = _abs(rel)
    if base.is_file():
        return [base]
    if base.is_dir():
        return _py_files_in(base)
    # 登记表里存的是 `.py` 文件名，拆包后实际是**同名目录**⇒ 再试一次无后缀形态
    if base.suffix:
        pkg = base.with_suffix("")
        if pkg.is_dir():
            return _py_files_in(pkg)
    raise FileNotFoundError(
        f"找不到源码：{base}"
        + (f"（同名包 {base.with_suffix('')} 也不存在）" if base.suffix else "")
    )


def read_source(
    rel: str | Path, *, expect: str | Iterable[str] | None = None
) -> str:
    """把 `rel` 对应的**全部**源码拼成一段文本（LF 归一化）。

    Args:
        expect: 可选的**正向锚点**（一个或多个）。给定时会断言它们都出现在
            读到的文本里 —— 用来挡住「读取点选错了文件集」这类失配：
            文件集错了，静态判据（`"X" not in src`）会**恒真通过**，比报错难查得多。
            ★ 锚点必须是「只有读对了才可能出现」的符号，且**必须先在文件里
              实测存在**（本仓铁律：needle 不存在 ⇒ 判据恒真空跑）。
            ★ 给**多个**锚点时建议取自**不同文件** —— 那样同时证明拼接覆盖了整包，
              而不只是其中第一个文件。
    """
    files = source_files(rel)
    text = "\n".join(
        p.read_bytes().decode("utf-8").replace("\r\n", "\n") for p in files
    )
    if expect is not None:
        anchors = (expect,) if isinstance(expect, str) else tuple(expect)
        missing = [a for a in anchors if a not in text]
        if missing:
            raise AssertionError(
                f"读了 {len(files)} 个文件却找不到锚点 {missing}：{_abs(rel)}\n"
                f"      文件集：{[p.name for p in files]}\n"
                "      ⇒ 读取点选错了，或判据窗口与实际模块形态不一致"
            )
    return text


def parse_module(rel: str | Path) -> ast.Module:
    """把 `rel`（**文件或包**）解析成**单个** `ast.Module`。

    包时把各文件的 `body` 拼进同一个 Module。这在本仓的用法下**等价于逐文件解析**：
    这些判据只扫「源码**形态**」（`tools=` 实参、模块级 `x = ...` 赋值、
    某个函数的定义体），**不依赖跨文件作用域** —— 因此拼接不会引入
    「名字在别的文件里定义了」这类假阴/假阳。

    ★ 这条能力必须只有一份实现：`test_agent_tool_wiring::_parse`、
      `test_tool_catalog::_tools_expr_nodes`、`test_thinking_trace::_merged_tree`
      都要它 —— 各写一遍就是「同一判定多份实现」（本仓明令禁止，且拆包时必然漂移）。
      ★ 第 356 轮实测：`test_thinking_trace::_merged_tree` **确实**自己抄了一份
        逐字相同的合并逻辑（它是「扫描 `modules/**/agent*` 后合并」，不是按 `rel`
        解析，所以当时没走 `parse_module`）⇒ 本轮抽 `merge_files` 收口。
    """
    return merge_files(source_files(rel))


def merge_files(files: list[Path]) -> ast.Module:
    """把若干源文件的 AST 合并成**一棵** `ast.Module`（本仓**唯一**的合并实现）。

    单文件时走 `ast.parse` 快路径（保留 `type_ignores`），多文件时拼 `body`。

    ★ 消费方：`parse_module`（按 `rel` 解析）与 `test_thinking_trace::_merged_tree`
      （按已发现的文件列表合并）。**新增消费方请调本函数，不要再抄一份**。
    """
    if len(files) == 1:
        return ast.parse(files[0].read_bytes().decode("utf-8", "replace"))
    merged = ast.Module(body=[], type_ignores=[])
    for f in files:
        merged.body.extend(ast.parse(f.read_bytes().decode("utf-8", "replace")).body)
    return merged


def class_mro_body(tree: ast.Module, cls_name: str) -> list[ast.AST] | None:
    """该类**及其全部（递归）基类**的类体节点（同一棵 tree 内按名解析）；无此类 → `None`。

    ★ 为什么必须沿基类递归（第 356 轮实测的真回归）：
      mixin 拆包后 `class CustomerServiceAgent(MixinCore, MixinFaq, ..., BaseAgent)`
      的**自身类体几乎是空的** —— `__init__` / 装配点 / `_build_router` 全住在
      `MixinCore` 等 mixin 里。任何「只看 `cls.body`」的判据都会判「没有」，
      而「没有」在这些判据里往往等于**真空通过**（`all(...)` 恒真）或**报错转红**，
      两种都不是真话。按基类名递归 = 复刻 Python 的方法查找 ⇒ 语义与拆包前**等价**
      （既没放宽，也没把窗口扩大到「整个包随便哪个类」）。

    ★ 前提：`tree` 必须是**合并后**的树（包 ⇒ `parse_module` / `merge_files`）。
      逐文件解析时跨文件的基类解析不到 ⇒ 又退回「只看类体」的老病。因此
      `parse_module` 的「不得依赖行号」约束在此同样适用：合并后 `lineno` 只是
      **该节点在其原文件内**的行号，不能用来拼「路径:行号」去定位。

    ★ 消费方：`test_thinking_trace::_class_methods`、
      `test_hitl_policy::_assembly_facts`。**新增消费方请调本函数，不要再抄一份。**
    """
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    if cls_name not in defs:
        return None
    out: list[ast.AST] = []
    seen: set[str] = set()

    def walk_bases(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        node = defs.get(name)
        if node is None:
            return
        out.extend(node.body)
        for base in node.bases:
            if isinstance(base, ast.Name):
                walk_bases(base.id)
            elif isinstance(base, ast.Attribute):
                walk_bases(base.attr)

    walk_bases(cls_name)
    return out
