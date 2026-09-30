"""候选 / 选品记忆域门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.candidates import <name>`；
     `from modules.candidates.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 为什么导出这些出口：它们正是两个跨模块消费者实际需要的
  **校验 / 读 / 生命周期流转原语 / 查询值域真源**：
    · `product_research`（选品分析师的工具层）—— 校验与落库（多轮槽位补齐 /
      去重 / 写库）、读详情、评审流转、评审通过推产品库；
    · `modules/library`（跨 Agent 共用的只读工具）—— 候选列表。
  其余行内读写留在 `service.py` 内部，不构成跨模块契约。

★ 第 205 轮扩出口（3 个）：`get_candidate` / `review_candidate` /
  `approve_candidate`。它们原先只以**内联代码**存在于 `router.py`，
  Agent 侧够不着（第 204 轮盘点：老板点名的「获取选品」「入产品库」两条缺口）。

★ 第 216 轮扩出口（3 个）：`count_candidates`（真实总数）/ `CandidateQueryError`
  （非法值的**同一个判定**，两个消费者各给各的人话）/ `CANDIDATE_SORT_KEYS`
  （排序值域真源，工具描述直接由它生成，防两处口径漂移）；
  `REVIEW_STATUSES` 顺带上移为出口（工具描述同理）。
  ★ 同轮**删掉** `candidate_exists` —— 判重已收口进 `create_candidate`
    （`on_duplicate="skip"`），它作为独立出口已无消费者。
    留着一个「没人用的判重出口」会让人以为判重还在外面做。
"""
from modules.candidates.service import (
    CANDIDATE_SORT_FIELDS,
    CANDIDATE_SORT_KEYS,
    REVIEW_STATUSES,
    CandidateQueryError,
    approve_candidate,
    count_candidates,
    create_candidate,
    describe_missing_fields,
    get_candidate,
    list_candidates,
    missing_required_fields,
    review_candidate,
)

__all__ = [
    "CANDIDATE_SORT_FIELDS",
    "CANDIDATE_SORT_KEYS",
    "REVIEW_STATUSES",
    "CandidateQueryError",
    "approve_candidate",
    "count_candidates",
    "create_candidate",
    "describe_missing_fields",
    "get_candidate",
    "list_candidates",
    "missing_required_fields",
    "review_candidate",
]
