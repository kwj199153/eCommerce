# -*- coding: utf-8 -*-
"""身份域保留期清理的**接线**门禁（第 331 轮）。

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
两个清理函数、两张表、两个保留期 —— 在"接上"之前**全都已经是好的**：

    · `core/identity/login_guard.py::purge_old_attempts`   （`login_attempts`）
    · `core/identity/email_tokens.py::purge_spent_tokens`  （`email_tokens`）
    · `config.login_attempt_retention_days` / 本轮新补的 `email_token_retention_days`

缺的只是**没有任何东西会去调用它们** —— 现象是「两张表只增不减」。
★ 实测本机开发库：`login_attempts` 在 14 天里累积到 **3169** 行
  （2026-09-16 14:34 → 2026-09-30 02:59），而清理从写下那天起一次都没跑过。

本文件守**六种互相独立**、且都不报错的失败模式：

  ① `core/redis.py::beat_schedule` 里的任务名写错
     ⇒ beat 照常投递、worker 照常运行，队列里多一条没人认识的消息。
       「没人消费」不是错误 ⇒ 表现是**什么都没发生**。
  ② `autodiscover_tasks([...])` 漏了 `"core.identity"`
     ⇒ 装饰器从未被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 查不到，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同 ⇒ 必须是两条用例。
  ③ 任务体是个空壳（调度接上了，但里面没真的调清理核）
     ⇒ ① ② 全绿，任务每天"成功"一次，两张表永远不变。
  ④ 清理核写好了，但**唯一的调用点不在 tasks.py 里**（或干脆没有）
     ⇒ 又回到"死代码"的原点 —— 而这是本轮修的那个缺陷本身。
  ⑤ 保留期判据写错（例如把 `created_at < cutoff` 写成 `>`，
     或把 `email_tokens` 的两段条件 `AND` 写成 `OR`）
     ⇒ 删是删了，但删的是**不该删的** —— 而且不报错。
  ⑥ 清理核**自己 commit**（或反过来在任务里漏 commit）
     ⇒ 测试无法回滚；或删除在会话关闭时被静默回滚，而任务仍报"成功"。

★ 反向注入清单（**逐条实测**，13 条全部至少打红一条，且还原后基线复绿）：
  注入点                                          ⇒ 打红的用例
  ─────────────────────────────────────────────────────────────────────────
  1  `core/redis.py` 那条 `"task":` 改一个字符        ⇒ ① 名字相等
     （② autodiscover 那条**仍然绿** —— 故两者必须分开，见下）
  2  autodiscover 列表里删掉 `"core.identity"`       ⇒ ② autodiscover
  3  `_purge_once()` 换成 `return {}`（空壳）        ⇒ ④ 任务体 + ⑤ 唯一调用点
  4  `_purge_once` 里删掉 `purge_spent_tokens` 调用   ⇒ ④ 任务体 + ⑤ 唯一调用点
     （只清一张表 ⇒ 另一张仍无界增长，且两张表的指标都在"成功"）
  5  `_purge_once` 里去掉 `await session.commit()`   ⇒ ④ 任务体
     （删了会在会话关闭时被静默回滚，而任务仍报"成功"）
  6  `login_guard.py` 里 `created_at < cutoff` 改 `>` ⇒ ⑧ login 边界行为
  7  `email_tokens.py` 里**外层** `AND` 改成 `OR_`    ⇒ ⑧ email 四行样本（D 被删）
     （内层 `or_` 改成 `and_` 同样转红 —— 打在 B 上：已过期的行留下）
  8  调度条目里删掉 `"options": {"queue": ...}`       ⇒ ③ 队列显式声明
  9  在 `tasks.py` 的 `_purge_once` 里多调一次清理核   ⇒ ⑤ 唯一调用点（计数 2）
  10  任一个清理核换回裸 SQL（`text("DELETE FROM ...")`）⇒ ⑥ 唯一删除路径
  11  `except` 里 `raise` 换成 `return {"ok": False}` ⇒ ④ 异常不吞
  12  `_run_sync(_purge_once())` 换成 `asyncio.run(...)`⇒ ④ 禁 asyncio.run
  13  `email_token_cutoff` 的默认值写死回 `7`         ⇒ ⑦ 保留期来自配置

★ 台架落在 `.workbuddy/probes/r331_reverse_injection.py`（含「注入是否真的扎进去」的
  前置断言 + 「从自己保存的字节还原并 sha256 复核」；禁 `git checkout` 式还原）。
  ★ 踩过的坑记在这里，省得下次重踩：本仓 CRLF/LF **混存** ——
    `core/redis.py` / `login_guard.py` / `email_tokens.py` 是 CRLF，
    而本轮新建的 `tasks.py` / `retention.py` 是 LF。用 `\n` 写针去扎 CRLF 文件
    ⇒ 命中 0 次 ⇒ 会被误读成「门禁没牙齿」。台架因此带行尾自适应。

★ 为什么行为用例**不提交**（在事务里 rollback）：
  `purge_old_attempts` / `purge_spent_tokens` 都是**全局**删除（按 `created_at`
  过滤，不按租户）—— 这正是保留期任务该有的语义。但若门禁真的 commit 一次，
  它会把共享库里所有超过保留期的**真实**行一起删掉：
  「验证代码的测试」就变成了数据破坏者。⇒ 本文件的做法是
  在**同一个未提交的事务**里：造自造行 → 跑清理并断言 → **rollback**。
  于是：① 真实数据毫发无损；② 顺带把「清理核只删不提交」这条契约也钉住了
  （若哪天有人在核里加了 commit，`test_..._does_not_commit_itself` 会转红）。
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
ENTRY_KEY = "identity-purge-expired"
TASKS_MODULE = BACKEND / "core" / "identity" / "tasks.py"
RETENTION_MODULE = BACKEND / "core" / "identity" / "retention.py"
LOGIN_GUARD_MODULE = BACKEND / "core" / "identity" / "login_guard.py"
EMAIL_TOKENS_MODULE = BACKEND / "core" / "identity" / "email_tokens.py"

#: 生产代码的扫描根（不含 tests/ / scripts/ / alembic/：那里的引用不算"接线"）。
PROD_ROOTS = ("core", "modules", "ai_infra", "platforms")

#: 两个清理核 + 它们各自负责的表（ORM 类名）。
KERNELS = ("purge_old_attempts", "purge_spent_tokens")
MODEL_OF_KERNEL = {"purge_old_attempts": "LoginAttempt", "purge_spent_tokens": "EmailToken"}
#: 受保留期清理管辖的**表名**（只用于「裸 SQL 判据」限定范围，防假阳性）。
_GUARDED_TABLES = ("login_attempts", "email_tokens")
#: 「唯一调用点」= 本文件的被测对象。
EXPECTED_CALLER = "core/identity/tasks.py"


def _src(path: Path) -> str:
    """读源码并**行尾归一化**（本仓 CRLF/LF 混存，锚点不能依赖某一种）。"""
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _iter_prod_py():
    """产出生产源码 (相对路径, 源码)。"""
    for root in PROD_ROOTS:
        d = BACKEND / root
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            yield f.relative_to(BACKEND).as_posix(), _src(f)


# ============================================================================
# 判据的**纯函数**形态 —— 抽出来是为了能做反向自检（见第 ⑥ 组）
# ============================================================================

def _callee_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")


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
                    out.add(_callee_name(n))
    return out


def _swallows_exception(source: str, func_name: str) -> bool:
    """该函数是否**存在** try/except 却**不在**处理器里 `raise`（= 偷偷吞掉）。

    ★ 返回 True 即视为缺陷：本任务的契约是「异常不吞」——
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


