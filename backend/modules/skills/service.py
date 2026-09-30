"""技能仓库服务层（第 181 轮 · 批 B）

==============================================================================
★ 归属注入：**服务端说了算**（本仓铁律）
==============================================================================
`create_skill` / `update_skill` **从不**从请求体读 `owner_id` / `account_id` /
`is_demo` 这三个字段 —— 它们由服务端按当前身份注入。

理由（本仓已有过真实事故）：pydantic 会**忽略**多余字段，所以
「前端传了 account_id」既不会报 422、也不会被采纳，症状是"看起来成功了但归属没变"。
把归属从请求体里**删掉**，比依赖"前端别传"可靠。

★★ 写路径缺值硬拒绝：`create_skill` 在**没有身份**时直接抛错，
  而不是落一行无主技能。无主技能属于「谁都不该继承的数据」——
  它会被过渡期兜底分支判给某个 `owner_id` 恰好为空的人吗？不会（那些分支要求
  `owner_id == user.id`），但它会变成**演示身份可见**（`is_demo` 默认 False ⇒
  其实也不可见）。问题在于：它是一行**无法被任何正常路径访问**的孤儿数据，
  却占着全局唯一的 `name` ⇒ 真实用户想用这个名字会被唯一约束顶回来，且
  报错指向"名字重复"（错误方向）。所以宁可当场拒绝。

==============================================================================
★ 版本：内容变了才落 revision
==============================================================================
`update_skill` 里比对的是**正文**（`content`）而不只是"这个请求调用了 update"：
改标题、改描述、改勾选的 Agent 都不产生新版本 —— 那些不是"技能内容"的变更。
若只按"调了 update 就 +1"，版本号会迅速失去意义（用户改个描述就跳一个版本）。

★ 版本号自动 **patch +1**（`1.0.0 → 1.0.1`），也允许请求体显式指定
  （`version` 字段）—— 大改时用户想标 `2.0.0`，不该逼他改两次。
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.accounts import filter_accessible_skills, skill_account_id
from core.identity.models import User
from modules.skills.agents import is_known_agent
from modules.skills.icon import generate_skill_icon
from modules.skills.tools_catalog import all_tool_names, is_known_tool
from modules.skills.db_model import (
    SkillFavoriteRecord,
    SkillRecord,
    SkillRevisionRecord,
)

#: 合法可见范围
VISIBILITIES = ("account", "private")

def new_skill_id() -> str:
    return f"skill_{uuid.uuid4().hex[:8]}"


def new_revision_id() -> str:
    return f"rev_{uuid.uuid4().hex[:8]}"


def new_favorite_id() -> str:
    return f"fav_{uuid.uuid4().hex[:8]}"


def bump_version(current: str) -> str:
    """`1.0.3` → `1.0.4`。解析不了就退回 `1.0.1`（不抛错：版本号是展示信息，
    格式怪不该让一次保存失败）。"""
    text = str(current or "").strip()
    parts = text.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return "%s.%s.%d" % (parts[0], parts[1], int(parts[2]) + 1)
    return "1.0.1"


#: `as_shortcut` 的**写入口名集合**（同一列，多个别名）。
#:
#: ★★★ 为什么允许别名，而不是只认一个名字：
#:   DB 列名由老板拍板定为 `as_shortcut`（snake_case），而**前端契约**沿用
#:   camelCase（`isShortcut`，与同文件的 `enabledAgents` / `isDemo` /
#:   `accountId` 同风格，也与 `serialize()` 的出参名逐字对齐）。
#:   只认一个名字的后果是**另一个名字静默落到默认值** —— 调用方以为关掉了卡片，
#:   实际什么都没发生，而且不报错。这正是本仓最怕的「写口缺值不报错」
#:   （同族：`_validate_tools` 的 fail-closed 论证）。
#:   ⇒ 三个名字指向同一列，收在这一处；将来再加别名只改本常量。
SHORTCUT_KEYS = ("isShortcut", "asShortcut", "as_shortcut")


def _read_shortcut(data: Dict, *, default: bool = True) -> bool:
    """从 payload 读「是否显示为快捷卡片」，任一别名皆可；都没带 ⇒ `default`。

    ★ `default=True` 是**刻意的方向**：字段缺席 = "调用方没提这件事"，
      而不是"要关掉它"。取假值会让任何漏传该字段的旧调用方**静默丢失一排卡片**。
    """
    payload = data or {}
    for key in SHORTCUT_KEYS:
        if key in payload:
            return bool(payload.get(key))
    return default


def serialize(
    skill: SkillRecord,
    *,
    include_content: bool = True,
    favorited: bool = False,
) -> Dict:
    """转成前端契约。

    ★ `include_content=False` 用于**列表**接口：正文动辄数千字符，
      而列表页一次要展示几十条 —— 全带上等于把列表接口变成一次全量导出。
      点开详情时再按需拉（与 `platform_rules` 的「列表不带 doc.content」同判据）。

    ★ `favorited` 由**调用方**传入 —— 它不是 ORM 行上的字段：收藏住
      `skill_favorites` 表、键是「用户 × 技能」，只有调用方知道
      "看这份数据的是谁"。
      ★★ 每个返回技能对象的地方都必须传对：漏传会返回 `false`，而前端会
         据此**取消星标显示** —— 症状是「我的收藏丢了」，看起来像数据被删。
         列表路径用 `_favorite_ids()` 一次查完（避免 N+1），
         单条路径用 `is_favorited()`。
    """
    data = {
        "id": skill.id,
        "name": skill.name,
        "title": skill.title or "",
        # ★ 图标（emoji）。用 getattr 而不是 skill.icon：
        #   本函数同时被测试用**简易对象 / dict 包装**喂过，而图标是后加的列 ——
        #   写死属性访问会让那些既有用例在"没这个属性"上炸，
        #   而它们要测的（可见性、正文）与图标无关。
        #   空串是**合法值**（= 没生成 / 没填），不要在这里换成默认 emoji。
        "icon": (getattr(skill, "icon", "") or ""),
        "description": skill.description or "",
        "tools": list(skill.tools or []),
        "version": skill.version or "1.0.0",
        "visibility": skill.visibility or "account",
        "enabled": bool(skill.enabled),
        "enabledAgents": list(skill.enabled_agents or []),
        # ★ 是否在对话页显示为快捷卡片（第 248 轮）。**与 `enabledAgents` 是两个判定**：
        #   后者=「对本 Agent 生效」，本字段=「要不要给它一张卡」。
        #   ★ 用 `getattr` 兜底（同上面的 `icon`）：本函数被测试用简易对象 / dict 包装
        #     喂过，而本列是最后加的 —— 写死属性访问会让那些既有用例炸在"没这个属性"上，
        #     而它们要测的（可见性、正文）与本列无关。
        #   ★ 缺属性 / 取到 `None` 时**一律当 True**（`is not False`）：
        #     方向必须是"照常显示卡片"。反过来的话，任何一个没跟上新列的假对象
        #     都会让整排卡片**静默消失**（零报错），而这类缺陷极难归因。
        "isShortcut": getattr(skill, "as_shortcut", True) is not False,
        "isDemo": bool(getattr(skill, "is_demo", False)),
        "accountId": skill_account_id(skill),
        "createdAt": skill.created_at.isoformat() if skill.created_at else None,
        "updatedAt": skill.updated_at.isoformat() if skill.updated_at else None,
        # ★ 当前身份是否收藏了它（见签名处的论证）
        "favorited": bool(favorited),
    }
    if include_content:
        data["content"] = skill.content or ""
    return data


# ============================================================================
# 读
# ============================================================================

async def _favorite_ids(db: AsyncSession, user: Optional[User]) -> set:
    """当前身份收藏的全部 `skill_id`（**一次查完**）。

    ★ 为什么不逐条查：列表页一次几十条，逐条查就是 N+1 次往返。
    ★ 无身份 ⇒ 空集。这**不是降级** —— 收藏是「用户 × 技能」的关系，
      没有用户时这个概念根本不存在（不是「暂时读不到」）。
    """
    if user is None:
        return set()
    rows = (
        await db.execute(
            select(SkillFavoriteRecord.skill_id).where(
                SkillFavoriteRecord.user_id == user.id
            )
        )
    ).scalars().all()
    return set(rows)


async def is_favorited(db: AsyncSession, user: Optional[User], skill_id: str) -> bool:
    """当前身份是否收藏了这条技能（**单条路径**用）。"""
    if user is None:
        return False
    hit = (
        await db.execute(
            select(SkillFavoriteRecord.id).where(
                SkillFavoriteRecord.user_id == user.id,
                SkillFavoriteRecord.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    return hit is not None


async def list_skills(db: AsyncSession, user: Optional[User]) -> List[Dict]:
    """当前身份可见的全部技能（列表形态，不含正文）。

    ★ 收藏标记**内联下发**，而不是让前端再拉一个「我的收藏」列表去合并：
      两步拉取会引入「两次请求之间收藏变了」的时间窗，以及「列表里这条的
      id 在收藏集合里没匹配上」这类只能靠约定维持的口径分叉。
    """
    rows = (await db.execute(select(SkillRecord))).scalars().all()
    visible = await filter_accessible_skills(db, user, rows)
    fav_ids = await _favorite_ids(db, user)
    return [
        serialize(s, include_content=False, favorited=s.id in fav_ids)
        for s in visible
    ]


async def tool_usage(db: AsyncSession, user: Optional[User]) -> Dict:
    """工具 ← 技能 的**反向引用**索引（第 208 轮「工具仓库」的唯一读口）。

    ★ 为什么这个读口存在（老板原话：「做一个工具仓库，参照 skill 仓库」）：
      正向边（技能 → 工具）界面上早就有了 —— 编辑抽屉的「配套工具」勾选、
      卡片上的工具 tag。**反向边（这个工具被哪些技能引用了）全仓没有展示面**。
      那就是工具仓库相对技能仓库**唯一真正新增的信息**，本读口只做这一件事。

    ★ 归属口径**一行都不自己写**：直接调 `filter_accessible_skills`。
      它是技能列表端点的**唯一筛法** —— 在这里重写一份「可见性判断」
      就是第 177 轮 P1-5 那个形态（列表入口收紧了、这条路径还是松的，
      且这条路径**永远测不到**）。

    ★ 未知工具名**照实上报**（`unknownTools`），不隐藏：
      读口这一侧确实不校验 —— `ai_infra.skills.render_skill_tools()` 渲染
      「本技能配套工具」时原样渲染、只去重保序（第 207 轮认定的唯一真缺口），
      所以库里可能存在本表登记之前写入的名字。
      隐藏它们 = 用户看不见、也就删不掉（同 `tools_catalog.tool_title`
      「未知工具原样返回」那条判据）。这里把「有多少条引用指向不存在的工具」
      从**不可见**变成**一条可读的事实** —— 不改写口行为，只让它可见。

    ★ `unusedTools`（目录里有、却没有任何技能引用）也在此算好：
      它是工具仓库最有行动价值的信号（"哪些工具没人用"），
      且口径必须与 `usage` **同源** —— 前端拿两张表自己做差集
      = 第二份实现，改一处就静默失配。

    ★ `usage` 是**字典**而不是列表：界面按工具名查「被谁引用」，
      查一次 O(1)；给列表则前端自己建索引 = 又一次口径搬运。
      排序不做（Python 3.7+ dict 保插入序 = 技能表的自然顺序，
      界面要按 Agent 分组展示时按 `TOOL_CATALOG` 顺序遍历即可）。
    """
    rows = (await db.execute(select(SkillRecord))).scalars().all()
    visible = await filter_accessible_skills(db, user, rows)

    usage: Dict[str, List[Dict]] = {}
    for s in visible:
        for raw_name in (s.tools or []):
            name = str(raw_name or "").strip()
            if not name:
                continue
            # ★ 每条引用带够界面所需的全部事实（含 `enabled` / `enabledAgents`），
            #   让「这条引用有没有真的生效」由**已下发的事实**推导，
            #   而不是前端再拉一次技能列表去对账（两次请求之间会变）。
            usage.setdefault(name, []).append(
                {
                    "id": s.id,
                    "name": s.name,
                    "title": s.title or s.name,
                    "enabled": bool(s.enabled),
                    "enabledAgents": list(s.enabled_agents or []),
                }
            )

    return {
        "usage": usage,
        "unknownTools": sorted(n for n in usage if not is_known_tool(n)),
        "unusedTools": sorted(n for n in all_tool_names() if n not in usage),
        "referencedTools": len(usage),
        "totalSkills": len(visible),
    }


async def get_skill_row(db: AsyncSession, skill_id: str) -> Optional[SkillRecord]:
    return (
        await db.execute(select(SkillRecord).where(SkillRecord.id == skill_id))
    ).scalar_one_or_none()


async def get_skill_by_name(db: AsyncSession, name: str) -> Optional[SkillRecord]:
    return (
        await db.execute(select(SkillRecord).where(SkillRecord.name == name))
    ).scalar_one_or_none()


async def get_skill_detail(db: AsyncSession, user: Optional[User], skill_id: str) -> Optional[Dict]:
    """单条详情（**含正文**）。不存在返回 None —— 由路由层转 404/403。

    ★ 收藏态在这里一并查出：调用方拿到的是「看这条技能时的完整视图」，
      不需要再补一次请求（补请求 = 又一个可失配的口径）。
    """
    row = await get_skill_row(db, skill_id)
    if row is None:
        return None
    return serialize(
        row, include_content=True, favorited=await is_favorited(db, user, row.id)
    )


async def list_revisions(db: AsyncSession, skill_id: str) -> List[Dict]:
    rows = (
        await db.execute(
            select(SkillRevisionRecord)
            .where(SkillRevisionRecord.skill_id == skill_id)
            .order_by(SkillRevisionRecord.changed_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "skillId": r.skill_id,
            "version": r.version or "",
            "content": r.content or "",
            "note": r.note or "",
            "action": r.action or "update",
            "changedBy": r.changed_by,
            "changedAt": r.changed_at.isoformat() if r.changed_at else None,
        }
        for r in rows
    ]


# ============================================================================
# 写
# ============================================================================

def _validate_agents(raw) -> Optional[List[str]]:
    """校验 `enabled_agents` 只能填**真实存在**的 agent_name。

    ★ 未知值**不静默丢弃**而是返回 None 表示非法：静默丢弃会让前端看到
      「我勾了 8 个、保存后只剩 6 个」却不报错 —— 那不是用户能自查的失败。
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return None
    out: List[str] = []
    for item in raw:
        name = str(item or "").strip()
        if not name:
            continue
        if not is_known_agent(name):
            return None
        if name not in out:
            out.append(name)
    return out


