# -*- coding: utf-8 -*-
"""反向注入：证明 `tests/test_trade_review_binding.py` 的判据会把坏改动打成红。

★ 为什么必须跑这一遍（本仓铁律：「没被反向注入验证过的门禁 = 没有门禁」）
------------------------------------------------------------------------
一条判据如果删除 target 代码之后它照样绿，那它不是判据，是装饰。下面逐个
把被测代码改坏，断言**对应的那条用例必须转红**，然后立刻还原。

★ 还原安全：不动文件本身，**内存里改 src 写回原文**，并在每轮结束后比对
   sha256 与注入前一致（不一致就中止后续所有变体 —— 别让探针自己污染仓库）。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PY = sys.executable

VARIANTS = [
    (
        "去掉 SPU 内 distinct 去重",
        "modules/trade/service/queries.py",
        "        .distinct()\n",
        "",
        "test_reviews_for_spu_dedupes",
    ),
    (
        "去掉差评 join 那一处 spus 店铺作用域",
        "modules/trade/service/queries.py",
        "            scope_condition(CustomerReviewRecord, shop_id),\n"
        "            scope_condition(SpuRecord, shop_id),\n",
        "            scope_condition(CustomerReviewRecord, shop_id),\n",
        "test_both_shop_scopes_are_applied_in_spu_query",
    ),
    (
        "把数据缺口空态合并成 no_reviews",
        "modules/trade/service/queries.py",
        'return {**head, "empty_state": "no_asin_binding"}',
        'return {**head, "empty_state": "no_reviews"}',
        "test_empty_states_are_distinct_literals",
    ),
    (
        "去掉 exists 子查询的 correlate",
        "modules/trade/service/queries.py",
        "        .correlate(CustomerReviewRecord)\n",
        "",
        "test_orphan_query_scopes_skus_through_spus_and_correlates",
    ),
    (
        "把 /reviews/orphans 端点改名（前端还在调旧路径）",
        "modules/trade/router.py",
        '"/reviews/orphans"',
        '"/reviews/orphans-renamed"',
        "test_review_endpoints_exist",
    ),
]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def run_one(node: str) -> int:
    """跑单条或整个文件（`node` 为空 ⇒ 跑整个文件，否则 `-k node`）。

    ★ 不能用 `file.py::` 的空 node：pytest 会把它当成用法错误直接返回 **4**
      （不是「没找到用例」，是 usage error）—— 会把这种假红误读成「判据抓到了」。
    """
    target = "tests/test_trade_review_binding.py"
    args = [PY, "-m", "pytest", target, "-q"]
    if node:
        args[-1:-1] = ["-k", node]
    p = subprocess.run(args, cwd=str(BACKEND), capture_output=True, text=True)
    return p.returncode


def main():
    print("=== 反向注入：每条都应转红（exit != 0）===")
    failed = []
    for label, rel, old, new, node in VARIANTS:
        f = BACKEND / rel
        src = f.read_bytes().decode("utf-8").replace("\r\n", "\n")
        before = sha(src)
        n = src.count(old)
        if n != 1:
            print(f"  !! 锚点命中 {n} 次，跳过：{label}")
            failed.append((label, f"锚点 {n} 次"))
            continue
        f.write_bytes(src.replace(old, new, 1).encode("utf-8"))
        try:
            code = run_one(node)
            ok = code != 0
            print(f"  {'OK ' if ok else 'BAD'} {label} -> pytest exit={code}")
            if not ok:
                failed.append((label, f"exit={code}，判据没抓住"))
        finally:
            f.write_bytes(src.encode("utf-8"))
            after = (f.read_bytes().decode("utf-8").replace("\r\n", "\n"))
            if sha(after) != before:
                print(f"  !! 还原失败，中止：{rel}")
                raise SystemExit(2)

    print("\n=== 还原后原文件应全绿 ===")
    code = run_one("")
    print(f"  full-file pytest exit={code}（0=绿）")
    if code != 0:
        failed.append(("原文件全量", f"exit={code}"))

    print("\n=== 结论 ===")
    if failed:
        for lab, why in failed:
            print(f"  有问题：{lab} —— {why}")
        raise SystemExit(1)
    print("  全部反向注入都转红了，且还原后全绿 ⇒ 判据是活的")


if __name__ == "__main__":
    main()
