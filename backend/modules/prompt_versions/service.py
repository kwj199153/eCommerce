"""提示词覆写层 - 读写与同步（第 351 轮 · P0-7 B 档）

==============================================================================
★ 本模块是「表」与「内存注册表」之间的**唯一**同步点
==============================================================================
    两条链路的职责分工：
      · 写：管理端点 → 本模块 → `prompt_versions` 表（并可选立即同步内存）；
      · 读：`get_prompt_template()` 打的是**内存注册表**（`ai_infra.llm.PROMPT_TEMPLATES`），
            不是表 —— 渲染路径上一个数据库往返都不能有。
    ⇒ 于是「库里改了、内存没改」是一种可能的中间状态。本模块用
      `apply_all_overrides()` 把它收敛：**先撤回全部已应用的覆写、再按库重新应用**。
      这样「内存 = 库的一个投影」是一个可重放的等式，而不是靠增量维护的状态机
      （增量维护会在「删了一行」「换了一条」时留下幽灵覆写）。

==============================================================================
★ `describe()` 的五种状态（前端据此决定显示什么）
==============================================================================
  · `not-overridden` —— 源码版生效，没写过覆写（常态）
  · `active`         —— 覆写生效，且基线对得上当前源码
  · `stale`          —— 覆写存在但**基线已失效**（源码改过）⇒ 被闸门拦下，源码版生效
  · `disabled`       —— 覆写存在但被关掉 ⇒ 源码版生效
  · `unknown-name`   —— 库里有一行，但该名字**当前没注册**
                        （改名 / 删了 prompts.py / 忘了 import）⇒ 覆写无法生效

  ★ 最后一种不能并进 `stale`：两者的处置完全不同 —— stale 要重写覆写，
    unknown-name 要修**注册**（往往是漏 import 了 `prompts.py`）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_infra.llm import (
    PromptOverrideRejected,
    applied_overrides,
    apply_override,
    registered_names,
    reset_override,
    source_fingerprint,
    validate_override,
    variables_of,
)
from ai_infra.llm.prompt_spec import FINGERPRINT_LEN  # noqa: F401  —— 仅供对账时引用
from core.database import get_async_session
from core.logger import get_logger

from .db_model import PromptVersion

logger = get_logger(__name__)

STATUS_NOT_OVERRIDDEN = "not-overridden"
STATUS_ACTIVE = "active"
STATUS_STALE = "stale"
STATUS_DISABLED = "disabled"
STATUS_UNKNOWN_NAME = "unknown-name"


def _content_fingerprint(content: str) -> str:
    """与 `PromptSpec.fingerprint` 同算法（复用 `PromptSpec` 本身，不另写一份哈希）。"""
    from ai_infra.llm import PromptSpec

    return PromptSpec(name="__fp__", content=content).fingerprint


def _status_of(name: str, row: Optional[PromptVersion], source_fp: Optional[str]) -> str:
    if source_fp is None:
        return STATUS_UNKNOWN_NAME
    if row is None:
        return STATUS_NOT_OVERRIDDEN
    if not row.enabled:
        return STATUS_DISABLED
    if (row.base_fingerprint or "") != source_fp:
        return STATUS_STALE
    return STATUS_ACTIVE


def _to_item(name: str, row: Optional[PromptVersion]) -> Dict[str, Any]:
    """把「注册表事实」与「库里那一行」合并成前端要的一条。"""
    source_fp = source_fingerprint(name)
    source_version: Optional[str] = None
    from ai_infra.llm import PROMPT_TEMPLATES

    src_spec = PROMPT_TEMPLATES.get(name)
    if src_spec is not None:
        source_version = src_spec.version

    status = _status_of(name, row, source_fp)
    return {
        "name": name,
        "status": status,
        # ★ 与 `status` **分开**报：`active` 是**配置态**（这条覆写能装上），
        #   `applied` 是**运行态**（它已经在内存注册表里生效）。
        #   两者可以不同 —— 直接改库、还没跑 `apply_all_overrides()` 时就是
        #   active 但 not applied。合成一个字段会让界面把「已配置」读成「已生效」。
        "applied": name in applied_overrides(),
        # ★ 只有在覆写**真的生效**时才把版本/指纹报成覆写那一版 ——
        #   否则界面会显示「v3 生效中」而实际跑的是源码 v1（虚假陈述）。
        "version": (row.version if row is not None and status == STATUS_ACTIVE else source_version),
        "fingerprint": (row.fingerprint if row is not None and status == STATUS_ACTIVE else None),
        "base_fingerprint": row.base_fingerprint if row is not None else None,
        "source_fingerprint": source_fp,
        "source_version": source_version,
        "enabled": bool(row.enabled) if row is not None else False,
        "note": row.note if row is not None else None,
        "updated_at": row.updated_at if row is not None else None,
        "variables": list(variables_of(name)),
    }


# ============================================================
# 读
# ============================================================

async def list_status(db: AsyncSession) -> Dict[str, Any]:
    """全部模板的合并状态（已注册的 + 库里多出来的）。"""
    rows = {
        r.name: r
        for r in (await db.execute(select(PromptVersion))).scalars().all()
    }
    names = list(registered_names())
    # 库里多出来的名字（改名 / 未注册）也要露出来，否则运维看不到它们
    names += [n for n in sorted(rows) if n not in names]

    items = [_to_item(n, rows.get(n)) for n in names]
    # ★ 分母取**内存里真正生效的那一份**（`applied_overrides()`），不是
    #   「状态算出来是 active 的条数」—— 后者是配置态，可能与运行态不同
    #   （见 `_to_item` 里 `applied` 字段的说明）。
    applied = set(applied_overrides()) & {i["name"] for i in items}
    return {
        "items": items,
        "registered_total": len(registered_names()),
        "overridden_total": len(rows),
        "applied_total": len(applied),
        "stale_total": sum(1 for i in items if i["status"] == STATUS_STALE),
    }


async def get_row(db: AsyncSession, name: str) -> Optional[PromptVersion]:
    return (
        await db.execute(select(PromptVersion).where(PromptVersion.name == name))
    ).scalar_one_or_none()


async def describe(db: AsyncSession, name: str) -> Dict[str, Any]:
    """单个模板的合并状态（写端点回显用）。

    ★ 与 `list_status()` 共用**同一个** `_to_item()`：两份实现必然在某次
      加字段后不同步，而表现是「列表里显示 stale、详情里显示 active」——
      两个都说自己是对的，排查时先要怀疑的是界面而不是数据。
    """
    key = (name or "").strip()
    return _to_item(key, await get_row(db, key))


# ============================================================
# 写
# ============================================================

class UnknownPromptName(ValueError):
    """覆写只能作用在**已注册**的提示词上 —— 未注册的名字写进去永远不会生效。"""


class NoOverrideRow(LookupError):
    """名字**已注册**、库里却**没有这一行**覆写。

    ★ 与 `UnknownPromptName` 分开而不是复用一个异常：两者的处置完全不同 ——
      · `UnknownPromptName` ⇒ 400，去修**注册**（漏 import `prompts.py` / 改名）；
      · `NoOverrideRow`     ⇒ 404，去**写**这条覆写（或确认你点错了行）。
      压成一个异常会逼调用方再查一次注册表来分辨 ——
      那种「靠猜」的分支正是在下一次改名时会悄悄走错的一条。
    """


class InvalidOverride(ValueError):
    """这条覆写**过不了闸门**（stale / 变量集不符 / 正文不合规）。

    ★ 与 `UnknownPromptName` 分开：后者是「名字不对」，本异常是「正文不对」
      —— 两者的修法完全不同（去修注册 vs 去改正文）。
    """

    def __init__(self, message: str, *, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


async def upsert_version(
    db: AsyncSession,
    *,
    name: str,
    content: str,
    version: str,
    note: Optional[str],
    user_id: Optional[str],
) -> PromptVersion:
    """新建 / 替换一条覆写。

    Raises:
        UnknownPromptName: 该名字当前没注册 —— **硬拒绝**。
            允许写入的后果是「库里有一条永远不生效的覆写」：
            界面显示已配置，线上却跑着源码版，而没有一处会报错。
    """
    key = (name or "").strip()
    if not key:
        raise UnknownPromptName("缺少模板名")

    # ★ 基线由**服务端现算**（见 schemas.py 文件头）：未注册 ⇒ 拒绝写入。
    #   ⚠️ 注意 `source_fingerprint` 在**已有覆写**时返回的是 `_ORIGINALS` 里的
    #      源码规格 ⇒ 它始终指向「源码那一版」，这是刻意的（见 oauth 同名函数的说明）。
    source_fp = source_fingerprint(key)
    if source_fp is None:
        raise UnknownPromptName(
            f"模板 {key!r} 未注册，无法写覆写（写了也不会生效）。"
            f"当前已注册: {registered_names()}"
        )

    # ★★ 落库**之前**跑一遍全部闸门（与 `apply_override()` 同一实现）。
    #   为什么不能只靠应用时那道闸门：写口的顺序是「先落库、后应用」——
    #   一条变量集不符的正文会被写进库（enabled + 基线对得上 ⇒ `_status_of`
    #   判 `active`），而它在应用时被拒 ⇒ **界面显示「覆写生效中」、
    #   线上跑源码版**。那正是本模块存在要消灭的虚假陈述。
    try:
        validate_override(
            key,
            content=content,
            version=version or "1",
            base_fingerprint=source_fp,
        )
    except PromptOverrideRejected as exc:
        raise InvalidOverride(str(exc), reason=exc.reason) from exc

    fingerprint = _content_fingerprint(content)
    row = await get_row(db, key)
    if row is None:
        row = PromptVersion(
            name=key,
            content=content,
            version=version or "1",
            fingerprint=fingerprint,
            base_fingerprint=source_fp,
            enabled=True,
            note=note,
            created_by=user_id,
        )
        db.add(row)
    else:
        row.content = content
        row.version = version or "1"
        row.fingerprint = fingerprint
        row.base_fingerprint = source_fp
        row.enabled = True
        row.note = note
        row.created_by = user_id
    await db.flush()
    return row


async def set_enabled(
    db: AsyncSession, *, name: str, enabled: bool
) -> PromptVersion:
    """开关一条覆写。

    Raises:
        UnknownPromptName: 该名字当前**没注册**（与 `upsert_version` 同口径 ⇒ 400）。
        NoOverrideRow: 名字注册了、但库里没有覆写行（⇒ 404）。
    ★ 两种「没有」必须分开报（理由见 `NoOverrideRow` 的 docstring）。
    """
    key = (name or "").strip()
    if source_fingerprint(key) is None:
        raise UnknownPromptName(
            f"模板 {key!r} 未注册，无法开关覆写。当前已注册: {registered_names()}"
        )
    row = await get_row(db, key)
    if row is None:
        raise NoOverrideRow(f"模板 {key!r} 没有覆写记录")
    row.enabled = bool(enabled)
    await db.flush()
    return row


async def delete_version(db: AsyncSession, name: str) -> bool:
    """删除一条覆写（幂等：不存在返回 False）。"""
    row = await get_row(db, (name or "").strip())
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


# ============================================================
# 同步：库 → 内存注册表
# ============================================================

async def _load_enabled_rows(session: AsyncSession) -> List[Dict[str, str]]:
    """读启用中的覆写。

    ★ 立刻转成 dict：本函数可能在 `get_async_session()` 的 `async with` 里调用，
      而那个上下文在退出时会 `commit()` ⇒ ORM 对象被 expire ⇒
      出了块再访问属性会 `DetachedInstanceError`（不是「读不到」，是**炸**）。
    """
    rows = (
        await session.execute(
            select(PromptVersion).where(PromptVersion.enabled.is_(True))
        )
    ).scalars().all()
    return [
        {
            "name": r.name,
            "content": r.content,
            "version": r.version,
            "base_fingerprint": r.base_fingerprint,
        }
        for r in rows
    ]


async def apply_all_overrides(db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """把库里的覆写**同步**到内存注册表，返回一份可读的报告。

    ★ 先撤回、再应用（而不是增量合并）：让「内存 = 库的投影」成为可重放的等式。
      增量维护在「删掉一行」「名字改了」时会留下**幽灵覆写**
      —— 库里已经没有它了，线上却还在用它。

    Args:
        db: 可选。传了就复用（管理端点，与请求同一事务）；
            不传则自建会话（应用启动期 —— 那时还没有请求上下文）。

    Returns:
        {"applied": [...], "reset": [...], "skipped": [{"name","reason","message"}]}

    ★ 单条失败**不**中断整体：一条 stale 的覆写不该让其它 11 条都装不上。
      失败原因逐条进 `skipped`，由调用方（启动日志 / 端点响应）呈现。
    """
    report: Dict[str, Any] = {"applied": [], "reset": [], "skipped": []}

    for name in list(applied_overrides()):
        if reset_override(name):
            report["reset"].append(name)

    if db is not None:
        rows = await _load_enabled_rows(db)
    else:
        async with get_async_session() as session:
            rows = await _load_enabled_rows(session)

    for row in rows:
        try:
            apply_override(
                row["name"],
                content=row["content"],
                version=row["version"],
                base_fingerprint=row["base_fingerprint"],
            )
        except PromptOverrideRejected as exc:
            report["skipped"].append(
                {"name": row["name"], "reason": exc.reason, "message": str(exc)}
            )
            logger.warning(
                "提示词覆写未生效: name={} reason={}", row["name"], exc.reason
            )
            continue
        report["applied"].append(row["name"])

    return report