def _validate_visibility(raw) -> Optional[str]:
    if raw is None:
        return "account"
    value = str(raw).strip() or "account"
    return value if value in VISIBILITIES else None


async def create_skill(
    db: AsyncSession,
    user: Optional[User],
    payload: Dict,
    *,
    account_id: Optional[str],
) -> Dict:
    """新建技能。

    ★ `account_id` 由路由层解析后传入（服务端注入），**不读 payload**。
    ★ 无身份 ⇒ 抛 `PermissionError`（路由层转 403）：
      见模块 docstring「写路径缺值硬拒绝」。
    """
    if user is None:
        raise PermissionError("需要登录后才能新建技能")

    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise ValueError("技能标识（name）不能为空")

    agents = _validate_agents((payload or {}).get("enabledAgents"))
    if agents is None:
        raise ValueError("enabledAgents 含未知 Agent（只接受平台已有的 Agent）")

    visibility = _validate_visibility((payload or {}).get("visibility"))
    if visibility is None:
        raise ValueError("visibility 只能是 account 或 private")

    tools = _validate_tools((payload or {}).get("tools"))
    if tools is None:
        raise ValueError("tools 含未注册的工具（只接受平台已注册的工具名）")

    existing = await get_skill_by_name(db, name)
    if existing is not None:
        raise ValueError(f"技能标识 {name!r} 已被占用（技能标识全局唯一）")

    content = str((payload or {}).get("content") or "")
    version = str((payload or {}).get("version") or "").strip() or "1.0.0"
    title = str((payload or {}).get("title") or "").strip()
    description = str((payload or {}).get("description") or "").strip()

    # ★ 图标（第 188 轮需求原文：「emoji + 保存时自动生成 + 允许手工改
    #   （留空则 AI 补）」）：
    #     给了值 ⇒ 采纳（**允许手工改**）；留空 ⇒ 调 LLM 补一个。
    #   ★ 生成失败返回 None ⇒ 落空串，**不阻断保存**（装饰性元数据不配丢一次写入）。
    #     也不换成"像模像样的默认图标" —— 那会让生成从未成功这件事不可见。
    icon = str((payload or {}).get("icon") or "").strip()
    if not icon:
        icon = await generate_skill_icon(title, description) or ""

    row = SkillRecord(
        id=new_skill_id(),
        name=name,
        title=title,
        icon=icon,
        description=description,
        content=content,
        tools=tools,
        version=version,
        visibility=visibility,
        enabled=bool((payload or {}).get("enabled", True)),
        enabled_agents=agents,
        # ★ 卡片开关（第 248 轮）：缺席 ⇒ True（= 保持现行为）。理由见 `_read_shortcut`。
        as_shortcut=_read_shortcut(payload),
        # ★ 归属：服务端注入（见模块 docstring）
        owner_id=user.id,
        account_id=account_id,
        is_demo=False,  # 演示标记只由 seed 双向收敛，接口不可写
    )
    db.add(row)
    # 建档即留一条快照：否则「最初那版长什么样」在改过之后无从查证。
    db.add(
        SkillRevisionRecord(
            id=new_revision_id(),
            skill_id=row.id,
            version=version,
            content=content,
            note="创建",
            action="create",
            changed_by=user.id,
        )
    )
    await db.commit()
    await db.refresh(row)
    # ★ 新技能必然未被收藏 ⇒ 直接给 False，不必多查一次
    return serialize(row, include_content=True, favorited=False)


