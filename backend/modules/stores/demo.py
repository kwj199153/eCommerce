"""
演示账号 —— 给「演示模式」一个**可归属、可隔离**的数据锚点（第 176 轮重做）

==============================================================================
★ 第 176 轮为什么推翻了第 175 轮的形态
==============================================================================
第 175 轮的实现是「**新建一家**无主演示店铺 `store_demo0001`，再用种子把数据灌进去」。
老板实测后的逐字反馈：

    「以前的图文是可以一一对应的，现在图片又变成了不对应了（是比一一对应更
      早的版本）；我需要的是演示模式下，有多个店铺（之前的亚马逊1，亚马逊2，
      虾皮1，虾皮2，然后选品库产品库都有11对应图文）；你现在这个好好像是更早
      的版本图文，并且只设置了1个店铺」
    「应该是一个演示账号，这个账号读取数据库中的 mock 数据，然后店铺和产品
      都无所谓了啊 都在我的演示账号下」

两个问题，**都在"新建一家店"这个形态本身**：

  ① **只建了 1 家店** —— 老板要的是 4 家（亚马逊1 / 亚马逊2 / 虾皮1 / 虾皮2）。
  ② **灌的是 `SEED_*` 常量那套数据，图片是 `https://picsum.photos/seed/...`**
     —— 随机照片，与商品标题毫无关系。而库里早先灌的演示数据用的是
     `/mock/products/<ASIN>.png`（**图片文件名 = ASIN**）⇒ 严格 1:1 对应
     （实测：`store_c3529ab1` 的 11 条选品 / 14 条产品全部命中）。
     老板要的就是后者，所以第 175 轮那家店看起来是"比一一对应更早的版本"。

⇒ 正解**不是**"再造一套数据"，而是**把演示身份锚到「演示账号」上**：
  老板本来就有一个装满演示数据的账号（`tenant-test-a@example.com` →
  account `4c4629a8-…`，名下 4 家店），那套图文 1:1 的数据就躺在它名下。
  演示身份要看到的就是**它名下的店铺**。

==============================================================================
★ 判定链没改，改的是「谁被标成 is_demo」
==============================================================================
`filter_accessible_stores(db, None, stores)` 仍然只返回 `is_demo=True` 的店铺
（第 175 轮那条窄口，`core/auth/accounts.py`）。本轮改的是**标记的来源**：

    第 175 轮：新建一家无主店并标它          ⇒ 1 家店、数据与真实库脱钩
    第 176 轮：把**演示账号名下的全部店铺**标上 ⇒ 4 家店、数据就是库里的

而且标记是**推导**出来的，不是硬编码 id 列表：老板往演示账号里加店铺，
下次启动就自动带上它，不用改代码。反向也收敛 —— 不属于演示账号的行会被
**清掉标记**（`is_demo=False`），所以「谁可见」永远只有一份事实。

==============================================================================
★ 为什么判定落在数据库列上，而不是硬编码 id
==============================================================================
硬编码 id 会让"演示店铺是哪一个"变成**两份实现**（seed 写死一个、鉴权再写死
一次比较），改一处就静默失配。列是**数据**，判定只有一处。
本模块只负责**写标记**，从不参与判定。

==============================================================================
★ 演示账号是谁：`config.demo_account_email`（可用环境变量覆盖）
==============================================================================
默认取 `tenant-test-a@example.com`（库里唯一一个装满了演示数据的账号）。
★ 刻意用 email 而不是 account id 硬编码：account id 是 uuid，换库就变；
  email 是人的标识，且能被 env 覆盖。
★ 第 182 轮：真源从本模块的 `os.getenv` 上收到 `core.config` ——
  同一个 email 现在同时决定「演示店铺归谁」与「演示身份是谁」，
  两处分离会让演示模式半死不活（见 `demo_account_email()` 的注释）。
"""

from typing import List, Optional

from sqlalchemy import select

from core.config import config
from core.database import async_session_factory
from core.identity.account_models import Account
from core.identity.models import User
from core.stores import StoreRecord


