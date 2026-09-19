"""长期记忆的**机制层**（第 149 轮 C2-1）。

分工（与本项目既有两处完全同构）：

    ai_infra/session_state.py       ↔  modules/conversation/state_store.py
    ai_infra/plan.py                ↔  modules/secretary
    **ai_infra/memory/**            ↔  modules/memory/

左边是**机制**：纯函数、零 IO、零 DB、零网络，可以在没有数据库、
没有 API key 的机器上被完整测试。
右边是**接线**：建表 / HTTP 端点 / Celery 定时任务。

★★ 为什么必须切这一刀
---------------------
长期记忆的核心逻辑（归一化、去重、配额、上限、markdown 读写）一旦和
"落库 + 端点"写在同一个文件里，测试它就必须先起 PostgreSQL、先建表、
先造用户 —— 于是实际结果是**没人写它的门禁**，
而它偏偏是最容易出错的部分（边界、幂等、顺序稳定性）。

裁成两半之后，`tests/test_agent_memory.py` 可以直接断言：
"同一个输入跑两次结果逐字段相同"、"60 条上限恰好把第 61 条挤掉"、
"注入块在 2000 字处按整行截断" —— 全部零基础设施。

本包对外只暴露两件东西的入口：`limits`（口径）与 `distill`（规则）。
`entry` 是数据形态，一般不必直接 import。
"""

from __future__ import annotations

from .entry import (
    PROMPT_HEADER,
    MemoryEntry,
    dedup_key,
    group_by_section,
    match_section,
    normalize_text,
    parse_markdown,
    render_markdown,
    render_prompt_block,
    truncate_text,
)
from .limits import (
    ALL_SECTIONS,
    DEFAULT_SECTION_QUOTA,
    DEFAULT_SOURCE_WEIGHT,
    DISTILL_BATCH_LIMIT,
    DISTILL_COOLDOWN_HOURS,
    DISTILL_HOUR,
    DISTILL_LOOKBACK_HOURS,
    DISTILL_MANUAL_GAP_SECONDS,
    DISTILL_MINUTE,
    DISTILL_PERIOD_HOURS,
    FAILURE_LOG_KINDS,
    KIND_DISTILL,
    KIND_DISTILL_FAILED,
    KIND_IMPORT,
    KIND_MANUAL,
    KIND_RESET,
    LOG_KINDS,
    MAX_CANDIDATES_PER_RUN,
    MAX_DISTILL_MESSAGES,
    MAX_DISTILL_TRANSCRIPT_CHARS,
    MAX_ENTRIES,
    MAX_ENTRY_CHARS,
    MAX_LOGS,
    MAX_LOG_CHARS,
    MAX_LOG_SAMPLE_CHARS,
    MAX_LOG_SAMPLE_ITEMS,
    MAX_PROMPT_CHARS,
    MIN_DISTILL_LINE_CHARS,
    MEMORY_SOURCES,
    SECTION_ALIASES,
    SECTION_COMMS,
    SECTION_FOCUS,
    SECTION_OPS,
    SECTION_OTHER,
    SECTION_PERSONAL,
    SECTION_QUOTA,
    SECTION_WORK,
    SOURCE_DISTILL,
    SOURCE_IMPORT,
    SOURCE_MANUAL,
    SOURCE_WEIGHTS,
    TRUNCATION_MARK,
    is_known_log_kind,
    ordered_sections,
    section_quota,
    source_weight,
)
from .distill import (
    DistillError,
    build_extract_prompt,
    converge,
    diff_summary,
    extract_candidates,
    format_log_content,
    parse_candidates,
    validate_entries,
)

__all__ = [
    "ALL_SECTIONS",
    "DEFAULT_SECTION_QUOTA",
    "DEFAULT_SOURCE_WEIGHT",
    "DISTILL_BATCH_LIMIT",
    "DISTILL_COOLDOWN_HOURS",
    "DISTILL_HOUR",
    "DISTILL_LOOKBACK_HOURS",
    "DISTILL_MANUAL_GAP_SECONDS",
    "DISTILL_MINUTE",
    "DISTILL_PERIOD_HOURS",
    "DistillError",
    "FAILURE_LOG_KINDS",
    "KIND_DISTILL",
    "KIND_DISTILL_FAILED",
    "KIND_IMPORT",
    "KIND_MANUAL",
    "KIND_RESET",
    "LOG_KINDS",
    "MAX_CANDIDATES_PER_RUN",
    "MAX_DISTILL_MESSAGES",
    "MAX_DISTILL_TRANSCRIPT_CHARS",
    "MAX_ENTRIES",
    "MAX_ENTRY_CHARS",
    "MAX_LOGS",
    "MAX_LOG_CHARS",
    "MAX_LOG_SAMPLE_CHARS",
    "MAX_LOG_SAMPLE_ITEMS",
    "MAX_PROMPT_CHARS",
    "MEMORY_SOURCES",
    "MIN_DISTILL_LINE_CHARS",
    "MemoryEntry",
    "PROMPT_HEADER",
    "SECTION_ALIASES",
    "SECTION_COMMS",
    "SECTION_FOCUS",
    "SECTION_OPS",
    "SECTION_OTHER",
    "SECTION_PERSONAL",
    "SECTION_QUOTA",
    "SECTION_WORK",
    "SOURCE_DISTILL",
    "SOURCE_IMPORT",
    "SOURCE_MANUAL",
    "SOURCE_WEIGHTS",
    "TRUNCATION_MARK",
    "build_extract_prompt",
    "converge",
    "dedup_key",
    "diff_summary",
    "extract_candidates",
    "format_log_content",
    "group_by_section",
    "is_known_log_kind",
    "match_section",
    "normalize_text",
    "ordered_sections",
    "parse_candidates",
    "parse_markdown",
    "render_markdown",
    "render_prompt_block",
    "section_quota",
    "source_weight",
    "truncate_text",
    "validate_entries",
]
