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

    # ①b 演示标记（★ 必须最先 —— 下面各 seed 可能要给演示店铺补灌数据）
    #
    #    ★ 它解决什么：演示档下 `GET /api/v1/stores` 曾恒返回空（安全修复 4612abb
    #      的成果：匿名不得见真实店铺）。但前端 `demo-token` 按设计不是身份 ⇒
    #      `user 恒为 None` ⇒ 列表恒空 ⇒ `current_shop_id` 写不进 localStorage
    #      ⇒ 所有业务请求不带 X-Shop-ID ⇒ **每个面板都是空的**。
    #      正解不是放宽过滤，而是给演示身份一个**专属数据集**。
    #
    #    ★ 第 176 轮重做：数据集的锚从"新建一家演示店铺"改为"**演示账号**"
    #      （`DEMO_ACCOUNT_EMAIL`，默认 tenant-test-a@example.com）—— 它名下
    #      4 家店（亚马逊1 / 亚马逊2 / 虾皮1 / 虾皮2）里就躺着老板要的那套
    #      `/mock/products/<ASIN>.png` 图文一一对应的数据。
    #      详见 modules/stores/demo.py 的文件头。
    #
    #    ★ 这里**不再**给演示店铺补灌种子数据（第 176 轮）：
    #      第 175 轮的形态是"新建一家空店 ⇒ 必须灌"；第 176 轮的演示店铺是
    #      **本来就装着演示数据的 4 家店**，补灌只会把 `SEED_*` 那套
    #      `picsum.photos` 随机图灌进原本干净的店铺（实测：虾皮1/2 各多了
    #      3 选品 / 6 产品 / 7 素材，亚马逊2 多了 6 产品 / 7 素材），
    #      正好把"图与商品不对应"重新灌回去 —— 而老板明确只要"保证亚马逊1"。
    #      ⇒ 去掉补灌。`only_for_shop_ids` 参数保留在各 seed 里
    #        （有 `test_seed_shop_ids.py` 守着，将来要"给指定店铺补灌"仍可用）。
    from modules.stores.demo import ensure_demo_stores

    result["demo_store"] = await _try("演示店铺标记", ensure_demo_stores)

    # ② 产品库（SPU + SKU 分表；为每个已存在店铺各灌一份）
    from modules.products.seed import seed_products_if_empty
    result["products"] = await _try(
        "产品库", seed_products_if_empty
    )

    # ③ 素材库
    from modules.assets.seed import seed_assets_if_empty
    result["assets"] = await _try(
        "素材库", seed_assets_if_empty
    )

    # ④ 候选选品库
    from modules.candidates.seed import seed_candidates_if_empty
    result["candidates"] = await _try(
        "候选选品库", seed_candidates_if_empty
    )

    # ⑤ 竞品监控池
    #    注意：本 seed 不硬编码 shop_id，而是查 stores 表取真实店铺 id 逐个灌。
    #    真实租户 id 是 X-Shop-ID 里的 store_xxxxxxxx，写死 "shop-1" 会导致
    #    那批数据任何请求都查不到（2026-09-12 已修，见 test_seed_shop_ids.py）。
    from modules.monitors.seed import seed_monitors_if_empty
    result["monitors"] = await _try(
        "竞品监控池", seed_monitors_if_empty
    )

    # ⑤b 竞品快照（把上面的监控池**展开**成逐日时序行）
    #     ★ 顺序有硬依赖：本步的输入就是 `monitors` 表，池子为空则一行都不展开
    #       （刻意不去编一批竞品 —— 那正是本轮要删掉的东西）。
    #
    #     ★ 为什么必须有这一步：竞品 Agent 原先经 `get_data_source()` 取数，
    #       无 SP-API 凭据时回退到 `MockAmazonDataSource` —— 每次查询**现场随机**
    #       生成 6 个竞品（TP-Link / Anker / JBL…），与用户监控池里真正盯的对象
    #       （ZestPro / Voltage / CafeNow…）**零交集**，且同一问题两次答案不同。
    #       落库后 Agent 只读 `amazon_competitor_snapshots`，可复盘、可对账。
    from modules.amazon_sp.seed import seed_competitor_snapshots_if_empty
    result["competitor_snapshots"] = await _try(
        "竞品快照",
        seed_competitor_snapshots_if_empty,
    )

    # ⑥ 平台规则库（6 条规则 + 5 篇带正文的文档 / 每店铺）
    from modules.platform_rules.seed import seed_platform_rules_if_empty
    result["platform_rules"] = await _try(
        "平台规则库", seed_platform_rules_if_empty
    )

    # ⑦ 业务话术库（每店铺一份默认库 + 6 条通用问答）
    from modules.knowledge_base.seed import seed_knowledge_if_empty
    result["knowledge_base"] = await _try(
        "业务话术库", seed_knowledge_if_empty
    )

    # ⑧ 技能仓库（第 181 轮 · 批 B）
    #    ★ 与演示店铺**同构**的两步：① 确保示例技能存在（幂等，不覆盖已有正文）
    #      ② 把演示账号名下的技能标 `is_demo=True`（双向收敛，残留会被降回 False）。
    #      详见 `modules/skills/seed.py` 的文件头。
    #    ★ 它不依赖店铺，也不给任何店铺灌数据 —— 技能是**账号级**资源，
    #      与「一店铺一租户」的业务数据是两个维度。
    from modules.skills.seed import ensure_demo_skills

    result["skills"] = await _try("技能仓库（演示示例）", ensure_demo_skills)

    # ⑨ 交易履约域（订单 / 明细 / 物流 / 差评 / 归因 / 补偿规则 / SKU 健康分）
    #
    #    ★ 为什么排在**最后**：它依赖上面 ② 的产品库 —— `pick_anchor_sku`
    #      要按三级优先度从**该店自己的产品库**里挑锚定 SKU，产品库为空的店
    #      会被整店跳过（不编一个产品库查不到的 SKU —— 那是「说得出来、
    #      指不到行」的死数据，见 modules/trade/seed.py 文件头）。
    #    ★ 灌的是**演示数据**（`source='mock_seed'`）：这套表的上游是适配层，
    #      在接上真实平台凭据之前，只有它能给出可演示的内容；
    #      `service.is_mock_source()` 让上层能在回答里如实标注这一点，
    #      而不是让「演示数据」与「真实同步」在界面上长得一模一样。
    from modules.trade.seed import seed_trade_if_empty

    result["trade"] = await _try(
        "交易履约（订单/物流/差评）", seed_trade_if_empty
    )

    # ⑩ 选品市场洞察快照（第 305 轮 · 蓝海挖掘大盘云图）
    #    ★ 演示 mock 只灌演示账号店铺（is_demo=True），真实账号空态 fail-closed。
    #    seed 内部默认目标 = 演示店铺，不碰真实账号数据。
    from modules.product_research.seed import seed_market_snapshots_if_empty

    result["market_snapshots"] = await _try(
        "选品市场洞察快照", seed_market_snapshots_if_empty
    )

    return result
