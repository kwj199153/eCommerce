"""
平台规则库 API

数据源：PostgreSQL（platform_rules / platform_rule_docs 表），唯一权威源。

端点：
GET    /api/v1/platform-rules              - 规则 + 文档列表（一次拉全）
POST   /api/v1/platform-rules              - 新建规则
PUT    /api/v1/platform-rules/{rule_id}    - 更新规则
DELETE /api/v1/platform-rules/{rule_id}    - 删除规则
POST   /api/v1/platform-rules/batch        - 批量导入（文件解析后提交）
POST   /api/v1/platform-rules/ai-split     - AI 从文档正文拆分规则
POST   /api/v1/platform-rule-docs          - 登记文档素材
DELETE /api/v1/platform-rule-docs/{doc_id} - 删除文档素材

租户隔离：全部走 `get_current_shop_id`（X-Shop-ID 头）。
无租户上下文时列表返回空 —— 与 candidates / monitors / products 一致。

**路由注册顺序有讲究**：`/platform-rules/batch` 与 `/platform-rules/ai-split` 必须
注册在 `/platform-rules/{rule_id}` **之前**，否则会被当成 rule_id="batch" 匹配走。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.tenant.middleware import get_current_shop_id
from modules.platform_rules import service
from modules.platform_rules.ai_split import split_rules_from_doc

router = APIRouter(prefix="/api/v1", tags=["平台规则库"])


# ====== 规则 ======

@router.get("/platform-rules")
async def list_platform_rules(shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    规则 + 文档素材一次返回。

    前端 store 的 `items` 与 `docs` 是两个 state，但它们在同一个页面同时渲染，
    分两次请求只会多一次往返、还要处理两个 loading 态。一次拉全更贴合使用方式。
    """
    if not shop_id:
        return {"items": [], "docs": [], "total": 0}
    items = await service.list_rules(shop_id)
    docs = await service.list_docs(shop_id)
    return {"items": items, "docs": docs, "total": len(items)}


@router.post("/platform-rules", status_code=201)
async def create_platform_rule(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """新建一条规则。必填：标题 + 正文（平台/分类/生效日期都有默认值）"""
    missing = service.missing_required_fields(payload)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"缺少必填字段：{service.describe_missing_fields(missing)}",
        )
    return await service.create_rule(payload, shop_id=shop_id)


@router.post("/platform-rules/batch")
async def batch_create_platform_rules(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    批量导入（前端解析 JSON/CSV/TXT 后提交）。

    逐条校验必填：导入的文件常有缺字段的行，整批 422 会让用户不知道哪行坏了。
    改为「跳过坏行 + 返回 skipped 计数」，前端已有 errors 列表可对照。
    """
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="items 不能为空")

    valid = [it for it in items if isinstance(it, dict) and not service.missing_required_fields(it)]
    skipped = len(items) - len(valid)
    if not valid:
        raise HTTPException(
            status_code=422,
            detail="全部条目都缺少必填字段（规则标题 / 规则正文）",
        )
    result = await service.create_rules_batch(valid, shop_id=shop_id)
    result["skipped"] = skipped
    return result


@router.post("/platform-rules/ai-split")
async def ai_split_rules(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    从文档正文用 LLM 提取结构化规则（返回结果**未标注查重**，由前端补 _dupStatus）。

    LLM 不可用 / 文档无正文时返回 `degraded=True` + 空数组 + 中文原因，
    **绝不返回编造的规则** —— 前端据此提示「AI 拆分暂不可用」。
    """
    doc_id = (payload or {}).get("doc_id") or (payload or {}).get("docId")
    if not doc_id:
        raise HTTPException(status_code=422, detail="doc_id 不能为空")
    doc = await service.get_doc_by_id(doc_id, shop_id=shop_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return await split_rules_from_doc(doc)


@router.put("/platform-rules/{rule_id}")
async def update_platform_rule(
    rule_id: str,
    payload: dict,
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    result = await service.update_rule(rule_id, payload, shop_id=shop_id)
    if result is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return result


@router.delete("/platform-rules/{rule_id}")
async def delete_platform_rule(rule_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ok = await service.delete_rule(rule_id, shop_id=shop_id)
    if not ok:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"message": "规则已删除", "id": rule_id}


# ====== 文档素材 ======

@router.post("/platform-rule-docs", status_code=201)
async def create_platform_rule_doc(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """登记一篇文档素材。正文（content）可选 —— 上传只登记元数据时为空"""
    if not (payload or {}).get("filename", "").strip():
        raise HTTPException(status_code=422, detail="文件名不能为空")
    return await service.create_doc(payload, shop_id=shop_id)


@router.get("/platform-rule-docs/{doc_id}")
async def get_platform_rule_doc(doc_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    取单篇文档**含正文**。

    列表接口刻意不返回 content（正文动辄数千字符，一次拉 5 篇只是为了让用户点开其中一篇）。
    来源文档预览改为点开时按需拉取这一条。
    """
    doc = await service.get_doc_by_id(doc_id, shop_id=shop_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return service.doc_to_dict(doc, include_content=True)


@router.delete("/platform-rule-docs/{doc_id}")
async def delete_platform_rule_doc(doc_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    删除文档素材。**不级联删除引用它的规则**：source_doc_id 只是溯源自标，
    文档没了规则依然有效，删附件不该连带删业务数据。
    """
    ok = await service.delete_doc(doc_id, shop_id=shop_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"message": "文档已删除", "id": doc_id}
