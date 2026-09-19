"""会话归属门禁（P0-1，2026-09-18）：`session_id` 是**客户端提供的**，必须判「是你的吗」

==============================================================================
★ 这条缺陷的两个可执行形态（修复前实测，生产模式 `auth_required=True`）
==============================================================================
B 持**自己的**有效 token，把 A 的 session_id 塞进请求：

    通道 1 —— `GET  /api/v1/conversations/{A的id}/history`  → 200 + A 的完整对话
              `POST /api/v1/conversations/{A的id}/messages` → 200，且 A 侧真被写入
              （三个端点当时**没有任何鉴权依赖**，`owner_id` 还是 body 里自报的）

    通道 2 —— `POST /api/v1/orchestrator/chat`（**前端在用**，`api/secretary.ts`）
              客户端给的 `session_id` 被直接拿来读历史 → 注入 LLM → 再把本轮
              两条消息写回去。这条比通道 1 更严重：泄露面一样，但它是活链路。

⇒ 本文件按「通道 1 / 通道 2 / 静态门禁 / 反向注入」四段组织。
   静态门禁那几条是**防复发**的：它们在 CI 里能对"又长出一个没判权的入口"说不。

★ 为什么静态门禁要写成 AST 而不是数串：
   本仓已有的教训 —— 断言「某符号不存在」会被**自己刚写的注释**绊倒
   （注释里逐字引用了被禁的名字，`grep -c` 得 3，全在注释里 ⇒ 假 FAIL）。
"""

import ast
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy import text

BACKEND = pathlib.Path(__file__).resolve().parents[1]
CONV_ROUTER = BACKEND / "modules" / "conversation" / "router.py"
CONV_SERVICE = BACKEND / "modules" / "conversation" / "service.py"

#: ★ **故意不分归属**的公开函数（第 151 轮登记）。
#:
#: `active_owner_ids` 是夜间调度的**枚举器**（「该给谁跑」的输入）。
#: 它返回的是 owner **id 列表**，不返回任何人的数据 —— 所以它没有、
#: 也不该有 `owner_id` 参数。
#:
#: ★★ 豁免不是「忘了」的委婉说法：登记在这里的同时，
#:   必须由 `test_platform_wide_readers_are_not_reachable_from_http`
#:   证明它**不可从 HTTP 触达**（两边共用这份名单，不各抄一份）。
PLATFORM_WIDE = {
    "active_owner_ids": "夜间整理枚举活跃 owner（只返回 id 列表）",
}



# ============================================================ 夹具

