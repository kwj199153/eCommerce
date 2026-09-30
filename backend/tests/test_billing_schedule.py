"""计费定时任务的**调度接线**门禁（P1，2026-09-25）

==============================================================================
★★★ 这条门禁守的是一类「不报错的失效」
==============================================================================
三条任务的实现都在 `modules/billing/tasks.py`（待支付回收 / 订阅到期清算 /
支付宝对账），调度表在 `core/redis.py::beat_schedule`。两者之间是
**名字的字符串匹配**，而这层匹配的三个失败模式**全都不报错**：

  ① 调度表里的任务名写错了（`billing.expire_pending` vs
     `billing.expire_pending_invoices`）
     ⇒ beat 照常投递、worker 照常运行、队列里多一条**没人认识**的消息。
       而“没人消费”不是错误，队列不会报错 ⇒ 表现是**什么都没发生**。

  ② `core/redis.py` 的 `autodiscover_tasks([...])` 列表漏了 `modules.billing`
     ⇒ 任务装饰器根本没被执行过（没有任何进程 import 过那个模块）
       ⇒ `celery inspect registered` 里查不到它们，而 beat 仍在投递。
       症状与 ① **逐字节相同**，但修法完全不同（一个是改名字，一个是改列表）。

  ③ 调度条目的 `options.queue` 缺了默认值，而 `worker.py --queues` 只监听
     `default` ⇒ 投到别的队列上，同样静默积压。

本文件把三者都钉住：① 与 `TASK_*` 常量相等、② 用**子进程**真跑一遍
autodiscover、③ 显式断言 queue。

==============================================================================
★★ 为什么 ② 必须走子进程，不能在用例进程里 import
==============================================================================
`@celery_app.task(name=...)` 是 **import 副作用**：只要本用例 `import
modules.billing.tasks`（哪怕只是为了读 `TASK_EXPIRE_PENDING` 这个常量），
任务就已经被注册进 `celery_app.tasks` 了 —— 于是
`assert name in celery_app.tasks` 这句**被用例自己满足**，
把 autodiscover 列表整行删掉它照样绿（**假绿**，认的是测试的 import，不是被测行为）。

⇒ 这里起一个**干净的子进程**：先断言 `modules.billing.tasks` 尚未被 import，
再调 `loader.import_default_modules()` 触发 autodiscover（**不是** `finalize()`，
实测后者不触发），最后看任务名在不在。
（判据来源：本仓「注册是 import 副作用 ⇒ 数'绑了几个'禁 grep 源码字面量」。）

★ 反向注入清单（每条都必须让本文件**至少一条**转红）：
 1. `core/redis.py` 里任一条 `"task":` 字面量改一个字符
    ⇒ `test_beat_task_names_equal_task_constants` 转红；
 2. `autodiscover_tasks` 列表里删掉 `"modules.billing"`
    ⇒ `test_tasks_are_registered_by_autodiscover` 转红
      （而 `test_beat_task_names_equal_task_constants` **仍然是绿的** ——
       这正是 ① 与 ② 必须分成两条用例的原因）；
 3. 某条调度条目的 `options.queue` 删掉
    ⇒ `test_every_billing_entry_declares_a_queue` 转红；
 4. 把 `crontab(...)` 换成 `timedelta(...)`
    ⇒ `test_cadence_comes_from_config_not_hardcoded` 转红。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

#: 后端根目录（用例进程与子进程共用同一工作目录口径）
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _as_set(v) -> set:
    """celery 的 crontab 把 hour/minute 存成 **set**（实测 `{3}`），不是标量。

    ★ 与 `tests/test_memory_distill.py::_as_set` 是同一份判断的两个副本 ——
      本仓 `tests/` 无 `__init__.py`（跨模块 import 的解析依赖 pytest 的
      import 模式），故这里刻意重复三行，而不是跨文件 import。
    """
    if v is None:
        return set()
    if isinstance(v, (set, frozenset, list, tuple)):
        return set(v)
    return {v}


#: 调度条目的键 → 它应当投递的任务名常量属性名。
#: ★ 这张表**只写"哪个键对哪个常量"**，不写真名字符串 —— 真名字符串是
#:   `tasks.py` 的唯一真源，在这里再抄一份就等于给自己造了个替身
#:   （抄错时两条用例会一起绿）。
ENTRIES = {
    "billing-expire-pending": "TASK_EXPIRE_PENDING",
    "billing-sweep-subscriptions": "TASK_SWEEP_SUBSCRIPTIONS",
    "billing-reconcile-alipay": "TASK_RECONCILE",
}


# ============================================================================
# ① 名字必须对得上
# ============================================================================

def test_beat_task_names_equal_task_constants():
    """调度表投递的名字，必须**逐字**等于 `tasks.py` 注册的名字。

    ★ 反向注入：把 `core/redis.py` 里 `"task": "billing.reconcile_alipay_orders"`
      改成 `"billing.reconcile_orders"` ⇒ 本条转红。
      而 `autodiscover` 那条用例**不会**红（名字错了但模块确实被加载过）——
      两条用例各守一半，缺一不可。
    """
    from core.redis import celery_app
    from modules.billing import tasks as T

    schedule = celery_app.conf.beat_schedule or {}

    for key, const_name in ENTRIES.items():
        entry = schedule.get(key)
        assert entry is not None, (
            f"beat_schedule 里没有 {key!r} —— 这条定时任务退回「零实现」，"
            f"而“没有这个条目”在运行期不产生任何日志或报错。"
        )
        expected = getattr(T, const_name)
        assert entry.get("task") == expected, (
            f"{key!r} 投递的是 {entry.get('task')!r}，"
            f"而 tasks.py 注册的是 {expected!r}（{const_name}）—— "
            f"两处名字不一致时 beat 会往一个没人注册的名字投递："
            f"现象是「任务永远停在 pending，日志里一条都没有」。"
        )


def test_beat_entries_are_three_distinct_jobs():
    """三条调度必须是**三个不同的任务**（防止复制粘贴时漏改名字）。

    ★ 为什么值得单列：从 `billing-expire-pending` 复制出另外两条、
      只改了 schedule 忘改 task 时，`beat_schedule` 本身完全合法 ——
      两条条目会指向同一个任务，于是**订阅到期清算与日对账一起消失**，
      而“消失”这件事没有任何地方会报出来。
    """
    from core.redis import celery_app

    schedule = celery_app.conf.beat_schedule or {}

    names = [schedule[k]["task"] for k in ENTRIES if k in schedule]
    assert len(names) == len(set(names)), (
        f"三条计费调度里有重复的任务名：{names} —— "
        f"重复意味着至少一条排程被另一条顶掉（静默少跑一个任务）。"
    )
    assert len(names) == len(ENTRIES), (
        f"期望 {len(ENTRIES)} 条计费调度，实际只找到 {len(names)} 条：{names}"
    )


# ============================================================================
# ② 必须真的被 autodiscover 注册（子进程，见模块 docstring）
# ============================================================================

def test_tasks_are_registered_by_autodiscover():
    """`autodiscover_tasks` 必须真的把 `modules.billing.tasks` 加载进来。

    ★ 子进程的第一步是断言 `modules.billing.tasks` **尚未被 import** ——
      这是本用例的**自检**：若将来有人在文件顶部加了
      `from modules.billing import tasks`，注册会变成“用例自己干的”，
      本用例就会退化成假绿。那一步断言会先红，把人挡在假绿之前。

    ★ 反向注入：`core/redis.py` 的 autodiscover 列表去掉 `"modules.billing"`
      ⇒ 本条转红（`registered` 全 False）。
    """
    names = [
        "billing.expire_pending_invoices",
        "billing.sweep_expired_subscriptions",
        "billing.reconcile_alipay_orders",
    ]
    code = f"""
