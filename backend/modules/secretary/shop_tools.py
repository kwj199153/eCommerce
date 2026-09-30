"""
店秘书「店铺切换工具」

把「切换当前店铺」包装成工具，让主 Agent 能一句话切到目标店铺。
这是「AI 原生」的核心能力之一：店铺数据源切换是高频操作，不应只藏在侧栏。

设计要点（与 navigation_tools.py / product_tools.py 一致）：
- 工具本身不直接改前端状态（后端够不着前端的 shopStore），只查库 + 返回结构化标记，
  由 orchestrator 端点透传给前端，前端 dispatchAppAction 落地为 shopStore.setCurrentShop。
- 数据源：PostgreSQL 的 stores_store 表（与 /api/v1/stores 同源）。
- 与 select_product 不同：switch_shop 要列出**归属你的全部**店铺
  （不受**当前 shop** 限制），因此不依赖请求注入的 shop_id，
  用独立 build_shop_tools() 构建。
- ★★★ 但**必须按归属过滤**（第 239 轮）：不受「当前 shop」限制
  ≠ 不受「租户」限制。本文件曾把前者误推成后者 ⇒ `_list_shops()`
  读全表、把**别家店铺**喂给 LLM（老板实测：UI 显示 4 家、对话回答 9 家，
  模型还为这个错误输入编了一段「演示模式只有 1–2 家可用」的幻觉）。
  筛选真源是 `core.auth.accounts.filter_accessible_stores`
  —— 与 `/api/v1/stores` 是**同一份**实现，不再有第二份口径。
"""

import json
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.side_effects import READ_ONLY_METADATA
from sqlalchemy import select

from core.auth.accounts import filter_accessible_stores
from core.database import async_session_factory
from core.identity.models import User
from core.observability.context import current_user_id
from core.stores import StoreRecord, SHOP_ORDER_BY

logger = logging.getLogger(__name__)


def _platform_family(platform: str) -> str:
    """把具体站点归到平台家族：`shopee_my` / `shopee_tw` → `shopee`。

    为什么需要：老板说「虾皮」「亚马逊」时指的是**平台家族**，而库里存的是
    带站点的 `shopee_my` / `shopee_tw`。子串匹配时「虾皮2」不能命中
    「虾皮1 shopee_my」，但「shopee」能命中全部虾皮店铺 —— 需要一个统一的
    家族名来做筛选与分组。
    """
    p = (platform or "").lower()
    for fam in ("shopee", "amazon", "temu", "tiktok", "shopify"):
        if p.startswith(fam):
            return fam
    return p


async def _resolve_current_user(session):
    """把请求上下文里的 `user_id` 解析回 `User` 行（拿不到 ⇒ `None`）。

    ★ 为什么从 ContextVar 取身份、而不是从工具入参取：
      工具入参是**模型给的**，可被提示注入伪造。身份只能由服务端注入 ——
      与 `ai_infra/skills.py::_load_skill` 读 `current_user_id()` 同一范式。

    ★ 为什么查不到 ⇒ `None`（而不是抛错、也不是随便挑一个人）：
      与 `core/auth/demo_identity.resolve_demo_user` 守卫②**同构** ——
      「查不到那个人」的语义是**无身份**，下游 `filter_accessible_stores`
      据此只放行演示店铺。这既是安全失败方向，也避免把「用户刚被删」
      变成一次 500。
    """
    uid = current_user_id()
    if not uid:
        return None
    user = (
        await session.execute(select(User).where(User.id == uid))
    ).scalars().first()
    if user is None:
        logger.warning(
            "[shop_tools] 上下文 user_id=%r 查不到 User 行 ⇒ 按无身份处理", uid
        )
    return user