def _orm_deletes(source: str, model: str, label: str) -> list[str]:
    """源码里是否有作用在 `Model` 上的 `delete(...)`（返回位置描述）。"""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee_name(node) == "delete":
            if any(isinstance(a, ast.Name) and a.id == model for a in node.args):
                hits.append(f"{label}:{node.lineno}")
    return hits


def _raw_delete_literals(source: str, label: str) -> list[str]:
    """源码里是否还留着**裸 SQL** 的 DELETE 字面量（`text("DELETE FROM ...")`）。

    ★ 判据刻意**同时**要求「有 DELETE」与「点到这两张表之一」：
      · 只判 `text("...")` ⇒ 会把时间格式化之类的无关 SQL 也报出来（假阳性）；
      · 只判表名 ⇒ 会把 `SELECT ... FROM login_attempts` 报出来（假阳性）。
      假阳性和假阴性一样有害：门禁天天红，最后所有人学会无视它。

    ★ 这一条与 `_orm_deletes` 是**一对**：ORM 收口要证的正是「裸 SQL 已不在」。
      只判前者的话，把裸 SQL 加回来（同时保留一处 ORM 调用）也能骗过它。
    """
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _callee_name(node) == "text"):
            continue
        if not node.args:
            continue
        a = node.args[0]
        if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
            continue
        up = a.value.upper()
        if "DELETE" in up and any(t in a.value for t in _GUARDED_TABLES):
            hits.append(f"{label}:{node.lineno}")
    return hits


