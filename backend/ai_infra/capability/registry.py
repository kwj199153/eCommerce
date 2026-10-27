# -*- coding: utf-8 -*-
"""已绑定应用的只读能力目录（单例）+ 检索。

## 为什么单独一个模块而不是塞进 `spec.py`

`spec.py` 是**纯函数**（喂一份 spec，出一份目录）—— 门禁可以对任意形状的
spec 断言它。本模块持有**进程内单例**（`app` 引用 + 目录），属于"有状态"那一半。
两者混在一起，测试就得先装应用才能测派生逻辑。

## 没有绑定应用时怎么办（测试 / 脚本 / Celery）

`catalog()` 返回**空字典**，`find()` 返回空列表，工具返回一句可读的
`capability_unavailable`。★ 不抛异常：能力层是**增强**，它不该让一个
在脚本/后台任务里跑的 Agent 整轮崩掉；但也**不能假装成功**（返回空列表
与"没有匹配"在语义上要能分开 —— 见 `find()` 的 `bound` 标记）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .spec import Capability, build_catalog

__all__ = [
    "bind_app",
    "is_bound",
    "catalog",
    "get_capability",
    "find",
    "stats",
    "top_tags",
]

_catalog: Dict[str, Capability] = {}
_app: Any = None


def bind_app(app: Any) -> int:
    """绑定 FastAPI 应用并派生目录；返回条目数（启动期调用一次）。

    ★ 幂等：重复调用只重建目录（测试里反复装配不会累积）。
    """
    global _app, _catalog
    _app = app
    _catalog = build_catalog(app.openapi())
    return len(_catalog)


def is_bound() -> bool:
    """能力层是否可用（= 启动期 `bind_app()` 跑过且目录非空）。"""
    return bool(_catalog)


def app_of() -> Any:
    """已绑定的应用（内部调用要用它做 ASGI transport）。"""
    return _app


def catalog() -> Dict[str, Capability]:
    return _catalog


def get_capability(name: str) -> Optional[Capability]:
    """按 `operationId` 取名（**精确**，不做模糊 —— 模糊会静默调错端点）。"""
    if not name:
        return None
    return _catalog.get(name.strip())


def _score(cap: Capability, terms: List[str]) -> int:
    """关键词命中计分（小写、子串）。

    ★ 为什么不用向量检索（对方也没用）：能力名与 summary 都是**短文本**，
      且使用者（LLM）给的是"断货""库存"这种业务词 —— 子串命中已经够用，
      而向量检索会引入 embedding 成本与"看起来很像但毫不相关"的误召回。
    """
    hay = f"{cap.name} {cap.summary} {cap.keywords}".lower()
    score = 0
    for t in terms:
        if t and t in hay:
            score += 3 if t in cap.name.lower() else 1
    return score


def find(query: str, limit: int = 8) -> Tuple[List[Capability], bool]:
    """按关键词检索读能力；返回 `(命中列表, 是否已绑定)`。

    ★ 第二个返回值不是装饰：**"没有匹配"与"能力层没装"必须能区分**。
      两者都返回空列表时，模型只会说"没找到" —— 而真相可能是
      "这台机器上根本没装能力层"，排查方向完全不同（本仓判过同族问题：
      取不到就静默退化 = 假数据冒充实测）。
    """
    if not _catalog:
        return [], False
    terms = [t for t in (query or "").lower().replace("_", " ").split() if t]
    if not terms:
        # 空查询 = 列前 N 条（给模型一个"先看看有什么"的入口）
        rows = sorted(_catalog.values(), key=lambda c: (c.path, c.name))
        return rows[: max(1, limit)], True

    scored = [(_score(c, terms), c) for c in _catalog.values()]
    hits = [(s, c) for s, c in scored if s > 0]
    hits.sort(key=lambda pair: (-pair[0], pair[1].path, pair[1].name))
    return [c for _, c in hits[: max(1, limit)]], True


def top_tags(limit: int = 12) -> List[str]:
    """出现最多的业务域标签（`find` 零命中时给模型一个"换个词"的抓手）。

    ★ 为什么值得单独给：本仓 `tags` 是**中文**业务域，而 `summary` 有相当一部分
      是英文。零命中时只回一句"没找到"，模型下一句往往还是同一个中文词 ——
      把可用的域名列给它，才有第二次机会。
    """
    counter: Dict[str, int] = {}
    for cap in _catalog.values():
        for t in cap.tags:
            counter[t] = counter.get(t, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[: max(1, limit)]]


def stats() -> Dict[str, Any]:
    """盘面读数（`GET /capabilities` 与门禁用）。"""
    paths = {c.path for c in _catalog.values()}
    return {
        "bound": is_bound(),
        "operations": len(_catalog),
        "paths": len(paths),
    }
