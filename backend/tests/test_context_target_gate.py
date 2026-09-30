"""门禁：**前置缺失时不得凭会话历史凑出作用对象**（第 251 轮）。

背景（老板实测，已复现）：选品分析师没点【载入选品】就点「上架建议」卡片，
系统答「好的，我们已经确定了评估对象：<某个商品>」并给出完整上架建议 ——
而那个商品是**上一轮**对话里出现过的，本次从没选过。

机制层取证：点名技能时强制走带**全量会话历史**的工具环路，技能正文的
「适用条件」又假定对象已存在 ⇒ 模型从历史里"续"上了旧对象。

本文件钉六层，缺一层就有一条静默通道：

  A. **机制层三态**：`None`（未参与）/ `specified=False`（明确没有）/ 有对象
     —— 压成两态就有客户端静默绕过门禁。
  B. **判定方向**：「拿不到权威信息」判成**缺失**（安全失败方向）。
  C. **渲染**：明确没有时必须注入「不得从历史里挑一个顶上」。
  D. **服务层真的不进 LLM**（桩计数为 0）+ **端点真的绑了字段**（含三态判别）。
     ★ 第 257 轮把「端点」那一半从「数某个文件里出现几次」改成
       **按端点清单对账**（四对 `/chat`、`/chat/stream`，AST 现算端点集合）。
       旧断言正是钉住旧形态的负资产：Listing / AIGC 整条漏在外面时它**照旧绿**。
  E. **名单不漂移**：与技能仓库里那批候选类技能逐字相等（可推导，不靠人工）。
  F. **注册点不被业务域私有化**：注册住 `modules/context_target_section.py`
     （`modules/` 根，横切位置），由 `modules/__init__.py` 触发；
     任何业务模块都不得再 import 它（第 257 轮上提前它住在选品模块里）。

★ 第 257 轮的起因（老板报障 + 截图）：选品分析师的「上下文条」写着评估对象，
  而 **Listing 优化师 / AIGC 媒体生成器都显示「（无上下文参数）」**——
  可这两个 Agent 同样要先选一个商品才能开工。取证结论：**不是取舍，是疏漏**
  —— 第 251 轮那条链的五层全部只接了选品一条链路。
"""

import pathlib

import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_infra.context_target import (
    ContextTarget,
    bind_context_target,
    current_context_target,
    is_context_target_missing,
    normalize_context_target,
    render_context_target_block,
)
from ai_infra.skills import bind_requested_skill
from modules.product_research.context_target_gate import (
    NEED_TARGET_REPLY,
    TARGET_REQUIRED_SKILLS,
    context_target_rejection,
    target_required_skill,
)
from modules.customer_service.schemas import ChatRequest as CsChatRequest
from modules.product_research.schemas import ChatRequest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_SKILL = "candidate-launch-advice"


# =========================================================== A. 三态
def test_normalize_keeps_three_states_apart():
    """`None` / `{}` / 有内容 —— **三态分明**（本模块的地基）。"""
    assert normalize_context_target(None) is None, "「未提供」被压成了「明确没有」"
    missing = normalize_context_target({})
    assert missing is not None and missing.specified is False
    assert normalize_context_target({"label": "候选选品"}).specified is False, (
        "只有 label、没有 title/ref ⇒ 拿它做不了任何事，必须算「没有对象」"
    )
    hit = normalize_context_target({"label": "候选选品", "title": "某品", "ref": "B001"})
    assert hit.specified is True and hit.title == "某品" and hit.ref == "B001"


def test_blank_strings_are_not_a_target():
    """空串 / 纯空白 ⇒ 「没有对象」，不是「有对象但叫空名字」。"""
    for blank in ("", "   ", "\n\t"):
        t = normalize_context_target({"title": blank, "ref": blank})
        assert t.specified is False, f"{blank!r} 被当成了有效对象"


