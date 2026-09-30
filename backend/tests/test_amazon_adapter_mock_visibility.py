"""
旧 mock 适配器的「静默假数据 → 有声假数据」门禁（第 164 轮 #729 建立）。

背景
----
`platforms/amazon/client.py` 是 Phase 2 遗留的**旧 mock 世界**，由
`get_platform_adapter("amazon")` 提供给 `product_research` / `listing_generator`。
两个世界对「我在给假数据」这件事的态度完全不同：

| 世界 | 工厂 | 真源分支 | 生产用户 | 告警 |
|---|---|---|---|---|
| 新 | `get_data_source()` | 有 | ad_analysis / competitor_intel / review_analyst | ✅ `logger.warning` |
| 旧 | `get_platform_adapter()` | **无**，无条件假 | product_research / listing_generator | ❌ **无** ← 本轮修 |

用户看到的是「蓝海机会」四个字，不是「演示数据」。
**静默的假数据比报错的假数据危害大一个量级。**

本文件钉住的六件事
------------------
1. 未匹配关键词**必产 ≥1 条 WARNING**（这是最危险的一条：搜索量/竞争度/趋势
   都是 `random.*` 现编的，同一个词每次结果不同）。
2. 编造点**不能漏**、真实算法**不能误标** —— 用的是「集合法」而不是「逐条 assert」：
   告警的方法集合必须**恰好等于**编造方法集合（多一个 = 误标，少一个 = 漏埋）。
3. 真实算法 `calculate_fees` **不得**打 MOCK 告警（否则告警本身失去信息量）。
4. `get_bsr_rank` 死代码从**契约 + 4 个平台客户端**一起删干净。
5. `AmazonAdapter` 仍可实例化 —— 这是「抽象方法不能只删一个覆写」的正面判据
   （只删 Amazon 的覆写 ⇒ `TypeError: Can't instantiate abstract class`，
   整套选品链路直接崩）。
6. 类里每新增一个公开方法，都必须被显式归类（编造 / 真实），否则本门禁变红。
"""

import ast
import inspect
import logging
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CLIENT = BACKEND / "platforms" / "amazon" / "client.py"
BASE = BACKEND / "platforms" / "base.py"

LOGGER_NAME = "platforms.amazon.client"

#: 编造数据的出口 —— 每一次调用都必须留下 WARNING
MOCK_METHODS = {
    "search_products",
    "match_products",
    "get_product_detail",
    "get_keyword_data",
    "get_reviews",
    "analyze_competitors",
}

#: 真实算法 —— 不得打 MOCK 告警（打错了 = 告警失去信息量，等于没告警）
REAL_METHODS = {"calculate_fees"}

#: 非数据出口的公开成员，显式排除
NON_DATA_MEMBERS = {"platform_type", "MOCK_LATENCY_SCALE"}

MOCK_ASIN = "B0CGLKP2R1"


def _adapter():
    from platforms import get_platform_adapter

    return get_platform_adapter("amazon")


def _warn_records(caplog):
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno >= logging.WARNING]


def _messages(caplog):
    return [r.getMessage() for r in _warn_records(caplog)]


# ============================================================
# 1 / 2. 告警覆盖：集合法，双向都管
# ============================================================

async def _exercise_all(adapter) -> set[str]:
    """调一遍所有数据出口（含 `get_mock_products` 这个模块级出口）。

    ★ 必须返回「实际调用过的方法名集合」，并在断言前核对它**恰好等于**
      `MOCK_METHODS | REAL_METHODS`。
      为什么：本文件里有一条**否定式**判据「真实算法不得被告警」——
      如果夹具漏调了 `calculate_fees`，那条断言就**恒真**（没调用自然没告警），
      反向注入「把 calculate_fees 误标为 MOCK」也不会变红（实测踩到，INJ2 空跑）。
      **否定式断言必须同时证明「被否定的对象确实被碰过」。**
    """
    from platforms.amazon.client import get_mock_products

    invoked: set[str] = set()

    get_mock_products("electronics")
    invoked.add("get_mock_products")

    await adapter.search_products("coffee grinder")
    invoked.add("search_products")

    await adapter.match_products("coffee grinder")
    invoked.add("match_products")

    await adapter.get_product_detail(MOCK_ASIN)
    invoked.add("get_product_detail")

    await adapter.get_keyword_data("a-keyword-not-in-the-mock-table-xyz")
    invoked.add("get_keyword_data")

    await adapter.get_reviews(MOCK_ASIN)
    invoked.add("get_reviews")

    await adapter.analyze_competitors([MOCK_ASIN])
    invoked.add("analyze_competitors")

    adapter.calculate_fees(29.99, category="Home & Kitchen", weight_lbs=1.0)
    invoked.add("calculate_fees")

    return invoked


