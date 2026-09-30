# -*- coding: utf-8 -*-
"""演示身份免配额 —— 门禁（第 220 轮）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
老板报的原始症状是「选品分析师回复成了兜底文案」。根因链的最后一环是
**429**：前端带 `demo-token` ⇒ 第 182 轮起它被解析成一个**真 `User`**
（不再是 `None`）⇒ 免费版 `api_calls_used=100 / limit=100` 用满 ⇒
`check_api_quota` 抛 429 ⇒ 前端落到兜底文案。

于是本仓 `main.py` 的 API_QUOTA 段落此前那句承诺
    「演示模式…… 不计量不拦截 ⇒ 本地演示零影响」
在第 182 轮就**已经失真**（本章第 220 轮把它更正过来）。

老板拍板的处置是 **A：演示身份免配额** ——
    · 演示身份：放行，且**不计量**；
    · 真账号（含普通免费用户）：照常按额度拦截（429）。

==============================================================================
★ 为什么豁免判据是「凭据形态」而不是「这个人是谁」
==============================================================================
唯一真源 = `core/auth/demo_identity.py::is_demo_request`（第 220 轮新增），
它同时被 `dependencies.py`（2 处）与 `core/metering/usage_tracker.py`（3 处）消费。

用「已解析出的 user 是不是演示账号」做判据会造出**第二份实现**：一处认凭据前缀、
一处认 email，两者迟早漂移。本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。

★ 这条定档的**代价**必须写下来（不是"更安全"三个字能带过的）：
  演示账号的额度被豁免 ⇒ 任何拿到 `demo-token` 的人都能无限刷。
  兜住它的不是配额，而是另外两道（都已有门禁）：
    ① 哨兵只在 `DEMO_MODE=true` 时生效 —— 生产由
       `config._enforce_production_safety` **拒绝启动**（`test_demo_identity.py` §8）；
    ② 演示身份的可见范围**恰好等于演示账号一个容器**
       （`test_demo_identity.py::test_visible_accounts_equal_exactly_the_demo_account`）。
  ⇒ 即"无限刷的是演示账号自己的数据"，不是别人的。

==============================================================================
★ 反向注入清单（每条都必须让本文件转红，实测见 §6）
==============================================================================
 1. 删掉 `check_api_quota` 里的 `if is_demo_request(request): return current_user`
    ⇒ `test_demo_exempt_from_api_quota` 转红。
 2. 删掉 `meter_agent_chat` 里的豁免（改回无条件 `check_quota`）
    ⇒ `test_demo_over_http_*` 转红（429）。
 3. 把豁免判据换成 `config.demo_mode`（**环境开关当判据**）
    ⇒ `test_real_token_still_blocked_while_demo_mode_is_on` 转红。
 4. 把 `if not demo_identity:` 的次数结算改回无条件 `record_usage`
    ⇒ `test_demo_over_http_*` 的「次数不变」断言转红。
 5. 在 `usage_tracker.py` 里手写一份 `is_demo_credential(...) and config.demo_mode`
    ⇒ `test_demo_predicate_has_a_single_implementation` 转红。
"""

import ast
from pathlib import Path

from sqlalchemy import select

BACKEND = Path(__file__).resolve().parents[1]

#: 与前端 `frontend/src/config/demoMode.ts::DEMO_TOKEN` 逐字一致
#: （另有跨语言契约门禁 `test_demo_identity.py::test_demo_sentinel_prefix_matches_frontend`）。
DEMO_TOKEN = "demo-token"

DEMO_HEADERS = {"Authorization": f"Bearer {DEMO_TOKEN}"}


# ============================================================================
# 0. 小工具
# ============================================================================