# =========================================================== B. 判定方向
async def test_missing_judgment_fails_closed():
    """拿不到权威信息 ⇒ 判**缺失**（安全失败方向）。"""
    async with bind_context_target(None):
        assert is_context_target_missing() is True, "未提供被判成「有对象」= 门禁失效"
    async with bind_context_target({}):
        assert is_context_target_missing() is True, "明确没有却没判成缺失"
    async with bind_context_target({"title": "某品", "ref": "B001"}):
        assert is_context_target_missing() is False, "有对象却被判成缺失（会误拒）"


async def test_bind_scope_restores_even_on_exception():
    """作用域必须**无条件复位** —— 否则同进程后续请求沿用上一次的选择。"""
    assert current_context_target() is None
    with pytest.raises(RuntimeError):
        async with bind_context_target({"title": "A", "ref": "R"}):
            raise RuntimeError("boom")
    assert current_context_target() is None, "异常退出后没有还原"

    async with bind_context_target({"title": "outer", "ref": "O"}):
        async with bind_context_target({"title": "inner", "ref": "I"}):
            assert current_context_target().title == "inner"
        assert current_context_target().title == "outer", "内层退出把外层一起清了"
    assert current_context_target() is None


# =========================================================== C. 渲染
def test_render_silent_when_client_not_participating():
    """客户端没参与 ⇒ **空串**（凭空写「本次没有对象」是负增益）。"""
    assert render_context_target_block(None) == ""


def test_render_missing_forbids_history_pickup():
    """「明确没有」那一段必须写明**不得从历史里挑一个顶上** —— 本洞的现场。"""
    block = render_context_target_block(ContextTarget(specified=False))
    assert "（无）" in block
    assert "不得" in block and "历史" in block, (
        "缺了「不得沿用历史对象」这句，模型就会像实测那样把上一轮的评估对象续上来"
    )


def test_render_present_pins_authority_to_this_request():
    """「有对象」那一段必须写明**只认本次**。"""
    block = render_context_target_block(
        ContextTarget(specified=True, label="候选选品", title="某品", ref="B001")
    )
    assert "某品" in block and "B001" in block and "候选选品" in block
    assert "本次" in block and "历史" in block


# =========================================================== D-1. 门禁判定
def _skill(name):
    return bind_requested_skill(name)


@pytest.mark.parametrize(
    "skill,has_target,should_reject",
    [
        (CANDIDATE_SKILL, False, True),    # 点名 + 需要对象 + 没给 ⇒ 拒
        (CANDIDATE_SKILL, True, False),    # 点名 + 需要对象 + 给了 ⇒ 放行
        ("blueocean-hard-filter", False, False),   # 不需要对象的技能 ⇒ 放行
        (None, False, False),              # 没点名 ⇒ 放行（普通提问行为不变）
    ],
)
async def test_gate_matrix(skill, has_target, should_reject):
    target = {"label": "候选选品", "title": "某品", "ref": "B001"} if has_target else {}
    async with _skill(skill), bind_context_target(target):
        got = context_target_rejection()
    if should_reject:
        assert got == NEED_TARGET_REPLY
    else:
        assert got is None


async def test_unprovided_field_also_rejected():
    """**本客户端未提供**该字段（老客户端）时也拒 —— fail-closed 的一侧。

    ★ 这一条是刻意的：拿不到权威信息就不能假定有对象。
      代价只是要求调用方把对象带上（可恢复）；反着判就是把本洞放回来。
    """
    async with _skill(CANDIDATE_SKILL), bind_context_target(None):
        assert target_required_skill() == CANDIDATE_SKILL, "名单判断没生效"
        assert context_target_rejection() == NEED_TARGET_REPLY


# =========================================================== D-2. 服务层零调用
async def test_service_chat_does_not_reach_agent(monkeypatch):
    """前置缺失 ⇒ **连模型都不叫**（agent 零调用）—— 本门禁的硬证据。"""
    from modules.product_research.service import product_research_service as svc

    spy = MagicMock()
    spy.invoke = AsyncMock(side_effect=AssertionError("前置缺失时不该调用 Agent"))
    monkeypatch.setattr(svc, "agent", spy, raising=False)

    async with _skill(CANDIDATE_SKILL), bind_context_target({}):
        resp = await svc.chat("请按「上架建议」执行。")

    assert resp.reply == NEED_TARGET_REPLY
    assert spy.invoke.await_count == 0, "门禁没拦住 —— Agent 被调用了"


