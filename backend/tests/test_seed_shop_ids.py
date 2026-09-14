"""
seed 的 shop_id 注入回归测试

背景（2026-09-12 修复）：`candidates/seed.py` 与 `products/seed.py` 曾把
`shop_id` 写死成 `"shop-1"`，而真实租户 id 是 `X-Shop-ID` 头传进来的
`store_xxxxxxxx`（store_ 前缀 + 8 位 hex）—— 两者格式对不上，列表端点按
shop_id 过滤后**一条都查不到**，属于「灌了但等于没灌」。

更隐蔽的是：两个 seed 都有 `if count > 0: return 0` 守卫，表非空时根本不执行，
所以「查不到数据」并不等于「没有这个 bug」—— 它是定时炸弹，清库/换环境重启才爆。

本文件锁死三件事：
  1. **种子数据源里不允许出现 shop_id 字段**（必须运行时注入真实店铺 id）；
  2. **seed 函数必须从 stores 表取真实店铺 id**（源码级断言，防换个地方硬编码）；
  3. **表非空时幂等返回 0**（不重复灌）。

为什么第 2 条用源码断言而不是执行断言：seed 的行为测试需要「清表 → 跑 seed」，
但 tests 连的是开发库，清表会毁掉演示数据。源码断言同样能拦住「改回硬编码」。
"""

import ast
import importlib
import inspect

import pytest
from sqlalchemy import select, func

from core.database import async_session_factory


SEED_MODULES = {
    "candidates": {
        "module": "modules.candidates.seed",
        "data": "SEED_CANDIDATES",
        "fn": "seed_candidates_if_empty",
        "db": "modules.candidates.db_model",
        "model": "CandidateRecord",
    },
    "products": {
        "module": "modules.products.seed",
        "data": "SEED_PRODUCTS",
        "fn": "seed_products_if_empty",
        "db": "modules.products.db_model",
        "model": "SpuRecord",
    },
    "monitors": {
        "module": "modules.monitors.seed",
        "data": "SEED_SPECS",
        "fn": "seed_monitors_if_empty",
        "db": "modules.monitors.db_model",
        "model": "MonitorRecord",
    },
}


def _load(path: str):
    return importlib.import_module(path)


def _spec(key: str):
    """返回 (seed 模块, 种子数据列表, seed 函数, ORM 模型类)"""
    s = SEED_MODULES[key]
    mod = _load(s["module"])
    return (
        mod,
        getattr(mod, s["data"]),
        getattr(mod, s["fn"]),
        getattr(_load(s["db"]), s["model"]),
    )


# ====== 1. 种子数据源不含 shop_id ======

@pytest.mark.parametrize("key", list(SEED_MODULES))
def test_seed_data_has_no_hardcoded_shop_id(key):
    """种子数据列表里不允许出现 shop_id —— 它必须由 seed 函数运行时注入。"""
    _, data, _, _ = _spec(key)
    assert data, f"{key} 的种子数据不应为空"
    offenders = [d.get("id") or d.get("asin") for d in data if "shop_id" in d]
    assert not offenders, (
        f"{key} 的种子数据中仍有硬编码 shop_id 的条目：{offenders}；"
        f"应删除该字段，改由 seed 函数查 stores 表注入真实店铺 id"
    )


# ====== 2. 源码级断言：真的查了 stores 表 ======

@pytest.mark.parametrize("key", list(SEED_MODULES))
def test_seed_function_reads_real_shop_ids(key):
    """seed 函数必须从 StoreRecord 取真实店铺 id，并在无店铺时提前返回 0。"""
    _, _, fn, _ = _spec(key)
    src = inspect.getsource(fn)
    assert "StoreRecord.id" in src, f"{fn.__name__} 未从 stores 表取真实店铺 id"
    assert "if not shop_ids" in src, f"{fn.__name__} 缺少「无店铺则跳过」的守卫"
    # 真正的回归信号：若还在从种子数据里取 shop_id，说明数据源又混进了归属字段
    # （该字段已从 SEED_* 移除，取它会直接 KeyError）
    assert '["shop_id"]' not in src and "['shop_id']" not in src, (
        f"{fn.__name__} 仍在从种子数据里取 shop_id（该字段已从数据源移除）"
    )


def test_no_shop_1_literal_in_seed_modules():
    """
    AST 级检查：三个 seed 模块里不允许存在字符串常量 'shop-1'。
    （docstring 里的历史说明是长文本，不等于该字面量，不会被误伤。）
    """
    for key in SEED_MODULES:
        mod, _, _, _ = _spec(key)
        tree = ast.parse(inspect.getsource(mod))
        lits = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        assert "shop-1" not in lits, f"{key} 的 seed 模块仍有硬编码 'shop-1' 字面量"


# ====== 3. 幂等：表非空时返回 0、不新增行 ======

@pytest.mark.parametrize("key", list(SEED_MODULES))
async def test_seed_is_idempotent_when_table_not_empty(key):
    """开发库里三张表都已有数据 → seed 必须返回 0 且行数不变（不重复灌）。"""
    _, _, fn, model = _spec(key)

    async with async_session_factory() as session:
        before = (await session.execute(select(func.count()).select_from(model))).scalar_one()

    returned = await fn()

    async with async_session_factory() as session:
        after = (await session.execute(select(func.count()).select_from(model))).scalar_one()

    if before > 0:
        assert returned == 0, f"{fn.__name__} 在表非空时仍写入 {returned} 条"
        assert after == before, f"{fn.__name__} 在表非空时改变了行数：{before} -> {after}"


# ====== 4. 库里已落地业务行的归属合法性 ======

async def test_existing_candidates_use_valid_shop_ids():
    """
    candidates 表里已落地的行，其 shop_id 必须来自 stores 表。
    唯一允许的例外是空串（无租户头写入的历史遗留，属待清理脏数据）——
    出现 'shop-1' 这类旧占位值即视为回归。
    """
    from modules.stores.db_model import StoreRecord
    from modules.candidates.db_model import CandidateRecord

    async with async_session_factory() as session:
        real = set((await session.execute(select(StoreRecord.id))).scalars().all())
        used = set((await session.execute(
            select(CandidateRecord.shop_id).distinct()
        )).scalars().all())

    invalid = {s for s in used if s not in real}
    assert "shop-1" not in invalid, f"candidates 表仍有旧占位 shop_id：{invalid}"
    assert invalid <= {""}, f"candidates 表存在无法归因的 shop_id：{invalid - {'', 'shop-1'}}"
