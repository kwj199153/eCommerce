# -*- coding: utf-8 -*-
"""长期记忆的**跨语言契约**门禁（第 152 轮 · 批 C2 前端接线）。

为什么需要它
============
`frontend/src/api/memory.ts` 的类型是照着后端返回结构**手抄**的。而"抄错一个
字段名"这件事在本项目里有一个非常难发现的性质：

    它**不会报错**。

· 后端返回 `entry_count`，前端写 `entryCount` ⇒ TS 编译通过（字面量类型是
  自己声明的）、运行时拿到 `undefined`、界面显示 `0 / 60 条` 或干脆空白；
· 后端多返回一个字段 ⇒ 前端永远看不见它，也没有任何东西会红；
· 后端把 `enabled` 改名 ⇒ 界面开关永远是"关"，而库里的值是对的。

r141 §2.4 判定 `MemoryEvolution.vue` 是假页面，靠的是"它展示了一份编造的数据"。
而**类型对不上**是同一类失效的另一种形态：展示的不是编造的，是 `undefined`。
⇒ 必须有一条断言把两侧**真对上**，而不是各自相信自己的那一份。

四组断言
========
    A 形状（双向）：TS 接口字段集合 == 真库 + 真 HTTP 返回的 JSON 键集合。
      ★ 走**真 HTTP**（`client` 夹具，ASGI）+ **真库**（`user` 夹具真注册真登录），
        不 mock。因为要验的正是 `response_model` 序列化之后的那份 JSON。
    B 取值域（双向）：TS `DISTILL_REASON_CODES` == 后端全部 `reason` 生产者的取值。
      ★ 这条抓的是一个**真实缺陷**：本文件第一版手写的联合类型只有闸门那三种
        （disabled / too_soon / cooling），而一个刚注册、还没说过话的用户点
        「立即整理」拿到的第一个 `reason` 就是 `no_messages` —— 界面第一次
        出现的值就不在类型里。
    C 拒绝路径：6 个端点匿名一律 **401**（fail-closed）。
      ★ 前端抽屉的 `needLogin` 出口、以及"记忆不属于任何人时谁都读不到"这条
        业务判据，都建立在"后端确实会拒"之上。只在服务层测不够 ——
        HTTP 面才是前端真正打交道的那一层。
    D 出参不含 `owner_id`：归属只进不出（前端不需要它，泄露它没有收益）。

★ 与 `test_memory_distill.py`（C2-4 门禁）的分工
  那个文件钉的是**调度与形态**（beat 任务名、不可跨 loop、AST 形态）；
  本文件钉的是**HTTP 面与前端类型的一致性**。两者不重叠。

★ 反向注入（怎么改会变红，逐条实测）
  A：把 `api/memory.ts` 里任一接口字段改名（如 `entry_count` → `entryCount`）
     ⇒ 该接口的相等断言两边同时报出"缺哪个 / 多哪个"。
     ★ 环境变量 `MEMORY_TS_API` 可指向副本，便于在不改工作区的前提下实测。
  B：在 `tasks.py` 加一种 `reason="xxx"`，或在 TS 数组里删一项 ⇒ B 组变红。
  C：把某个端点的依赖从 `_REQUIRE_USER` 摘掉 ⇒ C 组变红。
"""

from __future__ import annotations

import ast
import os
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

_TS_API_ENV = os.environ.get("MEMORY_TS_API")
TS_API = (
    pathlib.Path(_TS_API_ENV)
    if _TS_API_ENV
    else REPO / "frontend" / "src" / "api" / "memory.ts"
)
TASKS_PY = BACKEND / "modules" / "memory" / "tasks.py"
SERVICE_PY = BACKEND / "modules" / "memory" / "service.py"

#: 记忆路由的全部端点。★ 与 `router.py` 的 6 个装饰器一一对应；
#: 少列一个不会让本文件变红（只是少测一个），多列一个会让 C 组恒红。
MEMORY_ENDPOINTS = (
    ("GET", "/api/v1/memory"),
    ("PUT", "/api/v1/memory"),
    ("PUT", "/api/v1/memory/profile"),
    ("POST", "/api/v1/memory/reset"),
    ("GET", "/api/v1/memory/logs"),
    ("POST", "/api/v1/memory/distill"),
)

#: 两条**列表**行 ⇒ `parse_markdown` 把它们各自成条（连续非列表行会合成一条）。
SAMPLE_MARKDOWN = (
    "# 沟通偏好\n"
    "- 结论先行，不喜欢长篇大论\n"
    "- 数据说话，对比表格优于纯文字\n"
)

#: 参与"形状相等"比对的 TS 接口
SHAPE_INTERFACES = (
    "MemorySnapshot",
    "MemoryProfile",
    "MemoryEntry",
    "MemoryLimits",
    "MemoryLog",
    "DistillResult",
    "DistillResponse",
)


