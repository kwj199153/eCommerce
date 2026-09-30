# -*- coding: utf-8 -*-
"""审计保留期清理的**接线**门禁（第 328 轮）。

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
清理的三个零件在"接上"之前**全都已经是好的**：表（`audit_logs`）、
保留期（`config.audit_retention_days`）、清理核（`retention.purge_expired`）。
缺的只是**没有任何东西会去调用清理核** —— 现象是「审计表只增不减」。

★ 对照实例就在本仓（这不是假设）：
  `core/identity/login_guard.py::purge_old_attempts` 与
  `core/identity/email_tokens.py::purge_spent_tokens` —— 两个清理函数
  **写好了、幂等、也有行为测试，但生产代码里零调用点**（只有测试调）。
  ⇒ 本轮刻意**不**照抄"只写个函数"的范式，而要钉住「真的接上了调度」。

本文件守四种**互相独立**、且都不报错的失败模式：

  ① `core/redis.py::beat_schedule` 里的任务名写错
     ⇒ beat 照常投递、worker 照常运行，队列里多一条没人认识的消息。
       「没人消费」不是错误 ⇒ 表现是**什么都没发生**。
  ② `autodiscover_tasks([...])` 漏了 `"core.audit"`
     ⇒ 装饰器从未被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 查不到，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同 ⇒ 必须是两条用例。
  ③ 任务体是个空壳（调度接上了，但里面没真的调清理核）
     ⇒ ① ② 全绿，任务每天"成功"一次，表永远不变。
  ④ 保留期判据写错（例如把 `created_at < cutoff` 写成 `>`）
     ⇒ 删是删了，但删的是**不该删的** —— 而且不报错。

★ 反向注入清单（每条都必须让本文件**至少一条**转红，已逐条实测）：
  1. `core/redis.py` 里 `"task": "audit.purge_expired"` 改一个字符
     ⇒ `test_beat_task_name_equals_task_constant` 转红
     （autodiscover 那条**仍然绿** —— 故两者必须分开）；
  2. autodiscover 列表里删掉 `"core.audit"`
     ⇒ `test_task_is_registered_by_autodiscover` 转红；
  3. `_purge_once()` 换成 `return 0`（任务体空壳）
     ⇒ `test_task_body_actually_calls_the_purge_kernel` 转红；
  4. 清理核里 `AuditLog.created_at < cutoff` 改成 `> cutoff`
     ⇒ `test_purge_deletes_only_rows_past_the_retention_window` 转红；
  5. 删掉调度条目的 `options.queue`
     ⇒ `test_the_entry_declares_a_queue` 转红。

★ 为什么行为用例要在事务里 **rollback**（而不是 commit）：
  `purge_expired` 是**全局**删除（按 `created_at` 过滤，不按租户）——
  这正是保留期任务该有的语义。但若门禁真的 commit 一次，
  它会把共享库里所有超过 N 天的**真实**审计行一起删掉：
  「验证代码的测试」就变成了数据破坏者。⇒ 本文件的做法是
  先插两行自造数据 → 在**一个新会话里**跑清理并断言 → **rollback**。
  于是：① 真实数据毫发无损；② 顺带把「只删不提交」这条契约也钉住了。
"""

from __future__ import annotations

import ast
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]

#: beat 调度表里的键（`core/redis.py::beat_schedule`）。
ENTRY_KEY = "audit-purge-expired"
RETENTION_MODULE = BACKEND / "core" / "audit" / "retention.py"
TASKS_MODULE = BACKEND / "core" / "audit" / "tasks.py"
#: 唯一允许出现「删 audit_logs」的模块（对应 service.py 是唯一写入路径）。
AUDIT_DELETE_PATH = RETENTION_MODULE


def _src(path: Path) -> str:
    """读源码并**行尾归一化**（本仓 CRLF/LF 混存，锚点不能依赖某一种）。"""
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


# ============================================================================
# 判据的**纯函数**形态 —— 抽出来是为了能做反向自检（见 C 组）
# ============================================================================