async def _list_shops() -> list[dict]:
    """读取**当前身份可见的**店铺（按创建时间排序），返回轻量字典列表。

    ★ 排序键复用 `SHOP_ORDER_BY` 真源 —— 与 `/api/v1/stores` 同源。
    老板说「切到第 2 个店铺」时，序号就是**这里**数出来的（LLM 读 tool 返回值），
    而用户看的是 `/api/v1/stores` 的顺序。两者必须一致，否则静默切错店。

    ★ 同时标注**平台内序号**（`platform_index` / `platform_total`）：
    老板说「第二个虾皮店铺」时指的是平台内第 2 个，而 `index` 是全局序号 ——
    历史上 LLM 拿全局序号去猜「虾皮2」，猜成了全局第 3 个（= 虾皮1），静默切错店。
    给出平台内序号后，LLM 无需自己数。
    """
    async with async_session_factory() as session:
        q = select(StoreRecord).order_by(*[getattr(StoreRecord, k) for k in SHOP_ORDER_BY])
        rows = (await session.execute(q)).scalars().all()

        # ★★★ 第 239 轮：按归属过滤 —— 与 `/api/v1/stores` **同一份真源**。
        #   修前这里是「读全表」，于是 UI 显示 4 家、LLM 被告知 9 家，
        #   其中 1 家属于**别的账号**、4 家是测试残留。
        #   ★ 过滤后 `index` / `platform_index` / `total` 全部基于**可见集合**
        #     重算 —— 序号是给 LLM 定位用的，必须与用户看到的列表同源，
        #     否则「切到第 2 个店铺」会静默切到别家。
        #   ★ `user` 为 None（无身份 / 查不到该人）时，下游走
        #     `filter_accessible_stores` 的演示窄口（只 `is_demo` 行）：
        #     真实店铺**仍然不可见** —— 安全失败方向，不放大范围。
        user = await _resolve_current_user(session)
        rows = await filter_accessible_stores(session, user, rows)

    # 先按平台家族分组计数（保持 SHOP_ORDER_BY 的全局顺序）
    fam_counter: dict[str, int] = {}
    fam_total: dict[str, int] = {}
    for r in rows:
        fam = _platform_family(r.platform)
        fam_total[fam] = fam_total.get(fam, 0) + 1

    out: list[dict] = []
    for i, r in enumerate(rows):
        fam = _platform_family(r.platform)
        fam_counter[fam] = fam_counter.get(fam, 0) + 1
        out.append({
            "id": r.id,
            "name": r.name,
            "platform": r.platform,
            "index": i + 1,                       # 全局序号（从 1 开始）
            "platform_family": fam,               # shopee / amazon / temu ...
            "platform_index": fam_counter[fam],   # 平台内序号（从 1 开始）
            "platform_total": fam_total[fam],     # 该平台店铺总数
            "total": len(rows),
        })
    return out


async def list_visible_shops() -> list[dict]:
    """`_list_shops` 的**公开别名** —— 供 `shop_context` 取「历史去污染」名单。

    ★ 为什么必须是**同一个函数**而不是再写一次查询：本模块的「可见店铺」口径
      = 读全表 → `filter_accessible_stores`（归属过滤）→ 按 `SHOP_ORDER_BY` 排序。
      第 239 轮的事故正是"读全表"把别家店铺喂给了 LLM。若在去污染那边另写一份
      查询，就等于**第二份实现**（本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到），
      而且过滤条件一漂移，被抹掉的店名集合就会与 UI 看到的列表不一致。
    """
    return await _list_shops()