async def test_every_mock_method_warns_and_the_real_one_does_not(caplog):
    """告警集合必须**恰好**等于编造方法集合。

    ★ 为什么用集合而不是逐条 assert：逐条 assert 只能证明「我想到的都告警了」，
      证明不了「没漏」。集合法同时管两头 —— 少一个 = 漏埋（假数据又静默了），
      多一个 = 误标（把真的说成假的 ⇔ 告警不再可信）。
    """
    adapter = _adapter()
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        invoked = await _exercise_all(adapter)

    # 先证明夹具真的碰过每一个出口 —— 否则下面的「未告警」断言恒真（假绿）
    assert invoked == MOCK_METHODS | REAL_METHODS | {"get_mock_products"}, (
        f"夹具漏调了方法，否定式断言会恒真：漏={sorted(MOCK_METHODS | REAL_METHODS | {'get_mock_products'} - invoked)}"
    )

    msgs = _messages(caplog)
    warned = {m.split(" ")[0].split(".")[-1] for m in msgs if "MOCK 编造数据" in m}
    warned.discard("get_mock_products")  # 模块级出口，单独判

    assert warned == MOCK_METHODS, (
        f"告警的方法集合与编造方法集合不一致："
        f"漏埋={sorted(MOCK_METHODS - warned)}，误标={sorted(warned - MOCK_METHODS)}"
    )
    for real in REAL_METHODS:
        assert real not in warned, f"{real} 是真实算法，不该被打上 MOCK 告警"

    # 模块级出口也必须喊
    assert any("get_mock_products" in m and "MOCK 编造数据" in m for m in msgs), (
        "get_mock_products 是旧世界真正的数据出口，必须告警"
    )


def test_public_members_are_all_classified():
    """新增公开方法必须显式归类，否则本门禁变红。

    ★ 这条是「防遗漏」的元判据：没有它，以后加一个 `get_bestsellers()` 悄悄编数据，
      上面那条集合法判据照样是绿的（集合是「已分类的子集」在比对）。
    """
    from platforms.amazon.client import AmazonAdapter

    public = {n for n in vars(AmazonAdapter) if not n.startswith("_")}
    expected = MOCK_METHODS | REAL_METHODS | NON_DATA_MEMBERS
    assert public == expected, (
        f"AmazonAdapter 的公开成员与「真假分类表」不一致："
        f"未归类={sorted(public - expected)}，表里有但类里没了={sorted(expected - public)}"
    )


# ============================================================
# 1. 未匹配关键词：最危险的那条
# ============================================================

async def test_unmatched_keyword_warns_that_values_are_randomly_invented(caplog):
    """未命中模拟词库 ⇒ 搜索量/竞争度/趋势全是 `random.*` 现编 ⇒ 必须告警。"""
    adapter = _adapter()
    kw = "definitely-not-in-the-mock-keyword-table-xyz"

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        await adapter.get_keyword_data(kw)

    msgs = _messages(caplog)
    assert msgs, "未匹配关键词没有产生任何 WARNING"
    hit = [m for m in msgs if kw in m]
    assert hit, f"告警里没有带上关键词，线上无法定位：{msgs}"
    assert "unmatched" in hit[0], "未匹配分支应带 unmatched 标记，与「命中词库」区分开"


