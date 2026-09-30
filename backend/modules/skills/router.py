"""技能仓库 API（第 181 轮 · 批 B）

端点：
GET    /api/v1/agents                       - 平台 Agent 目录（勾选界面的数据源）
GET    /api/v1/tools                        - 平台工具目录（**工具技能**勾选的数据源）
GET    /api/v1/tools/usage                  - 工具 ← 技能 反向引用（工具仓库视图，第 208 轮）
GET    /api/v1/skills                       - 技能列表（不含正文）
GET    /api/v1/skills/{skill_id}            - 技能详情（含正文）
POST   /api/v1/skills                       - 新建技能
PUT    /api/v1/skills/{skill_id}            - 更新技能（正文变了会自动落版本）
DELETE /api/v1/skills/{skill_id}            - 删除技能（连带版本历史）
GET    /api/v1/skills/{skill_id}/revisions  - 版本历史
POST   /api/v1/skills/{skill_id}/rollback   - 回滚到某个版本
PUT    /api/v1/skills/{skill_id}/agents     - 「Agent 内勾选启用」的写入点
PUT    /api/v1/skills/{skill_id}/tools      - 设置技能**配备**哪些工具（第 209 轮）
PUT    /api/v1/skills/{skill_id}/favorite   - 收藏 / 取消收藏（幂等，全量覆盖）

==============================================================================
★ 鉴权：`get_acting_user`（optional auth + 演示解析），**读口与写口同一档**
==============================================================================
第 182 轮需求原文：「演示模式也当作一个真实的账号，只是无需账号密码。
也有全套功能，目前无法编辑 skill。」

⇒ 演示身份必须**真的能读、也能写**，所以本模块**所有会碰到租户数据的端点**
  （`/skills*` 全部 —— 读口与写口同一档）统一用 `get_acting_user`：
  它把演示哨兵解析成**演示账号主人**（真 `User`），
  ★ 第 209 轮：此处原先硬编码「本模块的 9 个端点（读 5 / 写 4）」，
    与真实路由表已经对不上（**陈旧计数**），且没法从一处复算。
    ⇒ 去掉数字，改判据式表述；`/agents` 与 `/tools` 是静态平台元数据、
      不含租户数据 ⇒ **不鉴权**（见 `/tools/usage` 那段的两档说明）。
  与真实登录用户走**同一条**归属链 —— `ensure_can_access_skill` /
  `filter_accessible_skills` / `ensure_default_account` 一行都不需要为演示模式开分支。

★ 与第 181 轮的差异（**需求变更**，不是缺陷修复）：
  当时演示身份被解析成 `None`，于是写口被 `_reject_no_identity` + 服务层的
  `user is None ⇒ PermissionError` 双重封死 —— 那是刻意的只读设计。
  本轮老板明确要求"全套功能"，故**保留归属门、去掉能力门**：
    · 跨账号写别人的技能 → 仍然 403（`ensure_can_access_skill`，一行没松）
    · 演示账号写**自己**的技能 → 放行（新行为）
    · 真匿名（无任何凭据）写任何技能 → 仍然 403（`_reject_no_identity`，一行没松）

★ 两层分工不变：
    路由层 —— 认证（你是谁）
    服务层 —— 授权（你能不能动这条数据）
  这与 `main.py::BUSINESS_AUTH` + `_ensure_store_access` 的两段式一致。

==============================================================================
★ 归属注入：`account_id` 由本层从 `ensure_default_account` 取，**不读请求体**
==============================================================================
与 `create_store` 同口径（见 `modules/stores/router.py` 里那段 A 档的注释）：
`ensure_default_account()` 是**幂等**的，老用户此前没有容器记录时补建、已有则复用。
  非幂等会造出第二个账户，而重复账户**不报错** —— 用户会看到两个一模一样的团队。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.accounts import ensure_can_access_skill, ensure_default_account
# ★ 第 182 轮：由 `require_auth_if_enabled` 改为 `get_acting_user`。
#   两者在**当前**实现下等价（前者自本轮起也会把演示哨兵解析成真主角），
#   但本入口要的是「**行动者**」语义 —— 读口与写口都必须认得演示身份。
#   独立函数让「有人把 optional-auth 改回返回 None」这件事**显式**地打到这里，
#   而不是让技能写口静默失效（第 181 轮踩过的形态）。
from core.auth.dependencies import get_acting_user
from core.database import get_db
from modules.skills import service
from modules.skills.agents import AGENT_CATALOG
from modules.skills.tools_catalog import TOOL_CATALOG, grouped_catalog, is_known_tool

# ★★★ 这一行是**功能性的**，不是风格问题 —— 别删：
#   `provider` 在 import 时执行 `install()`，把技能目录注入段与
#   `load_skill` 读取器登记进 `ai_infra` 的注册表。
#   删掉它 = 三个端点和数据库都正常、门禁全绿，但**技能永远不注入**，
#   且没有任何一处会报错（`collect_prompt_sections` 对空的注册表完全正常）。
#   ⇒ 由 `tests/test_skill_injection.py::test_section_registered` 钉住。
from modules.skills import provider  # noqa: F401 —— import 即完成注册

router = APIRouter(prefix="/api/v1", tags=["技能管理"])


def _reject_no_identity(current_user) -> None:
    """技能的**写**端点要求「有身份」（fail-closed）—— 无身份一律 403。

    ★★★ 第 182 轮：这个函数**保留**，但它拦的对象变了。

      第 181 轮它拦的是"演示身份"（当时演示身份恒为 `None`）⇒ 演示模式只读。
      第 182 轮演示身份被解析成**真 `User`**，于是它现在只拦**真匿名**：
      完全不带凭据（`auth_required=False` 的本地放行档），
      以及演示解析**三重守卫未过**（demo_mode 关 / 找不到账号 / 账号是超管 / 停用）
      时的安全降级。

      ⇒ 语义从「演示不能改」变成「**说不清你是谁，就不能改**」。
        这才是它本来该有的含义 —— 一个没有身份可归属的写入，
        事后在日志/审计里连"是谁做的"都答不出来。

    ★ 为什么仍然不复用 `ensure_can_access_skill`：
      那是**读**判据 —— 它对无身份**刻意放行** `is_demo` 行（演示模式要看得到技能）。
      拿它当写口 = 「谁看得见谁能改」⇒ 任何匿名访客都能改 / 删演示技能。
      本仓判据「认证 ≠ 授权」：能不能看见它、能不能改它是两个判定。
      （同族：服务层 `service.create_skill` 对 `user is None` 同样硬拒绝 —— 双保险。）
    """
    if current_user is None:
        raise HTTPException(
            status_code=403,
            detail="无法识别你的身份，不能修改技能仓库。请登录，或从演示模式进入。",
        )


# ============================================================================
# Agent 目录
# ============================================================================

@router.get("/agents")
async def list_agents():
    """平台 Agent 目录（**唯一**真源，见 `modules/skills/agents.py`）。

    ★ 不需要鉴权：它是**静态的平台元数据**（8 个 Agent 的名字），
      不含任何租户数据。加鉴权只会让演示身份连勾选界面都渲染不出来。
    """
    return {"items": AGENT_CATALOG, "total": len(AGENT_CATALOG)}


# ============================================================================
# 工具目录
# ============================================================================

@router.get("/tools")
async def list_tools():
    """平台工具目录（**唯一**真源，见 `modules/skills/tools_catalog.py`）。

    ★ 为什么需要这个端点（第 185 轮老板原话）：

        那用户怎么知道有哪些工具呢？目前是让用户自己写工具名

      在此之前，技能编辑页的「工具定义」是一个自由文本输入框：
      租户可以填**任意字符串**，而后端 `service._normalize_tools` 只做
      「去空 / 去重 / 保序」，**不校验存在性**。更糟的是那个输入框的
      placeholder 举例是 `export_report` —— 一个全仓不存在的工具。
      ⇒ 本端点把「有哪些工具」从"要用户猜"变成**可枚举的事实**。

    ★ 不需要鉴权：与 `/agents` 同判据 —— 它是**静态的平台元数据**
      （55 个工具的名字、中文说明、所属 Agent），**不含任何租户数据**。
      加鉴权只会让演示身份连勾选界面都渲染不出来。

    ★ 同时返回平铺 `items` 与按 Agent 分组的 `grouped`：
      界面要**按 Agent 分组**展示（工具是按 Agent 装配的），
      而分组口径必须**住后端** —— 前端自己按 `agent` 字段再分一遍
      = 第二份实现，改一处就静默失配（同 `agents.py` docstring 那条判据）。

    ★ 只含**真接线**的 55 个工具 —— 收录判据就是「源码里 `BaseAgent(tools=...)`
      实参命名的容器里的工具」。注册了却没有任何 Agent 绑定的工具**一个都不下发**：
      它们勾了也调不起来，而"让租户勾一个不生效的工具"比"不给他勾"更糟
      —— 他会以为配好了。

      ★ 第 204 轮之前这条排除名单里还有 19 个（`ad_analysis` 6 / `aigc_media` 9 /
        `customer_service` 4；`competitor_intel` 的 8 个更早接线）：它们已随各自的
        `_build_router()` 真正装配并登记入表。
      ★ 这份名单**不靠人记**：`tests/test_tool_catalog.py` 的判据 A 用
        「目录表 == 装配点运行时真值」的**集合相等**双向钉住它。

      ★ 第 218 轮：其中 6 个是**跨 Agent 共用**（`list_candidates` /
        `list_products`，选品分析师与店秘书共用**同一份实现**）——
        它们会**同时出现在两家 Agent 的分组里**。这是收敛「同端点多名」的结果：
        同一个后端能力只留一个工具名（落选名登记在
        `tools_catalog.REJECTED_TOOL_ALIASES`）。界面侧据此可以判断
        「这个工具不止一家能用」，而不是把它显示成两家各有各的实现。
    """
    return {
        "items": TOOL_CATALOG,
        "grouped": grouped_catalog(),
        "total": len(TOOL_CATALOG),
    }


# ============================================================================
# 工具仓库（**只读**，第 208 轮）
# ============================================================================
#
# ★ 本模块**只有一个**工具相关读口，且**没有**任何工具写口。
#   工具的真源是代码里的静态表 `tools_catalog.TOOL_CATALOG`（不是数据库表）
#   —— 所以「新建 / 编辑 / 删除工具」在**结构上**不存在，不是"尚未实现"。
#   详见下方 `tool_usage` 的 docstring。

@router.get("/tools/usage")
async def tool_usage(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """工具 ← 技能 的**反向引用**（工具仓库视图的数据源；第 208 轮）。

    ★ 与 `/tools` **刻意不同鉴权档**，两处都写了理由（读代码时最容易看漏的地方）：

        `/tools`       —— 静态平台元数据（55 个工具的名字/说明/归属），
                          **不含任何租户数据** ⇒ 不鉴权。
        本端点         —— 内容是「**你账号下**哪些技能引用了它」
                          ⇒ 必须过 `get_acting_user`，否则就是越权枚举。

      路径前缀相同不代表同一档。

    ★ 为什么本模块**没有**工具写口（`POST/PUT/DELETE /tools`）：
      工具由**代码**定义 —— `tools_catalog.TOOL_CATALOG` 是一张手写静态表，
      没有 `tools` 表、没有 ORM 实体、没有归属列。
      ⇒ 结构上就不存在「新建工具」这件事，不是"暂时没做"。
        这与老板本轮的需求原文一致：「用户是不能新建的」。
        前端因此也**不渲染任何写动作**（改工具归属 Agent 要改代码 +
        过 `tests/test_tool_catalog.py` 的判据 G/H/K 与 `ASSEMBLY_POINTS`）。

    ★ 若把「工具归属哪个 Agent」做成可勾选，就会造出**第二个真源**：
      代码声明 + 门禁钉住的那一份，与用户勾出来的那一份必然漂移。
      ⇒ 工具仓库对 Agent 只做**只读展示**。
        可写的「绑定」共**两条**，各自唯一、互不重叠：
          · 技能 ← 工具：`PUT /skills/{id}/tools`（第 209 轮）——
            写 `skill.tools`，它是**提示词引导**（软），**不是**运行期权限；
          · 技能 ← Agent：`PUT /skills/{id}/agents`。
        「工具 ← Agent」**没有**写口（见上：那是代码真源）。
    """
    return await service.tool_usage(db, current_user)


# ============================================================================
# 技能
# ============================================================================

@router.get("/skills")
async def list_skills(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """技能列表（按归属过滤；**不含正文**）。

    ★ 第 182 轮：演示身份拿到的是**演示账号自己的技能**（第 181 轮是
      「`is_demo=True` 的那几条」，因为当时演示身份是 `None`）。
      判定仍全在 `filter_accessible_skills` 内部，本层**不复制口径** ——
      演示账号与真实账号共用同一条「账户集合」判定。
    """
    items = await service.list_skills(db, current_user)
    return {"items": items, "total": len(items)}


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """技能详情（含正文）。"""
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    # ★ 归属校验：不存在与无权**同一响应**（不泄露 id 是否存在）
    await ensure_can_access_skill(db, current_user, row)
    return service.serialize(
        row,
        include_content=True,
        favorited=await service.is_favorited(db, current_user, row.id),
    )


@router.post("/skills", status_code=201)
async def create_skill(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """新建技能。必填：`name`（技能标识）。"""
    _reject_no_identity(current_user)

    account = await ensure_default_account(db, current_user)
    try:
        return await service.create_skill(
            db, current_user, payload, account_id=account.id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """更新技能（正文变化 ⇒ 自动落一条版本快照并递增版本号）。"""
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权修改该技能")

    try:
        return await service.update_skill(db, current_user, row, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """删除技能（连带它的版本历史）。"""
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权删除该技能")

    await service.delete_skill(db, row)
    return {"message": "技能已删除", "id": skill_id}


# ============================================================================
# 版本
# ============================================================================

@router.get("/skills/{skill_id}/revisions")
async def list_revisions(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """版本历史（按时间倒序）。"""
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row)
    items = await service.list_revisions(db, skill_id)
    return {"items": items, "total": len(items)}


@router.post("/skills/{skill_id}/rollback")
async def rollback_skill(
    skill_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """回滚到指定版本（**不删历史**，本次回滚本身落一条新快照）。"""
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权修改该技能")

    revision_id = str((payload or {}).get("revisionId") or (payload or {}).get("revision_id") or "").strip()
    if not revision_id:
        raise HTTPException(status_code=422, detail="revisionId 不能为空")

    result = await service.rollback_skill(db, current_user, row, revision_id)
    if result is None:
        raise HTTPException(status_code=404, detail="该版本不存在")
    return result


# ============================================================================
# Agent 装配（范式 1：「技能仓库全局管理，Agent 内勾选启用」的写入点）
# ============================================================================

@router.put("/skills/{skill_id}/agents")
async def set_skill_agents(
    skill_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """设置该技能对哪些 Agent 生效（全量覆盖语义）。

    ★ 全量覆盖而不是增量 add/remove：勾选界面本来就是「一组 checkbox 的当前值」，
      增量接口会让"并发两次勾选"产生无法解释的合并结果。
    ★ `agentNames` 接受**前端 id 或后端 agent_name**（由 `agents.find_by_id` 归一）——
      前端手里天然是 id，后端存的是 name，归一化必须发生在一处（这里是唯一入口）。
    """
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权修改该技能")

    from modules.skills.agents import find_by_id, is_known_agent

    raw = (payload or {}).get("agentNames")
    if raw is None:
        raw = (payload or {}).get("agent_names")
    if raw is None:
        raise HTTPException(status_code=422, detail="agentNames 不能为空（可为空数组）")
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=422, detail="agentNames 必须是数组")

    resolved = []
    for item in raw:
        key = str(item or "").strip()
        if not key:
            continue
        if is_known_agent(key):
            name = key
        else:
            found = find_by_id(key)
            if found is None:
                raise HTTPException(status_code=422, detail=f"未知 Agent：{key!r}")
            name = found["name"]
        if name not in resolved:
            resolved.append(name)

    return await service.update_skill(db, current_user, row, {"enabledAgents": resolved})


# ============================================================================
# skill 配装（技能 ← 工具）—— 第 209 轮
# ============================================================================

@router.put("/skills/{skill_id}/tools")
async def set_skill_tools(
    skill_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """设置该技能**配备**哪些工具（全量覆盖语义）。

    ★ 与 `PUT /skills/{id}/agents` **同形同收口**：勾选界面提交的是
      「一组 checkbox 的当前值」，增量接口会让「并发两次勾选」
      产生无法解释的合并结果。

    ★★★ 这个字段在运行期**既不授予也不限制**任何工具 —— 这段必须写在这里，
      否则下一个读代码的人会把「勾了工具」当成「授权了工具」：
        · Agent 的工具面来自 `BaseAgent.__init__` 的装配，真源是
          `TOOL_CATALOG`，由 `tests/test_tool_catalog.py` 判据 A 与
          **真实装配点**双向钉死（集合相等）；
        · `build_skill_tools()` 恒只返回一个 `load_skill`；
        · `skill.tools` 的**唯一**去处是 `render_skill_body()` 往提示词里
          渲染「本技能配套工具」。
      ⇒ 它是**提示词层面的引导**（软），不是权限。
        界面上必须如实标注，否则用户会以为"勾了就等于授权"。

    ★ 为什么不在写口拒绝「不属于该技能所挂 Agent 的工具」：那是**组合约束**
      （`tools` 与 `enabledAgents` 谁先填都可能），硬拒会让
      「先绑工具、后勾 Agent」这一正常操作流失败
      —— 判据同 `service._validate_tools` docstring。
      界面用「按已勾选的 Agent 收窄候选集」来规避它。

    ★ 存在性校验（fail-closed）：未知工具名一律 **422 硬拒**，不静默丢弃。
      静默丢弃会让用户看到「我勾了 3 个、保存后只剩 1 个」却不知道为什么。
      （这一点尤其重要：工具退役后，**旧名字**会从"生效"变成"永久空转"，
        而界面上看不出任何差别 —— 第 207 轮 4 个退役名就是这么在库里活下来的。）
    """
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权修改该技能")

    raw_names = (payload or {}).get("toolNames")
    if raw_names is None:
        raw_names = (payload or {}).get("tool_names")
    if raw_names is None:
        raise HTTPException(status_code=422, detail="toolNames 不能为空（可为空数组）")
    if not isinstance(raw_names, (list, tuple)):
        raise HTTPException(status_code=422, detail="toolNames 必须是数组")

    resolved = []
    for item in raw_names:
        key = str(item or "").strip()
        if not key:
            continue
        if not is_known_tool(key):
            raise HTTPException(
                status_code=422,
                detail=f"未知工具：{key!r}（工具由代码定义，见 tools_catalog）",
            )
        if key not in resolved:
            resolved.append(key)

    return await service.update_skill(db, current_user, row, {"tools": resolved})


# ============================================================================
# 收藏（⭐）—— 第 194 轮
# ============================================================================

@router.put("/skills/{skill_id}/favorite")
async def set_skill_favorite(
    skill_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_acting_user),
):
    """把该技能设为「已收藏 / 未收藏」（**全量覆盖**语义，幂等）。

    ★ 与 `set_skill_agents` 同形态（`PUT` + 明确目标值），理由也同源：
      toggle / 增量语义在「重复请求」下会产生与用户意图相反的结果，
      而覆盖语义天然收敛。

    ★ 收藏也**必须过归属校验**，不能因为「收藏只是个人偏好」就跳过 ——
      否则这个端点会变成一个「某个 `skill_id` 存不存在」的探测接口。

    ★ 响应口径与**既有三个写端点（update / delete / rollback）保持一致**：
      不存在 ⇒ 404、不属于你 ⇒ 403，两者**刻意不合并**。
      本仓另有「不存在与不属于你须同一响应」的判据（`session` / `store` 系
      端点），但那条针对的是**资源对非同账号成员完全不可见**的场景；
      技能是**账号内共享资源**，同账号成员本来就能在列表里看到它 ⇒
      「403 = 存在但不属于你」不额外泄漏任何东西。
      单为收藏端点另造一套口径，只会让同类写口出现两套说法。
      （钉住它的用例：`tests/test_skill_favorite.py::test_favorite_cross_account_is_rejected`）
    """
    _reject_no_identity(current_user)
    row = await service.get_skill_row(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await ensure_can_access_skill(db, current_user, row, detail="无权收藏该技能")

    raw = (payload or {}).get("favorited")
    if raw is None:
        raise HTTPException(status_code=422, detail="favorited 不能为空（true / false）")
    if not isinstance(raw, bool):
        # ★ 必须显式判类型：`"false"` 是个**真值字符串**，按 truthy 判定
        #   会把它当成「要收藏」—— 前端只要漏一次 JSON.stringify 就会静默反着来。
        raise HTTPException(status_code=422, detail="favorited 必须是布尔值")

    result = await service.set_favorite(db, current_user, row, raw)
    return {"id": row.id, "favorited": result}
