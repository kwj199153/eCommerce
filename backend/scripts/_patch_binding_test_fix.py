# -*- coding: utf-8 -*-
"""修 `tests/test_trade_review_binding.py` 的两处判据形态错误。

① `_service_calls_in_router()` 原来收集的是 `service.X(...)` 的**调用**形态，
   而本仓 router 的实际写法是 `_guard(service.X, "标签", ...)` —— 函数对象被当作
   **参数**传进去（`router.py` 8 个端点全是这个形态）⇒ 判据收集到空集，恒红。
   ★ 这就是本仓那条铁律的实例：判据的 needle 必须先在文件里实测存在，
     否则「取反后恒真 / 集合恒空」都难以察觉。

② FakeSession 的语句分派把孤儿查询误判成 SKU 查询：
   孤儿语句的文本里含 `NOT (EXISTS (SELECT skus.id FROM skus JOIN spus ...)`，
   "FROM skus" 命中了 SKU 分支 ⇒ 明细行返回成了 sku 列表（空）。
   ⇒ 必须先判 NOT EXISTS，再判 FROM skus。
"""
from __future__ import annotations

from pathlib import Path

T = Path(__file__).resolve().parents[1] / "tests" / "test_trade_review_binding.py"

src = T.read_bytes().decode("utf-8").replace("\r\n", "\n")

old = '''def _service_calls_in_router() -> set[str]:
    """router 里实际调用的 `service.<name>` —— 「有函数没出口」就是这么长出来的。"""
    tree = ast.parse(ROUTER_SRC)
    return {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "service"
    }'''

new = '''def _service_calls_in_router() -> set[str]:
    """router 里**引用到的** `service.<name>` —— 「有函数没出口」就是这么长出来的。

    ★ 只收 `service.X(...)` 的**调用**形态会收集到**空集**：本仓 router 的实际
      写法是 `_guard(service.X, "标签", session, shop, ...)` —— 函数对象作为
      **参数**传进统一异常映射点，全部 11 个端点都是这个形态。
      ⇒ 判据必须覆盖「属性引用」，而不是「函数调用」。
    """
    tree = ast.parse(ROUTER_SRC)
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "service"
    }


def test_router_call_probe_is_not_empty():
    """自证：上面的探针在本文件里必须真能吃到东西（空集 ⇒ 每条断言都恒红）。"""
    calls = _service_calls_in_router()
    assert calls, "router 里一个 service.X 都没解析到 —— 探针形态错了，门禁在假红"
    assert "list_dispositions" in calls, "连既有端点都没解析到 ⇒ 探针不可信"'''

assert src.count(old) == 1, f"锚点①命中 {src.count(old)} 次"
src = src.replace(old, new, 1)

old2 = '''        t = str(stmt)
        # ① 计数：count() select_from(customer_reviews)
        if "count(*)" in t:
            return _Res([self.total])
        # ② SPU 本体
        if "FROM spus" in t:'''

new2 = '''        t = str(stmt)
        # ① 计数：count() select_from(customer_reviews)
        if "count(*)" in t:
            return _Res([self.total])
        # ② 孤儿主查（文本里带 `NOT (EXISTS ... FROM skus ...`）必须排在「FROM skus」
        #    之前 —— 否则子查询里的 "FROM skus" 会把明细行分派成 SKU 列表。
        if "NOT (EXISTS" in t:
            return _Res(self.reviews)
        # ③ SPU 本体
        if "FROM spus" in t:'''

assert src.count(old2) == 1, f"锚点②命中 {src.count(old2)} 次"
src = src.replace(old2, new2, 1)

T.write_bytes(src.encode("utf-8"))
print("fixed test file")
