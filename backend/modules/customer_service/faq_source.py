"""客服话术的**唯一真源**：`knowledge_faqs` 表。

======================================================================
★ 为什么要有这个文件（第 286 轮）
======================================================================
改造前，智能客服的 FAQ / RAG 检索源是 `agent_cs.MOCK_FAQ_DB` —— 进程内存
里 12 条硬编码字典。而库里 `knowledge_faqs` 躺着**同一业务、可编辑、带热度**
的真数据，`modules/knowledge_base/db_model.py` 的文件头还白纸黑字写着它是
「智能客服 RAG 的一路检索源」。于是同一个问题有两种答案：

    · 客服 Agent 说：命中内存 12 条（改不动、不落库、重启即回原样）
    · 资料库页面说：命中表里那批（运营真的在维护）

★ 这就是第 285 轮审查里点出的 **A 类「接错源」**：不是缺数据，是代码读错了
  地方。和订单追踪（读 SP-API 而不读自有 `orders`）是同一种病。

本模块把「客服话术从哪里来」收成**一处**：

    load_faq_items(shop_id)          → 读表（唯一取数口）
    seed_cs_faqs(...)                → 把演示话术灌进表（一次性 / 可重跑）

======================================================================
★ 三条硬纪律
======================================================================
① **租户隔离**：`knowledge_faqs.shop_id` 是作用域列（外键指向 `stores_store`），
   查询一律经 `core.tenant.scoping.scope_condition`，不手写 `shop_id ==`。
   缺店铺 ⇒ **抛 `PermissionError`**（fail-closed），绝不放大成「查全部店铺」。

② **不静默退化**：数据库不可用 / 查询异常 ⇒ **原样抛出**，由调用方把原因
   显示给用户。这里**没有**任何「取不到就回退内存 mock」的分支 ——
   那正是上一版最恶劣的地方（假数据冒充真数据，且不报错）。

③ **空 ≠ 错**：表里 0 行是**正常业务状态**（这个店铺还没配话术），
   返回空列表；调用方据此给「尚未配置话术」的文案，与「库连不上」分清。

======================================================================
★ 演示数据怎么来的
======================================================================
`cs_faq_seed.json`（12 条，就是原 `MOCK_FAQ_DB` 的逐字内容）经 `seed_cs_faqs()`
灌进 `knowledge_faqs`，遵守老板定的原则：**数据可以先 mock 到数据库**。
区别是它现在**在库里**：可编辑、可删、可被前端资料库页面看到，
而不是锁死在 Python 源码里。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select

from core.database import async_session_factory
from core.logger import get_logger
from core.tenant.scoping import scope_condition
from core.stores import StoreRecord
# ★ 两张知识库表的 ORM 类**刻意不在模块级导入**：
#   `tests/test_module_layering.py` 禁止 PLUGIN → PLUGIN 的 **import 期**依赖
#   （客服与知识库都是 PLUGIN）。真正的 import 下沉到两个函数内部，
#   并统一走 `modules.knowledge_base` **门面**（不是 `.db_model` 深路径）。

logger = get_logger("customer_service.faq_source")


#: 表里的分类 code → 客服展示用的中文名。
#:
#: ★ 为什么加载时要翻成中文：`_search_faq` 的**类别权重表**和前端
#:   `/faq/categories` 用的都是中文口径（「物流」「退换货」）。翻一次，
#:   让「客服这一层的口径」不变，只有存储口径换成了英文 code。
#: ★ `order` / `aftersale` 两个 code 是本轮新增的：内存版有这两个分类，
#:   而表注释里列的枚举没有 —— 硬套会丢失分类信息（都落进 `other`）。
CATEGORY_LABELS: Dict[str, str] = {
    "shipping": "物流",
    "return": "退换货",
    "order": "订单",
    "aftersale": "售后",
    "product": "产品",
    "payment": "支付",
    "account": "账户",
    "policy": "政策",
    "review": "评价",
    "other": "其他",
}

#: 展示名 → 表 code（灌种子时反向用；也便于将来按中文名查表）
LABEL_TO_CATEGORY: Dict[str, str] = {v: k for k, v in CATEGORY_LABELS.items()}

#: 表里的 priority 是字符串（high/medium/low），`_search_faq` 的加权公式
#: 要的是数值 ⇒ 在这里归一。★ 映射只此一处，别在调用方各写一份。
_PRIORITY_SCORE: Dict[str, int] = {"high": 100, "medium": 60, "low": 30}

#: 演示话术（原内存 `MOCK_FAQ_DB` 的逐字内容）。**只在灌库时**读。
_SEED_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cs_faq_seed.json")


def _priority_to_int(code: Optional[str]) -> int:
    return _PRIORITY_SCORE.get((code or "").strip().lower(), 30)


async def load_faq_items(shop_id: Optional[str]) -> List[Dict[str, Any]]:
    from modules.knowledge_base import KnowledgeFaqRecord  # 延迟 + 走门面（见文件头）
    """读**当前店铺**的启用话术（status=active），映射成客服 FAQ 字段。

    Args:
        shop_id: 店铺 id。**必须显式传入**（调用方从请求上下文拿），
            不从任何 ContextVar 里摸 —— 范式 B（`invoke()`）从不设置那玩意。

    Returns:
        FAQ 字典列表（可直接构造 `FAQItem`）。**空列表 = 该店铺还没配话术**。

    Raises:
        PermissionError: 缺店铺上下文（话术是租户隔离数据，不允许跨店读）。
        Exception: 数据库不可用 / 查询失败 —— **原样抛出**，不吞、不回退。
    """
    if not shop_id:
        # ★ fail-closed：与 `modules/trade/tools.py::_require_shop_id` 同口径。
        #   返回空列表会让上层「自然地」落到「没找到答案」文案，
        #   把「没选店铺」伪装成「没有这条话术」—— 归因反向。
        raise PermissionError(
            "缺少店铺上下文（X-Shop-ID），拒绝读取话术库 —— "
            "话术是租户隔离数据，不允许跨店查询"
        )

    async with async_session_factory() as session:
        rows = (await session.execute(
            select(KnowledgeFaqRecord)
            .where(
                scope_condition(KnowledgeFaqRecord, shop_id),
                KnowledgeFaqRecord.status == "active",
            )
        )).scalars().all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append({
            "id": r.id,
            "question": r.question or "",
            "answer": r.answer or "",
            "category": CATEGORY_LABELS.get(r.category or "other", r.category or "其他"),
            "keywords": list(r.keywords or []),
            "priority": _priority_to_int(r.priority),
            # `views` / `helpful_count` 在表里没有对应列：
            # usage_count 是「被客服命中次数」，views 是「被客户看过次数」，
            # 语义不同 ⇒ views 用 0，不拿 usage_count 冒充实测数据。
            "views": 0,
            "helpful_count": 0,
            "usage_count": int(r.usage_count or 0),
        })

    # 高优先级在前、同优先级热度高的在前（命中排序稳定可复现）
    items.sort(key=lambda i: (-int(i["priority"]), -int(i["usage_count"]), i["id"]))
    return items


def _load_seed_rows() -> List[Dict[str, Any]]:
    with open(_SEED_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


async def seed_cs_faqs(
    *, only_for_shop_ids: Optional[Sequence[str]] = None,
) -> Dict[str, int]:
    """把 12 条演示话术灌进 `knowledge_faqs`（幂等：已存在则跳过）。

    ★ 挂在店铺的**默认知识库**下（`is_default=True`）：`kb_id` 是话术的
      唯一归属维度，挂错容器这条话术在任何视图里都查不到。
      店铺还没有默认库 ⇒ 跳过该店铺（**不代建**，避免静默造数据）。

    Args:
        only_for_shop_ids: 只给点名的店铺灌；None = 所有店铺。

    Returns:
        {shop_id: 本次新增行数}
    """

    from modules.knowledge_base import (
        KnowledgeBaseRecord, KnowledgeFaqRecord,
    )  # 延迟 + 走门面（见文件头，PLUGIN→PLUGIN 不许 import 期依赖）
    rows = _load_seed_rows()
    result: Dict[str, int] = {}

    async with async_session_factory() as session:
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if only_for_shop_ids is not None:
            known = set(shop_ids)
            shop_ids = [s for s in only_for_shop_ids if s in known]

        for shop_id in shop_ids:
            kb = (await session.execute(
                select(KnowledgeBaseRecord).where(
                    scope_condition(KnowledgeBaseRecord, shop_id),
                    KnowledgeBaseRecord.is_default.is_(True),
                ).limit(1)
            )).scalars().first()
            if kb is None:
                logger.warning(f"[cs_faq] 跳过店铺 {shop_id}：没有默认知识库可挂载")
                continue

            exist = set((await session.execute(
                select(KnowledgeFaqRecord.id).where(
                    scope_condition(KnowledgeFaqRecord, shop_id)
                )
            )).scalars().all())

            added = 0
            for item in rows:
                fid = f"cs-{item['id']}-{shop_id}"
                if fid in exist:
                    continue
                session.add(KnowledgeFaqRecord(
                    id=fid,
                    shop_id=shop_id,
                    kb_id=kb.id,
                    question=item.get("question", ""),
                    answer=item.get("answer", ""),
                    category=item.get("category", "other"),
                    keywords=list(item.get("keywords") or []),
                    priority=item.get("priority", "medium"),
                    status="active",
                    usage_count=int(item.get("usage_count") or 0),
                ))
                added += 1

            if added:
                result[shop_id] = added

        await session.commit()

    return result


__all__ = [
    "CATEGORY_LABELS",
    "LABEL_TO_CATEGORY",
    "load_faq_items",
    "seed_cs_faqs",
]
