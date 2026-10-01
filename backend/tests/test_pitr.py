# -*- coding: utf-8 -*-
"""PITR（WAL 归档 + 物理基线 + 恢复演练）的**接线**门禁（第 351 轮 / P0-2）。

==============================================================================
★★★ 这条门禁守的是「逻辑 dump 在跑」与「能不能恢复到任意时间点」之间的缝
==============================================================================
`backup_db.py` + `db_backup_daily` **全绿的时候**，PITR 仍可能完全不存在 ——
r350 的实测就是这个状态：`wal_level` / `archive_mode` / `pg_basebackup`
在**生产代码**里 0 命中。而且**没有任何东西会报错**：

    `pg_dump` 每天成功一次、`/health` 一直绿、告警一条不响 ——
    而事故当天你想"恢复到 14:02、但保留 14:00 之后新签的两单"，答案是**做不到**。

本文件守七种互相独立、且都不报错的失效：

  ① `core/redis.py::beat_schedule` 里任务名写错 ⇒ beat 照常投递、worker 照常运行，
     队列里多一条没人认识的消息（"没人消费"不是错误 ⇒ 什么都没发生）
  ② `autodiscover_tasks([...])` 漏了 `"core.backup"` ⇒ 装饰器从未被执行过；
     症状与 ① **逐字节相同**，修法完全不同 ⇒ 必须是两条用例
  ③ 任务体是空壳（调度接上了，但没真去跑脚本）⇒ 每天"成功"，`backups/base/` 永不增长
  ④ 吞掉脚本的非 0 退出码 ⇒ "校验失败"与"成功"在任务结果里长得一样
  ⑤ `archive_command` **不幂等**（缺 `test ! -f`）：PG 归档失败会重试同一个段，
     没有 `test ! -f` 时重试直接覆盖 —— 而目标位置的 `.done` 标记已经写下了，
     ⇒ "归档成功"与"内容被后来者改过"可以同时成立，且无人知晓
  ⑥ 产物没进 `.gitignore` ⇒ WAL 段（16MB/个）被提交进仓库
  ⑦ 少了告警 ⇒ 以上任何一条发生都只在日志里，而日志会被滚动覆盖

★ 反向注入清单（逐条实测，见 `.workbuddy/probes/r351/revinject_pitr.py`）：
  注入点                                                    ⇒ 打红的用例
  ────────────────────────────────────────────────────────────────────────────
  1  beat 里 `"task"` 改一个字符                            ⇒ ①（② 仍绿）
  2  autodiscover 列表删掉 `"core.backup"`                  ⇒ ②
  3  `wal_archive_fetch` 体换成 `return {}`                 ⇒ ③ / ⑦
  4  `_run_pitr` 里删掉 `if proc.returncode != 0: raise`    ⇒ ④
  5  任务 `except` 里 `raise` 换 `return`                   ⇒ ④ 的"不吞"那条
  6  `ARCHIVE_COMMAND` 去掉 `test ! -f `                    ⇒ ⑤
  6b `pg_pitr.py` 的 `--help` 少一个子命令                  ⇒ 子命令那条
  7  `.gitignore` 里删掉 `backups/`                         ⇒ ⑥
  8  告警规则里删掉 `pitr_runs_total` 那三条                ⇒ ⑦

★ 为什么 `_run_pitr` 的调用点用「恰好 N」而不是「至少 1」：多出来的调用点意味着
  别处也在起 PITR 子进程（例如某个端点在"点一下手动基线"），那是**另一条设计决策**，
  必须被 review 到（同 `IMPORT_TIME_EDGES` 的集合相等思路）。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TASKS_MODULE = BACKEND / "core" / "backup" / "tasks.py"
SCRIPT = BACKEND / "scripts" / "pg_pitr.py"
ALERT_RULES = ROOT / "observability" / "alert_rules.yml"
GITIGNORE = ROOT / ".gitignore"

#: beat 调度条目键 → 期望的任务注册名。
#: ★ 期望值写成**字面量**：`@celery_app.task(name=...)` 是 import 副作用，
#:   一旦从 `tasks.py` import 常量来比较，断言就可能被用例自己满足（本仓记过多次）。
ENTRIES: dict[str, str] = {
    "wal-archive-fetch": "backup.wal_archive_fetch",
    "pg-basebackup-weekly": "backup.pg_basebackup_weekly",
}

#: `pg_pitr.py` 必须暴露的子命令（缺一个 = 某条能力根本没有入口）。
SUBCMDS = ("status", "enable", "archive-fetch", "basebackup", "drill")

#: 生产代码里**唯一**允许调用 `_run_pitr` 的模块。
EXPECTED_CALLER = "core/backup/tasks.py"


def _src(path: Path) -> str:
    """读源码并**行尾归一化**（本仓 CRLF/LF 混存，锚点不能依赖某一种）。"""
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


# ============================================================================
# 判据的**纯函数**形态 —— 抽出来是为了能做反向自检（见最后一组）
# ============================================================================
def _name_problems(schedule: dict, key: str, expected_task_name: str) -> list[str]:
    """`schedule` 里那条调度条目投递的名字，是否**逐字**等于注册名。"""
    entry = (schedule or {}).get(key)
    if entry is None:
        return [f"beat_schedule 里没有 {key!r}"]
    got = entry.get("task")
    if got != expected_task_name:
        return [f"{key!r} 投递 {got!r}，而 tasks.py 注册的是 {expected_task_name!r}"]
    return []


def _queue_problems(schedule: dict, key: str) -> list[str]:
    entry = (schedule or {}).get(key)
    if entry is None:
        return [f"beat_schedule 里没有 {key!r}"]
    if not (entry.get("options") or {}).get("queue"):
        return [f"{key!r} 没有显式声明 options.queue"]
    return []


def _archive_command_problems(cmd: str) -> list[str]:
    """`archive_command` 是否**幂等**且真的在做拷贝。

    ★ 这是本文件里唯一一条**纯字符串判据**，但它是合法的：`archive_command`
      的值本身就是"要被执行的一条 shell 命令"，它是数据、不是形态。
      （本仓禁止的是「用源码字符串包含代替形态判断」，不是禁止判数据。）
    """
    out: list[str] = []
    if not cmd or not cmd.strip():
        out.append("archive_command 是空的（归档会全部失败）")
        return out
    if "%p" not in cmd or "%f" not in cmd:
        out.append(f"archive_command 里缺 %p/%f 占位符：{cmd!r}（那不是一条归档命令）")
    if "cp " not in cmd and "mv " not in cmd:
        out.append(f"archive_command 里没有拷贝动作：{cmd!r}")
    if "test ! -f" not in cmd:
        out.append(
            f"archive_command **不幂等**（缺 `test ! -f`）：{cmd!r} —— "
            "PG 归档失败会重试同一个段，重试时直接覆盖目标，"
            "而目标位置的 .done 标记已经写下 ⇒ 「归档成功」与「内容已被改写」可以同时成立"
        )
    return out


def _callee_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")


def _calls_of(source: str, func_name: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    out.add(_callee_name(n))
    return out


def _string_constants(source: str, func_name: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for n in ast.walk(node):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    out.add(n.value)
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


def _run_pitr_call_sites(source: str, label: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee_name(node) == "_run_pitr":
            out.append((label, "_run_pitr"))
    return out


@pytest.fixture(scope="module")
def pitr_module() -> Any:
    """按路径加载 `scripts/pg_pitr.py`（`scripts/` 不是包，不能用 import）。

    ★ 为什么"加载模块"而不是"grep 源码"：`ARCHIVE_COMMAND` 是 f-string 拼出来的，
      源码里根本没有最终形态那串字符 —— grep 只能查到片段，查不到**真值**。
    """
    spec = importlib.util.spec_from_file_location("_pg_pitr_under_test", SCRIPT)
    assert spec and spec.loader, f"加载不了 {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================================
# ① 名字必须对得上
# ============================================================================
@pytest.mark.parametrize("key,expected", sorted(ENTRIES.items()))
def test_beat_task_name_equals_task_constant(key: str, expected: str) -> None:
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。"""
    from core.backup import tasks as tasks_mod
    from core.redis import celery_app

    real = {v for k, v in vars(tasks_mod).items() if k.startswith("TASK_")}
    assert expected in real, (
        f"期望的任务名 {expected!r} 不在 `core/backup/tasks.py` 的 TASK_* 常量里：{sorted(real)}"
    )

    problems = _name_problems(celery_app.conf.beat_schedule, key, expected)
    assert not problems, (
        "\n".join(problems)
        + "\n两处不一致时 beat 会往一个**没人注册**的名字投递："
        "现象是「backups/base/ 再不长新目录，且日志里一条都没有」——"
        "（「没人消费」本身不是错误，所以什么都不会发生）。"
    )


