# -*- coding: utf-8 -*-
"""收紧店铺作用域判据 + 修反向注入脚本的两处失效。

① **判据太弱**（实测发现）：`scope_condition(SpuRecord, shop_id)` 在
   `list_reviews_for_spu` 里出现 **2 次** ——
     (a) SPU 本体查询：判断这个 SPU 属不属于本店；
     (b) 差评 join 查询：挡住「别家店的 SKU 用同名 ASIN 认领本店差评」。
   原先只判「存在」⇒ 删掉任意一处，另一处还在，测试照样绿。
   ⇒ 改成判 **>= 2，并在报错里点名这两处**（同 Cyprus 仓那条「同一判定两条路径都要测」）。

② 反向注入脚本：两处变体锚点命中 2 次（docstring 里也有一模一样的串），
   且最后那次「跑全文件」传的是空 node ⇒ pytest 直接 usage error(exit=4)。
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEST = BACKEND / "tests" / "test_trade_review_binding.py"
PROBE = BACKEND / "scripts" / "probe_binding_gate_injection.py"


def rw(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def wr(p: Path, s: str) -> None:
    p.write_bytes(s.encode("utf-8"))


def sub(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    assert n == 1, f"锚点命中 {n} 次：{label}"
    return src.replace(old, new, 1)


# ---------------- 测试：作用域判据收紧

t = rw(TEST)

t = sub(
    t,
    '''def test_both_shop_scopes_are_applied_in_spu_query():
    """差评的 `shop_id` 与产品的 `spus.shop_id` 都得挂 —— `skus` 没有店铺列。"""
    src = _func_src("list_reviews_for_spu")
    for needle in ("scope_condition(CustomerReviewRecord, shop_id)",
                   "scope_condition(SpuRecord, shop_id)"):
        assert needle in src, (
            f"缺少 {needle}：产品线只能经 `spus.shop_id` 定归属，"
            "而差评另有一份 shop_id；漏一处就是跨租户读"
        )''',
    '''def test_both_shop_scopes_are_applied_in_spu_query():
    """差评的 `shop_id` 与产品的 `spus.shop_id` 都得挂 —— `skus` 没有店铺列。

    ★ 为什么 `spus` 这一侧必须判 **>= 2 处**而不是「存在」
      ----------------------------------------------------------------
      这两处守的是**不同的东西**，删掉任何一处都不该放行：
        (a) SPU 本体查询 —— 判断这个 SPU 属不属于本店；
        (b) 差评 join 查询 —— 挡住「别家店的 SKU 用同一个 ASIN 认领本店差评」。
      原先只判「存在」⇒ 删一处、留一处，测试照样绿（防御被悄悄打了折
      还没人发现）。这类漏判不会报错，只会让口子慢慢变大。
    """
    src = _func_src("list_reviews_for_spu")
    n_spu = src.count("scope_condition(SpuRecord, shop_id)")
    assert n_spu >= 2, (
        f"`list_reviews_for_spu` 里的 spus 店铺过滤只有 {n_spu} 处（应 >= 2）："
        "①SPU 本体查询 判断归属、②差评 join 查询 挡别家 SKU 认领 —— 缺一就是跨租户读"
    )
    assert "scope_condition(CustomerReviewRecord, shop_id)" in src, (
        "差评侧缺了店铺过滤：`skus` 表没有 shop_id，产品归属只能经 `spus.shop_id`，"
        "而差评自己另有一份 shop_id，两条都得挂"
    )''',
    "收紧店铺作用域判据",
)

wr(TEST, t)

# ---------------- 注入脚本：锚点 + 全文件跑法

p = rw(PROBE)

p = sub(
    p,
    '''    (
        "去掉 spus 那一处店铺作用域",
        "modules/trade/service.py",
        "            scope_condition(SpuRecord, shop_id),\\n            SpuRecord.id == spu_id,",
        "            SpuRecord.id == spu_id,",
        "test_both_shop_scopes_are_applied_in_spu_query",
    ),
    (
        "把数据缺口空态合并成 no_reviews",
        "modules/trade/service.py",
        '"no_asin_binding"',
        '"no_reviews"',
        "test_empty_states_are_distinct_literals",
    ),''',
    '''    (
        "去掉差评 join 那一处 spus 店铺作用域",
        "modules/trade/service.py",
        "            scope_condition(CustomerReviewRecord, shop_id),\\n"
        "            scope_condition(SpuRecord, shop_id),\\n",
        "            scope_condition(CustomerReviewRecord, shop_id),\\n",
        "test_both_shop_scopes_are_applied_in_spu_query",
    ),
    (
        "把数据缺口空态合并成 no_reviews",
        "modules/trade/service.py",
        'return {**head, "empty_state": "no_asin_binding"}',
        'return {**head, "empty_state": "no_reviews"}',
        "test_empty_states_are_distinct_literals",
    ),''',
    "注入变体锚点改精确",
)

p = sub(
    p,
    '''def run_one(node: str) -> int:
    p = subprocess.run(
        [PY, "-m", "pytest", f"tests/test_trade_review_binding.py::{node}", "-q"],
        cwd=str(BACKEND), capture_output=True, text=True,
    )
    return p.returncode''',
    '''def run_one(node: str) -> int:
    """跑单条或整个文件（`node` 为空 ⇒ 跑整个文件，否则 `-k node`）。

    ★ 不能用 `file.py::` 的空 node：pytest 会把它当成用法错误直接返回 **4**
      （不是「没找到用例」，是 usage error）—— 会把这种假红误读成「判据抓到了」。
    """
    target = "tests/test_trade_review_binding.py"
    args = [PY, "-m", "pytest", target, "-q"]
    if node:
        args[-1:-1] = ["-k", node]
    p = subprocess.run(args, cwd=str(BACKEND), capture_output=True, text=True)
    return p.returncode''',
    "修全文件跑法",
)

wr(PROBE, p)

print("patched: test_trade_review_binding.py + probe_binding_gate_injection.py")
