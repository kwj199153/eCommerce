"""交易履约 + 买家反馈域（trade）—— 模块门面

★ 为什么这三个名字要在这里显式导出：`wiring.MODEL_MODULES` 之外，
  凡是跨包引用本模块的地方都应走 `__init__`（`core/stores` 的先例）。
  直接 `from modules.trade.db_model import X` 会让「模型搬家」变成全仓搜索。

名称避坑（重要）：本模块的 `customer_reviews` 是**买家差评**，
与 `modules/review_analyst` 的 `review_reports`（运营复盘归档）毫无关系 ——
命名陷阱详见 `db_model.py` 文件头。
"""

from .sync import (
    MANUAL_METHOD, SourceNotSupported, attribution_row_id, item_row_id,
    order_row_id, review_row_id, shipment_row_id,
    sync_orders_from_source, sync_reviews_from_source, sync_trade,
    upsert_order, upsert_review,
)
from .demo_script import (
    DEMO_FALLBACK_SKU, DEMO_ORDER_SPECS, DEMO_REVIEW_SAMPLES,
    build_demo_order_payloads, build_demo_review_payloads,
    demo_review_gold,
)
from .db_model import (
    ATTRIBUTION_CAUSES, CAUSE_LABELS,
    CompensationRuleRecord, CustomerReviewRecord, OrderItemRecord, OrderRecord,
    ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord,
    SkuHealthScoreRecord,
    SOURCE_CSV_IMPORT, SOURCE_MOCK_SEED, SOURCE_PLATFORM_API,
)
# ★ 工具层：宿主（客服等）经本门面挂载，不许 `from modules.trade.tools import ...`
from .tools import set_shop_id_resolver, trade_tools
from .service import (
    DISPOSITION_CHANNELS, DISPOSITION_EXECUTION_MODES, DISPOSITION_STATUSES,
    # ★ `DISPOSITION_TRANSITIONS` **故意不导出**：状态机是本模块**内**策略，
    #   没有任何跨模块消费方（router 只在注释里引过它）。放进 `__all__` 会把
    #   「内部策略」伪装成「跨模块契约」⇒ 按契约面语义，测试就得把桩打在门面
    #   上，而 service 内部读的是**定义处** ⇒ 桩永不生效（假绿）。
    CompensationOverBudget, DispositionError, DispositionNotFound,
    MissingShopContext, parse_iso,
    apply_compensation_rule, approve_disposition, attribute_review,
    backfill_dispositions, build_disposition_draft, collect_evidence,
    compute_sku_health, compute_transit_and_delay, count_dispositions,
    count_orphan_reviews, count_recent_negative_reviews, get_disposition,
    get_order_context,
    get_review_context, is_mock_source,
    issue_disposition, list_dispositions, list_recent_negative_reviews,
    list_orphan_reviews, list_reviews_for_spu,
    list_enabled_rules_for_cause, match_compensation_rule, propose_disposition,
    record_execution_receipt,
    # ★ 第 304 轮后半：补偿规则 CRUD + 人工补归因（此前这两个能力没有端点）
    ATTRIBUTABLE_CAUSES, CONDITION_KEYS, ACTION_TYPES,
    list_compensation_rules, create_compensation_rule, update_compensation_rule,
    delete_compensation_rule, set_review_attribution,
    reject_disposition,
    scan_reviews_risk, score_from_parts,
)
# ★ 风险话术识别（第 299 轮 P0）：**纯判定，无任何写操作**。
#   P1 的读端点与 Agent 工具一律经本门面取名字（不许 `from modules.trade.risk_scan import`）。
from .risk_scan import (
    CATEGORY_LABELS, DECISION_CLEAN, DECISION_RISK, DECISION_UNKNOWN,
    LEVEL_HIGH, LEVEL_LABELS, LEVEL_LOW, LEVEL_MEDIUM, LEVEL_UNKNOWN,
    RISK_CATEGORIES, SUGGESTED_ACTION, RiskHit, ScanResult,
    batch_chunk_count, fuse, scan_llm, scan_llm_batch, scan_naive, scan_rules,
    scan_text,
)

