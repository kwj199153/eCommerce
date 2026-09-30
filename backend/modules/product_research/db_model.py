"""
选品市场洞察快照持久化 ORM 模型（第 305 轮 · 蓝海挖掘大盘云图）

为「选品前市场洞察」提供 PostgreSQL 持久化。

==============================================================================
★ 为什么这个表叫「快照」而不是「实时市场」
==============================================================================
「选品前市场洞察」看的是**第三方类目全量数据**（品类分布 / 价格带 / 竞争密度 /
搜索热度 / 卖家分布 / 趋势变化），这些数据来自 Helium10 / 卖家精灵 / Keepa /
ABA 等外部数据源 —— **本仓现在没有**。这不是"缺一个图表"的问题，是"缺数据源"。

所以本表先把**数据结构**立住：站点 × 类目 × 日期 的一个快照行，六维度指标
打平成 JSON / 数值列。将来接真数据，只需**改写入层**（把第三方 API 的返回
落进这些列），读层（聚合端点 + 前端 Treemap）一行不动。

==============================================================================
★ 演示数据只给演示账号：不脏真实账号
==============================================================================
老板的原话：「我需要的数据库中的 mock 数据都是给演示账号用的，这样才不会脏数据」。

隔离复用现成的「店铺归属」真相源（第 176 轮，`modules/stores/demo.py`）：
演示数据挂到演示账号名下的店铺（`is_demo=True`），真实账号靠 account 边界
天然看不到。本表多一个 `is_demo` 冗余标记，是为了**读层能显式判断**
「这批数据是 mock 还是真实」，从而在响应里如实标注 `degraded: true` ——
而不是让演示数据与真实同步在界面上长得一模一样（同 `modules/trade/seed.py`
的 `source='mock_seed'` 思路）。

==============================================================================
★ 六维度字段设计（打平，避免"JSON 一坨查不动"）
==============================================================================
  · 品类分布    category_path（三级路径，`/` 分隔）+ category_name
  · 价格带      price_min / price_max / price_median（类目下商品成交价分布）
  · 竞争密度    seller_count（卖家数）+ listing_count（在售 ASIN 数）
  · 搜索热度    search_volume（月搜索量）
  · 卖家分布    new_seller_count（新卖家数，衡量入场难度）
  · 趋势变化    search_growth（搜索增长率 %）+ price_trend（价格趋势）
  · 蓝海评分    blue_ocean_score（0-100，由上面六维度综合算出的"值不值得进"）
"""

from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MarketSnapshotRecord(Base):
    """选品市场洞察快照表（/market-insight 数据源）"""
    __tablename__ = "market_snapshots"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_market_snapshots_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # msnap-xxx
    # 站点 + 类目 + 快照日期 定位一个快照行（同一类目跨日期有多行 ⇒ 趋势）
    site: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # amazon_us / amazon_uk / shopee_sg
    category_path: Mapped[str] = mapped_column(String(256), nullable=False, index=True)  # home_kitchen/kitchen_dining/coffee
    category_name: Mapped[str] = mapped_column(String(128), default="")  # 展示用末级类目名

    # ====== 六大维度（打平列） ======
    # 品类分布（类目下在售规模）
    listing_count: Mapped[int] = mapped_column(Integer, default=0)  # 在售 ASIN 数
    # 价格带（成交价分布，USD）
    price_min: Mapped[float] = mapped_column(Float, default=0)
    price_max: Mapped[float] = mapped_column(Float, default=0)
    price_median: Mapped[float] = mapped_column(Float, default=0)
    # 竞争密度
    seller_count: Mapped[int] = mapped_column(Integer, default=0)  # 卖家数
    # 搜索热度
    search_volume: Mapped[int] = mapped_column(Integer, default=0)  # 月搜索量
    # 卖家分布
    new_seller_count: Mapped[int] = mapped_column(Integer, default=0)  # 近 3 月新卖家数（入场难度）
    # 趋势变化
    search_growth: Mapped[float] = mapped_column(Float, default=0)  # 搜索增长率 %
    price_trend: Mapped[str] = mapped_column(String(16), default="stable")  # rising / stable / falling

    # ====== 蓝海综合评分（六维度算出的"值不值得进"） ======
    blue_ocean_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100

    # ====== 快照日期（趋势：同一类目多行按日期排序） ======
    snapshot_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # YYYY-MM-DD

    # ====== 归属与演示标记 ======
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="演示 mock 标记：读层据此显式标注 degraded（第 305 轮）",
    )

    source: Mapped[str] = mapped_column(String(32), default="mock_seed")  # mock_seed / third_party

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
# 理由同 `modules/candidates/db_model.py` 末尾：字符串外键 `stores_store.id`
# 需由声明方自己把目标表带进来（自洽），否则单独 import 本模块时 flush 会抛
# NoReferencedTableError。
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
