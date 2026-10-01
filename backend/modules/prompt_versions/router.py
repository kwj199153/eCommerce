"""提示词覆写层 —— 管理端点（第 351 轮 · P0-7 B 档）。

==============================================================================
★ 访问控制：**平台超管**，且这是刻意的
==============================================================================
表里没有 `store_id` / `account_id` —— 覆写是**平台级配置**，不属于任何租户
（论证见 `db_model.py` 文件头）。所以「按归属过滤」那条判据**不适用**；
代价是读口必须**更严**，否则就是「无归属 + 人人可读」的越权形态。

⇒ 本文件每条端点一律 `Depends(get_admin_user)`（与 `core/audit/router.py` 同款）：
      · 匿名 / 无效 token ⇒ **401**（由 `get_current_user` 抛出）；
      · 已登录但非平台超管 ⇒ **403**。
   ★ 401 与 403 必须分开：压成同一个码会让调用方分不清
     「该去登录」与「登录了也没用」，而这是两种完全不同的处置。

★ 为什么 router 级**不**挂 `BUSINESS_AUTH`：
  那个依赖是 optional-auth（无凭据时返回 `None`）—— 挂上它只会把「匿名」
  放行到 handler，再由 handler 里的 `get_admin_user` 兜住，两层语义叠起来
  让 401 的来源变得难追。本模块照 `core/audit/router.py` 的范式：
  **端点自带**超管门禁，路由级不加任何依赖。

★ 不挂 `API_QUOTA`：本路由全是 CRUD（读表 / 写表），不产生任何模型调用。
  配额门的挂载原则是「只挂真正烧钱的端点」。

==============================================================================
★ 写端点为什么自己 `commit` 再写审计
==============================================================================
`get_db` 的事务语义是「正常返回时 commit、异常传播上来就 rollback」。
审计走 `record_audit()`，它**自带会话、自提交**（见 `core/audit/service.py`）——
两者不是一个事务。于是如果把成功审计写在 commit 之前：

    业务回滚（后面某步抛了） ⇒ 审计已经落地，记的却是一次**没发生**的改动

⇒ 写端点显式 `await db.commit()` **之后**再写成功审计。
  失败分支反过来：先写失败审计、再抛 —— 那一侧的要点是
  「谁试过改线上提示词」，即便业务没生效也必须留痕。
  端点内这次 commit 之后，`get_db` 收尾的那次 commit 变成空操作，无害。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import (
    ACTION_PROMPT_OVERRIDE_DELETE,
    ACTION_PROMPT_OVERRIDE_WRITE,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    TARGET_PROMPT,
    record_audit,
)
from core.auth.dependencies import get_admin_user
from core.database import get_db
from core.identity.models import User

from . import service
from .schemas import (
    PromptVersionApplyResult,
    PromptVersionEnabledRequest,
    PromptVersionListResponse,
    PromptVersionUpsertRequest,
)
from .service import InvalidOverride, NoOverrideRow, UnknownPromptName

router = APIRouter(prefix="/api/v1/prompt-versions", tags=["提示词覆写"])

#: 路径参数。★ 与 ORM 的 `String(128)` 一致 —— 超长的名字在服务端只会变成
#: 一次「未注册」的拒绝，提前用 422 挡掉更省事，也让契约面自己说清上限。
_Name = Path(..., min_length=1, max_length=128, description="模板名（注册表 key）")


def _unknown_name_to_http(exc: UnknownPromptName) -> HTTPException:
    """「名字没注册」⇒ 400。

    ★ 用 400 而不是 404：这不是「某个已存在的资源找不到」，而是**请求本身
      写错了对象**（该模板名当前不在注册表里 —— 常见于改名、漏 import
      `prompts.py`、或注册表尚未装配）。把两者压成 404 会让排查方向偏向
      「数据是不是被删了」，而真因在**注册**那一侧。
    """
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _invalid_override_to_http(exc: InvalidOverride) -> HTTPException:
    """「正文过不了闸门」⇒ 400，并把 `reason` 带进 body。

    ★ reason 必须原样带出去（`stale` / `vars-mismatch` / `invalid`）：
      三者的修法完全不同 —— 重写覆写 / 先改源码 / 改正文语法。
      压成一句「覆写不合法」等于让人从错误信息里猜方向。
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": str(exc), "reason": exc.reason},
    )


