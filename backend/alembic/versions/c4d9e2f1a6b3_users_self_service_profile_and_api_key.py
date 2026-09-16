"""users 自助管理：个人资料列（phone/company/avatar_url/notification_prefs）+ user_api_keys 表

Revision ID: c4d9e2f1a6b3
Revises: f2a7c1d4e5b8
Create Date: 2026-09-16 21:05:00.000000

==============================================================================
内容（第 100 轮，2026-09-16）
==============================================================================
补 `frontend/src/views/Settings.vue` 那 7 个一直 404 的 `/users/*` 端点
所需的数据结构：

1. `users` 加四列
   - `phone` / `company`      ← `PUT /users/profile`
   - `avatar_url`             ← `POST /users/avatar`（落盘后存 `/static/avatars/...`）
   - `notification_prefs`     ← `PUT /users/notifications`（JSON，部分更新）
2. 新表 `user_api_keys`（**只存 sha256 与掩码串**，明文只在创建响应里给一次）

==============================================================================
★★★ 一、为什么**没用** autogenerate
==============================================================================
同目录 `d1e2f3a4b5c6` 的 docstring 记着那次事故：开发服务器开着
`--reload` ⇒ 改完 ORM 立刻 `create_all` 把新表建进开发库 ⇒
随后 autogenerate 对着开发库比对，**看到表已存在就静默漏掉 create_table**
⇒ 本机能跑通、全新库直接失败。

⇒ 本文件**手写**，并在**只跑过 alembic 的探针库**上验证
  （`upgrade head` + `alembic check` 双向确认）。

==============================================================================
★★★ 二、为什么本迁移必须是**幂等**的（第 101 轮补记的实测证据）
==============================================================================
「手写」只解决了漏表，没解决**抢建**。实测 2026-09-17 在开发库上：

    $ alembic current          → f2a7c1d4e5b8      （迁移没跑）
    information_schema.users   → 13 列，phone/company/avatar_url/
                                 notification_prefs **全部缺失**
    to_regclass('user_api_keys') → user_api_keys   （★ 表却已经在了！）

即：`--reload` 的 create_all 已经把**新表**建好了，但 create_all
**不给已有表加列** ⇒ 库里处于「半新」状态。此时直接 `upgrade head`
必然撞 `DuplicateTable`，而报错信息是「user_api_keys 已存在」，
看不出「真正缺的是 users 的四列」—— 极易误判成迁移写错。

⇒ 故本迁移改为**存在性探测 + 按需执行**，一个文件同时吃两种场景：
      · 全新库（只跑过 alembic）        → 正常建表 + 建列 + 建索引
      · 开发库（被 create_all 抢先建表）→ 只补缺失的四列，表/索引跳过
  与同仓 `a8c9d0e1f2b3_add_shop_voice_table.py` 的「幂等」约定一致。

★ 幂等之所以在这里**无害**：两种场景下的目标结构完全一致 ——
  create_all 走的是同一份 `Base.metadata`，实测建出的列/外键名
  （`fk_user_api_keys_user_id_users`）/三个索引名与本文件逐字相同，
  所以「跳过」不会留下与迁移意图不符的结构，`alembic check` 仍报无差异。

★ 三处与 ORM 的写法必须**逐字对齐**，否则 `alembic check` 会报差异：
  ① `key_hash` 在 ORM 是 `unique=True, index=True` ⇒ SQLAlchemy 生成的是
     **unique index**，不是 UniqueConstraint（别写成 UniqueConstraint）；
  ② `is_active` 的 `server_default` 用 `sa.text("true")` 与 ORM 的 `"true"` 对应；
  ③ 外键带显式 `name`（本仓约定，便于 downgrade / 排障定位）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d9e2f1a6b3'
down_revision: Union[str, Sequence[str], None] = 'f2a7c1d4e5b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ==============================================================================
# 存在性探测（幂等的实现手段）
# ==============================================================================
def _inspector():
    """当前连接的 inspector。**每次现取**，不要在模块层缓存 ——
    同一进程内可能先后连不同的库（CI 的 downgrade/upgrade 往返）。"""
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {i["name"] for i in _inspector().get_indexes(table)}


_USER_NEW_COLUMNS = (
    # 全部可空：存量行没有这些值，且它们都不是判定依据
    ("phone", sa.Column("phone", sa.String(length=32), nullable=True)),
    ("company", sa.Column("company", sa.String(length=120), nullable=True)),
    ("avatar_url", sa.Column("avatar_url", sa.String(length=512), nullable=True)),
    # JSON 而不是 Text：读侧要按 key 取（见 models.merge_notification_prefs），
    # 存字符串会让"补默认值"那一步变成一次手工 json.loads + 异常处理。
    ("notification_prefs", sa.Column("notification_prefs", sa.JSON(), nullable=True)),
)

_API_KEY_INDEXES = (
    ("ix_user_api_keys_user_id", ["user_id"], False),
    # ★ unique index（不是 UniqueConstraint）—— 与 ORM 的 `unique=True, index=True` 对齐
    ("ix_user_api_keys_key_hash", ["key_hash"], True),
    ("ix_user_api_keys_user_active", ["user_id", "is_active"], False),
)


def upgrade() -> None:
    # ---- 1. users 四列（逐个探测：可能只缺一部分 —— create_all 从不动已有表）----
    for col_name, col in _USER_NEW_COLUMNS:
        if not _has_column("users", col_name):
            op.add_column("users", col)
        else:
            print(f"[c4d9e2f1a6b3] users.{col_name} 已存在，跳过")

    # ---- 2. user_api_keys ----
    if _has_table("user_api_keys"):
        # 开发库场景：create_all 已按同一份 metadata 建好，结构一致
        print("[c4d9e2f1a6b3] user_api_keys 已存在（create_all 抢先建表），跳过 create_table")
    else:
        op.create_table(
            "user_api_keys",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("key_masked", sa.String(length=64), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_user_api_keys_user_id_users",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # 索引独立探测：即使表是 create_all 建的，也要保证索引齐全
    for idx_name, cols, unique in _API_KEY_INDEXES:
        if not _has_index("user_api_keys", idx_name):
            op.create_index(idx_name, "user_api_keys", cols, unique=unique)
        else:
            print(f"[c4d9e2f1a6b3] 索引 {idx_name} 已存在，跳过")


def downgrade() -> None:
    """可逆。

    ★ 与 `d1e2f3a4b5c6` 不同：那次有**数据回填**，逆向会丢业务含义，故不逆。
      本次只加列与一张纯新增表，drop 回去没有任何歧义 ⇒ 完整实现 downgrade
      （CI 有 `downgrade base && upgrade head` 的往返断言）。

    ★ 同样做存在性探测：开发库里这张表可能是 create_all 建的，
      若已被手工处理过，硬 drop 会报错而不是安全跳过。
    """
    if _has_table("user_api_keys"):
        for idx_name, _cols, _u in _API_KEY_INDEXES:
            if _has_index("user_api_keys", idx_name):
                op.drop_index(idx_name, table_name="user_api_keys")
        op.drop_table("user_api_keys")

    for col_name, _col in reversed(_USER_NEW_COLUMNS):
        if _has_column("users", col_name):
            op.drop_column("users", col_name)