def _kernel_call_sites(source: str, label: str) -> list[tuple[str, str]]:
    """产出 `(文件, 被调名)` —— 出现了两个清理核之一的调用点。"""
    out: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee_name(node) in KERNELS:
            out.append((label, _callee_name(node)))
    return out


def _uses_asyncio_run(source: str) -> bool:
    """源码里是否调了 `asyncio.run(...)`（★ 本仓记过多次的"假绿"形态）。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            v = node.func.value
            if node.func.attr == "run" and isinstance(v, ast.Name) and v.id == "asyncio":
                return True
    return False


# ============================================================================
# ① 名字必须对得上
# ============================================================================

def test_beat_task_name_equals_task_constant():
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。"""
    from core.identity.tasks import TASK_PURGE_EXPIRED
    from core.redis import celery_app

    problems = _name_problems(celery_app.conf.beat_schedule, TASK_PURGE_EXPIRED)
    assert not problems, (
        "\n".join(problems)
        + "\n两处不一致时 beat 会往一个**没人注册**的名字投递："
        "现象是「两张表只增不减，且日志里一条都没有」——"
        "（「没人消费」本身不是错误，所以什么都不会发生）。"
    )


# ============================================================================
# ② 必须真的被 autodiscover 注册
# ============================================================================

def test_task_is_registered_by_autodiscover():
    """`autodiscover_tasks` 必须真的把 `core.identity.tasks` 加载进来。

    ★★ 为什么必须走**子进程**，不能在用例进程里 import：
      `@celery_app.task(name=...)` 是 **import 副作用** —— 只要本用例
      `import core.identity.tasks`（哪怕只为读一个常量），任务就已经注册进
      `celery_app.tasks` 了。于是断言**被用例自己满足**：把 autodiscover
      列表整行删掉它照样绿（**假绿**，认的是测试的 import，不是被测行为）。
      本仓 billing / trade / audit 三条同款门禁都记过这个坑。
    """
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{BACKEND}')\n"
        f"os.chdir(r'{BACKEND}')\n"
        "assert 'core.identity.tasks' not in sys.modules, '前置条件：不能先被 import'\n"
        "from core.redis import celery_app\n"
        "from celery.loaders.app import AppLoader\n"
        "# 用 import_default_modules() 而不是 finalize()：实测后者不触发 autodiscover\n"
        "AppLoader(app=celery_app).import_default_modules()\n"
        "# 这里**绝不能** import core.identity.tasks（哪怕只为读 TASK_* 常量）：\n"
        "# 注册是 import 副作用 —— 一 import，断言就被本用例自己满足了。\n"
        "# 期望值只能写成**字面量**；它与 TASK_* 常量是否一致，由\n"
        "# test_beat_task_name_equals_task_constant 守（各守一半，缺一不可）。\n"
        "EXPECTED = ['identity.purge_expired']\n"
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
        "`core/redis.py::autodiscover_tasks` 里少了 `\"core.identity\"`。"
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
# ④ 任务体必须真的走**两个**清理核
# ============================================================================

def test_task_body_actually_calls_both_purge_kernels():
    """Celery 任务体 → `_purge_once` → **两个**清理核 + `commit`，三级都要在。

    ★ 为什么单列：上面三条只证明「调度接上了」。任务体若被写成 `return {}`
      （或只清一张表、或漏 commit），三条全绿、任务每天"成功"一次，
      而表永远不变（或悄悄回滚）。
    """
    src = _src(TASKS_MODULE)

    task_calls = _calls_of(src, "purge_expired_identity_rows")
    assert task_calls, (
        "tasks.py 里找不到 `purge_expired_identity_rows` —— 任务体被换掉了？"
    )
    assert "_purge_once" in task_calls, (
        f"任务体没有调 `_purge_once`，实际调用：{sorted(task_calls)} —— "
        "调度接上了但清理不会发生（每天「成功」一次，表永远不变）。"
    )

    once_calls = _calls_of(src, "_purge_once")
    for kernel in KERNELS:
        assert kernel in once_calls, (
            f"`_purge_once` 没有调 `{kernel}`，实际调用：{sorted(once_calls)} —— "
            "两张表必须都被清（只清一张时另一张仍无界增长，且指标上看不出差）。"
        )
    assert "commit" in once_calls, (
        f"`_purge_once` 没有 commit —— 删除会在会话关闭时被回滚，"
        f"而任务仍报成功（「删了 0 行」与「没删」长得一样）。"
        f"实际调用：{sorted(once_calls)}"
    )