# ============================================================ 工具


def _ts_interface_fields(src: str, name: str) -> set[str]:
    """抽出 `export interface NAME { ... }` 的字段名。

    ★ 只认**缩进恰好 2 个空格**的 `名字:` 行：接口里的注释行以 `/` 或 `*` 开头
      不匹配，嵌套对象的字段缩进 ≥4 个空格也不匹配。
    """
    m = re.search(r"export interface " + name + r"\s*\{(?P<body>.*?)\n\}", src, re.S)
    assert m is not None, (
        f"TS 文件里找不到接口 {name} —— 若已改名，本门禁对该接口的断言会静默失效，"
        f"请同步更新 SHAPE_INTERFACES"
    )
    return set(re.findall(r"^\s{2}(\w+)\??\s*:", m.group("body"), re.M))


def _ts_const_string_array(src: str, name: str) -> list[str]:
    """抽出 `export const NAME = [ 'a', 'b' ] as const` 的成员。"""
    m = re.search(
        r"export const " + name + r"\s*=\s*\[(?P<body>.*?)\]\s*as const", src, re.S
    )
    assert m is not None, f"TS 文件里找不到常量数组 {name}"
    return re.findall(r"'([^']*)'", m.group("body"))


def _claim_reason_codes() -> set[str]:
    """`service.claim_distill_run` 返回的**原因代码**（元组第 2 项的字面量）。

    ★ 用 AST 而不是正则扫整个文件：`return False, "x"` 这种形状在别处也可能出现，
      扫全文件会把无关的字符串算进来。只在这个函数的**体内**找。
    """
    tree = ast.parse(SERVICE_PY.read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "claim_distill_run"
        ),
        None,
    )
    assert fn is not None, "service.py 里找不到 claim_distill_run"
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            if len(node.value.elts) >= 2:
                second = node.value.elts[1]
                if (
                    isinstance(second, ast.Constant)
                    and isinstance(second.value, str)
                    and second.value
                ):
                    out.add(second.value)
    return out


def _outcome_reason_codes() -> set[str]:
    """`tasks.py` 里所有 `_outcome(reason="...")` 的字面量取值。

    ★ `reason=skip_code`（变量）不计入 —— 它们的取值来自 `claim_distill_run`，
      由 `_claim_reason_codes()` 负责收集。两处合起来才是全集。
    """
    tree = ast.parse(TASKS_PY.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if fname != "_outcome":
            continue
        for kw in node.keywords:
            if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str) and kw.value.value:
                    out.add(kw.value.value)
    return out


def _backend_reason_codes() -> set[str]:
    return _claim_reason_codes() | _outcome_reason_codes()


async def _purge_memory(owner_ids: list[str]) -> None:
    """删掉这几次调用产生的记忆行。

    ★ 为什么不能只靠 `_purge_users`（conftest 里那个唯一清理实现）：
      长期记忆的三张表 `owner_id` 是 `String(36)`，**没有外键**指向 `users`
      （见 `db_model.py` 的论证：它要能独立存在）。所以 `_purge_users`
      按外键依赖顺序删表时不会碰到它们 —— 删了用户，记忆行留在库里。
      ⇒ 本模块的用例必须自己收尾，否则每跑一次全量就往库里堆一批孤儿。
    """
    from sqlalchemy import delete

    from core.database import get_async_session
    from modules.memory.db_model import (
        MemoryEntryRecord,
        MemoryLogRecord,
        MemoryProfileRecord,
    )

    async with get_async_session() as s:
        await s.execute(
            delete(MemoryLogRecord).where(MemoryLogRecord.owner_id.in_(owner_ids))
        )
        await s.execute(
            delete(MemoryEntryRecord).where(MemoryEntryRecord.owner_id.in_(owner_ids))
        )
        await s.execute(
            delete(MemoryProfileRecord).where(
                MemoryProfileRecord.owner_id.in_(owner_ids)
            )
        )


def _diff(a: set, b: set) -> str:
    """给人看的差异描述（缺哪个 / 多哪个都要说，否则排查时只能靠猜）。"""
    return f"仅左侧有={sorted(a - b)} 仅右侧有={sorted(b - a)}"


# ============================================================ A 形状（双向）


