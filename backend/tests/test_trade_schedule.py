"""交易履约域「定时同步」的**接线**门禁（第 283 轮）

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
订单落库同步的四个零件（表 / 口径 / 写入路径 / 上游数据源）在接上之前
**全都已经是好的**，但没有任何东西会去调用它们 —— 现象是
「功能都在，订单表永远是那几条演示数据」。

本文件守的是「真的接上了」这件事，它有三个**互相独立**的失败模式，
而且三个都不报错：

  ① `core/redis.py::beat_schedule` 里的任务名写错
     ⇒ beat 照常投递、worker 照常运行，队列里多一条没人认识的消息。
       「没人消费」不是错误 ⇒ 表现是**什么都没发生**。

  ② `autodiscover_tasks([...])` 漏了 `"modules.trade"`
     ⇒ 装饰器从未被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 查不到，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同。

  ③ 任务体是个空壳（调度接上了，但里面没真的调落库路径）
     ⇒ ① ② 两条全绿，任务每分钟/每 6 小时「成功」一次，表永远不变。

★ 反向注入清单（每条都必须让本文件**至少一条**转红）：
 1. `core/redis.py` 里 `"task": "trade.sync_all_shops"` 改一个字符
    ⇒ `test_beat_task_names_equal_task_constants` 转红
    （而 autodiscover 那条**仍然绿** —— 故两者必须分成两条用例）；
 2. `autodiscover_tasks` 列表里删掉 `"modules.trade"`
    ⇒ `test_tasks_are_registered_by_autodiscover` 转红；
 3. 把 `_sync_one_shop` 里的 `sync_trade(...)` 换成别的（比如直接建 ORM 行）
    ⇒ `test_sync_task_uses_the_single_write_path` 转红；
 4. 删掉组合根 `wiring.SEED_STEPS` 里那条 `modules.trade.seed:...`
    （或让 `core/bootstrap.py::seed_base_data` 不再调用 `_resolve(...)`）
    ⇒ `test_bootstrap_wires_trade_seed` 转红；
 5. 删掉调度条目的 `options.queue`
    ⇒ `test_every_trade_entry_declares_a_queue` 转红。
"""

import ast
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

#: 调度条目的键 → 它应当投递的任务名**常量名**。
#: ★ 这里只写「哪个键对哪个常量」，不写真名字符串 —— 真名的唯一真源是
#:   `modules/trade/tasks.py`，在这里再抄一份就等于给自己造了个替身
#:   （抄错时两条用例会一起绿，看不出问题）。
ENTRIES = {
    "trade-sync-all-shops": "TASK_SYNC_ALL_SHOPS",
}


# ============================================================================
# ① 名字必须对得上
# ============================================================================

def test_beat_task_names_equal_task_constants():
    """调度表投递的名字，必须**逐字**等于 tasks.py 注册的名字。"""
    from core.redis import celery_app
    from modules.trade import tasks as T

    schedule = celery_app.conf.beat_schedule or {}
    for key, const_name in ENTRIES.items():
        entry = schedule.get(key)
        assert entry is not None, (
            f"beat_schedule 里没有 {key!r} —— 这条定时任务退回「零实现」，"
            f"而“没有这个条目”在运行期不产生任何日志或报错。"
        )
        expected = getattr(T, const_name)
        assert entry.get("task") == expected, (
            f"{key!r} 投递的是 {entry.get('task')!r}，而 tasks.py 注册的是 "
            f"{expected!r}（{const_name}）—— 两处不一致时 beat 会往一个没人注册"
            f"的名字投递：现象是「订单表永远不更新，日志里一条都没有」。"
        )


# ============================================================================
# ② 必须真的被 autodiscover 注册
# ============================================================================

def test_tasks_are_registered_by_autodiscover():
    """`autodiscover_tasks` 必须真的把 `modules.trade.tasks` 加载进来。

    ★★ 为什么必须走**子进程**，不能在用例进程里 import：
      `@celery_app.task(name=...)` 是 **import 副作用** —— 只要本用例
      `import modules.trade.tasks`（哪怕只是为了读一个常量），任务就已经
      被注册进 `celery_app.tasks` 了。于是 `assert name in celery_app.tasks`
      这句**被用例自己满足**：把 autodiscover 列表整行删掉它照样绿
      （**假绿**，认的是测试的 import，不是被测行为）。
    """
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{BACKEND_DIR}')\n"
        f"os.chdir(r'{BACKEND_DIR}')\n"
        "assert 'modules.trade.tasks' not in sys.modules, '前置条件：不能先被 import'\n"
        "from core.redis import celery_app\n"
        "from celery.loaders.app import AppLoader\n"
        "# ★ 用 import_default_modules() 而不是 finalize()：实测后者不触发 autodiscover\n"
        "AppLoader(app=celery_app).import_default_modules()\n"
        "# ★★ 这里**绝不能** `import modules.trade.tasks`（哪怕只是为了读 TASK_* 常量）：\n"
        "#    注册是 import 副作用 —— 一 import，断言就被本用例自己满足了，\n"
        "#    把 autodiscover 列表整行删掉它照样绿。本仓 billing 那条踩过同一个坑，\n"
        "#    反向注入实测：加了这行 import，② 号注入（删 autodiscover 条目）**不转红**。\n"
        "#    ⇒ 期望值只能写成字面量 —— 它正是本用例要钉的东西；\n"
        "#      它与 TASK_* 常量是否一致，由 test_beat_task_names_equal_task_constants 守。\n"
        "EXPECTED = ['trade.sync_all_shops', 'trade.sync_shop']\n"
        "names = set(celery_app.tasks)\n"
        "missing = [n for n in EXPECTED if n not in names]\n"
        "print('MISSING=' + ','.join(missing))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(BACKEND_DIR), timeout=180,
    )
    assert proc.returncode == 0, (
        f"子进程跑 autodiscover 失败（rc={proc.returncode}）：\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr[-2000:]}"
    )
    line = [l for l in proc.stdout.splitlines() if l.startswith("MISSING=")]
    assert line, f"子进程没输出结果行：{proc.stdout[-800:]}"
    missing = [x for x in line[-1][len("MISSING="):].split(",") if x]
    assert not missing, (
        f"autodiscover 之后仍查不到这些任务：{missing} —— "
        f"`core/redis.py::autodiscover_tasks` 里少了 `\"modules.trade\"`。"
        f"现象：beat 照常投递、任务永远停在 pending，日志里一条都没有。"
    )


