"""
业务话术库 - 业务逻辑层

与 `modules/platform_rules/service.py`、`modules/candidates/service.py` 同构：
写入口从 router 抽出，默认值集中收敛在 `build_*_record`，
`*_to_dict` 负责吐成**与前端 KnowledgeBase / FaqItem / KnowledgeDoc 一一对应**的 dict。

三个刻意的取舍：

1. **不校验 category / priority / status 枚举白名单**。
   它们是「前端配置驱动」的（`FAQ_CATEGORIES` 定义在 `stores/knowledge.ts`），
   后端再硬编码一份，前端加一个分类就要改两处、还会「前端能选、后端拒收」。
   只校验必填（FAQ = question + answer；知识库 = name；文档 = filename）。

2. **faq_count / doc_count 读时实时统计**（不落库）。
   存冗余计数就得在「增 FAQ / 改 FAQ / 删 FAQ / 批量删 / 导入 / 删库」六条路径上
   同步维护，漏一处数字就永远对不上。计数是派生数据，读时 count 一次即可。

3. **删知识库级联删 FAQ 与文档**（与 platform_rules「删文档不级联删规则」相反）。
   kb_id 是话术条目的唯一归属维度，容器没了条目在前端任何视图里都不可达
   （`currentItems` / `currentDocs` 都按 kb_id 过滤），留下就是查不到的孤儿行。
"""

import time
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from core.database import async_session_factory
from modules.knowledge_base.db_model import (
    KnowledgeBaseRecord,
    KnowledgeDocRecord,
    KnowledgeFaqRecord,
)


# ====== 字段契约（与前端类型严格对齐）======

# 知识库容器的最小充分信息 = 名称
KB_REQUIRED_FIELDS = ("name",)
# 一条话术的最小充分信息 = 所属库 + 问题 + 答案
# `kb_id` 必须必填：它是话术的**唯一归属维度**，前端 currentItems / currentDocs
# 都按 kb_id 过滤 —— 没归属的条目在 UI 里永远不可见，只会污染总数统计。
FAQ_REQUIRED_FIELDS = ("kb_id", "question", "answer")
# 文档素材同理：没有 kb_id 的文档在资料库页任何列表里都取不到
DOC_REQUIRED_FIELDS = ("kb_id", "filename")

FIELD_LABELS = {
    "kb_id": "所属知识库",
    "name": "知识库名称",
    "question": "问题",
    "answer": "答案",
    "filename": "文件名",
}

# 允许从 payload 直接写入的字段白名单（禁止 setattr 任意属性）
_KB_UPDATABLE_FIELDS = ("name", "description", "icon", "type")
_FAQ_UPDATABLE_FIELDS = ("question", "answer", "category", "keywords", "priority", "status")
_DOC_UPDATABLE_FIELDS = ("filename", "file_type", "size", "description", "content")

# 默认知识库的固定主键前缀（带店铺后缀，见 db_model docstring ①）
DEFAULT_KB_ID_PREFIX = "kb-default"


def missing_required_fields(payload: dict, required: tuple) -> list:
    """返回缺失的必填字段"""
    missing = []
    for field in required:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def describe_missing_fields(missing: list) -> str:
    """缺失字段 → 中文提示（别把 `question` 这种字段名甩给用户）"""
    return "、".join(FIELD_LABELS.get(f, f) for f in missing)


def _new_id(prefix: str) -> str:
    """
    生成主键 `{prefix}-{毫秒时间戳}-{6位随机}`。

    随机后缀是必要的：批量导入时同一毫秒会造出多条，只靠时间戳会主键冲突。
    前端从不解析 id（只当字符串用），多一段后缀无破坏。
    """
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


# ====== ORM → dict（与前端类型一一对齐）======

def kb_to_dict(kb: KnowledgeBaseRecord, faq_count: int = 0, doc_count: int = 0) -> dict:
    """ORM → dict（对齐前端 KnowledgeBase；计数由调用方传入，见模块注释 ②）"""
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "icon": kb.icon,
        "type": kb.type,
        "is_default": bool(kb.is_default),
        # 冗余计数：读取时实时算，前端直接展示，不用自己 count
        "faq_count": faq_count,
        "doc_count": doc_count,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
    }


