# -*- coding: utf-8 -*-
"""每日经营简报的**接线**门禁（第 371 轮）。

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
`monitors` 表从建表起就带着五个变化信号列，竞品监控看板也能画出来 ——
但用户**必须自己打开看板**才看得到。缺的不是计算，是**没有任何东西会
每天早上把它说给用户听**（第 371 轮之前，右上角铃铛的 `:count` 是硬编码 0）。

本文件守**七种互相独立**、且都不报错的失败模式：

  ① `core/redis.py::beat_schedule` 里的任务名写错
     ⇒ beat 照常投递、worker 照常运行，队列里多一条没人认识的消息。
       「没人消费」不是错误 ⇒ 表现是**什么都没发生**（简报表永远不长新行）。
  ② `autodiscover_tasks([...])` 漏了 `"modules.monitors"`
     ⇒ 装饰器从未被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 查不到，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同 ⇒ 必须是两条用例。
  ③ 任务体是空壳（调度接上了，但没真的去调生成核）
     ⇒ ① ② 全绿，任务每天"成功"一次，`daily_briefings` 永远不长新行。
  ④ 任务体吞掉异常（`except` 里 `return` 而不是 `raise`）
     ⇒ 「生成失败」与「今天真的没有变化」在结果里长得**一模一样**。
  ⑤ `/metrics` 上看不见这次执行（`except` 里没记指标就抛）
     ⇒ Celery 的 FAILURE 只活在 worker 日志里（结果 1 小时过期），
       没人能从长期指标上发现"简报已经两周没成功了"。
  ⑥ 用 `asyncio.run()` 而不是每线程常驻 loop
     ⇒ asyncpg 连接绑在创建它的 loop 上，**第一次成功、第二次必挂**，
       而单次验证会**全绿放行**（本仓记过多次的"假绿"形态）。
  ⑦ 「类型 ↔ 严重度 / 排序 / 标签」的键集合漂移
     ⇒ 某一类条目在摘要里排序错位、或新加了一类却忘了登记。
       症状只是"顺序看着不对"，**没有任何一处会报错**。

★ 反向注入清单见 `.workbuddy/probes/revinject-r371-briefing-gate.py`
  （每条判据都要能被真实源码改动打红）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: beat 调度表里的键（`core/redis.py::beat_schedule`）。
ENTRY_KEY = "monitors-daily-briefing"
REDIS = BACKEND / "core" / "redis.py"
TASKS = BACKEND / "modules" / "monitors" / "tasks.py"
BRIEFING = BACKEND / "modules" / "monitors" / "briefing.py"
MIGRATIONS = BACKEND / "alembic" / "versions"


def _src(path: Path) -> str:
    """读源码并**行尾归一化**（本仓 CRLF/LF 混存，锚点不能依赖某一种）。"""
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _callee_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")


# ============================================================================
# 判据的**纯函数**形态 —— 抽出来是为了能做反向自检（见最后一组）
# ============================================================================

def _name_problems(schedule: dict, expected: str) -> list:
    """调度条目投递的名字是否**逐字**等于注册名。"""
    entry = (schedule or {}).get(ENTRY_KEY)
    if entry is None:
        return [f"beat_schedule 里没有 {ENTRY_KEY!r}"]
    got = entry.get("task")
    if got != expected:
        return [f"{ENTRY_KEY!r} 投递 {got!r}，而 tasks.py 注册的是 {expected!r}"]
    return []


def _queue_problems(schedule: dict) -> list:
    """调度条目是否显式声明了队列（不声明 = 投到默认，将来分队列时会静默失效）。"""
    entry = (schedule or {}).get(ENTRY_KEY)
    if entry is None:
        return [f"beat_schedule 里没有 {ENTRY_KEY!r}"]
    if not (entry.get("options") or {}).get("queue"):
        return [f"{ENTRY_KEY!r} 没有显式声明 options.queue"]
    return []


def _autodiscover_problems(source: str, package: str) -> list:
    """`autodiscover_tasks([...])` 的列表里是否含某个包。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee_name(node) == "autodiscover_tasks":
            for arg in node.args:
                if isinstance(arg, ast.List):
                    vals = {e.value for e in arg.elts if isinstance(e, ast.Constant)}
                    if package not in vals:
                        return [f"autodiscover_tasks 列表里没有 {package!r}"]
                    return []
    return ["没找到 autodiscover_tasks(...) 调用（改写法了？）"]


def _calls_of(source: str, func_name: str) -> set:
    """某个（async）函数体内的全部被调名。"""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    out.add(_callee_name(n))
    return out


