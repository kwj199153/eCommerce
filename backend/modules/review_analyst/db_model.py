"""运营复盘库（ReviewReports）持久化 ORM 模型

为 `资料库 → 复盘库`（侧边栏 key = `reviews`）提供 PostgreSQL 持久化。

==============================================================================
★ 这个库是干什么的：**人工确认过的**复盘结果留档
==============================================================================
老板原话：

    我资料库开一个复盘资料库，当复盘 agent 的结果满意就入库

⇒ 复盘结果**默认不落库**（6 项能力是纯聚合计算，每次按当前数据源现算），
  只有老板点了「归档到复盘库」才留一份。这与本仓既有的「确认后入库」范式
  逐字同族：AIGC 出图 → `AssetArchiveModal`（`okText="确认归档"`）→ 营销素材库。

★ 为什么**不**在生成复盘时自动落库：
  自动落库 = 每跑一次留一条 ⇒ 库里很快堆满没人看过的中间结果，「上期是哪一期」
  变得不可判定（本仓判据：空状态优于虚构默认；同理，「没被看过的结果」不应与
  「被老板确认过的结果」混在一起）。人工确认这个动作本身就是**筛选**。

==============================================================================
★ 为什么存「客户端回传的快照」而不是「按 report_type 重跑一遍」
==============================================================================
入库的语义是**留档**，不是**重算**：

  · 重跑会拿到**另一批数字**（数据源按当前时刻取数，且 Mock 档 seed 相同但
    真实档每天变）⇒ 存下来的报告**不等于**老板刚才看过并点头的那一份。
    那正好废掉了「结果满意就入库」这件事本身。
  · 重跑还需要把「report_type → service 函数 + 默认天数」再写一份映射 ——
    那份映射的唯一真源已经在 `agent.py::_SERVICE_CALLS`，抄一份必然漂移
    （本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到）。

⇒ 所以 `data` 列就是**老板确认的那一份结构化快照原样**。
  服务端只做三件事：① 校验 `report_type` / `period_days`；
  ② 把归属与周期**覆盖**成服务端算出来的值（见下面「归属」一节）；
  ③ 落库。**不做任何数字上的二次加工。**

==============================================================================
★ 归属：`shop_id` 只能服务端注入
==============================================================================
本表的 `shop_id` 与其余 16 张业务表同口径 —— 字符串外键指向 `stores_store.id`，
由 router 的 `Depends(get_current_shop_id)`（strict 版）解析后注入。

★ 落库前还会把快照里的 `store_id` **覆盖**成同一个值：请求体里的 `data` 是
  前端回传的，它可以被改（改一下就是往**自己**这家店的库里写一份标着别家
  `store_id` 的报告）。覆盖是一个**唯一的写入点**，不是「接收了但忽略」。
  同族先例：`schemas.ReviewRequest` 干脆没有 `store_id` 字段。

==============================================================================
★ 幂等键为什么是 (shop_id, report_type, period_days, period_end) 而不是三个
==============================================================================
`period_days` **一个人撑不起「周期」这个概念**：days=30 的月报，8 月那份与
9 月那份的 `period_days` 完全相同 —— 若键只有 (shop_id, report_type, period_days)，
第二个月归档会**覆盖掉**第一个月，于是「下一期复盘读到上期做对比」这件事
在数据层就不可能成立（只剩一行，没有「上期」）。

⇒ 补一维 `period_end`（该份报告覆盖的**最后一天**，`YYYY-MM-DD`）：
  · 同一份报告当天重复归档 ⇒ 命中同一 (type, days, period_end) ⇒ **更新**（幂等，不产生重复行）
  · 隔一期再归档 ⇒ period_end 变了 ⇒ **新增**一行 ⇒ 天然支持跨期对比

★ `period_end` 由**服务端**按当天日期写入，不取请求体里的值：
  它是幂等键的一部分，客户端可控就等于客户端能决定「覆盖哪一条」。

==============================================================================
★ 为什么 `summary` 单列存一份（它明明也在 `data` 里）
==============================================================================
列表/工具出参**不回 `data`**（一份报告的 `details` 里可能挂着 35 行 SKU 明细，
十几 KB；列表 20 条就是几百 KB，塞进模型上下文更是不行）。
若列表要用的一句话结论只住在 `data` 里，那「不回 data」这条优化就没意义了
（仍然得把 JSON 读出来再扔掉）。

⇒ `summary` 是**写入期从同一份快照派生**的投影（不是第二份真源，也不独立编辑），
  单列存下来供列表直接用。这跟 `platform_rules` 把 `title` 单列、正文整篇存
  是同一类取舍。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base

#: 复盘报告类型（与 `schemas.ReviewReport.report_type` / service 六项能力一一对应）。
#: ★ 放这里而不是 service：本表要对它做**写口校验**，且查询侧（`spec.py` 的过滤
#:   值域、工具 description 的可选值）都要读同一份 —— 三处各写一遍必然漂移。
REVIEW_REPORT_TYPES: tuple = (
    "weekly_report",
    "monthly_review",
    "ad_review",
    "product_performance",
    "inventory_health",
    "profit_audit",
)


class ReviewReportRecord(Base):
    """复盘库表（`资料库 → 复盘库` 的数据源）。"""
    __tablename__ = "review_reports"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_review_reports_shop_id_stores_store",
        ),
        # ★ 幂等键（见模块 docstring「幂等键为什么是四维」）：
        #   同一个 (店铺, 报告类型, 周期长度, 周期末日) 只允许一行 ⇒
        #   重复归档是 UPDATE 而不是堆重复行。约束名供 `service.save_report`
        #   的 upsert 语义与将来的排障引用。
        UniqueConstraint(
            "shop_id", "report_type", "period_days", "period_end",
            name="uq_review_reports_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 租户隔离维度（空串 = 无租户上下文；写口由 strict 守卫拦下，不会写进空串）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # weekly_report / monthly_review / ad_review / product_performance /
    # inventory_health / profit_audit（见 REVIEW_REPORT_TYPES）
    report_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    period_days: Mapped[int] = mapped_column(Integer, default=7, index=True)
    #: 本份报告覆盖的最后一天 `YYYY-MM-DD`（服务端按归档当天写入）
    period_end: Mapped[str] = mapped_column(String(32), default="", index=True)

    #: 一句话结论（写入期从 data 派生的投影；列表/工具出参直接用它，见模块 docstring）
    summary: Mapped[str] = mapped_column(Text, default="")

    #: 结构化快照原样（`ReviewReport` 的 dict：metrics / details / insights / actions）。
    #: ★ 故意用 JSON 整体存取而不是拆列：六种报告的 details 形状**互不相同**
    #:   （campaigns / sku_rank / products / items / sales+ad），拆列会得到一张
    #:   大半字段恒 NULL 的宽表，而访问模式是「取整份报告」。
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<ReviewReportRecord {self.id} {self.report_type} "
            f"days={self.period_days} end={self.period_end}>"
        )


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'review_reports.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `modules/platform_rules/db_model.py`、`core/stores/models.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
