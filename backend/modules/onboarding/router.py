"""「加载示例数据」的 HTTP 契约面（第 387 轮 · 网站管理员 P0-2）

为什么这个端点是 POST 而不是 GET：它**写库**（往当前店铺灌示例数据）。
用 GET 会让浏览器预取 / 爬虫 / 「刷新一下」都变成写操作。

★ 归属校验不在本文件：`get_current_shop_id` 是 `X-Shop-ID` 解析与归属判定的
  **唯一真源**（`core/tenant/middleware.py`，含 `account_id ∈ 可见账户集合`
  判定，不符 403）。这里再抄一份就是两份实现，必然漂移，且必有一份测不到。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.tenant.middleware import get_current_shop_id
from modules.onboarding.service import SampleTargetMissing, load_sample_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/sample-data", response_model=dict)
async def load_sample_data_endpoint(
    shop_id: Optional[str] = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    """给**当前选中的店铺**灌一份示例数据（幂等）。

    响应里 `is_sample=true` + `label` 是**契约的一部分**：前端必须据此标注
    「这是示例数据，不是真实平台数据」。删掉这两个字段会让界面无从区分，
    于是示例数据会以「真实数据」的样子出现在公开站上 —— 那正是本仓最忌讳的
    一类缺陷（假数据冒充实测）。

    ★ `nothing_new=true` 不等于失败：各 seed 是 `*_if_empty`，该店已有数据时
      不重复写。前端应显示「示例数据已存在」，而不是「加载失败」或「加载成功」。
    """
    if not shop_id:
        # `get_current_shop_id` 对写方法已经会 400，这里是第二道（防御性）：
        # 将来若有人把它换成 `_optional` 版本，这里仍不会静默灌到空 id 上。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择店铺（缺少 X-Shop-ID）",
        )

    try:
        data = await load_sample_data(shop_id)
    except SampleTargetMissing as exc:
        # ★ 404 而不是 200：店铺不存在时「加载成功」是纯假成功。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"店铺不存在：{exc.shop_id}",
        ) from exc

    return {"success": True, "data": data}