def _name_problems(schedule: dict, expected_task_name: str) -> list[str]:
    """`schedule` 里那条调度条目投递的名字，是否**逐字**等于注册名。"""
    entry = (schedule or {}).get(ENTRY_KEY)
    if entry is None:
        return [f"beat_schedule 里没有 {ENTRY_KEY!r}"]
    got = entry.get("task")
    if got != expected_task_name:
        return [
            f"{ENTRY_KEY!r} 投递 {got!r}，而 tasks.py 注册的是 {expected_task_name!r}"
        ]
    return []


def _queue_problems(schedule: dict) -> list[str]:
    """该调度条目是否显式声明了队列。"""
    entry = (schedule or {}).get(ENTRY_KEY)
    if entry is None:
        return [f"beat_schedule 里没有 {ENTRY_KEY!r}"]
    if not (entry.get("options") or {}).get("queue"):
        return [f"{ENTRY_KEY!r} 没有显式声明 options.queue"]
    return []


def _calls_of(source: str, func_name: str) -> set[str]:
    """某个（async）函数体内的全部被调名（`f(...)` -> f，`a.f(...)` -> f）。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    f = n.func
                    out.add(
                        f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                    )
    return out


def _swallows_exception(source: str, func_name: str) -> bool:
    """该函数是否**存在** try/except 却**不在**处理器里 `raise`（= 偷偷吞掉）。

    ★ 返回 True 即视为缺陷：本任务的契约是「异常不吞」（见 tasks.py docstring）——
      吞掉之后「这次失败了」与「这次没有过期行」在返回值里长得一模一样。
    ★ 只在**有 except** 时才判：没有 try 的函数谈不上吞。
    """
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            continue
        for t in ast.walk(node):
            if not isinstance(t, ast.Try) or not t.handlers:
                continue
            for h in t.handlers:
                if not any(isinstance(s, ast.Raise) for s in ast.walk(h)):
                    return True
    return False


def _audit_row_deletes(source: str, label: str) -> list[str]:
    """源码里是否有作用在 `AuditLog` 上的 `delete(...)`（返回位置描述）。"""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if name != "delete":
                continue
            if any(isinstance(a, ast.Name) and a.id == "AuditLog" for a in node.args):
                hits.append(f"{label}:{node.lineno}")
    return hits


# ============================================================================
# ① 名字必须对得上
# ============================================================================

def test_beat_task_name_equals_task_constant():
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。"""
    from core.audit.tasks import TASK_PURGE_EXPIRED
    from core.redis import celery_app

    problems = _name_problems(celery_app.conf.beat_schedule, TASK_PURGE_EXPIRED)
    assert not problems, (
        "\n".join(problems)
        + "\n两处不一致时 beat 会往一个**没人注册**的名字投递："
        "现象是「审计表只增不减，且日志里一条都没有」——"
        "（「没人消费」本身不是错误，所以什么都不会发生）。"
    )


# ============================================================================
# ② 必须真的被 autodiscover 注册
# ============================================================================

def test_task_is_registered_by_autodiscover():
    """`autodiscover_tasks` 必须真的把 `core.audit.tasks` 加载进来。

    ★★ 为什么必须走**子进程**，不能在用例进程里 import：
      `@celery_app.task(name=...)` 是 **import 副作用** —— 只要本用例
      `import core.audit.tasks`（哪怕只为读一个常量），任务就已经注册进
      `celery_app.tasks` 了。于是断言**被用例自己满足**：把 autodiscover
      列表整行删掉它照样绿（**假绿**，认的是测试的 import，不是被测行为）。
      本仓 billing / trade 两条同款门禁都记过这个坑。
    """
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{BACKEND}')\n"
        f"os.chdir(r'{BACKEND}')\n"
        "assert 'core.audit.tasks' not in sys.modules, '前置条件：不能先被 import'\n"
        "from core.redis import celery_app\n"
        "from celery.loaders.app import AppLoader\n"
        "# 用 import_default_modules() 而不是 finalize()：实测后者不触发 autodiscover\n"
        "AppLoader(app=celery_app).import_default_modules()\n"
        "# 这里**绝不能** import core.audit.tasks（哪怕只为读 TASK_* 常量）：\n"
        "# 注册是 import 副作用 —— 一 import，断言就被本用例自己满足了。\n"
        "# 期望值只能写成**字面量**；它与 TASK_* 常量是否一致，由\n"
        "# test_beat_task_name_equals_task_constant 守（各守一半，缺一不可）。\n"
        "EXPECTED = ['audit.purge_expired']\n"
        "names = set(celery_app.tasks)\n"
        "missing = [n for n in EXPECTED if n not in names]\n"
        "print('MISSING=' + ','.join(missing))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(BACKEND),
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"子进程跑 autodiscover 失败（rc={proc.returncode}）：\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr[-2000:]}"
    )
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("MISSING=")]
    assert line, f"子进程没输出结果行：{proc.stdout[-800:]}"
    missing = [x for x in line[-1][len("MISSING="):].split(",") if x]
    assert not missing, (
        f"autodiscover 之后仍查不到这些任务：{missing} —— "
        "`core/redis.py::autodiscover_tasks` 里少了 `\"core.audit\"`。"
        "现象：beat 照常投递、任务永远停在 pending，日志里一条都没有。"
    )


