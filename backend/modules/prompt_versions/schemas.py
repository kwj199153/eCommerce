"""提示词覆写层 - API Schema（第 351 轮 · P0-7 B 档）

★ 请求体里**没有** `base_fingerprint`
    「这条覆写基于哪一版源码」是**服务端**从注册表现算的事实，不是客户端输入。
    让客户端传它，等于允许把一个错的基线写进库 —— 后果是 stale 闸门**永远不响**
    （库里那份基线永远"对得上"），而覆写静默盖掉别人改好的正文。
    与「归属只能服务端注入」是同一条判据：凡是服务端能算出真相的字段，
    就不该由客户端提供。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PromptVersionItem(BaseModel):
    """一条提示词在「源码 vs 覆写」两个视角下的合并状态。"""

    name: str
    #: active | stale | disabled | unknown-name | not-overridden
    status: str
    #: 当前生效版本（有覆写时是覆写版本，否则是源码版本）
    version: Optional[str] = None
    #: 覆写正文的指纹（无覆写时为空）
    fingerprint: Optional[str] = None
    #: 覆写写入时的源码基线（无覆写时为空）
    base_fingerprint: Optional[str] = None
    #: **当前源码**的指纹 —— stale 判定就是拿它与 `base_fingerprint` 比
    source_fingerprint: Optional[str] = None
    #: **运行态**：这条覆写是否已在内存注册表里生效。
    #: ★ 与 `status` 分开：`active` 只说明「能装上」，本字段说明「已经装上了」。
    #:   直接改库（没跑 `apply_all_overrides()`）时会出现 active 但 applied=False
    #:   —— 那正是需要显示给人看的状态，不能被合成一个字段掩盖掉。
    applied: bool = False
    #: 源码那一版的版本号
    source_version: Optional[str] = None
    enabled: bool = False
    note: Optional[str] = None
    updated_at: Optional[datetime] = None
    #: 当前生效正文声明了哪些变量（调用点契约）
    variables: List[str] = Field(default_factory=list)


class PromptVersionListResponse(BaseModel):
    items: List[PromptVersionItem]
    #: 已注册的模板总数（分母，便于前端显示「3 / 12 被覆写」）
    registered_total: int
    overridden_total: int
    #: 其中真正生效 / 被 stale 拦下 的数量
    applied_total: int
    stale_total: int


class PromptVersionUpsertRequest(BaseModel):
    """新建或替换一条覆写。"""

    content: str = Field(..., min_length=1, description="覆写正文")
    version: str = Field(default="1", min_length=1, description="覆写后的语义版本")
    note: Optional[str] = Field(default=None, description="为什么改（给人看）")


class PromptVersionEnabledRequest(BaseModel):
    enabled: bool


class PromptVersionApplyResult(BaseModel):
    """一次「同步到内存注册表」的结果。"""

    applied: List[str] = Field(default_factory=list)
    reset: List[str] = Field(default_factory=list)
    skipped: List[Dict[str, Any]] = Field(default_factory=list)