# ============================================================================
# ② 必须真的被 autodiscover 注册
# ============================================================================
def test_tasks_are_registered_by_autodiscover() -> None:
    """`autodiscover_tasks` 必须真的把 `core.backup.tasks` 加载进来。

    ★★ 为什么必须走**子进程**：`@celery_app.task(name=...)` 是 import 副作用 ——
      只要本用例 `import core.backup.tasks`（哪怕只为读一个常量），任务就已经
      注册进 `celery_app.tasks` 了，于是断言**被用例自己满足**（假绿）。
      本仓 billing / trade / audit / identity / backup 五条同款门禁都记过这个坑。
    """
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{BACKEND}')\n"
        f"os.chdir(r'{BACKEND}')\n"
        "assert 'core.backup.tasks' not in sys.modules, '前置条件：不能先被 import'\n"
        "from core.redis import celery_app\n"
        "from celery.loaders.app import AppLoader\n"
        "AppLoader(app=celery_app).import_default_modules()\n"
        "# 期望值只能写字面量（见文件头 ★）\n"
        "EXPECTED = ['backup.wal_archive_fetch', 'backup.pg_basebackup_weekly']\n"
        "names = set(celery_app.tasks)\n"
        "print('MISSING=' + ','.join([n for n in EXPECTED if n not in names]))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(BACKEND), timeout=180
    )
    assert proc.returncode == 0, (
        f"子进程跑 autodiscover 失败（rc={proc.returncode}）：\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr[-2000:]}"
    )
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("MISSING=")]
    assert line, f"子进程没输出结果行：{proc.stdout[-800:]}"
    missing = [x for x in line[-1][len("MISSING=") :].split(",") if x]
    assert not missing, (
        f"autodiscover 之后仍查不到这些任务：{missing} —— "
        "`core/redis.py::autodiscover_tasks` 里少了 `\"core.backup\"`（本文件与 "
        "`core/backup/tasks.py` 同包，通常是同一次改动把它带掉的）。"
    )