def _no_row_to_http(exc: NoOverrideRow) -> HTTPException:
    """「注册了、但没有覆写行」⇒ 404 —— 这时确实没什么可开关 / 可删的。"""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ============================================================
# 读
# ============================================================


@router.get("", response_model=PromptVersionListResponse)
async def list_prompt_versions(
    _admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """全部模板在「源码 vs 覆写」两个视角下的合并状态（平台超管专属）。

    ★ 返回的是**合并**视图而不是纯表内容：库里那一行不会告诉调用方
      「这条覆写现在到底生效没生效」。判据见 `service._status_of()`
      与 `service._to_item()` 里「只在 active 时才报覆写版本」那段注释。
    """
    return await service.list_status(db)


@router.get("/{name}")
async def get_prompt_version(
    name: str = _Name,
    _admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """单个模板的合并状态。

    ★ 未注册的名字**不报 404**：库里可能有它的残留行（改名后的孤儿），
      而 `unknown-name` 正是要把它露出来的状态 —— 报 404 会让运维
      看不到「库里还留着一条永远不生效的覆写」。
    """
    return await service.describe(db, name)


# ============================================================
# 写
# ============================================================


@router.put("/{name}")
async def upsert_prompt_version(
    body: PromptVersionUpsertRequest,
    name: str = _Name,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """新建 / 替换一条覆写，并**立即**同步到内存注册表。

    ★ 为什么写端点顺手同步一次：写完不同步是「最坏的一种成功」——
      接口 200、库里有一行、界面显示已配置，而线上跑的还是源码版，
      **没有任何一处会报错**。同步失败不阻断写入（覆写本身是有效配置），
      但会把原因如实放进响应的 `skipped` 里。

    Raises:
        400: 该模板名当前**没注册**（写了也永远不会生效 ⇒ 硬拒绝）；
             或正文**过不了闸门**（stale / 变量集不符 / 语法不合规）——
             闸门在**落库之前**跑，库里的每一行都必然装得上。
    """
    try:
        await service.upsert_version(
            db,
            name=name,
            content=body.content,
            version=body.version,
            note=body.note,
            user_id=admin.id,
        )
    except InvalidOverride as exc:
        await record_audit(
            action=ACTION_PROMPT_OVERRIDE_WRITE,
            actor=admin,
            status=STATUS_FAILURE,
            target_type=TARGET_PROMPT,
            target_id=name,
            summary=f"写入提示词覆写被拒（{exc.reason}）：{name}",
            detail={"reason": exc.reason, "message": str(exc)},
        )
        raise _invalid_override_to_http(exc) from exc
    except UnknownPromptName as exc:
        # ★ 顺序：先留痕、再抛。审计自带会话，不会被这次回滚带走。
        await record_audit(
            action=ACTION_PROMPT_OVERRIDE_WRITE,
            actor=admin,
            status=STATUS_FAILURE,
            target_type=TARGET_PROMPT,
            target_id=name,
            summary=f"写入提示词覆写被拒（未注册的模板名）：{name}",
            detail={"reason": str(exc)},
        )
        raise _unknown_name_to_http(exc) from exc

    await db.commit()

    report = await service.apply_all_overrides(db)
    # ★ 审计必须说清「是什么改动」，而不是「改了一个东西」：
    #   版本号 + 内容长度 + 是否真的生效，才让人事后能判断这次改动的后果。
    await record_audit(
        action=ACTION_PROMPT_OVERRIDE_WRITE,
        actor=admin,
        status=STATUS_SUCCESS,
        target_type=TARGET_PROMPT,
        target_id=name,
        summary=f"写入提示词覆写：{name} v{body.version}",
        detail={
            "version": body.version,
            "content_length": len(body.content),
            "applied": name in report["applied"],
            "skipped": report["skipped"],
            "note": body.note,
        },
    )
    state = await service.describe(db, name)
    state["skipped"] = report["skipped"]
    return state


@router.post("/{name}/enabled")
async def set_prompt_version_enabled(
    body: PromptVersionEnabledRequest,
    name: str = _Name,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """开关一条覆写（关掉 = 保留记录，让源码版生效）。

    Raises:
        400: 该模板名没注册。
        404: 注册表里有这个名字，但**没有覆写行** —— 这时没什么可开关的，
            必须如实说不存在，而不是静默 no-op 回一个 200。
    """
    try:
        await service.set_enabled(db, name=name, enabled=body.enabled)
    except UnknownPromptName as exc:
        await record_audit(
            action=ACTION_PROMPT_OVERRIDE_WRITE,
            actor=admin,
            status=STATUS_FAILURE,
            target_type=TARGET_PROMPT,
            target_id=name,
            summary=f"开关提示词覆写被拒（未注册的模板名）：{name}",
            detail={"reason": str(exc)},
        )
        raise _unknown_name_to_http(exc) from exc
    except NoOverrideRow as exc:
        raise _no_row_to_http(exc) from exc

    await db.commit()
    report = await service.apply_all_overrides(db)
    await record_audit(
        action=ACTION_PROMPT_OVERRIDE_WRITE,
        actor=admin,
        status=STATUS_SUCCESS,
        target_type=TARGET_PROMPT,
        target_id=name,
        summary=f"{'启用' if body.enabled else '停用'}提示词覆写：{name}",
        detail={"enabled": bool(body.enabled), "skipped": report["skipped"]},
    )
    state = await service.describe(db, name)
    state["skipped"] = report["skipped"]
    return state


@router.delete("/{name}")
async def delete_prompt_version(
    name: str = _Name,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """删除一条覆写 ⇒ 源码版重新生效。

    ★ 一次「静默的行为回退」—— 所以必须审计，且 summary 要写明后果。
      幂等：不存在返回 `deleted=False`（200，不是 404）——
      对删除来说「最终状态就是你想要的」比「你第几次点」更重要，
      而 404 会让前端把一次成功的收敛显示成失败。
    """
    existed = await service.get_row(db, name) is not None
    await service.delete_version(db, name)
    await db.commit()

    report = await service.apply_all_overrides(db)
    await record_audit(
        action=ACTION_PROMPT_OVERRIDE_DELETE,
        actor=admin,
        status=STATUS_SUCCESS if existed else STATUS_FAILURE,
        target_type=TARGET_PROMPT,
        target_id=name,
        summary=(
            f"删除提示词覆写：{name}（源码版重新生效）"
            if existed
            else f"删除提示词覆写：{name}（本就没有覆写行，未产生变更）"
        ),
        detail={"existed": existed, "reset": name in report["reset"]},
    )
    state = await service.describe(db, name)
    state["skipped"] = report["skipped"]
    # ★ 回显**操作自身的后果**，而不只是合并状态：
    #   `deleted=False` 就是幂等的第二次点击。没有这个字段，前端只能拿
    #   「返回值里有 name」当成功 —— 那样「删了个不存在的」与「真的删了」
    #   长得一模一样。
    state["deleted"] = existed
    state["reset"] = name in report["reset"]
    return state


@router.post("/apply", response_model=PromptVersionApplyResult)
async def apply_prompt_versions(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """把库里的覆写**同步**到内存注册表（渲染路径读的就是它）。

    ★ 为什么不能只靠写端点里的那次同步：直接改库（迁移脚本 / 手工 SQL /
      另一个进程写的）不会经过写端点。这个端点给出一个**显式**的收敛点，
      并把逐条失败原因报出来（`skipped`），而不是让「覆写没生效」
      变成没人知道的静默状态。
    """
    report = await service.apply_all_overrides(db)
    if report["skipped"]:
        # ★ 一条 stale 的覆写意味着**源码改过而覆写没跟上** —— 这时源码版生效，
        #   是安全方向，但必须可见（否则「覆写写了却一直没生效」没人知道）。
        await record_audit(
            action=ACTION_PROMPT_OVERRIDE_WRITE,
            actor=admin,
            status=STATUS_FAILURE,
            target_type=TARGET_PROMPT,
            summary=f"提示词覆写同步部分失败：{len(report['skipped'])} 条未生效",
            detail={"skipped": report["skipped"]},
        )
    return report