def test_task_does_not_swallow_exceptions():
    """★ 「异常不吞」必须真的成立：except 处理器里必须有 `raise`。"""
    src = _src(TASKS_MODULE)
    assert not _swallows_exception(src, "purge_expired_identity_rows"), (
        "`purge_expired_identity_rows` 有 try/except 却**没有 raise** —— "
        "清理失败会被吞掉，而任务看起来成功。"
    )


def test_task_module_does_not_use_asyncio_run():
    """★ 禁止 `asyncio.run()`：本仓记过多次的"第一次成功、第二次必挂"。

    Celery worker 是同步进程、复用应用级 asyncpg 连接池；`asyncio.run()`
    每次新建并关闭 loop ⇒ 第二次执行报 `Task got Future attached to a
    different loop`，而**单次验证会全绿放行**。⇒ 必须走每线程常驻 loop。
    """
    src = _src(TASKS_MODULE)
    assert "_thread_loop" in src, (
        "tasks.py 里没有 `_thread_loop` —— 每线程常驻 loop 的写法被换掉了？"
    )
    assert not _uses_asyncio_run(src), (
        "tasks.py 里出现了 `asyncio.run(...)` —— 复用连接池时会"
        "「第一次成功、第二次必挂」，而单次验证看不出来。"
    )


# ============================================================================
# ⑤ 两个清理核的**唯一**调用点必须是本任务的 tasks.py（防退回死代码）
# ============================================================================

def test_purge_kernels_are_wired_exactly_once():
    """★ 这是本轮修的那个缺陷本身的判据：清理核必须**有且只有一个**调用点。

    改前它们是**零调用点**（只有测试调）⇒ 两张表生产里只增不减。
    现在允许的调用点**恰好**是 `core/identity/tasks.py`（每核各 1 次）。

    ★ 为什么用「恰好」而不是「至少」：多出来的调用点意味着别处也在删这两张表
      （例如某个端点在"清理当前用户的历史"），那是**另一条设计决策**，
      必须被 review 到（同 `IMPORT_TIME_EDGES` 的集合相等思路）。
    """
    hits: list[tuple[str, str]] = []
    for label, src in _iter_prod_py():
        hits += _kernel_call_sites(src, label)

    offenders = sorted({f"{label} -> {name}" for label, name in hits if label != EXPECTED_CALLER})
    assert not offenders, (
        "清理核在 `core/identity/tasks.py` **之外**还有调用点：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 若这是有意的（新的一条删除通道），请显式更新本门禁并说明理由；"
          "若只是顺手调用，请删掉 —— 清理路径必须唯一，否则「谁在删」会变成隐式约定。"
    )

    for kernel in KERNELS:
        n = sum(1 for _, name in hits if name == kernel)
        assert n == 1, (
            f"`{kernel}` 在生产代码里的调用点有 {n} 个（应为 1：tasks.py::_purge_once）—— "
            f"0 个 = 又变回死代码（两张表只增不减）；"
            f">1 个 = 出现了第二条删除通道。实际命中：{sorted(hits)}"
        )


# ============================================================================
# ⑥ 每张表只能有**一条**删除路径，且必须是 ORM（表名单一真源）
# ============================================================================

def test_each_table_has_exactly_one_delete_path():
    """★ 删这两张表**只允许**出现在各自的表模块里，且只允许走 ORM `delete()`。

    两条断言是一对：
      · ORM 侧：`delete(LoginAttempt)` 只出现在 `login_guard.py`，
        `delete(EmailToken)` 只出现在 `email_tokens.py`（各自恰好 1 处）；
      · 裸 SQL 侧：**全生产源码**里不得再有 `text("DELETE ...")` 指向这两张表
        （扫全仓而不是只扫上面两个模块 —— 否则"在别处新开一条裸 SQL 删除"
         就漏了）。

    ★ 为什么要钉（而不是"ORM 写法好看"）：裸 SQL 里表名是**第二份真源**，
      写错时的现象是"删了 0 行"——与"没有过期行"长得一模一样，不报错。
      `core/audit/retention.py` 为此在 r328 定过同款规矩。
    ★ 为什么要钉"只有一条"：`login_attempts` 是登录审计（append-only 的证据），
      多一条删除路径就等于多一个"证据可以消失"的口子。
    """
    expected = {
        "LoginAttempt": LOGIN_GUARD_MODULE,
        "EmailToken": EMAIL_TOKENS_MODULE,
    }
    rel_of = {m: p.relative_to(BACKEND).as_posix() for m, p in expected.items()}

    offenders: list[str] = []
    for label, src in _iter_prod_py():
        for model, home_rel in rel_of.items():
            hits = _orm_deletes(src, model, label)
            if hits and label != home_rel:
                offenders += hits
    assert not offenders, (
        "在各自表模块之外出现了删除这两张表的调用：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 保留期清理是**唯一**允许的删除路径（见 core/identity/retention.py）。"
    )

    for model, home in expected.items():
        rel = rel_of[model]
        hits = _orm_deletes(_src(home), model, rel)
        assert len(hits) == 1, (
            f"{rel} 里对 `delete({model})` 的出现次数是 {len(hits)}（应为 1）—— "
            f"0 次 = 清理核没在删这张表；>1 次 = 有多条删除语句，"
            f"保留期方向可能不一致。命中：{hits}"
        )

    raw: list[str] = []
    for label, src in _iter_prod_py():
        raw += _raw_delete_literals(src, label)
    assert not raw, (
        "生产代码里仍有**裸 SQL 的 DELETE 字面量**指向这两张表：\n  "
        + "\n  ".join(raw)
        + "\n⇒ 表名会有第二份真源（写错时的现象是「删了 0 行」，与「没有过期行」"
          "长得一样）。请改回 ORM 的 `delete(Model)`。"
    )


