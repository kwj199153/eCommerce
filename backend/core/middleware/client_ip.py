"""
客户端 IP 提取 —— 中间件层**唯一**实现

★ 修复前的重复（第 94 轮「横切关注点三层安放」审计实测）

    `core/middleware/request_log.py::RequestLogMiddleware._client_ip`
    与 `core/middleware/rate_limit.py::RateLimitMiddleware._client_key`
    是同一段逻辑的拷贝（都是「X-Forwarded-For 首跳 → 回落 request.client」），
    只有取不到时的占位符不同（`"-"` vs `"unknown"`）。

    ★ 审计修正（2026-09-16 做 P0-2 时补 grep 才发现）：**实际是 4 份**，
      不是审计时认定的 2 份 —— 另外两份在 core/identity/ 下：

        core/identity/router.py::_client_ip         （登录时记录来源 IP）
        core/identity/security_router.py::_client_ip（重置密码申请时记录来源 IP）

      后两者的注释里**自己写着**"与 rate_limit.py 同一套逻辑" —— 也就是说
      它们知道自己是第四份拷贝，只是没人负责收敛。这就是"横切能力必须收敛到
      独立 Service"的现实形态：不是有人故意抄，而是**每次新增用途时就地写一份
      更省事**，而每一次都很合理。

    多份各自演进时会出现这种情况：**同一条请求**，访问日志里记的客户端 IP、
    限流计数用的 key、以及安全审计里记录的来源 IP 指向不同来源 ——
    排查「为什么这个 IP 被限流了」时，三处证据互相矛盾，而代码看起来毫无问题。

★ 为什么占位符由调用方决定（这里返回 `None` 而不是某个默认值）

    `None` 表示"拿不到"，是**事实**；用 `"-"` 还是 `"unknown"` 是**用途决定的**
    （日志列里 `-` 是惯例；限流 key 里需要一个稳定可拼字符串的 token）。
    把占位符也收进来，等于强行让两种用途共享一个值 —— 那不是收敛，
    那是把两件事绑死。

⚠️ 安全前提（与 rate_limit.py 既有说明一致，别丢）

    `X-Forwarded-For` 只在**前置代理可信**时可靠：反向代理（Nginx）后
    `request.client.host` 是代理 IP，所以优先取首跳。但若服务**直接暴露公网
    且未经代理**，该头部可由客户端任意伪造。部署时须确保代理层**覆盖**
    （而不是追加）该头部。
"""

from typing import Optional

from fastapi import Request


def client_ip(request: Optional[Request]) -> Optional[str]:
    """
    取客户端 IP：优先 `X-Forwarded-For` 首跳，回落 `request.client.host`。

    ★ 形参接受 `Optional[Request]`：`core/identity/` 下的两个调用方在部分路径上
      拿到的可能是 `None`（它们原先的本地实现签名本就是可选的）。
      "没有请求" 与 "有请求但取不到 IP" 对调用方是一回事（决定占位符即可），
      所以统一返回 `None`，不在这里区分 —— 区分只会让每个调用方多写一个分支。

    Returns:
        IP 字符串；取不到时返回 `None`（占位符由调用方决定，见模块 docstring）。
    """
    if request is None:
        return None

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or None
