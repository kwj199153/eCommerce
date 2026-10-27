# -*- coding: utf-8 -*-
"""能力目录 —— 真源是 `app.openapi()`，不是手写的表。

## 为什么要有这一层（第 400 轮 P1-1，对标 eEducation 的 `capability/`）

现状：后端 **242 条端点**，Agent 只够得到 **65 个手写工具**（`TOOL_CATALOG`），
而这 65 个是人从端点里**挑出来**再手写成工具的。后果是：

* 新增一个能力要人工同步 3～6 处（工具定义 / 目录条目 / 审批名单 / 计数断言）；
* 端点写好了、Agent 不知道 —— 只能等某个人想起来"再写个工具"。

这一层把「有哪些读能力」变成**从代码自动派生**的事实：
端点的 `summary` / `tags` / 参数签名本来就是端点作者写的，
是唯一会随代码同步的东西。Agent 先用 `find_capabilities` 找、再用
`describe_capability` 看参数、最后 `read_capability` 调 —— 操作知识**不塞进
工具 schema**（省 token），按需取。

## A 档（本轮）只做**读**

只暴露 `GET`。写操作（POST/PUT/PATCH/DELETE，本仓 201 条）一条都不进目录，
所以「审批面」与租户写守卫**完全不变** —— 这是这一档风险最低的原因。

★ 为什么不按 `operationId` 里的动词猜读写：猜错一次就是**写操作绕过审批**。
  按 HTTP 方法判是**结构性**的，猜不歪。（`POST` 在本仓有大量"读"语义，
  例如 `/product-research/chat`；那类留在 B 档，靠 `x-side-effect` 显式声明。）

## 拒绝清单（递归与身份）

`BLOCKED_PREFIXES` 里的端点不进目录。其中两条是**硬约束**：

* `orchestrator` / `agents` —— 能力层调它们会**递归回自己**
  （店秘书 → read_capability → 店秘书 → …），一开口就把图跑爆；
* `auth` —— 那里会**签发 token**。一个"能读任意端点"的工具如果能拿到令牌，
  就等于把身份提升做成了一次普通工具调用。

★ 拒绝按**前缀**判而不是黑名单逐个列：新加端点时漏写一行的代价
  是「悄悄多出一个可读面」，而前缀是**兜底方向**（宁可多拒，不可漏放）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

__all__ = [
    "Capability",
    "ParamInfo",
    "BLOCKED_PREFIXES",
    "BLOCKED_METHODS",
    "build_catalog",
    "is_exposed",
    "effect_of",
]

#: 只读能力只暴露这些方法（结构性判据，不猜语义）
BLOCKED_METHODS = frozenset({"post", "put", "patch", "delete"})

#: 不进目录的路径前缀（见模块 docstring 的两条硬约束）
BLOCKED_PREFIXES: Tuple[str, ...] = (
    "/api/v1/auth",          # 会签发 token ⇒ 能力层拿到它 = 身份提升
    "/api/v1/orchestrator",  # 店秘书自身 ⇒ 能力层调它 = 递归回自己
    "/api/v1/agents",        # 审批 resume ⇒ 会推进图（副作用）
    "/api/v1/admin",
    "/api/v1/internal",
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
)


@dataclass(frozen=True)
class ParamInfo:
    """一个端点参数的**最小**描述（够模型拼对请求即可，不做 schema 全文）。"""

    name: str
    location: str            # path / query / header / cookie
    required: bool = False
    type: str = "string"
    description: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "in": self.location,
            "type": self.type,
        }
        if self.required:
            d["required"] = True
        if self.description:
            # ★ 截断：端点作者有时写整段说明，全带上会让 describe 的输出
            #   比数据本身还长（本仓单条 op 的 JSON 平均 1.4KB）
            d["desc"] = self.description[:120]
        return d


@dataclass(frozen=True)
class Capability:
    """一条可调用的读能力。`name` = OpenAPI 的 `operationId`（端点函数名派生）。"""

    name: str
    method: str
    path: str
    summary: str = ""
    tags: Tuple[str, ...] = ()
    params: Tuple[ParamInfo, ...] = ()
    #: 供检索的额外关键词（summary 为空时至少还有路径可搜）
    keywords: str = ""

    def as_row(self) -> Dict[str, Any]:
        """`find_capabilities` 返回的一行（**不含**参数 schema —— 省 token）。

        ★ 带一个 `tag`：本仓不少端点的 `summary` 是**英文**（"Get My Account"），
          而 `tags` 是中文业务域（"账户与成员" / "差评处置"）。只给英文摘要时，
          模型用中文关键词找完再看列表，仍然认不出这条是不是自己要的。
        """
        row: Dict[str, Any] = {
            "name": self.name,
            "summary": self.summary or self.path,
            "path": self.path,
        }
        if self.tags:
            row["tag"] = self.tags[0]
        return row


def effect_of(method: str) -> str:
    """按 HTTP 方法给副作用档（A 档只用得上 `read`）。"""
    m = (method or "").lower()
    if m in ("get", "head", "options"):
        return "read"
    if m == "delete":
        return "irreversible"
    return "write"


def is_exposed(path: str, method: str) -> bool:
    """这条 op 是否进只读目录。"""
    if (method or "").lower() in BLOCKED_METHODS:
        return False
    if (method or "").lower() not in ("get", "head"):
        return False
    p = (path or "").rstrip("/") or "/"
    for pre in BLOCKED_PREFIXES:
        if p == pre or p.startswith(pre + "/"):
            return False
    return True


def _params_of(op: Dict[str, Any]) -> Tuple[ParamInfo, ...]:
    out: List[ParamInfo] = []
    for p in op.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        schema = p.get("schema") or {}
        # `$ref` / `anyOf` 之类的取不到 type ⇒ 记成 string（参数名与位置才是关键）
        ptype = schema.get("type") or "string"
        out.append(
            ParamInfo(
                name=str(p.get("name") or ""),
                location=str(p.get("in") or "query"),
                required=bool(p.get("required")),
                type=str(ptype),
                description=str(p.get("description") or ""),
            )
        )
    return tuple(p for p in out if p.name)


def build_catalog(spec: Dict[str, Any]) -> Dict[str, Capability]:
    """从一份 OpenAPI spec 派生出只读目录（**纯函数**，可在测试里喂假 spec）。

    ★ 纯函数是刻意的：真源来自 `app.openapi()`（要装整个应用），
      而门禁需要能对"某个形状的 spec"单独断言 —— 两者分开才好测。
    """
    catalog: Dict[str, Capability] = {}
    for path, ops in (spec.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            if not is_exposed(path, method):
                continue
            name = str(op.get("operationId") or "").strip()
            if not name:
                # 没有 operationId 的 op 无法按名字调用 ⇒ 跳过（而不是编一个：
                # 编出来的名字在 openapi() 重新生成后会漂移，表现为"点时 404"）
                continue
            tags = tuple(str(t) for t in (op.get("tags") or []))
            catalog[name] = Capability(
                name=name,
                method=method.upper(),
                path=path,
                summary=str(op.get("summary") or "").strip(),
                tags=tags,
                params=_params_of(op),
                keywords=" ".join([path, " ".join(tags)]),
            )
    return catalog
