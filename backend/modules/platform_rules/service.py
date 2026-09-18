"""
平台规则库 - 业务逻辑层

把**写入口**从 router 抽出，与 `modules/monitors/service.py`、`modules/candidates/service.py`
同构：REST 路由与（将来的）Agent 工具共用同一套默认值与字段契约，避免两处各写一遍。

字段默认值集中收敛在 `build_rule_record` / `build_doc_record` 里；
`rule_to_dict` / `doc_to_dict` 负责把 ORM 吐成**与前端 PlatformRule / PlatformRuleDoc
一一对应**的 dict（前端 store 直接赋值，不做二次映射）。

两个刻意的取舍：

1. **不校验 platform / category 枚举白名单**。这两个是「前端配置驱动」的
   （`PLATFORMS` / `RULE_CATEGORIES` 定义在 `stores/platformRules.ts`），
   后端再硬编码一份枚举，前端加一个平台就得改两处、还会出现「前端能选、后端拒收」。
   故只校验必填（title + content），枚举值原样存。

2. **文档列表不返回正文**。`content` 单篇 3~4k 字符，列表接口全带上纯属浪费
   （前端文档列表只用 filename/size/description）。`doc_to_dict(include_content=False)`
   是默认值，只有 AI 拆分内部才需要整篇正文 —— 那时后端自己读，不经网络。
"""

import time
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from core.database import async_session_factory
from core.tenant.scoping import scoped
from modules.platform_rules.db_model import PlatformRuleDocRecord, PlatformRuleRecord


# ====== 字段契约（与前端 PlatformRule 严格对齐）======

# 判据：一条规则的最小充分信息 = 标题 + 正文。
# 平台/分类有默认值，生效日期可缺省为今天；没正文的「规则」只是空壳，必须拦住。
PLATFORM_RULE_REQUIRED_FIELDS = ("title", "content")

PLATFORM_RULE_FIELD_LABELS = {
    "title": "规则标题",
    "content": "规则正文",
    "platform": "平台",
    "category": "规则分类",
}

# 允许从 payload 直接写入的字段白名单（禁止 setattr 任意属性）
_RULE_UPDATABLE_FIELDS = (
    "platform", "category", "title", "content",
    "effective_date", "expiry_date", "status", "tags",
    "source", "source_doc_id",
)

_DOC_UPDATABLE_FIELDS = (
    "platform", "filename", "file_type", "size",
    "uploaded_at", "description", "content",
)


def missing_required_fields(payload: dict) -> list:
    """返回缺失的必填字段（对齐前端新建表单的 required）"""
    missing = []
    for field in PLATFORM_RULE_REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def describe_missing_fields(missing: list) -> str:
    """缺失字段 → 中文提示（别把 `title` 这种字段名甩给用户）"""
    return "、".join(PLATFORM_RULE_FIELD_LABELS.get(f, f) for f in missing)


def _new_id(prefix: str) -> str:
    """
    生成主键 `{prefix}-{毫秒时间戳}-{6位随机}`。

    带随机后缀是必要的：批量导入时同一毫秒会造出多条，只靠时间戳会主键冲突。
    与前端原先的 `rule-${Date.now()}` 相比多了后缀，但前端从不解析 id（只当字符串用），无破坏。
    """
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


# ====== ORM → dict ======

def rule_to_dict(r: PlatformRuleRecord) -> dict:
    """ORM → dict（字段名与前端 PlatformRule 一一对齐）"""
    return {
        "id": r.id,
        "platform": r.platform,
        "category": r.category,
        "title": r.title,
        "content": r.content,
        "effective_date": r.effective_date,
        "expiry_date": r.expiry_date,
        "status": r.status,
        # JSON 列在库里是 NULL，前端期望恒为数组 —— 统一兜底，别让前端判空
        "tags": r.tags or [],
        "source": r.source,
        "source_doc_id": r.source_doc_id,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def doc_to_dict(d: PlatformRuleDocRecord, include_content: bool = False) -> dict:
    """ORM → dict（对齐前端 PlatformRuleDoc；默认不返回正文，见模块注释）"""
    out = {
        "id": d.id,
        "platform": d.platform,
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

def build_rule_record(payload: dict, shop_id: Optional[str] = None) -> PlatformRuleRecord:
    """
    由 payload 构造 PlatformRuleRecord（不落库）。

    payload 字段除 `title` / `content` 外全部可选，缺省值在此集中收敛。
    """
    now = datetime.utcnow().isoformat()
    return PlatformRuleRecord(
        id=payload.get("id") or _new_id("rule"),
        shop_id=shop_id or payload.get("shop_id") or "",
        platform=payload.get("platform") or "amazon",
        category=payload.get("category") or "policy",
        title=payload.get("title") or "",
        content=payload.get("content") or "",
        effective_date=payload.get("effective_date") or _today(),
        expiry_date=payload.get("expiry_date"),
        # 只存用户设定的原值；按日期解析 active/upcoming/expired 是前端展示期计算
        status=payload.get("status") or "auto",
        tags=payload.get("tags") or [],
        source=payload.get("source") or "",
        source_doc_id=payload.get("source_doc_id"),
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )


def build_doc_record(payload: dict, shop_id: Optional[str] = None) -> PlatformRuleDocRecord:
    """由 payload 构造 PlatformRuleDocRecord（不落库）"""
    return PlatformRuleDocRecord(
        id=payload.get("id") or _new_id("doc"),
        shop_id=shop_id or payload.get("shop_id") or "",
        platform=payload.get("platform") or "amazon",
        filename=payload.get("filename") or "",
        file_type=payload.get("file_type") or "other",
        size=int(payload.get("size") or 0),
        uploaded_at=payload.get("uploaded_at") or datetime.utcnow().isoformat(),
        description=payload.get("description") or "",
        content=payload.get("content"),
    )


def apply_rule_fields(record: PlatformRuleRecord, payload: dict) -> None:
    """把 payload 里出现且非 None 的白名单字段合并进已有记录"""
    for field in _RULE_UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


def apply_doc_fields(record: PlatformRuleDocRecord, payload: dict) -> None:
    for field in _DOC_UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


# ====== 规则：查询 / 写入 ======

async def list_rules(shop_id: Optional[str]) -> List[dict]:
    """
    列出该店铺的全部规则。

    空 shop_id 一律返回空列表 —— 与 candidates / monitors 一致：
    没有租户上下文时无法判断归属，返回全库数据会造成跨租户串数据。
    """
    if not shop_id:
        return []
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(PlatformRuleRecord), PlatformRuleRecord, shop_id)
            # 与前端 filteredItems 的排序一致：生效日期倒序
            .order_by(PlatformRuleRecord.effective_date.desc())
        )).scalars().all()
        return [rule_to_dict(r) for r in rows]


