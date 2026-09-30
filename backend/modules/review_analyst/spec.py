"""运营复盘库 —— 声明式查询元数据（`core.library_query.LibrarySpec`）。

★ 为什么这个库也要登记一份 spec
--------------------------------------------------------------------------
第 218 轮把「作用域 / 排序白名单 / limit 归一 / 真实 count / 去重 / 字段投影 /
出参信封」七件事抽进 `core.library_query` 之后，侧边栏「资料库」那 6 个库
**每一个**都在自己包里声明了一份 spec（`ASSET_SPEC` / `MONITOR_SPEC` /
`FAQ_SPEC` / `RULE_SPEC` / `PRODUCT_SPEC` / `CANDIDATE_SPEC`）。
复盘库是第 7 个 ⇒ 跟着同一范式走。

若不登记、改为在 `service.list_saved_reports` 里手写 `order_by(...)`：
  · 排序维度就变成「服务层硬编码一份 + 工具 description 里再描述一份」，
    而 description 面向模型 —— 它说的可选值与代码真正校验的那份**必然漂移**
    （第 216 轮实测过这个形态：传「通过」静默回空列表，与「真的没有」长得一样）；
  · `count` 与 `list` 的过滤口径会各写一遍（第 216 轮踩过的「列表 9 条、
    总数 11」）。
⇒ 所以排序/过滤/计数一律交给内核，本文件只回答「这个库能按什么排、按什么筛」。

★ `key="reviews"` 必须与前端侧边栏的菜单 key 逐字一致
--------------------------------------------------------------------------
消费方是**两份**：前端 `components/Sidebar/KnowledgeBase.vue` 的 `<a-menu-item
key="reviews">`，与前端 `utils/appActions.ts` 的 `AppView`。
跨端对齐由 `frontend/scripts/check-review-library-view.cjs` 钉住
（前端那侧是唯一可执行真源；本文件在 Python 侧，无法在 Node 门禁里读，
故门禁钉的是「前端三处 + 后端工具名/端点」这一组，见该脚本头部说明）。
"""

from core.library_query import FilterSpec, LibrarySpec

from .db_model import REVIEW_REPORT_TYPES, ReviewReportRecord

#: 排序维度：`{对外名: (模型属性, 方向)}`。
#:
#: · `period_end` —— 默认维度。**为什么不按 `created_at` 排**：老板说的「上期」
#:   是**业务周期**（上一周 / 上个月），不是「上一次点归档的时刻」。两份报告
#:   同一天归档、但覆盖周期不同时，按归档时刻排会得到任意顺序。
#:   降序 ⇒ 最近的周期在最前，`list_reviews` 取前 N 条正好是「最近几期」。
#: · `created_at` —— 归档时刻（回答「我最近归档了什么」）。
#: · `period_days` —— 周期长度（回答「30 天的月报有哪些」）。
REVIEW_SPEC = LibrarySpec(
    key="reviews",
    label="复盘库",
    model=ReviewReportRecord,
    sort_fields={
        "period_end": ("period_end", "desc"),
        "created_at": ("created_at", "desc"),
        "period_days": ("period_days", "desc"),
    },
    default_sort="period_end",
    filters={
        # ★ 值域**不在这里再抄一遍**：直接取 `db_model.REVIEW_REPORT_TYPES`
        #   （写口校验读的是同一个元组）。抄一份的后果是「写口拒收、读口放行」
        #   或反之 —— 两种都只在特定取值下才暴露。
        "report_type": FilterSpec(attr="report_type", values=REVIEW_REPORT_TYPES),
    },
)
