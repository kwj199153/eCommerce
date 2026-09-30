# -*- coding: utf-8 -*-
"""数据库每日备份的**接线**门禁（第 340 轮 / P0-2）。

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
备份脚本 `backend/scripts/backup_db.py` 在"接上 beat"之前**已经是好的**：
dump → 结构校验 → 深度校验 → 原子落盘 → 轮转，外加 verify / drill / restore 全在。
缺的只是**没有任何东西会去调用它** —— 没有 beat 条目、没有 Celery 任务、没有 cron。
现象是：`backups/` 目录只在有人手动跑时才会出现新文件，而"手动跑"没人会天天记得。
等到真要用备份那天才发现"最近一份是三个月前的"，**不可逆**。
这同 `core/audit/`（第 328 轮）/ `core/identity/`（第 331 轮）那两组保留期清理。

本文件守**五种互相独立**、且都不报错的失败模式：

  ① `core/redis.py::beat_schedule` 里的任务名写错
     ⇒ beat 照常投递、worker 照常运行，队列里多一条没人认识的消息。
       「没人消费」不是错误 ⇒ 表现是**什么都没发生**。
  ② `autodiscover_tasks([...])` 漏了 `"core.backup"`
     ⇒ 装饰器从未被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 查不到，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同 ⇒ 必须是两条用例。
  ③ 任务体是个空壳（调度接上了，但里面没真的去跑备份脚本）
     ⇒ ① ② 全绿，任务每天"成功"一次，`backups/` 永远不长新文件。
  ④ 执行脚本时**吞掉非 0 退出码**（记个 warning 继续）
     ⇒ "备份失败"与"备份成功"在任务结果里长得一样 —— 本仓反复记的"假成功"。
  ⑤ 脚本路径漂移（被移动 / 改名）却静默返回成功
     ⇒ 现象是"每天都跑、每天都成功、就是没有新备份文件"。

★ 反向注入清单（**逐条实测**，见 `.workbuddy/probes/r340_reverse_injection.py`）：
  注入点                                                  ⇒ 打红的用例
  ──────────────────────────────────────────────────────────────────────
  1  `core/redis.py` 那条 `"task":` 改一个字符             ⇒ ① 名字相等
     （② autodiscover 那条**仍然绿** —— 故两者必须分开）
  2  autodiscover 列表里删掉 `"core.backup"`               ⇒ ② autodiscover
  3  `db_backup_daily` 体换成 `return {}`（空壳）          ⇒ ③ 任务体
  4  `_run_backup` 里 `subprocess.run` 换成 `return 0`     ⇒ ③ 任务体（跑脚本那条）
  5  `_run_backup` 里删掉 `if proc.returncode != 0: raise` ⇒ ④ 退出码翻译
  6  `db_backup_daily` 的 `except` 里 `raise` 换 `return`  ⇒ ⑤ 异常不吞
  7  `BACKUP_SCRIPT` 常量改成一个不存在的路径              ⇒ ⑥ 脚本存在 + 行为
  8  调度条目里删掉 `"options": {"queue": ...}`            ⇒ ⑦ 队列显式声明
  9  `_run_backup` 里 `--keep` 后面接常量 `14` 而非 config ⇒ ⑧ 份数来自配置

★ 与 audit / identity 两条同款门禁的**唯一差别**：本任务体**不碰数据库**，
  故不需要 `_thread_loop`（它只是 `subprocess.run`，库访问在子进程里）。
  但同样**禁止** `asyncio.run()` —— 那只会凭空造出一个没人 join 的 loop。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: beat 调度表里的键（`core/redis.py::beat_schedule`）。
ENTRY_KEY = "db-backup-daily"
TASKS_MODULE = BACKEND / "core" / "backup" / "tasks.py"
TASKS_PKG = BACKEND / "core" / "backup" / "__init__.py"
SCRIPT = BACKEND / "scripts" / "backup_db.py"
ALERT_RULES = BACKEND.parent / "observability" / "alert_rules.yml"

#: 生产代码里**唯一**允许调用 `_run_backup` 的模块。
EXPECTED_CALLER = "core/backup/tasks.py"


def _src(path: Path) -> str:
    """读源码并**行尾归一化**（本仓 CRLF/LF 混存，锚点不能依赖某一种）。"""
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _callee_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")


# ============================================================================
# 判据的**纯函数**形态 —— 抽出来是为了能做反向自检（见最后一组）
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
                    out.add(_callee_name(n))
    return out


def _attr_names(source: str, func_name: str) -> set[str]:
    """某函数体内出现的**属性名**（`a.b` -> "b"），供判 `config.db_backup_keep`。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            for n in ast.walk(node):
                if isinstance(n, ast.Attribute):
                    out.add(n.attr)
    return out


