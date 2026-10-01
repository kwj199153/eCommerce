"""组合根（composition root）—— 跨层装配清单的**唯一真源**。

==============================================================================
★ 为什么要有这一层（第 335 轮 P0-7）
==============================================================================
`core/` 是内核，**不应认识任何业务模块的名字**。但有两件事天然需要一份
「本应用有哪些业务模块」的清单：

  · 把全部 ORM 模型注册进 `Base.metadata`（否则 alembic autogenerate 漏表、
    development 的 create_all 建不出表）；
  · 把基础/演示数据种进空库（否则注册接口因 `subscription_plans` 空表直接 500）。

历史上这两份清单**硬编码在 `core/database.py` 与 `core/bootstrap.py` 里**
⇒ 构成 `core → modules` 反向依赖共 **28 处**（`core` 反向 import `modules.*`），
与分层方向（`modules → core`）相反。

⇒ 本模块把「清单」外移到**组合根**，内核只保留**机制**：

    core/database.py   : register_all_models(model_modules)  —— 按名单导入模型模块
    core/bootstrap.py  : seed_base_data(seed_steps)          —— 按步骤跑引导

★ 依赖方向由此反转：
    `wiring → core`、`wiring → modules` 都是**合法方向**；
    `core` 不再 import 任何 `modules.*`。

★ 本模块的位置：`backend/wiring.py`（顶层）—— 既不在 `core/` 也不在
  `modules/`。调用方是各**进程入口**：`main.py`（API）、`alembic/env.py`
  （迁移）、`scripts/bootstrap_db.py`（CI / 一键起库），以及若干探针脚本。
  ⇒ 「什么时候装配」由入口决定，「装配什么」只有这里一份。

★ 为什么清单存的是**字符串模块名**而不是直接 import 实体：
  本模块被 `alembic/env.py` 在迁移时导入。若在顶层 import 各业务的 `seed`
  模块，会把它们的服务层 / LLM 客户端 / 平台适配一并拉进迁移进程
  （迁移只需要 ORM 元数据）。字符串清单让「导入时机」推迟到真正调用的那一刻。
"""

from __future__ import annotations

# ★ `SeedStep` 的定义住在 `core/bootstrap.py`（它是**机制层**的数据类型）；
#   本模块只提供**清单**。方向是 `wiring → core`（合法），
#   反之（core 认识组合根）才是不该有的。
from core.bootstrap import SeedStep