# ============================================================================
# ③ 队列必须显式声明
# ============================================================================

def test_the_entry_declares_a_queue():
    """调度条目要显式给 `options.queue`（`worker.py --queues` 只监听 default）。"""
    from core.redis import celery_app

    problems = _queue_problems(celery_app.conf.beat_schedule)
    assert not problems, (
        "\n".join(problems)
        + " —— 投到非 default 队列时 worker 不会消费，任务静默积压。"
    )


# ============================================================================
# ④ 任务体必须真的走清理核（★ 防「调度接上了但清理没发生」）
# ============================================================================

def test_task_body_actually_calls_the_purge_kernel():
    """Celery 任务体 → `_purge_once` → `purge_expired`，两级都要在。

    ★ 为什么单列：上面三条只证明「调度接上了」。任务体若被写成 `return 0`
      （或直接 `pass`），三条全绿、任务每天"成功"一次，而表永远不变。
    """
    src = _src(TASKS_MODULE)
    task_calls = _calls_of(src, "purge_expired_audit_logs")
    assert task_calls, (
        "tasks.py 里找不到 `purge_expired_audit_logs` —— 任务体被换掉了？"
    )
    assert "_purge_once" in task_calls, (
        f"任务体没有调 `_purge_once`，实际调用：{sorted(task_calls)} —— "
        "调度接上了但清理不会发生（每天「成功」一次，表永远不变）。"
    )

    once_calls = _calls_of(src, "_purge_once")
    assert "purge_expired" in once_calls, (
        f"`_purge_once` 没有调清理核 `purge_expired`，实际调用：{sorted(once_calls)}"
    )
    assert "commit" in once_calls, (
        f"`_purge_once` 没有 commit —— 删除会在会话关闭时被回滚，"
        f"而任务仍报成功（「删了 0 行」与「没删」长得一样）。"
        f"实际调用：{sorted(once_calls)}"
    )


def test_task_does_not_swallow_exceptions():
    """★ 「异常不吞」必须真的成立：except 处理器里必须有 `raise`。

    若改成「捕获后返回 0 行」，「这次失败了」与「这次没有过期行」在返回值里
    完全一样 —— 那正是「假成功」。tasks.py 的 docstring 承诺了不吞，
    这条把承诺变成判据。
    """
    src = _src(TASKS_MODULE)
    assert not _swallows_exception(src, "purge_expired_audit_logs"), (
        "`purge_expired_audit_logs` 有 try/except 却**没有 raise** —— "
        "清理失败会被吞掉，而任务看起来成功。"
    )


def test_audit_rows_are_deleted_only_in_the_retention_module():
    """★ 删 `audit_logs` 只允许出现在 `retention.py`（唯一删除路径）。

    对应 `test_audit_gate.py::A2`（构造 `AuditLog` 只允许在 `service.py`）的
    **删除版**：`models.py` 把本表定义为 append-only，并声明「清理必须是
    独立的、显式的模块」。若别处也能删，那条声明就只是一句注释。
    """
    offenders: list[str] = []
    for root in ("core", "modules", "ai_infra", "platforms"):
        d = BACKEND / root
        if not d.is_dir():
            continue
        for f in d.rglob("*.py"):
            if "__pycache__" in f.parts or f == AUDIT_DELETE_PATH:
                continue
            offenders += _audit_row_deletes(
                _src(f), str(f.relative_to(BACKEND))
            )
    assert not offenders, (
        "在 core/audit/retention.py 之外出现了删除 `audit_logs` 的调用 —— "
        f"审计的删除路径只能有一条（见 retention.py 文件头）：{offenders}"
    )


