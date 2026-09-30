"""
交易履约 + 买家反馈域 —— HTTP 出口（第 287 轮 P0-2 新建）

★ 为什么本模块此前**没有** router
--------------------------------
`modules/trade` 一直是「有模型、有 service、有工具、没端点」的状态：
`customer_reviews` / `review_attributions` / `review_dispositions` 三张表
只能通过 Agent 工具（`trade_tools`）间接到达。于是 `review_dispositions`
成了三无表 —— 全库 0 行、无 HTTP 端点、前端零消费。本文件补的就是这个出口。

★ 归属口径
--------------------------------
`X-Shop-ID` 一律由 `Depends(get_current_shop_id)` 解析（strict 版：**写方法**
缺头直接在依赖解析阶段 400，零数据库往返）。请求体里**没有** `store_id`
字段 ⇒ 结构上不可能被客户端指定归属。

读端点拿到空 `store_id` 时**不返回空列表**，而是 400「请先选择店铺」：
本模块的数据全是租户隔离的，「还没选店铺」与「这家店没有处置记录」
是两件不同的事 —— 混成同一个空列表，界面上看着一模一样，
用户会得出「这家店不用处理差评」的错误结论（本仓：失败必须能归因）。

★ 为什么「批准人 / 发放人」不从请求体取
--------------------------------
`approver` / `actor` 一律由 `require_acting_user` **服务端注入**。
让客户端自己报「我是张三批的」等于把审计字段做成了可伪造项 ——
与 `create_ticket` 的 `store_id` 形参是同一类老毛病。请求体里
**没有**这两个字段（pydantic 会忽略多余字段，但物理上没有落点）。

★ 异常映射收在一处（`_guard`）
--------------------------------
`DispositionNotFound` ⇒ 404（「不存在」与「不属于本店」同一句，防枚举）；
`DispositionError` ⇒ 400（状态机/取值不合法，是请求形状问题）；
其余 ⇒ 500。三个端点族（草稿 / 提议 / 审批发放）共用这一个映射点，
不在下面各写一遍（同一判定两份实现 ⇒ 至少一份永远测不到）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth.dependencies import require_acting_user
from core.tenant.middleware import get_current_shop_id
from core.database import async_session_factory
from core.logger import get_logger

from . import service

_log = get_logger("modules.trade.router")

router = APIRouter(prefix="/api/v1/trade", tags=["差评处置"])


# ============================================================ 请求体
#
# ★ 这些模型只做**类型**约束，不做业务校验：通道值域、状态转移合法性
#   的唯一实现在 `service`（`DISPOSITION_CHANNELS` / `DISPOSITION_TRANSITIONS`）。
#   在 pydantic 上再写一遍 `Literal[...]` 就是两份实现，HTTP 那条会让
#   service 那份变成永远测不到（本仓铁律）。

class ProposeDispositionBody(BaseModel):
    """生成 / 更新一条 `proposed` 处置。

    所有处置内容字段都可留空 ⇒ 由 `service.build_disposition_draft` 现算填上
    （响应里的 `draft_filled=True` 表示用了现算的那份）。
    """
    review_id: str = Field(..., description="评价 id 或平台侧评价 id")
    channels: Optional[list[str]] = Field(
        None, description="处置通道，留空按规则推导（reply/coupon/refund/reship/escalate）")
    compensation: Optional[dict] = Field(
        None, description='补偿方案，如 {"type":"coupon","amount":8,"currency":"USD"}')
    coupon_code: str = ""
    reply_draft_en: str = ""
    reply_draft_zh: str = ""
    ticket_id: Optional[str] = None
    notes: str = ""


class RejectDispositionBody(BaseModel):
    notes: str = Field("", description="驳回原因（会追加进 notes）")


class ExecutionReceiptBody(BaseModel):
    """登记「平台上真的执行完了」的回执（`issued` → `executed`）。

    ★ 请求体里**没有** `executed_by`：与 `approver` / `actor` 同一条口径，
      登记人由**服务端注入** —— 让客户端自报「张三在平台上做完了」等于把
      审计字段做成可伪造项。

    ★ `platform_ref` 可以留空：人工在后台做退款未必拿得到单一凭证号。
      空 = 「做了但没凭证」；「没做」的判据是**这一行存不存在**。
    """
    execution_mode: str = Field(
        "manual", description="执行方式；当前只接受 manual（人工在平台执行后登记）")
    platform_ref: str = Field(
        "", description="平台侧凭证号：退款单号 / 券码 / case id；拿不到就留空")
    receipt_note: str = Field("", description="回执备注（做了什么、在哪做的）")


class AttributionBody(BaseModel):
    """**手工**给一条差评指定归因（`primary_cause`）。

    ★ `evidence` / `notes` 可选：人工补标常常只有「我看了内容，是物流问题」
      这一句依据，硬要他填结构化证据只会逼出假证据。
    """
    primary_cause: str = Field(
        ..., description="归因取值；必须是 ATTRIBUTION_CAUSES 之一，**不接受 unknown**")
    causes: Optional[list[str]] = Field(None, description="次要成因（留空沿用原值）")
    evidence: Optional[list] = Field(None, description="证据条目（留空沿用原值）")
    notes: str = Field("", description="补标依据 / 备注（会作为一条 manual 证据附上）")


class RuleCreateBody(BaseModel):
    """新建补偿规则。

    ★ 形状校验**不在这里**做（pydantic 上再写一遍就是两份实现）：
      值域 / 条件键 / 金额正负的唯一实现在 `service._validate_rule_shape`。
    """
    code: str = Field(..., description="规则代号（同店唯一；小写字母/数字/连字符）")
    name: str = Field("", description="规则名称（留空用 code）")
    cause: str = Field(..., description="针对哪个归因（不接受 unknown）")
    priority: int = Field(100, description="优先级，小者优先")
    conditions: Optional[dict] = Field(
        None, description='命中条件，如 {"max_rating":3,"min_delay_days":3}')
    action: Optional[dict] = Field(
        None, description='补偿方案，如 {"type":"coupon","amount":8,"currency":"USD"}')
    budget_cap: float = Field(0, description="单笔硬上限；<= 0 表示未设上限")
    enabled: bool = Field(True, description="是否启用")
    notes: str = Field("", description="备注")


class RuleUpdateBody(BaseModel):
    """部分更新补偿规则 —— **只改传进来的字段**（`code` 不可改）。"""
    name: Optional[str] = None
    cause: Optional[str] = None
    priority: Optional[int] = None
    conditions: Optional[dict] = None
    action: Optional[dict] = None
    budget_cap: Optional[float] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


# ============================================================ 统一异常映射

async def _guard(fn, label: str, *args, **kwargs):
    """唯一异常映射点。"""
    try:
        return await fn(*args, **kwargs)
    except service.DispositionNotFound as e:
        # ★「不存在」与「不属于本店」同一句 404（可区分即可枚举）
        raise HTTPException(status_code=404, detail=str(e))
    except service.DispositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # ★ 规则 / 归因的形状问题同样是 4xx（同一异常映射点，不另写一份）
    except (service.RuleError, service.AttributionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.RuleConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (service.RuleNotFound, service.AttributionNotFound) as e:
        # ★「不存在」与「不属于本店」同一句（可区分即可枚举）
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # pragma: no cover - 兜底
        _log.error("差评处置端点异常 label=%s err=%s", label, e)
        raise HTTPException(status_code=500, detail=f"{label}失败: {str(e)}")


def _require_shop(store_id: Optional[str]) -> str:
    """读端点的店铺守卫 —— 缺店铺 400，不放宽成空列表。"""
    if not (store_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail="缺少店铺上下文（X-Shop-ID）—— 请先选择店铺；"
                   "差评与处置都是租户隔离数据，不提供「跨店汇总」这一档。",
        )
    return store_id.strip()


def _actor_name(user) -> str:
    """把「行动者」投影成一个可审计的名字（服务端注入，客户端给不了）。"""
    return getattr(user, "email", None) or getattr(user, "id", "") or ""


# ============================================================ 读：草稿建议

@router.get("/dispositions/{review_id}/draft", summary="处置草稿建议（不落库）")
async def draft_disposition(
    review_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """按「归因 + 补偿规则」合成一份待批准建议 —— **不落库、不发券、不退款**。

    `ready=false` 时看 `reason`：没归因 / 没启用规则 / 超预算，三种原因分开报。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.build_disposition_draft, "生成处置草稿", session, shop, review_id,
        )


