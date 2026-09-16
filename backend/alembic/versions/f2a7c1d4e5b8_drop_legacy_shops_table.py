"""p1-c: 删掉账户侧遗留的 shops 表与 shopplatform 枚举

Revision ID: f2a7c1d4e5b8
Revises: d1e2f3a4b5c6
Create Date: 2026-09-16 14:40:00.000000

==============================================================================
为什么要删（P1-c 收拢，2026-09-16）
==============================================================================
本项目曾有**两套店铺实体**，ID 空间不同、互不同步：

    | 侧 | 表 | ID 形态 | 谁在读 |
    |----|----|---------|--------|
    | 账户侧 | `shops` | UUID | 只有 core/identity/shop_router.py 的 7 个端点 |
    | 业务侧 | `stores_store` | `store_xxx` | 15 个业务模块的 `get_current_shop_id*` |

实测（本轮，全后端 AST/grep 统计）：
  · 那 7 个 `/api/v1/shops` 端点**生产 0 调用点**（前端只调 `/api/v1/stores`）；
  · `shops` 表在开发库里只有 1 行 —— 隔离自检脚本的产物 `TenantB-Shop`；
  · 用 `POST /shops` 建出来的店在业务侧**根本不可用**：把它的 UUID 放进
    `X-Shop-ID` 打业务端点，业务侧查 `stores_store` 查不到 ⇒ 403。
    ⇒ 这条路会**安静地生产一批废店**（不报错、不告警，建的时候一切正常）。

收拢后层级唯一（Account / AccountMember 见 core/identity/account_models.py）：

    User ──(owner_user_id)──> Account ──(account_id)──> StoreRecord
                                 │
                                 └──(account_members)──> User

⇒ 账户侧实体整片清掉：ORM 模型（`Shop` / `ShopPlatform` / `User.shops`）、
  路由（`core/identity/shop_router.py`）、中间件里那套租户上下文设施
  （`tenant_context` 家族），以及**本表的物理存储**。

★ 业务侧分区键 `store_xxx` 一动不动：16 张业务表的外键、全部前端调用、
  `X-Shop-ID` 语义都不变。所以本迁移**完全不触碰** `stores_store`。

==============================================================================
★ 为什么**没有**数据迁移（upgrade 里不搬数据）
==============================================================================
按上面的实测结论，`shops` 里的行就是**废店**（业务侧不可用），不该搬进
`stores_store` —— 搬进去只会凭空多出用户看不懂、点开就 403 的店铺。

⚠️ 但这条判断依赖「本库的 shops 只有自检脚本产物」这一前提。
   若某个部署里 `shops` 确有真实数据，请**先人工核对**再执行本迁移：
   本文件的 downgrade 能重建**表结构**，但**恢复不了数据**。

幂等性：全部 `IF EXISTS`。对「已手工清理过」的库是 no-op，
对「干净 upgrade 上来的库」是唯一一次真实执行。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a7c1d4e5b8'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 `shops` 表与 `shopplatform` 枚举（幂等）。

    ★ 顺序：**先表后类型**。枚举类型的依赖来自表的列，表还在时
      `DROP TYPE` 会被 PostgreSQL 以 `DependentObjectsStillExist` 拒绝。
    ★ 索引随表一起消失，但显式 `DROP INDEX IF EXISTS` 一次：
      历史库上可能存在基线未记录的手工索引名，留着它会让
      `alembic downgrade` 后的重建撞名。
    """
    op.execute("DROP INDEX IF EXISTS ix_shops_owner_id")
    op.execute("DROP TABLE IF EXISTS shops")
    op.execute("DROP TYPE IF EXISTS shopplatform")


def downgrade() -> None:
    """重建 `shops` 表与 `shopplatform` 枚举（**结构可回滚，数据不可回滚**）。

    ★ 为什么照抄基线 `0d44a915bbb8` 的定义，而不是写 `pass`：
      downgrade 的契约是「把 schema 恢复到上一版的形状」。写 `pass` 会让
      `alembic downgrade` 显示成功，而库停在「比上一版少一张表」的状态 ——
      之后再 upgrade 也不会有任何提示，纯粹静默失真。

    ★ 让 `op.create_table` 的 `sa.Enum(..., name='shopplatform')` 隐式建类型
      （与基线生成方式一致），本函数不再手工 `CREATE TYPE`：
      执行本函数的前提是 upgrade 已把该类型删掉，故不存在撞名。
      ★ PG 的类型名是**全局**的（不在 schema 内），因此 name 必须显式写出。

    ★ 只恢复结构，不恢复行。原数据（开发库里的 `TenantB-Shop` 等）不会回来。
    """
    op.create_table(
        'shops',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column(
            'platform',
            sa.Enum('AMAZON_US', 'AMAZON_UK', 'TIKTOK', 'SHOPIFY', name='shopplatform'),
            nullable=False,
        ),
        sa.Column('seller_id', sa.String(length=255), nullable=True),
        sa.Column('marketplace_id', sa.String(length=20), nullable=True),
        sa.Column('api_credentials', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_connected', sa.Boolean(), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shops_owner_id'), 'shops', ['owner_id'], unique=False)