# ============================================================================
# ⑤ 行为：保留期边界（真库，但**不真删**真实数据）
# ============================================================================

async def _insert_audit_row(tag: str, *, days_ago: float) -> str:
    """自造一条审计行并**提交**（返回 id）。刻意用裸 SQL 指定 `created_at`。

    ★ 必须能指定历史时间戳 —— ORM 的 `default=datetime.utcnow` 与
      `record_audit()` 都会把时间写成"现在"，而本用例要证的正是**按时间过滤**。
    """
    from core.database import get_async_session

    rid = str(uuid.uuid4())
    ts = datetime.utcnow() - timedelta(days=days_ago)
    async with get_async_session() as db:
        await db.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, action, status, target_type, target_id, summary, created_at) "
                "VALUES (:id, 'login.success', 'success', 'user', :tag, :summary, :ts)"
            ),
            {"id": rid, "tag": tag, "summary": f"保留期门禁用例 {tag}", "ts": ts},
        )
        await db.commit()
    return rid


async def _drop_rows(tag: str) -> None:
    """清掉本用例自造的行（只按 target_id 精确删，不碰真实数据）。"""
    from core.database import get_async_session

    async with get_async_session() as db:
        await db.execute(
            text("DELETE FROM audit_logs WHERE target_id = :tag"), {"tag": tag}
        )
        await db.commit()


@pytest.mark.asyncio
async def test_purge_deletes_only_rows_past_the_retention_window():
    """保留期边界：过期行被删、**期内行必须留下**，且删完可回滚（不提交）。

    ★ 反向注入（已实测）：把核里的 `created_at < cutoff` 改成 `> cutoff`
      ⇒ 本条两条断言**同时**转红（删了新的、留了旧的）。
    """
    from core.audit.retention import purge_expired
    from core.database import get_async_session

    tag = f"purge-{uuid.uuid4().hex[:10]}"
    old_id = await _insert_audit_row(tag, days_ago=10)
    fresh_id = await _insert_audit_row(tag, days_ago=0)
    try:
        async with get_async_session() as db:
            deleted = await purge_expired(db, retention_days=5)
            assert deleted >= 1, (
                "保留期 5 天、库里存在 10 天前的行，却一行都没删 —— "
                "清理核没有真的按 created_at 过滤（或 cutoff 算反了）"
            )
            rows = (
                await db.execute(
                    text("SELECT id FROM audit_logs WHERE target_id = :tag"),
                    {"tag": tag},
                )
            ).scalars().all()
            assert old_id not in rows, "超过保留期的行**没有**被删掉"
            assert fresh_id in rows, (
                "保留期**之内**的行被删掉了 —— 判据方向写反了"
                "（这比「一条都不删」更危险：它在销毁近期证据）"
            )
            # ★ 核刻意「只删不提交」（见 retention.py）：这里回滚，
            #   既撤销本次删除（真实数据毫发无损），又顺带钉住了那条契约。
            await db.rollback()

        async with get_async_session() as db:
            still = (
                await db.execute(
                    text("SELECT id FROM audit_logs WHERE id = :i"), {"i": old_id}
                )
            ).scalars().all()
        assert still == [old_id], (
            "清理核自己 commit 了 —— 它必须把事务边界留给调用方"
            "（否则测试无法回滚，且「谁负责提交」会变成隐式约定）"
        )
    finally:
        await _drop_rows(tag)


def test_retention_cutoff_clamps_low_values():
    """★ 保留期下限必须钳到 1 天，且方向是**错得轻**的那一侧。

    ★ 为什么这条单独存在、且**不碰数据库**：
      「配成 0 会不会清空全表」这个问题若用一次真删来验证，等于拿共享库
      当赌注（真删了就不可逆）。⇒ 把 cutoff 的算法抽成纯函数
      （`retention_cutoff`）后，它变成一个纯算术断言：既钉住了方向，
      又零副作用。
    """
    from core.audit.retention import retention_cutoff

    now = datetime(2026, 9, 30, 12, 0, 0)
    for bad in (0, -1, -999):
        assert retention_cutoff(bad, now=now) == now - timedelta(days=1), (
            f"保留期 {bad} 没有被钳到 1 天 —— 后果是「每次清空全表」，"
            "而那是不可逆的数据销毁；配置写错不该有这个后果"
        )
    assert retention_cutoff(1, now=now) == now - timedelta(days=1)
    assert retention_cutoff(90, now=now) == now - timedelta(days=90)


