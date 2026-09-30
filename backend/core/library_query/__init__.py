"""资料库通用查询内核（第 218 轮）。

对外只有三样东西 —— 声明式元数据、查询、计数：

    from core.library_query import LibrarySpec, FilterSpec, LibraryQueryError
    from core.library_query import query_library, count_library, clamp_limit

各库在自己的包里声明 `LibrarySpec`（见 `modules/candidates/service.py` 的
`CANDIDATE_SPEC`），消费方（`modules/library/tools.py`）调 `query_library`。
"""

from core.library_query.executor import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
    count_library,
    query_library,
    resolve_filters,
    resolve_sort_clause,
)
from core.library_query.spec import FilterSpec, LibraryQueryError, LibrarySpec

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "FilterSpec",
    "LibraryQueryError",
    "LibrarySpec",
    "clamp_limit",
    "count_library",
    "query_library",
    "resolve_filters",
    "resolve_sort_clause",
]