# =============================================================================
# 一、ORM 模型清单 —— `register_all_models()` 的唯一输入
# =============================================================================
# ★★ 为什么必须是唯一真源：
#   本清单有**两个消费者** —— `init_db()`（开发期 create_all 兜底）与
#   `alembic/env.py`（autogenerate 比对 `target_metadata`）。
#   历史上两处各写一份，`env.py` 那份漏了 monitors / platform_rules /
#   knowledge_base / voice_clone / aigc_media 共 5 个模块 ⇒ `target_metadata`
#   里少 9 张表 ⇒ autogenerate 生成的迁移**静默漏表**（不报错、不告警，
#   只在全新库上表现为「表不存在」）。
#
# ⇒ 新增业务模块时**只改这里**，两个消费者自动同步。
MODEL_MODULES: tuple[str, ...] = (
    # --- core 层实体（入边 ≥ 2 的基础域；`core → core` 是合法方向）---
    "core.identity.models",
    # 账户域（★ P1-b/P1-c 2026-09-16）：Account/AccountMember 取代 shops 的架构位置；
    # EmailToken/LoginAttempt 服务邮箱验证、密码重置与登录审计。
    "core.identity.account_models",
    "core.identity.auth_models",
    # ★ 第 140 轮：StoreRecord 随实体归位搬到 core/stores/。
    "core.stores",
    # 通用审计日志（audit_logs）—— 第 327 轮 P0-5：把「谁在什么时候对**哪个
    # 对象**做了什么」从各处散落的 logger.info 提升为可查询、可追责的记录。
    # ★ core 层实体（入边 ≥ 2 的基础域，与 stores 同组）；**零外键** ——
    #   审计必须比被记录的主体活得久，理由见 core/audit/models.py 文件头。
    "core.audit.models",
    # --- modules 层业务域 ---
    "modules.billing.models",
    "modules.products.db_model",
    "modules.assets.db_model",
    "modules.candidates.db_model",
    "modules.amazon_sp.db_model",
    "modules.conversation.db_model",
    "modules.monitors.db_model",
    "modules.platform_rules.db_model",
    "modules.knowledge_base.db_model",
    # 附加模块：语音克隆（独立表 shop_voice，不 ALTER 任何既有表）
    # 无条件导入以完成 metadata 注册；是否真正启用由 config.voice_clone_enabled 决定
    "modules.voice_clone.db_model",
    # AIGC 异步任务表（aigc_jobs）—— 长任务的状态权威源
    "modules.aigc_media.db_model",
    # 客服工单表（cs_tickets）—— 第 143 轮 A4：工单从「只在内存里造一个就返回」
    # 变成真的落库（此前 success=True 的工单号指向不了任何记录）。
    "modules.customer_service.db_model",
    # 长期记忆三张表（memory_profiles / memory_entries / memory_logs）
    # —— 第 149 轮 C2：让「记忆与进化」页从硬编码假页面变成有真存储。
    # ★ 键是 owner_id（人）而不是 thread_id（会话）⇒ 跨会话有效，
    #   这也是它不能复用 conversation 那三张表的原因。
    "modules.memory.db_model",
    # 技能仓库三张表（skills / skill_revisions / skill_favorites）：
    # 第 181 轮 · 批 B 建前两张（「能力全量常驻 system prompt」→
    # 「按需加载的技能机制」）；第 194 轮补第三张（技能收藏）。
    "modules.skills.db_model",
    # 复盘库表（review_reports）：「资料库 → 复盘库」——
    # 复盘结果**人工确认后**才留档。此前 6 项能力算完即弃：
    # 老板看一眼就没了，既无从回看，也无从「拿上期做对比」。
    "modules.review_analyst.db_model",
    # 交易履约 + 买家反馈域（orders / order_items / shipments / customer_reviews /
    # review_attributions / review_dispositions / compensation_rules / sku_health_scores）
    # —— 第 283 轮新增。注意：这里的 `customer_reviews` 与上面 review_analyst 的
    #   `review_reports` 是**两回事**（买家差评 vs 运营复盘归档）—— 别只看名字。
    "modules.trade.db_model",
    # 选品市场洞察快照（market_snapshots）—— 第 305 轮「蓝海挖掘大盘云图」。
    # 「选品前市场洞察」六维度的数据落点，演示 mock 只灌演示账号（is_demo 标记）。
    "modules.product_research.db_model",
    # 提示词覆写表（prompt_versions）—— 第 351 轮 · P0-7 B 档。
    # ★ 它出现在「业务模块清单」里**不是**因为归属 —— 这张表刻意没有
    #   store_id / account_id（平台级配置，不属于任何租户，见该模块文件头）。
    #   登记它的唯一理由是 `target_metadata` 必须认识它的 ORM 实体，
    #   否则 autogenerate 会**静默漏表**（不报错，只在全新库上表现为「表不存在」）。
    "modules.prompt_versions.db_model",
)


