# -*- coding: utf-8 -*-
"""r389 · AI 原生契约门禁（A1 / A3 / A5）。

背景：运维把 `/openapi.json` 对外开放之后，外部 Agent（或 OpenAPI codegen、
MCP 客户端）只能靠这份说明书工作。说明书错一个字符串、少一条 security 声明，
对方的失败形态是「404」「每次都得先调一次试 401」，而**我们这边一切正常**。

四条不变式，每条都对应一次实测到的缺陷：

A1  `tokenUrl` 必须是真实可调用的登录路径。
    历史：写成 `/api/auth/login`（真路径 `/api/v1/auth/login`）⇒ 照 schema 调 404，
    且 404 会被误判成「没有登录接口」。一个字符串的事，卡住所有标准客户端第一步。

A3  需要身份的操作必须在 openapi 里**声明** security。
    历史：鉴权是靠 `dependencies=[Depends(...)]` 挂的，而这些依赖**手动从
    request.headers 读 Authorization** ⇒ FastAPI 的 openapi 生成器看不见
    ⇒ 291 个 op 里 266 个（91%）`security=None`。
    修法不是给端点补鉴权（那是几天且必然改出 bug），而是给依赖加一个
    **只读的** `_scheme: Optional[str] = Depends(oauth2_scheme_optional)`
    ⇒ 行为零变化，声明出现。修完 266 -> 26。

A3b `oauth2_scheme_optional` 必须 `auto_error=False`。
    默认 True 时，缺 Authorization 头会在**依赖解析阶段**直接 401，
    破坏 `require_auth_if_enabled` 的 optional auth 语义（本地演示模式整片 401）。
    运维侧踩过同类事故。

A3c 这几个依赖的**位置参数顺序**必须是 `(request, db, ...)`。
    ★ 这条是给自己立碑：我第一版把 `_scheme` 插在 `request` 与 `db` 之间，
    而 `require_auth_if_enabled(request, db)` 有 4 处位置调用
    （usage_tracker ×3、tenant/middleware ×1）⇒ AsyncSession 被当成 _scheme 吃掉，
    db 退回 `Depends(get_db)` 标记对象 ⇒ 运行期 500。
    而 import / openapi() / 绝大多数单测**全都看不出来**。

A5  顶层 `openapi_tags` 必须定义，且覆盖全部 op 级 tag。
    历史：31 个中文 tag 只散落在 operation 上，顶层为空 ⇒ 外部 Agent 看不到
    「这个系统有哪几块能力」这一层。
"""

from __future__ import annotations

import inspect

import pytest

# ---------------------------------------------------------------- 常量

#: A1 期望的登录路径（OpenAPI 叫 tokenUrl，实际是「拿 token 的端点」）
EXPECTED_TOKEN_URL = "/api/v1/auth/login"

#: A3 允许「无 security 声明」的端点 —— **精确集合**，不是通配。
#: 为什么精确：新增一个公开端点必须是**有意识的决定**（登录、注册、健康检查、
#: 支付回调、OAuth 回调）。用 `/api/v1/auth/*` 通配会把将来误加的
#: `/api/v1/auth/change-password` 一起放行，而这正是最该拦的那个。
#: 这条会带来「加端点就得改测试」的摩擦 —— 故意如此。
PUBLIC_OPS = {
    ("GET", "/health"),
    # 认证入口本身
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/device/switch"),
    # 套餐列表：登录前就要能看定价
    ("GET", "/api/v1/billing/plans"),
    # 第三方回调：签名/验签是它们自己的鉴权方式，不是 Bearer
    ("POST", "/api/v1/billing/webhook/alipay"),
    ("GET", "/api/v1/amazon-sp/oauth/callback"),
}

#: 这些依赖必须有 `_scheme` 参数（让 openapi 看得见）+ 保持 `(request, db)` 位置语义
SCHEME_DEPS = (
    "require_auth_if_enabled",
    "require_authenticated_user",
    "get_acting_user",
    "require_acting_user",
)


@pytest.fixture(scope="module")
def spec():
    """整模块只生成一次 openapi（import main 约 10 秒）。"""
    import os
    import sys

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    cwd = os.getcwd()
    os.chdir(backend)  # config 用相对 CWD 读 .env
    try:
        import main as main_mod

        return main_mod.app.openapi()
    finally:
        os.chdir(cwd)


def _ops(spec):
    out = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method.lower() in ("get", "post", "put", "patch", "delete", "head", "options"):
                if isinstance(op, dict):
                    out.append((method.upper(), path, op))
    return out


# ------------------------------------------------------------------- A1
def test_a1_token_url_points_to_a_real_endpoint(spec):
    """securitySchemes 里的 tokenUrl 必须能在 paths 里找到，且是 POST。"""
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    assert schemes, "components.securitySchemes 为空 ⇒ 客户端不知道 token 从哪来"

    token_urls = []
    for name, sch in schemes.items():
        for flow_name, flow in ((sch.get("flows") or {}) or {}).items():
            url = (flow or {}).get("tokenUrl")
            if url:
                token_urls.append((name, flow_name, url))
    assert token_urls, (
        "没有任何 flow 声明 tokenUrl（只有 HTTPBearer 时就是这样：\n"
        "它只说「带一个 Bearer」，没说「token 从哪来」）")

    for name, flow_name, url in token_urls:
        assert url == EXPECTED_TOKEN_URL, (
            "%s.%s.tokenUrl = %r，期望 %r\n"
            "⇒ 照 schema 调会 404，而 404 会被误判成「没有登录接口」"
            % (name, flow_name, url, EXPECTED_TOKEN_URL))
        assert url in spec["paths"], (
            "tokenUrl %r 不在 paths 里 ⇒ 说明书自己指了一个不存在的端点" % url)
        methods = {m.upper() for m in spec["paths"][url]}
        assert "POST" in methods, "tokenUrl 端点没有 POST，OAuth2 password flow 走不通"


