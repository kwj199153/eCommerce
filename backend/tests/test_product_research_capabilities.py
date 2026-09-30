"""
选品 Agent 能力面门禁（第 200 轮建立）。

为什么有这个文件
----------------
`router.py` 的模块 docstring 原文写着：

    端点列表（共 8 个 —— 与路由表**逐条对应**，由
    `tests/test_product_research_capabilities.py` 钉住不许漂移）

**但那个测试文件当时并不存在。** 这是本项目反复踩过的形态 ——「注释承诺型假门禁」：
注释里写下一条保证，实现里没有任何东西在守它。文档漂移就是这么长出来的：
第 199 轮盘点时 `router.py` 的 docstring 只列了 6 个端点，漏了 `approval/resume`
与 `chat/stream`，全仓没有一条测试因此变红。

所以本文件把那句承诺兑现成可执行判据：

A. docstring 的端点清单 ⇔ 真实路由表（**双向**相等，且条数 == 声明的条数）
B. `/capabilities` 的 `features[].endpoint` 集合 ⇔ 真实路由表
C. 上面两条都带**防空跑断言**（路由表为空 / 清单为空 ⇒ 直接失败，不静默通过）

形态判据一律走 **AST**，不做源码字符串包含 —— 本仓吃过「docstring 骗过字符串判据」
的亏；而本文件守的恰恰就是 docstring，用字符串判据等于自欺。

它守的不是「代码对不对」，而是「**关于这份代码的说法对不对**」：
加端点时只改代码不改 docstring ⇒ A 红；只改 docstring 不改代码 ⇒ A 红；
`capabilities` 的 `features` 漏一个新端点 ⇒ B 红。

反向注入（已实测能转红，不是对着结论点头）
------------------------------------------
1. 删掉 docstring 里 `- POST  /api/v1/product-research/chat/stream` 那一行
   ⇒ A 红（「只在路由表里: [('POST', '/chat/stream')]」）。
2. 把 `features` 里任意一项的 `endpoint` 改成别的不存在的路径 ⇒ B 红。
3. 把 docstring 的「共 8 个」改成「共 7 个」⇒ A 红（声明条数不符）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTER_FILE = BACKEND / "modules" / "product_research" / "router.py"

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# docstring 行形态：`- POST  /api/v1/product-research/chat            - 自然语言对话`
# ★ 注意有些行是「方法名 + 两个空格」（对齐用），所以用 \s+ 而不是单个空格。
_DOC_LINE = re.compile(r"^-\s*(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)", re.MULTILINE)
# 声明条数：`端点列表（共 8 个 —— ...）`
_DOC_COUNT = re.compile(r"端点列表（共\s*(\d+)\s*个")


def _parse() -> dict:
    """把 router.py 里「四处说法」解析出来（全走 AST + 模块 docstring）。"""
    src = ROUTER_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # ---- router 的 prefix（用于把 docstring 里的全路径归一成装饰器里的相对路径）----
    prefix = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "router" for t in node.targets
        ):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Call):
                    for kw in sub.keywords:
                        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                            prefix = str(kw.value.value)
    assert prefix, "未能从 router.py 里定位 `APIRouter(prefix=...)`"

    def _norm(path: str) -> str:
        if path.startswith("/api/v1"):
            path = path[len("/api/v1"):]
        if path.startswith(prefix):
            path = path[len(prefix):]
        return path

    # ---- ① 真实路由表：(METHOD, path) -> handler ----
    routes: dict[tuple[str, str], str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "router" or func.attr not in _HTTP_METHODS:
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            routes[(func.attr.upper(), str(dec.args[0].value))] = node.name

    # ---- ② docstring 端点清单 ----
    doc = ast.get_docstring(tree, clean=False)
    assert doc, "router.py 没有模块 docstring —— 本门禁的判据 A 失去对照物"
    declared = [(m, _norm(p)) for m, p in _DOC_LINE.findall(doc)]

    m_count = _DOC_COUNT.search(doc)
    declared_count = int(m_count.group(1)) if m_count else None

    # ---- ③ /capabilities 的 features[].endpoint ----
    features: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if not {"agent_name", "features"} <= keys:
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and k.value == "features"):
                continue
            if not isinstance(v, ast.List):
                continue
            for item in v.elts:
                if not isinstance(item, ast.Dict):
                    continue
                for ik, iv in zip(item.keys, item.values):
                    if (
                        isinstance(ik, ast.Constant)
                        and ik.value == "endpoint"
                        and isinstance(iv, ast.Constant)
                    ):
                        features.append(_norm(str(iv.value)))

    return {
        "routes": routes,
        "route_paths": {p for _, p in routes},
        "declared": declared,
        "declared_count": declared_count,
        "features": features,
        "prefix": prefix,
    }


def test_docstring_endpoint_list_matches_route_table():
    """判据 A：docstring 的端点清单 ⇔ 真实路由表。"""
    data = _parse()
    routes = data["routes"]
    declared = data["declared"]

    assert routes, "路由表为空 —— 判据空跑（AST 没解析到任何 @router.xxx 装饰器）"
    assert declared, "docstring 端点清单为空 —— 判据空跑"

    route_set = set(routes)
    declared_set = set(declared)

    assert declared_set == route_set, (
        "router.py 的模块 docstring 端点清单与真实路由表不一致\n"
        f"  只在 docstring 里（写在纸上但没有实现）: {sorted(declared_set - route_set)}\n"
        f"  只在路由表里（实现了但没写进 docstring）: {sorted(route_set - declared_set)}\n"
        f"  提示：prefix = {data['prefix']!r}"
    )

    assert data["declared_count"] == len(route_set), (
        f"docstring 宣称「共 {data['declared_count']} 个」，实际路由表有 {len(route_set)} 个"
    )


def test_capabilities_features_match_route_table():
    """判据 B：/capabilities 的 features[].endpoint ⇔ 真实路由表（按**路径**比）。

    ★ 为什么这里只比路径、不比方法：`features` 的条目里**没有方法字段**
      （形如 `{"name": ..., "endpoint": ...}`），所以拿不到方法。
      方法维度的漂移由判据 A 覆盖（docstring 写了方法）。两条判据互补，不重叠。
    """
    data = _parse()
    route_paths = data["route_paths"]
    features = data["features"]

    assert route_paths, "路由表为空 —— 判据空跑"
    assert features, "/capabilities 的 features 为空 —— 判据空跑"

    assert len(features) == len(set(features)), (
        f"/capabilities 的 features 里有重复 endpoint: "
        f"{sorted(p for p in set(features) if features.count(p) > 1)}"
    )

    feature_set = set(features)
    assert feature_set == route_paths, (
        "/capabilities 的 features[].endpoint 与真实路由表不一致\n"
        f"  只在 features 里（对外宣称了不存在的能力）: {sorted(feature_set - route_paths)}\n"
        f"  只在路由表里（有能力但对外没宣称）:       {sorted(route_paths - feature_set)}"
    )