@pytest_asyncio.fixture
async def conv_users(make_user):
    """
    造 N 个**互相隔离**的用户，并在用例结束后连**会话**一起清干净。

    ★ 为什么不能只靠 `make_user` / `_purge_users`：
      `_purge_users` 删的是「指向 users 的外键依赖」和「按 shop_id 分区的业务表」。
      而 `conversations.owner_id` **没有外键**（它只是个普通索引列），
      且本仓写入的 `shop_id` 恒为 NULL ⇒ 两把扫帚都扫不到它。
      不自己清，开发库里会越堆越多（这正是 `owner_id` 全 NULL 那 57 行的成因之一）。
    """
    created = []

    async def _make(label: str = "u") -> dict:
        u = await make_user(label)
        created.append(u)
        return u

    yield _make

    ids = [u["user_id"] for u in created]
    if not ids:
        return
    from core.database import get_async_session

    async with get_async_session() as db:
        # 先删消息（conversation_messages.conversation_id 也无外键，必须自己动手）
        await db.execute(
            text(
                "DELETE FROM conversation_messages WHERE conversation_id IN ("
                "  SELECT id FROM conversations WHERE owner_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await db.execute(
            text("DELETE FROM conversations WHERE owner_id = ANY(:ids)"), {"ids": ids}
        )
        await db.commit()


async def _new_session(client, headers, agent_id: str = "secretary") -> str:
    r = await client.post(
        "/api/v1/conversations", json={"agent_id": agent_id}, headers=headers
    )
    assert r.status_code == 200, f"建会话失败: {r.status_code} {r.text}"
    return r.json()["session_id"]


async def _append(client, headers, sid: str, content: str, role: str = "user"):
    return await client.post(
        f"/api/v1/conversations/{sid}/messages",
        json={"role": role, "content": content},
        headers=headers,
    )


async def _history_count(sid: str) -> int:
    from core.database import get_async_session

    async with get_async_session() as db:
        n = (
            await db.execute(
                text("SELECT count(*) FROM conversation_messages WHERE conversation_id = :s"),
                {"s": sid},
            )
        ).scalar()
    return int(n)


async def _db_owner(sid: str):
    from core.database import get_async_session

    async with get_async_session() as db:
        return (
            await db.execute(
                text("SELECT owner_id FROM conversations WHERE id = :s"), {"s": sid}
            )
        ).scalar_one_or_none()


# ==================================================== 通道 1：/conversations/*

@pytest.mark.asyncio
async def test_owner_can_read_and_write_own_session(client, conv_users, auth_on):
    """基线：自己的会话自己能用（防止"一律 404"式的过度修复）。"""
    a = await conv_users("owner")
    sid = await _new_session(client, a["headers"])
    assert (await _append(client, a["headers"], sid, "我的第一句话")).status_code == 200

    r = await client.get(f"/api/v1/conversations/{sid}/history", headers=a["headers"])
    assert r.status_code == 200, r.text
    assert [m["content"] for m in r.json()["history"]] == ["我的第一句话"]


@pytest.mark.asyncio
async def test_other_user_cannot_read_history(client, conv_users, auth_on):
    """★ B 持有效 token 读 A 的会话历史 ⇒ 404（修复前是 200 + 全文）。"""
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid, "A 的商业机密")

    r = await client.get(f"/api/v1/conversations/{sid}/history", headers=b["headers"])
    assert r.status_code == 404, f"越权读到了内容: {r.status_code} {r.text}"
    assert "商业机密" not in r.text


@pytest.mark.asyncio
async def test_other_user_cannot_append_message(client, conv_users, auth_on):
    """★ B 往 A 的会话写消息 ⇒ 404，且 A 侧一条都没多（污染为零）。"""
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid, "原有内容")
    before = await _history_count(sid)

    r = await _append(client, b["headers"], sid, "B 注入的脏数据")
    assert r.status_code == 404, f"越权写入了: {r.status_code} {r.text}"
    assert await _history_count(sid) == before, "A 的会话被污染了"


@pytest.mark.asyncio
async def test_missing_session_and_foreign_session_are_indistinguishable(
    client, conv_users, auth_on
):
    """不存在的 ID 与别人的 ID 必须**同一响应**，否则可拿来枚举有效 session_id。"""
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid = await _new_session(client, a["headers"])

    r_foreign = await client.get(f"/api/v1/conversations/{sid}/history", headers=b["headers"])
    r_absent = await client.get(
        "/api/v1/conversations/session_ffffffffffffffff/history", headers=b["headers"]
    )
    assert r_foreign.status_code == r_absent.status_code == 404
    assert r_foreign.json() == r_absent.json(), "响应体不同 ⇒ 泄露了 session_id 是否存在"


