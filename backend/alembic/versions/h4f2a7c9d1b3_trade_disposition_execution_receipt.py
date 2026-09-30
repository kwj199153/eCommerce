"""review_dispositions 补「平台执行回执」五列 + `executed` 状态（第 304 轮 P0·A 档）

Revision ID: h4f2a7c9d1b3
Revises: g1d4e7f2a8b5
Create Date: 2026-09-29 10:00:00.000000

==============================================================================
★ 为什么必须补这五列：`issued` 一个人承担了两种语义
==============================================================================
老板问：「差评台账处置后，是不是应该接 API 到平台真实处置？」

取证结论（`.workbuddy/probes/r303_closure/`，只读取证）：

  · `modules/trade/*.py` 里 `httpx` / `requests` / `aiohttp` / `urllib` **命中 0 次**；
  · `amazon_sp/data_sources/base.py` 的 11 个能力清一色 `fetch_*` + `health_check`，
    **没有任何写方法**；`auth.py` 只申请 `sellingpartnerapi::migration`（只读 scope）；
  · `platforms/base.py` 抽象基类同样没有写方法，`shopee/client.py` 大量 TODO + `return []`。

⇒ `issue_disposition` 只做三件事：状态 `approved → issued`、生成**本地**券码
  `_mint_coupon_code()`、可选重写回复草稿。**零出站调用**。

于是库里此前**没有任何字段**能回答「平台上到底做没做」，而界面却写着
「已发放」+ `effect: '退回部分或全部货款'` —— 这是**字面为真、暗示为假**：
本地确实改了状态，但「钱退回去了」是界面自己编的。

==============================================================================
★ 为什么选「加回执列」而不是「现在就把平台 API 接上」
==============================================================================
接真写接口需要：平台侧写权限 scope（Amazon 要重新申请 LWA scope）、
退款/发券的幂等键设计、失败重试与对账、多平台适配。这些是 B/C 档的活。

本轮走 A 档：**先把「已核准」与「已执行」在数据层分开**。
  · `issued`   ＝ 本地已核准（券码已生成、回复可对外），**平台侧还没动**；
  · `executed` ＝ 平台上真的执行完了，且有回执（`executed_at` / `executed_by` /
                 `platform_ref` / `execution_mode` / `receipt_note` 五列）。

分开之后，「已发放」这个词就**不再是无据可查的宣称**：没登记回执的行，
`executed_at` 恒为空串 ⇒ 界面只能画成「已核准 · 待平台执行」。

==============================================================================
★ 五列一律空串起步，不用 0 / false / "-"
==============================================================================
`""` 的语义是「还没登记」。给默认值填 0 / false 会让**空回执伪装成已回执**
—— 与本仓「拿不到就报未知，不许猜」同一条口径。

★ `server_default` 只在这一步存在：`ADD COLUMN ... NOT NULL` 在已有数据的表上
  必须给默认值（否则 PG 无法为既有行补值），补完立刻摘掉 —— 留着会让「默认值」
  有两个真源（SQL 一份、ORM 的 Python 侧一份）。

★ 幂等：与 `d4a7b2e8c1f6` 同款 `_has_column` 守卫。开发期 `init_db()` 在
  development 下对**同一份** `Base.metadata` 跑 `create_all`，新库启动过一次
  就带上这五列了；此后 `upgrade head` 再 `ADD COLUMN` 会抛 `DuplicateColumn`
  —— 而那恰恰是「本该顺利」的场景。

★ 反向迁移只 `drop_column`：这几列是「加出来的」，回退就该只把它们退掉。
  列没了，`executed` 这个状态也就没有数据支撑了 —— 不会出现「库里有、代码不用」
  的残渣。

★ 本迁移**不改** `status` 列：状态值域是 Python 侧的
  `service.DISPOSITION_STATUSES`，库里 `status` 只是 `String(16)`，
  既有的 `issued` 行不需要回填（它们的语义本来就是「已核准」）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h4f2a7c9d1b3'
down_revision: Union[str, Sequence[str], None] = 'g1d4e7f2a8b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'review_dispositions'

#: (列名, 长度)；`receipt_note` 是 Text，长度为 None
_COLUMNS: tuple[tuple[str, str, object], ...] = (
    ('execution_mode', '执行方式：manual（人工在平台执行）；空串 = 还没登记', sa.String(16)),
    ('platform_ref', '平台侧凭证号：退款单号 / 券码 / case id', sa.String(128)),
    ('executed_by', '登记人（服务端注入，不由客户端自报）', sa.String(64)),
    ('executed_at', '登记时间（ISO 字符串）', sa.String(64)),
    ('receipt_note', '回执备注：做了什么、在哪做的', sa.Text()),
)


def _has_column(table: str, column: str) -> bool:
    """表与列是否都已在库里（理由见文件头「幂等」一节）。"""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    for name, _comment, type_ in _COLUMNS:
        if _has_column(_TABLE, name):
            continue
        op.add_column(
            _TABLE,
            # server_default 只为「给既有行补空串」而存在，下一步就摘掉。
            sa.Column(name, type_, nullable=False, server_default=''),
        )
        op.alter_column(_TABLE, name, server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    for name, _comment, _type in _COLUMNS:
        if _has_column(_TABLE, name):
            op.drop_column(_TABLE, name)