# =============================================================================
# 二、基础/演示数据引导步骤 —— `seed_base_data()` 的唯一输入
# =============================================================================
#: 引导步骤清单。★ **顺序有意义**。
#:
#: ① `plans` 必须最前：`subscriptions.plan_id` 有外键指向 `subscription_plans.id`，
#:    套餐不在库里时注册接口直接 500。它是内建步骤（`core.bootstrap` 提供），
#:    因为它要拿一个数据库 session，与其余 seed 的 `() -> int` 签名不同。
#: ② `demo_store` 紧随其后：下面各 seed 可能要给演示账号店铺补灌数据。
#: ③ `competitor_snapshots` 的输入就是 `monitors` 表（池子为空则一行都不展开）。
#: ④ `trade` 排在**产品库之后**：`pick_anchor_sku` 要按三级优先度从**该店自己的
#:    产品库**里挑锚定 SKU，产品库为空的店会被整店跳过。
SEED_STEPS: tuple[SeedStep, ...] = (
    # ① 订阅套餐（free / pro / enterprise）—— 必须在最前
    #    缺失会导致注册接口 500：创建默认订阅时 plan_id=1 触发外键约束失败
    SeedStep("plans", "订阅套餐", "core.bootstrap:seed_default_plans"),
    #
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
    SeedStep("demo_store", "演示店铺标记", "modules.stores.demo:ensure_demo_stores"),
    # ② 产品库（SPU + SKU 分表；为每个已存在店铺各灌一份）
    SeedStep("products", "产品库", "modules.products.seed:seed_products_if_empty"),
    # ③ 素材库
    SeedStep("assets", "素材库", "modules.assets.seed:seed_assets_if_empty"),
    # ④ 候选选品库
    SeedStep("candidates", "候选选品库", "modules.candidates.seed:seed_candidates_if_empty"),
    # ⑤ 竞品监控池
    #    注意：本 seed 不硬编码 shop_id，而是查 stores 表取真实店铺 id 逐个灌。
    #    真实租户 id 是 X-Shop-ID 里的 store_xxxxxxxx，写死 "shop-1" 会导致
    #    那批数据任何请求都查不到（2026-09-12 已修，见 test_seed_shop_ids.py）。
    SeedStep("monitors", "竞品监控池", "modules.monitors.seed:seed_monitors_if_empty"),
    # ⑤b 竞品快照（把上面的监控池**展开**成逐日时序行）
    #     ★ 顺序有硬依赖：本步的输入就是 `monitors` 表，池子为空则一行都不展开
    #       （刻意不去编一批竞品 —— 那正是本轮要删掉的东西）。
    #
    #     ★ 为什么必须有这一步：竞品 Agent 原先经 `get_data_source()` 取数，
    #       无 SP-API 凭据时回退到 `MockAmazonDataSource` —— 每次查询**现场随机**
    #       生成 6 个竞品（TP-Link / Anker / JBL…），与用户监控池里真正盯的对象
    #       （ZestPro / Voltage / CafeNow…）**零交集**，且同一问题两次答案不同。
    #       落库后 Agent 只读 `amazon_competitor_snapshots`，可复盘、可对账。
    SeedStep(
        "competitor_snapshots",
        "竞品快照",
        "modules.amazon_sp.seed:seed_competitor_snapshots_if_empty",
    ),
    # ⑥ 平台规则库（6 条规则 + 5 篇带正文的文档 / 每店铺）
    SeedStep(
        "platform_rules", "平台规则库", "modules.platform_rules.seed:seed_platform_rules_if_empty"
    ),
    # ⑦ 业务话术库（每店铺一份默认库 + 6 条通用问答）
    SeedStep(
        "knowledge_base", "业务话术库", "modules.knowledge_base.seed:seed_knowledge_if_empty"
    ),
    # ⑧ 技能仓库（第 181 轮 · 批 B）
    #    ★ 与演示店铺**同构**的两步：① 确保示例技能存在（幂等，不覆盖已有正文）
    #      ② 把演示账号名下的技能标 `is_demo=True`（双向收敛，残留会被降回 False）。
    #      详见 `modules/skills/seed.py` 的文件头。
    #    ★ 它不依赖店铺，也不给任何店铺灌数据 —— 技能是**账号级**资源，
    #      与「一店铺一租户」的业务数据是两个维度。
    SeedStep("skills", "技能仓库（演示示例）", "modules.skills.seed:ensure_demo_skills"),
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
    SeedStep("trade", "交易履约（订单/物流/差评）", "modules.trade.seed:seed_trade_if_empty"),
    # ⑩ 选品市场洞察快照（第 305 轮 · 蓝海挖掘大盘云图）
    #    ★ 演示 mock 只灌演示账号店铺（is_demo=True），真实账号空态 fail-closed。
    #    seed 内部默认目标 = 演示店铺，不碰真实账号数据。
    SeedStep(
        "market_snapshots",
        "选品市场洞察快照",
        "modules.product_research.seed:seed_market_snapshots_if_empty",
    ),
)

__all__ = ["MODEL_MODULES", "SEED_STEPS", "SeedStep"]
