# -*- coding: utf-8 -*-
"""确认 /api/v1/trade/* 这组端点真的挂到了 app 上。

★ 为什么不能直接看 `scripts/route_inventory.py` 的输出：它打印明细时写死了
  `_biz[:15]`（只打前 15 条，字母序）⇒ trade 在末尾，看不见 ≠ 没注册。
  判挂载与否要看 app 本身，不是看某个脚本愿意打多少行。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import app  # noqa: E402

paths = sorted({getattr(r, "path", "") for r in app.routes})
hits = [p for p in paths if p.startswith("/api/v1/trade")]

print(f"app 路由总数 = {len(paths)}")
print(f"/api/v1/trade/* 端点 = {len(hits)}")
for p in hits:
    print("   ", p)

expected = [
    "/api/v1/trade/reviews",
    "/api/v1/trade/reviews/by-spu/{spu_id}",
    "/api/v1/trade/reviews/orphans",
    "/api/v1/trade/dispositions",
    "/api/v1/trade/dispositions/backfill",
    "/api/v1/trade/dispositions/{review_id}",
    "/api/v1/trade/dispositions/{review_id}/approve",
    "/api/v1/trade/dispositions/{review_id}/draft",
    "/api/v1/trade/dispositions/{review_id}/issue",
    "/api/v1/trade/dispositions/{review_id}/reject",
]
missing = [p for p in expected if p not in hits]
print("\n缺失:", missing if missing else "无")
raise SystemExit(1 if missing else 0)