# ============================================================ 写：提议 / 批量补生成

@router.post("/dispositions", summary="生成或更新一条待批准处置")
async def propose_disposition(
    body: ProposeDispositionBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """写入 / 更新 `proposed` 处置（**唯一写入路径**，与 Agent 工具、脚本共用）。

    ★ `approved` / `issued` 的既有记录**拒绝被覆盖**（400）——
      券码已经生成就是既成事实，重跑归因改不了它。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.propose_disposition, "生成处置", session, shop, body.review_id,
            channels=body.channels, compensation=body.compensation,
            coupon_code=body.coupon_code, reply_draft_en=body.reply_draft_en,
            reply_draft_zh=body.reply_draft_zh, ticket_id=body.ticket_id,
            notes=body.notes,
        )


@router.post("/dispositions/backfill", summary="给有归因的差评批量补生成处置")
async def backfill_dispositions(
    limit: int = 50,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """给「有归因但还没有处置」的中差评批量生成 `proposed` 草稿（**幂等**：已有则跳过）。

    ★ 为什么要有这个端点：补好写入路径之后表里**仍然可能是 0 行**
      （历史差评从未被处置过）。没有它，「补出口」就只是补了一根空管道。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.backfill_dispositions, "批量生成处置", session, shop, limit=limit,
        )


