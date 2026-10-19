"""演示种子守卫（r385 · 商用审查 P1-4）。

==============================================================================
★ 缺陷形态（审查报告原文）
==============================================================================
七个业务 seed 的守卫都是「**全表**为空 ⇒ 给**每个**已存在店铺灌一份」。
⇒ 全新库 + 客户已建店 + 客户还没录产品 + 重启一次 = **演示产品被灌进真实店铺**。
审查报告把它标成"待核"，其实代码事实就是确定的：

    modules/products/seed.py:359  `if count > 0: return 0`（全表计数，不是按店）

==============================================================================
★ 修法
==============================================================================
`core.bootstrap.SeedStep` 加 `requires_demo`；`seed_base_data` 在非 demo 模式下
**跳过**这些步骤（记 0 条，键不消失）。清单标记住在组合根 `wiring.SEED_STEPS`，
本文件锁死三件事：

  1. 非 demo ⇒ 标记过的步骤**一次都不调用**（用 spy 数调用次数，不靠返回值）；
  2. demo ⇒ 照常调用（否则等于把演示环境也关掉了）；
  3. 跳过时 `result` 的**键集合不变**（只变值）—— 键少一个会被 CI / 探针
     读成「这一步不存在」，那是另一种假象。
"""

from __future__ import annotations

import pytest

import core.bootstrap as bootstrap
from core.bootstrap import SeedStep, seed_base_data

#: 真实存在、但**不会被真的调用**（`_try` 被 spy 顶掉，只走到 `_resolve`）
TARGET = "core.bootstrap:seed_default_plans"


def _steps() -> list[SeedStep]:
    return [
        SeedStep("plans", "订阅套餐", TARGET),
        SeedStep("products", "产品库", TARGET, requires_demo=True),
        SeedStep("knowledge_base", "业务话术库", TARGET, requires_demo=True),
    ]


@pytest.fixture()
def spy(monkeypatch):
    """顶掉 `_try`：记录被执行的 label，返回固定 5。"""
    calls: list[str] = []

    async def fake_try(label: str, fn):  # noqa: ANN001
        calls.append(label)
        return 5

    monkeypatch.setattr(bootstrap, "_try", fake_try)
    return calls


@pytest.mark.asyncio
async def test_non_demo_skips_demo_steps(spy):
    result = await seed_base_data(_steps(), demo_mode=False)

    assert spy == ["订阅套餐"], f"只有非演示步骤该执行，实际调用 {spy}"
    assert result == {"plans": 5, "products": 0, "knowledge_base": 0}


@pytest.mark.asyncio
async def test_demo_mode_runs_everything(spy):
    result = await seed_base_data(_steps(), demo_mode=True)

    assert spy == ["订阅套餐", "产品库", "业务话术库"], f"demo 模式应全跑，实际 {spy}"
    assert result == {"plans": 5, "products": 5, "knowledge_base": 5}


@pytest.mark.asyncio
async def test_skip_keeps_keys(spy):
    """跳过只改值、不删键 —— 键少一个会被读成「这一步不存在」。"""
    skipped = await seed_base_data(_steps(), demo_mode=False)
    full = await seed_base_data(_steps(), demo_mode=True)

    assert set(skipped) == set(full)


@pytest.mark.asyncio
async def test_default_reads_config(spy, monkeypatch):
    """不传 demo_mode 时读 `config.demo_mode`（运行期读，不是 import 期固化）。"""
    from core.config import config as settings

    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    await seed_base_data(_steps())
    assert "产品库" in spy, "config.demo_mode=True 时应执行演示步骤"

    spy.clear()
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    await seed_base_data(_steps())
    assert "产品库" not in spy, "config.demo_mode=False 时应跳过演示步骤"


# ---------------------------------------------------------------------------
# 组合根清单（**清单型**判据：钉住"哪些步骤必须标记"）
# ---------------------------------------------------------------------------
#: 判别标准：**灌的是编造的业务数据**（演示商品 / picsum 素材 / 演示话术 /
#: 演示规则 / 种子竞品快照 / 种子订单）⇒ 必须 requires_demo=True。
#: 真实客户看到空态，好过看到"别人的假数据"。
MUST_BE_DEMO_ONLY = frozenset(
    {
        "demo_store",
        "products",
        "assets",
        "candidates",
        "monitors",
        "competitor_snapshots",
        "platform_rules",
        "knowledge_base",
        "skills",
        "trade",
        "market_snapshots",
    }
)


def test_wiring_marks_business_seeds():
    from wiring import SEED_STEPS

    by_key = {s.key: s for s in SEED_STEPS}
    missing = sorted(k for k in MUST_BE_DEMO_ONLY if k not in by_key)
    assert not missing, f"清单里没有这些步骤（改过名？）：{missing}"

    not_marked = sorted(k for k in MUST_BE_DEMO_ONLY if not by_key[k].requires_demo)
    assert not not_marked, f"这些步骤灌的是演示数据，但没有 requires_demo=True：{not_marked}"


def test_plans_is_never_demo_only():
    """套餐是**基础数据**：缺了注册接口直接 500，绝不能跟着 demo 开关走。"""
    from wiring import SEED_STEPS

    plans = next(s for s in SEED_STEPS if s.key == "plans")
    assert plans.requires_demo is False