#: 演示账号的主人 email（演示数据都挂在这个账号下）。
#:
#: ★ 一个 user 可能有多个账号（`ensure_default_account` 之外还能手工建），
#:   本模块取**最早创建**的那个（与 `SHOP_ORDER_BY=(created_at, id)` 同口径，
#:   保证任何机器上选中的都是同一行）。
#:
#: ★★★ 第 182 轮：真源从「本模块的 `os.getenv`」改为 **`config.demo_account_email`**。
#:
#:   为什么必须改（这不是审美问题）：第 182 轮起，演示身份由
#:   `core/auth/demo_identity.py::resolve_demo_user` 解析成**演示账号主人**，
#:   它读的是 `config.demo_account_email`。若本模块继续读自己的 `os.getenv`，
#:   同一个概念就有了**两份实现**：老板在 .env 里改一处、另一处不知道
#:   ⇒ 演示店铺挂在 A 账号、演示技能挂在 B 账号，而演示身份只能命中之一
#:   —— 表现为"店铺列表有、技能仓库空"这种半死不活的状态。
#:   本仓判据：「同一判定两份实现 ⇒ 至少一份永远测不到」。
#:
#:   ★ 环境变量 `DEMO_ACCOUNT_EMAIL` 的覆盖能力**没有丢**：
#:     pydantic-settings 对 `demo_account_email` 字段默认就认同名大写环境变量
#:     （`case_sensitive=False`、无 `env_prefix`），且**还额外支持 .env 文件**。
#:
#:   ★ 为什么做成**函数**而不是模块级常量：常量在 import 时求值一次，
#:     测试里 `monkeypatch.setattr(config, "demo_account_email", …)` 就改不动它了
#:     —— 那会让"演示账号可配置"这件事只在生产生效、在测试里失效。
def demo_account_email() -> str:
    """演示账号主人 email（实时读配置，**不是** import 期快照）。"""
    return (config.demo_account_email or "").strip()


async def demo_account_id() -> Optional[str]:
    """
    演示账号 id；找不到返回 `None`（调用方据此退回"不标任何店铺"）。

    ★ 返回 `None` 而不是抛异常：演示账号缺失只影响演示体验，不该让
      `seed_base_data()` 整体失败（它在启动路径上）。
    """
    email = demo_account_email()
    if not email:
        # 显式留空 = 「关闭演示身份」的降级开关（见 config 字段描述）。
        return None
    async with async_session_factory() as session:
        return (
            await session.execute(
                select(Account.id)
                .join(User, User.id == Account.owner_user_id)
                .where(User.email == email)
                .order_by(Account.created_at, Account.id)
                .limit(1)
            )
        ).scalar_one_or_none()


async def ensure_demo_stores() -> int:
    """
    把「演示账号名下的全部店铺」标记为演示店铺（**幂等**，且双向收敛）。

    Returns:
        本次发生变化的行数：`0` 表示库里已经是期望状态（稳态，99% 的启动走这里）。

    ★ 与其余 seed 的关键差异：本函数**不判「表非空就跳过」**。
      店铺表非空是常态（真实店铺就住在这里），而演示标记必须**每次启动都校正**
      —— 老板手工改了归属、或换了一个演示账号，下一次启动就要生效。

    ★ 双向收敛（`!=` 而不是"只标 True"）：
      只标 True 会把历史残留留在库里 —— 例如第 175 轮建的那家无主店
      `store_demo0001`（`is_demo=True` 且 `account_id=None`），它会一直对演示身份
      可见。`bool(existing) != want` 顺手把它降回 False，不需要专门的清理逻辑。
    """
    acct_id = await demo_account_id()
    if acct_id is None:
        # 演示账号不存在 ⇒ 不动任何标记（fail-closed：宁可演示模式是空的，
        # 也不能因为"找不到账号"就把某家真实店铺标成演示店铺放出去）。
        return 0

    async with async_session_factory() as session:
        rows = (await session.execute(select(StoreRecord))).scalars().all()
        changed = 0
        for store in rows:
            want = store.account_id == acct_id
            if bool(getattr(store, "is_demo", False)) != want:
                store.is_demo = want
                changed += 1
        if changed:
            await session.commit()

    return changed


async def demo_store_ids() -> List[str]:
    """
    全部演示店铺 id（供 `core/bootstrap.py` 转交给各 seed 的 `only_for_shop_ids`）。

    ★ 返回**列表**而不是单个 id：演示账号名下有几家店由数据决定，不是常量。

    ★ 它的现在职责变小了：演示店铺就是 4 家**本来就有数据**的店，所以
      `only_for_shop_ids` 通常什么也不灌。留着是为了「老板往演示账号里新建店铺」
      这条路径 —— 新店会被七个 seed 补灌一份种子数据（幂等，已有的不动）。
    """
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(StoreRecord.id).where(StoreRecord.is_demo.is_(True))
            )
        ).scalars().all()
    return list(rows)