# ============================================================================
# ③ 队列必须显式声明
# ============================================================================
@pytest.mark.parametrize("key", sorted(ENTRIES))
def test_entries_declare_a_queue(key: str) -> None:
    from core.redis import celery_app

    problems = _queue_problems(celery_app.conf.beat_schedule, key)
    assert not problems, "\n".join(problems) + " —— 投到非 default 队列时 worker 不会消费。"


# ============================================================================
# ④ 任务体必须真的去跑 PITR 脚本
# ============================================================================
@pytest.mark.parametrize(
    "func,subcmd", [("wal_archive_fetch", "archive-fetch"), ("pg_basebackup_weekly", "basebackup")]
)
def test_task_bodies_really_run_the_pitr_script(func: str, subcmd: str) -> None:
    """Celery 任务体 → `_run_pitr` → 真的执行 `pg_pitr.py <subcmd>`。

    ★ 为什么单列：上面的名字/注册/队列三条只证明「调度接上了」。任务体若被写成
      `return {}`，三条全绿、任务每周"成功"一次，而 `backups/base/` 永不出现。
    """
    src = _src(TASKS_MODULE)

    calls = _calls_of(src, func)
    assert calls, f"tasks.py 里找不到 `{func}` —— 任务体被换掉了？"
    assert "_run_pitr" in calls, (
        f"`{func}` 没有调 `_run_pitr`，实际调用：{sorted(calls)} —— "
        "调度接上了但 PITR 不会发生（任务「成功」一次，产物目录永远不变）。"
    )
    consts = _string_constants(src, func)
    assert subcmd in consts, (
        f"`{func}` 里没有子命令字面量 {subcmd!r}，实际：{sorted(consts)} —— "
        "`pg_pitr.py` 的子命令写错会走到 argparse 的 usage 分支（退出码 1）。"
    )

    run_calls = _calls_of(src, "_run_pitr")
    assert "run" in run_calls, (
        f"`_run_pitr` 里没有调 `subprocess.run`，实际：{sorted(run_calls)} —— "
        "它必须真的起子进程跑脚本，而不是返回一个常量。"
    )