# ============================================================================
# ③ 队列必须显式声明
# ============================================================================

def test_every_trade_entry_declares_a_queue():
    """每条调度条目都要显式给 `options.queue`。

    ★ `worker.py --queues` 只监听 `default`；条目不给 queue 时
      （理论上会走 task_default_queue，但那层默认值一旦被别处覆盖）
      任务就会投到没人监听的队列上，静默积压。
    """
    from core.redis import celery_app

    schedule = celery_app.conf.beat_schedule or {}
    for key in ENTRIES:
        entry = schedule.get(key)
        assert entry is not None, f"beat_schedule 里没有 {key!r}"
        queue = (entry.get("options") or {}).get("queue")
        assert queue, (
            f"{key!r} 没有显式声明 options.queue —— 投到非 default 队列时"
            f"worker 不会消费，任务静默积压。"
        )


# ============================================================================
# ④ 任务体必须真的走唯一写入路径（★ 防「调度接上了但同步没发生」）
# ============================================================================

def _func_calls(tree: ast.AST, func_name: str) -> list[ast.Call]:
    """取某个（async）函数体内的**全部调用**。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    return []


def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def test_sync_task_uses_the_single_write_path():
    """`_sync_one_shop` 必须调 `sync_trade`，且**不许**自己建 ORM 行。

    ★ 为什么值得单列：上面三条只证明「调度接上了」。任务体若被写成
      直接 `session.add(OrderRecord(...))`，三条全绿、任务每 6 小时成功一次，
      而派生态与归因会变成**第二份实现** —— 与 seed 那份各自漂移，
      两边都不报错，差别只体现在「迟了 7 天 vs 迟了 6 天」这种数字上。
    """
    src = (BACKEND_DIR / "modules" / "trade" / "tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    calls = _func_calls(tree, "_sync_one_shop")
    assert calls, "tasks.py 里找不到 `_sync_one_shop` —— 任务体被换掉了？"
    names = {_call_name(c) for c in calls}
    assert "sync_trade" in names, (
        f"`_sync_one_shop` 里没有调 `sync_trade`，实际调用：{sorted(names)} —— "
        f"订单落库必须走 `modules/trade/sync.py` 这一条路径。"
    )

    # ★ 任务体里不许出现 `session.add(` —— 出现即绕过 sync 自己写库
    offenders = [n for n in calls if _call_name(n) == "add"]
    assert not offenders, (
        "`_sync_one_shop` 里出现了 `session.add(...)` —— 任务体不许绕过 "
        "`sync.py` 自己建 ORM 行（那会让写入路径变成两份）。"
    )


# ============================================================================
# ⑤ bootstrap 必须真的挂上 trade 的 seed
# ============================================================================

def test_bootstrap_wires_trade_seed():
    """trade 的 seed 必须真的挂在引导链上，且引导链真的会执行它。

    ★ 为什么这条必须存在：本轮接线前，trade 的 seed **写了、也幂等，
      但零调用**（bootstrap 里没有它）。后果是空库起来后 8 张表全空，
      而这件事**没有任何报错** —— 演示时「收到一条差评」从第一步就走不下去。

    ★ 第 335 轮 P0-7（B 档）：步骤**清单**从 `core/bootstrap.py` 外移到组合根
      `wiring.SEED_STEPS` 的**字符串目标**（`"包.模块:属性"`），因为 `core`
      不得反向 import `modules`。于是本判据的实现随之改成**行为判据**：

        ① **登记**：`wiring.SEED_STEPS` 里确实有 trade 的这一条；
        ② **执行**：`core/bootstrap.py::seed_base_data` 真的会调 `_resolve(...)`
           去解析并执行每一步。

      ⇒ 两半**缺一不可**，与改动前的「import + 调用」两半一一对应：
        「只登记不执行」= 旧的「只 import 不调用」，同样是**不报错的失效**。
    """
    import wiring  # noqa: PLC0415

    targets = [s.target for s in wiring.SEED_STEPS]
    want = "modules.trade.seed:seed_trade_if_empty"
    assert want in targets, (
        f"组合根 `wiring.SEED_STEPS` 里没有 {want!r}（零实现）—— "
        f"空库起来后 trade 8 张表全空，且不报错。当前登记：{targets}"
    )

    path = BACKEND_DIR / "core" / "bootstrap.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "seed_base_data"
        ),
        None,
    )
    assert fn is not None, "`core/bootstrap.py` 里找不到 `seed_base_data` —— 引导链断了"
    # ★ 只看 `seed_base_data` **函数体内**：全文件正则会被别处同形调用旁路满足。
    calls_resolve = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_resolve"
        for n in ast.walk(fn)
    )
    assert calls_resolve, (
        "`seed_base_data` 登记了步骤却**没有调用** `_resolve(...)` 去执行它们 —— "
        "只登记不执行 = 空库起来后 trade 8 张表全空，且不报错。"
    )