import json, sys
# 自检：此刻还不该有任何计费任务被注册（否则本用例测的是“测试自己的 import”）
assert "modules.billing.tasks" not in sys.modules, "前置被污染：模块已被 import"

from core.redis import celery_app
# ★★ 触发点是 `loader.import_default_modules()`，**不是** `finalize()`（实测）：
#   `autodiscover_tasks()` 只在 `import_modules` 信号上挂了一个接收器，
#   而发这个信号的是 loader —— 也正是 `celery -A core.redis worker` 启动时
#   走的那一步。实测：`finalize()` 前后 `celery_app.tasks` 都是 9 个，
#   billing.* 一个都没有；换成 `import_default_modules()` 后立刻变 15 个。
#   ⇒ 用 `finalize()` 写这条断言，它会**恒红**（与实装不符的哨兵），
#     而用"先 import 任务模块再看注册表"写，它会**恒绿**（自己满足自己）。
celery_app.loader.import_default_modules()

names = {names!r}
print("@@RESULT@@" + json.dumps({{
    "registered": {{n: (n in celery_app.tasks) for n in names}},
    "module_loaded": "modules.billing.tasks" in sys.modules,
}}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"子进程失败（{proc.returncode}）—— 这不是“任务没注册”，"
        f"而是“连 core.redis 都 import 不起来”，归因方向不同：\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    marker = "@@RESULT@@"
    line = next((l for l in proc.stdout.splitlines() if marker in l), None)
    assert line is not None, f"子进程没有输出结果行：\n{proc.stdout}\n{proc.stderr}"
    payload = json.loads(line.split(marker, 1)[1])

    assert payload["module_loaded"], (
        "import_default_modules() 之后 `modules.billing.tasks` 仍未被 import —— "
        "`core/redis.py::autodiscover_tasks` 的列表里漏了 `modules.billing`。"
        "（注意 autodiscover 只是“去哪些包找 tasks 模块”的清单，"
        "漏了它任务装饰器根本不会被执行，而 beat 仍在投递。）"
    )
    missing = [n for n, ok in payload["registered"].items() if not ok]
    assert not missing, (
        f"这些任务名在 autodiscover 之后仍未注册：{missing} —— "
        f"worker 侧不认识它们，投递出去的消息永远不会被消费，且不报错。"
    )


# ============================================================================
# ③ 节奏与队列
# ============================================================================

def test_cadence_comes_from_config_not_hardcoded():
    """调度节奏必须取自 `core/config.py` 的常量，且必须是 **crontab**。

    ★ 为什么必须 crontab（与 memory 那条同理由）：crontab 每次按**当前时间**
      重算下次触发点，不依赖调度文件里的 `last_run_at`；用 `timedelta` 时，
      schedule 文件一旦丢失（容器重建、卷没挂上），就再也算不出"该什么时候跑"
      ⇒ 漏掉一整天，而日志里只有一句“等待下一次运行”。

    ★ 为什么节奏不能手写在这个文件里：`BILLING_*` 常量在 core/config.py，
      是“待支付 TTL / 回收频率 / 对账时刻”这一组关系的一份真源 ——
      写死后改一处漏一处，表现是“回收频率与 TTL 不匹配”（要么白扫、
      要么用户撤销订单后二维码迟迟不失效）。

    ★ 反向注入：把某条 `crontab(hour=..., minute=...)` 换成 `timedelta(hours=1)`
      ⇒ 第一段转红；把 `hour=BILLING_SWEEP_HOUR` 写死成 3 ⇒ 第二段转红
      （除非常量恰好也是 3 —— 所以断言比的是**两边同时取值**，不是字面量）。
    """
    from celery.schedules import crontab

    from core.config import (
        BILLING_EXPIRE_PENDING_INTERVAL_MINUTES,
        BILLING_RECONCILE_HOUR,
        BILLING_RECONCILE_MINUTE,
        BILLING_SWEEP_HOUR,
        BILLING_SWEEP_MINUTE,
    )
    from core.redis import celery_app

    schedule = celery_app.conf.beat_schedule or {}

    for key in ENTRIES:
        sch = schedule[key]["schedule"]
        assert isinstance(sch, crontab), (
            f"{key!r} 的调度是 {type(sch).__name__} 而不是 crontab —— "
            f"schedule 文件丢失后会漏掉一整天（crontab 会按当前时间重算）。"
        )

    # 待支付回收：分钟级 `*/N`
    #
    # ★★ 比的是**展开后的分钟集合**，不是字面量 `"*/5"`（实测踩到）：
    #   celery 的 crontab 会把 `*/5` 立刻展开成 {0, 5, 10, …, 55} ——
    #   于是 `_as_set(sch.minute) == {"*/5"}` 恒为 False，
    #   写出来是一条**恒红**的哨兵（与实装不符），而不是门禁。
    #   正确的判据是"分钟集合 == 以该常数为步长、从 0 起的等差序列"：
    #   步长写错（比如把常量改成 7，而 crontab 仍是 `*/5`）时立刻红。
    expire_minute = _as_set(schedule["billing-expire-pending"]["schedule"].minute)
    expected_expire_minutes = set(range(0, 60, BILLING_EXPIRE_PENDING_INTERVAL_MINUTES))
    assert expire_minute == expected_expire_minutes, (
        f"待支付回收的分钟集合是 {sorted(expire_minute)}，"
        f"与「以 BILLING_EXPIRE_PENDING_INTERVAL_MINUTES="
        f"{BILLING_EXPIRE_PENDING_INTERVAL_MINUTES} 为步长」的等差序列 "
        f"{sorted(expected_expire_minutes)} 不一致（两份写法）"
    )

    # 到期清算：每天 H:M
    sweep = schedule["billing-sweep-subscriptions"]["schedule"]
    assert _as_set(sweep.hour) == {BILLING_SWEEP_HOUR} and _as_set(
        sweep.minute
    ) == {BILLING_SWEEP_MINUTE}, (
        f"到期清算的调度是 {_as_set(sweep.hour)}:{_as_set(sweep.minute)}，"
        f"与 config 的 {BILLING_SWEEP_HOUR}:{BILLING_SWEEP_MINUTE} 不一致"
    )

    # 日对账：每天 H:M，且必须**晚于**到期清算（否则当天状态还没收敛就核对）
    rec = schedule["billing-reconcile-alipay"]["schedule"]
    assert _as_set(rec.hour) == {BILLING_RECONCILE_HOUR} and _as_set(
        rec.minute
    ) == {BILLING_RECONCILE_MINUTE}, (
        f"日对账的调度是 {_as_set(rec.hour)}:{_as_set(rec.minute)}，"
        f"与 config 的 {BILLING_RECONCILE_HOUR}:{BILLING_RECONCILE_MINUTE} 不一致"
    )
    assert (BILLING_RECONCILE_HOUR, BILLING_RECONCILE_MINUTE) >= (
        BILLING_SWEEP_HOUR,
        BILLING_SWEEP_MINUTE,
    ), (
        f"日对账（{BILLING_RECONCILE_HOUR}:{BILLING_RECONCILE_MINUTE}）排在了"
        f"到期清算（{BILLING_SWEEP_HOUR}:{BILLING_SWEEP_MINUTE}）之前 —— "
        f"对账会拿“还没收敛的状态”去和支付宝比，把正常单判成异常（误报）。"
    )


def test_every_billing_entry_declares_a_queue():
    """每条调度都必须显式声明投递队列 —— 与 `worker.py --queues` 对齐。

    ★ 为什么这条值得一个用例：漏了 `options.queue` 时 celery 用默认队列，
      而 `worker.py` 只监听白名单里的队列 ⇒ 消息投到一个没人监听的地方，
      静默积压。这与“名字写错”的症状一样（什么都不发生），但根因在配置。
    """
    from core.redis import celery_app

    schedule = celery_app.conf.beat_schedule or {}

    for key in ENTRIES:
        opts = schedule[key].get("options") or {}
        assert opts.get("queue"), (
            f"{key!r} 没有声明 options.queue —— worker 的 --queues 白名单若不含"
            f"默认队列，这条任务会被投到一个没人监听的地方并静默积压。"
        )
        assert opts["queue"] == "default", (
            f"{key!r} 投到队列 {opts['queue']!r}，而计费任务约定走 'default'"
            f"（worker.py --queues 已含它）。改队列必须同步改 worker 启动参数。"
        )


# ============================================================================
# ④ 对账任务在非支付宝网关下必须**显式跳过**（而不是硬跑一遍刷假告警）
# ============================================================================

def test_reconcile_skips_loudly_when_gateway_is_not_alipay():
    """网关不是 alipay 时必须返回 `ran=False` + `reason='not_alipay'`。

    ★ 为什么这条是**安全**判据而不是“少做点事”：
      硬跑一遍会拿 `mock-xxxx` 之类的单号去问支付宝，全量返回 TRADE_NOT_EXIST，
      于是每一条 paid 账单都被判成"幽灵单" ⇒ 一夜之间刷出成百条 CRITICAL 告警，
      而真相只是“这个环境用 mock 支付”。**假告警会训练运维忽略真告警。**

    ★ 但“跳过”必须**可观测**：返回里带 `ran=False` 与原因，
      否则它和“跑完了、一切正常”长得一模一样 —— 那正是本仓反复收敛的
      「静默退化」形态（取不到数据不许静默退化成 0）。

    ★ 反向注入：把 `if gw != "alipay": return {...}` 整段删掉
      ⇒ 本条转红（会真的去连支付宝/数据库，最终抛异常）。
    """
    from core.config import config
    from modules.billing import tasks as T

    prev = config.payment_gateway
    config.payment_gateway = "mock"
    try:
        result = T.reconcile_alipay_orders(lookback_days=3)  # bind=True ⇒ 直接调用即注入 self
    finally:
        config.payment_gateway = prev

    assert result.get("ran") is False, (
        f"网关是 mock 时对账任务仍报告「已执行」（{result}）—— "
        f"它会拿 mock 单号去问支付宝，把所有 paid 账单判成幽灵单并刷 CRITICAL。"
    )
    assert result.get("reason") == "not_alipay", (
        f"跳过必须带**可区分的原因**（期望 reason='not_alipay'），实际 {result} —— "
        f"只有 `ran=False` 看不出是“跳过”还是“跑了但什么都没查”。"
    )
    assert result.get("gateway") == "mock", (
        f"跳过原因的上下文里要带上当时的网关值，否则运维得去猜配置：{result}"
    )