def test_run_pitr_is_wired_exactly_twice() -> None:
    """★ `_run_pitr` 在 `core/backup/tasks.py` 之内只能被调用**恰好两次**（两个任务各一次）。"""
    prod_roots = ("core", "modules", "ai_infra", "platforms")
    hits: list[tuple[str, str]] = []
    for root in prod_roots:
        d = BACKEND / root
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            hits += _run_pitr_call_sites(_src(f), f.relative_to(BACKEND).as_posix())

    offenders = sorted({f"{label} -> {name}" for label, name in hits if label != EXPECTED_CALLER})
    assert not offenders, (
        "`_run_pitr` 在 `core/backup/tasks.py` **之外**还有调用点：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 若这是有意的（新的一条 PITR 触发通道），请显式更新本门禁并说明理由。"
    )
    assert len(hits) == 2, (
        f"`_run_pitr` 的调用点有 {len(hits)} 个（应为 2：两个任务各一次）—— "
        f"0/1 个 = 有一半 PITR 从未接线；>2 个 = 出现了第三条通道。实际命中：{sorted(hits)}"
    )


# ============================================================================
# ④b 退出码必须翻译成异常；异常不得被吞
# ============================================================================
def test_exit_code_is_translated_to_an_exception() -> None:
    """★ `_run_pitr` 必须把**非 0 退出码**翻译成异常（不能只记日志）。"""
    tree = ast.parse(_src(TASKS_MODULE))
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_pitr"),
        None,
    )
    assert fn is not None, "tasks.py 里找不到 `_run_pitr`"

    has_raise_in_guard = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "returncode" in test and any(isinstance(s, ast.Raise) for s in ast.walk(node)):
            has_raise_in_guard = True
    assert has_raise_in_guard, (
        "`_run_pitr` 里没有 `if <returncode 判断>: raise` —— "
        "脚本的 2 表示「校验失败」，吞掉它就把「校验失败」记成「成功」（本仓反复记的假成功）。"
    )


@pytest.mark.parametrize("func", ["wal_archive_fetch", "pg_basebackup_weekly"])
def test_tasks_do_not_swallow_exceptions(func: str) -> None:
    assert not _swallows_exception(_src(TASKS_MODULE), func), (
        f"`{func}` 有 try/except 却**没有 raise** —— "
        "失败会被吞掉（退出码非 0 只记个 warning），而任务看起来成功。"
    )


# ============================================================================
# ⑤ archive_command 必须幂等（★ 本轮的真缺陷形态）
# ============================================================================
def test_archive_command_is_idempotent(pitr_module: Any) -> None:
    """`archive_command` 必须是「已存在就不覆盖」的形态。"""
    problems = _archive_command_problems(pitr_module.ARCHIVE_COMMAND)
    assert not problems, "\n".join(problems)