def _calls_named(tree: ast.AST, name: str) -> list:
    """AST 里所有**真的调用** `name(...)` 的位置（不看注释/字符串）。

    ★ 为什么必须走 AST：判据若用「源码字符串包含」，本文件与
      `usage_tracker.py` 的 **docstring 里就写着** `is_demo_credential(token)` ——
      字符串判据会被自己的说明文字绊倒（假红），反过来也可能被
      「注释里写对了、代码里写错了」骗过（假绿）。
      本仓判据：形态判据走 AST，禁「源码字符串包含」。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == name:
            out.append(node.lineno)
        elif isinstance(fn, ast.Attribute) and fn.attr == name:
            out.append(node.lineno)
    return out


def _http_request(path: str = "/probe", headers: list | None = None):
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [],
    })


def _bearer(value: str) -> list:
    return [(b"authorization", value.encode("utf-8"))]


async def _exhaust_quota(user_id: str, *, api: bool = True, chat: bool = True) -> None:
    """把某个用户的额度打满（连带断言订阅真的存在）。

    ★ `api` / `chat` 两个开关是给**反例用例**用的，不是可有可无的：
      反例要证明的是「**某一层**仍然拦得住真账号」。若两处额度都打满，
      429 就会来自**另一层** —— 于是「把这一层的豁免判据写错」这种缺陷
      根本显不出来（用例照绿，而测的东西不是它）。
    """
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )).scalar_one_or_none()
        assert sub is not None, (
            "前提不成立：这个用户没有 subscriptions 行 ⇒ 额度无从谈起"
            "（`check_quota` 会以「订阅无效或已过期」为由拒绝，与额度无关，"
            "会让本文件的断言变成假绿）。"
        )
        assert sub.plan is not None, "前提不成立：订阅没挂套餐（plan 为空）"
        if api:
            sub.api_calls_used = sub.plan.api_calls_limit
        if chat:
            sub.agent_chats_used = sub.plan.agent_chat_limit
        await db.commit()


async def _usage(user_id: str) -> tuple:
    """(api_calls_used, agent_chats_used, llm_tokens_used)"""
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )).scalar_one()
        return (sub.api_calls_used, sub.agent_chats_used, sub.llm_tokens_used or 0)


async def _make_demo_account(make_user, monkeypatch, *, exhaust: bool) -> dict:
    """造一个「名下有容器」的用户并配成**演示账号**；`exhaust=True` 时把额度打满。

    ★ `exhaust` 这个开关不是图方便，它对应**两组断言各自的前提**：
      · `exhaust=True`  → 证明「**不被拦**」：额度满 ⇒ 不豁免就必然 429；
      · `exhaust=False` → 证明「**不被记**」。这一半**必须**用没打满的账号 ——
        额度一旦打满，`record_usage` 本来就会拒绝写入（返回 False 且不 commit），
        于是「次数没变」这个断言**恒真**，而它看起来完全像在验证「不计量」。
        本仓判据：判据要取自「只有改动成功才可能出现」的观察集合。

    ★ 为什么必须 `ensure_default_account`：`resolve_demo_user` 的查询里有一条
      `join(Account, ...)` —— 守卫 ② 的真实语义是「**查得到一个名下有容器的主人**」
      （见 `demo_identity.py` 的长论证：没有容器的用户当演示身份，
      写口会在外键处炸成「数据库不可用」= 归因错方向）。
      少了这一步，解析会退回匿名，本文件的用例会以「429/403」的形态红
      —— 而失败原因指向**守卫**，不是它真正要测的配额豁免。
    """
    from core.auth.accounts import ensure_default_account
    from core.config import config
    from core.database import get_async_session
    from core.identity.models import User
    from core.metering import usage_tracker as ut

    owner = await make_user("demoquota")
    monkeypatch.setattr(config, "demo_account_email", owner["email"], raising=True)

    async with get_async_session() as db:
        u = (
            await db.execute(select(User).where(User.id == owner["user_id"]))
        ).scalar_one()
        await ensure_default_account(db, u)
        # `ensure_default_account` 只 flush 不 commit（它服务于"同一事务内建店+建容器"）
        await db.commit()

    if exhaust:
        await _exhaust_quota(owner["user_id"])
        # 正向对照：这个账号**确实**被额度拦着（否则下面所有"放行"断言都是假绿）
        async with get_async_session() as db:
            allowed, reason = await ut.UsageTracker.check_quota(
                db, owner["user_id"], ut.UsageType.API_CALL)
        assert not allowed, (
            "前提不成立：这个账号的 API 额度并没有打满 ⇒ "
            "「演示身份被放行」的断言即使实现对也是**假绿**"
            f"（check_quota 说：{reason!r}）"
        )
    else:
        async with get_async_session() as db:
            allowed, reason = await ut.UsageTracker.check_quota(
                db, owner["user_id"], ut.UsageType.API_CALL)
        assert allowed, (
            f"前提不成立：这个账号一注册额度就是满的（{reason!r}）⇒ "
            "后面「次数没变」的断言会退化成「扣减本来就被额度拒绝」，"
            "与「豁免生效」毫无关系（**恒真**的假绿）。"
        )
    return owner


# ============================================================================
# 1. 唯一真源：演示判定只能有一处实现（形态门禁，AST）
# ============================================================================


def test_demo_predicate_has_a_single_implementation():
    """★★★ 演示身份判定的**实现**只能有一处；其余文件只能**调用**它。

    ★ 为什么这条是形态门禁而不是行为用例：行为用例抓不住"两份实现"——
      两份都实现对了时候照样全绿，只有当它们**漂移**时才会红，
      而漂移的那一刻没有用例覆盖到另外那一份（本仓原话：同一判定两份实现
      ⇒ 至少一份永远测不到）。形态门禁在这里是**唯一**能提前抓住它的判据。

    ★ 第 220 轮之前的实况（就是这条要防的）：
      `dependencies.py` 的 `require_auth_if_enabled` 写的是
      `has_bearer and is_demo_credential(token) and config.demo_mode`，
      而同一个文件里的 `get_acting_user` 写的是
      `is_demo_credential(token) and config.demo_mode` —— 少了 `has_bearer` 那一半。
    """
    demo = BACKEND / "core/auth/demo_identity.py"
    deps = BACKEND / "core/auth/dependencies.py"
    usage = BACKEND / "core/metering/usage_tracker.py"

    demo_calls = _calls_named(ast.parse(demo.read_text(encoding="utf-8")), "is_demo_credential")
    assert demo_calls, (
        f"{demo.name} 里连 `is_demo_credential` 都不调了 —— 本文件的前提（唯一真源在那里）"
        "已经不成立，请先核对该函数是否被改名/搬走。"
    )

    for path in (deps, usage):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hand = _calls_named(tree, "is_demo_credential")
        assert not hand, (
            f"★ {path.name} 第 {hand} 行仍**手写**调用 `is_demo_credential(...)` —— "
            "演示判定出现了第二份实现。请改调唯一真源 "
            "`core.auth.demo_identity.is_demo_request(request)`。"
        )
        assert _calls_named(tree, "is_demo_request"), (
            f"★ {path.name} 没有调用唯一真源 `is_demo_request` —— 豁免根本没接上"
            "（症状：演示模式照旧被 429 拦住）。"
        )

    # ★ 消费点登记表：**数量**也要钉住。
    #   豁免是「每个入口各一处」的形态 —— 少一处就有入口漏网（例如
    #   `check_agent_chat_quota` 被漏掉时，店秘书会 429 而其它 Agent 正常，
    #   症状看起来像"某个 Agent 坏了"）。新增消费点时必须同步改这里。
    assert len(_calls_named(ast.parse(deps.read_text(encoding="utf-8")), "is_demo_request")) == 2, (
        "`dependencies.py` 里 `is_demo_request` 的消费点不再是 2 个"
        "（`require_auth_if_enabled` + `get_acting_user`）—— "
        "新增/删除了判定点却没同步登记表。"
    )
    assert len(_calls_named(ast.parse(usage.read_text(encoding="utf-8")), "is_demo_request")) == 3, (
        "`usage_tracker.py` 里 `is_demo_request` 的消费点不再是 3 个"
        "（`check_api_quota` + `meter_agent_chat` + `check_agent_chat_quota`）—— "
        "少一个就有入口漏网。"
    )


# ============================================================================
# 2. 唯一真源本身的判据：凭据形态 + 演示开关
# ============================================================================


def test_is_demo_request_requires_bearer_scheme(monkeypatch):
    """`is_demo_request` 只认「Bearer + 哨兵前缀 + DEMO_MODE=true」这三件同时成立。

    ★ `scheme == "bearer"` 那一半不是洁癖：`require_auth_if_enabled` 的 ② 档
      （带了自称 Bearer 的凭据 ⇒ 一律强制校验真身份）就是按 scheme 分流的。
      少了它会出现「同一枚头，演示分支认、真身份分支不认」的缝。
    """
    from core.auth import demo_identity
    from core.config import config

    monkeypatch.setattr(config, "demo_mode", True, raising=True)

    assert demo_identity.is_demo_request(_http_request(headers=_bearer(f"Bearer {DEMO_TOKEN}"))) is True
    assert demo_identity.is_demo_request(_http_request(headers=_bearer("bearer demo-whatever"))) is True
    # 非 Bearer 头：不算演示身份（真身份校验那一侧也不会认它）
    assert demo_identity.is_demo_request(_http_request(headers=_bearer(f"Demo {DEMO_TOKEN}"))) is False
    # 真 token：不是哨兵
    assert demo_identity.is_demo_request(_http_request(headers=_bearer("Bearer eyJhbGciOi.fake.jwt"))) is False
    # 无凭据
    assert demo_identity.is_demo_request(_http_request(headers=[])) is False
    # 有 Bearer 但值为空
    assert demo_identity.is_demo_request(_http_request(headers=_bearer("Bearer "))) is False

    monkeypatch.setattr(config, "demo_mode", False, raising=True)
    assert demo_identity.is_demo_request(_http_request(headers=_bearer(f"Bearer {DEMO_TOKEN}"))) is False, (
        "★ `DEMO_MODE=false` 时哨兵串竟然还被认成演示身份 —— "
        "生产环境里任何知道 `demo-token` 这个字符串的人都能拿到豁免。"
    )


# ============================================================================
# 3. 依赖级行为：演示身份 + 额度打满 ⇒ 放行
# ============================================================================


async def test_demo_exempt_from_api_quota(demo_on, auth_off, make_user, monkeypatch):
    """演示身份在 **API 额度已满** 时仍然放行（`check_api_quota` 的豁免）。"""
    from core.database import get_async_session
    from core.metering import usage_tracker as ut

    owner = await _make_demo_account(make_user, monkeypatch, exhaust=True)

    async with get_async_session() as db:
        got = await ut.check_api_quota(request=_http_request(headers=_bearer(f"Bearer {DEMO_TOKEN}")), db=db)

    assert got is not None and got.id == owner["user_id"], (
        "★ 演示身份被 API 额度拦住了（或没解析成演示账号主人）—— "
        "这正是老板报的那条 bug 的后端一半：演示模式免费额度用满 ⇒ 一律 429 ⇒ "
        "前端只能落到兜底文案。"
    )


async def test_demo_exempt_from_agent_chat_quota(demo_on, auth_off, make_user, monkeypatch):
    """演示身份在 **对话额度已满** 时仍然放行（`check_agent_chat_quota` 的豁免）。

    ★ 为什么与上一条分开：豁免是**每个入口各一处**的形态（`usage_tracker.py`
      里三处）。只测一处的话，漏掉另外两处时仍会全绿。
    """
    from core.database import get_async_session
    from core.metering import usage_tracker as ut

    owner = await _make_demo_account(make_user, monkeypatch, exhaust=True)

    async with get_async_session() as db:
        got = await ut.check_agent_chat_quota(
            request=_http_request(headers=_bearer(f"Bearer {DEMO_TOKEN}")), db=db)

    assert got is not None and got.id == owner["user_id"], (
        "★ 演示身份被 Agent 对话额度拦住了 —— "
        "`check_agent_chat_quota` 这一处漏了豁免（症状：某些入口 429、另一些正常）。"
    )


# ============================================================================
# 4. HTTP 级：路由装配真的接上了（并在真链路上验证「不计量」）
# ============================================================================


async def test_demo_over_http_product_research_is_not_429(
    client, demo_on, auth_off, make_user, monkeypatch
):
    """老板报的那条路径（选品分析师）端到端不再 429。

    ★ 「不计量」**不在这里判**（理由见函数末尾的注释）：本用例的账号额度已打满，
      判它等于在验证一件与豁免无关的事。

    ★ 为什么必须走 HTTP：依赖级用例只证明「函数本身放行」，证明不了
      **它被挂在路由上**（本仓登记过的形态：`dependencies=... if config.y else []`
      ⇒ 门禁根本没挂，而函数级用例照样绿）。
    """
    owner = await _make_demo_account(make_user, monkeypatch, exhaust=True)
    before = await _usage(owner["user_id"])

    r = await client.post(
        "/api/v1/product-research/chat",
        json={"message": "目前选品库中哪个最贵"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code != 429, (
        "★ 演示身份在选品分析师这条路径上仍然 429 —— "
        "这正是老板截图里那条 bug（前端会把它渲染成兜底文案）。"
        f"\n响应：{r.status_code} {r.text[:300]}"
    )
    assert r.status_code == 200, f"演示身份应正常返回，实际 {r.status_code}：{r.text[:300]}"

    # ★ 「不计量」这一半**刻意不在这里断言**：本用例的账号额度已打满，而
    #   `record_usage` 在超限时本来就会拒绝写入 ⇒「次数没变」恒真，
    #   断言它等于在验证一件与豁免无关的事（**假绿**）。
    #   「不计量」改由 `test_demo_over_http_keeps_llm_cost_recorded` 在
    #   **未打满**的账号上判 —— 那里次数若变了，才是真的出了问题。
    assert before[0] > 0 and before[1] > 0, "前提：本用例的账号额度确实是满的"


async def test_demo_over_http_keeps_llm_cost_recorded(
    client, demo_on, auth_off, make_user, monkeypatch, fake_llm
):
    """★★★ 演示身份豁免的是**次数**，不是**账本**：LLM 真实消耗必须照记。

    ★ `exhaust=False` 是**刻意**的（理由见 `_make_demo_account` 的 docstring）：
      额度打满时 `record_usage` 本来就拒绝写入，「次数没变」会退化成恒真的断言；
      用一个尚有余量的账号，次数若变了才说明真的计了量。

    ★ 为什么这条不能省：演示对话**真的在花第三方的钱**（DashScope 按 token 计费）。
      如果豁免实现成「整段 `return`，连 `reset_meter` / 结算都不做」，
      那么免费版演示会把平台成本变成一笔**无声的支出** —— 界面一切正常，
      账上看不见。本仓判据：可豁免的是产品策略，「成本」属于平台账本，不能失明。
    """
    owner = await _make_demo_account(make_user, monkeypatch, exhaust=False)
    before = await _usage(owner["user_id"])

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code != 429, f"演示身份不应 429：{r.status_code} {r.text[:300]}"
    assert r.status_code == 200, r.text[:300]

    after = await _usage(owner["user_id"])
    assert after[:2] == before[:2], (
        f"演示身份的「次数」被计了（{before[:2]} → {after[:2]}）—— "
        "免配额应当同时免计量。"
    )
    assert after[2] > before[2], (
        "★ 演示身份的 LLM 真实消耗**没有落库**（llm_tokens_used 未增长）—— "
        "演示对话真的在花第三方的钱，成本必须照记：能豁免的是「次数」，"
        "不是「账本」。"
    )


# ============================================================================
# 5. 反例：真账号照样拦（**尤其是演示开关开着的时候**）
# ============================================================================


async def test_real_token_still_blocked_by_api_quota_while_demo_mode_is_on(
    client, demo_on, auth_off, user, auth_headers
):
    """★★★ 反例：`DEMO_MODE=true` + **真 token** ⇒ 照样 429。

    这条钉住的是豁免判据的**方向**。如果实现写成
        `if config.demo_mode: 跳过配额`
    （拿**环境开关**当判据），那么在演示环境里**任何真实登录用户**都能无限刷，
    而 `test_billing_metering.py` 的 429 用例（`auth_on` ⇒ `demo_mode` 为假）
    **照样绿** —— 它抓不到这个方向。

    ⇒ 必须把「演示开关开着 + 真身份」这个**组合**单独钉住：
      判据是「凭据形态」，不是「环境开关」，也不是「这个人是谁」。

    ★ **只打满 API 额度**（对话额度留空）是刻意的：两处都打满时，429 可能
      来自 `meter_agent_chat`，于是「`check_api_quota` 的判据被写成环境开关」
      这个缺陷**在本条显不出来**（用例照绿）。第一轮反向注入 RI-3 正是这样
      漏过去的 —— 记下来：反例的 429 必须**可归因到被测的那一层**。
    """
    from core.database import get_async_session
    from core.metering import usage_tracker as ut

    await _exhaust_quota(user["user_id"], api=True, chat=False)

    async with get_async_session() as db:
        api_ok, api_reason = await ut.UsageTracker.check_quota(
            db, user["user_id"], ut.UsageType.API_CALL)
        chat_ok, _ = await ut.UsageTracker.check_quota(
            db, user["user_id"], ut.UsageType.AGENT_CHAT)
    assert not api_ok, f"前提不成立：API 额度没打满（{api_reason!r}）"
    assert chat_ok, "前提不成立：对话额度也被打满了 ⇒ 429 归因不到 API 这一层"

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 429, (
        "★ 真 token 在演示开关打开的环境里**绕过了** API 额度 —— "
        "豁免判据被写成了 `config.demo_mode`（环境开关）而不是凭据形态。"
        "后果：任何真实登录用户在演示环境里无限刷。"
        f"\n响应：{r.status_code} {r.text[:300]}"
    )


async def test_real_token_still_blocked_by_chat_quota_while_demo_mode_is_on(
    client, demo_on, auth_off, user, auth_headers
):
    """反例（对话那条路）：只打满**对话次数**，真 token 仍 429。

    ★ 「只打满对话次数」是刻意的：若顺便把 API 额度也打满，429 会来自
      `check_api_quota`，而本条要证明的 `meter_agent_chat` 那条路可能
      根本没被走到 —— 用例全绿而**测的东西不是它**（本仓登记过的假绿形态）。
      （同一条纪律见 `test_real_token_still_blocked_by_api_quota_*`：反例的
      429 必须**可归因到被测的那一层**。）
    """
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        sub.agent_chats_used = sub.plan.agent_chat_limit
        await db.commit()

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 429, (
        "★ 真 token 在演示开关打开的环境里绕过了**对话次数**额度 —— "
        "`meter_agent_chat` 的豁免判据错了（应为凭据形态，不是 `config.demo_mode`）。"
        f"\n响应：{r.status_code} {r.text[:300]}"
    )