async def update_skill(
    db: AsyncSession,
    user: Optional[User],
    row: SkillRecord,
    payload: Dict,
) -> Dict:
    """更新技能（含版本落档）。

    ★ 传入的是**已通过归属校验的 ORM 行**（路由层负责 403），本函数不再判权 ——
      判权只有一处入口，避免"两处都判、其中一处漏了"。
    """
    data = payload or {}

    if "enabledAgents" in data:
        agents = _validate_agents(data.get("enabledAgents"))
        if agents is None:
            raise ValueError("enabledAgents 含未知 Agent（只接受平台已有的 Agent）")
        row.enabled_agents = agents

    if "visibility" in data:
        visibility = _validate_visibility(data.get("visibility"))
        if visibility is None:
            raise ValueError("visibility 只能是 account 或 private")
        row.visibility = visibility

    if "title" in data:
        row.title = str(data.get("title") or "").strip()
    if "description" in data:
        row.description = str(data.get("description") or "").strip()
    if "icon" in data:
        # ★ 三态语义（第 188 轮）：
        #   · 字段**没带** ⇒ 不动（"这次请求没提交图标" ≠ "我要清空它"）；
        #   · 带了非空值  ⇒ 采纳用户手工输入（需求原文「允许手工改」）；
        #   · 带了空串    ⇒ 走 AI 补（需求原文「留空则 AI 补」）。
        #   三者共用"`in` 判定"这个本函数既有范式（title/description 同款）。
        icon = str(data.get("icon") or "").strip()
        if not icon:
            icon = (
                await generate_skill_icon(row.title or "", row.description or "") or ""
            )
        row.icon = icon
    if "tools" in data:
        tools = _validate_tools(data.get("tools"))
        if tools is None:
            raise ValueError("tools 含未注册的工具（只接受平台已注册的工具名）")
        row.tools = tools
    if "enabled" in data:
        row.enabled = bool(data.get("enabled"))
    # ★ 卡片开关（第 248 轮）—— 三态语义与上面的 `icon` 同款：
    #   · 任一别名**没带** ⇒ 不动（"这次没提交它" ≠ "我要关掉它"）；
    #   · 带了 ⇒ 采纳其布尔值。
    #   用 `any(... in data)` 而不是只看第一个名字：别名任意一个都算"提交过了"。
    if any(k in data for k in SHORTCUT_KEYS):
        row.as_shortcut = _read_shortcut(data)
    if "name" in data:
        new_name = str(data.get("name") or "").strip()
        if new_name and new_name != row.name:
            clash = await get_skill_by_name(db, new_name)
            if clash is not None and clash.id != row.id:
                raise ValueError(f"技能标识 {new_name!r} 已被占用")
            row.name = new_name

    # ★ 只有**正文**变化才产生新版本（见模块 docstring）
    if "content" in data:
        new_content = str(data.get("content") or "")
        if new_content != (row.content or ""):
            row.content = new_content
            row.version = str(data.get("version") or "").strip() or bump_version(row.version)
            db.add(
                SkillRevisionRecord(
                    id=new_revision_id(),
                    skill_id=row.id,
                    version=row.version,
                    content=new_content,
                    note=str(data.get("note") or "").strip(),
                    action="update",
                    changed_by=user.id if user is not None else None,
                )
            )
        elif data.get("version"):
            # 内容没变但显式指定了版本号 ⇒ 采纳（用户在做版本号对齐）
            row.version = str(data["version"]).strip()

    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    # ★ 这里必须查**真实**收藏态：`set_skill_agents` 等端点复用本函数，
    #   若返回恒 False，前端的星标会被「更新一下配置」抹掉
    #   （症状是「我明明收藏过」）。
    return serialize(
        row, include_content=True, favorited=await is_favorited(db, user, row.id)
    )


