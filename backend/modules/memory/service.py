"""长期记忆服务层（第 149 轮 批 C2-3）。

一句话分工
==========
    `ai_infra/memory/`          机制：口径 / 数据形态 / 算法（零 IO、零 DB）
    `modules/memory/db_model`   表结构（三张表，键是 `owner_id`）
    **本文件**                   把两者接起来，并守住下面四条不变量
    `modules/memory/router`     HTTP 面（只做入参/出参形状与身份提取）
    `modules/memory/tasks`      每晚自动整理（C2-4）

★★ 为什么这一层不是「把 CRUD 包一层」
====================================
本项目已经真实发生过一次「有表、有页面、功能却是假的」的事件
（r141 §2.4：`MemoryEvolution.vue` 36 行硬编码假记忆 + 7 条假日志 + 保存零 API 调用）。
表与页面都能让人以为功能存在。真正决定「它是不是真的」的是四条不变量，
而它们各自都必须**只在一处**被判、且必须能被测试**直接打穿**：

 1. **归属**：`owner_id` 是**首要且必填**参数（签名即门禁）。
    缺它一律拒绝 —— 不是「回退到匿名档案」。后者会造出**无主记忆**：
       · 任何人登录后都读不到它（却又一直躺在库里）；
       · 每晚任务会一直为它花钱调模型。
 2. **上限**：超限**拒绝并说清是第几条超了**（`validate_entries` 的人话清单），
    绝不静默截断。用户手写的东西被悄悄改掉是不可接受的 ——
    这正是 `converge` 与 `validate_entries` 分成两个函数的原因。
 3. **身份稳定性**：保存是「整批替换」（用户提交的就是**全集**），
    但已存在条目的 `id` / `created_at` / `source` 必须**按去重键原样继承**。
    否则用户在编辑器里改一个错字再保存，会把 AI 归纳的条目一次性
    「升级」成手写来源，权重体系（`limits.SOURCE_WEIGHTS`）当场失真，
    此后「满了先挤掉谁」就再也算不对了。
 4. **留痕**：每次写入都落一条 `memory_logs`，且 `kind` 过
    `is_known_log_kind()` 守卫。时间线是「它真的跑过」的唯一证据 ——
    r141 判「假页面」用的就是这条判据。

★ 归属为什么不在本层判「是谁」，只判「有没有」
---------------------------------------------
「是谁」由 `core/auth` 回答（HTTP 面用 `require_authenticated_user`）。
本层只要求调用方**已经**回答了这个问题 —— 因为本模块的调用方不止 HTTP：
每晚的 Celery 任务与 system prompt 注入都不经路由。把「有没有身份」
收在本层一处，三处调用方就共用同一条判定，而不是各写一份。

★ 为什么读不建行（`snapshot` 是只读的）
---------------------------------------
档案表（`memory_profiles`）必须能独立存在（见 `db_model` 的论证），
但「没有行」这个状态**只在本文件里被解释一次**（`DEFAULT_ENABLED`）。
让 GET 顺手建行有两个坏处：刷新一次多一点数据、并发下撞主键。
行由**第一次写入**建（`_ensure_profile`）。

★ 时间一律是 naive UTC，输出时补 `Z`
------------------------------------
库里与同仓 `conversations` / `agent_session_state` 一致，存 naive UTC。
对外输出时补上 `Z`：不补的话 JS 的 `new Date("2026-09-18T13:40:00")`
会按**本地时区**解析（中国 UTC+8 ⇒ 显示的时间整体偏移），
而学习时间线恰好是用户最容易一眼看出错的地方。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_infra.memory import (
    ALL_SECTIONS,
    DISTILL_COOLDOWN_HOURS,
    DISTILL_MANUAL_GAP_SECONDS,
    DISTILL_PERIOD_HOURS,
    FAILURE_LOG_KINDS,
    KIND_DISTILL,
    KIND_DISTILL_FAILED,
    KIND_IMPORT,
    KIND_MANUAL,
    KIND_RESET,
    MAX_ENTRIES,
    MAX_ENTRY_CHARS,
    MAX_LOGS,
    MAX_LOG_CHARS,
    SECTION_QUOTA,
    SOURCE_DISTILL,
    SOURCE_IMPORT,
    SOURCE_MANUAL,
    MemoryEntry,
    converge,
    diff_summary,
    format_log_content,
    is_known_log_kind,
    parse_markdown,
    render_markdown,
    truncate_text,
    validate_entries,
)
from core.database import get_async_session

from .db_model import MemoryEntryRecord, MemoryLogRecord, MemoryProfileRecord

logger = logging.getLogger(__name__)

#: 档案不存在时 `enabled` 的取值（**唯一真源**）。
#:
#: ★ 为什么不"让每个读取方各判一次『没有行算开还是算关』"：
#:   那会变成三份实现（HTTP 读 / 每晚任务 / prompt 注入），且三份迟早不一致。
#:   所有读取都经 `snapshot()`，默认值只在这里出现一次。
DEFAULT_ENABLED = True

#: 用户侧**可以自报**的来源。★ 刻意不含 `SOURCE_DISTILL`：
#:   `distill` 的权重是 1（AI 的猜测），手写/导入是 10（用户的明确意图）。
#:   若客户端能自称 `distill`，它等于自己把自己的内容标成"可以先被挤掉" ——
#:   而用户完全看不出这件事发生过。`distill` 由每晚任务独占写入。
USER_SOURCES: tuple[str, ...] = (SOURCE_MANUAL, SOURCE_IMPORT)

#: 用户来源 → 时间线记录类型。
#:
#: ★ 必须写成显式映射，不能图省事写 `kind = source`：两者今天**恰好**同名字符串，
#:   但那是巧合。哪天有人把 `KIND_MANUAL` 改成 `"edit"`，`kind = source` 会
#:   静默继续工作（写成 `"manual"`，仍是已登记类型），而那条改动本意没生效。
_SOURCE_LOG_KIND: dict[str, str] = {
    SOURCE_MANUAL: KIND_MANUAL,
    SOURCE_IMPORT: KIND_IMPORT,
}

#: 无身份时的拒绝文案。★ 要说清"是记忆功能要登录"并给出**动作**，
#: 否则用户不知道自己卡在哪一步、该做什么。
NO_IDENTITY_DETAIL = (
    "长期记忆按账号归属，需要先登录后再使用：匿名会话没有可归属的对象。"
)


# ============================================================================
# 基础工具
# ============================================================================


def _require_owner(owner_id: Optional[str]) -> str:
    """归属**门禁**：没有身份一律拒绝（fail-closed）。

    ★ 为什么在服务层判、而不是只在路由判：本模块的调用方不止 HTTP ——
      每晚的 Celery 任务与 system prompt 注入都不经路由。只在路由判的话，
      任务侧会把 `owner_id=None` 当成一个"合法的空值"写下去，
      落出一份**无主记忆**（见模块 docstring）。

    ★ 为什么是 401 而不是 400：这不是"参数写错了"，而是"不知道你是谁"，
      文案要指向**登录**这个动作。
    """
    oid = str(owner_id or "").strip()
    if not oid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=NO_IDENTITY_DETAIL,
        )
    return oid


def _iso(value: Optional[datetime]) -> Optional[str]:
    """naive UTC datetime → 带 `Z` 的 ISO 字符串（理由见模块 docstring）。"""
    if not isinstance(value, datetime):
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _new_entry_id() -> str:
    return f"mem_{uuid.uuid4().hex[:16]}"


def _new_log_id() -> str:
    return f"mlog_{uuid.uuid4().hex[:16]}"


def limits_snapshot() -> dict:
    """把机制层的上限**原样**交给前端。

    ★ 为什么由后端提供、而不是前端自己写一组常量：上限是**后端判据**。
      前端写一份就是第二份实现 —— 改了后端忘改前端，界面上的"60 条上限"
      与实际开始 400 的阈值就对不上了，而没有任何东西会红。
    """
    return {
        "max_entries": MAX_ENTRIES,
        "max_entry_chars": MAX_ENTRY_CHARS,
        "max_logs": MAX_LOGS,
        "sections": list(ALL_SECTIONS),
        "section_quota": dict(SECTION_QUOTA),
    }


#: 读条目时**只取列**，不取 ORM 实体。
#:
#: ★★ 这不是微优化，而是为了避开一个真实的坑：`save_memory` 在一个事务里
#:   「先全删、再按同一个主键插回」。若删除前把行加载成了 ORM 实体，
#:   会话的 identity map 里就留着"这些主键的对象"；随后 `add_all()` 新实例
#:   复用同样的主键，SQLAlchemy 会在 flush 时判定「新实例与持久实例冲突」。
#:   只取列（返回 Row，不进 identity map）就没有这个问题。
_ENTRY_COLS = (
    MemoryEntryRecord.id,
    MemoryEntryRecord.section,
    MemoryEntryRecord.content,
    MemoryEntryRecord.dedup_key,
    MemoryEntryRecord.source,
    MemoryEntryRecord.ordinal,
    MemoryEntryRecord.created_at,
    MemoryEntryRecord.updated_at,
)


def _to_entry(row) -> MemoryEntry:
    """数据库行 → 机制层条目对象（`ordinal` 不进 `MemoryEntry`：顺序是列表的属性）。"""
    return MemoryEntry(
        content=row.content,
        section=row.section,
        source=row.source,
        id=row.id,
        updated_at=_iso(row.updated_at),
    )


async def _read_entry_rows(session: AsyncSession, owner_id: str) -> list:
    """读该 owner 的全部条目行，**按 `ordinal` 升序**（= 用户看到的顺序）。"""
    rows = await session.execute(
        select(*_ENTRY_COLS)
        .where(MemoryEntryRecord.owner_id == owner_id)
        .order_by(MemoryEntryRecord.ordinal, MemoryEntryRecord.id)
    )
    return list(rows.all())


async def _ensure_profile(
    session: AsyncSession,
    owner_id: str,
    *,
    enabled: Optional[bool] = None,
) -> None:
    """确保档案行存在；`enabled` 非 None 时一并写入。

    ★ 用 `INSERT ... ON CONFLICT` 而不是「先 SELECT 再 INSERT」：
      后者在两个并发写（如用户连点两次开关）下会撞主键 —— 而那种失败
      表现为一次 500，用户看到的是"开关点了没反应"。
    ★ 冲突目标用 `index_elements=["owner_id"]` 而不是 `constraint=<名字>`：
      `owner_id` 是**主键**，其隐式索引名是方言生成的（`memory_profiles_pkey`）。
      把生成出来的名字写进代码，就是 `state_store.py` 警告过的那种"名字漂移"
      （改名时漏一处不报错，只会在第一次落盘时炸）。这里根本没有名字可漂。
    """
    now = datetime.utcnow()
    stmt = pg_insert(MemoryProfileRecord).values(
        owner_id=owner_id,
        enabled=DEFAULT_ENABLED if enabled is None else bool(enabled),
        created_at=now,
        updated_at=now,
    )
    set_: dict = {"updated_at": now}
    if enabled is not None:
        set_["enabled"] = bool(enabled)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=["owner_id"], set_=set_)
    )


async def _write_log(
    session: AsyncSession,
    owner_id: str,
    kind: str,
    content: str,
    detail: Optional[dict] = None,
) -> None:
    """落一条时间线记录，并把该 owner 的记录裁到 `MAX_LOGS` 条。

    ★ `kind` 必须过写入守卫：落一条未登记的 `kind` 进库，等于在时间线上
      加一条永远渲染不出图标、也永远筛不出来的孤儿记录。宁可调用方当场
      拿到错误，也不要让它在表里沉默地积存。

    ★ 裁到 `MAX_LOGS` 是**这张表的唯一回收机制**。它是"只增不改"的流水，
      若没有上限，"只增"就等于无限增长 —— 而这是每天自动跑出来的数据，
      增长速度与用户行为无关。裁的是**最旧的**（`created_at` 升序的前几条）。
    """
    if not is_known_log_kind(kind):
        raise ValueError(
            f"未登记的记忆记录类型：{kind!r}"
            f"（真源见 ai_infra.memory.limits.LOG_KINDS）"
        )
    session.add(
        MemoryLogRecord(
            id=_new_log_id(),
            owner_id=owner_id,
            kind=kind,
            content=truncate_text(content, MAX_LOG_CHARS),
            detail=detail or None,
        )
    )
    # 先 flush 让新记录进到查询可见的范围，否则"最新的 MAX_LOGS 条"里不含它，
    # 会把它自己算成多余的而删掉（或反过来留下 MAX_LOGS+1 条）。
    await session.flush()
    stale = list(
        (
            await session.execute(
                select(MemoryLogRecord.id)
                .where(MemoryLogRecord.owner_id == owner_id)
                .order_by(
                    MemoryLogRecord.created_at.desc(), MemoryLogRecord.id.desc()
                )
                .offset(MAX_LOGS)
            )
        )
        .scalars()
        .all()
    )
    if stale:
        await session.execute(
            delete(MemoryLogRecord).where(MemoryLogRecord.id.in_(stale))
        )


# ============================================================================
# 读
# ============================================================================


async def load_entries(owner_id: Optional[str]) -> list[MemoryEntry]:
    """读该 owner 的全部条目（顺序 = 展示顺序）。

    ★ 这是本模块对**其它模块**的读原语：system prompt 注入（读口）与
      每晚任务都从它进。有了它，"记忆长什么样"只有一处实现。
    """
    oid = _require_owner(owner_id)
    async with get_async_session() as session:
        return [_to_entry(r) for r in await _read_entry_rows(session, oid)]


@dataclass(frozen=True)
class MemoryInjection:
    """读口（system prompt 注入）的一次读结果。

    ★ 为什么不实现 `__bool__`：`if got:` 会在「开关关了」与「有身份但一条都没有」
      两种情况下都为假 —— 而排查时最需要区分的恰恰是这两者。调用方请显式读
      `.injectable` 与 `.entries`。
    """

    #: 本次是否允许把记忆注入 system prompt。
    injectable: bool
    #: 该 owner 的全部条目（按展示顺序）。`injectable=False` 时恒为空列表。
    entries: list


async def load_injectable_entries(owner_id: Optional[str]) -> MemoryInjection:
    """读口专用：一次给出「这次能不能注入 + 该 owner 的条目」。

    与 `load_entries` 的三点差异 —— **都是有意的，不是口径不一致**：

      1. **不抛 401**。`_require_owner` 的 fail-closed 是给 HTTP 面用的：
         用户点「保存」必须知道"为什么没存上"，所以文案要指向登录。
         读口跑在**图的节点里**，一次匿名请求（或 Celery 里的任务）走到这里
         抛异常 ⇒ **整轮对话挂掉**。而"这个人没有记忆"是完全正常的状态。
      2. **看开关**。`memory_profiles.enabled=false` ⇒ 不注入。
         这正是本包 docstring 里那句「关掉之后**任务跳过**、**注入块为空**」的
         后半句（前半句在 `tasks.distill_one_owner`）。
         ★ 若读口只调 `load_entries`，用户关掉开关后记忆依然每轮都在 prompt 里
           —— 那个开关就成了装饰品，而界面上显示的是「已关闭」。
      3. **开关与条目在同一个 session 里读出来**。分两次读会留一个窗口：
         用户正好在两步之间关掉开关 ⇒ 已经关掉了却仍然注入了这一次。

    ★ `injectable=False` 覆盖三种来路：无身份 / 开关关闭 / 档案不存在且
      `DEFAULT_ENABLED` 为假。对「注不注入」这一问题三者**同解**。
      将来若需要区分，请在这里加一个显式的 `reason` 字段，
      而不是让调用方去猜是哪种情况。
    """
    oid = str(owner_id or "").strip()
    if not oid:
        return MemoryInjection(injectable=False, entries=[])

    async with get_async_session() as session:
        profile = await session.get(MemoryProfileRecord, oid)
        enabled = DEFAULT_ENABLED if profile is None else bool(profile.enabled)
        if not enabled:
            return MemoryInjection(injectable=False, entries=[])
        rows = await _read_entry_rows(session, oid)

    return MemoryInjection(injectable=True, entries=[_to_entry(r) for r in rows])


async def list_logs(
    owner_id: Optional[str], *, limit: int = MAX_LOGS
) -> list[dict]:
    """读学习时间线（**倒序**，最新在前）。

    ★ 上限取 `min(limit, MAX_LOGS)`：库里本来最多只有 `MAX_LOGS` 条，
      让调用方能要来更多只是让"上限"这个数字看起来可协商。
    """
    oid = _require_owner(owner_id)
    size = max(1, min(int(limit or MAX_LOGS), MAX_LOGS))
    async with get_async_session() as session:
        rows = await session.execute(
            select(
                MemoryLogRecord.id,
                MemoryLogRecord.kind,
                MemoryLogRecord.content,
                MemoryLogRecord.detail,
                MemoryLogRecord.created_at,
            )
            .where(MemoryLogRecord.owner_id == oid)
            .order_by(MemoryLogRecord.created_at.desc(), MemoryLogRecord.id.desc())
            .limit(size)
        )
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "content": r.content,
                "detail": r.detail,
                "created_at": _iso(r.created_at),
                # ★ "这条是坏消息吗"的判据来自**后端口径**，不是前端再列一遍 kind
                #   名单 —— 后端新增一种失败类型时，前端那份名单不会跟着变，
                #   结果是一条失败记录被渲染成正常记录（比不渲染更糟）。
                "is_failure": r.kind in FAILURE_LOG_KINDS,
            }
            for r in rows.all()
        ]


async def snapshot(owner_id: Optional[str]) -> dict:
    """本页需要的全部状态，**一次给全**（抽屉打开就是这一发）。

    ★ 为什么把"读"收成一个快照函数：保存 / 重置之后前端要拿到**新状态**。
      若那些写端点各自手拼一份返回值，就会出现「保存后界面与重新打开不一致」
      —— 而两边都是"后端返回的"，谁也没法判断哪个才对。写端点一律
      `return await snapshot(...)`，同一个实现。
    """
    oid = _require_owner(owner_id)
    async with get_async_session() as session:
        profile = await session.get(MemoryProfileRecord, oid)
        rows = await _read_entry_rows(session, oid)

    entries = [_to_entry(r) for r in rows]
    newest = max((r.updated_at for r in rows), default=None)
    return {
        "profile": {
            "enabled": DEFAULT_ENABLED if profile is None else bool(profile.enabled),
            "last_distilled_at": _iso(
                profile.last_distilled_at if profile is not None else None
            ),
        },
        "markdown": render_markdown(entries),
        "entries": [e.as_dict() for e in entries],
        "entry_count": len(entries),
        "updated_at": _iso(newest),
        "limits": limits_snapshot(),
    }


# ============================================================================
# 写
# ============================================================================


async def save_memory(
    owner_id: Optional[str],
    markdown: str,
    *,
    source: str = SOURCE_MANUAL,
) -> dict:
    """提交**整份** markdown（编辑器里看到的就是全集）并整批替换。

    顺序与理由（每一步都不能挪位）：

      1. **来源校验**：只接受用户侧来源（`USER_SOURCES`）。
      2. `parse_markdown` 拆条目（**只做形状**，不裁剪）。
      3. `validate_entries` 校验上限 ⇒ 有问题 **400 + 人话清单**。
         ★ 必须排在 `converge` **之前**：`converge` 会静默去掉重复、截断超长、
           裁掉超量 —— 那三件事对"每晚自动整理"是对的，对"用户点保存"是错的。
           先校验之后，`converge` 只剩下第 2 步（合并重复）还会真的生效，
           而那一步的结果**不改变任何一条内容**（合并不改写文字）。
      4. `converge` 收敛。
      5. 整批替换（一个事务），并按去重键**继承** `id` / `created_at` / `source`。
      6. 落一条时间线记录。
    """
    oid = _require_owner(owner_id)
    src = str(source or SOURCE_MANUAL).strip().lower()
    if src not in USER_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"source 只能是 {' / '.join(USER_SOURCES)}；"
                f"`{SOURCE_DISTILL}` 由每晚自动整理任务独占写入，不接受客户端自报"
            ),
        )

    submitted = parse_markdown(markdown, source=src)

    problems = validate_entries(submitted)
    if problems:
        # ★ 拼接成一句给用户看的中文串（每条问题都已经自带"第 N 条 / 哪个分节"）。
        #   不用 list 是因为前端普遍把 `detail` 直接塞进 message 组件，
        #   拿到数组会显示成一串方括号。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="；".join(problems),
        )

    converged = converge(submitted)

    # ★ 不变量自查：校验通过之后，收敛**不应该**再删掉任何一条。
    #   若这里对不上，说明"校验用的上限"与"收敛用的上限"不是同一套 ——
    #   而后果是**用户的内容被静默丢弃**。宁可 500（会有人来查），
    #   也不要静默丢数据（没有人会知道）。
    unique_keys = {e.key for e in submitted}
    if len(converged) != len(unique_keys):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"记忆收敛前后条数不一致（唯一 {len(unique_keys)} 条 → "
                f"收敛后 {len(converged)} 条），已中止保存以免静默丢弃内容"
            ),
        )

    async with get_async_session() as session:
        rows = await _read_entry_rows(session, oid)
        before = [_to_entry(r) for r in rows]
        existing = {r.dedup_key: r for r in rows}

        # 全删全插（见 `_ENTRY_COLS` 的说明：上面只取了列，identity map 是干净的）。
        # 一个事务内先删后插 ⇒ 不存在唯一约束 `(owner_id, dedup_key)` 的中间冲突，
        # 也不存在"删了一半"的残局。
        await session.execute(
            delete(MemoryEntryRecord).where(MemoryEntryRecord.owner_id == oid)
        )

        now = datetime.utcnow()
        order = 0
        for entry in converged:
            old = existing.get(entry.key)
            session.add(
                MemoryEntryRecord(
                    # ★ 位置即身份：能按去重键对上的条目沿用原主键，
                    #   于是"这条记忆"跨保存是可指的（日志样本、前端 diff 都靠它）。
                    id=old.id if old is not None else _new_entry_id(),
                    owner_id=oid,
                    section=entry.section,
                    content=entry.content,
                    dedup_key=entry.key,
                    # ★★ 来源继承（本函数最关键的一行）：编辑器里没有"来源"
                    #    这个字段，若一律写成请求的 `source`，用户改一个错字
                    #    就会把 AI 归纳的条目全部升级成手写来源 ——
                    #    `SOURCE_WEIGHTS` 决定"满了先挤掉谁"，权重一失真，
                    #    后续的配额裁剪就再也算不对，且没有任何报错。
                    source=old.source if old is not None else src,
                    ordinal=order,
                    # 创建时间也继承：不继承的话每条记忆的"创建时间"都会
                    # 变成最后一次保存的时间，那是个看得见的假信息。
                    created_at=old.created_at if old is not None else now,
                    updated_at=now,
                )
            )
            order += 1

        await session.flush()

        summary = diff_summary(before, converged)
        await _write_log(
            session,
            oid,
            _SOURCE_LOG_KIND[src],
            format_log_content(summary, action="保存记忆"),
            summary,
        )
        await _ensure_profile(session, oid)

    return await snapshot(oid)


async def reset_memory(owner_id: Optional[str]) -> dict:
    """清空全部条目，**保留开关本身**。

    ★ 为什么保留开关：用户点"重置"的意思是「忘掉我记过的东西」，
      不是「以后别再记了」。把开关一并关掉是**替他做了一个他没做的决定**，
      而他只会发现"重置之后再也不学习了"，且不知道怎么恢复。
      （要停止学习请用开关 —— 那是它存在的意义。）
    """
    oid = _require_owner(owner_id)
    async with get_async_session() as session:
        rows = await _read_entry_rows(session, oid)
        removed = len(rows)
        await session.execute(
            delete(MemoryEntryRecord).where(MemoryEntryRecord.owner_id == oid)
        )
        await _write_log(
            session,
            oid,
            KIND_RESET,
            f"已重置：清空原有 {removed} 条记忆（「生成对话记忆」开关保持原状）",
        )
        await _ensure_profile(session, oid)
    logger.info("长期记忆已重置 owner=%s 清空 %d 条", oid, removed)
    return await snapshot(oid)


async def set_enabled(owner_id: Optional[str], enabled: bool) -> dict:
    """写「生成对话记忆」总开关，返回**权威**状态。

    ★ 返回值必须是库里的真值而不是入参：前端拿到之后要回写本地开关 ——
      否则一次失败的写入会留下一个"看起来打开了、其实没打开"的界面状态，
      而用户唯一的线索是"为什么它不记我的偏好"。
    """
    oid = _require_owner(owner_id)
    async with get_async_session() as session:
        await _ensure_profile(session, oid, enabled=bool(enabled))
    return {"profile": (await snapshot(oid))["profile"]}


# ============================================================================
# 夜间自动整理（C2-4）：闸门 / 落库 / 留痕
# ============================================================================
#
# ★ 为什么这三件事住在服务层、而不是写进 `modules/memory/tasks.py`：
#   它们全部要写 `memory_profiles` / `memory_entries` / `memory_logs`，
#   而"谁能写这三张表、按什么纪律写"必须**只有一处**（见模块 docstring 的不变量）。
#   放进任务模块的话，Celery 就有了绕开服务层的 DB 通道 ——
#   于是"归属 / 上限 / 来源继承"在任务路径上**没人守**，
#   而下一次改动只会记得改服务层那一份。


async def claim_distill_run(
    owner_id: Optional[str], *, force: bool = False
) -> tuple[bool, str, str]:
    """决定"这次整理该不该跑"；该跑则**先占用**（写 `last_distilled_at`）。

    返回 `(是否占用, 原因代码, 人话说明)`。原因代码是**机器可读**的
    （`disabled` / `too_soon` / `cooling`），人话给界面直接展示 ——
    两者混在同一个字段里，前端就只能做字符串匹配来分支，
    而分支是必要的：开关关着要引导去打开开关，连点只需提示等待。

    三道闸门，顺序即优先级：

      ① 「生成对话记忆」开关关着 ⇒ 一律不跑。
         ★ `force` **不能**绕过它：手动点"立即整理"做的也是"从我的对话里
         提取"，正是那个开关在管的事。绕过它等于替用户同意一件他明确关掉的事。
      ② 距上次**发起**不足 `DISTILL_MANUAL_GAP_SECONDS` ⇒ 一律不跑（防连点）。
         ★ `force` 也不能绕过：force 的语义是"别管今晚跑过没有"，
         不是"钱也要烧"。这一道管的是"同一个人一分钟内点 20 次"。
      ③ 距上次发起不足 `DISTILL_COOLDOWN_HOURS` ⇒ 只有 `force=True` 才跑。

    ★★ 为什么"先占用"（写时间戳）而不是"跑完了再写"：
      `task_acks_late=True` 下 worker 崩溃会**重投递**同一个任务。
      时间戳若在成功之后才写，崩溃那一刻的重投递会立刻再跑一次 ——
      同一个人当晚被整理两次、LLM 被调用两次。先占用后执行时，最坏情况是
      "这一晚想跑但没跑成"（次日冷却到期会重试）—— 代价方向是**少花钱**，
      而不是重复花钱。这与 `db_model.last_distilled_at` 的注释口径一致
      （"成功/失败都写"）。
    """
    oid = _require_owner(owner_id)
    now = datetime.utcnow()
    async with get_async_session() as session:
        profile = await session.get(MemoryProfileRecord, oid)
        if profile is not None and not bool(profile.enabled):
            return False, "disabled", "「生成对话记忆」开关是关闭状态，先打开它再整理"

        last = profile.last_distilled_at if profile is not None else None
        if last is not None:
            gap = (now - last).total_seconds()
            if gap < DISTILL_MANUAL_GAP_SECONDS:
                wait = int(DISTILL_MANUAL_GAP_SECONDS - gap) + 1
                return False, "too_soon", f"距上次整理只有 {int(gap)} 秒，请 {wait} 秒后再试"
            if not force and gap < DISTILL_COOLDOWN_HOURS * 3600:
                return False, "cooling", (
                    f"距上次整理 {gap / 3600:.1f} 小时；"
                    f"夜间整理每 {DISTILL_PERIOD_HOURS} 小时一次"
                    f"（冷却 {DISTILL_COOLDOWN_HOURS} 小时），本次跳过"
                )

        # ★ `_ensure_profile` 必须排在 UPDATE **之前**：库里没有这一行时，
        #   直接 UPDATE 会影响 0 行 —— 而"0 行"不会报错，于是**占用失败**，
        #   冷却闸门随即失效（下一次还会跑、还会花钱）。
        await _ensure_profile(session, oid)
        await session.execute(
            update(MemoryProfileRecord)
            .where(MemoryProfileRecord.owner_id == oid)
            .values(last_distilled_at=now)
        )
    return True, "", ""


async def apply_distilled(
    owner_id: Optional[str],
    entries: Sequence[MemoryEntry],
    *,
    action: str = "自动整理",
) -> dict:
    """把整理结果整批写回（★ `source=distill` 的**唯一**写入点）。

    与 `save_memory` 共用同一套写入纪律（整批替换、按去重键继承
    `id` / `created_at` / `source`、`ordinal` 按提交顺序），三处**有意**不同：

      · 不做 `validate_entries`：条目来自 `converge`，已经在上限之内；
      · 新条目的默认来源是 `SOURCE_DISTILL`（权重 1），而不是 `manual`；
      · 会写一条 `KIND_DISTILL` 时间线记录 —— 这正是"那晚它真的跑过"的证据。

    ★★ 来源继承在这里比在 `save_memory` 里更关键：整理会把**用户手写**的条目
      原样读进来再写回去。若一律写成 `distill`，用户亲手写的偏好会在一次
      夜间整理之后集体降级成"AI 猜测"（权重 10 → 1），此后配额裁剪
      会把它们**优先牺牲掉** —— 而用户只会某天发现"我明明写过的没了"。
    """
    oid = _require_owner(owner_id)
    converged = converge(entries)

    async with get_async_session() as session:
        rows = await _read_entry_rows(session, oid)
        before = [_to_entry(r) for r in rows]
        existing = {r.dedup_key: r for r in rows}

        # 与 `save_memory` 同理：上面只取列 ⇒ identity map 干净 ⇒
        # 同一事务内"先全删再按同一主键插回"不会触发实例冲突。
        await session.execute(
            delete(MemoryEntryRecord).where(MemoryEntryRecord.owner_id == oid)
        )

        now = datetime.utcnow()
        order = 0
        for entry in converged:
            old = existing.get(entry.key)
            session.add(
                MemoryEntryRecord(
                    id=old.id if old is not None else _new_entry_id(),
                    owner_id=oid,
                    section=entry.section,
                    content=entry.content,
                    dedup_key=entry.key,
                    source=old.source if old is not None else SOURCE_DISTILL,
                    ordinal=order,
                    created_at=old.created_at if old is not None else now,
                    updated_at=now,
                )
            )
            order += 1

        await session.flush()

        summary = diff_summary(before, converged)
        content = format_log_content(summary, action=action)
        await _write_log(session, oid, KIND_DISTILL, content, summary)
        await _ensure_profile(session, oid)

    return {"summary": summary, "content": content}


#: `record_distill_outcome` 允许写的 `kind`。
#:
#: ★ 收窄到这两种**整理结局**：`manual` / `import` / `reset` 属于用户动作，
#:   各自有专门的写入点（`save_memory` / `reset_memory`）。放开会让
#:   "谁在写哪种日志"失去边界，而 `kind` 正是时间线渲染与筛选的依据。
_DISTILL_LOG_KINDS: tuple[str, ...] = (KIND_DISTILL, KIND_DISTILL_FAILED)


async def record_distill_outcome(
    owner_id: Optional[str],
    kind: str,
    content: str,
    detail: Optional[dict] = None,
) -> None:
    """给一次整理留痕（"成功但无事" / "失败" 都走这里）。

    ★ 为什么"跑了但没内容"也要留一条：`KIND_DISTILL` 覆盖两种情况 ——
      "有新内容"与"跑通了但没有新内容"，两者都是**正常运行**；
      而"压根没跑"在界面上同样显示为"暂无学习记录"。
      不写这一条，用户就无法区分"昨晚跑了"与"昨晚没跑" ——
      这正是 r141 判「假页面」的那条判据（与 `KIND_DISTILL_FAILED` 的注释同源）。
    """
    oid = _require_owner(owner_id)
    if kind not in _DISTILL_LOG_KINDS:
        raise ValueError(
            f"record_distill_outcome 只接受 {_DISTILL_LOG_KINDS}，收到 {kind!r}"
        )
    async with get_async_session() as session:
        await _write_log(session, oid, kind, content, detail)
        await _ensure_profile(session, oid)