def _swallows_exception(source: str, func_name: str) -> bool:
    """该函数是否**存在** try/except 却**不在**处理器里 `raise`（= 偷偷吞掉）。"""
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name
        ):
            continue
        for t in ast.walk(node):
            if not isinstance(t, ast.Try) or not t.handlers:
                continue
            for h in t.handlers:
                if not any(isinstance(s, ast.Raise) for s in ast.walk(h)):
                    return True
    return False


def _uses_asyncio_run(source: str) -> bool:
    """源码里是否调了 `asyncio.run(...)`。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            v = node.func.value
            if node.func.attr == "run" and isinstance(v, ast.Name) and v.id == "asyncio":
                return True
    return False


def _except_records_metric(source: str, func_name: str) -> bool:
    """异常处理器里是否**先记了指标**（否则失败只活在 1 小时过期的结果后端里）。"""
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name
        ):
            continue
        for t in ast.walk(node):
            if not isinstance(t, ast.Try) or not t.handlers:
                continue
            for h in t.handlers:
                for n in ast.walk(h):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                        if n.func.attr == "inc":
                            return True
    return False


def _attr_names(source: str, func_name: str) -> set:
    """某函数体内出现的**属性名**（`a.b` -> "b"）。"""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for n in ast.walk(node):
                if isinstance(n, ast.Attribute):
                    out.add(n.attr)
    return out


# ============================================================================
# ① / ② 名字与注册面
# ============================================================================

def test_beat_task_name_equals_task_constant():
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。"""
    from core.redis import celery_app
    from modules.monitors.tasks import TASK_GENERATE_BRIEFINGS

    problems = _name_problems(celery_app.conf.beat_schedule, TASK_GENERATE_BRIEFINGS)
    assert not problems, (
        "\n".join(problems)
        + "\n两处不一致时 beat 会往一个**没人注册**的名字投递："
        "现象是「简报表再不长新行，且日志里一条都没有」。"
    )


def test_beat_entry_declares_queue():
    """调度条目必须显式声明队列。"""
    from core.redis import celery_app

    problems = _queue_problems(celery_app.conf.beat_schedule)
    assert not problems, "\n".join(problems)


def test_autodiscover_includes_monitors_package():
    """`autodiscover_tasks([...])` 必须含 `"modules.monitors"`。

    ★ 与上一条**必须分开**：名字对但没注册，与名字错，症状逐字节相同、
      修法完全不同（前者改 autodiscover 列表，后者改 beat 条目）。
    """
    problems = _autodiscover_problems(_src(REDIS), "modules.monitors")
    assert not problems, "\n".join(problems)


# ============================================================================
# ③ 任务体不是空壳
# ============================================================================

def test_task_body_calls_generator():
    """任务体必须真的走到生成核（三层：task → _generate_all → generate_for_shop）。"""
    src = _src(TASKS)
    assert "_generate_all" in _calls_of(src, "generate_daily_briefings"), (
        "generate_daily_briefings 没有调用 _generate_all —— 任务是个空壳，"
        "调度全绿而 daily_briefings 永远不长新行"
    )
    assert "generate_for_shop" in _calls_of(src, "_generate_all"), (
        "_generate_all 没有调用 generate_for_shop —— 枚举了店铺却没生成任何简报"
    )
    assert "commit" in _attr_names(src, "_generate_all"), (
        "_generate_all 里没有 commit —— 事务边界缺失（不提交 = 什么都没写进去）"
    )


def test_generator_reads_from_monitors_and_writes_briefing():
    """生成核必须**读** monitors、**写** daily_briefings。"""
    src = _src(BRIEFING)
    calls = _calls_of(src, "generate_for_shop")
    assert "add" in calls, "generate_for_shop 没有 session.add（新建分支缺失）"
    # 逐列取出来交给纯函数（不把 ORM 实体透进去 ⇒ 纯函数才能零成本单测）
    body = _src(BRIEFING)
    assert "build_briefing_items" in calls, "generate_for_shop 没有调用纯函数 build_briefing_items"
    assert "MonitorRecord" in body and "DailyBriefingRecord" in body


# ============================================================================
# ④ / ⑤ 异常不吞 + 失败可观测
# ============================================================================

def test_task_does_not_swallow_exception():
    """任务体不吞异常（否则「失败」与「今天没变化」在结果里一模一样）。"""
    assert not _swallows_exception(_src(TASKS), "generate_daily_briefings"), (
        "generate_daily_briefings 的 except 里没有 raise —— 异常被吞成"
        "「生成 0 条」，而那与「今天真的没有变化」长得一模一样"
    )