async def test_memory_json_shape_matches_frontend_types(client, user):
    """真库 + 真 HTTP 跑完 6 个端点，逐个对象与 TS 接口**双向**比键。"""
    ts = TS_API.read_text(encoding="utf-8")
    iface = {n: _ts_interface_fields(ts, n) for n in SHAPE_INTERFACES}
    codes = _ts_const_string_array(ts, "DISTILL_REASON_CODES")

    headers = {"Authorization": f"Bearer {user['token']}"}
    owner = user["user_id"]

    try:
        # ---------- 1) GET 空记忆 ----------
        r = await client.get("/api/v1/memory", headers=headers)
        assert r.status_code == 200, f"GET /memory: {r.status_code} {r.text}"
        snap = r.json()
        assert set(snap) == iface["MemorySnapshot"], _diff(
            iface["MemorySnapshot"], set(snap)
        )
        # ★ 空记忆必须是空串，不是"暂无记忆"这种占位文案 ——
        #   占位文案会被 parse_markdown 读成一条真记忆（router 的 docstring 有论证）。
        assert snap["markdown"] == "", f"空记忆的 markdown 应为空串：{snap['markdown']!r}"
        assert snap["entry_count"] == 0
        assert set(snap["profile"]) == iface["MemoryProfile"], _diff(
            iface["MemoryProfile"], set(snap["profile"])
        )
        assert set(snap["limits"]) == iface["MemoryLimits"], _diff(
            iface["MemoryLimits"], set(snap["limits"])
        )

        # ---------- 2) PUT 开关（返回权威值） ----------
        r = await client.put(
            "/api/v1/memory/profile", headers=headers, json={"enabled": True}
        )
        assert r.status_code == 200, f"PUT /memory/profile: {r.status_code} {r.text}"
        prof = r.json()
        assert set(prof) == {"profile"}, _diff({"profile"}, set(prof))
        assert set(prof["profile"]) == iface["MemoryProfile"], _diff(
            iface["MemoryProfile"], set(prof["profile"])
        )
        assert prof["profile"]["enabled"] is True, "返回值必须是库里的权威值"

        # ---------- 3) PUT 保存整份 ----------
        r = await client.put(
            "/api/v1/memory",
            headers=headers,
            json={"markdown": SAMPLE_MARKDOWN, "source": "manual"},
        )
        assert r.status_code == 200, f"PUT /memory: {r.status_code} {r.text}"
        saved = r.json()
        assert set(saved) == iface["MemorySnapshot"], _diff(
            iface["MemorySnapshot"], set(saved)
        )
        assert saved["entry_count"] == 2, f"两行列表应成 2 条：{saved['entries']}"
        assert saved["entries"], "保存后 entries 不该为空"
        assert set(saved["entries"][0]) == iface["MemoryEntry"], _diff(
            iface["MemoryEntry"], set(saved["entries"][0])
        )
        assert set(saved["limits"]) == iface["MemoryLimits"], _diff(
            iface["MemoryLimits"], set(saved["limits"])
        )

        # ---------- 4) GET 时间线 ----------
        r = await client.get("/api/v1/memory/logs", headers=headers)
        assert r.status_code == 200, f"GET /memory/logs: {r.status_code} {r.text}"
        logs = r.json()["logs"]
        assert logs, "刚保存过，时间线至少该有一条记录（这是'它真的跑过'的唯一证据）"
        assert set(logs[0]) == iface["MemoryLog"], _diff(
            iface["MemoryLog"], set(logs[0])
        )
        # ★ 界面按 `is_failure` 上色，所以它必须是 bool（不是 None / 字符串）
        assert isinstance(logs[0]["is_failure"], bool), (
            f"is_failure 必须是 bool：{logs[0]['is_failure']!r}"
        )

        # ---------- 5) POST 立即整理 ----------
        r = await client.post("/api/v1/memory/distill", headers=headers)
        assert r.status_code == 200, f"POST /memory/distill: {r.status_code} {r.text}"
        dis = r.json()
        assert set(dis) == iface["DistillResponse"], _diff(
            iface["DistillResponse"], set(dis)
        )
        assert set(dis["result"]) == iface["DistillResult"], _diff(
            iface["DistillResult"], set(dis["result"])
        )
        assert set(dis["memory"]) == iface["MemorySnapshot"], _diff(
            iface["MemorySnapshot"], set(dis["memory"])
        )
        # ★★ 这条是 B 组在**运行期**的落地：真跑出来的 reason 必须落在前端那份
        #    数组里。这个用户从没说过话 ⇒ 实测拿到 `no_messages`，
        #    而它正是本文件第一版手写联合类型**没有**的那个值。
        assert dis["result"]["reason"] in codes, (
            f"运行期 reason={dis['result']['reason']!r} 不在前端 DISTILL_REASON_CODES "
            f"{codes} 里 —— 界面第一次出现的值就不在类型里"
        )

        # ---------- 6) POST 重置 ----------
        r = await client.post("/api/v1/memory/reset", headers=headers)
        assert r.status_code == 200, f"POST /memory/reset: {r.status_code} {r.text}"
        reset = r.json()
        assert set(reset) == iface["MemorySnapshot"], _diff(
            iface["MemorySnapshot"], set(reset)
        )
        assert reset["entry_count"] == 0, "重置后条目必须清零"
        # ★ 重置**保留开关**（用户的意思是"忘掉"，不是"以后别记了"）
        assert reset["profile"]["enabled"] is True, "重置不该顺手关掉开关"
    finally:
        await _purge_memory([owner])