async def rollback_skill(
    db: AsyncSession,
    user: Optional[User],
    row: SkillRecord,
    revision_id: str,
) -> Optional[Dict]:
    """把某个历史版本的内容写回当前技能。

    ★ 回滚**不删历史**：它本身产生一条 `action="rollback"` 的新 revision。
      否则"回滚"这个动作会抹掉证据 —— 事后无从知道什么时候被回滚过。
    """
    rev = (
        await db.execute(
            select(SkillRevisionRecord).where(
                SkillRevisionRecord.id == revision_id,
                SkillRevisionRecord.skill_id == row.id,
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        return None

    row.content = rev.content or ""
    row.version = bump_version(row.version)
    row.updated_at = datetime.utcnow()
    db.add(
        SkillRevisionRecord(
            id=new_revision_id(),
            skill_id=row.id,
            version=row.version,
            content=row.content,
            note=f"回滚到 {rev.version or rev.id}",
            action="rollback",
            changed_by=user.id if user is not None else None,
        )
    )
    await db.commit()
    await db.refresh(row)
    return serialize(
        row, include_content=True, favorited=await is_favorited(db, user, row.id)
    )


async def delete_skill(db: AsyncSession, row: SkillRecord) -> None:
    """删除技能。

    ★ **连带删除它的版本历史**（DB 层 `ON DELETE CASCADE`）。
      理由：历史是**这条技能**的历史，技能没了它就无所依附；
      留下来只会变成永远查不到、却占着表的孤儿行。
      （与 `platform_rules` 的「删文档不删规则」相反 —— 那里的规则
        是独立业务实体，这里的版本只是同一实体的过去时。）
    """
    await db.delete(row)
    await db.commit()


async def set_favorite(
    db: AsyncSession,
    user: Optional[User],
    row: SkillRecord,
    favorited: bool,
) -> bool:
    """把「当前用户 × 这条技能」的收藏关系设为 `favorited` —— **幂等**。

    ★★★ 为什么是「设为」而不是「切换」（toggle）：
      toggle **不幂等**。网络重试、用户双击、前端乐观更新失败后重发，
      都会让状态翻转**两次**，最终与用户意图相反 —— 而界面上看不出哪里
      错了（星标正好回到点击前的样子，用户会以为自己没点到）。
      `PUT + 明确目标值` 让任意次数的重复请求收敛到同一状态。

    ★ 目标状态已达成时**什么都不做**（既不建第二行、也不报错）——
      这是「幂等」的完整含义，不只是「不重复插入」。

    ★ 并发下两个请求可能同时判定「需要插入」⇒ 靠 `(user_id, skill_id)`
      唯一约束兜底，捕获 `IntegrityError` 后视为**目标状态已达成**
      （而不是 500）：唯一约束在这里是**第二道保障**，不是错误来源。
    """
    if user is None:
        raise PermissionError("需要登录后才能收藏技能")

    existing = (
        await db.execute(
            select(SkillFavoriteRecord).where(
                SkillFavoriteRecord.user_id == user.id,
                SkillFavoriteRecord.skill_id == row.id,
            )
        )
    ).scalar_one_or_none()

    if favorited:
        if existing is None:
            db.add(
                SkillFavoriteRecord(
                    id=new_favorite_id(), user_id=user.id, skill_id=row.id
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
    elif existing is not None:
        await db.delete(existing)
        await db.commit()

    return bool(favorited)


def _validate_tools(raw) -> Optional[List[str]]:
    """校验 `tools` 只能填**平台已注册**的工具名（`tools_catalog`）。

    ★ 与 `_validate_agents` **同判据**：未知值返回 `None` 表示非法，
      **不静默丢弃** —— 静默丢弃会让用户看到「我勾了 3 个、保存后只剩 1 个」
      却不知道为什么，那不是用户能自查的失败。

    ★ 为什么这条校验是必须的（第 185 轮修掉的缺陷）：
      在此之前 `tools` 走 `_normalize_tools`，只做「去空 / 去重 / 保序」，
      **完全不校验存在性**。而前端那个自由输入框的 placeholder 举例是
      `export_report` —— 一个全仓不存在的工具。于是用户可以存进一个
      **永不生效**的配置：模型不会调它（工具根本不在该 Agent 手上），
      界面也照常显示这个 tag，全程没有任何反馈。

      ⇒ 未知工具名必须在**写口**被拒绝，让用户在保存那一刻就知道。
         （这也是本表存在的意义：`tools_catalog` 是「哪些名字合法」的唯一真源。）

    ★ 硬拒而不是过滤掉非法项：过滤会把错误藏起来
      （库里存了个用户没预期的清单，而用户以为自己勾的那些都生效了）。

    ★ 合法但"不属于所挂 Agent"的工具**不在此处拒绝** —— 那是**组合约束**
      （`tools` 与 `enabledAgents` 两个字段谁先填都可能），
      硬拒会让「先绑工具、后勾 Agent」这一正常操作流失败。
      界面用「按已勾选的 Agent 收窄候选集」来避免它，
      渲染期再兜一层过滤（见 `provider`）。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace("，", ",").split(",")]
    if not isinstance(raw, (list, tuple)):
        return None
    out: List[str] = []
    for item in raw:
        name = str(item or "").strip()
        if not name:
            continue
        if not is_known_tool(name):
            return None
        if name not in out:
            out.append(name)
    return out


# ============================================================================
# 给 Agent 用的读口（渐进披露第二级的取数实现）
# ============================================================================

async def read_skill_for_agent(
    db: AsyncSession,
    user: Optional[User],
    agent_name: str,
    skill_name: str,
) -> Optional[str]:
    """`load_skill` 的实际取数：按「归属 + 已启用 + 对该 Agent 启用」三重过滤后，
    返回**已渲染好的正文**（第二级披露的内容）。

    ★ 三重过滤缺一不可：
      ① 归属（`filter_accessible_skills`）—— 越权的技能不能因为知道名字就读到；
      ② `enabled` 全局开关        —— 关掉的技能不进任何 Agent；
      ③ `enabled_agents` 含本 Agent —— 「Agent 内勾选启用」的实际生效点。

    ★ 返回 `None`（而不是抛 403）：「这个技能对你不存在」与「这个技能存在但没给
      你这个 Agent 启用」在工具层**不该可分** —— 可分就等于给模型一个探测接口。
    """
    row = await get_skill_by_name(db, skill_name)
    if row is None:
        return None

    visible = await filter_accessible_skills(db, user, [row])
    if not visible:
        return None

    if not bool(row.enabled):
        return None

    agents = list(row.enabled_agents or [])
    if agent_name not in agents:
        return None

    from ai_infra.skills import render_skill_body

    return render_skill_body(row)


__all__ = [
    "VISIBILITIES",
    "new_skill_id",
    "new_revision_id",
    "new_favorite_id",
    "bump_version",
    "serialize",
    "list_skills",
    "get_skill_row",
    "get_skill_by_name",
    "get_skill_detail",
    "list_revisions",
    "create_skill",
    "update_skill",
    "rollback_skill",
    "delete_skill",
    "is_favorited",
    "set_favorite",
    "read_skill_for_agent",
]
