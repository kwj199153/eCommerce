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
lifespan 与 `scripts/bootstrap_db.py`（CI 用）共用同一个函数，新增基础数据只改这里。

==============================================================================
★ 边界（不要越界）
==============================================================================
本模块**不建表**。建表只有两条正式路径：
    · alembic（CI / 生产 / 本地一键起库都走它）
    · `init_db()` 的 development 分支 create_all（仅本地兜底）
把建表混进来会让「迁移脚本是否真的能跑」失去验证（见 ci.yml 的注释）。
"""

from typing import Awaitable, Callable, Dict

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


async def seed_base_data() -> Dict[str, int]:
    """
    灌入全部基础/演示数据，返回 {步骤名: 新增条数}。

    ★ 顺序有意义：**订阅套餐必须最先**。
      `subscriptions.plan_id` 有外键指向 `subscription_plans.id`，
      套餐不在库里时注册接口直接 500（见下方 init_default_plans 调用处的注释）。
      其余 seed 之间无依赖，但都依赖「店铺已存在」——它们会自己查 stores 表，
      无店铺时返回 0（不是错误，见 test_seed_shop_ids.py 锁死的契约）。
    """
    result: Dict[str, int] = {}

    # ① 订阅套餐（free / pro / enterprise）—— 必须在最前
    #    缺失会导致注册接口 500：创建默认订阅时 plan_id=1 触发外键约束失败
    try:
        from core.metering.usage_tracker import init_default_plans
        from core.database import get_async_session

        async with get_async_session() as session:
            await init_default_plans(session)
        _log.info("✅ 订阅套餐基础数据已就绪")
        result["plans"] = 1
    except Exception as e:  # noqa: BLE001
        _log.warning("⚠️ 订阅套餐初始化跳过: {}", e)
        result["plans"] = 0

    # ② 产品库（SPU + SKU 分表；为每个已存在店铺各灌一份）
    from modules.products.seed import seed_products_if_empty
    result["products"] = await _try("产品库", seed_products_if_empty)

    # ③ 素材库
    from modules.assets.seed import seed_assets_if_empty
    result["assets"] = await _try("素材库", seed_assets_if_empty)

    # ④ 候选选品库
    from modules.candidates.seed import seed_candidates_if_empty
    result["candidates"] = await _try("候选选品库", seed_candidates_if_empty)

    # ⑤ 竞品监控池
    #    注意：本 seed 不硬编码 shop_id，而是查 stores 表取真实店铺 id 逐个灌。
    #    真实租户 id 是 X-Shop-ID 里的 store_xxxxxxxx，写死 "shop-1" 会导致
    #    那批数据任何请求都查不到（2026-09-12 已修，见 test_seed_shop_ids.py）。
    from modules.monitors.seed import seed_monitors_if_empty
    result["monitors"] = await _try("竞品监控池", seed_monitors_if_empty)

    # ⑥ 平台规则库（6 条规则 + 5 篇带正文的文档 / 每店铺）
    from modules.platform_rules.seed import seed_platform_rules_if_empty
    result["platform_rules"] = await _try("平台规则库", seed_platform_rules_if_empty)

    # ⑦ 业务话术库（每店铺一份默认库 + 6 条通用问答）
    from modules.knowledge_base.seed import seed_knowledge_if_empty
    result["knowledge_base"] = await _try("业务话术库", seed_knowledge_if_empty)

    return result