def test_archive_command_is_the_one_actually_written(pitr_module: Any) -> None:
    """★ `enable` 写进 `ALTER SYSTEM` 的，必须**就是**那条被检查过的常量。

    ★ 为什么单列：若 `enable` 里另写了一段内联字符串（与常量各写一份），
      上面那条断言的是**常量**，而库里生效的是**另一份** —— 判据与事实错位。
      这里用 AST 判「`cmd_enable` 的字符串字面量集合里没有别的 archive_command」，
      并判它引用了 `ARCHIVE_COMMAND` 这个名字。
    """
    src = _src(SCRIPT)
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_enable"),
        None,
    )
    assert fn is not None, "pg_pitr.py 里找不到 `cmd_enable`"

    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "ARCHIVE_COMMAND" in names, (
        "`cmd_enable` 没有引用模块级 `ARCHIVE_COMMAND` —— 它多半自己内联了一份，"
        "于是上面那条判据检查的常量与实际写进库里的值是两份东西"
    )
    # `enable` 自己不该再出现 "test ! -f"（那说明它内联了第二份归档命令）
    inline = [c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    assert not [s for s in inline if "test ! -f" in s], (
        f"`cmd_enable` 里出现了内联的归档命令：{[s for s in inline if 'test ! -f' in s]}"
    )


# ============================================================================
# ⑥ 脚本必须真的暴露全部子命令（行为判据，不是读源码）
# ============================================================================
def test_script_exists_and_exposes_all_subcommands() -> None:
    assert SCRIPT.is_file(), f"PITR 脚本缺失：{SCRIPT}"
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "--help"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, f"--help 退出码 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    missing = [c for c in SUBCMDS if c not in r.stdout]
    assert not missing, (
        f"`pg_pitr.py --help` 里没有这些子命令：{missing} —— "
        "能力存在但**没有入口**，等于不存在"
    )


# ============================================================================
# ⑦ 产物不得被提交（WAL 段 16MB/个）
# ============================================================================
@pytest.mark.allow_real_network_subprocess  # ★ 只是查本仓的忽略规则；git 不在"出网"行列
def test_wal_and_base_artifacts_are_gitignored() -> None:
    """用 `git check-ignore` 让 **git 自己**回答，而不是我们读 `.gitignore` 猜。

    ★ 为什么需要 `allow_real_network_subprocess`：`conftest.py` 的自动夹具把
      `git` 归进了「网络类子进程」一并拦掉（它防的是 `git clone/fetch` 那类）。
      这里是**纯本地**查询（`git check-ignore` 只读索引与忽略规则），
      放行是安全的；换掉这个判据（比如自己读 `.gitignore` 做字符串匹配）
      会退化成"读配置猜行为"，而忽略规则有取反、目录式、层级覆盖等形态。
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("环境中没有 git CLI，无法用 git 自身判定忽略规则")
    r = subprocess.run(
        [git, "check-ignore", "-v", "backups/wal/000000010000000000000001"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, (
        "`backups/wal/<段>` **没有**被 git 忽略（git check-ignore 退出码 != 0）—— "
        "WAL 段 16MB/个，一个上午就能把仓库撑爆。\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


# ============================================================================
# ⑧ 指标必须注册 + 真的被写
# ============================================================================
def test_pitr_metrics_are_registered_and_written() -> None:
    from core.observability.metrics import render_prometheus

    rendered = render_prometheus()
    for name in ("pitr_runs_total", "pitr_wal_archive_bytes"):
        assert f"# TYPE {name}" in rendered, f"`{name}` 没有注册进 _REGISTRY：\n{rendered[:400]}"

    src = _src(TASKS_MODULE)
    kinds = _string_constants(src, "wal_archive_fetch") | _string_constants(src, "pg_basebackup_weekly")
    assert "wal_fetch" in kinds, (
        f"`wal_archive_fetch` 没有用 kind=\"wal_fetch\" 记指标，实际字符串：{sorted(kinds)} —— "
        "两个 PITR 任务共用一个计数器又分不开 kind 时，「一半坏了」会被另一半的成功盖住"
    )
    assert "basebackup" in kinds, (
        f"`pg_basebackup_weekly` 没有用 kind=\"basebackup\" 记指标，实际：{sorted(kinds)}"
    )


# ============================================================================
# ⑨ 告警必须覆盖三种失效
# ============================================================================
def test_alert_rules_cover_the_three_failures() -> None:
    """★ 这里用**精确名**而不是「字符串包含」。

    ★ 第一版写成 `assert f"alert: {name}" in text` —— 反向注入实测**打不红**：
      `"alert: WalFetchFailing"` 恰是 `"alert: WalFetchFailingX"` 的**子串**，
      于是把三条告警逐个改名后判据照样绿。同一族「包含式判据被前缀相同的新值骗过」
      在本仓记录过多次，这里改成先解析出 YAML 里的**告警名集合**再判成员资格。
    """
    text = ALERT_RULES.read_text(encoding="utf-8")

    # 指标必须出现在某条 `expr:` 里（而不是碰巧在注释里被提到）
    assert re.search(r"^\s*expr:.*pitr_runs_total", text, re.MULTILINE), (
        "没有任何告警规则的 `expr:` 引用 `pitr_runs_total` —— PITR 的失效将只在日志里，"
        "而日志会被滚动覆盖"
    )

    declared = set(re.findall(r"^\s*-\s*alert:\s*(\S+)\s*$", text, re.MULTILINE))
    missing = [
        a for a in ("WalFetchFailing", "PitrBasebackupFailing", "PitrBasebackupStalled")
        if a not in declared
    ]
    assert not missing, (
        f"告警规则里缺这些告警名：{missing}（实际声明了 {sorted(declared)}）—— "
        "三种失效（外送失败 / 基线失败 / 基线根本没跑）必须各有一条，"
        "只留 Failing 的话「从不产生任何指标」那一半永远不会被报出来"
    )


# ============================================================================
# ⑩ 判据自身必须能被反向输入打红（否则它就是恒真）
# ============================================================================
def test_predicates_catch_doctored_inputs() -> None:
    """把每个纯函数喂一个**己知坏了**的输入，断言它真的报问题。

    ★ 这一组是「门禁的门禁」：没有它，上面十条都可能是恒真的空跑。
      本仓记过同款教训（「没被反向注入验证过的门禁 = 没有门禁」）。
    """
    good = {
        "task": "backup.pg_basebackup_weekly",
        "schedule": object(),
        "options": {"queue": "default"},
    }
    assert _name_problems({"k": good}, "k", "backup.pg_basebackup_weekly") == []
    assert _name_problems({"k": good}, "k", "backup.typo") != []
    assert _name_problems({}, "k", "backup.pg_basebackup_weekly") != []

    assert _queue_problems({"k": good}, "k") == []
    assert _queue_problems({"k": {**good, "options": {}}}, "k") != []

    ok_cmd = "test ! -f /a/%f && cp %p /a/%f"
    assert _archive_command_problems(ok_cmd) == []
    assert _archive_command_problems("cp %p /a/%f") != []          # 不幂等
    assert _archive_command_problems("") != []                      # 空
    assert _archive_command_problems("test ! -f /a/%f") != []       # 没在拷贝
    assert _archive_command_problems("cp %p") != []                 # 缺 %f

    bad_src = "def f():\n    try:\n        g()\n    except Exception:\n        return 1\n"
    good_src = "def f():\n    try:\n        g()\n    except Exception:\n        raise\n"
    assert _swallows_exception(bad_src, "f") is True
    assert _swallows_exception(good_src, "f") is False


# ============================================================================
# ⑪ 端到端演练（环境齐备时才跑；否则明确 skip 并说明缺什么）
# ============================================================================
def _drill_skip_reason() -> str | None:
    if shutil.which("docker") is None:
        return "环境无 docker CLI（CI 的 service 容器不叫 my-postgres，无法 docker exec）"
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "my-postgres"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0 or r.stdout.strip() != "true":
        return "容器 my-postgres 未运行"
    r = subprocess.run(
        ["docker", "exec", "my-postgres", "psql", "-U", "kevin", "-d", "postgres", "-tAc",
         "SHOW archive_mode"],
        capture_output=True, text=True, timeout=60,
    )
    if r.stdout.strip() != "on":
        return "archive_mode≠on —— 先跑 `python scripts/pg_pitr.py enable`"
    return None


_DRILL_SKIP = _drill_skip_reason()


@pytest.mark.skipif(_DRILL_SKIP is not None, reason=_DRILL_SKIP or "")
def test_pitr_drill_end_to_end() -> None:
    """真演练：基线 + 归档 ⇒ 起临时容器恢复到具名还原点。

    ★ 这条才是 PITR 的**权威判据**：其余十条只证明"接线接对了"。
      断言在脚本内（`cmd_drill`）—— 还原点**之前**的写入必须在、
      之后的写入必须不在；只有一边成立都可能恒真（比如恢复根本没跑、库是空的）。
    """
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "drill"],
        cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900,
    )
    assert r.returncode == 0, (
        f"PITR 演练失败（退出码 {r.returncode}）：\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
    )
    assert "RESULT: OK" in r.stdout, f"演练没给出成功结论：\n{r.stdout[-2000:]}"
    for needle in ("A（还原点之前）= 1", "B（还原点之后）= 0"):
        assert needle in r.stdout, (
            f"演练输出里没有 `{needle}` —— 断言没跑到或被改弱了：\n{r.stdout[-2000:]}"
        )