async def test_matched_keyword_still_warns_but_says_why_differently(caplog):
    """命中模拟词库仍然是编造（只是不必现编），两条分支的「原因」必须能区分。"""
    from platforms.amazon.client import MOCK_KEYWORDS

    keyword = next(iter(MOCK_KEYWORDS))
    adapter = _adapter()
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        await adapter.get_keyword_data(keyword)

    msgs = [m for m in _messages(caplog) if keyword in m]
    assert msgs, "命中词库时也必须告警（读的是内存假表，不是真实关键词数据）"
    assert "unmatched" not in msgs[0], "命中分支不该带 unmatched 标记"


# ============================================================
# 4 / 5. 死代码删除 + 抽象方法陷阱
# ============================================================

def _methods_of(path: Path, cls_name: str | None = None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    if cls_name is None:
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(n.name)
    else:
        for c in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name):
            for m in c.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(m.name)
    return names


def test_get_bsr_rank_is_gone_from_everywhere():
    """死代码删干净：契约 + 4 个平台客户端都不得再有这个方法。

    ★ 为什么必须一起删：它是 `platforms/base.py` 里的 **`@abstractmethod`**。
      只删 `AmazonAdapter` 的覆写 ⇒ `AmazonAdapter` 无法实例化
      （`TypeError: Can't instantiate abstract class`）⇒ 整套选品链路直接崩。
      「删死代码前先看它是不是契约的一部分」。
    """
    assert "get_bsr_rank" not in _methods_of(BASE), "base.py 的抽象声明没删掉"
    for rel in [
        "platforms/amazon/client.py",
        "platforms/shopee/client.py",
        "platforms/shopify/client.py",
        "platforms/tiktok/client.py",
    ]:
        p = BACKEND / rel
        assert "get_bsr_rank" not in p.read_text(encoding="utf-8"), f"{rel} 仍有残留"

    # 全仓不得有调用点（否则删的是活的）
    for f in BACKEND.rglob("*.py"):
        if {".venv", "venv", "site-packages"} & set(f.parts):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in ast.walk(tree):
            assert not (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get_bsr_rank"
            ), f"{f}:{n.lineno} 仍在调用已被删除的 get_bsr_rank"


def test_amazon_adapter_is_still_instantiable():
    """抽象方法只删一个覆写会让类无法实例化 —— 这条是那次陷阱的正面判据。"""
    from platforms.amazon.client import AmazonAdapter

    assert not inspect.isabstract(AmazonAdapter), "AmazonAdapter 变成了抽象类（漏删覆写？）"
    assert isinstance(_adapter(), AmazonAdapter)


# ============================================================
# 6. 形状门禁：不得用 loguru 的 logger（`%s` 会静默丢参数）
# ============================================================

def test_uses_stdlib_logging_not_loguru():
    """本模块必须用 stdlib `logging`。

    ★ 实测（第 164 轮）：`core.logger.get_logger()` 返回 **loguru**，按 `str.format`
      插值 —— 写 `logger.warning("a=%s", 1)` **不报错、参数被静默丢弃、日志原样打出 `a=%s`**。
      stdlib 走 `InterceptHandler` 会先 `record.getMessage()` 做 `%` 插值，`%s` 才对。
      同目录 `platforms/amazon/sp_api/*` 也全是 stdlib，保持一致。
    """
    tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
    assert "logging" in imported, "本模块应用 stdlib logging"
    assert "core.logger" not in imported, (
        "不要在这里用 loguru 的 get_logger —— 它的 `%s` 会静默丢参数"
    )
    src = CLIENT.read_text(encoding="utf-8")
    assert "logging.getLogger(__name__)" in src


@pytest.mark.parametrize("method", sorted(MOCK_METHODS))
def test_warning_message_points_at_the_real_data_source(method):
    """告警必须给出「去哪儿拿真数据」，否则它只是一句抱怨。"""
    src = CLIENT.read_text(encoding="utf-8")
    assert "modules.amazon_sp.get_data_source()" in src, "告警里缺少真实数据源指引"