# ============================================================================
# ⑦ 保留期必须是**配置**（两张表都要），且下限被钳住
# ============================================================================

def test_defaults_come_from_config(monkeypatch):
    """不传参数时，两张表的保留期分别取各自 config 字段（不是写死的常量）。

    ★ 判据方式：把配置改成一个**会让边界移动**的值，再看 cutoff 是否跟着变 ——
      若代码里写死了 7 / 30，改动配置就无效，本条转红。
    ★ 这条**不碰数据库**：`..._cutoff()` 是纯函数（见 `retention.py` 的存在理由）。
      ★ 它同时钉住本轮补的那个配置项：`email_token_retention_days` 改前
        **根本不存在**（保留期硬编码在 `purge_spent_tokens(older_than_days: int = 7)`）。
    """
    import core.identity.retention as R

    for field in ("login_attempt_retention_days", "email_token_retention_days"):
        assert hasattr(R.config, field), (
            f"config 上没有 {field} —— 该表的保留期退化成了硬编码常量"
        )

    now = datetime(2026, 9, 30, 12, 0, 0)
    monkeypatch.setattr(R.config, "login_attempt_retention_days", 45, raising=False)
    monkeypatch.setattr(R.config, "email_token_retention_days", 3, raising=False)

    assert R.login_attempt_cutoff(now=now) == now - timedelta(days=45), (
        "login_attempts 的默认保留期没有跟着 config 走 —— 配置项形同虚设"
    )
    assert R.email_token_cutoff(now=now) == now - timedelta(days=3), (
        "email_tokens 的默认保留期没有跟着 config 走 —— "
        "这正是本轮修的那个缺陷（改前写死 7 天）"
    )

    # 显式传参必须**压过**配置（否则调用方无法临时收紧/放宽）
    assert R.login_attempt_cutoff(10, now=now) == now - timedelta(days=10)
    assert R.email_token_cutoff(1, now=now) == now - timedelta(days=1)


def test_retention_cutoff_clamps_low_values():
    """★ 保留期下限必须钳到 1 天，且方向是**错得轻**的那一侧。

    ★ 为什么这条单独存在、且**不碰数据库**：「配成 0 会不会清空全表」这个问题
      若用一次真删来验证，等于拿共享库当赌注（真删了就不可逆）。
      ⇒ 纯算术断言：既钉住方向，又零副作用。
    ★ 为什么要钉「两份实现收口成一份」：改前两个清理核各写了一遍
      `max(1, ...)`，且**语义还不一致**（一个 `or` 默认值、一个直接用）。
    """
    from core.identity.retention import MIN_RETENTION_DAYS, retention_cutoff

    assert MIN_RETENTION_DAYS == 1, "防呆下限被改了 —— 请先回答「配成 0 会怎样」"
    now = datetime(2026, 9, 30, 12, 0, 0)
    for bad in (0, -1, -999):
        assert retention_cutoff(bad, now=now) == now - timedelta(days=1), (
            f"保留期 {bad} 没有被钳到 1 天 —— 后果是「每次清空全表」，"
            "而那是不可逆的数据销毁；配置写错不该有这个后果"
        )
    assert retention_cutoff(7, now=now) == now - timedelta(days=7)
    assert retention_cutoff(90, now=now) == now - timedelta(days=90)


# ============================================================================
# ⑧ 行为：真库，但**不提交**（真实数据毫发无损）
# ============================================================================

