# -*- coding: utf-8 -*-
"""内部**只读**调用：把一次能力调用真正打到自己的端点上。

## 为什么走 ASGI 进程内 HTTP，而不是直接调端点函数

端点函数带一堆 `Depends`（鉴权、租户解析、额度、DB 会话）。手写一遍
「怎么把这些依赖补齐」= 第二份实现，而且它与真实请求路径的差异
（少了哪个守卫、多了哪个放行）**不会报错**，只会在某个租户上读错数据。
走 `httpx.ASGITransport` 是把请求**真的**跑一遍同一条依赖链 ——
守卫、归属、配额全部原样生效。

## 身份从哪来

`core/observability/context.py::current_forward_headers()`：中间件在请求入口
记下白名单内的三个头（`authorization` / `x-shop-id` / `x-request-id`）。
本模块把它们原样带上 —— 于是"能力层能读到什么"与"这个人自己能读到什么"
是**同一个集合**，不多不少。

★ 缺身份一律**本地拦下**（`sent: false`），不发请求：
  * 没有 `authorization` ⇒ 内部调用会变成匿名，读到的不是他的数据；
  * 没有 `x-shop-id` ⇒ 本仓数据作用域只有一层，缺了它读端点拿不到店铺
    上下文（要么空、要么跨店铺 —— 两种都不能接受）。

## `sent` 语义（对标 eEducation 的同名设计）

    sent=false, ok=false  → **本地**拦下（缺身份 / 参数不认识 / 路径被拒）
    sent=true,  ok=false  → 请求发出去了，服务端拒绝（401/403/404/422…）

模型据此决定下一步：前者要**修参数或换能力**，后者要**先判断权限**。
合成一个"失败"会让它反复重试同一个注定失败的调用。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from core.logger import get_logger
from core.observability.context import current_forward_headers

from .registry import app_of, get_capability
from .spec import Capability

__all__ = ["call_read", "MAX_PAYLOAD_CHARS"]

logger = get_logger("capability.invoke")

#: 单次读返回的字符上限（超出就截断并**明确告知**）。
#: ★ 为什么要截：一个列表端点可以吐几百条记录，直接塞进 tool result 会把
#:   模型的上下文一次性吃光（本仓实测过 239k 的会话）。截断而不是报错 ——
#:   模型看得见前 N 条与"还有更多"，可以自己收窄参数再读。
MAX_PAYLOAD_CHARS = 8000

#: 内部调用的超时（秒）。读端点应当很快；慢到 15s 的多半是聚合查询，
#: 再等下去只是拖住整轮对话。
TIMEOUT_S = 15.0


def _fail(error: str, **extra: Any) -> Dict[str, Any]:
    """本地拦下（**没有发出请求**）。"""
    return {"sent": False, "ok": False, "error": error, **extra}


def _resolve_params(
    cap: Capability, params: Dict[str, Any]
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """把入参切成 (路径, query, 错误)。路径参数做 `quote(..., safe="")`。

    ★ `safe=""` 是必须的：值里出现 `/` `?` `#` 时会**改掉最终路径**
      （本项目在别的链路上踩过同族问题）。`BLOCKED_PREFIXES` 判的是**模板**，
      拼完之后打到哪个路径它管不着。
    """
    path = cap.path
    query: Dict[str, Any] = {}
    unknown = []
    by_name = {p.name: p for p in cap.params}

    for k, v in (params or {}).items():
        info = by_name.get(k)
        if info is None:
            unknown.append(k)
            continue
        if info.location == "path":
            raw = str(v)
            # ★★ 路径参数里出现分隔符，**转义也救不回来**：
            #   实测 `a%2Fb` 打到 Starlette 会在路由匹配前被解码回 `a/b`，
            #   于是路径被切成两段 ⇒ 404（而调用方以为"参数就是带斜杠的值"）。
            #   这属于**无法表达**的请求，只能本地拒 —— 让它 404 才是最坏的结果：
            #   模型会以为"这个能力不存在"，去换别的能力，而真正的问题是参数形状。
            if any(ch in raw for ch in ("/", "\\", "?", "#")):
                return path, query, {
                    "error": "path_param_has_separator",
                    "param": k,
                    "hint": "路径参数不能含 / \\ ? #（会被路径解析吃掉）；请改用支持过滤的 query 参数",
                }
            path = path.replace("{" + k + "}", quote(raw, safe=""))
        elif info.location == "query":
            query[k] = v
        elif info.location == "header":
            # 直接改请求头 = 身份/租户的旁路，A 档不做（B 档再议，且要过审批）
            unknown.append(k)
        else:
            unknown.append(k)

    if unknown:
        return path, query, {
            "error": "unrecognized_params",
            "unknown": sorted(unknown),
            "allowed": sorted(by_name),
        }
    if "{" in path:
        # 模板里还有占位符 ⇒ 必填路径参数没给（发出去必然 404/422）
        missing = [p.name for p in cap.params if p.location == "path" and "{" + p.name + "}" in path]
        return path, query, {"error": "missing_path_params", "missing": missing}
    return path, query, None


async def call_read(name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行一次只读能力调用（`name` = operationId）。"""
    cap = get_capability(name)
    if cap is None:
        return _fail(
            "unknown_capability",
            name=name,
            hint="先用 find_capabilities 找名字；名字是 OpenAPI 的 operationId",
        )

    app = app_of()
    if app is None:
        return _fail("capability_unavailable", hint="能力层未绑定应用（启动期 bind_app 未执行）")

    headers = current_forward_headers()
    if not headers.get("authorization"):
        return _fail(
            "no_identity",
            hint="当前调用没有可转发的登录身份 —— 能力层不能以匿名身份读你的数据",
        )
    if not headers.get("x-shop-id"):
        return _fail(
            "no_shop",
            hint="当前没有选中的店铺（缺 X-Shop-ID），读端点拿不到店铺上下文",
        )

    path, query, err = _resolve_params(cap, params or {})
    if err is not None:
        return _fail(**err)

    # 延迟 import：`httpx` 只在真的调用时才需要（启动期少一个依赖加载）
    import httpx

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://capability.local", timeout=TIMEOUT_S
        ) as client:
            resp = await client.get(path, params=query, headers=headers)
    except Exception as e:  # noqa: BLE001 —— 传输层异常不该让整轮对话崩
        logger.warning(f"[capability] {name} 内部调用失败: {type(e).__name__}: {e}")
        return {"sent": True, "ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"[:200]}

    body: Any
    raw = resp.text or ""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = raw[:MAX_PAYLOAD_CHARS]

    # ★ 只判状态码不够：本仓有"伪成功"先例（200 + `success:true` + `data.error`）。
    #   这里不做业务判定（那是各端点自己的契约），但把状态码原样交给模型。
    ok = 200 <= resp.status_code < 300

    text = json.dumps(body, ensure_ascii=False, default=str) if not isinstance(body, str) else body
    truncated = len(text) > MAX_PAYLOAD_CHARS
    if truncated:
        text = text[:MAX_PAYLOAD_CHARS]

    out: Dict[str, Any] = {
        "sent": True,
        "ok": ok,
        "status": resp.status_code,
        "data": text,
    }
    if truncated:
        out["truncated"] = True
        out["hint"] = (
            f"结果超过 {MAX_PAYLOAD_CHARS} 字符已截断 —— 用更具体的查询参数缩小范围，"
            "不要直接把这个片段当完整数据"
        )
    if not ok:
        # 服务端拒绝：把它的 detail 顶到 `error` 上（模型最需要看的就是这句）
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("message") or "")[:300]
        out["error"] = detail or f"HTTP {resp.status_code}"
    return out