async def _list_shops_payload() -> str:
    """`list_shops` 工具的协程体：把可见店铺列表包成**与资料库家族同形**的出参。

    ★ 为什么要有这个只读工具（第 243 轮 = 第 240 轮方案 A′）：
      修前 `build_shop_tools()` **只产出 `switch_shop`** —— 它是**替换语义**，
      调一次就真的切店。于是老板问「我有几家店 / 都绑了哪些店铺」时，模型手里
      **没有任何只读的店铺查询工具**，只能拿别的工具凑数：
        · 调 `get_my_subscription` → 答「最多可绑定 3 家」（那是**套餐上限**，
          不是实际店铺数）；
        · 或调 `switch_shop` → 为了回答而**真的切了店**（无授权的状态变更）。
      三层根因与实测证据见 `docs/round-240-shop-list-no-tool.md`。

    ★ 出参**逐键对齐** `modules/library/tools.py` 的 `type/total/returned/items`
      四键（`product_list` / `candidate_list` / …），只是 `type` 取 `shop_list`。
      为什么对齐：模型已经会读那一族的出参（`total` 是**真实总数**、`items` 可能被
      `limit` 截断），另发明一套就要在提示词里多教一遍、且容易教漏。

    ★ **刻意不含 `action` 键**：前端的 `dispatchAppAction` 见到
      `action: "switch_shop"` 就切店 —— 一个「查询」绝不能带这个副作用。
      （判据：`tests/test_secretary_shop_list_tool.py` 断言出参键集合恰为四键。）

    ★ 为什么**不复用** `_switch_shop` 的返回体（那里是 `{"action": ...}`）：
      那是**动作契约**（给前端 dispatch 用的），这里是**数据契约**（给模型读的）。
      两者混在一个出参里，就会出现「读一次列表顺手切了店」这种不可解释的行为。
    """
    shops = await _list_shops()
    items = [
        {
            "id": s["id"],
            "name": s["name"],
            "platform": s["platform"],
            "index": s["index"],                       # 全局序号（从 1 开始）
            "platform_family": s["platform_family"],   # shopee / amazon / temu ...
            "platform_index": s["platform_index"],     # 平台内序号（从 1 开始）
            "platform_total": s["platform_total"],     # 该平台店铺总数
        }
        for s in shops
    ]
    return json.dumps(
        {
            "type": "shop_list",
            "total": len(items),
            "returned": len(items),
            "items": items,
        },
        ensure_ascii=False,
    )


async def _switch_shop(
    nth: int = 1,
    shop_name: str = "",
    platform: str = "",
    platform_nth: int = 0,
) -> str:
    """切换到目标店铺（按 名称 > 平台内序号 > 全局序号 依次匹配）。

    Args:
        nth: 全局第几个店铺（从 1 开始）。未给更精确条件时的兜底。
        shop_name: 店铺名关键词（如「虾皮1」「Amazon US」）。优先级最高。
        platform: 平台家族名（`shopee` / `amazon` / `temu` ...）。用于限定范围。
        platform_nth: **平台内**第几个（从 1 开始）。老板说「第二个虾皮店铺」时用这个。
    """
    shops = await _list_shops()

    if not shops:
        return json.dumps(
            {"action": "switch_shop", "shop": None, "reason": "还没有任何店铺，请先在侧栏「店铺群」里添加"},
            ensure_ascii=False,
        )

    # ★ 入参留痕：切错店时这是唯一能定论的证据（LLM 传了什么 vs 我们怎么解析）。
    #   历史事故：老板说「虾皮2」，工具按 nth 命中到全局第 3 个（虾皮1）。
    #   没有这行日志，只能靠猜。
    logger.info(
        "[shop_tools] switch_shop 入参 nth=%r shop_name=%r platform=%r platform_nth=%r 候选=%s",
        nth, shop_name, platform, platform_nth,
        [f"{x['index']}:{x['name']}({x['platform_family']}#{x['platform_index']})" for x in shops],
    )

    target: Optional[dict] = None
    index = 0

    # ① 店铺名关键词（最精确）：全字匹配优先，其次子串（避免「虾皮1」误配「虾皮10」）
    if shop_name:
        kw = shop_name.strip().lower()
        target = next((x for x in shops if kw == x["name"].lower()), None)
        if target is None:
            target = next(
                (x for x in shops if kw in f"{x['name']} {x['platform']}".lower()),
                None,
            )
        if target is not None:
            index = target["index"] - 1

    # ② 平台内序号（老板说「第二个虾皮店铺」走这条）
    if target is None and platform_nth and platform:
        fam = _platform_family(platform)
        cands = [x for x in shops if x["platform_family"] == fam]
        if cands:
            pos = max(1, min(int(platform_nth), len(cands))) - 1
            target = cands[pos]
            index = target["index"] - 1

    # ③ 全局序号（兜底）
    if target is None:
        idx = max(0, min(int(nth), len(shops)) - 1)
        target = shops[idx]
        index = idx

    logger.info(
        "[shop_tools] switch_shop 命中 -> %s (index=%d/%d)",
        target["name"], index + 1, len(shops),
    )

    logger.info(
        "[shop_tools] switch_shop 命中 -> %s (全局 %d/%d, %s#%d)",
        target["name"], index + 1, len(shops),
        target["platform_family"], target["platform_index"],
    )

    return json.dumps(
        {
            "action": "switch_shop",
            "shop": {"id": target["id"], "name": target["name"], "platform": target["platform"]},
            "index": target["index"],
            "total": len(shops),
        },
        ensure_ascii=False,
    )


