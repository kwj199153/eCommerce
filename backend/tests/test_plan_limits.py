"""套餐档位闸（r385 · 商用审查 P0-5）。

==============================================================================
★ 缺陷形态
==============================================================================
`max_shops` / `max_users` 在 `subscription_plans` 里有值（3/1、10/5、50/20），
全仓却只有**两处读、且都是展示**：

    modules/billing/router.py:159-160
    modules/secretary/subscription_tools.py:112

⇒ 免费版能建 50 家店、能加 20 人；企业版与免费版在这些维度完全一样，
  差的那 ¥999 只买到调用次数。

==============================================================================
★ 本文件锁四件事
==============================================================================
  1. **兜底口径**：没有生效订阅 ⇒ 按免费版上限（**不是放行**）；
  2. **边界**：`current >= max` 就拒（本次动作会新增一条）；
  3. **错误体**：402 + 结构化 detail（前端据此显示升级引导）；
  4. **接线**：两个写端点**真的**调用了闸门（AST 判据）——
     这条防的是「模块写好了但没人调用」：那种形态下所有单测都绿，
     而线上照旧不拦。
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from modules.billing import plan_limits
from modules.billing.plan_limits import (
    FREE_FALLBACK,
    METRIC_SHOPS,
    METRIC_USERS,
    PlanLimits,
    enforce_account_limit,
    get_plan_limits,
    plan_limit_error,
)

BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 兜底口径：FREE_FALLBACK 必须等于「免费版」档位（防两处漂移）
# ---------------------------------------------------------------------------
def test_free_fallback_values():
    assert (FREE_FALLBACK.max_shops, FREE_FALLBACK.max_users) == (3, 1)


def test_free_fallback_matches_seeded_plan():
    """`init_default_plans()` 给 free 档写的值 == FREE_FALLBACK。

    ★ 为什么要有这条：两个数字住在两个文件里（一个常量、一个建表语句），
      漂移后**不会报任何错** —— 只会让"没有订阅的人"和"免费版用户"看到
      不同的上限，而没人知道为什么。
    """
    src = (BACKEND / "core" / "metering" / "usage_tracker.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    free_call = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "SubscriptionPlan":
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            if getattr(kwargs.get("name"), "value", None) == "free":
                free_call = kwargs
                break
    assert free_call is not None, "没在 init_default_plans 里找到 name='free' 的套餐"

    def _int(node) -> int:
        assert isinstance(node, ast.Constant), "档位值应为整数字面量"
        return int(node.value)

    assert _int(free_call["max_shops"]) == FREE_FALLBACK.max_shops
    assert _int(free_call["max_users"]) == FREE_FALLBACK.max_users


# ---------------------------------------------------------------------------
# get_plan_limits：无订阅 / 已失效 ⇒ 免费版兜底
# ---------------------------------------------------------------------------
def _db_returning(*results):
    """造一个只实现 `.execute()` 的假 session，按调用顺序返回结果。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=results)
    return db


def _scalar(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar_one.return_value = value
    return res


def _plan(name: str, shops: int, users: int, display: str = "") -> MagicMock:
    p = MagicMock()
    p.name = name
    p.display_name = display or name
    p.max_shops = shops
    p.max_users = users
    return p


def _sub(plan, active: bool = True) -> MagicMock:
    s = MagicMock()
    s.plan = plan
    s.is_active = active
    return s


@pytest.mark.asyncio
async def test_no_subscription_falls_back_to_free():
    db = _db_returning(_scalar(None))
    limits = await get_plan_limits(db, "user-1")
    assert limits == FREE_FALLBACK


@pytest.mark.asyncio
async def test_expired_subscription_falls_back_to_free():
    db = _db_returning(_scalar(_sub(_plan("pro", 10, 5), active=False)))
    limits = await get_plan_limits(db, "user-1")
    assert limits == FREE_FALLBACK


@pytest.mark.asyncio
async def test_active_subscription_reads_plan():
    db = _db_returning(_scalar(_sub(_plan("enterprise", 50, 20, "企业版"))))
    limits = await get_plan_limits(db, "user-1")
    assert (limits.plan_name, limits.max_shops, limits.max_users) == ("enterprise", 50, 20)


# ---------------------------------------------------------------------------
# enforce_account_limit：边界是 `current >= max`（本次动作要新增一条）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rejects_at_limit(monkeypatch):
    monkeypatch.setattr(plan_limits, "get_plan_limits", AsyncMock(return_value=FREE_FALLBACK))
    monkeypatch.setattr(plan_limits, "count_account_shops", AsyncMock(return_value=3))
    db = _db_returning(_scalar("owner-1"))  # 只有加锁查 owner

    with pytest.raises(HTTPException) as ei:
        await enforce_account_limit(db, account_id="acc-1", metric=METRIC_SHOPS)

    assert ei.value.status_code == 402
    body = ei.value.detail
    assert body["code"] == "PLAN_LIMIT_EXCEEDED"
    assert (body["current"], body["limit"]) == (3, 3)
    assert body["upgrade_url"].startswith("/settings/")


@pytest.mark.asyncio
async def test_passes_below_limit(monkeypatch):
    monkeypatch.setattr(plan_limits, "get_plan_limits", AsyncMock(return_value=FREE_FALLBACK))
    monkeypatch.setattr(plan_limits, "count_account_shops", AsyncMock(return_value=2))
    db = _db_returning(_scalar("owner-1"))

    limits = await enforce_account_limit(db, account_id="acc-1", metric=METRIC_SHOPS)
    assert limits.max_shops == 3


@pytest.mark.asyncio
async def test_seats_count_includes_owner(monkeypatch):
    """免费版 1 席位 ⇒ 邀请第 1 个成员就该被拒（owner 已占 1 个）。"""
    monkeypatch.setattr(plan_limits, "get_plan_limits", AsyncMock(return_value=FREE_FALLBACK))
    monkeypatch.setattr(plan_limits, "count_account_seats", AsyncMock(return_value=1))
    db = _db_returning(_scalar("owner-1"))

    with pytest.raises(HTTPException) as ei:
        await enforce_account_limit(db, account_id="acc-1", metric=METRIC_USERS)
    assert ei.value.detail["metric"] == METRIC_USERS


def test_error_body_is_serialisable():
    """detail 必须是纯 JSON 可序列化结构（FastAPI 会原样回给前端）。"""
    import json

    exc = plan_limit_error(
        metric=METRIC_SHOPS,
        limit=PlanLimits("pro", "专业版", 10, 5),
        current=10,
        account_id="acc-1",
    )
    json.dumps(exc.detail, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 接线判据（AST）：闸门**真的**挂在两个写端点上
# ---------------------------------------------------------------------------
def _calls_in_func(path: Path, func_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == func_name:
            names: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        names.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        names.add(fn.attr)
            return names
    raise AssertionError(f"{path.name} 里没有函数 {func_name}")


def test_create_store_is_gated():
    calls = _calls_in_func(BACKEND / "modules" / "stores" / "router.py", "create_store")
    assert "enforce_account_limit" in calls, "建店端点没挂档位闸 ⇒ 免费版仍可无限建店"
    assert "is_demo_request" in calls, "演示豁免判据缺失 ⇒ 演示账号会被自己的店数挡住"


def test_invite_member_is_gated():
    calls = _calls_in_func(BACKEND / "core" / "auth" / "accounts_router.py", "invite_member")
    assert "enforce_account_limit" in calls, "加成员端点没挂席位闸 ⇒ 免费版仍可无限加人"
