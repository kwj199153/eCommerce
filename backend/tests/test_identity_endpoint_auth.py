"""
身份端点的「鉴权模式无关性」守护（2026-09-16）

★★★ 这条测试钉住的是什么
「团队成员」（`/api/v1/accounts/*`）与「自助资料」（`/api/v1/users/*`）是
**身份与授权数据**：说不清"你是谁"就不该能读，更不该能改。

但旧实现把这条 fail-closed 判定写成了 `require_auth_if_enabled` 的复用，
而后者在 `config.auth_required=False` 时**第一步就 `return None`（连 token
都不解析）**。于是本地演示模式（本地 `.env` 就是 `AUTH_REQUIRED=false`）下：

    带合法 JWT    -> 401    <- 错：这是"功能被焊死"
    带 demo-token -> 401    <- 对（它不是 JWT）
    不带 token    -> 401    <- 对

「演示模式不开放」应当表达为「**没有真身份不放行**」，
而不是「**有真身份也不放行**」。

★ 为什么原有测试没抓到它
`test_account_store_hierarchy.py` 覆盖了归属判定的四条分支与团队共享，
但**没有任何一条 401 断言** —— 那 9 个端点在演示模式下的行为零覆盖。
门禁存在 != 门禁在执行。

★ 前端为什么会呈现为"提示要登录可是没有入口"
后端 401 的文案让人"先去登录"，而登录后**结果完全一样**（还是 401）；
同时前端 `request.ts` 对 demo-token 的 401 静默处理，连失败都没落到
任何登录入口上。后端这条口径修正后，前端才有"登录了真能用"这个前提。
"""

# ====== 账户端点（accounts_router -> require_authenticated_user）======


async def test_accounts_accepts_valid_token_in_demo_mode(auth_off, client, make_user):
    """
    ★★★ 核心门禁：演示模式下，**合法 token 必须被认**。

    反向注入验证：把 `require_authenticated_user` 改回复用
    `require_auth_if_enabled`（即旧实现），本条必须转红。
    """
    u = await make_user("demo-ok")
    r = await client.get("/api/v1/accounts", headers=u["headers"])

    assert r.status_code == 200, (
        f"演示模式下合法 token 被拒（{r.status_code}）—— 身份功能被焊死。"
        f" 响应={r.text[:300]}"
    )
    body = r.json()
    assert isinstance(body.get("accounts"), list)
    # 项目契约：列表端点一律 {"<集合名>": [...], "total": n}
    assert body.get("total") == len(body["accounts"])


async def test_accounts_rejects_anonymous_in_demo_mode(auth_off, client):
    """
    演示模式**不代表**身份数据可以匿名读 —— fail-closed 的方向不能丢。
    """
    r = await client.get("/api/v1/accounts")

    assert r.status_code == 401
    detail = r.json()["detail"]
    # 文案要给出**可执行**的指引
    assert "登录" in detail
    # 但不能把后端环境变量名抛给终端用户：那是实现细节，
    # 用户既看不懂、也改不了（旧文案正是这么写的）。
    assert "AUTH_REQUIRED" not in detail, "401 文案不该暴露后端环境变量名"


async def test_accounts_rejects_demo_token(auth_off, client):
    """
    前端演示模式会往 localStorage 写 `access_token='demo-token'` 并照常发出去。
    它不是 JWT => 必须 401，**绝不能**被当成身份。
    """
    r = await client.get(
        "/api/v1/accounts", headers={"Authorization": "Bearer demo-token"}
    )
    assert r.status_code == 401


async def test_identity_endpoint_is_auth_mode_agnostic(client, make_user):
    """
    ★★★ 本文件的一句话总结：**同一枚合法 token，在两种鉴权模式下都必须能访问**。

    身份判定不该受 `config.auth_required`（那是"业务数据要不要设限"的开关）
    影响。这两个概念混在一起，就是"登录了也打不开"的成因。

    比 `auth_on` / `auth_off` 两个夹具更有说服力：同一条用例、同一枚 token、
    只切换开关，结论必须不变。
    """
    from core.config import config

    u = await make_user("agnostic")
    prev = config.auth_required
    try:
        for mode in (False, True):
            config.auth_required = mode
            r = await client.get("/api/v1/accounts", headers=u["headers"])
            assert r.status_code == 200, (
                f"auth_required={mode} 时合法 token 被拒（{r.status_code}）—— "
                f"身份判定被环境开关绑架了。响应={r.text[:300]}"
            )
    finally:
        config.auth_required = prev


# ====== 自助资料端点（users_router -> get_current_user）======


async def test_users_endpoint_accepts_valid_token_in_demo_mode(auth_off, client, make_user):
    """
    `/users/*` 与 `/accounts/*` 必须**同一条口径**：两边都 fail-closed，
    但都只 fail 在"没有有效身份"，不 fail 在"环境开关关着"。

    这两处此前用的是两个不同的依赖（`get_current_user` vs
    `require_authenticated_user`），行为却曾**相反** ——
    正是"同一判定两份实现"的代价。本条把它们钉在一起。
    """
    u = await make_user("users-ok")
    r = await client.get("/api/v1/users/api-keys", headers=u["headers"])

    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert r.json()["total"] == 0


async def test_users_endpoint_rejects_anonymous_in_demo_mode(auth_off, client):
    r = await client.get("/api/v1/users/api-keys")
    assert r.status_code == 401


# ====== 形态门禁 ======


def test_require_authenticated_user_does_not_delegate_to_switch():
    """
    ★ 形态门禁：`require_authenticated_user` **不得**再复用
      `require_auth_if_enabled`，也不得读 `config.auth_required`。

    为什么用**源码**断言而不是行为断言：改回旧实现以后，行为断言只在
    `auth_required=False` 时才红 —— 若测试进程恰好开着鉴权就一路绿。
    本门禁在**任何模式下**都立刻报警。

    ★ 必须**先剥掉 docstring 与注释**再匹配：本函数的说明里确实提到了
      那几个名字（讲分工），直接 `in` 会被文字骗过。
    """
    import inspect

    from core.auth.dependencies import require_authenticated_user

    src = inspect.getsource(require_authenticated_user)

    # 1) 剥 docstring：按三引号切分，只留 docstring 之后的**可执行代码**
    parts = src.split('"""')
    assert len(parts) >= 3, "函数结构异常：没有找到 docstring"
    after_doc = '"""'.join(parts[2:])

    # 2) 剥行注释（注释里解释"为什么不用某个函数"是正当的，不该触发门禁）
    code = "\n".join(
        ln for ln in after_doc.splitlines() if not ln.strip().startswith("#")
    )

    assert "require_auth_if_enabled" not in code, (
        "require_authenticated_user 又退回了开关式实现 —— "
        "演示模式（AUTH_REQUIRED=false）下合法 token 会被拒，身份功能被焊死。"
    )
    assert "auth_required" not in code, (
        "身份判定不该读 config.auth_required —— 那是业务数据的开关，"
        "与'你是谁'无关。"
    )
