"""
交易履约 + 买家反馈域 —— 服务层（唯一计算口径）

====================================================
★ 为什么要有一个 service 而不是「工具里现算」
====================================================
「是不是迟了」「赔多少」「这个 SKU 健康吗」这三个判断，本模块**只在这里算一次**。
工具层 / 路由层 / seed 全部调用本文件的函数。

理由不是洁癖。让同一判断散落在 Agent 提示词、工具函数、seed 脚本三处，
后果已经在 `cs-refund-playbook` 那类技能身上发生过一次：
技能正文要求「引用订单/物流证据判断责任归属」，而没有任何地方能产出那个证据
=> 要求变成口号。判断若不能被某个函数断言，它就只是文案。

====================================================
★ 三条硬口径（改动前请三思）
====================================================
1. **归因的证据优先于关键词。**
   先看数据仓库里到底有没有「这单迟了 5 天」这种**事实**；有证据就按证据归类，
   只有在拿不到订单/物流时才退回文本关键词。反过来会让「按关键词猜」盖过
   「按事实判」—— 那是把 LLM 的读后感当证据。

2. **拿不到就报 'unknown'，不许猜。**
   本仓对「静默退化」一贯 fail-closed；`unknown` 是**合法结果**，也必须能被断言
   （见 `ATTRIBUTION_CAUSES` 里的注释）。

3. **补偿金额超 `budget_cap` 必须显式报错，不许悄悄按上限赔。**
   悄悄截断会让「规则说赔 8 块」与「实际赔了 5 块」都不报错地并存，
   审计时无从发现。
"""
# @generated-by: split_trade_service.py (第 355 轮)

# ============================================================
# ★ 原 `service.py` 的**导入段原文**（逐行搬回，含注释）
#   目的：让 `service.X` 的名字空间与拆分前**完全一致**。
#   例：`service.risk_scan`（测试在它上面打桩）、`service.datetime`
#   这些『导入进来的名字』当时是可访问的，re-export 定义是不够的。
# ============================================================
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import String, and_, desc, func, literal, or_, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.tenant.scoping import scope_condition
from modules.products import SkuRecord, SpuRecord
# ★ 风险话术识别（第 299 轮 P0/P1）：本模块**只读**消费它的判定能力。
#   注意方向：`risk_scan` 不 import `service`（叶子模块），因此这里没有循环。
from modules.trade import risk_scan
from modules.trade.db_model import (
    ATTRIBUTION_CAUSES, CAUSE_LABELS,
    CompensationRuleRecord, CustomerReviewRecord, OrderItemRecord, OrderRecord,
    ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord,
    SkuHealthScoreRecord, SOURCE_MOCK_SEED,
)


# ============================================================
# ★ 本包是 `modules/trade/service` 的**对外唯一契约面**。
#   拆分前它是一个 2535 行的单文件；拆分后按子域分文件，
#   但**对外名字集合一字未变** —— 门面（`modules/trade/__init__.py`）、
#   `tools.py` / `router.py` 的 `service.X` 调用、以及直接
#   `from modules.trade.service import ...` 的测试全部照常工作。
#   ★ 私有名（`_review_risk_text` 等）也在此显式导出：
#     `tests/test_trade_demo_review_samples.py` 直引了 `_review_risk_text`。
# ============================================================

from ._base import (_log, MissingShopContext, MissingSiblingForReview, CompensationOverBudget, AttributionError, AttributionNotFound, RuleError, RuleNotFound, RuleConflict, DispositionError, DispositionNotFound, parse_iso, days_between, compute_transit_and_delay, _order_to_dict, _item_to_dict, _shipment_to_dict, _review_to_dict, _attribution_to_dict, _disposition_to_dict, _load_review_scoped, is_mock_source)
from .attribution import (_KEYWORD_RULES, _CAUSE_PRIORITY, _hit_keywords, collect_evidence, attribute_review, ATTRIBUTABLE_CAUSES, set_review_attribution)
from .rules import (CONDITION_KEYS, ACTION_TYPES, _rule_to_dict, _rule_row_id, _normalize_code, _validate_rule_shape, list_compensation_rules, create_compensation_rule, update_compensation_rule, delete_compensation_rule, _load_rule_scoped, list_enabled_rules_for_cause, match_compensation_rule, _conditions_match, apply_compensation_rule, _channels_from_action)
from .sku_health import (_HEALTH_WEIGHTS, _LOGISTICS_TOLERANCE, _PACKAGING_TOLERANCE, _clamp, score_from_parts, compute_sku_health, _count_orders_for_sku, _previous_score, get_sku_health_score)
from .queries import (get_order_context, get_review_context, _recent_negative_condition, list_recent_negative_reviews, count_recent_negative_reviews, _review_match_condition, _rating_condition, _match_kind_of, list_reviews_for_spu, _not_bound_to_sku, count_orphan_reviews, list_orphan_reviews)
from .review_risk import (RISK_SCAN_MAX_LIMIT, RISK_SCAN_MAX_LIMIT_DEEP, _RISK_DECISION_RANK, _llm_configured, _review_risk_text, _risk_block_from_scan, _unscannable_block, scan_reviews_risk)
from .systemic import (REPEAT_ISSUE_THRESHOLD, SYSTEMIC_NEGATIVE_RATE, VERDICT_LABELS, count_repeat_issues, analyze_review_systemic)
from .disposition import (DISPOSITION_STATUSES, DISPOSITION_TRANSITIONS, DISPOSITION_CHANNELS, DISPOSITION_EXECUTION_MODES, _REPLY_CAUSE_ZH, _REPLY_CAUSE_EN, _render_reply_drafts, _disposition_row_id, _mint_coupon_code, _assert_transition, _load_disposition_row, build_disposition_draft, propose_disposition, approve_disposition, reject_disposition, _issue_draft_inputs, _rerender_reply_drafts_on_issue, issue_disposition, record_execution_receipt, get_disposition, list_dispositions, count_dispositions, backfill_dispositions)