def test_default_retention_comes_from_config(monkeypatch):
    """不传参数时，保留期取 `config.audit_retention_days`（不是写死的常量）。

    ★ 判据方式：把配置改成一个**会让边界移动**的值，再看行为是否跟着变 ——
      若代码里写死了 90，改动配置就无效，本条转红。
    """
    import core.audit.retention as R

    assert hasattr(R.config, "audit_retention_days"), (
        "config 上没有 audit_retention_days —— 保留期退化成了硬编码"
    )
    monkeypatch.setattr(R.config, "audit_retention_days", 3, raising=False)
    now = datetime(2026, 9, 30, 12, 0, 0)
    assert R.retention_cutoff(now=now) == now - timedelta(days=3), (
        "默认保留期没有跟着 config 走 —— 配置项形同虚设"
    )


# ============================================================================
# ⑥ 反向自检：判据必须**能报出**违规样本（否则等于没有判据）
# ============================================================================

def test_name_predicate_reports_a_doctored_entry():
    """① 的判据必须能报出**被改坏的名字**，且放过合规形态。"""
    good = {ENTRY_KEY: {"task": "audit.purge_expired"}}
    assert _name_problems(good, "audit.purge_expired") == []
    assert _name_problems(good, "audit.purge_expiredX"), "常量改名后判据没报出来"

    doctored = {ENTRY_KEY: {"task": "audit.purge_expired_typo"}}
    assert _name_problems(doctored, "audit.purge_expired"), "判据没能报出错的名字"

    assert _name_problems({}, "audit.purge_expired"), "判据没能报出**条目缺失**"


def test_queue_predicate_reports_a_missing_queue():
    """③ 的判据必须能报出**没声明队列**的条目。"""
    assert _queue_problems({ENTRY_KEY: {"options": {"queue": "default"}}}) == []
    assert _queue_problems({ENTRY_KEY: {"task": "x"}}), "判据没能报出缺失的 queue"
    assert _queue_problems({ENTRY_KEY: {"options": {}}}), (
        "判据没能报出 options 存在但 queue 为空的情况"
    )


def test_body_predicates_report_an_empty_shell():
    """④ 的判据必须能报出**空壳任务体**与**吞异常**两种形态。"""
    shell = (
        "def purge_expired_audit_logs(self):\n"
        "    return 0\n"
        "async def _purge_once():\n"
        "    return 0\n"
    )
    assert "_purge_once" not in _calls_of(shell, "purge_expired_audit_logs"), (
        "判据把空壳任务体当成了合规实现"
    )

    good = (
        "def purge_expired_audit_logs(self):\n"
        "    try:\n"
        "        return _run_sync(_purge_once())\n"
        "    except Exception:\n"
        "        raise\n"
    )
    assert "_purge_once" in _calls_of(good, "purge_expired_audit_logs")
    assert not _swallows_exception(good, "purge_expired_audit_logs")

    swallowed = (
        "def purge_expired_audit_logs(self):\n"
        "    try:\n"
        "        return _run_sync(_purge_once())\n"
        "    except Exception:\n"
        "        return {'ok': False}\n"
    )
    assert _swallows_exception(swallowed, "purge_expired_audit_logs"), (
        "判据没能报出「吞异常」的形态 —— 那会让失败与「没有过期行」长得一样"
    )


def test_delete_predicate_reports_a_second_delete_path():
    """⑤ 的判据必须能报出**第二处删除路径**。"""
    assert _audit_row_deletes("x = 1\n", "a.py") == [], "判据在无删除时误报"
    hits = _audit_row_deletes(
        "await db.execute(delete(AuditLog).where(AuditLog.id == '1'))\n", "b.py"
    )
    assert hits, "判据没能报出第二处 `delete(AuditLog)`"
