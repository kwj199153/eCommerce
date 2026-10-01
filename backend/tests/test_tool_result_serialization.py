# -*- coding: utf-8 -*-
"""工具出参序列化 —— `_dump` 收口的**唯一可观测判据**（第 356 轮）。

━━━ 为什么需要 ━━━
改前 8 个 `*/tools.py` 各抄一份 `_dump(resp)`，其中 **5 份逐字相同**。
本仓铁律「同一判定禁两份实现」在**方法论文档层面**早就写着，但连续四轮复审
（r335 / r350 / r353 / r354）都只**数了份数**（×8）、**没读 docstring 对没对
实现** —— 于是 `aigc_media` 那份的假承诺（「优先 data，其次 message/error」，
实现里根本没有这个逻辑）活过了四轮。⇒ 收口，并把「收口」变成可观测判据。

━━━ 判据（五条，每条都能回答「哪一处改动能把它打红」）━━━
  T1 **dict 通道全体一致**：8 个 `_dump` 对 JSON-safe `dict` 必须给出**同一字符串**。
     打红它：任一处漏掉 `ensure_ascii=False`（或改回 `json.dumps` 默认）。
  T2 **5 个三态消费方共享同一实现**：`_dump` 必须是**同一个函数对象**、且来自
     `ai_infra/tools/serialization.py`。打红它：任一消费方退回本地定义。
  T3 **扫描面自证（分母现算）**：从磁盘 AST 扫出「调用了 `_dump(`」的
     `modules/*/tools.py`，集合必须与本文文件的登记表一致（防「新增注册表忘了
     登记」）；且每份都真的**有调用点**（防「import 了但没人用」）。
  T4 **三态语义**：`model_dump()` 通道 / `str()` 兜底 / `default=str` 容
     `date`·`Decimal`。打红它：删任一分支。
  T5 **`aigc_media` 的文档与行为一致**：它是**有意**保留的两态版（无
     `default=str`、不走 `model_dump()`）—— 把它的**实测行为**与**摘要行**一起
     钉住，于是「docstring 说什么」与「代码做什么」不可能再各说各话。
     ★ 这条正是那道假承诺的**对症判据**：改文档不改行为 ⇒ 行为判据红；
       改行为不改文档（或摘要行又写回一个不存在的承诺）⇒ 摘要行判据红。

★ 反向注入见 `.workbuddy/probes/r356/inject_dump_consolidation.py`（四组 + 反例）。
★ 为什么 `listing_generator` **不在**这 8 个里：它走 `resp.model_dump_json()`
  （Pydantic 自带的 JSON 序列化），是**另一种**出参范式、根本没有 `_dump`。
  T3 的分母由磁盘现算，所以「漏登记」与「多登记」都会红。
"""

import ast
import inspect
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from modules.ad_analysis import tools as ad_tools
from modules.aigc_media import tools as aigc_tools
from modules.competitor_intel import tools as ci_tools
from modules.customer_service import tools as cs_tools
from modules.library import tools as lib_tools
from modules.product_research import tools as pr_tools
from modules.review_analyst import tools as ra_tools
from modules.trade import tools as trade_tools

BACKEND = Path(__file__).resolve().parents[1]

#: 8 个「定义或复用 `_dump`」的工具注册表。
#: ★ 键 = 模块短名（= 目录名），值 = 模块对象。
ALL_TOOLS = {
    "ad_analysis": ad_tools,
    "aigc_media": aigc_tools,
    "competitor_intel": ci_tools,
    "customer_service": cs_tools,
    "library": lib_tools,
    "product_research": pr_tools,
    "review_analyst": ra_tools,
    "trade": trade_tools,
}

#: 复用**共享真源**的 5 个（改前是逐字相同的三态版）。
SHARED = (
    "ad_analysis", "competitor_intel", "customer_service",
    "product_research", "review_analyst",
)

#: 唯一真源所在模块（import 目标）。
SERIALIZATION_MODULE = "ai_infra.tools.serialization"
SERIALIZATION_FILE = "ai_infra/tools/serialization.py"

#: 收口后**有意保留**的各版本；改 C 档（统一它们）时同步这里。
EXPECTED_DISTINCT_IMPLS = 4


class _HasModelDump:
    """既不是 `dict`、`str()` 也没被覆盖 ⇒ 只有 `model_dump()` 分支能认它。"""

    def model_dump(self):
        return {"kind": "pydanticish", "n": 1}

    def __str__(self):
        return "STR-OF-MODEL"


class _NoModelDump:
    def __str__(self):
        return "weird-obj"


def _rel(module) -> str:
    """模块对应的仓库内相对路径（posix 风格）。"""
    return Path(inspect.getsourcefile(module)).relative_to(BACKEND).as_posix()


