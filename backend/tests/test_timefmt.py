"""`core/timefmt.py::utc_iso` —— 「时间进 JSON 必须带时区偏移」的**纯函数**判据。

================================================================================
★ 为什么这条口径值得单独一个文件
================================================================================
它错的时候**不会报任何错**。

仓库里的时间列是 naive-UTC；`dt.isoformat()` 对 naive 值输出
`"2026-09-25T12:00:00"`（无偏移）。前端 `new Date(...)` 对**无偏移**的
date-time 形式按**本地时区**解析（ECMA-262）⇒ UTC+8 的浏览器把这一刻读早 8 小时。

8 小时这个量级很"巧"：
  · 金额、状态、账单号、套餐名 **全部正确** ⇒ 粗看接口没毛病；
  · 只有**倒计时**（`expires_at`，TTL 30 分钟）和**日期边界**（周期起止）
    会露馅 —— 前者一打开就显示"已过期"，后者只在午夜附近差一天。
⇒ 没有任何"业务断言"会顺带把它测出来，必须专门钉住。

★ 分工（两半缺一不可）
  · 本文件：纯函数的行为（无需数据库，毫秒级）；
  · 「接口真的用上它了吗」→ `tests/test_billing_alipay_webhook.py` 的
    「9. 时间口径」一节 + `tests/test_billing_payment.py` 的同名用例
    （需要真库夹具，守的是**响应体**）。

★ 反向注入清单（每条都必须让本文件至少一条转红）
  1. `utc_iso` 里去掉 `value.replace(tzinfo=timezone.utc)`
     ⇒ `test_naive_is_interpreted_as_utc_and_marked` 转红（又回到无偏移）。
  2. 去掉 `value.astimezone(timezone.utc)` 分支
     ⇒ `test_aware_input_is_normalized_to_utc` 转红（`+08:00` 直接漏出去）。
  3. 去掉 `if value is None: return None`
     ⇒ `test_none_passes_through` 转红（`AttributeError` ⇒ 500）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.timefmt import utc_iso


# ============================================================================
# 1. 正向：naive 值 → 带偏移的字符串
# ============================================================================

def test_naive_is_interpreted_as_utc_and_marked():
    """naive 值按 UTC 解释，且输出**必须带偏移**。

    ★ 断言写的是**完整字符串**而不是 `endswith("+00:00")`：
      后者对 `"2026-09-25T12:00:00.000000+00:00"`（多出微秒）也成立，
      而微秒会让"同一时刻两种写法"从后门回来。
    """
    s = utc_iso(datetime(2026, 9, 25, 12, 0))
    assert s == "2026-09-25T12:00:00+00:00"
    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None, "★ 解析回来必须是 aware 的（前端才能无歧义读取）"
    assert dt.utcoffset() == timedelta(0)
    assert dt.replace(tzinfo=None) == datetime(2026, 9, 25, 12, 0), (
        "★ 墙上时间被改动了 —— naive 值本来就存的是 UTC，只该补偏移、不该换算"
    )


def test_aware_input_is_normalized_to_utc():
    """带偏移的输入归一化到 UTC：同一时刻在接口里只有**一种**字符串形态。

    ★ 为什么必须归一化而不是"原样透传"：
      原样透传会让 `+08:00` 与 `+00:00` 两种写法同时出现在接口里，
      于是"按字符串比对时间"的缓存键、测试断言、日志去重全部静默失效
      —— 它们看不出 `20:00+08:00` 与 `12:00+00:00` 是同一刻。
    """
    beijing = datetime(2026, 9, 25, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    assert utc_iso(beijing) == "2026-09-25T12:00:00+00:00"


def test_none_passes_through():
    """`None` 原样透传 —— 前端要能吃到一个明确的 `null`（而不是空串）。

    ★ 反向注入 3 说明：去掉 `None` 分支会 `AttributeError` ⇒ 端点 500。
      而 `paid_at` 在**未支付**的账单上必然是 `None`（那正是支付进行中的常态）
      ⇒ 这个分支不是防御性代码，是主路径。
    """
    assert utc_iso(None) is None


def test_round_trip_preserves_the_instant():
    """「序列化 → 解析」必须还原同一个时刻 —— 这是整条口径的**目的**。"""
    src = datetime(2026, 9, 25, 12, 0)
    back = datetime.fromisoformat(utc_iso(src))
    assert back == src.replace(tzinfo=timezone.utc)
    assert back.utcoffset() == timedelta(0)


# ============================================================================
# 2. 因果证据：证明「不带偏移」确实会让浏览器偏 8 小时
# ============================================================================

def test_missing_offset_would_be_misread_as_local_time():
    """**反向对照**：不带偏移的字符串，浏览器确实会读早 8 小时。

    ★ 这条不是在测 `utc_iso`，而是给上面那组判据提供**因果证据**。
      没有它，未来的读者（或我自己）会以为"加不加偏移无非是个风格问题"，
      于是很自然地把 `.isoformat()` 写回去 —— 而这正是不变量的死法。
    """

    def how_a_browser_reads(s: str, browser_offset_hours: int) -> datetime:
        """复刻 `new Date(s)` 的两条分支。

        · 字符串**无偏移** ⇒ ECMA-262 规定按**本地时区**解析 ← 缺陷就在这条；
        · 字符串**带偏移** ⇒ 时刻已由字符串唯一确定，与本地时区无关 ← utc_iso 的产物。
        """
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone(timedelta(hours=browser_offset_hours)))
        return dt

    naive = datetime(2026, 9, 25, 12, 0).isoformat()
    assert "+" not in naive and not naive.endswith("Z"), (
        f"裸 isoformat() 的输出意外带上了偏移：{naive!r} —— 本用例的前提不成立，"
        f"请核对 Python 行为后再改这条判据（否则它变成恒真的空跑）"
    )

    truth = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    seen = how_a_browser_reads(naive, browser_offset_hours=8)  # 中国用户的浏览器
    assert seen - truth == timedelta(hours=-8), (
        f"预期的 8 小时偏差没出现（实得 {seen - truth}）—— 前提变了，判据需重写"
    )

    # 而走 utc_iso 之后，**同一个浏览器**读出来就是真值（偏差归零）
    fixed = utc_iso(datetime(2026, 9, 25, 12, 0))
    assert how_a_browser_reads(fixed, browser_offset_hours=8) - truth == timedelta(0), (
        f"★ utc_iso 的产物在 UTC+8 的浏览器里仍被读错：{fixed!r}"
    )


# ============================================================================
# 3. 交付形态：模块必须**零业务依赖**（否则 core 分层门禁会红）
# ============================================================================

def test_module_is_importable_without_business_code():
    """`core/timefmt.py` 只能依赖标准库。

    ★ 这是 `tests/test_core_layering.py` 的同一条不变量在**这一处**的前置哨兵：
      timefmt 被 `modules/billing/*` 在最内层调用，一旦它反向 import 业务模块，
      就会形成 import 期的 core → modules 耦合（该门禁会红）。
      这里就地钉住，报错信息比那边更贴近改动人。
    """
    import ast
    from pathlib import Path

    src_path = Path(__file__).resolve().parents[1] / "core" / "timefmt.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert imported, "没解析出任何 import —— 扫描器失效了（判据会恒绿）"
    offenders = [m for m in imported if m.split(".")[0] in {"modules", "platforms", "ai_infra"}]
    assert not offenders, (
        f"★ core/timefmt.py 反向依赖了业务包：{offenders} —— "
        f"core 层不得在 import 期耦合 modules/platforms/ai_infra"
    )
