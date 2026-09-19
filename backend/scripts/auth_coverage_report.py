"""
鉴权覆盖体检脚本

用途：枚举 FastAPI 应用的全部路由，逐个检查是否挂载了认证/授权依赖，
      输出按模块聚合的覆盖报告，用作多租户改造的验收基线。

原理：递归遍历 route.dependant.dependencies，收集依赖函数名，
      与已知的认证依赖名集合比对（不依赖运行时请求，静态可判定）。

用法（在 backend 目录下执行）：
    python scripts/auth_coverage_report.py
    python scripts/auth_coverage_report.py --show-unauth   # 列出每个未鉴权路由
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict

# 允许以脚本方式直接运行（把 backend 根目录加入 sys.path）
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from main import app  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

# 认定为「认证/授权」的依赖函数名
#
# ★ P1-c（2026-09-16）维护说明：
#   - 删掉 `require_shop_owner` —— 那是**账户侧**（shops 表 / UUID）的
#     权限工厂，已随账户侧实体整体删除。留着一个不存在的名字只会让
#     报告看起来"有一类依赖"，实际永远命中不到。
#   - 加上 `_current_user` —— `core/auth/accounts_router.py` 的
#     fail-closed 身份门（无身份一律 401）。不登记它，整个
#     `/api/v1/accounts` 模块会在报告里显示成"无鉴权"，与事实相反。
#   - 加上 `_REQUIRE_USER` —— `modules/memory/router.py` 的 fail-closed 身份门
#     （★ 第 153 轮）。它此前写成 `functools.partial(require_authenticated_user,
#     what="长期记忆")`，而 **partial 没有 `__name__`** ⇒ 本脚本取到 None
#     ⇒ `/api/v1/memory` 的 6 个端点全被报成 **0% 无鉴权**，与事实完全相反
#     （它一直是 fail-closed 的）。同一批端点当时还 100% 500：
#     `AttributeError: 'coroutine' object has no attribute 'id'`
#     —— 因为 FastAPI 不 await partial 包装过的依赖（见该文件 docstring）。
#     ★ 所以本报告现在多了第 ④ 节，直接点名这种形态，不再只靠名单。
#   ★ 判据：这份清单必须与实际存在的依赖函数名保持一致；
#     名字写错**不会报错**，只会让覆盖率数字静默失真。
AUTH_DEPENDENCY_NAMES = {
    "get_current_user",
    "get_current_active_user",
    "get_current_user_optional",
    "require_auth_if_enabled",
    "require_permissions",
    "require_admin",
    "_current_user",
    "_REQUIRE_USER",
    "get_current_tenant",
}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def collect_dependency_names(dependant, acc=None):
    """递归收集一个 Dependant 树里的所有依赖函数名"""
    if acc is None:
        acc = set()
    for dep in getattr(dependant, "dependencies", []) or []:
        call = getattr(dep, "call", None)
        name = getattr(call, "__name__", None)
        if name:
            acc.add(name)
        collect_dependency_names(dep, acc)
    return acc


def collect_form_anomalies(dependant, acc=None):
    """收集「形态自相矛盾」的依赖：asyncio 说是协程，FastAPI 却**不会** await 它。

    ★ 第 153 轮新增。这一档此前在本报告里**完全不可见**：它既不是"没挂依赖"
      （名单判定会显示已鉴权），也不报错（除非真发一次请求）。
      `modules/memory/router.py` 的 6 个端点因此 100% 500，而本报告当时
      把它们算成 **0% 无鉴权** —— 方向刚好相反（它们其实一直是 fail-closed 的）。

    ★ 为什么必须用 `is_coroutine_callable` 而不是 `asyncio.iscoroutinefunction`：
      后者对 `functools.partial(require_authenticated_user, ...)` 返回 **True**，
      而 FastAPI 判"要不要 await"用的是前者（返回 **False**）。
      两个判定分歧的地方，就是本函数要找的地方。
    """
    from fastapi.dependencies.utils import is_coroutine_callable

    if acc is None:
        acc = []
    for dep in getattr(dependant, "dependencies", []) or []:
        call = getattr(dep, "call", None)
        if (
            call is not None
            and asyncio.iscoroutinefunction(call)
            and not is_coroutine_callable(call)
        ):
            acc.append(call)
        collect_form_anomalies(dep, acc)
    return acc


def module_of(path: str) -> str:
    """从 URL 路径推断所属模块，便于聚合"""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "(root)"
    if parts[0] == "api" and len(parts) > 1:
        # /api/v1/xxx -> xxx
        idx = 2 if len(parts) > 2 else len(parts) - 1
        return parts[idx] if len(parts) > 2 else parts[-1]
    return parts[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-unauth", action="store_true", help="列出所有未鉴权路由明细")
    args = parser.parse_args()

    total = 0
    protected = 0
    per_module = defaultdict(lambda: {"total": 0, "protected": 0})
    unauth_routes = []
    form_anomalies = []  # (methods, path, call)

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(m for m in route.methods if m in HTTP_METHODS)
        if not methods:
            continue

        total += 1
        names = collect_dependency_names(route.dependant)
        is_protected = bool(names & AUTH_DEPENDENCY_NAMES)
        mod = module_of(route.path)

        per_module[mod]["total"] += 1
        if is_protected:
            protected += 1
            per_module[mod]["protected"] += 1
        else:
            unauth_routes.append((mod, ",".join(methods), route.path))
        for _call in collect_form_anomalies(route.dependant):
            form_anomalies.append((",".join(methods), route.path, _call))

    print("=" * 68)
    print("鉴权覆盖体检报告")
    print("=" * 68)
    from core.config import config
    mode = "生产模式（业务接口强制 Bearer Token）" if config.auth_required else "演示模式（业务接口放行，无鉴权）"
    print(f"当前模式: AUTH_REQUIRED={config.auth_required}  -> {mode}")
    print("-" * 68)
    print(f"总端点数: {total}    已鉴权: {protected}    未鉴权: {total - protected}")
    if total:
        print(f"覆盖率: {protected / total * 100:.1f}%")
    print()
    print(f"{'模块':<24}{'端点':>6}{'已鉴权':>8}{'覆盖率':>10}")
    print("-" * 68)
    for mod, stat in sorted(per_module.items(), key=lambda kv: kv[1]["total"], reverse=True):
        cov = stat["protected"] / stat["total"] * 100 if stat["total"] else 0
        flag = "" if cov >= 100 else ("  <-- 无鉴权" if cov == 0 else "  <-- 部分覆盖")
        print(f"{mod:<24}{stat['total']:>6}{stat['protected']:>8}{cov:>9.0f}%{flag}")

    # ④ 依赖形态（★ 第 153 轮）：见 collect_form_anomalies 的 docstring。
    #    这一档的症状是 **500** 而不是 401 —— 名单覆盖率 100% 也照样中招。
    print()
    print("依赖形态（asyncio 说是协程、而 FastAPI 不会 await 的依赖）:")
    print("-" * 68)
    if form_anomalies:
        for _m, _p, _c in form_anomalies:
            print(f"  [BAD] {_m:<12} {_p}  {_c!r}")
        print(f"  ==> {len(form_anomalies)} 处：这些端点在真实请求下会 500"
              "（handler 拿到的是协程对象，不是依赖的返回值）")
    else:
        print("  （无 —— 全应用没有 partial 包装 async 依赖这一形态）")

    if args.show_unauth and unauth_routes:
        print()
        print("未鉴权路由明细:")
        print("-" * 68)
        for mod, methods, path in unauth_routes:
            print(f"  [{mod:<18}] {methods:<18} {path}")

    # 出口码：存在未鉴权端点或依赖形态异常时返回 1，便于接 CI
    return 1 if (protected < total or form_anomalies) else 0


if __name__ == "__main__":
    sys.exit(main())