@pytest.mark.asyncio
async def test_login_attempt_purge_deletes_only_rows_past_retention():
    """保留期边界：过期行被删、**期内行必须留下**，且删完可回滚（不提交）。

    ★ 反向注入（已实测）：把核里的 `created_at < cutoff` 改成 `> cutoff`
      ⇒ 本条两条断言**同时**转红（删了新的、留了旧的）。
    """
    from core.database import get_async_session
    from core.identity.login_guard import purge_old_attempts

    email = f"purge-gate-{uuid.uuid4().hex[:10]}@example.invalid"
    async with get_async_session() as db:
        ts_old = datetime.utcnow() - timedelta(days=90)
        ts_fresh = datetime.utcnow()
        old_id, fresh_id = str(uuid.uuid4()), str(uuid.uuid4())
        for rid, ts in ((old_id, ts_old), (fresh_id, ts_fresh)):
            await db.execute(
                text(
                    "INSERT INTO login_attempts (id, email, success, reason, created_at) "
                    "VALUES (:id, :e, false, 'bad_password', :ts)"
                ),
                {"id": rid, "e": email, "ts": ts},
            )
        await db.flush()

        deleted = await purge_old_attempts(db, retention_days=30)
        assert deleted >= 1, (
            "保留期 30 天、事务里存在 90 天前的行，却一行都没删 —— "
            "清理核没有真的按 created_at 过滤（或 cutoff 算反了）"
        )
        rows = (
            await db.execute(
                text("SELECT id FROM login_attempts WHERE email = :e"), {"e": email}
            )
        ).scalars().all()
        assert old_id not in rows, "超过保留期的行**没有**被删掉"
        assert fresh_id in rows, (
            "保留期**之内**的行被删掉了 —— 判据方向写反了"
            "（这比「一条都不删」更危险：它在销毁近期证据）"
        )
        # ★ 核心刻意「只删不提交」（见 retention.py / tasks.py）：这里回滚，
        #   既撤销本次删除（真实数据毫发无损），又顺带钉住了那条契约。
        await db.rollback()

    # ★ 关键判据：本用例**全程未提交** ⇒ 回滚后两行都不该在库里。
    #   为什么这里要一起查 `fresh_id`（而不是只查被删掉的 old_id）：
    #   若哪一天清理路径自己 commit 了，old_id 是"被删掉并提交"（照样查不到），
    #   而 **fresh_id 是"被插入并提交"**（查得到）—— 只查 old_id 就会漏掉这种
    #   「清理核偷偷提交」的回归。这正是 audit 那条同款用例盯的东西。
    async with get_async_session() as db:
        leftover = (
            await db.execute(
                text("SELECT id FROM login_attempts WHERE id IN (:a, :b)"),
                {"a": old_id, "b": fresh_id},
            )
        ).scalars().all()
    assert leftover == [], (
        f"回滚后仍留在库里：{leftover} —— 说明这条路径上有**提交**发生"
        "（清理核必须把事务边界留给调用方；一旦它自己 commit，"
        "本门禁就没法在共享库上安全地验证真实数据了）。"
    )


