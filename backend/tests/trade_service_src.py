# -*- coding: utf-8 -*-
"""trade 服务层**源码文本**的读取点（第 355 轮引入；第 356 轮起改为通用实现的薄封装）。

## 为什么需要它
`modules/trade/service.py`（2535 行）在第 355 轮拆成了 `modules/trade/service/`
包（8 个子模块 + `__init__.py`）。有门禁要读它的源码做 AST 形态判据
（`test_trade_review_binding` / `test_trade_review_risk_view` /
`test_trade_systemic_check`）。

若每个门禁各自写一份「怎么把包拼回一段源码」——那就是**同一判定多份实现**
（本仓明令禁止）：包结构一变，多处漂移，且漂移是静默的。

## 与 `tests/pkg_source.py` 的分工（避免「两份实现」）
第 356 轮处理「`agent_cs.py` 待拆」时发现同一个读取需求在本仓已有第二处、
且还会继续变多 ⇒ 通用能力（单文件 ⇄ 包双态、LF 归一化、空集合显式报错）
上收到 `tests/pkg_source.py`。**本文件只保留 trade 的「读取点」语义**
（包在哪 + 一个稳定的公开函数名），实现一律委托，禁止在这里再写一遍拼包逻辑。

## 契约
- `read_service_source()` 返回**包内全部 `.py` 的拼接文本**，顺序固定（文件名排序）。
- 行尾一律归一化为 `LF`（消费方不必各自再做）。
- 消费方**不得依赖行号**：所有判据都按**符号名**定位
  （`ast.walk` + `n.name`），拼接顺序不影响它们。
"""

from __future__ import annotations

from pathlib import Path

from pkg_source import read_source, source_files  # noqa: E402  （tests/ 无 __init__.py，按同级模块导入）

_BACKEND = Path(__file__).resolve().parents[1]

#: trade 服务层包目录（拆分后的形态）。
SERVICE_PKG = _BACKEND / "modules" / "trade" / "service"

#: 正向锚点：只有读对了 trade 服务层的文件集才可能出现。
#: ★ 用途见 `pkg_source.read_source` 的 `expect` 形参 —— 挡住「读取点选错文件集」
#:   这类失配（文件集错了时，`"X" not in src` 形态的判据会**恒真通过**）。
#: ★ 两条**取自不同文件**（`_base.py` / `attribution.py`）⇒ 同时证明拼接覆盖了整包，
#:   而不只是第一个文件。两条都用**定义形态**（`def name(`），逐字实测存在。
_SERVICE_ANCHORS = (
    "def is_mock_source(",  # modules/trade/service/_base.py
    "def attribute_review(",  # modules/trade/service/attribution.py
)


def service_package_files() -> list[Path]:
    """包内全部 Python 源文件（排序后，顺序稳定）。"""
    return source_files(SERVICE_PKG)


def read_service_source() -> str:
    """把 trade 服务层包内**全部** `.py` 拼成一段源码文本。

    Raises:
        FileNotFoundError: 包目录不存在或为空 —— 那说明拆分形态又被改动了，
            此时**必须显式报错**而不是返回空串（空串会让所有 AST 判据
            变成「什么都没找到」的假绿）。
        AssertionError: 读到的文本里缺正向锚点（读取点选错了文件集）。
    """
    return read_source(SERVICE_PKG, expect=_SERVICE_ANCHORS)