def test_task_records_metric_before_raising():
    """失败必须先记指标再抛（结果后端 1 小时就过期，指标才是长期告警源）。"""
    assert _except_records_metric(_src(TASKS), "generate_daily_briefings"), (
        "异常处理器里没有 `.inc(...)` —— Celery 的 FAILURE 只活在 worker 日志里，"
        "没人能从长期指标上发现简报已经两周没成功"
    )


def test_task_uses_thread_loop_not_asyncio_run():
    """禁 `asyncio.run()`：asyncpg 连接绑在创建它的 loop 上，第二次必挂。"""
    src = _src(TASKS)
    assert not _uses_asyncio_run(src), (
        "tasks.py 里出现了 asyncio.run() —— 复用应用级连接池时第一次成功、"
        "第二次抛 `Task got Future attached to a different loop`，而单次验证全绿"
    )
    assert "_thread_loop" in src and "threading.local" in src, (
        "没有每线程常驻 loop（_thread_loop）—— 与 audit / trade / memory 的既定范式不符"
    )


# ============================================================================
# ⑦ 键集合：类型 ↔ 标签 / 严重度 / 排序 必须三方相等
# ============================================================================

def test_type_key_sets_are_identical():
    """`ITEM_TYPE_LABELS` / `_TYPE_SEVERITY` / `_TYPE_ORDER` 的键集合必须**完全相等**。

    ★ 漏一个不会报错，只会让摘要里那一类的计数文案缺失、或排序错位 ——
      属于本仓反复记的「同一事实 N 份写法，改一处静默漂移」。
    """
    from modules.monitors import briefing

    labels = set(briefing.ITEM_TYPE_LABELS)
    severity = set(briefing._TYPE_SEVERITY)
    order = set(briefing._TYPE_ORDER)
    assert labels == severity == order, (
        f"键集合漂移：labels-only={labels - severity - order}，"
        f"severity-only={severity - labels - order}，order-only={order - labels - severity}"
    )


def test_severity_rank_covers_all_severities():
    """`_SEVERITY_RANK` 必须覆盖 `_TYPE_SEVERITY` 用到的全部严重度。"""
    from modules.monitors import briefing

    used = set(briefing._TYPE_SEVERITY.values())
    missing = used - set(briefing._SEVERITY_RANK)
    assert not missing, f"这些严重度没有排序权重：{missing}（排序会退化成 9）"


# ============================================================================
# 纯函数行为（阈值 / None / 排序 / 摘要 / 幂等键）
# ============================================================================

def _rec(**kw):
    base = {
        "asin": "B00000000",
        "title": "商品",
        "latest_price": 10.0,
        "price_change_7d": 0.0,
        "latest_bsr": 100,
        "bsr_change_7d": 0,
        "reviews_added_7d": 0,
        "stock_status": "in_stock",
        "estimated_units_remaining": None,
        "listing_changes": None,
    }
    base.update(kw)
    return base


def test_threshold_boundaries_are_inclusive_exact():
    """阈值是**闭区间**：恰好等于阈值必须触发（差一点不触发）。"""
    from modules.monitors import briefing as B

    assert B.build_briefing_items([_rec(price_change_7d=B.PRICE_DROP_THRESHOLD_PCT)]), (
        "恰好等于降价阈值没有触发 —— 边界判据与常量注释不一致"
    )
    assert not B.build_briefing_items(
        [_rec(price_change_7d=B.PRICE_DROP_THRESHOLD_PCT + 0.1, stock_status="in_stock")]
    ), "差 0.1 就够阈值却触发了 —— 阈值被放宽了"
    assert B.build_briefing_items([_rec(bsr_change_7d=B.BSR_CLIMB_THRESHOLD)])
    assert B.build_briefing_items([_rec(reviews_added_7d=B.REVIEW_SURGE_THRESHOLD)])
    assert B.build_briefing_items(
        [_rec(listing_changes=[{"d": i} for i in range(B.LISTING_CHANGE_MIN)])]
    ), "恰好 LISTING_CHANGE_MIN 处没有触发"
    assert not B.build_briefing_items(
        [_rec(listing_changes=[{"d": i} for i in range(B.LISTING_CHANGE_MIN - 1)])]
    ), "少于 LISTING_CHANGE_MIN 处却触发了"