async def test_service_stream_does_not_reach_agent(monkeypatch):
    """流式路径**同一判定**（流式不是另一套智能）。"""
    from modules.product_research.service import product_research_service as svc

    spy = MagicMock()
    spy.stream_chat = MagicMock(side_effect=AssertionError("前置缺失时不该调用 Agent"))
    monkeypatch.setattr(svc, "agent", spy, raising=False)

    async with _skill(CANDIDATE_SKILL), bind_context_target({}):
        chunks = [c async for c in svc.stream_chat("请按「上架建议」执行。")]

    assert chunks == [NEED_TARGET_REPLY]


async def test_service_passes_through_when_target_present(monkeypatch):
    """有对象时**照常**调用 Agent —— 门禁不能把正常路径一起掐掉。"""
    from modules.product_research.service import product_research_service as svc

    class _Res:
        content = "ok"
        display_type = "text"
        data = None

    spy = MagicMock()
    spy.invoke = AsyncMock(return_value=_Res())
    monkeypatch.setattr(svc, "agent", spy, raising=False)

    async with _skill(CANDIDATE_SKILL), bind_context_target({"title": "某品", "ref": "B001"}):
        resp = await svc.chat("请按「上架建议」执行。")

    assert resp.reply == "ok"
    assert spy.invoke.await_count == 1


# =========================================================== D-3. 端点契约
def test_request_keeps_three_states_at_http_boundary():
    """HTTP 边界上「字段不出现」与「传 null」必须**可区分**（`model_fields_set`）。"""
    absent = ChatRequest(message="x")
    assert "context_target" not in absent.model_fields_set, "不传字段却被记成传过"

    explicit_none = ChatRequest(message="x", context_target=None)
    assert "context_target" in explicit_none.model_fields_set, (
        "传 null 与不传被压成同一态 ⇒ 门禁只在「新客户端」上生效"
    )

    with_target = ChatRequest(
        message="x", context_target={"label": "候选选品", "title": "某品", "ref": "B001"}
    )
    assert with_target.context_target.title == "某品"


def test_payload_parser_keeps_three_states_and_is_shared_by_all_endpoints():
    """请求体 → 载荷的转换必须把三态**原样**传下去，且**所有下发链路共用一份实现**。

    ★ 第 257 轮：这个解析从 `product_research/router.py` 的私有函数上提到
      `ai_infra/context_target.py`（唯一实现）。上提的原因不是"更整齐"：
      三条链路各写一份时，漏掉 `model_fields_set` 那一次判断的版本**不会报任何错**
      —— 它只是安静地让门禁失效（本仓「同一判定两份实现 ⇒ 至少一份永远测不到」）。
      ⇒ 所以判据也从「这个私有函数的三态」改成「**同一个函数**在每一个请求模型上
      三态一致」：只测一条链路的话，另外几条接错了也照旧绿。
    ★ 名单口径 = `CHAT_ENDPOINTS` 的模块集合（第 298 轮补客服；两处清单必须同步，
      只改一处就是「少测一条链路」的假绿）。
    """
    from ai_infra.context_target import context_target_payload
    from modules.aigc_media.schemas import ChatRequest as AigcChatRequest
    from modules.listing_generator.schemas import ListingChatRequest

    cases = [
        (ChatRequest, "product_research"),
        (ListingChatRequest, "listing_generator"),
        (AigcChatRequest, "aigc_media"),
        (CsChatRequest, "customer_service"),
    ]
    for model, who in cases:
        assert context_target_payload(model(message="x")) is None, (
            f"{who}: 不传字段被读成了「明确没有」⇒ 门禁只在「新客户端」上生效"
        )
        assert context_target_payload(model(message="x", context_target=None)) == {}, (
            f"{who}: 传 null 与不传被压成同一态 ⇒ 静默旁路"
        )
        got = context_target_payload(
            model(message="x", context_target={"title": "某品", "ref": "B001"})
        )
        # ★ 第 272 轮：`detail` 是新增的补充数据字段（可选），未传时 `model_dump()`
        #   会带上 `detail: None`。本判据守的是「三态解析 + 三链路共用一份实现」，
        #   `detail` 的加入不改变三态语义 —— 期望值随真实形状更新，不钉死旧形态。
        assert got == {"label": None, "title": "某品", "ref": "B001", "detail": None}, f"{who}: {got}"


