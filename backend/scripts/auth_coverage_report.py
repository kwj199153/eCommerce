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
AUTH_DEPENDENCY_NAMES = {
    "get_current_user",
    "get_current_active_user",
    "get_current_user_optional",
    "require_auth_if_enabled",
    "require_permissions",
    "require_admin",
    "require_shop_owner",
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

    if args.show_unauth and unauth_routes:
        print()
        print("未鉴权路由明细:")
        print("-" * 68)
        for mod, methods, path in unauth_routes:
            print(f"  [{mod:<18}] {methods:<18} {path}")

    # 出口码：存在未鉴权端点时返回 1，便于接 CI
    return 1 if protected < total else 0


if __name__ == "__main__":
    sys.exit(main())
