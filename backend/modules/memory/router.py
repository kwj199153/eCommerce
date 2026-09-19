"""长期记忆 HTTP 面（第 149 轮 批 C2-3）。

端点清单
========
    GET  /api/v1/memory           读：开关 + 记忆全文 + 上限（一次给全）
    PUT  /api/v1/memory           写：提交**整份** markdown（编辑器里看到的就是全集）
    PUT  /api/v1/memory/profile   写：开关
    POST /api/v1/memory/reset     写：清空全部条目（开关保留）
    GET  /api/v1/memory/logs      读：学习时间线

★ 归属（`owner_id`）**不出现在任何请求体 / 查询参数里**
=====================================================
它一律取自服务端身份（`current_user.id`）。请求体里带 `owner_id`
是本项目真实踩过的洞 —— `ConversationCreateRequest.owner_id` 曾是客户端自报字段，
实测能把自己的会话挂到别人名下（落库 `owner_id=<受害者的 id>`）。
所以这里**从一开始**就没有这个字段，而不是"先有再删"。
★ 客户端照旧发 `owner_id` 不会 422（pydantic 默认忽略多余字段），但**不会被采纳**。

★★ 为什么本路由**不挂** `BUSINESS_AUTH`
=====================================
`BUSINESS_AUTH` 是 **optional-auth**：它允许「完全不带凭据 + `AUTH_REQUIRED=false`」
这一档返回 `None`。而长期记忆按**人**归属 —— 匿名会话没有可归属的对象，
也就不存在「可降级形态」（业务数据能降级成"演示数据"，记忆不能：
一份不属于任何人的记忆，谁都读不到，却会一直被每晚任务花钱整理）。
⇒ 本模块各端点**各自**声明 `require_authenticated_user`（fail-closed）。

★ 这不是"路由级挂一层就够了"的重复劳动：路由级依赖**不向 handler 注入参数**。
  只挂路由级的话 handler 根本拿不到 `current_user`，也就无从取 `owner_id`
  —— 这正是 `conversation/router.py` 修过的那个形态
  （"路由挂了一层依赖"看起来像有鉴权，实际只是挡住了匿名）。

★ 为什么不挂 `API_QUOTA`
  本路由全是 CRUD，不烧钱。挂上去的后果是「配额用完的用户连自己的记忆都改不了」
  —— 与 `main.py` 里「纯 CRUD 不挂配额」是同一条判据。
  真正会调模型的「立即整理」端点由它**自己**声明配额依赖（C2-4 落地）。

★ `POST /memory/distill`（"立即整理"）**随 C2-4 一起落地**
  这个端点在 C2-3 时刻意缺席：它必须与 `modules/memory/tasks.py`（Celery 任务）
  同时存在，否则就是**新的空承诺** —— 而 r141 判定本模块是「假页面」的依据，
  恰恰是「界面承诺了后端没实现的事」。现在两者同日出现，且共用**同一个实现**
  （`tasks.distill_one_owner`）：手动与夜间走同一条路径，
  不存在「手动的能跑、夜间的没接上」这种只有一边被测到的形态。

★ 本模块里**只有这一个**端点声明配额
  其余四个都是纯 CRUD，不烧钱（挂上去只会让配额用完的用户连自己的记忆都改不了）。
  `distill` 会调模型 ⇒ 由它**自己**声明 `check_api_quota`。
  ★ 不通过 `main.py` 的 `API_QUOTA` 列表挂 —— 那是**路由级**的，
    挂上去会把同一路由下的 CRUD 一起计费。
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import require_authenticated_user
from core.database import get_db
from core.identity.models import User
from core.metering.usage_tracker import check_api_quota

from . import service, tasks

router = APIRouter(prefix="/memory", tags=["长期记忆"])


#: 本模块的身份依赖。`what` 只影响 401 的文案
#: （要让用户知道"是记忆功能需要登录"，而不是笼统的"该功能需要登录"）。
#:
#: ★ 为什么**必须**是一个真的 `async def`，不能图省事写成
#:   `partial(require_authenticated_user, what="长期记忆")`
#:   ——★ 第 153 轮实测事故，本模块 6 个端点曾因此 100% 500：
#:
#:   FastAPI 判「这个依赖要不要 await」用的**不是** `asyncio.iscoroutinefunction`，
#:   而是它自己的 `is_coroutine_callable`（`fastapi/dependencies/utils.py`）：
#:
#:       isroutine(call)  → iscoroutinefunction(call)     # 普通函数/方法：看它自己
#:       isclass(call)    → False                         # 类不算协程
#:       否则             → iscoroutinefunction(call.__call__)
#:
#:   `functools.partial` 既不是 routine 也不是 class（它是个**对象**），
#:   落到第三支 —— 而 `partial.__call__` 是**同步**的 C 方法包装 ⇒ 判为 False
#:   ⇒ **不 await**，直接把**协程对象**当身份注入 handler。
#:   同一对象、同一进程里的三个判定值（实测）：
#:
#:       asyncio.iscoroutinefunction(partial)   → True    ← 直觉会信的那一个
#:       is_coroutine_callable(partial)         → False   ← FastAPI 真正问的那一个
#:       str(partial)                           → 含 "require_authenticated_user"
#:
#:   后果不是 401 而是 **500**：handler 里 `current_user.id` 报
#:   `AttributeError: 'coroutine' object has no attribute 'id'`。
#:
#: ★ 为什么当时三套既有验证全绿（各自差一层，缺一不可）：
#:   * `tests/test_memory_distill.py` 的 dependant 树断言对依赖名做**子串**匹配，
#:     而 `str(partial)` 恰好含 `require_authenticated_user` ⇒ 只能判「挂没挂」，
#:     判不出「挂上去能不能用」（第 153 轮已补形态断言 + 全应用门禁）；
#:   * `r150_probe_c24.py`（115/115）与全部服务层测试都**绕过 HTTP** 直接调
#:     service ⇒ 缺陷在**依赖注入层**，绕过去就永久看不见；
#:   * 前端那时是假页面（r141 判定）⇒ 没有任何真调用会踩到它。
#:   * 还有第二个症状：`scripts/auth_coverage_report.py` 按 `__name__` 白名单
#:     判定，而 partial 没有 `__name__` ⇒ 体检报告把本模块报成
#:     **`memory 6 端点 0% <-- 无鉴权`**，与事实完全相反（它本是 fail-closed 的）。
#:
#: ★ 当初写 partial 的动机没变，也别丢：**不重抄 `request` / `db` 的注入链**。
#:   下面的 wrapper 把两者原样转交给唯一实现（判定逻辑仍只有一份），
#:   形态与 `core/auth/accounts_router.py::_current_user` 完全一致 ——
#:   那是本仓**已经跑通的惯用写法**，不新造第二种。
#:   ★ `request` 必须写**裸 `Request`**，不能写 `Optional[Request]`：
#:     `core/auth/dependencies.py` 那段「写 Union 会让整个应用起不来」的教训
#:     就在这条链上。
async def _REQUIRE_USER(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """fail-closed 身份门；主语固定为「长期记忆」，只影响 401 文案。"""
    return await require_authenticated_user(request, db, what="长期记忆")


class ProfileUpdateRequest(BaseModel):
    """开关入参。★ 只有这一个字段 —— 归属类字段一律不进请求体（见模块 docstring）。"""

    enabled: bool = Field(..., description="是否允许 AI 从对话中提取并记住上下文")


class MemorySaveRequest(BaseModel):
    """保存入参。

    * `markdown`：整份内容。假页面里那个 textarea 提交的就是它 ——
      存储形态是条目、I/O 形态是 markdown，转换只发生在后端一处
      （见 `ai_infra/memory/entry.py` 的论证：前端自己拼/拆 markdown
      就是第二个解析实现）。
    * `source`：`manual`（编辑器保存）或 `import`（导入文件）。
      ★ 客户端能选它，是因为只有客户端知道这次是"手打"还是"导入文件"；
        但服务端会**再校验一次**（`service.USER_SOURCES`），
        `distill` 不接受自报 —— 那会让用户内容被标成"AI 猜测"从而优先被挤掉，
        而他完全看不出这件事发生过。
    """

    markdown: str = Field("", description="整份长期记忆的 markdown")
    source: str = Field("manual", description="manual / import")


class ProfileResponse(BaseModel):
    profile: dict = Field(default_factory=dict, description="{enabled, last_distilled_at}")


class MemoryResponse(BaseModel):
    profile: dict = Field(default_factory=dict)
    markdown: str = Field("", description="记忆全文（空串 = 真的没有内容）")
    entries: list = Field(default_factory=list)
    entry_count: int = 0
    updated_at: str | None = None
    limits: dict = Field(default_factory=dict, description="上限口径（后端真源，前端不要再写一份）")


class LogsResponse(BaseModel):
    logs: list = Field(default_factory=list)


@router.get("", response_model=MemoryResponse, summary="读取长期记忆与开关状态")
async def get_memory(current_user: User = Depends(_REQUIRE_USER)):
    """开关 + 记忆全文 + 条目 + 上限。

    ★ 空记忆返回 `markdown: ""` 而**不是**一段占位文案（如"暂无记忆"）：
      占位文案一旦进了文本就会被 `parse_markdown` 读成**一条真实的记忆**，
      从此每次整理都要为它费一次去重、占一格配额，
      而用户会看到一条自己从没写过的内容。空状态由前端渲染。
    """
    return await service.snapshot(current_user.id)


@router.put("", response_model=MemoryResponse, summary="保存整份长期记忆")
async def save_memory(
    request: MemorySaveRequest,
    current_user: User = Depends(_REQUIRE_USER),
):
    """整批替换。**超限 ⇒ 400**（附"第几条超了"的人话清单），不静默截断。

    ★ 返回保存之后的**完整快照**（与 `GET` 同一个实现）：
      前端拿到它直接重渲染，不需要再发一次 GET —— 也就不会出现
      "保存成功但界面还是旧内容"这种要刷新才对的中间态。
    """
    return await service.save_memory(
        current_user.id, request.markdown, source=request.source
    )


@router.put("/profile", response_model=ProfileResponse, summary="更新记忆开关")
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(_REQUIRE_USER),
):
    """写开关。返回库里的**权威值**，由前端回写本地开关状态。"""
    return await service.set_enabled(current_user.id, request.enabled)


@router.post("/reset", response_model=MemoryResponse, summary="重置长期记忆")
async def reset_memory(current_user: User = Depends(_REQUIRE_USER)):
    """清空全部条目，**保留开关**（要停止学习请用开关，那是它存在的意义）。"""
    return await service.reset_memory(current_user.id)


@router.get("/logs", response_model=LogsResponse, summary="读取学习时间线")
async def list_logs(
    limit: int = 30,
    current_user: User = Depends(_REQUIRE_USER),
):
    """时间线（倒序）。`is_failure` 由后端给出，前端不要再列一遍 `kind` 名单。"""
    return {"logs": await service.list_logs(current_user.id, limit=limit)}


class DistillResponse(BaseModel):
    """「立即整理」的返回。

    ★ 刻意**同时**返回 `result`（这次做了什么）与 `memory`（做完之后的状态）：
      只返回 result 的话，前端要再发一次 GET 才能刷新界面 ——
      于是出现"整理成功但界面还是旧的"这个中间态，用户会再点一次
      （= 再烧一次钱）。与本模块 `PUT /memory` 返回完整快照是同一条判据。
    """

    result: dict = Field(
        default_factory=dict,
        description="{ran, ok, reason, error, summary, content, elapsed_ms}",
    )
    memory: MemoryResponse


@router.post("/distill", response_model=DistillResponse, summary="立即整理一次长期记忆")
async def distill_now(
    current_user: User = Depends(_REQUIRE_USER),
    # ★ 参数名带下划线前缀是**刻意**的：它只为副作用（配额检查）而存在，
    #   端点体里用不到它。命名成 `quota` 会让人以为能读它。
    _quota=Depends(check_api_quota),
):
    """从最近的对话里抽取新的长期记忆（**同步执行**，会调模型）。

    三种结局都会**如实返回**，界面必须分别渲染：

        result.ran == False           —— 没跑；`content` 是人话原因，`reason` 是原因代码
        result.ran and result.ok      —— 跑了且成功（`summary` / `content`）
        result.ran and not result.ok  —— 跑了但失败（`error`；时间线里也有一条 `distill_failed`）

    ★ 失败**不**用 5xx：这不是"请求错误"，而是这次整理的**业务结论**。
      用 500 会让前端落进通用错误分支，于是只剩一个 toast ——
      而用户需要同时看到"跑过了 + 失败了 + 时间线里有一条记录"这三件事。
      （HTTP 200 包装业务失败**不构成「伪成功」**：判据是 `ok` 字段而不是状态码。
        r141 记的 `/competitor/compare` 那条教训的问题恰恰相反 ——
        它返回 `success: true`，把错误塞进 `data.error` 里。）

    ★ 同步执行、不投 Celery：手动点击的期望是"现在就有结果"。
      投递后立刻返回 202 的话，用户拿到的只是一张空收据，
      而真正花掉的钱和结果都得靠轮询时间线才能看到。
      （夜间那条路径必须异步 —— 那是无人等待的批量任务，见 `tasks.py`。）

    ★ `force=True`：手动点击的语义是"我现在就要一次，别管夜间调度跑过没有"。
      但它**绕不过**两道闸门（开关关着 / 60 秒内连点），理由见
      `service.claim_distill_run`。
    """
    result = await tasks.distill_one_owner(
        current_user.id, force=True, action="立即整理"
    )
    return {"result": result, "memory": await service.snapshot(current_user.id)}