def faq_to_dict(f: KnowledgeFaqRecord) -> dict:
    """ORM → dict（字段名与前端 FaqItem 一一对齐）"""
    return {
        "id": f.id,
        "kb_id": f.kb_id,
        "question": f.question,
        "answer": f.answer,
        "category": f.category,
        # JSON 列在库里是 NULL，前端期望恒为数组 —— 统一兜底
        "keywords": f.keywords or [],
        "priority": f.priority,
        "status": f.status,
        "usage_count": f.usage_count or 0,
        "created_at": f.created_at,
        "updated_at": f.updated_at,
    }


def doc_to_dict(d: KnowledgeDocRecord, include_content: bool = False) -> dict:
    """ORM → dict（对齐前端 KnowledgeDoc；默认不返回正文，正文数千字符）"""
    out = {
        "id": d.id,
        "kb_id": d.kb_id,
        "filename": d.filename,
        "file_type": d.file_type,
        "size": d.size,
        "uploaded_at": d.uploaded_at,
        "description": d.description,
    }
    if include_content:
        out["content"] = d.content
    return out


# ====== 构造 ======

def build_kb_record(payload: dict, shop_id: Optional[str] = None) -> KnowledgeBaseRecord:
    """由 payload 构造 KnowledgeBaseRecord（不落库）"""
    now = datetime.utcnow().isoformat()
    kb_id = payload.get("id") or _new_id("kb")
    # 单主键表多店铺灌入：id 必须带店铺后缀，否则第二个店铺主键冲突
    if shop_id and not kb_id.endswith(f"-{shop_id}"):
        kb_id = f"{kb_id}-{shop_id}"
    return KnowledgeBaseRecord(
        id=kb_id,
        shop_id=shop_id or payload.get("shop_id") or "",
        name=payload.get("name") or "",
        description=payload.get("description") or "",
        icon=payload.get("icon") or "📚",
        type=payload.get("type") or "custom",
        is_default=bool(payload.get("is_default") or False),
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )


def build_faq_record(payload: dict, shop_id: Optional[str] = None) -> KnowledgeFaqRecord:
    """由 payload 构造 KnowledgeFaqRecord（不落库）"""
    now = datetime.utcnow().isoformat()
    return KnowledgeFaqRecord(
        id=payload.get("id") or _new_id("faq"),
        shop_id=shop_id or payload.get("shop_id") or "",
        kb_id=payload.get("kb_id") or "",
        question=payload.get("question") or "",
        answer=payload.get("answer") or "",
        category=payload.get("category") or "other",
        keywords=payload.get("keywords") or [],
        priority=payload.get("priority") or "medium",
        status=payload.get("status") or "active",
        usage_count=int(payload.get("usage_count") or 0),
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )


def build_doc_record(payload: dict, shop_id: Optional[str] = None) -> KnowledgeDocRecord:
    """由 payload 构造 KnowledgeDocRecord（不落库）"""
    return KnowledgeDocRecord(
        id=payload.get("id") or _new_id("kdoc"),
        shop_id=shop_id or payload.get("shop_id") or "",
        kb_id=payload.get("kb_id") or "",
        filename=payload.get("filename") or "",
        file_type=payload.get("file_type") or "other",
        size=int(payload.get("size") or 0),
        uploaded_at=payload.get("uploaded_at") or datetime.utcnow().isoformat(),
        description=payload.get("description") or "",
        content=payload.get("content"),
    )


def apply_kb_fields(record: KnowledgeBaseRecord, payload: dict) -> None:
    """把 payload 里出现且非 None 的白名单字段合并进已有记录"""
    for field in _KB_UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


def apply_faq_fields(record: KnowledgeFaqRecord, payload: dict) -> None:
    for field in _FAQ_UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


def apply_doc_fields(record: KnowledgeDocRecord, payload: dict) -> None:
    for field in _DOC_UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


# ====== 内部：计数与租户过滤 ======

def _scoped(model, shop_id: Optional[str], stmt):
    """给查询挂上租户条件（空 shop_id 时列表接口会提前返回空，不走这里）"""
    if shop_id:
        stmt = stmt.where(model.shop_id == shop_id)
    return stmt


async def _count_map(session, model, shop_id: str, column) -> dict:
    """按 kb_id 统计数量 → {kb_id: count}"""
    rows = (await session.execute(
        select(column, func.count())
        .where(model.shop_id == shop_id)
        .group_by(column)
    )).all()
    return {kb_id: cnt for kb_id, cnt in rows}


# ====== 知识库容器 ======