# ============================================================ 读：列表 / 详情

@router.get("/dispositions", summary="列出本店铺的差评处置")
async def list_dispositions(
    status: Optional[str] = None,
    limit: int = 50,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """列出处置（新 → 旧），带所属评价摘要（界面要显示「这是哪条差评」）。

    - **status**: `proposed` / `approved` / `issued` / `executed` / `rejected`，
      留空看全部；非法值 ⇒ 400（不静默忽略成「看全部」）。
      ★ `issued` ≠ `executed`：前者是本地已核准，后者是平台上真的执行完了。
    - **total**: 真实条数（不受 `limit` 截断）—— 列表页的「共 N 条」要它。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        items = await _guard(
            service.list_dispositions, "读取处置列表", session, shop,
            status=status, limit=limit,
        )
        total = await _guard(
            service.count_dispositions, "统计处置", session, shop, status=status,
        )
    return {"items": items, "total": total}


@router.get("/dispositions/{review_id}", summary="处置详情")
async def get_disposition(
    review_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """取一条处置（含所属评价摘要）。没有 ⇒ 404。"""
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        item = await _guard(
            service.get_disposition, "读取处置详情", session, shop, review_id,
        )
    if item is None:
        raise HTTPException(status_code=404, detail="这条评价还没有处置记录")
    return item


# ============================================================ 读：产品 ↔ 差评 关联
#
# ★ 这两个端点是同一个问题的两半：
#     左边 = 「某个产品名下有哪些差评」（产品详情的差评 tab）
#     右边 = 「哪些差评谁都没认领」（孤儿兜底列表）
#   只做一半 ⇒ 另一半静默丢失：软关联没有外键兜，join 不上不会报错，
#   只会变成一个谁也发现不了的 0。

@router.get("/reviews", summary="本店铺近期的中差评（工作台主列表）")
async def list_recent_reviews(
    max_rating: int = 3,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """差评工作台的主列表 —— 「本店最近发生了哪些中差评」。

    ★ 为什么 endpoint 要补：`service.list_recent_negative_reviews` 此前只有
      Agent 工具一个调用点，HTTP 面没有出口 ⇒ 前端工作台拿不到差评清单，
      只能退而用「处置列表」（那只覆盖**已经处置过**的差评，历史差评全是 0
      处置 ⇒ 列表永远空白）。差评以**差评**为主语，处置以**处置**为主语，
      两者不可互相替代。

    - **total**: 真实条数（另行 count，不受 `limit` 截断）。
    - 缺 `X-Shop-ID` ⇒ 400，不返回空列表（本模块一律不提供「跨店汇总」这一档）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        items = await _guard(
            service.list_recent_negative_reviews, "读取近期差评", session, shop,
            max_rating=max_rating, days=days, limit=limit, offset=offset,
        )
        total = await _guard(
            service.count_recent_negative_reviews, "统计近期差评", session, shop,
            max_rating=max_rating, days=days,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ============================================================ 读：风险话术识别（P1）
#
# ★ 为什么独立成一个端点而不是给 `/reviews` 加个 `with_risk=true`：
#   ① `/reviews` 是面板主列表的**热路径**，加参数会让「要不要跑 LLM」
#      这件事从一个显式动作退化成一次参数拼写；
#   ② 风险扫描有独立的成本量级（deep ⇒ 每条一次模型调用）与独立语义
#      （`degraded` / 计数 / 排序），耦合进主列表后两条语义互相污染。
#   前端「🛡 风险识别」按钮显式打这个端点 —— 贵的动作必须是**用户按的**。

@router.get("/reviews/risk", summary="差评风险话术识别（只读，按风险排序）")
async def scan_reviews_risk(
    max_rating: int = 3,
    days: int = 30,
    limit: int = 20,
    offset: int = 0,
    deep: bool = False,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """对近期中差评逐条跑风险话术识别，**按「风险 → 未定论 → 干净」排序**后返回。

    ★ 这是**只读**端点：不改 `review_dispositions`、不发券、不退款、不写任何表。
      识别只产出「请人复核」的线索；处置动作仍卡在批准 / 发放那两步（HITL 边界不动）。

    - **deep**：是否启用 LLM 语义通道。**默认 `False`** —— 浅层（规则通道）是默认档，
      零模型成本。语义通道**只有在用户主动按【风险识别】时**才被请求，
      而且落到后端是**分层**的：
        ① 规则通道全量先跑（零成本），它同时决定谁不用送语义；
        ② 规则已判出**四类风险**的条目**不再送语义**（`fuse()` 在那个分支
           提前 return、压根不读 LLM，所以不送是无操作）；
        ③ 其余条目**打包成一次批量语义调用**（实测 20 条 43.4 s → 约 2 s）。
      响应里的 `semantic_sent` / `semantic_skipped` / `llm_calls` 就是这三步的读数。
      ★ **没有 LLM 凭据时不会静默降级成「无风险」**：响应里 `degraded=true`，
      且每条判 `unknown`（前端必须如实播报这层降级，不得显示成「全部清白」）。
    - **排序由后端做**：前端拿到什么顺序就按什么顺序渲染，**不得**自己重排
      （那是同一判定两份实现）。★ 排序作用在**本页内**（`limit`/`offset` 之后）；
      跨页置顶要全量扫描再分页，deep 下会成倍放大模型成本 ⇒ P1 不引入。
    - `total` 是真实条数（不受 `limit` 截断）；`scanned < total` ⇒ 本页只覆盖了一部分。
    - 缺 `X-Shop-ID` ⇒ 400，不返回空列表（本模块一律不提供「跨店汇总」这一档）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.scan_reviews_risk, "扫描差评风险", session, shop,
            max_rating=max_rating, days=days, limit=limit, offset=offset, deep=deep,
        )


@router.get("/reviews/by-spu/{spu_id}", summary="某个 SPU 名下的差评")
async def list_reviews_by_spu(
    spu_id: str,
    max_rating: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """产品详情「差评 tab」的数据源 —— **SPU 当聚合壳，键在 SKU 上**。

    - **max_rating**: 留空看全部星级，给 `3` 只看中差评（≤3 星，含星级缺失）。
    - **empty_state**: 界面必须按它分别播报 ——
      `no_reviews` 是「确实没有差评」（正常结论）；
      `no_asin_binding` / `no_sku` 是**数据缺口**（SKU 没登记 ASIN，
      差评再存在也关联不上）。把后者显示成「暂无差评」＝把缺口伪装成清白。

    ★ 同一个 ASIN 可能对应多个 SKU / 多个 SPU ⇒ 结果**已去重**，
      同一条差评不会被重复计数（真库实测：`B0CXXXX009` → 4 SKU / 4 SPU）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.list_reviews_for_spu, "读取产品差评", session, shop, spu_id,
            max_rating=max_rating, limit=limit, offset=offset,
        )


@router.get("/reviews/orphans", summary="关联不上产品的差评（孤儿兜底列表）")
async def list_orphan_reviews(
    max_rating: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """本店境内无法通过 ASIN / SKU 码匹配到**本店**任何产品的差评。

    ★ 「本店」这三个字是口径的一部分：某个 ASIN 命中了**别家店**的 SKU，
      在本店视角里依然是孤儿 —— 直接用无店铺过滤的 join 会让孤儿数系统性
      偏低，看起来像"我们的关联质量很好"。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.list_orphan_reviews, "读取孤儿差评", session, shop,
            max_rating=max_rating, limit=limit, offset=offset,
        )


# ============================================================ 读：个案 / 系统性判定
#
# ★ 为什么这两个端点必须存在（第 294 轮 B 档）
#   `count_repeat_issues` 与 `get_sku_health_score` 此前**只有 Agent 工具通道**
#   能到达（全仓唯一消费点是 `tools.py` 那个工具），HTTP 面没有任何出口 ⇒
#   差评工作台面板**结构上给不出**「这是个案还是系统性问题」这一步。
#   用户于是说得出「面板里走完整流程了，技能卡还用得上吗」—— 因为面板
#   确实静默漏了第 3 步，且漏得毫无提示。
#
# ★ 这两条只读端点**不写库、不发券**：判定与取数放端点，动作仍卡在人手里
#   （批准 / 发放那三步的边界不动）。

@router.get("/reviews/{review_id}/systemic-check", summary="这条差评是个案还是系统性问题")
async def check_review_systemic(
    review_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """一条差评的「个案 / 重复问题 / 系统性风险」判定 —— **后端唯一口径**。

    ★ 前端**不得**自己组合这个结论：组合规则（同因次数 ≥ 阈值，且环比为负
      或中差评占比偏高 ⇒ 系统性）本身就是判据，复制到界面就是第二份实现。

    - `ready=false` ⇒ 看 `reason`（多半是这条差评还没有归因；此时硬判＝猜）。
    - `recommend_escalate=true` ⇒ 面板给出「采纳：勾选升级通道」的动作入口。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.analyze_review_systemic, "判定个案/系统性",
            session, shop, review_id,
        )


@router.get("/skus/{sku}/health", summary="SKU 买家反馈健康分（最近一期）")
async def get_sku_health(
    sku: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """某 SKU 最近一期的**买家反馈**健康分。

    ★ 与广告分析里广告活动的 `health_score` **不是一回事**：这个是
      「买家怎么说」（评分 / 迟到 / 包装投诉），那个是「广告投得好不好」。

    - `found=false` ⇒ 这个 SKU 还没算过健康分（需先有一期归因数据）。
      界面必须把它与「健康分为 0」分开播报，否则缺口会伪装成实测结论。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.get_sku_health_score, "读取 SKU 健康分", session, shop, sku,
        )


# ============================================================ 写：审批 / 驳回 / 发放
#
# ★ 这三步是**人**的动作，不在 Agent 工具里 —— 发券/退款不可逆，
#   必须过人。Agent 只能把处置写到 `proposed`。

@router.post("/dispositions/{review_id}/approve", summary="批准处置")
async def approve_disposition(
    review_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """`proposed` → `approved`。批准人由服务端注入（请求体里没有这个字段）。"""
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.approve_disposition, "批准处置", session, shop, review_id,
            approver=_actor_name(user),
        )


@router.post("/dispositions/{review_id}/reject", summary="驳回处置")
async def reject_disposition(
    review_id: str,
    body: RejectDispositionBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """`proposed` / `approved` → `rejected`。

    ★ `approved` 也能驳回（批完发现金额写错要有退路）；`issued` 不能
      （券码已生成并写进了给买家的回复，只能另开一笔，不能把历史改没）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.reject_disposition, "驳回处置", session, shop, review_id,
            approver=_actor_name(user), notes=body.notes,
        )


@router.post("/dispositions/{review_id}/issue", summary="发放处置（不可逆）")
async def issue_disposition(
    review_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """`approved` → `issued`。**只有这一步会生成券码**。

    ★ 前置必须是 `approved`：未经人批准就发券等于把 HITL 架空。

    ★ ★ 这一步**不调用任何平台接口**：`issued` = 本地已核准（券码生成、回复可对外），
      平台侧动作要由人做完之后走 `/receipt` 登记。把这两件事合成一步，界面就会
      继续把「已核准」画成「已发放」（第 304 轮 P0·A 档）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.issue_disposition, "发放处置", session, shop, review_id,
            actor=_actor_name(user),
        )


@router.post("/dispositions/{review_id}/receipt", summary="登记平台执行回执（终态）")
async def record_execution_receipt(
    review_id: str,
    body: ExecutionReceiptBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """`issued` → `executed`：**本系统不调用平台接口**，这一步是「人去平台做完了，回来登记」。

    ★ 为什么必须有这个端点（第 304 轮 P0·A 档）：`issue_disposition` 只是本地核准
      （生成券码 + 把券码写进给买家的回复），**零出站调用**。此前库里没有任何字段
      能回答「平台上做没做」⇒ 界面的「已发放」是字面为真、暗示为假。登记回执之后，
      「谁、什么时候、凭什么凭证、在平台上做完了」才真的落进台账，
      `executed` 也才成为**唯一**能支撑「已执行」这个词的终态。

    ★ 为什么 `executed` 之后不能再退回：券码已经写进给买家的回复，把历史改没
      只会让台账与对话对不上账（要调整只能另开一笔）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.record_execution_receipt, "登记执行回执", session, shop, review_id,
            execution_mode=body.execution_mode, platform_ref=body.platform_ref,
            receipt_note=body.receipt_note, executed_by=_actor_name(user),
        )


# ============================================================ 写：人工补归因
#
# ★ 为什么补这个端点（第 304 轮后半实测）：风险识别命中 12 条、处置台账只有 5 条，
#   真因是 12 条里 **8 条 `primary_cause = unknown`**，而处置链只扫有归因的那批。
#   此前**没有任何入口**能把 unknown 推进一步 ⇒ 这 8 条永远进不了台账。

@router.post("/reviews/{review_id}/attribution", summary="手工给这条差评指定归因")
async def set_attribution(
    review_id: str,
    body: AttributionBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """把一条「判不出来」的差评标上具体成因，它才会进入处置链。

    ★ `primary_cause` 不接受 `unknown`：那不是可选项，是自动判定判不出来的结果。
    ★ 落 `method="manual"`，自动同步**不会**把它冲回 unknown（人工 > 自动）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.set_review_attribution, "补归因", session, shop, review_id,
            primary_cause=body.primary_cause, causes=body.causes,
            evidence=body.evidence, notes=body.notes, actor=_actor_name(user),
        )


# ============================================================ 读写：补偿规则
#
# ★ 第 304 轮后半：此前 `compensation_rules` 有表有种子有匹配逻辑，
#   **没有端点也没有界面** ⇒ 失败提示让人「到补偿规则里配一条」是负指令
#   （指向一个不存在的面板）。这四个端点就是那个入口。

@router.get("/compensation-rules", summary="列出本店的补偿规则")
async def list_rules(
    include_disabled: bool = True,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """配置界面的主列表。

    - **include_disabled**: 默认 True —— 停用中的规则也要看得见，
      否则「我明明配过」会变成谁也找不到的一条记录。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.list_compensation_rules, "读取补偿规则", session, shop,
            include_disabled=include_disabled,
        )


@router.post("/compensation-rules", summary="新建一条补偿规则")
async def create_rule(
    body: RuleCreateBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """★ 归属由服务端注入（请求体里没有 shop_id），与处置端点同一条口径。

    ★ 同店同 code ⇒ 400（不静默覆盖：覆盖会让「我配的 8 块」变成别人配的 30 块）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.create_compensation_rule, "新建补偿规则", session, shop,
            code=body.code, name=body.name, cause=body.cause, priority=body.priority,
            conditions=body.conditions, action=body.action, budget_cap=body.budget_cap,
            enabled=body.enabled, notes=body.notes,
        )


@router.patch("/compensation-rules/{rule_id}", summary="改一条补偿规则（含启停）")
async def update_rule(
    rule_id: str,
    body: RuleUpdateBody,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """部分更新 —— 只改传进来的字段；`code` 不可改（它是主键的一部分）。"""
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.update_compensation_rule, "更新补偿规则", session, shop, rule_id,
            **body.model_dump(exclude_none=True),
        )


@router.delete("/compensation-rules/{rule_id}", summary="删除一条补偿规则")
async def delete_rule(
    rule_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
    user=Depends(require_acting_user),
):
    """硬删。处置记录存的是**展开后的方案快照**，删规则不会让已生成的处置变孤儿。

    ★ 想留着以后再用就走 `PATCH` 的 `enabled=false`（停用），不必删。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.delete_compensation_rule, "删除补偿规则", session, shop, rule_id,
        )