def test_alert_thresholds_are_frozen():
    """告警阈值必须**显式改过测试**才能动 —— 不许被悄悄放宽。

    ★★ 这条是**反向注入逼出来的**（I8）：上面的边界测试用的是**常量自身**
      算期望（`range(LISTING_CHANGE_MIN)`），于是把常量从 2 放宽到 1 时
      它**自适应通过** —— 那条判据在常量被改坏时是真空跑。
      ⇒ 「行为判据」必须配一条「值判据」，否则改常量这条路径无人看守。

    ★ 放宽阈值的后果是**静默的**：简报不再报那些信号，而界面一切正常
      （今天的条目少几条，谁能看出来？）。用户不会知道
      「以前会提醒我的事，现在不提醒了」—— 这正是本仓反复记的失效形态。

    ★ 每个数字的来历都写在 `briefing.py` 的常量注释里（其中两个是
      第 371 轮真实数据驱动的调整）。要改它们，请连着把这里一起改 ——
      那一步的停顿就是本判据的全部价值。
    """
    from modules.monitors import briefing as B

    assert B.PRICE_DROP_THRESHOLD_PCT == -10.0, "降价阈值被改了（放宽 = 少报价格战）"
    assert B.BSR_CLIMB_THRESHOLD == -100, "BSR 跃升阈值被改了"
    assert B.REVIEW_SURGE_THRESHOLD == 20, "评论激增阈值被改了"
    assert B.LISTING_CHANGE_MIN == 2, (
        "Listing 变更门槛被放宽了 —— 回到 1 等于没有门槛："
        "第 371 轮实测它一家占过 48% 的条目，会把降价/排名跃升挤出展示上限"
    )
    assert B.MAX_ITEMS == 20, (
        "展示上限被改回去了 —— 12 比真实产量还小（实测每家店都恰好顶到 12 条，"
        "那是截断不是筛选）"
    )


def test_none_is_not_treated_as_zero():
    """字段缺失（None）**不得**当成 0 —— 否则"没采集到"退化成"什么都没发生"。"""
    from modules.monitors import briefing as B

    items = B.build_briefing_items(
        [_rec(price_change_7d=None, bsr_change_7d=None, reviews_added_7d=None, listing_changes=None)]
    )
    assert items == [], f"字段全缺失却产出了条目：{items}"


def test_items_sorted_by_severity_then_type_order():
    """排序 = 严重度 → 类型优先级 → asin；且**不得**退化成 type 字母序。"""
    from modules.monitors import briefing as B

    items = B.build_briefing_items(
        [
            _rec(asin="B1", listing_changes=[{"d": 1}, {"d": 2}]),   # listing_change (info, order 5)
            _rec(asin="B2", bsr_change_7d=-999),                      # bsr_climb (info, order 4)
            _rec(asin="B3", stock_status="out_of_stock"),             # stock_out (high, order 0)
        ]
    )
    assert [it["severity"] for it in items] == ["high", "info", "info"]
    info_types = [it["type"] for it in items if it["severity"] == "info"]
    assert info_types == ["bsr_climb", "listing_change"], (
        f"同严重度内没有按类型优先级排（实得 {info_types}）—— "
        "按 type 字母序会让 bsr_climb 排在 price_drop 前面"
    )


def test_summarize_never_returns_empty_string():
    """空列表必须给**明确文案**，不能返回空串（空串在界面上等于"有通知但没内容"）。"""
    from modules.monitors import briefing as B

    assert B.summarize([]) == "今天没有需要你处理的变化"
    assert B.summarize([]) != ""


def test_briefing_id_carries_tenant_and_date():
    """主键必须把租户维度与日期都编进去（同 monitors 的 `mon-{asin}-{shop}` 判据）。"""
    from modules.monitors.briefing import briefing_id

    assert briefing_id("2026-10-15", "store_abc") == "brief-2026-10-15-store_abc"
    # 无租户上下文时用占位，**不能**省掉那一段（省掉会与"恰好叫 demo 的店"撞主键）
    assert briefing_id("2026-10-15", None) == "brief-2026-10-15-demo"
    assert briefing_id("2026-10-15", "") == "brief-2026-10-15-demo"


# ============================================================================
# 归属：读口 / 写口都必须带 shop_id 条件
# ============================================================================

def test_mark_read_query_includes_shop_id():
    """标记已读的归属条件必须**进查询**，不能先查出来再在 Python 里比。

    ★ 两者对调用方的可见差异（404 vs 403）就是一个**存在性探测器**。
    """
    attrs = _attr_names(_src(BRIEFING), "mark_read")
    assert "shop_id" in attrs, (
        "mark_read 里没有 shop_id —— 归属条件丢失，任何人可用他人 briefing_id 探测存在性"
    )
    assert "read_at" in attrs, "mark_read 没碰 read_at"
    # 跨店必须返回 None（调用方据此回 404），而不是抛异常或返回空 dict
    body = _src(BRIEFING)
    assert "scalar_one_or_none" in body, "mark_read 没有用 scalar_one_or_none（拿不到时无法区分）"


