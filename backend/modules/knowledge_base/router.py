"""
业务话术库 API

数据源：PostgreSQL（knowledge_bases / knowledge_faqs / knowledge_docs），唯一权威源。

端点：
GET    /api/v1/knowledge-base                    - 容器 + 话术 + 文档一次拉全
POST   /api/v1/knowledge-base                    - 新建知识库容器
PUT    /api/v1/knowledge-base/{kb_id}            - 重命名 / 改描述
DELETE /api/v1/knowledge-base/{kb_id}            - 删除容器（级联删其下话术与文档）
POST   /api/v1/knowledge-base/faqs               - 新建话术
POST   /api/v1/knowledge-base/faqs/batch         - 批量导入（文件解析后提交）
POST   /api/v1/knowledge-base/faqs/batch-delete  - 批量删除（勾选删除）
PUT    /api/v1/knowledge-base/faqs/{faq_id}      - 更新话术
DELETE /api/v1/knowledge-base/faqs/{faq_id}      - 删除话术
POST   /api/v1/knowledge-base/docs               - 登记文档素材
GET    /api/v1/knowledge-base/docs/{doc_id}      - 取单篇文档（含正文）
DELETE /api/v1/knowledge-base/docs/{doc_id}      - 删除文档素材

租户隔离：全部走 `get_current_shop_id`（X-Shop-ID 头）。
无租户上下文时列表返回空 —— 与 candidates / monitors / platform-rules 一致。

**路由注册顺序有讲究**：`/knowledge-base/faqs/batch` 与
`/knowledge-base/faqs/batch-delete` 必须注册在 `/knowledge-base/faqs/{faq_id}` **之前**，
否则会被当成 faq_id="batch" / "batch-delete" 匹配走。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.tenant.middleware import get_current_shop_id
from modules.knowledge_base import service

router = APIRouter(prefix="/api/v1", tags=["业务话术库"])


# ====== 一次性拉全 ======

@router.get("/knowledge-base")
async def list_knowledge_base(shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    容器 + 话术 + 文档一次返回。

    前端 store 的 `knowledgeBases` / `items` / `docs` 是三个 state，但同页渲染；
    而且话术与文档在服务端**按 kb_id 分组展示**，分三次请求只会多两次往返、
    还要处理三个 loading 态。一次拉全更贴合使用方式。
    """
    if not shop_id:
        return {"bases": [], "faqs": [], "docs": [], "total": 0}
    bases = await service.list_knowledge_bases(shop_id)
    faqs = await service.list_faqs(shop_id)
    docs = await service.list_docs(shop_id)
    return {"bases": bases, "faqs": faqs, "docs": docs, "total": len(faqs)}


# ====== 知识库容器 ======

@router.post("/knowledge-base", status_code=201)
async def create_knowledge_base(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """新建知识库容器。必填：名称（图标/类型/描述有默认值）"""
    missing = service.missing_required_fields(payload, service.KB_REQUIRED_FIELDS)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"缺少必填字段：{service.describe_missing_fields(missing)}",
        )
    return await service.create_kb(payload, shop_id=shop_id)


@router.put("/knowledge-base/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    payload: dict,
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    result = await service.update_kb(kb_id, payload, shop_id=shop_id)
    if result is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return result


@router.delete("/knowledge-base/{kb_id}")
async def delete_knowledge_base(kb_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    删除知识库容器，**级联删除**其下话术与文档。

    返回 `deleted_faqs` / `deleted_docs` 计数，前端据此提示「已删除 N 条话术」——
    静默连删会让用户以为只删了个空文件夹。
    """
    result = await service.delete_kb(kb_id, shop_id=shop_id)
    if result is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"message": "知识库已删除", "id": kb_id, **result}


# ====== 话术条目 ======

@router.post("/knowledge-base/faqs", status_code=201)
async def create_faq(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """新建一条话术。必填：所属知识库 + 问题 + 答案"""
    missing = service.missing_required_fields(payload, service.FAQ_REQUIRED_FIELDS)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"缺少必填字段：{service.describe_missing_fields(missing)}",
        )
    return await service.create_faq(payload, shop_id=shop_id)


@router.post("/knowledge-base/faqs/batch")
async def batch_create_faqs(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    批量导入（前端解析 CSV / JSON / TXT 后提交）。

    逐条校验必填：导入文件常有缺字段的行，整批 422 会让用户不知道哪行坏了。
    改为「跳过坏行 + 返回 skipped 计数」，前端已有 errors 列表可对照。
    """
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="items 不能为空")

    valid = [
        it for it in items
        if isinstance(it, dict) and not service.missing_required_fields(it, service.FAQ_REQUIRED_FIELDS)
    ]
    skipped = len(items) - len(valid)
    if not valid:
        raise HTTPException(status_code=422, detail="全部条目都缺少必填字段（所属知识库 / 问题 / 答案）")
    result = await service.create_faqs_batch(valid, shop_id=shop_id)
    result["skipped"] = skipped
    return result


@router.post("/knowledge-base/faqs/batch-delete")
async def batch_delete_faqs(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """批量删除（列表勾选删除）。返回实际删除条数"""
    ids = (payload or {}).get("ids")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=422, detail="ids 不能为空")
    deleted = await service.delete_faqs_batch(ids, shop_id=shop_id)
    return {"deleted": deleted, "ids": ids}


@router.put("/knowledge-base/faqs/{faq_id}")
async def update_faq(
    faq_id: str,
    payload: dict,
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    result = await service.update_faq(faq_id, payload, shop_id=shop_id)
    if result is None:
        raise HTTPException(status_code=404, detail="话术不存在")
    return result


@router.delete("/knowledge-base/faqs/{faq_id}")
async def delete_faq(faq_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ok = await service.delete_faq(faq_id, shop_id=shop_id)
    if not ok:
        raise HTTPException(status_code=404, detail="话术不存在")
    return {"message": "话术已删除", "id": faq_id}


# ====== 文档素材 ======

@router.post("/knowledge-base/docs", status_code=201)
async def create_doc(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """登记一篇文档素材。必填：所属知识库 + 文件名；正文（content）可选"""
    missing = service.missing_required_fields(payload, service.DOC_REQUIRED_FIELDS)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"缺少必填字段：{service.describe_missing_fields(missing)}",
        )
    return await service.create_doc(payload, shop_id=shop_id)


@router.get("/knowledge-base/docs/{doc_id}")
async def get_doc(doc_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    取单篇文档**含正文**。

    列表接口刻意不返回 content（整篇动辄数千字符，一次拉全库只是为了让用户点开一篇）。
    """
    doc = await service.get_doc_by_id(doc_id, shop_id=shop_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return service.doc_to_dict(doc, include_content=True)


@router.delete("/knowledge-base/docs/{doc_id}")
async def delete_doc(doc_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ok = await service.delete_doc(doc_id, shop_id=shop_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"message": "文档已删除", "id": doc_id}