def _string_constants(source: str, func_name: str) -> set[str]:
    """某函数体内出现的字符串字面量（供判 `"backup"` / `"--keep"` 子命令）。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            for n in ast.walk(node):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    out.add(n.value)
    return out


def _swallows_exception(source: str, func_name: str) -> bool:
    """该函数是否**存在** try/except 却**不在**处理器里 `raise`（= 偷偷吞掉）。"""
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


def _uses_asyncio_run(source: str) -> bool:
    """源码里是否调了 `asyncio.run(...)`（★ 本仓记过多次的"假绿"形态）。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            v = node.func.value
            if node.func.attr == "run" and isinstance(v, ast.Name) and v.id == "asyncio":
                return True
    return False


def _run_backup_call_sites(source: str, label: str) -> list[tuple[str, str]]:
    """产出 `(文件, 被调名)` —— 出现了 `_run_backup` 的调用点。"""
    out: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee_name(node) == "_run_backup":
            out.append((label, "_run_backup"))
    return out


# ============================================================================
# ① 名字必须对得上
# ============================================================================

def test_beat_task_name_equals_task_constant():
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。"""
    from core.backup.tasks import TASK_DB_BACKUP
    from core.redis import celery_app

    problems = _name_problems(celery_app.conf.beat_schedule, TASK_DB_BACKUP)
    assert not problems, (
        "\n".join(problems)
        + "\n两处不一致时 beat 会往一个**没人注册**的名字投递："
        "现象是「backups/ 再不长新文件，且日志里一条都没有」——"
        "（「没人消费」本身不是错误，所以什么都不会发生）。"
    )


# ============================================================================
# ② 必须真的被 autodiscover 注册
# ============================================================================

def test_task_is_registered_by_autodiscover():
    """`autodiscover_tasks` 必须真的把 `core.backup.tasks` 加载进来。

    ★★ 为什么必须走**子进程**，不能在用例进程里 import：
      `@celery_app.task(name=...)` 是 **import 副作用** —— 只要本用例
      `import core.backup.tasks`（哪怕只为读一个常量），任务就已经注册进
      `celery_app.tasks` 了。于是断言**被用例自己满足**：把 autodiscover
      列表整行删掉它照样绿（**假绿**，认的是测试的 import，不是被测行为）。
      本仓 billing / trade / audit / identity 四条同款门禁都记过这个坑。
    """
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{BACKEND}')\n"
        f"os.chdir(r'{BACKEND}')\n"
        "assert 'core.backup.tasks' not in sys.modules, '前置条件：不能先被 import'\n"
        "from core.redis import celery_app\n"
        "from celery.loaders.app import AppLoader\n"
        "# 用 import_default_modules() 而不是 finalize()：实测后者不触发 autodiscover\n"
        "AppLoader(app=celery_app).import_default_modules()\n"
        "# 这里**绝不能** import core.backup.tasks（哪怕只为读 TASK_* 常量）：\n"
        "# 注册是 import 副作用 —— 一 import，断言就被本用例自己满足了。\n"
        "# 期望值只能写成**字面量**；它与 TASK_* 常量是否一致，由\n"
        "# test_beat_task_name_equals_task_constant 守（各守一半，缺一不可）。\n"
        "EXPECTED = ['backup.db_daily']\n"
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
        "`core/redis.py::autodiscover_tasks` 里少了 `\"core.backup\"`。"
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
# ④ 任务体必须真的去跑备份脚本（三级都要在）
# ============================================================================

def test_task_body_actually_runs_the_backup_script():
    """Celery 任务体 → `_run_backup` → 真的执行 `backup_db.py backup`。

    ★ 为什么单列：上面三条只证明「调度接上了」。任务体若被写成 `return {}`
      （或 `_run_backup` 被换成返回常量），三条全绿、任务每天"成功"一次，
      而 `backups/` 永远不长新文件。
    """
    src = _src(TASKS_MODULE)

    task_calls = _calls_of(src, "db_backup_daily")
    assert task_calls, "tasks.py 里找不到 `db_backup_daily` —— 任务体被换掉了？"
    assert "_run_backup" in task_calls, (
        f"任务体没有调 `_run_backup`，实际调用：{sorted(task_calls)} —— "
        "调度接上了但备份不会发生（每天「成功」一次，backups/ 永远不变）。"
    )

    run_calls = _calls_of(src, "_run_backup")
    assert "run" in run_calls, (
        f"`_run_backup` 里没有调 `subprocess.run`，实际调用：{sorted(run_calls)} —— "
        "它必须真的去起子进程跑脚本，而不是返回一个常量。"
    )

    consts = _string_constants(src, "_run_backup")
    assert "backup" in consts, (
        f"`_run_backup` 里没有子命令字面量 `\"backup\"`，实际：{sorted(consts)} —— "
        "`backup_db.py` 的子命令写错了会走到 argparse 的 usage 分支（退出码 1）。"
    )
    assert "--keep" in consts, (
        f"`_run_backup` 里没有 `\"--keep\"`，实际：{sorted(consts)} —— "
        "不传 --keep 时脚本用默认 14，份数就不再受 config 控制（见 ⑧）。"
    )

    attrs = _attr_names(src, "_run_backup")
    assert "db_backup_keep" in attrs, (
        f"`_run_backup` 没有读 `config.db_backup_keep`，实际属性：{sorted(attrs)} —— "
        "保留份数退化成脚本里的硬编码常量，配置项形同虚设。"
    )


def test_run_backup_is_wired_exactly_once():
    """★ `_run_backup` 在 `core/backup/tasks.py` 之内只能被调用**恰好一次**。

    ★ 为什么用「恰好」而不是「至少」：多出来的调用点意味着别处也在起备份
      子进程（例如某个端点在"点一下手动备份"），那是**另一条设计决策**，
      必须被 review 到（同 `IMPORT_TIME_EDGES` 的集合相等思路）。
    """
    prod_roots = ("core", "modules", "ai_infra", "platforms")
    hits: list[tuple[str, str]] = []
    for root in prod_roots:
        d = BACKEND / root
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            hits += _run_backup_call_sites(_src(f), f.relative_to(BACKEND).as_posix())

    offenders = sorted({f"{label} -> {name}" for label, name in hits if label != EXPECTED_CALLER})
    assert not offenders, (
        "`_run_backup` 在 `core/backup/tasks.py` **之外**还有调用点：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 若这是有意的（新的一条备份触发通道），请显式更新本门禁并说明理由。"
    )
    assert len(hits) == 1, (
        f"`_run_backup` 的调用点有 {len(hits)} 个（应为 1：db_backup_daily 内）—— "
        f"0 个 = 又变回死代码；>1 个 = 出现了第二条备份通道。实际命中：{sorted(hits)}"
    )


def test_task_does_not_swallow_exceptions():
    """★ 「异常不吞」必须真的成立：except 处理器里必须有 `raise`。"""
    src = _src(TASKS_MODULE)
    assert not _swallows_exception(src, "db_backup_daily"), (
        "`db_backup_daily` 有 try/except 却**没有 raise** —— "
        "备份失败会被吞掉（退出码非 0 只记个 warning），而任务看起来成功。"
    )


def test_exit_code_is_translated_to_an_exception():
    """★ `_run_backup` 必须把**非 0 退出码**翻译成异常（不能只记日志）。"""
    src = _src(TASKS_MODULE)
    tree = ast.parse(src)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_run_backup"
        ),
        None,
    )
    assert fn is not None, "tasks.py 里找不到 `_run_backup`"
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert raises, (
        "`_run_backup` 里没有任何 `raise` —— 备份失败（退出码 1/2 / 子进程超时）"
        "会被静默放过，任务仍然报成功。"
    )
    # 判据落在 `returncode` 这个属性上（而不是源码里有没有 "returncode" 字符串）
    assert any(
        isinstance(n, ast.Attribute) and n.attr == "returncode" for n in ast.walk(fn)
    ), "`_run_backup` 没有检查 `proc.returncode` —— 退出码根本没被读"


def test_task_module_does_not_use_asyncio_run():
    """★ 禁止 `asyncio.run()`：本任务体是纯同步 subprocess，不需要任何 loop。

    ★ 与 audit / identity 相反：那两个任务要开 asyncpg 会话，必须 `_thread_loop`；
      本任务**不碰数据库连接**（库访问在子进程里），所以既不需要 `_thread_loop`，
      也绝不该引入 `asyncio.run()` —— 那只会凭空造出一个没人 join 的 loop。
    """
    src = _src(TASKS_MODULE)
    assert not _uses_asyncio_run(src), (
        "tasks.py 里出现了 `asyncio.run(...)` —— 本任务体是纯同步 subprocess，"
        "不需要任何 event loop，加了只会凭空造一个没人 join 的 loop。"
    )


# ============================================================================
# ⑤ 脚本与告警资产必须真的在
# ============================================================================

def test_backup_script_exists():
    """被调度的脚本必须在盘上，**且模块指向的就是它**。

    ★ 反向注入（第 7 条）实测抓到过一处**真缺口**：本用例原先只断言测试文件自己的
      `SCRIPT` 常量存在 —— 把 `tasks.BACKUP_SCRIPT` 改到一个不存在的路径时它照样绿
      （判据判的是测试自己的常量，不是被测行为）。故改为断言**模块的** `BACKUP_SCRIPT`
      同时满足「等于约定路径」+「确实存在」。路径漂移是本仓记过的静默失效形态：
      "每天都跑、每天都成功、就是没有新备份文件"。
    """
    from core.backup import tasks as t

    assert SCRIPT.is_file(), f"备份脚本不存在：{SCRIPT}"
    assert Path(t.BACKUP_SCRIPT) == SCRIPT, (
        f"core/backup/tasks.py 指向的脚本是 {t.BACKUP_SCRIPT}，而约定路径是 {SCRIPT} "
        "—— 脚本被移动/改名后，任务会在 FileNotFoundError 与静默成功之间摇摆。"
    )
    assert Path(t.BACKUP_SCRIPT).is_file(), f"模块指向的脚本不存在：{t.BACKUP_SCRIPT}"
    assert TASKS_PKG.is_file(), f"core/backup 缺 __init__.py：{TASKS_PKG}"


def test_alert_rules_cover_backup_failing_and_stalled():
    """两条方向相反的告警必须都在：Failing（跑了但失败）+ Stalled（压根没跑）。

    ★ 这不是"源码里有没有某个字符串"式的花招：对象是**数据文件**（YAML），
      判的正是"这条规则存在与否"。与 `scripts/check_alert_rules.py`（判
      「规则引用的指标真实且有人写」）互补 —— 那一条管**有效性**，本条管**存在性**。
    ★ 为什么必须成对：只留 Failing 的话，「beat 没起 / 任务名两处不一致 /
      autodiscover 漏了 core.backup」这类**完全不产生任何指标**的故障
      永远不会被报出来。
    """
    text = _src(ALERT_RULES)
    assert re.search(r"alert:\s*BackupFailing\b", text), (
        "observability/alert_rules.yml 里没有 BackupFailing 规则 —— "
        "备份跑了但失败（退出码非 0）不会告警。"
    )
    assert re.search(r"alert:\s*BackupStalled\b", text), (
        "observability/alert_rules.yml 里没有 BackupStalled 规则 —— "
        "beat 没跑 / 任务名两处不一致这类「什么指标都不产生」的故障永远不会响。"
    )
    assert "backup_runs_total" in text, (
        "两条备份告警必须建立在 `backup_runs_total` 上（core/backup/tasks.py 写入）"
    )


# ============================================================================
# ⑥ 行为：不依赖 docker —— 用桩替换 subprocess，验证命令形态与退出码翻译
# ============================================================================

def test_run_backup_builds_expected_command(tmp_path, monkeypatch):
    """`_run_backup` 组出的命令必须是 `[python, backup_db.py, backup, --keep, N]`。

    ★ 用桩替换 `subprocess.run`：本用例**不需要 docker / PG 容器**，
      只验证"我们交给脚本的是什么"。真正的 dump/校验/恢复由脚本自己的测试覆盖。
    """
    from core.backup import tasks as t

    fake_dump = tmp_path / "postgres-20261001-024100.dump"
    fake_dump.write_bytes(b"x" * 4096)
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return t.subprocess.CompletedProcess(
            cmd, 0, stdout=f"[4/4] 轮转\n\nRESULT: OK  {fake_dump}\n", stderr=""
        )

    monkeypatch.setattr(t.subprocess, "run", fake_run)
    info = t._run_backup()

    cmd = captured["cmd"]
    assert Path(cmd[1]) == t.BACKUP_SCRIPT, f"第一个参数不是备份脚本：{cmd}"
    assert cmd[2] == "backup", f"子命令不是 backup：{cmd}"
    assert "--keep" in cmd, f"命令里缺 --keep：{cmd}"
    keep_val = cmd[cmd.index("--keep") + 1]
    assert keep_val == str(t.config.db_backup_keep), (
        f"--keep 传的是 {keep_val!r}，而 config.db_backup_keep={t.config.db_backup_keep!r} "
        "—— 保留份数必须来自配置，不是硬编码"
    )
    assert captured["kw"].get("timeout") == t.BACKUP_TIMEOUT_SECONDS, (
        "没有给 subprocess 超时 —— 备份卡死会一直占着 worker，"
        "且超时那一刻先被 Celery 硬杀，我们记不上失败指标"
    )
    assert info["bytes"] == 4096, f"没有从 RESULT 行解析出备份大小：{info}"
    assert info["file"] == fake_dump.name, f"没有解析出文件名：{info}"


def test_run_backup_raises_on_nonzero_exit(monkeypatch):
    """退出码非 0（脚本的 2 = 备份校验失败）必须抛错，不能被当成成功。"""
    from core.backup import tasks as t

    def fake_run(cmd, **kw):
        return t.subprocess.CompletedProcess(
            cmd, 2, stdout="", stderr="[ERROR] 备份结构校验失败，已丢弃该文件"
        )

    monkeypatch.setattr(t.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as ei:
        t._run_backup()
    assert "退出码=2" in str(ei.value), (
        f"异常里没有带退出码，排查时定位不到失败原因：{ei.value}"
    )


def test_run_backup_does_not_spawn_when_script_missing(tmp_path, monkeypatch):
    """脚本不存在时**直接抛错**，不得静默返回成功、也不该真去起子进程。"""
    from core.backup import tasks as t

    monkeypatch.setattr(t, "BACKUP_SCRIPT", tmp_path / "does-not-exist.py")
    called = {"n": 0}

    def fake_run(*a, **kw):  # pragma: no cover - 不该被调到
        called["n"] += 1
        return t.subprocess.CompletedProcess(a, 0)

    monkeypatch.setattr(t.subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        t._run_backup()
    assert called["n"] == 0, (
        "脚本路径不存在时仍然起了子进程 —— 这会把「路径漂移」掩盖成「脚本自己报错」"
    )


def test_task_records_failed_metric_and_reraises(monkeypatch):
    """任务层：失败时必须**先记 `failed` 指标、再把异常抛出**（不吞）。"""
    from core.backup import tasks as t
    from core.observability import metrics as M

    M.reset_all()

    def boom():
        raise RuntimeError("pg_dump 炸了")

    monkeypatch.setattr(t, "_run_backup", boom)
    with pytest.raises(RuntimeError):
        t.db_backup_daily()

    rendered = M.render_prometheus()
    assert 'backup_runs_total{status="failed"}' in rendered, (
        "失败时没有自增 `backup_runs_total{status=\"failed\"}` —— "
        "BackupFailing 告警将永远不响。实际产物：\n" + rendered
    )


# ============================================================================
# ⑦ 反向自检：判据必须**能报出**违规样本（否则等于没有判据）
# ============================================================================

def test_name_predicate_reports_a_doctored_entry():
    assert _name_problems({ENTRY_KEY: {"task": "backup.db_daily"}}, "backup.db_daily") == []
    assert _name_problems({ENTRY_KEY: {"task": "backup.db_daily"}}, "backup.db_dailyX"), (
        "常量改名后判据没报出来"
    )
    assert _name_problems({ENTRY_KEY: {"task": "backup.db_dailly"}}, "backup.db_daily"), (
        "判据没能报出错的名字"
    )
    assert _name_problems({}, "backup.db_daily"), "判据没能报出**条目缺失**"


def test_queue_predicate_reports_a_missing_queue():
    assert _queue_problems({ENTRY_KEY: {"options": {"queue": "default"}}}) == []
    assert _queue_problems({ENTRY_KEY: {"task": "x"}}), "判据没能报出缺失的 queue"
    assert _queue_problems({ENTRY_KEY: {"options": {}}}), (
        "判据没能报出 options 存在但 queue 为空的情况"
    )


def test_body_predicates_report_an_empty_shell():
    shell = (
        "def db_backup_daily(self):\n"
        "    return {}\n"
        "def _run_backup():\n"
        "    return {}\n"
    )
    assert "_run_backup" not in _calls_of(shell, "db_backup_daily"), (
        "判据把空壳任务体当成了合规实现"
    )

    no_subprocess = "def _run_backup():\n    return {}\n"
    assert "run" not in _calls_of(no_subprocess, "_run_backup"), (
        "判据把「不起子进程」的实现当成了合规实现"
    )

    good = (
        "def db_backup_daily(self):\n"
        "    try:\n"
        "        return _run_backup()\n"
        "    except Exception:\n"
        "        BACKUP_RUNS.inc(status='failed')\n"
        "        raise\n"
    )
    assert "_run_backup" in _calls_of(good, "db_backup_daily")
    assert not _swallows_exception(good, "db_backup_daily")

    swallowed = (
        "def db_backup_daily(self):\n"
        "    try:\n"
        "        return _run_backup()\n"
        "    except Exception:\n"
        "        return {'ok': False}\n"
    )
    assert _swallows_exception(swallowed, "db_backup_daily"), (
        "判据没能报出「吞异常」的形态 —— 那会让失败与成功长得一样"
    )


def test_scanner_predicates_behave():
    """属性名 / 字符串 / asyncio.run / 调用点 四个判据都要能分辨正负样本。"""
    assert "db_backup_keep" in _attr_names(
        "def _run_backup():\n    x = config.db_backup_keep\n", "_run_backup"
    )
    assert "db_backup_keep" not in _attr_names(
        "def _run_backup():\n    x = 14\n", "_run_backup"
    )
    assert "--keep" in _string_constants(
        'def _run_backup():\n    cmd = ["backup", "--keep"]\n', "_run_backup"
    )
    assert _uses_asyncio_run("asyncio.run(coro())\n")
    assert not _uses_asyncio_run("subprocess.run(cmd)\n"), (
        "判据把合规的 `subprocess.run` 误报成了 `asyncio.run`"
    )
    assert _run_backup_call_sites("x = _run_backup\n", "a.py") == [], (
        "判据把**裸名字引用**（不是调用）当成了调用点"
    )
    assert _run_backup_call_sites(
        "def f():\n    return _run_backup()\n", "b.py"
    ) == [("b.py", "_run_backup")], "判据没能认出真正的调用点"