@pytest.mark.asyncio
async def test_self_reported_owner_id_is_ignored(client, conv_users, auth_on):
    """★ `owner_id` 是客户端自报字段（修复前能把自己会话挂到别人名下）⇒ 必须被忽略。"""
    a = await conv_users("victim")
    b = await conv_users("attacker")

    r = await client.post(
        "/api/v1/conversations",
        json={"agent_id": "secretary", "title": "冒充", "owner_id": a["user_id"]},
        headers=b["headers"],
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    owner = await _db_owner(sid)
    assert owner == b["user_id"], f"自报 owner_id 被采纳了: {owner!r}"


@pytest.mark.asyncio
async def test_platform_admin_can_access_any_conversation(client, conv_users, auth_on):
    """平台超管是**另一条链路**（`User.role == admin`）⇒ 只影响超管，不影响普通用户。"""
    a = await conv_users("owner")
    adm = await conv_users("admin")
    sid = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid, "只有超管能看的内容")

    from core.database import get_async_session
    from core.identity.models import UserRole

    # ★ 原生 SQL 里的 enum 字面量是 **name**（`ADMIN`），不是 `.value`（`admin`）：
    #   SQLAlchemy 的 `Enum(UserRole)` 默认按 **name** 落库。写小写会直接
    #   `InvalidTextRepresentationError: invalid input value for enum userrole: "admin"`。
    #   这里从枚举取名字而不是手抄字面量 —— 手抄就是下一次改名时的静默失效点。
    async with get_async_session() as db:
        await db.execute(
            text("UPDATE users SET role = :r WHERE id = :u"),
            {"r": UserRole.ADMIN.name, "u": adm["user_id"]},
        )
        await db.commit()

    r = await client.get(f"/api/v1/conversations/{sid}/history", headers=adm["headers"])
    assert r.status_code == 200, r.text
    assert "只有超管能看的内容" in r.text


# ==================================== 通道 2：POST /orchestrator/chat