@pytest.mark.asyncio
async def test_email_token_purge_keeps_unspent_unexpired_rows():
    """`email_tokens` 的**两段条件**：只删"已作废 **且** 够老"的行。

    四行样本，两种命运（★ 每一行都对应一处可能写错的方向）：

      | 行 | created_at | used_at | expires_at | 期望 | 若判据写错会怎样 |
      |----|-----------|---------|-----------|------|-----------------|
      | A  | -30 天    | -30 天  | -30 天    | 删   | —— |
      | B  | -30 天    | NULL    | -5 天     | 删   | 内层 `or_` 错写 `and_` ⇒ B 留下 |
      | C  | 今天      | 今天    | +1 小时   | 留   | 漏了 `created_at <` ⇒ C 被删 |
      | D  | -30 天    | NULL    | +10 天    | 留   | **外层 `AND` 错写 `OR_` ⇒ D 被删** |

    ★ D 那一行是本用例的重点（**注入 7 实测打在它身上**）：它是"老但**还能用**"的
      token（尚未消费、未过期）。删掉它的后果是**用户点自己邮件里的验证/重置链接
      会莫名失败**，而且从库里查不出原因（行已经没了）。
      ★ 注意区分两个方向，别记混：
        · **外层** `AND` → `OR`：条件变**松** ⇒ D 被删（本用例第一条反向注入）；
        · **内层** `or_` → `and_`：条件变**紧** ⇒ B 留下、`deleted >= 2` 也不成立
          （同样转红，只是靶子不同 —— 两种都实测过）。
    """
    from core.database import get_async_session
    from core.identity.auth_models import EmailToken, EmailTokenPurpose
    from core.identity.email_tokens import hash_token, purge_spent_tokens
    from core.identity.models import User, UserRole

    now = datetime.utcnow()
    tag = uuid.uuid4().hex[:10]
    uid = str(uuid.uuid4())
    rows = {
        "A": dict(created=now - timedelta(days=30), used=now - timedelta(days=30),
                  expires=now - timedelta(days=30) + timedelta(hours=1)),
        "B": dict(created=now - timedelta(days=30), used=None,
                  expires=now - timedelta(days=5)),
        "C": dict(created=now, used=now, expires=now + timedelta(hours=1)),
        "D": dict(created=now - timedelta(days=30), used=None,
                  expires=now + timedelta(days=10)),
    }

    async with get_async_session() as db:
        # ① 借一行 users：`email_tokens.user_id` 有 FK（NOT NULL + 外键），
        #    必须挂在一个真实的用户上。★ 这一行也**不提交**（回滚一并撤销）。
        db.add(
            User(
                id=uid,
                email=f"purge-gate-{tag}@example.invalid",
                hashed_password="x",  # 本用例不经鉴权，只要满足 NOT NULL
                role=UserRole.USER,
                is_active=True,
                is_verified=True,
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()

        ids: dict[str, str] = {}
        for key, spec in rows.items():
            tid = str(uuid.uuid4())
            ids[key] = tid
            # ★ 用 distinct 的 hash：token_hash 上有 UNIQUE 约束
            db.add(
                EmailToken(
                    id=tid,
                    user_id=uid,
                    purpose=EmailTokenPurpose.VERIFY_EMAIL.value,
                    token_hash=hash_token(f"{tag}-{key}"),
                    expires_at=spec["expires"],
                    used_at=spec["used"],
                    created_at=spec["created"],
                )
            )
        await db.flush()

        deleted = await purge_spent_tokens(db, older_than_days=7)
        assert deleted >= 2, (
            f"事务里有 2 行「已作废且够老」的 token，却只删了 {deleted} 行 —— "
            "两段条件没同时生效（`(used_at IS NOT NULL OR expires_at < now) "
            "AND created_at < cutoff`）"
        )

        left = set(
            (
                await db.execute(
                    text("SELECT id FROM email_tokens WHERE user_id = :u"), {"u": uid}
                )
            ).scalars().all()
        )
        assert ids["A"] not in left, "已消费且够老的行没被删（used_at 那半没生效）"
        assert ids["B"] not in left, "已过期且够老的行没被删（expires_at 那半没生效）"
        assert ids["C"] in left, (
            "**新鲜**的行被删了 —— `created_at < cutoff` 那一半没生效"
            "（用户在有效期内点链接会失败）"
        )
        assert ids["D"] in left, (
            "★ 尚未消费、尚未过期的 token 被删了 —— 两段条件之间的 `AND` 被写成了"
            " `OR`（正确形式是 `(used_at IS NOT NULL OR expires_at < now) "
            "AND created_at < cutoff`）。后果：用户点自己邮件里的链接会莫名失败，"
            "而从库里查不出原因（行已经没了）"
        )

        # ★ 核刻意「只删不提交」：回滚撤销删除 + 用户行 + 四行 token。
        await db.rollback()

    async with get_async_session() as db:
        leftover = (
            await db.execute(
                text("SELECT count(*) FROM email_tokens WHERE user_id = :u"), {"u": uid}
            )
        ).scalar()
        users_left = (
            await db.execute(text("SELECT count(*) FROM users WHERE id = :u"), {"u": uid})
        ).scalar()
        assert leftover == 0 and users_left == 0, (
            "本用例全程未提交，回滚后应什么都不剩 —— "
            "说明有一处**自己 commit 了**（清理核必须把事务边界留给调用方）"
        )


# ============================================================================
# ⑨ 反向自检：判据必须**能报出**违规样本（否则等于没有判据）
# ============================================================================

def test_name_predicate_reports_a_doctored_entry():
    """① 的判据必须能报出**被改坏的名字**，且放过合规形态。"""
    good = {ENTRY_KEY: {"task": "identity.purge_expired"}}
    assert _name_problems(good, "identity.purge_expired") == []
    assert _name_problems(good, "identity.purge_expiredX"), "常量改名后判据没报出来"

    doctored = {ENTRY_KEY: {"task": "identity.purge_expired_typo"}}
    assert _name_problems(doctored, "identity.purge_expired"), "判据没能报出错的名字"

    assert _name_problems({}, "identity.purge_expired"), "判据没能报出**条目缺失**"


def test_queue_predicate_reports_a_missing_queue():
    """③ 的判据必须能报出**没声明队列**的条目。"""
    assert _queue_problems({ENTRY_KEY: {"options": {"queue": "default"}}}) == []
    assert _queue_problems({ENTRY_KEY: {"task": "x"}}), "判据没能报出缺失的 queue"
    assert _queue_problems({ENTRY_KEY: {"options": {}}}), (
        "判据没能报出 options 存在但 queue 为空的情况"
    )


def test_body_predicates_report_an_empty_shell():
    """④ 的判据必须能报出**空壳任务体**、**漏一个核**、**吞异常**三种形态。"""
    shell = (
        "def purge_expired_identity_rows(self):\n"
        "    return {}\n"
        "async def _purge_once():\n"
        "    return {}\n"
    )
    assert "_purge_once" not in _calls_of(shell, "purge_expired_identity_rows"), (
        "判据把空壳任务体当成了合规实现"
    )

    one_table = (
        "async def _purge_once():\n"
        "    await purge_old_attempts(session)\n"
        "    await session.commit()\n"
    )
    calls = _calls_of(one_table, "_purge_once")
    assert "purge_spent_tokens" not in calls, (
        "判据把「只清一张表」的实现当成了合规实现"
    )

    good = (
        "def purge_expired_identity_rows(self):\n"
        "    try:\n"
        "        return _run_sync(_purge_once())\n"
        "    except Exception:\n"
        "        raise\n"
    )
    assert "_purge_once" in _calls_of(good, "purge_expired_identity_rows")
    assert not _swallows_exception(good, "purge_expired_identity_rows")

    swallowed = (
        "def purge_expired_identity_rows(self):\n"
        "    try:\n"
        "        return _run_sync(_purge_once())\n"
        "    except Exception:\n"
        "        return {'ok': False}\n"
    )
    assert _swallows_exception(swallowed, "purge_expired_identity_rows"), (
        "判据没能报出「吞异常」的形态 —— 那会让失败与「没有过期行」长得一样"
    )


def test_delete_predicates_report_second_path_and_raw_sql():
    """⑥ 的判据必须能报出**第二处删除路径**与**裸 SQL 字面量**（且不误报）。"""
    assert _orm_deletes("x = 1\n", "EmailToken", "a.py") == [], "判据在无删除时误报"
    assert _orm_deletes(
        "await db.execute(delete(EmailToken).where(EmailToken.id == '1'))\n",
        "EmailToken",
        "b.py",
    ), "判据没能报出 `delete(EmailToken)`"

    assert _raw_delete_literals(
        'await db.execute(text("DELETE FROM login_attempts WHERE x"))\n', "c.py"
    ), "判据没能报出裸 SQL 的 DELETE 字面量"
    assert _raw_delete_literals(
        'await db.execute(text("DELETE FROM email_tokens WHERE x"))\n', "c2.py"
    ), "判据漏了另一张表"
    # ★ 防假阳性：判据必须放过「别的表」与「同一张表的非删除语句」
    assert _raw_delete_literals(
        'await db.execute(text("DELETE FROM other_table WHERE x"))\n', "d.py"
    ) == [], "判据把**别的表**的删除也报了出来（假阳性 ⇒ 门禁会被无视）"
    assert _raw_delete_literals(
        'await db.execute(text("SELECT 1 FROM login_attempts"))\n', "e.py"
    ) == [], "判据把非 DELETE 的 SQL 也报了（假阳性）"
    assert _raw_delete_literals(
        'await db.execute(text("UPDATE email_tokens SET used_at = now()"))\n', "f.py"
    ) == [], "判据把 UPDATE 也当成了删除（假阳性）"


def test_wiring_scanner_reports_a_missing_call_site():
    """⑤ 的判据必须能：认出调用点、并且**不**把定义本身当成调用点。"""
    assert _kernel_call_sites("x = purge_old_attempts\n", "a.py") == [], (
        "判据把**裸名字引用**（不是调用）当成了调用点"
    )
    assert _kernel_call_sites(
        "async def f(s):\n    await purge_spent_tokens(s)\n", "b.py"
    ) == [("b.py", "purge_spent_tokens")], "判据没能认出真正的调用点"
    assert _uses_asyncio_run("asyncio.run(coro())\n"), "判据没能报出 asyncio.run"
    assert not _uses_asyncio_run("_thread_loop().run_until_complete(coro())\n"), (
        "判据把「每线程常驻 loop」的合规写法误报成了 asyncio.run"
    )