def test_payload_shape_is_defined_once():
    """每个下发该字段的请求体的该字段必须**同一个类**（不是同名同形状的多份）。

    ★ 只测三态值相等是不够的：多份独立定义的同名模型可以算出一样的结果，
      ⇒ 判据取**形态**（本仓既有判据：值判据骗得过形态缺陷）。
    """
    from ai_infra.context_target import ContextTargetPayload
    from modules.aigc_media.schemas import ChatRequest as AigcChatRequest
    from modules.customer_service.schemas import ChatRequest as CsChatRequest
    from modules.listing_generator.schemas import ListingChatRequest
    from modules.product_research.schemas import ChatRequest

    for model, who in (
        (ChatRequest, "product_research"),
        (ListingChatRequest, "listing_generator"),
        (AigcChatRequest, "aigc_media"),
        (CsChatRequest, "customer_service"),
    ):
        field = model.model_fields.get("context_target")
        assert field is not None, f"{who}: 请求体里没有 context_target 字段"
        assert field.annotation is not None
        # Optional[X] ⇒ annotation 是 Union[X, None]
        union_args = getattr(field.annotation, "__args__", ())
        assert ContextTargetPayload in union_args, (
            f"{who}: 字段类型不是机制层那一个 ContextTargetPayload（{field.annotation}）⇒ "
            f"形状多了一份实现，少一个字段的那份不会报错"
        )
        assert field.default is None, f"{who}: 给了非 None 默认值 ⇒ 第三态（不传字段）会消失"


#: 下发「作用对象」的对话端点清单：`(源文件, 端点函数名, 是否流式)`。
#:
#: ★★ 为什么是清单、而不是第 251 轮那个 `src.count(...) == 2`：
#:   旧断言数的是**一个文件里出现几次**，两个方向都会骗人 ——
#:     · **少接一条链路**（正是本轮要修的形态：Listing / AIGC 全漏在外面）⇒
#:       选品那个文件里仍是 2 处 ⇒ 断言**照旧绿**，缺陷被盖了章；
#:     · 同一个文件里多写一处巧合的绑定 ⇒ 红，但那不是缺陷。
#:   ⇒ 改成「端点清单 × 每条端点都要绑一次」，并按 AST **现算**本文件里的
#:     `/chat*` 端点集合与清单对账：新增一条对话端点就必须来登记一行。
#:   ★ 与前端的分工：前端门禁（`check-chat-failure-path.cjs` 的 L11）判
#:     "哪几条链路**发**了这个字段"，本条判"哪几条端点**接**了它"。
CHAT_ENDPOINTS: dict = {
    "modules/product_research/router.py": [
        ("chat", False),
        ("chat_stream", True),
    ],
    "modules/listing_generator/router.py": [
        ("chat_with_listing_agent", False),
        ("chat_with_listing_agent_stream", True),
    ],
    "modules/aigc_media/router.py": [
        ("aigc_chat", False),
        ("aigc_chat_stream", True),
    ],
    # ★ 第 298 轮补：客服此前**完全没有**这条通道（第 251 / 257 两轮都没覆盖到）。
    #   缺口形状是「界面已经承诺了那条路」——差评处置台账里写着「在对话里直接问」，
    #   而差评应对技能第 0 步要 `get_customer_review_context(review_id)`，
    #   该 id 只能来自用户消息文本或**会话历史** ⇒ 第 250 轮那个洞静默复发。
    #   ★ 端点函数名以 AST 现算为准（`chat_endpoint`，不是目录里想当然的 `chat`）。
    "modules/customer_service/router.py": [
        ("chat_endpoint", False),
        ("chat_stream", True),
    ],
}