@pytest.mark.asyncio
async def test_orchestrator_discards_foreign_session_id(client, conv_users, auth_off):
    """★★★ 活链路：B 带 A 的 session_id 调店秘书 ⇒ 绝不复用、绝不给内容。

    用 `auth_off`（演示档）**但带真 token**：这正是老板本机的运行模式，
    也是第 118 轮 optional-auth 修复后「带真 token 必须拿到真身份」的那一档。
    能在这里拦住，说明判定挂在**归属**上，而不是挂在"有没有 token"上。
    """
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid_a = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid_a, "A 的成本结构：毛利 62%")
    before = await _history_count(sid_a)

    r = await client.post(
        "/api/v1/orchestrator/chat",
        json={"message": "你好", "session_id": sid_a},
        headers=b["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["session_id"] != sid_a, "复用了别人的 session_id"
    assert "毛利 62%" not in r.text, "别人的历史被回显了"
    assert await _history_count(sid_a) == before, "A 的会话被 B 的对话污染"
    # B 拿到的是**自己的**新会话
    assert await _db_owner(body["session_id"]) == b["user_id"]


@pytest.mark.asyncio
async def test_orchestrator_reuses_own_session_id(client, conv_users, auth_off):
    """基线：自己的 session_id 必须照常复用（不能一律新建，那是过度修复）。"""
    a = await conv_users("owner")
    sid = await _new_session(client, a["headers"])

    r = await client.post(
        "/api/v1/orchestrator/chat",
        json={"message": "你好", "session_id": sid},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid
    assert await _history_count(sid) >= 2, "本轮 user + assistant 没有落库"


# ==================================================== 静态门禁（防复发）

def _route_handlers(src: str):
    """返回 {函数名: (是否路由端点, 全部默认值 AST 的 dump 文本)}。"""
    out = {}
    for n in ast.parse(src).body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_ep = any("router" in ast.dump(d) for d in n.decorator_list)
        defaults = [d for d in (list(n.args.defaults) + list(n.args.kw_defaults)) if d is not None]
        out[n.name] = (is_ep, [ast.dump(d) for d in defaults])
    return out


def test_conversation_router_endpoints_declare_identity_dependency():
    """★ `modules/conversation/router.py` 的**每个**端点都必须自己声明身份依赖。

    为什么不能只靠 main.py 的 router 级 `BUSINESS_AUTH`：
      路由级依赖**不向 handler 注入参数** —— 只挂 router 级的话 handler 根本拿不到
      `current_user`，归属判定无从谈起。「路由挂了一层依赖」看起来像有鉴权，
      而它只挡住了匿名。这正是本缺陷最容易复发的形态。
    """
    handlers = _route_handlers(CONV_ROUTER.read_text(encoding="utf-8"))
    eps = {k: v for k, v in handlers.items() if v[0]}
    assert len(eps) == 3, f"端点数变了（期望 3）: {sorted(eps)}"
    bad = [k for k, (_, defs) in eps.items()
           if not any("require_auth_if_enabled" in d for d in defs)]
    assert not bad, f"这些端点没有声明身份依赖: {bad} —— 归属判定会失效"


def test_identity_gate_scanner_is_not_vacuous():
    """反向注入：把依赖拿掉，上面的扫描必须**判它为不合规**（防门禁恒绿）。"""
    fake = (
        "from x import require_auth_if_enabled\n"
        "router = APIRouter()\n"
        "@router.get('/a')\n"
        "async def a(session_id: str, limit: int = 20):\n"
        "    pass\n"
    )
    handlers = _route_handlers(fake)
    assert handlers["a"][0] is True
    assert not any("require_auth_if_enabled" in d for d in handlers["a"][1]), \
        "扫描函数漏报：无依赖的端点被判成合规"


def test_conversation_create_request_has_no_ownership_fields():
    """★ 创建入参不得含归属类字段 —— 归属只能来自服务端身份。"""
    tree = ast.parse(CONV_ROUTER.read_text(encoding="utf-8"))
    cls = [n for n in ast.walk(tree)
           if isinstance(n, ast.ClassDef) and n.name == "ConversationCreateRequest"]
    assert cls, "没找到 ConversationCreateRequest（改名了？同步更新本门禁）"
    fields = {b.target.id for b in cls[0].body if isinstance(b, ast.AnnAssign)}
    assert fields == {"agent_id", "title"}, (
        f"ConversationCreateRequest 又多出字段: {sorted(fields)} —— "
        f"owner_id / shop_id 曾在这里被客户端自报"
    )


def test_service_public_api_declares_authorship_param():
    """★ `conversation/service.py` 的每个公开函数都必须显式声明"归属从哪来"。

    新增一个公开读/写函数而不声明归属，就是新开一条不判权的通道。
    本门禁让"忘了"变成一次测试失败，而不是一次上线后的越权。
    """
    # 期望：函数名 -> ("首参名" 或 "关键字必填参数名")
    expected = {
        "create_conversation": ("kwonly_required", "owner_id"),
        "get_owned_conversation": ("first", "user"),
        "require_owned_conversation": ("first", "user"),
        "history_of": ("first", "conv"),
        "get_history": ("first", "user"),
        "append_message": ("first", "user"),
        # 第 149–151 轮批 C2-4：夜间整理的**读口**（跨会话只读原语）
        "recent_messages_of_owner": ("first", "owner_id"),
        # 不分归属的**枚举器**：理由见模块级 PLATFORM_WIDE（同一事实不抄两遍）
        "active_owner_ids": ("platform_wide", ""),
    }
    tree = ast.parse(CONV_SERVICE.read_text(encoding="utf-8"))
    public = {
        n.name: n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    }
    assert set(public) == set(expected), (
        f"公开函数集合变了。多出: {sorted(set(public) - set(expected))}；"
        f"缺失: {sorted(set(expected) - set(public))}。"
        f"新增公开函数请同步在本门禁登记它的归属参数"
    )
    for name, (kind, param) in expected.items():
        fn = public[name]
        if kind == "platform_wide":
            # ★ 登记为 platform_wide 的函数**不许**带 owner_id 参数 ——
            #   带了就说明它不是「平台级」，而是漏了归属过滤，罪更重。
            args = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
            assert not any(a.arg == "owner_id" for a in args), (
                f"{name} 登记为 platform_wide，却带着 owner_id 参数 —— "
                f"请改成正常登记或去掉该参数"
            )
            # ★ 豁免必须与 PLATFORM_WIDE 对得上：登记处说「故意不分归属」，
            #   豁免名单里却没有它 ⇒ 两处口径已经分叉了。
            assert name in PLATFORM_WIDE, f"{name} 未在 PLATFORM_WIDE 里登记"
            continue
        if kind == "first":
            args = fn.args.posonlyargs + fn.args.args
            assert args and args[0].arg == param, \
                f"{name} 的首参应为 {param!r}，实际 {[a.arg for a in args][:1]}"
        else:
            kwonly = [a.arg for a in fn.args.kwonlyargs]
            assert param in kwonly, f"{name} 缺少关键字参数 {param!r}（实际 {kwonly}）"
            # ★ 真正要钉的是「**没有默认值**」：否则新调用点忘传会静默落一条
            #   无主会话（对谁都不可访问，用户只看到"刷新后对话丢了"）。
            idx = kwonly.index(param)
            assert fn.args.kw_defaults[idx] is None, (
                f"{name}.{param} 不能有默认值 —— 有默认值就失去「忘传即报错」的保护"
            )


def test_platform_wide_readers_are_not_reachable_from_http():
    """★★★ `PLATFORM_WIDE` 里的豁免必须**配一条不可达断言**。

    否则「豁免」就只是「忘了」的委婉说法：一个不分归属的公开函数，
    只要有人把它挂上一个端点，读的就是**全库所有人的 id/数据**。

    ★ 本用例与 `PLATFORM_WIDE` **共用同一份名单**（不从别处再抄一遍）：
      同一事实两份写法必然漂移，而漂移的方向是「豁免了但没测」。

    ★ 为什么扫 `router.py` 而不是扫「谁 import 了它」：HTTP 触达的**唯一**
      入口就是各模块的 `router.py`。扫 import 图会把「被 service 内部复用」
      也算成违规（那是正常复用，不是触达），反而逼人把名字改晦涩。

    反向注入已验：在 `modules/memory/router.py` 里写一行
    `from modules.conversation import active_owner_ids`（哪怕只是 import 不用）
    ⇒ 本条变红。
    """
    offenders = []
    for name in PLATFORM_WIDE:
        for p in (BACKEND / "modules").rglob("router.py"):
            if "__pycache__" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                # ★ 三态齐查：`Name`（直接引用）、`Attribute`（模块属性）、
                #   `alias`（import 进来 —— **哪怕当下没用**）。
                #   只查前两态时漏掉「先 import 备用」这一步，而它正是
                #   「挂上端点」的前一步；反向注入实测：只加一行 import，
                #   旧判据不红 —— 而本用例的 docstring 却承诺了它会红。
                #   （注释承诺型假门禁，见 r141 §2.4 那条铁律。）
                if isinstance(n, ast.Name) and n.id == name:
                    offenders.append(f"{p.relative_to(BACKEND)}:{n.lineno} NAME {name}")
                elif isinstance(n, ast.Attribute) and n.attr == name:
                    offenders.append(f"{p.relative_to(BACKEND)}:{n.lineno} ATTR {name}")
                elif isinstance(n, ast.alias) and n.name.split(".")[-1] == name:
                    offenders.append(f"{p.relative_to(BACKEND)}:{n.lineno} IMPORT {name}")
    assert not offenders, (
        f"平台级（不分归属）的读口被 HTTP 层引用了: {offenders} —— "
        f"它没有归属过滤，一旦挂上端点就是全库可读"
    )


def test_legacy_unauthenticated_reader_is_gone():
    """★ 旧的 `conversation_exists(conversation_id)`（只问存在、不问归属）必须已删除。

    ★ 用 AST 数**代码级引用**，不用数串：本仓踩过"断言 X 不存在，结果被自己
      刚写的注释绊倒"（注释里逐字引用了被禁的名字 ⇒ 假 FAIL / 假 PASS）。
    """
    hits = []
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in p.parts or "versions_legacy" in p.parts:
            continue
        try:
            t = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "conversation_exists":
                hits.append(f"DEF {p.relative_to(BACKEND)}:{n.lineno}")
            elif isinstance(n, ast.Name) and n.id == "conversation_exists":
                hits.append(f"USE {p.relative_to(BACKEND)}:{n.lineno}")
            elif isinstance(n, ast.Attribute) and n.attr == "conversation_exists":
                hits.append(f"ATTR {p.relative_to(BACKEND)}:{n.lineno}")
    assert not hits, f"无归属的会话存在性判定又出现了: {hits}"


def test_create_conversation_call_sites_pass_owner_id():
    """★ `create_conversation` 的每个调用点都必须显式传 `owner_id=`（防新增通道漏传）。"""
    bad = []
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in p.parts or p == CONV_SERVICE:
            continue
        try:
            t = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if name == "create_conversation":
                    if "owner_id" not in {k.arg for k in n.keywords}:
                        bad.append(f"{p.relative_to(BACKEND)}:{n.lineno}")
    assert not bad, f"这些调用点没传 owner_id ⇒ 会落无主会话: {bad}"


# ==================================================== 反向注入（判定真的在生效）

@pytest.mark.asyncio
async def test_ownership_gate_is_not_vacuous(client, conv_users, monkeypatch, auth_on):
    """★★ 反向注入：把归属判定打穿，上面的 404 必须**立刻变成 200**。

    没有这一条，上面那批 404 可能来自任何一个别的原因（路由没挂上、依赖报错、
    服务层抛异常被吞），门禁看起来全绿而实际早已失效。
    """
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid, "A 的商业机密")

    r = await client.get(f"/api/v1/conversations/{sid}/history", headers=b["headers"])
    assert r.status_code == 404, "前置条件不成立：本来就没挡住"

    import modules.conversation.service as svc

    monkeypatch.setattr(svc, "can_access_conversation", lambda user, conv: True)

    r2 = await client.get(f"/api/v1/conversations/{sid}/history", headers=b["headers"])
    assert r2.status_code == 200, (
        "打穿判定后仍然 404 ⇒ 上面的 404 不是这道判定给出的，"
        "本文件的越权断言没有验证到真正的东西"
    )
    assert "商业机密" in r2.text


@pytest.mark.asyncio
async def test_orchestrator_gate_is_not_vacuous(
    client, conv_users, monkeypatch, auth_off
):
    """★★ 反向注入（活链路）：打穿归属判定后，店秘书必须**原样复用** A 的 session_id
    并把 A 的历史读出来 —— 这才证明上面那条"丢弃并新建"是归属判定给出的，
    而不是被别的原因（路由没挂上、route() 抛异常被吞）顺带挡住的。

    ★ 这条比 `test_ownership_gate_is_not_vacuous` 更重要：通道 2 是**前端在跑**的
      真实链路，通道 1 目前前端 0 引用。门禁最容易在"没人走的那条路"上恒绿。
    """
    a = await conv_users("victim")
    b = await conv_users("attacker")
    sid_a = await _new_session(client, a["headers"])
    await _append(client, a["headers"], sid_a, "A 的成本结构：毛利 62%")
    before = await _history_count(sid_a)

    # 前置：没打穿时必须被拦（否则下面的断言什么也没证明）
    r = await client.post(
        "/api/v1/orchestrator/chat",
        json={"message": "你好", "session_id": sid_a},
        headers=b["headers"],
    )
    assert r.status_code == 200 and r.json()["session_id"] != sid_a

    import modules.conversation.service as svc

    monkeypatch.setattr(svc, "can_access_conversation", lambda user, conv: True)

    r2 = await client.post(
        "/api/v1/orchestrator/chat",
        json={"message": "你好", "session_id": sid_a},
        headers=b["headers"],
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["session_id"] == sid_a, (
        "打穿判定后仍然没复用 A 的 session_id ⇒ 「丢弃」另有来源，"
        "本文件的 orchestrator 越权断言是假绿"
    )
    # 读写两侧都复现：A 的会话真的被 B 追加了消息
    assert await _history_count(sid_a) > before, "写侧没复现 ⇒ 只拦住了读"
