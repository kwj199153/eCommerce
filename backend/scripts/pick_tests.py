#!/usr/bin/env python
"""
按改动范围自动选出「该跑哪些测试」——把「不要每次都跑全量」变成可执行动作。

用法（在 backend/ 下）：
    python scripts/pick_tests.py                       # 用 git 工作区改动自动映射
    python scripts/pick_tests.py --staged              # 只看已 git add 的
    python scripts/pick_tests.py --base HEAD~1         # 看相对某次提交的改动（推荐：本轮改了什么）
    python scripts/pick_tests.py --paths               # 只列出本次改动的文件清单（自检）
    python scripts/pick_tests.py backend/modules/secretary/shop_tools.py
    python scripts/pick_tests.py --run                 # 选出并直接执行
    python scripts/pick_tests.py --explain             # 打印每条映射的依据

⚠️ 工作区可能有大量跨轮次未提交的改动（实测曾达 177 个文件）。
   这时「工作区全量」会始终判成全量、失去意义。
   日常请用 `--base HEAD`（= 只看相对上次提交的增量），或在改完一批后先 commit。

设计原则（对应 MEMORY.md 的「测试分级」）：
  1. **改动 → 测试** 的映射基于**目录/模块名同构**，不猜语义；
  2. 命中「契约/基础设施」层（ai_infra / core / main / models / 中间件 / conftest）
     ⇒ **升级为全量**（这类改动的影响面无法靠命名推断）；
  3. 前端改动 ⇒ 不走 pytest，改跑 `vue-tsc` + 主题/自检脚本；
  4. 拿不准就要求全量 —— **漏跑的代价远大于多跑 1 分钟**。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TESTS = BACKEND / "tests"

# Windows 控制台默认 GBK → 中文输出乱码，强制 UTF-8（实测必须）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


# 命中即「升级为全量」的路径特征：契约层 / 基础设施 / 跨模块
FULL_RUN_TRIGGERS = [
    "backend/main.py",
    "backend/core/",
    "backend/ai_infra/",
    "backend/models/",
    "backend/core/billing/",
    "backend/tests/conftest.py",
    "backend/pytest.ini",
    "backend/alembic/",
]

# 模块 → 测试文件的显式补丁表（命名对不上时在此登记）
EXTRA_MAP = {
    "backend/modules/secretary": ["test_secretary_agent.py", "test_secretary_intent_shortcut.py"],
    "backend/modules/product_research": [
        "test_product_research_candidate_flow.py",
        "test_product_research_blue_ocean.py",
        "test_product_research_intent_routing.py",
    ],
    "backend/modules/user_subscription": ["test_billing_endpoints.py", "test_billing_metering.py"],
    "backend/modules/stores": ["test_stores.py", "test_seed_shop_ids.py"],
    "backend/modules/aigc_media": ["test_stream_sse.py"],
    "backend/modules/listing_generator": ["test_stream_sse.py", "test_auth_and_tenant.py"],
    "backend/modules/voice_clone": ["test_voice_clone_isolation.py"],
}

# 前端改动触发的检查（非 pytest）
FRONTEND_CHECKS = [
    "cd frontend && npx vue-tsc --noEmit",          # 类型
    "python frontend/scripts/check_theme_boot.py",   # 主题跨文件一致
    "python frontend/scripts/check_app_actions.py",  # 动作契约
]


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip()


def changed_files(staged: bool, explicit: list[str], base: str | None) -> list[str]:
    if explicit:
        return [_norm(p) for p in explicit]

    def _git(*a: str) -> list[str]:
        r = subprocess.run(["git", *a], capture_output=True, cwd=BACKEND.parent)
        return [_norm(x) for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]

    if base:
        # 相对某次提交的增量：包含已提交与未提交（--diff-filter 去掉删除项）
        files = _git("diff", "--name-only", "--diff-filter=d", base)
        if files:
            return files

    args = ["diff", "--name-only", "--diff-filter=d"]
    if staged:
        args.append("--staged")
    files = _git(*args)
    if not files:
        # 无未提交改动 → 用最近一次提交
        files = _git("show", "--name-only", "--pretty=format:")
    return files


def needs_full_run(files: list[str]) -> tuple[bool, str]:
    for f in files:
        for trig in FULL_RUN_TRIGGERS:
            if f.startswith(trig):
                return True, f"{f} 属于契约/基础设施层（{trig}）"
    return False, ""


def map_to_tests(files: list[str]) -> dict[str, list[str]]:
    """返回 {测试文件名: [触发它的改动文件, ...]}"""
    hits: dict[str, list[str]] = {}

    def add(test: str, src: str):
        hits.setdefault(test, [])
        if src not in hits[test]:
            hits[test].append(src)

    for f in files:
        if not f.startswith("backend/"):
            continue

        # 显式补丁表优先（最长前缀匹配）
        best = None
        for prefix in EXTRA_MAP:
            if f.startswith(prefix) and (best is None or len(prefix) > len(best)):
                best = prefix
        if best:
            for t in EXTRA_MAP[best]:
                add(t, f)
            continue

        # 兜底：模块名 → test_<模块名>.py
        m = re.search(r"backend/modules/([a-z_]+)/", f)
        if m:
            candidate = f"test_{m.group(1)}.py"
            if (TESTS / candidate).exists():
                add(candidate, f)
                continue
            # 该模块没有专属测试 → 保守起见记录为「无对应测试」
            hits.setdefault("__unmapped__", []).append(f)
            continue

        # backend/tests/ 自身的改动 → 只跑被改的那个文件
        mt = re.search(r"backend/tests/(test_[a-z_]+\.py)", f)
        if mt:
            add(mt.group(1), f)

    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="改动的文件（留空则用 git 自动探测）")
    ap.add_argument("--staged", action="store_true", help="只看已 git add 的改动")
    ap.add_argument("--base", metavar="REF", help="相对某次提交的增量，如 --base HEAD / HEAD~1")
    ap.add_argument("--paths", action="store_true", help="只列出改动文件后退出")
    ap.add_argument("--run", action="store_true", help="选出后直接执行")
    ap.add_argument("--explain", action="store_true", help="打印每条映射的依据")
    args = ap.parse_args()

    files = changed_files(args.staged, args.files, args.base)
    if not files:
        print("没有检测到改动。")
        return 0

    if args.paths:
        for f in files:
            print(f)
        return 0

    print(f"检测到 {len(files)} 个改动文件")
    if args.explain and len(files) <= 40:
        for f in files:
            print(f"  - {f}")
    elif args.explain:
        print(f"  （改动过多，省略清单；用 --paths 单独查看）")

    full, why = needs_full_run(files)
    frontend = [f for f in files if f.startswith("frontend/")]

    # 必须用「当前解释器」而不是裸 python：
    # 本机裸 python 指向无 pytest 的环境（实测 No module named pytest）。
    PY = sys.executable

    if full:
        print(f"\n⇒ 判定：**全量**（{why}）")
        print("  契约/基础设施层的影响面无法靠命名推断，必须全量。")
        pytest_args = ""
    else:
        hits = map_to_tests(files)
        tests = sorted(t for t in hits if t != "__unmapped__")

        if not tests:
            print("\n⇒ 判定：**全量**（未命中任何专属测试，保守升级）")
            if hits.get("__unmapped__"):
                print("  以下改动所属模块没有专属测试：")
                for f in hits["__unmapped__"]:
                    print(f"    - {f}")
            print("  ⇒ 无法定位影响面 ⇒ 按全量处理（漏跑的代价远大于多跑 1 分钟）。")
            pytest_args = ""
        else:
            print(f"\n⇒ 判定：**定向** —— {len(tests)} 个测试文件")
            for t in tests:
                via = ", ".join(hits[t][:3])
                more = "" if len(hits[t]) <= 3 else f" 等 {len(hits[t])} 处"
                print(f"  - {t}  ← {via}{more}")
            pytest_args = " ".join(f"tests/{t}" for t in tests)

    cmd = f'"{PY}" -m pytest -q {pytest_args}'.strip()

    if frontend:
        print(f"\n⇒ 前端改动 {len(frontend)} 处，另需跑：")
        for c in FRONTEND_CHECKS:
            print(f"  $ {c}")

    print(f"\n建议命令（在 backend/ 下）：\n  {cmd}")
    if args.run:
        print("\n--- 执行 ---")
        return subprocess.run(
            [PY, "-m", "pytest", "-q", *pytest_args.split()], cwd=BACKEND
        ).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