async def get_rule_by_id(rule_id: str, shop_id: Optional[str] = None) -> Optional[PlatformRuleRecord]:
    """按主键取规则（带租户校验：给了 shop_id 就必须匹配）"""
    async with async_session_factory() as session:
        q = select(PlatformRuleRecord).where(PlatformRuleRecord.id == rule_id)
        if shop_id:
            q = scoped(q, PlatformRuleRecord, shop_id)
        return (await session.execute(q)).scalar_one_or_none()


async def create_rule(payload: dict, shop_id: Optional[str] = None) -> dict:
    """新建一条规则（**唯一写入口**；批量导入也走这里，见 create_rules_batch）"""
    async with async_session_factory() as session:
        record = build_rule_record(payload, shop_id=shop_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return rule_to_dict(record)


async def create_rules_batch(items: List[dict], shop_id: Optional[str] = None) -> dict:
    """
    批量写入（文件导入用）。

    与 monitors 的 batch-upsert 不同：规则**不做 upsert 合并**。
    前端对导入内容已有「查重标注 + 用户确认」两步（duplicate/update 由用户决定是否仍添加），
    到这一步就是「用户已确认要写」的最终动作，再合并反而违背用户意图。
    """
    async with async_session_factory() as session:
        records = [build_rule_record(it, shop_id=shop_id) for it in items]
        for r in records:
            session.add(r)
        await session.commit()
        for r in records:
            await session.refresh(r)
        return {"added": len(records), "items": [rule_to_dict(r) for r in records]}


async def update_rule(rule_id: str, payload: dict, shop_id: Optional[str] = None) -> Optional[dict]:
    """更新规则；记录不存在（或不属于该租户）返回 None"""
    async with async_session_factory() as session:
        q = select(PlatformRuleRecord).where(PlatformRuleRecord.id == rule_id)
        if shop_id:
            q = scoped(q, PlatformRuleRecord, shop_id)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return None
        apply_rule_fields(record, payload)
        record.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(record)
        return rule_to_dict(record)


async def delete_rule(rule_id: str, shop_id: Optional[str] = None) -> bool:
    """删除规则；不存在（或不属于该租户）返回 False"""
    async with async_session_factory() as session:
        q = select(PlatformRuleRecord).where(PlatformRuleRecord.id == rule_id)
        if shop_id:
            q = scoped(q, PlatformRuleRecord, shop_id)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return False
        await session.delete(record)
        await session.commit()
        return True


# ====== 文档素材：查询 / 写入 ======

async def list_docs(shop_id: Optional[str]) -> List[dict]:
    """列出该店铺的全部文档素材（不含正文，见模块注释）"""
    if not shop_id:
        return []
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(PlatformRuleDocRecord), PlatformRuleDocRecord, shop_id)
            .order_by(PlatformRuleDocRecord.uploaded_at.asc())
        )).scalars().all()
        return [doc_to_dict(d) for d in rows]


async def get_doc_by_id(doc_id: str, shop_id: Optional[str] = None) -> Optional[PlatformRuleDocRecord]:
    async with async_session_factory() as session:
        q = select(PlatformRuleDocRecord).where(PlatformRuleDocRecord.id == doc_id)
        if shop_id:
            q = scoped(q, PlatformRuleDocRecord, shop_id)
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
    """
    删除文档素材。

    注意：**不级联删除引用它的规则** —— 规则的 `source_doc_id` 是溯源自标，
    文档没了规则仍然有效（前端只把「查看原文」链接降级为纯文本）。
    删附件不该连带删掉业务数据。
    """
    async with async_session_factory() as session:
        q = select(PlatformRuleDocRecord).where(PlatformRuleDocRecord.id == doc_id)
        if shop_id:
            q = scoped(q, PlatformRuleDocRecord, shop_id)
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return False
        await session.delete(record)
        await session.commit()
        return True