def test_list_and_count_are_shop_scoped():
    """列表与未读计数都必须按 shop_id 过滤。"""
    src = _src(BRIEFING)
    for fn in ("list_briefings", "count_unread"):
        assert "shop_id" in _attr_names(src, fn), f"{fn} 没有按 shop_id 过滤"


def test_router_uses_shop_dependency_and_404():
    """路由必须走 `get_current_shop_id`，且拿不到时回 404（不静默成功）。"""
    from pathlib import Path as _P

    router = _src(_P(BACKEND, "modules", "monitors", "router.py"))
    assert "get_current_shop_id" in router
    assert 'status_code=404' in router, (
        "标记已读拿不到时没有回 404 —— 静默成功会让前端清掉徽标，"
        "而服务端仍是未读 ⇒ 刷新一下又冒出来"
    )


# ============================================================================
# 模型 / 迁移：表名与注册面
# ============================================================================

def test_model_registered_and_tablename_frozen():
    """新表必须随模块进 `wiring.MODEL_MODULES`，且表名与迁移**逐字一致**。"""
    from wiring import MODEL_MODULES
    from modules.monitors.db_model import DailyBriefingRecord

    assert "modules.monitors.db_model" in MODEL_MODULES, (
        "modules.monitors.db_model 不在 MODEL_MODULES 里 —— create_all / alembic 看不到这张表"
    )
    assert DailyBriefingRecord.__tablename__ == "daily_briefings"


def test_migration_table_name_matches_orm():
    """迁移文件里的 `_TABLE` 必须与 ORM 的 `__tablename__` 相等。"""
    from modules.monitors.db_model import DailyBriefingRecord

    hits = []
    for p in MIGRATIONS.glob("*.py"):
        s = _src(p)
        if "daily_briefings" in s:
            m = re.search(r"^_TABLE = ['\"]([^'\"]+)['\"]", s, re.M)
            if m:
                hits.append((p.name, m.group(1)))
    assert hits, "没有找到建 daily_briefings 的迁移文件"
    for name, table in hits:
        assert table == DailyBriefingRecord.__tablename__, (
            f"迁移 {name} 建的是 {table!r}，而 ORM 声明的是 "
            f"{DailyBriefingRecord.__tablename__!r} —— 库里会多出一张没人用的表"
        )


# ============================================================================
# 反向自检：判据本身必须**有牙齿**（对坏样本报警）
# ============================================================================

def test_selfcheck_name_problems_detects_typo():
    """自检：名字判据必须能识破一个字符的改动。"""
    assert _name_problems({ENTRY_KEY: {"task": "monitors.generate_daily_briefingz"}}, "monitors.generate_daily_briefings")
    assert _name_problems({}, "monitors.generate_daily_briefings")
    assert not _name_problems(
        {ENTRY_KEY: {"task": "monitors.generate_daily_briefings", "options": {"queue": "default"}}},
        "monitors.generate_daily_briefings",
    )


def test_selfcheck_autodiscover_problems_detects_missing():
    """自检：autodiscover 判据必须能识破包名缺失。"""
    bad = 'celery_app.autodiscover_tasks(["modules.aigc_media", "modules.trade"])'
    good = 'celery_app.autodiscover_tasks(["modules.aigc_media", "modules.trade", "modules.monitors"])'
    assert _autodiscover_problems(bad, "modules.monitors")
    assert not _autodiscover_problems(good, "modules.monitors")


def test_selfcheck_swallow_detector_has_teeth():
    """自检：吞异常判据必须区分 `raise` 与 `return`。"""
    swallow = "def f():\n    try:\n        g()\n    except Exception:\n        return\n"
    keep = "def f():\n    try:\n        g()\n    except Exception:\n        raise\n"
    assert _swallows_exception(swallow, "f")
    assert not _swallows_exception(keep, "f")


def test_selfcheck_asyncio_run_detector_has_teeth():
    """自检：`asyncio.run` 判据必须能识破（且不误报 `loop.run_until_complete`）。"""
    bad = "import asyncio\ndef f():\n    asyncio.run(g())\n"
    good = "def f():\n    _thread_loop().run_until_complete(g())\n"
    assert _uses_asyncio_run(bad)
    assert not _uses_asyncio_run(good)


def test_selfcheck_except_metric_detector_has_teeth():
    """自检：失败可观测性判据必须区分「记了指标」与「只 raise」。"""
    bad = "def f():\n    try:\n        g()\n    except Exception:\n        raise\n"
    good = "def f():\n    try:\n        g()\n    except Exception:\n        M.inc(status='failed')\n        raise\n"
    assert not _except_records_metric(bad, "f")
    assert _except_records_metric(good, "f")