BIND_CALL = "bind_context_target(context_target_payload(request))"


def _chat_endpoints_in(src: str) -> list:
    """源码里 `/chat` / `/chat/stream` 端点的函数名（AST，剥注释之外的最硬形态）。

    ★ 走 AST 而不是字符串包含：注释掉一行 `@router.post("/chat")` 之后，
      `in src` 仍为真（本仓被 docstring / 注释骗过四次）。
    """
    import ast

    names = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in ("post", "get"):
                continue
            if not dec.args:
                continue
            path = dec.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                if path.value.rstrip("/").endswith("/chat") or path.value.rstrip("/").endswith(
                    "/chat/stream"
                ):
                    names.append((node.name, path.value.rstrip("/").endswith("/chat/stream")))
    return sorted(names)


def test_every_chat_endpoint_binds_context_target():
    """每一条对话端点都必须 `bind_context_target` —— **按端点清单对账**。

    ★ 漏一条的后果不是"少个字段"：那条链路的模型只能从用户消息或**会话历史**
      里猜"这次针对谁"，而猜错的结论打在别的品上时，界面/日志/测试全绿
      （第 250 轮那个洞的现场形态）。
    """
    for rel, expected in CHAT_ENDPOINTS.items():
        src = (BACKEND / rel).read_text(encoding="utf-8")

        # ① 现算端点集合与清单逐字相等（新增端点必须来登记）
        got = _chat_endpoints_in(src)
        assert got == sorted(expected), (
            f"{rel} 的 /chat 端点与清单不一致。\n"
            f"  实测: {got}\n  清单: {sorted(expected)}\n"
            f"新增一条对话端点就要在这份清单里加一行并给它补 bind_context_target —— "
            f"漏接是**静默**的（模型改从历史里猜对象）"
        )

        # ② 每条端点各绑一次（按函数体切块，不数全文件出现次数）
        for fn_name, is_stream in sorted(expected):
            call = f"async def {fn_name}"
            start = src.index(call)
            nxt = src.find("\n@router.", start + 1)
            body = src[start:] if nxt < 0 else src[start:nxt]
            assert body.count(BIND_CALL) == 1, (
                f"{rel}::{fn_name} 里 `{BIND_CALL}` 出现 "
                f"{body.count(BIND_CALL)} 次（要求恰好 1）"
            )
            if is_stream:
                # ★ 流式的写入点必须在**生成器体内**：包在返回 StreamingResponse
                #   的外层，`async with` 会在生成器被第一次迭代之前就退出 ⇒ 等于没设。
                gen_part = body.split("return StreamingResponse", 1)[0]
                assert BIND_CALL in gen_part, (
                    f"{rel}::{fn_name} 的绑定不在生成器体内（在 return StreamingResponse 之后）"
                    f"⇒ 等于没设，流式链路拿不到对象"
                )


def test_endpoint_scanner_is_not_vacuous():
    """门禁自检：端点扫描器必须真的认得出端点（否则上面那条在空集上恒绿）。"""
    fake = (
        '@router.post("/chat", response_model=X)\n'
        "async def chat(request: R):\n"
        "    pass\n"
        '@router.post(\n    "/chat/stream",\n    summary="s",\n)\n'
        "async def chat_stream(request: R):\n"
        "    pass\n"
        '@router.post("/approval/resume")\n'
        "async def resume(request: R):\n"
        "    pass\n"
    )
    got = _chat_endpoints_in(fake)
    assert got == [("chat", False), ("chat_stream", True)], got
    # 注释里的装饰器不算端点
    assert _chat_endpoints_in('# @router.post("/chat")\nx = 1\n') == []