def build_shop_tools() -> list:
    """构建店铺工具（列出 / 切换），不绑定当前 shop_id。

    ★ 第 243 轮（第 240 轮方案 A′）：从「只产出 `switch_shop`」扩到
      `[list_shops, switch_shop]` —— **读**（有哪些店）与**写**（切到哪家）
      必须各有一个工具。修前只有后者，而它是**替换语义**，于是「问有几家店」
      这类纯查询只能靠一个会真切店的工具来回答（实测事故，见
      `docs/round-240-shop-list-no-tool.md`）。
    ★ 顺序：只读的在前 —— 工具排列顺序对 LLM 有弱提示作用（同
      `navigation_tools.py` 里 ask_clarification 排在 handoff 之前的做法）。
    """
    return [
        StructuredTool.from_function(
            coroutine=_list_shops_payload,
            name="list_shops",
            description=(
                "列出当前身份可见的全部店铺（**只读**，不会切换店铺）。"
                "老板问「我有几家店」「店铺列表」「都绑了哪些店铺」「总共有几个店铺」"
                "「第 2 个店铺叫什么 / 是什么平台」这类**查询类**问题时用它。\n"
                "★ 出参 total 就是**真实店铺总数**，直接用它回答，不要去数 items。\n"
                "★ 严禁用 switch_shop 来数店铺或回答「有几家店」—— 它会**真的切店**；"
                "也不要用 get_my_subscription：那是套餐里「最多可绑定几家」的**上限**，"
                "不是实际店铺数（实测事故里模型正是拿它答成「最多可绑定 3 家」）。\n"
                "★ 每项含 店铺名 / 平台 / 全局序号 / 平台内序号，可直接用于随后挑目标店铺。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_switch_shop,
            name="switch_shop",
            description=(
                "切换当前工作的店铺（数据源）。老板说「切到 XX 店」「换个店铺」「用我的美国店」"
                "「切到第 2 个店铺」「第二个虾皮店铺」等时使用。\n"
                "参数选择（按精确度从高到低，**优先用更精确的**）：\n"
                "  1) shop_name：店铺全名或片段（如「虾皮1」「Amazon US」）—— 最精确，能用就用。\n"
                "  2) platform + platform_nth：平台家族 + **平台内**序号。老板说「第二个虾皮店铺」"
                "时传 platform='shopee', platform_nth=2（**不要**用全局序号去猜）。\n"
                "  3) nth：全局序号（仅当老板明确说「第 N 个店铺」且不涉平台时用）。\n"
                "可用店铺与它们的全局/平台内序号见工具返回；切换后，后续所有选品/产品/广告/"
                "竞品等操作都在该店铺数据源下进行。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
    ]
