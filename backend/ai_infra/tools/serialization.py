"""
工具出参序列化 —— **唯一真源**（第 356 轮收口）。

━━━ 为什么需要 ━━━
改前 8 个 `*/tools.py` 各抄一份 `_dump(resp)`，其中 **5 份逐字相同**
（三态：`dict` → dump / 有 `model_dump()` 的对象 → dump 其 `model_dump()` /
其余 → `str()`）：

    ad_analysis/tools.py · competitor_intel/tools.py · customer_service/tools.py
    product_research/tools.py · review_analyst/tools.py

模板复制的代价**不是行数**，而是「**语义漂移且无声**」：`aigc_media/tools.py`
那份的 docstring 写着「统一序列化：优先 data，其次 message/error」，而实现里
**从来没有**这个逻辑（没有 `resp["data"]` 取值，也没有 `message` / `error`
分支）。★ 声明承诺与实现不符，且连续四轮复审（r335 / r350 / r353 / r354）
都没发现 —— 因为那四轮都只**数了份数**（×8）、没**读 docstring 对没对实现**。

━━━ 收口口径（有意选择，勿随手改）━━━
· 5 个消费方一律写
  `from ai_infra.tools.serialization import dump_result as _dump`
  —— **保留本地名 `_dump`**，理由是两条可观测的：
    ① `grep -rn "_dump("` 仍能一次数全 8 个 `tools.py`（本地 API 一致）；
    ② `tests/test_review_analyst_tool_paths.py` 的三条 `_dump` 分支用例不必改。
· 收口后**仍有 4 份实现**：本函数 + `aigc_media`（两态）+ `library` / `trade`
  （单行）。**这是有意的**，理由见下。

━━━ 为什么不把那 3 份一起收口 ━━━
`_dump` 的产物是**工具直接回给 LLM 的字符串** ⇒ 统一语义 = **改变模型读到的
内容**。三者行为实测各不相同（读数见 `probes/r356/out-dump-baseline.txt`）：

| 输入 | 本函数（三态） | `aigc_media` | `library` / `trade` |
|---|---|---|---|
| `{"d": date(2026, 10, 2)}` | `'{"d": "2026-10-02"}'` | **`TypeError`** | `'{"d": "2026-10-02"}'` |
| `model_dump()` 对象 | `'{"kind": "pydanticish"}'` | `'STR-OF-MODEL'` | `'"STR-OF-MODEL"'`（json 编码的字符串） |

且 `trade` 有**前端 parity 门禁 T6** 从 `_map_order_from_trade` 抽键
（`frontend/scripts/check-order-track-parity.cjs`）⇒ 改它会牵动跨语言契约。
故本轮**只收口逐字相同的 5 份**，其余如实登记、行为不动。

━━━ 反向注入 ━━━
见 `.workbuddy/probes/r356/inject_dump_consolidation.py`：四组（打公共函数的
`default=str` / `ensure_ascii` / `model_dump` 分支 / 扫描面）+ 一组反例。
"""
from __future__ import annotations

import json

__all__ = ["dump_result"]


def dump_result(resp) -> str:
    """把工具出参序列化成**给 LLM 直接读的**字符串。

    三态（顺序即优先级）：

      ① `dict`             → `json.dumps(..., ensure_ascii=False, default=str)`
      ② 有 `model_dump()`  → 同上，但先取 `model_dump()`
      ③ 其余               → `str(resp)`（**不抛**）

    ★ `ensure_ascii=False` 是刻意的：出参进的是**模型上下文**，中文被转义成
      `\\uXXXX` 既白烧 token 又降低可读性。第 355 轮已单配一条用例钉它
      （`test_review_analyst_tool_paths.py::test_dump_does_not_escape_chinese`）。
    ★ `default=str` 是**兜底而不是可选**：`dict` 里混进 `date` / `Decimal` /
      `Enum` 时 `json.dumps` 会抛 `TypeError`，整个工具调用崩掉 —— 模型收到
      「工具报错」而不是业务结果，且失败会被归因到「数据源坏了」。
    ★ 分支顺序不可交换：`str()` 兜底必须在最后，未知类型才退化成字符串而不是
      异常；`dict` 判定必须在 `model_dump` 之前（表达「字典优先原样 dump」的意图）。
    """
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)