# =========================================================== E. 名单不漂移
def test_required_list_matches_candidate_skills():
    """名单必须与技能仓库里「绑到 ProductResearcher 的 `candidate-` 技能」逐字相等。

    ★ 生产代码用**显式名单**（可 grep、可读），推导规则只写在门禁里 ——
      约定当判据是脆的，当**检查**是硬的。
      新增一条候选类技能却没登记 ⇒ 这条红。
    """
    from modules.skills.seed import DEMO_SKILLS

    derived = {
        s["name"]
        for s in DEMO_SKILLS
        if "ProductResearcher" in (s.get("agents") or [])
        and str(s.get("name", "")).startswith("candidate-")
    }
    assert derived, "推导不出任何候选类技能 —— 推导规则本身失效了"
    assert derived == set(TARGET_REQUIRED_SKILLS), (
        f"名单漂移：名单里多/少了 {derived ^ set(TARGET_REQUIRED_SKILLS)}"
    )


def test_required_skills_all_exist_and_are_bound_to_this_agent():
    """名单里每个名字都必须真实存在且绑在本 Agent 上（改名残留 ⇒ 红）。"""
    from modules.skills.seed import DEMO_SKILLS

    by_name = {s["name"]: s for s in DEMO_SKILLS}
    for name in sorted(TARGET_REQUIRED_SKILLS):
        assert name in by_name, f"{name} 在技能仓库里不存在（多半是改名的残留）"
        assert "ProductResearcher" in (by_name[name].get("agents") or []), (
            f"{name} 没有绑到 ProductResearcher"
        )


# =========================================================== F. 读口真的注册了
#
# ★ 第 257 轮：注册点从 `modules/product_research/context_target_section.py`
#   上提到 `modules/context_target_section.py`，触发点从"选品 router"改成
#   `modules/__init__.py`（包初始化 ⇒ 任何业务模块被 import 都覆盖到）。
#   ⇒ 下面三条判据的靶子跟着换，但**判的东西变严了**：
#     从"某一条链路 import 了它"变成"注册不得再被任何业务模块私有"。

SECTION_PY = BACKEND / "modules" / "context_target_section.py"
MODULES_INIT_PY = BACKEND / "modules" / "__init__.py"


def test_reader_section_is_imported_at_module_level():
    """★ 同 `test_memory_injection.test_facade_imports_the_prompt_section_module`：

    注册是 **import 副作用** ⇒ 「谁负责 import 它」必须是**可查的一行**。
    文件写出来却不 import ⇒ 段落**静默不注册**：不报错、日志全绿，
    模型只是永远看不到「不得从历史里挑一个顶上」那一段 —— 于是回到本洞。

    ★ 第 257 轮起这一行住在 `modules/__init__.py`：包初始化 ⇒ 任何
      `import modules.<子包>` 都先执行它，"某条链路的 router 恰好被导入"
      不再是注册成立的前提（Celery worker / 直接 new Agent 的测试都覆盖到）。

    ★ 用 AST 而非字符串包含：注释掉那行后 `in src` 仍为真（假绿）。
      只认**模块顶层** `ImportFrom`：塞进函数体内等于「随缘注册」。
    """
    import ast

    tree = ast.parse(MODULES_INIT_PY.read_text(encoding="utf-8"))
    found = any(
        isinstance(n, ast.ImportFrom)
        and n.level == 1
        and not (n.module or "")
        and any(a.name == "context_target_section" for a in n.names)
        for n in tree.body
    )
    assert found, (
        "modules/__init__.py 没有在**模块顶层** import context_target_section ⇒ "
        "注册永不发生，「不得沿用历史对象」那段永远进不了 system prompt"
    )


def test_reader_section_actually_registers():
    """运行时对账：**只要 import 过任意业务模块**，注册表里就必须有这一段。

    ★ 段名用正则从源码里取，**不 import 那个模块** —— 否则
      `from ...context_target_section import SECTION_NAME` 这一行本身就会触发
      `ensure_registered()`，把被测行为做掉：反向注入掉那行 import 之后，
      这条用例**照旧绿**（第 251 轮反向注入实锤的假绿，比没有判据更坏 ——
      它给缺陷盖章）。
    ★ 这里 import 的是 `modules.listing_generator.schemas`（**不是**选品模块）：
      选品模块一被 import 就覆盖到了触发点，用它来验等于把"上提"这件事验丢。
    """
    import re

    _sec = SECTION_PY.read_text(encoding="utf-8")
    m = re.search(r'SECTION_NAME\s*=\s*"([^"]+)"', _sec)
    assert m, "读不出 SECTION_NAME —— 用例自身失效，不是被测对象的问题"
    section_name = m.group(1)

    import modules.listing_generator.schemas  # noqa: F401 —— import 本身就是要验证的动作
    from ai_infra.prompt_sections import registered_sections

    assert section_name in registered_sections(), (
        f"import 了业务模块但注册表里没有 {section_name}：{registered_sections()}"
    )


