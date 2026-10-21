"""店铺群管理模块"""
from modules.stores.router import router as stores_router

#: ★ 第 181 轮 · 批 B：把演示账号主人 email 提到门面。
#: 为什么需要它：`modules/skills/seed.py` 要把演示技能挂到**同一个**演示账号下
#: （否则会出现「演示店铺在 A 账号、演示技能在 B 账号」的分叉，而演示身份只能命中之一）。
#: 按 `test_module_facades.py` 契约，跨模块取名字必须走门面 ⇒ 这里一并声明。
#: ★ 第 182 轮：由常量 `DEMO_ACCOUNT_EMAIL` 改为**函数** `demo_account_email()`。
#:   常量是 import 期快照，而真源已上收到 `config.demo_account_email`（可运行期改）
#:   ⇒ 只有函数形式才能在任何时刻读到当前值。
#: ★ 它只读一个配置字段，导入本行**不产生任何 IO / 建表 / 后台任务**。
from modules.stores.demo import demo_account_email

#: ★ 第 325 轮补登：`modules/product_research/seed.py` 灌「市场洞察 mock」时要先知道
#: 「哪几家是演示店」（mock 只给演示账号用，绝不污染真实账号 —— 见该 seed 里
#: `only_for_shop_ids` 的注释）。它原本写的是 `from modules.stores.demo import ...`
#: 这种**深层引用**，越过了本门面 ⇒ `tests/test_module_facades.py` 条款 1 红。
#: ★ 为什么放这儿是安全的：`demo_store_ids` 是个 **async 函数**，import 本行
#:   **不产生任何 IO / 建表 / 后台任务**（与上面 `demo_account_email` 同理）。
from modules.stores.demo import demo_store_ids

#: ★ 第 387 轮：注册即播种要「按新账号建一家店」。
#: 为什么要走门面而不是让 `modules/onboarding` 自己 insert 一行：
#:   `modules/stores/router.py` 里维护着读缓存 `_store_db`（`/api/v1/stores` 的
#:   读源）。绕过 `create_store` 直接写 PG ⇒ 新店**要等重启才出现**，且不报错。
#: 本行导出的是**已经成对写好缓存 + 落库**的那个原语。
#: ★ 它 import 期不产生任何 IO（只定义函数），与上面两行同理。
from modules.stores.provisioning import create_store_for_account

__all__ = [
    "stores_router",
    "demo_account_email",
    "demo_store_ids",
    "create_store_for_account",
]