# ============================================================ B 取值域（双向）


def test_distill_reason_codes_match_backend_producers():
    """TS 的 reason 数组 == 后端两处生产者的取值集合。

    ★ 纯静态（不需要 DB / 不需要起应用）：比的是**源码**。
      两个生产者：
        `service.claim_distill_run` —— 三道闸门（disabled / too_soon / cooling）
        `tasks._outcome(reason=)`   —— 放行之后的四种
    """
    ts_codes = set(_ts_const_string_array(TS_API.read_text(encoding="utf-8"), "DISTILL_REASON_CODES"))
    backend = _backend_reason_codes()

    assert backend, "后端一个 reason 取值都没扫到 —— 生产者改名了？本断言会静默变空"
    assert ts_codes == backend, (
        "reason 取值集合两侧不一致（" + _diff(ts_codes, backend) + "）。\n"
        f"  前端 DISTILL_REASON_CODES = {sorted(ts_codes)}\n"
        f"  后端生产者 = {sorted(backend)}\n"
        "  ⇒ 后端新增一种结局时，必须同步 frontend/src/api/memory.ts"
    )


# ============================================================ C 拒绝路径


async def test_memory_endpoints_are_fail_closed_for_anonymous(client):
    """6 个端点匿名一律 401（不是 403、不是 200、不是 500）。

    ★ 为什么状态码本身是判据：前端抽屉要据 **401** 决定"给不给去登录的出口"
      （403 是"你没权限"，那类问题登录也解决不了，指向登录就是误导）。

    ★ 为什么每个写端点都带一份**合法**请求体：若带空体 / 缺字段的体，
      FastAPI 有可能先报 422（请求体校验）而不是 401 —— 那这条断言就变成
      在测 pydantic 的必填校验，而不是「门禁有没有挂」。带合法体之后，
      剩下的唯一变量就是身份，401 才能真正归因到 fail-closed。
    """
    bodies = {
        ("PUT", "/api/v1/memory"): {"markdown": "", "source": "manual"},
        ("PUT", "/api/v1/memory/profile"): {"enabled": True},
    }
    for method, path in MEMORY_ENDPOINTS:
        r = await client.request(method, path, json=bodies.get((method, path)))
        assert r.status_code == 401, (
            f"{method} {path} 匿名访问应 401，实际 {r.status_code}：{r.text[:200]}"
        )
        detail = r.json().get("detail", "")
        # 文案要说清"是哪个功能要登录"，否则用户不知道卡在哪一步
        assert "记忆" in detail, f"{method} {path} 的 401 文案没点明功能：{detail!r}"


# ============================================================ D 归属不出参


async def test_memory_responses_never_expose_owner_id(client, user):
    """任何响应体里都不得出现 `owner_id`。

    ★ 为什么这条值得钉：`owner_id` 是**服务端判据**。它出现在出参里没有任何
      收益（前端不需要它），却给了"客户端拿别人的 id 去拼请求"一个顺手的机会
      —— 而本模块的请求体里也刻意没有这个字段（`router.py` 的 docstring）。
      进不出、出不进，两边都不出现，才叫"归属只由服务端注入"。
    """
    headers = {"Authorization": f"Bearer {user['token']}"}
    owner = user["user_id"]

    def _keys(node) -> set:
        found: set = set()
        if isinstance(node, dict):
            for k, v in node.items():
                found.add(str(k))
                found |= _keys(v)
        elif isinstance(node, list):
            for v in node:
                found |= _keys(v)
        return found

    try:
        bodies = {}
        bodies["GET /memory"] = (
            await client.get("/api/v1/memory", headers=headers)
        ).json()
        bodies["PUT /memory"] = (
            await client.put(
                "/api/v1/memory",
                headers=headers,
                json={"markdown": SAMPLE_MARKDOWN, "source": "manual"},
            )
        ).json()
        bodies["GET /memory/logs"] = (
            await client.get("/api/v1/memory/logs", headers=headers)
        ).json()
        bodies["POST /memory/distill"] = (
            await client.post("/api/v1/memory/distill", headers=headers)
        ).json()

        for label, body in bodies.items():
            keys = _keys(body)
            assert "owner_id" not in keys, f"{label} 的响应体里出现了 owner_id"
            # 顺带确认响应里真的带上了这个用户的数据（否则上面的断言是空过）
            assert body, f"{label} 返回了空体，本断言失去意义"
    finally:
        await _purge_memory([owner])
