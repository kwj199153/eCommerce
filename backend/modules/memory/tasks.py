"""长期记忆的**每晚自动整理**（Celery 任务，第 149 轮批 C2-4）。

r141 §2.4 判定「记忆与进化」页是假页面，依据不是"没有表"，而是
**界面上承诺了「每晚自动整理更新」，而后端零实现**。C2-1 / C2-2 / C2-3 补齐了
机制、三张表、服务层与 HTTP 面，但「每晚」这两个字仍然是空的 ——
直到本文件出现，**且真的被调度器加载**。

⇒ 因此本模块的验收判据不是"函数能跑"，而是三件事同时成立：

  ① `celery_app.conf.beat_schedule` 里真的有这个条目，beat 真能算出下次运行时间；
  ② `celery inspect registered` 里查得到这两个任务名（= worker 真的注册了它们）；
  ③ 任务体里的**失败**会变成时间线上一条 `distill_failed` 记录 ——
     否则界面上的"暂无学习记录"会同时表示"没跑 / 跑了没事 / 跑失败了"三件事，
     而用户无法区分。这正是 r141 判「假页面」的同一条判据。

两个任务、两个粒度
==================
    distill_all_owners  —— beat 入口：枚举"最近活跃的人"，为每人投递一个任务
    distill_owner       —— 单个 owner 的整理（fan-out 的落点）

★ 为什么 fan-out，而不是在一个任务里 for 循环所有人
  单任务总时长 = Σ(每个人一次 LLM 调用)。本项目 `task_time_limit=1800`（30 分钟），
  100 个人 × 人均 15s 就是 25 分钟 —— 只要某天有人对话特别多，整批就会被硬杀在
  超时上，而**被杀掉的是整批**：前面已经整理好的白做（下次重新计费），后面的人
  一个都没轮到，且时间线上看不出是谁把整批拖垮的。
  fan-out 之后，超时与重试的粒度就是一个人。

★★ 跨 event loop 的连接池陷阱（本文件最关键的一处，与 aigc 同源但解法不同）
  Celery 是同步进程，任务体要 `asyncio.run(coro)`，而**每次 `asyncio.run` 都新建
  一个 event loop**；asyncpg 的连接绑定在创建它的那个 loop 上。复用模块级全局
  engine（`core.database.engine`）时，第二次任务必挂：

      RuntimeError: Task got Future attached to a different loop

  `modules/aigc_media/tasks.py` 记下了实测结论：**第一次任务成功、第二次必挂**，
  而且只在跑第二个任务时才暴露（单任务验证会"全绿"放行）。

  aigc 的解法是"每次运行新建 engine（NullPool）+ 结束 dispose"。本文件**不能照抄**：
  长期记忆的全部 DB 访问都在 `modules/memory/service.py` 与
  `modules/conversation/service.py`，它们走应用级的 `get_async_session()`。
  要在本文件注入另一个 engine，就得让那两个模块的一批公开函数都改成
  "接受外部 session" —— 那等于给同一件事造出第二条 DB 访问路径，
  正是本项目反复收敛掉的那种形态。

  ⇒ 这里用**每线程一个常驻 event loop**（`_run_sync`）：

      · loop 建好就不再关闭 ⇒ 池里的连接永远属于"创建它的那个 loop"；
      · `threads` 池会复用线程 ⇒ 同线程的后续任务复用同一个 loop，天然安全；
      · `prefork` 也不冲突：每个子进程在自己的线程里建自己的 loop。

    代价是一个进程内最多存活 N（=并发度）个 loop 与各自的连接池 ——
    夜间任务一天跑一次，这个数量级可以忽略。

  ★ 与之配套：worker 的默认池必须保持 **threads**（`worker.py` 顶部已论证 ——
    指标注册表是进程内的，prefork 下计数会落进子进程、`/metrics` 永远读到 0）。

★ LLM 客户端**每次运行新建并关闭**，不用 `get_llm()` 的单例：
  单例内部持一个 `httpx.AsyncClient`，而 AsyncClient 的连接同样绑定在
  "它第一次被使用的那个 loop / 线程"上。跨线程复用它的行为未定义；
  而这里的用量是"一晚一次、每人一次调用" —— 一次 TLS 握手的开销
  远小于它带来的不确定性。

★ 不要在本文件连 `task_success` / `task_failure` 信号
  `modules/aigc_media/tasks.py` 已经**全局**连了这两个信号（没有 `sender=` 过滤），
  重复连接会让每个任务被计两次。Celery 的信号是全局的，不按模块隔离 ——
  这是个只在"第二个任务模块出现时"才会暴露的坑。本模块的终态计数因此来自
  ① 那套全局信号（任务名作为标签）；② 下面自己的 `MEMORY_DISTILL_RUNS`
  （业务结局：ok / no_messages / skipped / failed）。
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from ai_infra.llm import DashScopeLLM
from ai_infra.memory import (
    DISTILL_BATCH_LIMIT,
    DISTILL_LOOKBACK_HOURS,
    KIND_DISTILL,
    KIND_DISTILL_FAILED,
    MAX_DISTILL_MESSAGES,
    converge,
    extract_candidates,
)
from core.logger import get_logger
from core.observability.metrics import CELERY_TASK_RESULTS, MEMORY_DISTILL_RUNS
from core.redis import celery_app
from modules.conversation import active_owner_ids, recent_messages_of_owner

from . import service
from .prompts import EXTRACT_INSTRUCTIONS

logger = get_logger("memory.tasks")

#: 任务注册名。★ 集中定义一次：这三个名字同时是 `CELERY_TASK_RESULTS` /
#: `MEMORY_DISTILL_RUNS` 的标签取值，分散写时改名只会让指标里多一条
#: 没人认识的序列 —— 不报错、不告警。
TASK_DISTILL_ALL = "memory.distill_all_owners"
TASK_DISTILL_OWNER = "memory.distill_owner"

#: 抽取温度。★ 取低值：这个任务的期望行为是"照实摘录"，不是"发挥"。
#: 高温下模型更容易把一次性任务当成长期偏好（见 `memory.prompts.EXTRACT_INSTRUCTIONS`）。
DISTILL_TEMPERATURE = 0.2


# ============================================================
# 每线程常驻 event loop（见模块 docstring 的长论证）
# ============================================================

_LOOP_LOCAL = threading.local()


def _thread_loop() -> asyncio.AbstractEventLoop:
    """本线程的常驻 loop（不存在就建，建好就不再关）。"""
    loop = getattr(_LOOP_LOCAL, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        # 一并设为"当前 loop"：部分库（httpx / anyio）在协程外会走 get_event_loop()。
        asyncio.set_event_loop(loop)
        _LOOP_LOCAL.loop = loop
    return loop


def _run_sync(coro) -> Any:
    """在**本线程常驻的** loop 上跑完一个协程。

    ★ 刻意不用 `asyncio.run()`：它每次新建并关闭一个 loop，池里的连接随即
      变成"属于一个已经死掉的 loop"（见模块 docstring 的实测结论）。
    """
    return _thread_loop().run_until_complete(coro)


async def _llm_call(prompt: str) -> str:
    """一次抽取调用。

    ★ 客户端每次新建、在 `finally` 里关闭 —— 理由见模块 docstring
      （单例客户端绑定在首次使用的 loop / 线程上）。
    """
    llm = DashScopeLLM(temperature=DISTILL_TEMPERATURE)
    try:
        response = await llm.chat(prompt, temperature=DISTILL_TEMPERATURE)
        return response.content
    finally:
        await llm.close()


# ============================================================
# 结果形状 + 指标写入点
# ============================================================


def _outcome(
    *,
    ran: bool,
    ok: bool,
    reason: str,
    status: str,
    summary: Optional[dict] = None,
    content: str = "",
    error: Optional[str] = None,
    started: Optional[float] = None,
) -> dict[str, Any]:
    """统一的返回形状，**并顺带写指标**。

    ★ 为什么把 `MEMORY_DISTILL_RUNS.inc()` 收在这一处、而不是四个 return 前
      各写一次：四处各写一次时，将来新增一种结局必然漏掉一处 ——
      而"漏掉的那一处"在 /metrics 上表现为"这个结局从未发生过"，
      比报错更难发现（`_emit_llm_metrics` 的 docstring 记过同一条教训）。

    字段语义（界面要能区分三件事，所以三者严格分开）：

        ran=False            —— 没跑（`reason` 是人话原因）
        ran=True, ok=True    —— 跑了且成功（`summary` / `content` 有值）
        ran=True, ok=False   —— 跑了但失败（`error` 有值，时间线已留痕）
    """
    MEMORY_DISTILL_RUNS.inc(status=status)
    return {
        "ran": ran,
        "ok": ok,
        "reason": reason,
        "error": error,
        "summary": summary,
        "content": content,
        "elapsed_ms": (
            int((time.perf_counter() - started) * 1000) if started is not None else 0
        ),
    }


# ============================================================
# 单人整理（HTTP「立即整理」与夜间任务共用这一个实现）
# ============================================================


async def distill_one_owner(
    owner_id: Optional[str],
    *,
    force: bool = False,
    action: str = "自动整理",
) -> dict[str, Any]:
    """整理**一个人**的长期记忆。

    `force=True` 只绕过**冷却窗口** —— 两个闸门的含义不同，见
    `service.claim_distill_run`：① 「生成对话记忆」开关关着 ⇒ 一律不跑；
    ② 距上次整理不足 `DISTILL_MANUAL_GAP_SECONDS` ⇒ 一律不跑（防连点烧钱）。
    这两条即使 `force` 也生效：force 的语义是"别管夜间调度跑过没有"，
    不是"我说了算，钱也要烧"。

    ★ 本函数**不抛异常**：抽取失败是常态（模型输出不合规 / 网络抖动），
      而在任务边界吞掉异常的前提是"它变成了一条显式记录" ——
      失败一律写 `KIND_DISTILL_FAILED` 进时间线，不是静默返回空结果。
      这一条可见性正是 r141 那条判据要求的东西。
    """
    started = time.perf_counter()

    claimed, skip_code, skip_detail = await service.claim_distill_run(
        owner_id, force=force
    )
    if not claimed:
        # ★ 跳过**不写时间线**：把"今天因为冷却跳过"也记一条，会让 30 条上限的
        #   时间线被"跳过"挤满，真正的整理结果反而被推出去（用户最想看的是后者）。
        #   跳过的可观测性由 MEMORY_DISTILL_RUNS{status="skipped"} 承担。
        # ★ `reason` 给**机器可读代码**（disabled / too_soon / cooling），
        #   人话放进 `content` —— 两者混在一个字段里，前端就只能做字符串匹配
        #   来分支，而分支是必要的：开关关着要引导去开开关，连点只需提示等待。
        logger.info(
            "[memory.tasks] 跳过整理 owner={} 原因={} 说明={}",
            owner_id,
            skip_code,
            skip_detail,
        )
        return _outcome(
            ran=False,
            ok=True,
            reason=skip_code,
            status="skipped",
            content=skip_detail,
            started=started,
        )

    oid = str(owner_id)

    # 1) 读：现有条目（去重与配额都要它）+ 窗口内的对话消息
    entries = await service.load_entries(oid)
    since = datetime.utcnow() - timedelta(hours=DISTILL_LOOKBACK_HOURS)
    messages = await recent_messages_of_owner(
        oid, since=since, limit=MAX_DISTILL_MESSAGES
    )

    # 2) 没有对话 ⇒ 仍然留一条"跑过了但没事"的记录。
    #    ★ 这一条不能省：没有它，用户看到"暂无学习记录"时无法判断
    #      "昨晚跑了但确实没内容"与"昨晚压根没跑"。
    if not messages:
        content = (
            f"{action}：最近 {DISTILL_LOOKBACK_HOURS} 小时内没有对话，"
            f"没有可整理的内容（当前共 {len(entries)} 条记忆）"
        )
        await service.record_distill_outcome(oid, KIND_DISTILL, content)
        logger.info("[memory.tasks] 无对话可整理 owner={} 现有={} 条", oid, len(entries))
        return _outcome(
            ran=True,
            ok=True,
            reason="no_messages",
            status="no_messages",
            content=content,
            started=started,
        )

    # 3) 抽取（★ 唯一烧钱的一步）
    try:
        candidates = await extract_candidates(
            messages,
            llm_call=_llm_call,
            # ★ 提示词来自**业务层**（本包 prompts.py）。机制层只负责把它拼进去。
            instructions=EXTRACT_INSTRUCTIONS,
            existing=entries,
        )
    except Exception as exc:  # noqa: BLE001 - 任务边界：失败必须变成一条显式记录
        error = f"{type(exc).__name__}: {exc}"
        await service.record_distill_outcome(
            oid,
            KIND_DISTILL_FAILED,
            f"{action}失败：{error}",
            {"error": error, "stage": "extract", "messages": len(messages)},
        )
        logger.exception("[memory.tasks] 整理失败 owner={}", oid)
        return _outcome(
            ran=True,
            ok=False,
            reason="distill_failed",
            status="failed",
            error=error,
            started=started,
        )

    # 4) 收敛 + 落库。
    #    ★ 与「保存」不同的是：这里的收敛**允许静默裁剪**（配额/上限），
    #      因为它是自动整理 —— 用户能在界面上看到结果（`distill.converge` 的论证）。
    try:
        merged = converge(list(entries) + list(candidates))
        outcome = await service.apply_distilled(oid, merged, action=action)
    except Exception as exc:  # noqa: BLE001 - 落库失败也要留痕
        error = f"{type(exc).__name__}: {exc}"
        await service.record_distill_outcome(
            oid,
            KIND_DISTILL_FAILED,
            f"{action}失败（写入阶段）：{error}",
            {"error": error, "stage": "persist"},
        )
        logger.exception("[memory.tasks] 整理落库失败 owner={}", oid)
        return _outcome(
            ran=True,
            ok=False,
            reason="persist_failed",
            status="failed",
            error=error,
            started=started,
        )

    summary = outcome["summary"]
    logger.info(
        "[memory.tasks] 整理完成 owner={} 抽取={} 条 新增={} 移除={} 现在={} 条 耗时={}ms",
        oid,
        len(candidates),
        summary.get("added"),
        summary.get("removed"),
        summary.get("after"),
        int((time.perf_counter() - started) * 1000),
    )
    return _outcome(
        ran=True,
        ok=True,
        reason="ok",
        status="ok",
        summary=summary,
        content=outcome["content"],
        started=started,
    )


# ============================================================
# Celery 任务体
# ============================================================


@celery_app.task(bind=True, name=TASK_DISTILL_OWNER)
def distill_owner(self, owner_id: str, force: bool = False) -> dict[str, Any]:
    """单个人整理的 Celery 入口（同步函数，内部桥到异步内核）。"""
    try:
        return _run_sync(distill_one_owner(owner_id, force=force))
    except Exception:
        # ★ 走到这里说明**连记账都没成功**（claim 之前就炸了，例如 DB 不可达）。
        #   那是基础设施问题，不是"这个人的数据有问题" —— 单独标一个状态，
        #   否则它和"抽取失败"在监控上长得一模一样。
        logger.exception("[memory.tasks] 整理任务无法启动 owner={}", owner_id)
        CELERY_TASK_RESULTS.inc(task=TASK_DISTILL_OWNER, status="infra_failure")
        raise


@celery_app.task(bind=True, name=TASK_DISTILL_ALL)
def distill_all_owners(self, lookback_hours: Optional[int] = None) -> dict[str, Any]:
    """beat 入口：枚举"最近活跃的人"，为每人投递一个整理任务。

    ★ 本任务**不整理任何人**，只做 fan-out。两个刻意的"不做"：

      · 不判冷却 —— 那是 `distill_owner` 自己的事。放在这里的话，
        一个人的档案异常会让整晚的调度整体失败；
      · 不写时间线 —— 写给谁？它是所有人的调度器，不属于任何一个 owner。

    ★ 返回 `dispatched`（投递数）而**不是"成功数"**：投递成功 ≠ 整理成功。
      把两者合成一个数字，会让"队列里堆了 100 个任务没人消费"
      和"100 个人都整理完了"看起来一模一样。
    """
    try:
        return _run_sync(_dispatch_all(lookback_hours))
    except Exception:
        logger.exception("[memory.tasks] 夜间调度失败")
        CELERY_TASK_RESULTS.inc(task=TASK_DISTILL_ALL, status="infra_failure")
        raise


async def _dispatch_all(lookback_hours: Optional[int]) -> dict[str, Any]:
    """枚举活跃 owner 并逐个投递。"""
    hours = int(lookback_hours or DISTILL_LOOKBACK_HOURS)
    since = datetime.utcnow() - timedelta(hours=hours)
    owners = await active_owner_ids(since=since, limit=DISTILL_BATCH_LIMIT)

    dispatched: list[str] = []
    failed: list[str] = []
    for oid in owners:
        try:
            distill_owner.delay(oid)
            dispatched.append(oid)
        except Exception:  # noqa: BLE001 - 一个人投不出去不该拖垮整晚
            failed.append(oid)
            logger.exception("[memory.tasks] 投递整理任务失败 owner={}", oid)

    # ★ 一个人都没投出去、而候选却有 ⇒ 显式失败。
    #   报"调度完成、投递 0 个"是最糟的形态：调度器看起来正常、时间线一条记录都没有，
    #   而真实原因是 Broker 不可达。宁可让任务红着，也不要让"什么都没发生"看起来像成功。
    if owners and not dispatched:
        raise RuntimeError(
            f"窗口 {hours}h 内有 {len(owners)} 位活跃用户，但一个整理任务都没投出去"
            f"（Broker 不可达？）—— 已显式失败，以免「调度成功但整晚什么都没发生」"
        )

    logger.info(
        "[memory.tasks] 夜间调度：窗口={}h 活跃={} 人 已投递={} 投递失败={}",
        hours,
        len(owners),
        len(dispatched),
        len(failed),
    )
    return {
        "window_hours": hours,
        "owners": len(owners),
        "dispatched": len(dispatched),
        "dispatch_failed": len(failed),
    }


__all__ = [
    "DISTILL_TEMPERATURE",
    "TASK_DISTILL_ALL",
    "TASK_DISTILL_OWNER",
    "distill_all_owners",
    "distill_one_owner",
    "distill_owner",
]