def _disk_callers() -> dict:
    """**现算**分母：磁盘上「调用了 `_dump(`」的 `modules/*/tools.py`。

    ★ 为什么用 AST 而不是 `grep`：本仓铁律「判据禁源码字符串包含」——
      docstring / 注释里提到 `_dump` 会骗过字符串判据。这里只认 `ast.Call`。
    """
    out = {}
    for p in sorted((BACKEND / "modules").glob("*/tools.py")):
        tree = ast.parse(p.read_bytes().decode("utf-8", "replace"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_dump"]
        if calls:
            out[p.parent.name] = (p.relative_to(BACKEND).as_posix(), len(calls))
    return out


# ============================================================
# T3 扫描面自证（分母现算）
# ============================================================

def test_disk_scan_face_matches_the_registry():
    """分母必须与磁盘一致：漏登记 / 多登记 / 登记了但没人调用 ⇒ 红。"""
    disk = _disk_callers()
    assert disk, "磁盘上一个调用 `_dump(` 的 tools.py 都扫不到 —— AST 判据可能失效"
    assert set(disk) == set(ALL_TOOLS), (
        "分子（本文件登记）与分母（磁盘现算）不一致：\n"
        f"  只在磁盘上（新增注册表忘了登记）：{sorted(set(disk) - set(ALL_TOOLS))}\n"
        f"  只在本文件（登记了磁盘上不存在的）：{sorted(set(ALL_TOOLS) - set(disk))}"
    )
    for short, (rel, n) in disk.items():
        assert n >= 1, f"{short} 的 `_dump` 调用点数为 {n}"


def test_every_registry_exposes_a_callable_dump():
    """8 份都必须取到**可调用**的 `_dump`（防空转：取不到就没得比）。"""
    missing = [s for s, m in ALL_TOOLS.items()
               if not callable(getattr(m, "_dump", None))]
    assert not missing, f"这些注册表没有可调用的 `_dump`：{missing}"


# ============================================================
# T1 dict 通道全体一致
# ============================================================

def test_all_dump_agree_on_json_safe_dicts():
    """★ `dict` 是工具出参最常见的形态 ⇒ 8 份必须给出**同一字符串**。

    ★ 载荷刻意含**中文键与中文值**：这样一条判据同时覆盖 `ensure_ascii=False`。
    """
    payload = {"中文": 1, "n": 2, "nested": {"k": "值"}}
    outs = {short: m._dump(dict(payload)) for short, m in ALL_TOOLS.items()}
    uniq = sorted(set(outs.values()))
    assert len(uniq) == 1, (
        "dict 通道出现 %d 种出参（应 1 种）：\n  %s"
        % (len(uniq), "\n  ".join(f"{k}: {v!r}" for k, v in outs.items()))
    )
    assert json.loads(uniq[0]) == payload, "出参不是载荷的 JSON 表示"
    assert "中文" in uniq[0], f"中文被转义成 \\uXXXX ⇒ ensure_ascii 不是 False：{uniq[0]!r}"


# ============================================================
# T2 5 个消费方共享同一实现（收口的唯一可观测判据）
# ============================================================

def test_five_three_state_consumers_share_one_implementation():
    """★ 这是「收口」本身的可观测形态：**同一个函数对象**，不是「长得一样」。"""
    impls = {short: ALL_TOOLS[short]._dump for short in SHARED}
    ids = {}
    for short, fn in impls.items():
        ids.setdefault(id(fn), []).append(short)
    assert len(ids) == 1, (
        "5 个消费方的 `_dump` 不是同一个对象（收口被打破）："
        + "；".join(f"实现{i}={v}" for i, v in enumerate(ids.values(), 1))
    )
    fn = next(iter(impls.values()))
    assert fn.__module__ == SERIALIZATION_MODULE, (
        f"共享实现来自 {fn.__module__}，期望 {SERIALIZATION_MODULE}"
    )
    assert fn.__name__ == "dump_result", f"共享实现名叫 {fn.__name__}，期望 dump_result"
    files = {Path(inspect.getsourcefile(fn)).relative_to(BACKEND).as_posix()}
    assert files == {SERIALIZATION_FILE}, f"共享实现住在 {files}，期望 {SERIALIZATION_FILE}"


def test_shared_source_is_one_function_object_not_a_redefinition():
    """反向自证：共享实现**不能**是「每个模块里又写了一份同名函数」。

    ★ 少了这条，`id()` 判据仍可能被「同一份代码被 exec 两次」之类的形态蒙过；
      这里同时钉住「只有一个模块定义了 `dump_result`」。
    """
    defined = []
    for p in sorted((BACKEND / "ai_infra").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_bytes().decode("utf-8", "replace"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "dump_result":
                defined.append(p.relative_to(BACKEND).as_posix())
    assert defined == [SERIALIZATION_FILE], (
        f"`dump_result` 的定义点应**唯一**，实测 {defined}"
    )


# ============================================================
# T4 三态语义
# ============================================================

@pytest.mark.parametrize("short", SHARED)
def test_three_state_semantics_per_consumer(short):
    """三态各自可达：`dict` / `model_dump()` / `str()` 兜底（**不抛**）。"""
    fn = ALL_TOOLS[short]._dump
    assert json.loads(fn({"a": 1})) == {"a": 1}
    obj = _HasModelDump()
    assert json.loads(fn(obj)) == {"kind": "pydanticish", "n": 1}, (
        f"{short}: 有 `model_dump()` 的对象没有走 `model_dump()` 通道"
    )
    assert fn(_NoModelDump()) == "weird-obj", (
        f"{short}: `str()` 兜底分支失效（应退化成字符串而不是抛/编码）"
    )


@pytest.mark.parametrize("short", SHARED)
def test_default_str_tolerates_non_json_types(short):
    """`default=str` 兜底：`dict` 里混进 `date` / `Decimal` 不得抛 `TypeError`。

    ★ 这不是吹毛求疵：`json.dumps` 遇到不可序列化对象会抛，整个工具调用崩掉
      ⇒ 模型收到「工具报错」而不是业务结果，失败还会被归因到数据源。
    """
    fn = ALL_TOOLS[short]._dump
    out = fn({"d": date(2026, 10, 2), "p": Decimal("1.50")})
    data = json.loads(out)
    assert data["d"] == "2026-10-02", f"{short}: date 未被 default=str 兜住：{out!r}"
    assert data["p"] == "1.50", f"{short}: Decimal 未被 default=str 兜住：{out!r}"


def test_shared_impl_is_directly_callable():
    """真源本身可用（防止判据只测到「模块属性」而真源是坏的）。"""
    fn = ad_tools._dump
    assert fn({"a": 1}) == '{"a": 1}'
    assert fn(_NoModelDump()) == "weird-obj", "`str()` 兜底分支失效"


# ============================================================
# T5 `aigc_media`：文档与行为一致（那道假承诺的对症判据）
# ============================================================

def test_aigc_media_dump_behaviour_matches_its_docstring():
    """★ `aigc_media` 的 `_dump` 是**有意保留**的两态版：行为 + 摘要行一起钉住。

    改前它的 docstring 写「统一序列化：优先 data，其次 message/error」，
    而实现只有「`dict` → dump / 其余 `str()`」——**声明承诺与实现不符**，
    且连续四轮复审都没发现。这条判据让两者不可能再分家：

    · ① 有 `model_dump()` 的对象**不走** `model_dump()`（⇒ 只有两态）；
    · ② `dict` 里混进 `date` 抛 `TypeError`（⇒ 没有 `default=str`）；
    · ③ **摘要行**不得再出现「优先 data」这种实现里没有的承诺。

    ★ 若哪天做 C 档（把它统一到共享真源）：本用例会红 —— 那时请**同时**
      更新 `ai_infra/tools/serialization.py` 的对照表、
      `tests/test_source_size_ratchet.py` 的登记段、以及本用例
      （`EXPECTED_DISTINCT_IMPLS` 也要改成 3）。
    """
    # ① 两态：不走 model_dump 通道
    obj = _HasModelDump()
    assert aigc_tools._dump(obj) == str(obj), (
        "`aigc_media._dump` 对 `model_dump()` 对象应直接 `str()`；"
        "若它开始走 `model_dump()`，说明已变成三态 ⇒ 文档与本判据都要改"
    )
    # ② 无 default=str：不可序列化类型**确实**抛（这是当前的真实行为）
    with pytest.raises(TypeError):
        aigc_tools._dump({"d": date(2026, 10, 2)})
    # ③ 摘要行不得写回一个实现里不存在的承诺
    doc = (aigc_tools._dump.__doc__ or "").strip()
    assert doc, "`aigc_media._dump` 没有 docstring"
    first = doc.splitlines()[0]
    assert "优先 data" not in first and "message/error" not in first, (
        f"`aigc_media._dump` 的摘要行又写回了一个实现里不存在的承诺：{first!r}\n"
        "（该函数只做「dict → json.dumps / 其余 str()」两态）"
    )
    # 顺带：dict 通道仍与全体一致（它本就该一致）
    assert aigc_tools._dump({"中文": 1}) == '{"中文": 1}'


def test_remaining_implementations_are_accounted_for():
    """收口后**仍有 4 份**实现 —— 登记在案，改动这份清单就要来改本判据。

    ★ 为什么这条值得存在：`_dump` 的产物是**工具直接回给 LLM 的字符串**，
      「统一语义」= 改变模型读到的内容。所以剩下的 3 份不是漏收，是**有意**。
    """
    ids = {id(m._dump) for m in ALL_TOOLS.values()}
    assert len(ids) == EXPECTED_DISTINCT_IMPLS, (
        f"不同实现份数实测 {len(ids)}，登记值是 {EXPECTED_DISTINCT_IMPLS}。\n"
        "  变少了 ⇒ 有人又收口了一份，请同步本文件与那份模块的 docstring；\n"
        "  变多了 ⇒ 有人又抄了一份 `_dump`（正是本判据要拦的）。"
    )
