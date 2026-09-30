# -*- coding: utf-8 -*-
"""把「空态必须字面不同」这条判据从**源码包含**改成 **AST 字符串常量**。

★ 反向注入抓出来的假绿（第 289 轮实测）
------------------------------------------------------------------------
原判据是 `"no_asin_binding" in src`（`src` = 函数源码文本）。
但函数的 **docstring 里逐条写了空态清单**：
    - `"no_asin_binding"`   SKU 登记了但 ASIN / sku_code 全空 ⇒ **数据缺口**
⇒ 把真正的 `return {..., "empty_state": "no_asin_binding"}` 删掉，docstring
  依旧给这几个字面量打供给 ⇒ **判据恒绿，抓不到改动**。

这正是本仓那条铁律的实例：
    「判据禁『源码字符串包含』（docstring 会骗过 → 假绿）；形态判据走 AST。」

修法：遍历函数体收集 `ast.Constant(str)`，并**先剥掉 docstring**
（docstring 本身也是 str 常量，不剥就等于没改）。
"""
from __future__ import annotations

from pathlib import Path

TEST = Path(__file__).resolve().parents[1] / "tests" / "test_trade_review_binding.py"

src = TEST.read_bytes().decode("utf-8").replace("\r\n", "\n")

old_probe = '''def _router_paths() -> set[str]:'''

new_probe = '''def _string_literals_in(name: str) -> set[str]:
    """取出函数体里的**字符串常量**（**剥掉 docstring**）。

    ★ 为什么不能用 `'"x" in ast.get_source_segment(...)`：
      ① docstring / 注释里写了同一串 ⇒ 真代码删了照样恒绿（已实测假绿一次）；
      ② 反过来，注释里的描述也会让「 newValue 不存在」的判据失效。
      AST 不收录注释，且这里显式跳过函数体第一条 str 表达式（docstring）。
    """
    tree = ast.parse(SERVICE_SRC)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name != name:
            continue
        body = list(fn.body)
        if body:
            first = body[0]
            is_doc = (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            )
            if is_doc:
                body = body[1:]
        return {
            c.value
            for node in body
            for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
    raise AssertionError(f"service 里找不到函数 {name}")


def _router_paths() -> set[str]:'''

assert src.count(old_probe) == 1, "探针锚点不唯一"
src = src.replace(old_probe, new_probe, 1)

old_test = '''    src = _func_src("list_reviews_for_spu")
    for lit in ("not_found", "no_sku", "no_asin_binding", "no_reviews"):
        assert f'"{lit}"' in src, (
            f"`list_reviews_for_spu` 缺少空态 {lit!r} —— "
            "四种空态少任何一种，界面就少一种归因"
        )'''

new_test = '''    lits = _string_literals_in("list_reviews_for_spu")
    # 自证：探针必须是活的（空集会让下面每条都恒绿 —— 那就是假绿，不是绿）
    assert lits, "AST 探针没取到任何字符串常量 ⇒ 下面的断言全部恒真，门禁是假的"
    for lit in ("not_found", "no_sku", "no_asin_binding", "no_reviews"):
        assert lit in lits, (
            f"`list_reviews_for_spu` 的**返回值**里缺少空态 {lit!r} —— "
            "四种空态少任何一种，界面就少一种归因"
            "（注意：只看 docstring 里有没有这个串是抓不到改动的，已实测）"
        )'''

assert src.count(old_test) == 1, "用例锚点不唯一"
src = src.replace(old_test, new_test, 1)

TEST.write_bytes(src.encode("utf-8"))
print("patched: 空态判据改为 AST 形态")