async def list_knowledge_bases(shop_id: Optional[str]) -> List[dict]:
    """
    列出该店铺的知识库容器（含实时统计的 faq_count / doc_count）。

    空 shop_id 一律返回空列表 —— 与 candidates / monitors / platform-rules 一致：
    没有租户上下文时无法判断归属，返回全库数据会造成跨租户串数据。
    """
    if not shop_id:
        return []
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(KnowledgeBaseRecord)
            .where(KnowledgeBaseRecord.shop_id == shop_id)
            # 默认库永远置顶，其余按创建时间正序（与前端列表渲染顺序一致）
            .order_by(KnowledgeBaseRecord.is_default.desc(), KnowledgeBaseRecord.created_at.asc())
        )).scalars().all()

        faq_counts = await _count_map(session, KnowledgeFaqRecord, shop_id, KnowledgeFaqRecord.kb_id)
        doc_counts = await _count_map(session, KnowledgeDocRecord, shop_id, KnowledgeDocRecord.kb_id)
        return [
            kb_to_dict(kb, faq_counts.get(kb.id, 0), doc_counts.get(kb.id, 0))
            for kb in rows
        ]


async def get_kb_by_id(kb_id: str, shop_id: Optional[str] = None) -> Optional[KnowledgeBaseRecord]:
    """按主键取知识库（带租户校验：给了 shop_id 就必须匹配）"""
    async with async_session_factory() as session:
        q = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.id == kb_id)
        q = _scoped(KnowledgeBaseRecord, shop_id, q)
        return (await session.execute(q)).scalar_one_or_none()


async def get_kb_dict(kb_id: str, shop_id: Optional[str] = None) -> Optional[dict]:
    """按主键取知识库（含计数）"""
    async with async_session_factory() as session:
        q = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.id == kb_id)
        q = _scoped(KnowledgeBaseRecord, shop_id, q)
        kb = (await session.execute(q)).scalar_one_or_none()
        if kb is None:
            return None
        faq_count = (await session.execute(
            select(func.count()).select_from(KnowledgeFaqRecord).where(KnowledgeFaqRecord.kb_id == kb.id)
        )).scalar_one()
        doc_count = (await session.execute(
            select(func.count()).select_from(KnowledgeDocRecord).where(KnowledgeDocRecord.kb_id == kb.id)
        )).scalar_one()
        return kb_to_dict(kb, faq_count, doc_count)


async def create_kb(payload: dict, shop_id: Optional[str] = None) -> dict:
    """新建知识库容器（**唯一写入口**）"""
    async with async_session_factory() as session:
        record = build_kb_record(payload, shop_id=shop_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return kb_to_dict(record, 0, 0)


async def update_kb(kb_id: str, payload: dict, shop_id: Optional[str] = None) -> Optional[dict]:
    """更新知识库元信息；不存在（或不属于该租户）返回 None"""
    async with async_session_factory() as session:
        q = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.id == kb_id)
        q = _scoped(KnowledgeBaseRecord, shop_id, q)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return None
        apply_kb_fields(record, payload)
        record.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(record)
        return kb_to_dict(record)


async def delete_kb(kb_id: str, shop_id: Optional[str] = None) -> Optional[dict]:
    """
    删除知识库容器，**级联删除**其下 FAQ 与文档（见模块注释 ③）。

    返回 `{deleted_faqs, deleted_docs}` 供前端提示；不存在返回 None。
    """
    async with async_session_factory() as session:
        q = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.id == kb_id)
        q = _scoped(KnowledgeBaseRecord, shop_id, q)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return None

        faq_res = await session.execute(
            sa_delete(KnowledgeFaqRecord).where(KnowledgeFaqRecord.kb_id == kb_id)
        )
        doc_res = await session.execute(
            sa_delete(KnowledgeDocRecord).where(KnowledgeDocRecord.kb_id == kb_id)
        )
        await session.delete(record)
        await session.commit()
        return {
            "deleted_faqs": faq_res.rowcount or 0,
            "deleted_docs": doc_res.rowcount or 0,
        }


# ====== 话术条目 ======

async def list_faqs(shop_id: Optional[str]) -> List[dict]:
    """列出该店铺的全部话术（前端按 kb_id 自己分组，故这里一次拉全）"""
    if not shop_id:
        return []
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(KnowledgeFaqRecord)
            .where(KnowledgeFaqRecord.shop_id == shop_id)
            .order_by(KnowledgeFaqRecord.created_at.asc())
        )).scalars().all()
        return [faq_to_dict(f) for f in rows]


