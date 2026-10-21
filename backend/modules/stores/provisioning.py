"""店铺「配置」（provisioning）—— 平台侧建店，**不经 HTTP**。

==============================================================================
为什么单独一个文件，而不是塞进 `router.py`
==============================================================================
`router.py` 是 HTTP 契约面（请求 / 响应 / 权限 / 档位闸 / 凭证加密）。
而「按账号建一家店」是一个**领域动作**，它还会被系统触发（注册即播种），
那时候没有请求上下文、没有 `current_user`、也不该走档位闸。

写进 router 会让「这段代码到底在响应谁的请求」变成一件需要读调用栈才知道的事。

==============================================================================
★★ 内存缓存必须同步写（这是本文件唯一容易漏的地方）
==============================================================================
`_store_db` 是 `/api/v1/stores` 的读源（见 router 文件头：利润引擎等同步代码
直接读它）。只写 PG、不写 dict ⇒ 新店**要等进程重启才出现**，而且**不报错**：
用户注册完看到「店铺列表为空」，你查数据库却发现店在。

所以这里复用 `create_store` 里那**必须成对**的两行：

    _store_db[store_id] = store      # 读缓存
    await _upsert_store_db(store)    # 权威存储

顺序也不能反：先落库再写缓存的话，中途失败会留下一个「内存里有、库里没有」
的店，它会在下一次重启时凭空消失。

==============================================================================
为什么**不**在这里过档位闸（`enforce_account_limit`）
==============================================================================
本函数只被两类调用方使用，且都用「账户当前为 0 家店」作为前置判据
（注册播种：新账号必然 0 家）。用户在 `POST /api/v1/stores` 手动建店时走的是
`create_store`，那里档位闸照旧生效。把闸门复制一份到这里，等于同一策略两份
实现 —— 而两份实现的下场一定是漂移。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from models.store import Store

# 同包内部取用（不是跨模块边界）：`_store_db` 与本文件必须看到**同一份**缓存，
# 这正是它不做成参数的原因 —— 传进来的副本会静默失效。
from modules.stores.router import _store_db, _upsert_store_db

#: 亚马逊美国站的 marketplace_id（参与方 ID）。写在这里而不是让调用方随手填字符串：
#: 这里错一个字母，`Marketplace(pid)` 解析就会抛 `UnsupportedMarketplace`，
#: 而现象是「注册后第一屏打不开」，与建店毫无关系的样子。
AMAZON_US_PARTICIPANT_ID = "ATVPDKIKX0DER"


async def create_store_for_account(
    *,
    owner_id: Optional[str],
    account_id: str,
    name: str,
    platform: str = "amazon",
    marketplace_id: Optional[str] = AMAZON_US_PARTICIPANT_ID,
    region_code: str = "us",
    currency: str = "USD",
) -> str:
    """在某账户下建一家店（不校验档位、不写凭证），返回 `store_xxx`。

    Args:
        owner_id: 「谁创建的」这一**事实**记录（审计/展示用，不参与授权）。
            系统建店时可以是 None，但注册播种应传新用户 id。
        account_id: 归属判定的**唯一依据**（`core/auth/accounts.py`）。
        name: 店名。调用方负责让它在账户内可辨认。

    Returns:
        新店铺 id（`store_` + 8 位 hex，与 `create_store` 同格式）。

    ★ 不写 `api_credentials`：凭证的唯一写入口是 `router._save_store_credentials`
      （Fernet 密文）。这里若顺手赋明文，等于把 P1-a 已修的缺陷重新引入。
    """
    store_id = f"store_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()

    store = Store(
        id=store_id,
        tenant_id="default_tenant",  # 历史兼容列，不参与任何判定
        owner_id=owner_id,
        account_id=account_id,
        name=name,
        platform=platform,
        marketplace_id=marketplace_id,
        region_code=region_code,
        currency=currency,
        # 与 `create_store` 一致：新店是「未连接」状态（不是「已同步」）。
        # 把未连接的店标成 active+connected 会让首屏显示「同步正常」，
        # 而实际上一条平台数据都没有 —— 典型的假成功。
        has_credentials=False,
        is_demo=False,
        created_at=now,
        updated_at=now,
    )

    _store_db[store_id] = store
    await _upsert_store_db(store)
    return store_id