# ------------------------------------------------------------------- A3
def test_a3_only_whitelisted_ops_lack_security(spec):
    """需要身份的操作必须声明 security；无声明的端点必须逐个登记。"""
    ops = _ops(spec)
    assert len(ops) > 250, "只扫到 %d 个 op，判据可能没扫到" % len(ops)

    undeclared = {(m, p) for m, p, op in ops if op.get("security") is None}
    extra = undeclared - PUBLIC_OPS
    assert not extra, (
        "这些端点没有 security 声明，也不在公开白名单里：\n  %s\n"
        "⇒ 外部 Agent 无法从说明书判断它们要身份（只能先调一次看 401）；\n"
        "   若它们确实该公开，请显式加进 PUBLIC_OPS 并写明理由。"
        % "\n  ".join("%s %s" % x for x in sorted(extra)))

    # 反向：白名单里登记的端点，必须真的存在（防止白名单腐烂）
    all_pairs = {(m, p) for m, p, _ in ops}
    stale = PUBLIC_OPS - all_pairs
    assert not stale, "公开白名单里有已不存在的端点（清单腐烂）：%s" % sorted(stale)


def test_a3_security_coverage_does_not_regress(spec):
    """覆盖率下限：无声明比例 <= 15%（修前 91%，修后 9%）。"""
    ops = _ops(spec)
    undeclared = sum(1 for _, _, op in ops if op.get("security") is None)
    ratio = undeclared / max(len(ops), 1)
    assert ratio <= 0.15, (
        "无 security 声明的 op 占 %.0f%%（%d/%d），超过 15%% 上限。\n"
        "⇒ 多半是新加的 router 用了「手动读 header」的依赖，或直接没挂鉴权。"
        % (ratio * 100, undeclared, len(ops)))


# ------------------------------------------------------------------ A3b
def test_a3b_optional_scheme_never_raises_on_missing_header():
    """auto_error 必须是 False，否则本地演示模式会整片 401。"""
    import os
    import sys

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    cwd = os.getcwd()
    os.chdir(backend)
    try:
        from core.auth.dependencies import oauth2_scheme, oauth2_scheme_optional

        assert oauth2_scheme_optional.auto_error is False, (
            "oauth2_scheme_optional.auto_error 必须为 False\n"
            "⇒ 为 True 时缺 Authorization 头会在依赖解析阶段直接 401，\n"
            "   破坏 require_auth_if_enabled 的 optional auth 语义")
        assert oauth2_scheme.auto_error is True, (
            "oauth2_scheme（强制版）应保持 auto_error=True —— 两者刻意不同")
        assert oauth2_scheme_optional.scheme_name == oauth2_scheme.scheme_name, (
            "两个 scheme 的 scheme_name 必须一致，否则 openapi 里会出现两条 securityScheme")
        # tokenUrl 的正确性由 A1 从 spec 上校验；OAuth2PasswordBearer 对象上没有 .flows 属性
    finally:
        os.chdir(cwd)


# ------------------------------------------------------------------ A3c
def test_a3c_dependency_positional_signature_is_stable():
    """★ 位置参数顺序必须是 (request, db)：`_scheme` 只能加在末尾或 keyword-only。

    这条是给一次真实事故立的碑：把 `_scheme` 插在 request 与 db 之间后，
    `require_auth_if_enabled(request, db)` 的 4 处位置调用
    （usage_tracker ×3、tenant/middleware ×1）把 AsyncSession 喂给了 _scheme，
    而 db 退回 `Depends(get_db)` 标记对象 ⇒ 运行期 500，
    但 import / openapi() / 单测全绿。
    """
    import os
    import sys

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    cwd = os.getcwd()
    os.chdir(backend)
    try:
        import core.auth.dependencies as deps
    finally:
        os.chdir(cwd)

    for name in SCHEME_DEPS:
        fn = getattr(deps, name, None)
        assert fn is not None, "core.auth.dependencies 里找不到 %s" % name
        params = list(inspect.signature(fn).parameters.values())[:2]
        assert [p.name for p in params] == ["request", "db"], (
            "%s 的前两个位置参数是 %r，必须是 ['request', 'db']\n"
            "⇒ 有直接调用点按位置传 (request, db)，顺序一变就会把 db 喂给别的参数"
            % (name, [p.name for p in params]))
        # 且必须带 _scheme（否则 openapi 又看不见 security）
        all_names = list(inspect.signature(fn).parameters)
        assert "_scheme" in all_names, (
            "%s 缺少 _scheme 参数 ⇒ 挂它的路由在 openapi 里又会变成 security=None" % name)


# ------------------------------------------------------------------- A5
def test_a5_top_level_tags_cover_every_op_tag(spec):
    """顶层 openapi_tags 必须定义，且覆盖所有 op 级 tag（含中文描述）。"""
    top = spec.get("tags") or []
    assert top, "顶层 openapi.tags 为空 ⇒ 外部 Agent 看不到「有哪几块能力」"

    declared = {t.get("name") for t in top}
    for t in top:
        assert t.get("description"), "tag %r 缺 description" % t.get("name")

    used = set()
    for _, _, op in _ops(spec):
        used.update(op.get("tags") or [])
    assert used, "所有 op 都没有 tag ⇒ 判据失效"

    missing = used - declared
    assert not missing, (
        "这些 op 级 tag 没有在顶层 openapi_tags 里登记：%s\n"
        "⇒ 新增带新 tag 的 router 时，请同步 main.py 的 _OPENAPI_TAGS"
        % sorted(missing))