__all__ = [
    # 数据模型
    "OrderRecord", "OrderItemRecord", "ShipmentRecord", "CustomerReviewRecord",
    "ReviewAttributionRecord", "ReviewDispositionRecord",
    "CompensationRuleRecord", "SkuHealthScoreRecord",
    # 归因常量
    "ATTRIBUTION_CAUSES", "CAUSE_LABELS",
    # 落库同步（本模块唯一写入路径）
    "SourceNotSupported", "MANUAL_METHOD",
    "order_row_id", "item_row_id", "shipment_row_id", "review_row_id",
    "attribution_row_id",
    "upsert_order", "upsert_review",
    "sync_orders_from_source", "sync_reviews_from_source", "sync_trade",
    # 演示剧本（唯一真源，seed 与 Mock 数据源共用）
    "DEMO_ORDER_SPECS", "DEMO_FALLBACK_SKU",
    # ★ 演示差评样本（独立于订单）+ 金标导出：
    #   评测脚本必须从这里取标签，不得自己在脚本里再抄一份。
    "DEMO_REVIEW_SAMPLES", "demo_review_gold",
    "build_demo_order_payloads", "build_demo_review_payloads",
    "SOURCE_MOCK_SEED", "SOURCE_CSV_IMPORT", "SOURCE_PLATFORM_API",
    # 服务层
    "MissingShopContext", "CompensationOverBudget",
    "compute_transit_and_delay", "attribute_review", "collect_evidence",
    "list_enabled_rules_for_cause",
    "match_compensation_rule", "apply_compensation_rule",
    # ★ 第 304 轮后半：补偿规则 CRUD + 人工补归因
    "ATTRIBUTABLE_CAUSES", "CONDITION_KEYS", "ACTION_TYPES",
    "list_compensation_rules", "create_compensation_rule", "update_compensation_rule",
    "delete_compensation_rule", "set_review_attribution",
    "compute_sku_health", "score_from_parts",
    "get_order_context", "get_review_context", "list_recent_negative_reviews",
    # ★ 产品 ↔ 差评 软关联（第 289 轮）：差评落在 SKU 上（SPU 只是聚合壳），
    #   关联不上产品的那批必须有个兜底出口，否则它们只是静默消失。
    "list_reviews_for_spu", "list_orphan_reviews", "count_orphan_reviews",
    "count_recent_negative_reviews",
    "is_mock_source",
    # ★ 处置（第 287 轮 P0-2：给 review_dispositions 补出口）
    #   写入路径只有 `propose_disposition` 一个；approved / issued 是**人**的动作，
    #   不在 Agent 工具里 —— 发券/退款不可逆，必须过人。
    # ★ 状态机 `DISPOSITION_TRANSITIONS` 不在此列（理由见上方 import 处）；
    #   值域（STATUSES / CHANNELS）才是跨模块契约。
    "DISPOSITION_STATUSES", "DISPOSITION_CHANNELS", "DISPOSITION_EXECUTION_MODES",
    "DispositionError", "DispositionNotFound",
    "build_disposition_draft", "propose_disposition", "approve_disposition",
    "reject_disposition", "issue_disposition", "get_disposition",
    # ★ `record_execution_receipt`（第 304 轮）：`issued` → `executed` 的唯一路径。
    #   本系统不调平台接口，这一步是「人做完回来登记」，给「已执行」一个真落点。
    "record_execution_receipt",
    "list_dispositions", "count_dispositions", "backfill_dispositions",
    # ★ `parse_iso` 也导出：客服算「签收了几天」要解析 `delivered_at`，
    #   在客服侧再写一份时间解析就是**同一判定两份实现**（本仓明令禁止）。
    "parse_iso",
    # ★ 风险话术识别（第 299 轮 P0，口径见第 302 轮）—— 四类：加码要挟 / 索赔
    #   / A-to-Z 前兆 / 开 case。★ 输入语域是**已公开发布的商品评价**，不是私信会话。
    #   ★ `naive` 通道在本模块**故意保留但不可用**：它是反面基线（用来说明
    #     「关键词风控」为什么不可行），`fuse()` 内部把它拒在融合之外。
    "RiskHit", "ScanResult", "RISK_CATEGORIES", "CATEGORY_LABELS",
    "LEVEL_HIGH", "LEVEL_MEDIUM", "LEVEL_LOW", "LEVEL_UNKNOWN",
    "DECISION_RISK", "DECISION_CLEAN", "DECISION_UNKNOWN", "SUGGESTED_ACTION",
    "LEVEL_LABELS",
    "scan_naive", "scan_rules", "scan_llm", "fuse", "scan_text",
    # ★ 第 300 轮：批量语义通道（生产路径）+ 包数计算（供读数对账）。
    #   `scan_full` 已退役：deep 走「四类命中跳过 + 其余一次批量」，
    #   留一个没人调用的逐条入口就是第二份语义实现。
    "scan_llm_batch", "batch_chunk_count",
    # ★ 第 299 轮 P1：把「风险识别」接到界面上的**只读**视图（service 层）。
    #   排序口径（风险→未定论→干净）与「deep 无凭据 ⇒ degraded」都在它里面，
    #   端点与未来的 Agent 工具共用这一份。
    "scan_reviews_risk",
    # 工具层（供宿主 Agent bind_tools）
    "trade_tools", "set_shop_id_resolver",
]