#: 拆分前后**逐个对账**用的名字清单（校验脚本读它）。
__all__ = [
    # _base.py
    "_log",
    "MissingShopContext",
    "MissingSiblingForReview",
    "CompensationOverBudget",
    "AttributionError",
    "AttributionNotFound",
    "RuleError",
    "RuleNotFound",
    "RuleConflict",
    "DispositionError",
    "DispositionNotFound",
    "parse_iso",
    "days_between",
    "compute_transit_and_delay",
    "_order_to_dict",
    "_item_to_dict",
    "_shipment_to_dict",
    "_review_to_dict",
    "_attribution_to_dict",
    "_disposition_to_dict",
    "_load_review_scoped",
    "is_mock_source",
    # attribution.py
    "_KEYWORD_RULES",
    "_CAUSE_PRIORITY",
    "_hit_keywords",
    "collect_evidence",
    "attribute_review",
    "ATTRIBUTABLE_CAUSES",
    "set_review_attribution",
    # rules.py
    "CONDITION_KEYS",
    "ACTION_TYPES",
    "_rule_to_dict",
    "_rule_row_id",
    "_normalize_code",
    "_validate_rule_shape",
    "list_compensation_rules",
    "create_compensation_rule",
    "update_compensation_rule",
    "delete_compensation_rule",
    "_load_rule_scoped",
    "list_enabled_rules_for_cause",
    "match_compensation_rule",
    "_conditions_match",
    "apply_compensation_rule",
    "_channels_from_action",
    # sku_health.py
    "_HEALTH_WEIGHTS",
    "_LOGISTICS_TOLERANCE",
    "_PACKAGING_TOLERANCE",
    "_clamp",
    "score_from_parts",
    "compute_sku_health",
    "_count_orders_for_sku",
    "_previous_score",
    "get_sku_health_score",
    # queries.py
    "get_order_context",
    "get_review_context",
    "_recent_negative_condition",
    "list_recent_negative_reviews",
    "count_recent_negative_reviews",
    "_review_match_condition",
    "_rating_condition",
    "_match_kind_of",
    "list_reviews_for_spu",
    "_not_bound_to_sku",
    "count_orphan_reviews",
    "list_orphan_reviews",
    # review_risk.py
    "RISK_SCAN_MAX_LIMIT",
    "RISK_SCAN_MAX_LIMIT_DEEP",
    "_RISK_DECISION_RANK",
    "_llm_configured",
    "_review_risk_text",
    "_risk_block_from_scan",
    "_unscannable_block",
    "scan_reviews_risk",
    # systemic.py
    "REPEAT_ISSUE_THRESHOLD",
    "SYSTEMIC_NEGATIVE_RATE",
    "VERDICT_LABELS",
    "count_repeat_issues",
    "analyze_review_systemic",
    # disposition.py
    "DISPOSITION_STATUSES",
    "DISPOSITION_TRANSITIONS",
    "DISPOSITION_CHANNELS",
    "DISPOSITION_EXECUTION_MODES",
    "_REPLY_CAUSE_ZH",
    "_REPLY_CAUSE_EN",
    "_render_reply_drafts",
    "_disposition_row_id",
    "_mint_coupon_code",
    "_assert_transition",
    "_load_disposition_row",
    "build_disposition_draft",
    "propose_disposition",
    "approve_disposition",
    "reject_disposition",
    "_issue_draft_inputs",
    "_rerender_reply_drafts_on_issue",
    "issue_disposition",
    "record_execution_receipt",
    "get_disposition",
    "list_dispositions",
    "count_dispositions",
    "backfill_dispositions",
]
