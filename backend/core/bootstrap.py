"""
数据库「就绪」引导 —— 基础数据的唯一真源

==============================================================================
★ 为什么要有这个模块
==============================================================================
「把数据库从空带到可用」这件事本来只写在 `main.py` 的 lifespan 里，
于是它有**两个消费者却只有一份实现**的问题被掩盖了：

  · 应用启动（main.py lifespan）—— 一直有
  · CI（.github/workflows/ci.yml）—— **一条都没有**

后果实测（探针 `.workbuddy/probes/project-audit-20260915/script-r51_ci_e2e.py`）：
在「alembic upgrade head 建好 33 张表但零数据」的空库上跑全量 pytest，
出现大面积 ERROR，首个根因是：

    asyncpg.exceptions.ForeignKeyViolationError:
      insert or update on table "subscriptions" violates foreign key
      constraint "subscriptions_plan_id_fkey"
      DETAIL: Key (plan_id)=(1) is not present in table "subscription_plans".

即 `subscription_plans` 空表 → 注册/订阅链路全断。
⇒ 「本地全绿」推不出「CI 全绿」，因为本地那份数据是**开发库攒下来的**。

所以把「建 schema 之外的全部引导动作」收敛到这里：
lifespan 与 `scripts/bootstrap_db.py`（CI 用）共用同一个函数；**步骤清单住在**
组合根 `wiring.SEED_STEPS`，新增基础数据只改那一处。

==============================================================================
★ 边界（不要越界）
==============================================================================
本模块**不建表**。建表只有两条正式路径：
    · alembic（CI / 生产 / 本地一键起库都走它）
    · `init_db()` 的 development 分支 create_all（仅本地兜底）
把建表混进来会让「迁移脚本是否真的能跑」失去验证（见 ci.yml 的注释）。
"""

import importlib
from typing import Awaitable, Callable, Dict, NamedTuple, Sequence

from core.logger import get_logger

_log = get_logger("core.bootstrap")


async def _try(label: str, fn: Callable[[], Awaitable[int]]) -> int:
    """
    跑一个 seed 步骤，失败只告警不中断。

    ★ 为什么保持「不中断」：这些是**演示/基础数据**，缺了会少功能但不该让服务起不来。
      但必须留下痕迹（`_log.warning` 带原因）—— 静默吞掉会让 CI 又变成假门禁。
    """
    try:
        n = await fn()
        if n:
            _log.info("✅ {} 种子数据已预置 {} 条", label, n)
        return n
    except Exception as e:  # noqa: BLE001
        _log.warning("⚠️ {} 种子数据跳过: {}", label, e)
        return 0


class SeedStep(NamedTuple):
    """一个引导步骤（**清单**住在组合根 `wiring.SEED_STEPS`）。

    key    : `seed_base_data()` 返回字典里的键（CI / 探针对账用）
    label  : 日志里显示的中文名
    target : `"包.模块:属性"` —— **延迟解析**，避免 import 本模块时把各业务
             seed（连同它们的服务层 / LLM 客户端 / 平台适配）一并拉进来。
    """

    key: str
    label: str
    target: str


def _resolve(target: str) -> Callable[[], Awaitable[int]]:
    """把 `"包.模块:属性"` 解析成可调用对象（延迟到真正要跑的那一刻才 import）。"""
    module_name, _, attr = target.partition(":")
    if not attr:
        raise ValueError(f"SeedStep.target 必须是 'pkg.mod:attr' 形式，收到 {target!r}")
    return getattr(importlib.import_module(module_name), attr)


async def seed_default_plans() -> int:
    """内建步骤：预置订阅套餐（free / pro / enterprise）。

    ★ 为什么它是内建步骤而不是 `modules/billing/seed.py` 里的一个函数：
      它要拿一个数据库 session（`init_default_plans(session)`），
      与其余 seed 的 `() -> int` 签名不同；而 `init_default_plans` 本身
      住在 `core.metering`（`core → core` 是合法方向）。
    ★ 顺序：**必须最前**（见 `wiring.SEED_STEPS` 的注释）——缺失会让注册
      接口 500：创建默认订阅时 `plan_id=1` 触发 `subscriptions_plan_id_fkey`。
    """
    from core.database import get_async_session
    from core.metering.usage_tracker import init_default_plans

    async with get_async_session() as session:
        await init_default_plans(session)
    return 1


async def seed_base_data(steps: Sequence[SeedStep]) -> Dict[str, int]:
    """按 `steps` 的顺序灌入全部基础/演示数据，返回 {步骤 key: 新增条数}。

    ★ 本函数只做**机制**：顺序、标签、目标全部由调用方（组合根）给出 ——
      `core` 不认识任何业务模块名（第 335 轮 P0-7 消除 `core → modules` 28 处）。
    ★ `steps` 必填、不给默认值：漏传 ⇒ 当场 `TypeError`，
      而不是静默地"引导完成、一条数据没有"（那是一个无报错的故障）。

    ★ 顺序为什么有意义（由 `wiring.SEED_STEPS` 保证）：
      **订阅套餐必须最先** —— `subscriptions.plan_id` 有外键指向
      `subscription_plans.id`，套餐不在库里时注册接口直接 500
      （见下方 `seed_default_plans` 的注释）。其余 seed 之间无依赖，
      但都依赖「店铺已存在」——它们会自己查 stores 表，无店铺时返回 0
      （不是错误，见 test_seed_shop_ids.py 锁死的契约）。
    """
    result: Dict[str, int] = {}
    for step in steps:
        result[step.key] = await _try(step.label, _resolve(step.target))
    return result