async def get_faq_by_id(faq_id: str, shop_id: Optional[str] = None) -> Optional[KnowledgeFaqRecord]:
    async with async_session_factory() as session:
        q = select(KnowledgeFaqRecord).where(KnowledgeFaqRecord.id == faq_id)
        q = _scoped(KnowledgeFaqRecord, shop_id, q)
        return (await session.execute(q)).scalar_one_or_none()


async def create_faq(payload: dict, shop_id: Optional[str] = None) -> dict:
    """新建一条话术"""
    async with async_session_factory() as session:
        record = build_faq_record(payload, shop_id=shop_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return faq_to_dict(record)


async def create_faqs_batch(items: List[dict], shop_id: Optional[str] = None) -> dict:
    """
    批量写入（文件导入用）。

    **不做 upsert 合并** —— 与 platform_rules 同理：到这一步就是
    「用户已确认要写」的最终动作，再合并反而违背用户意图。
    """
    async with async_session_factory() as session:
        records = [build_faq_record(it, shop_id=shop_id) for it in items]
        for r in records:
            session.add(r)
        await session.commit()
        for r in records:
            await session.refresh(r)
        return {"added": len(records), "items": [faq_to_dict(r) for r in records]}


async def update_faq(faq_id: str, payload: dict, shop_id: Optional[str] = None) -> Optional[dict]:
    """更新话术；不存在（或不属于该租户）返回 None"""
    async with async_session_factory() as session:
        q = select(KnowledgeFaqRecord).where(KnowledgeFaqRecord.id == faq_id)
        q = _scoped(KnowledgeFaqRecord, shop_id, q)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return None
        apply_faq_fields(record, payload)
        record.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(record)
        return faq_to_dict(record)


async def delete_faq(faq_id: str, shop_id: Optional[str] = None) -> bool:
    """删除话术；不存在（或不属于该租户）返回 False"""
    async with async_session_factory() as session:
        q = select(KnowledgeFaqRecord).where(KnowledgeFaqRecord.id == faq_id)
        q = _scoped(KnowledgeFaqRecord, shop_id, q)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return False
        await session.delete(record)
        await session.commit()
        return True


async def delete_faqs_batch(ids: List[str], shop_id: Optional[str] = None) -> int:
    """
    批量删除话术，返回实际删除行数。

    一次性 `DELETE ... WHERE id IN (...)`，不循环单条删 —— 前端勾选 20 条就是 20 次往返。
    """
    if not ids:
        return 0
    async with async_session_factory() as session:
        stmt = sa_delete(KnowledgeFaqRecord).where(KnowledgeFaqRecord.id.in_(ids))
        if shop_id:
            stmt = stmt.where(KnowledgeFaqRecord.shop_id == shop_id)
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount or 0


# ====== 文档素材 ======

async def list_docs(shop_id: Optional[str]) -> List[dict]:
    """列出该店铺的全部文档素材（不含正文，见 db_model 注释）"""
    if not shop_id:
        return []
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(KnowledgeDocRecord)
            .where(KnowledgeDocRecord.shop_id == shop_id)
            .order_by(KnowledgeDocRecord.uploaded_at.asc())
        )).scalars().all()
        return [doc_to_dict(d) for d in rows]


async def get_doc_by_id(doc_id: str, shop_id: Optional[str] = None) -> Optional[KnowledgeDocRecord]:
    async with async_session_factory() as session:
        q = select(KnowledgeDocRecord).where(KnowledgeDocRecord.id == doc_id)
        q = _scoped(KnowledgeDocRecord, shop_id, q)
        return (await session.execute(q)).scalar_one_or_none()


async def create_doc(payload: dict, shop_id: Optional[str] = None) -> dict:
    """登记一篇文档素材。正文由前端读取文件后一并提交（content 可为空）"""
    async with async_session_factory() as session:
        record = build_doc_record(payload, shop_id=shop_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return doc_to_dict(record)


async def delete_doc(doc_id: str, shop_id: Optional[str] = None) -> bool:
    """删除文档素材；不存在（或不属于该租户）返回 False"""
    async with async_session_factory() as session:
        q = select(KnowledgeDocRecord).where(KnowledgeDocRecord.id == doc_id)
        q = _scoped(KnowledgeDocRecord, shop_id, q)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return False
        await session.delete(record)
        await session.commit()
        return True
