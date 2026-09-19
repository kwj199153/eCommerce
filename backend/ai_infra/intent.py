# -*- coding: utf-8 -*-
"""意图识别的**唯一机制**：有序首命中的关键词路由。

★ 收敛口径（批 D2）—— 什么收进来、什么留在业务模块：

| 收进本模块（控制流） | 留在业务模块（策略数据） |
|---|---|
| 查询小写归一 | 每组的意图标签 |
| 按调用方给的顺序逐组判定 | 每组的关键词表 |
| 首个命中即返回 | 组的先后顺序（即优先级） |
| 命中后的 `label_fn` 兜底 | 兜底默认值 |

本模块**不认识任何业务概念**：它只吃调用方传进来的 `Route` 序列，刻意不内置
任何关键词表 —— 那会把业务语义搬进基础设施层（本仓有分层门禁
`tests/test_infra_layering.py` 钉住这条：反向 import / 业务标识符 / 业务字符串三层）。

★ 为什么兜底默认值必须由调用方提供、不能统一成某个常量：
  收敛前 6 家的默认值各不相同（`general` / `compare` / `faq_query` / `generate`），
  它是**业务语义**而不是机制细节 —— 统一它等于改行为。

★ 为什么这里**不做**「LLM 意图分类」兜底：
  关键词未命中的兜底已由**工具路由**承担（各 Agent 的 `_route_via_tools` /
  `_stream_via_tools`）。再叠一层 LLM 意图分类 = 同一判定出现第三份实现。
  本模块的职责只是「命中即省一次 LLM 往返」这个加速器。

★ 防回流门禁：`tests/test_intent_single_source.py` —— 用 **AST 形态扫描**（不是名单）
  断言「有序首命中路由」这种形态只许在本模块出现，并要求 6 个业务模块都真的调用它。
"""
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

__all__ = ["Route", "first_match"]


@dataclass(frozen=True)
class Route:
    """一组「意图标签 + 关键词表」。

    :param label: 该组的意图标签
    :param keywords: 该组的关键词表（**原样比较**：不做大小写转换，
        因此写成大写的关键词在小写归一后的查询里**永不命中** ——
        这是收敛前就存在的现象，本模块原样保留、不改策略）
    :param label_fn: 可选的**组内二次判定**钩子，用于「同一组关键词、结果还要再判一次」
        的复合规则。它只在**该组已被关键词命中之后**才被调用，因此不会把
        未命中的查询提前判成某个标签。收到的是**已小写归一**的查询。
    """

    label: str
    keywords: Sequence[str]
    label_fn: Optional[Callable[[str], str]] = None


def first_match(query: str, routes: Sequence[Route], default: str) -> str:
    """按 `routes` 的顺序逐组判定，返回首个命中组的标签；全不命中返回 `default`。

    ★ 空关键词被跳过（`kw and kw in q`）：空串是任何字符串的子串，若不过滤，
      一个误写的 `""` 会让该组**永远命中**、把整条链后面的组全部遮住。
      收敛前 6 份实现都没有这个保护 —— 属顺手修掉的缺陷，行为等价性见
      `tests/test_intent_single_source.py::test_empty_keyword_is_skipped`。
    """
    q = (query or "").lower()
    for route in routes:
        if any(kw and kw in q for kw in route.keywords):
            return route.label_fn(q) if route.label_fn is not None else route.label
    return default