def test_registration_is_not_owned_by_any_business_module():
    """★★ 注册点不得再回落到某个业务模块里（第 257 轮的核心不变量）。

    背景（老板报障）：这条机制对**全部 Agent** 生效，第 251 轮却把它注册在
    `modules/product_research/` 里 —— 于是"要给 Listing / AIGC 也接上"时，
    没有人的第一反应是去选品模块里找那个文件。机制被一个业务域的目录
    悄悄私有化了，而这个约定从未写在任何地方。

    ★ 判据走 AST（`ImportFrom` 的模块名 + 相对 import 解析）：
      注释里提到 `context_target_section` 不算（本文件自己就写了好几处）。
    """
    import ast

    offenders = []
    for p in sorted((BACKEND / "modules").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(BACKEND).as_posix()
        if rel == "modules/__init__.py":
            continue  # 公共注册点本身
        if p.parent == BACKEND / "modules":
            continue  # modules/ 根下的横切模块（就是它自己的家）
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                mod = n.module or ""
                names = [a.name for a in n.names]
                if "context_target_section" in mod or "context_target_section" in names:
                    offenders.append(f"{rel}:{n.lineno}")
    assert not offenders, (
        f"以下业务模块又在 import `context_target_section`：{offenders}\n"
        f"⇒ 注册点重新被某个业务域私有化。它应当只由 `modules/__init__.py` 触发 —— "
        f"业务模块 import 它不会多注册一次（`ensure_registered` 幂等），"
        f"但会让「这条机制属于谁」再次变得不可查。"
    )


# =========================================================== G. HTTP 端到端对照
#
# ★ 为什么只钉「拒答」这一侧：这一侧在 Agent 之前返回 ⇒ 不触网、快且稳。
#   「有对象 ⇒ 放行」由 D-2（`test_service_passes_through_when_target_present`，打桩计数）
#   覆盖；在 HTTP 层再测一遍要真跑 Agent，收益只是重复，代价是脆。
#
# ★ 与本洞的关系：老板看到的那段「好的，我们已经确定了评估对象：<水杯>」就是这两个
#   用例要挡的形态 —— 一个 200 + 一段**看着很正常**的上架建议。


async def test_http_chat_rejects_when_field_absent(client):
    """**老客户端**（请求体里根本没这个字段）⇒ 200 + 拒答。

    顺带把 router 的三态解析、绑定、依赖注入一起钉住：少任何一环，
    这里都会变成 200 + 一段正常的答复 —— 正是本洞的现场。
    """
    resp = await client.post(
        "/api/v1/product-research/chat",
        json={"message": "请按「上架建议」执行。", "skill": CANDIDATE_SKILL},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == NEED_TARGET_REPLY, (
        f"真端点没拒答 ⇒ 直接命中本洞。实得：{body.get('reply', '')[:120]!r}"
    )


async def test_http_chat_rejects_when_field_explicit_null(client):
    """**新客户端**的「明确没有对象」（`context_target: null`）⇒ 同样拒答。

    ★ 这一条专门盯「三态不能压成两态」：把 `null` 与"字段不出现"读成同一态的实现，
      会在这里放行（因为它把 `null` 当成了"客户端没参与"）。
    """
    resp = await client.post(
        "/api/v1/product-research/chat",
        json={
            "message": "请按「上架建议」执行。",
            "skill": CANDIDATE_SKILL,
            "context_target": None,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply"] == NEED_TARGET_REPLY, "两种「没有」被压成了一态"
