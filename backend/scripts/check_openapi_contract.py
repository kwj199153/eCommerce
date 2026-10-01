#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：OpenAPI 契约快照（第 353 轮 · L3-5）。

为什么需要它
------------
前端与第三方按 `/openapi.json` 接 API。此前仓库里**没有任何契约快照**
（`docs/openapi*` 与全仓 `openapi*.json` 命中 0）⇒ 后端把一个响应字段改名、
把 `Optional[X]` 收成 `X`、或删掉一条端点，**没有任何流程会看见**。
破坏面全在下游（前端拿到 `undefined`、第三方签名校验失败），
而本仓的 pytest 照样全绿。

本门禁做的事：把 `app.openapi()` 的**规范化 JSON** 落成快照提交进仓库，
每次跑测试时重新生成并逐字节比对；不一致 ⇒ 退出码 1 + 逐项漂移清单。

★ 快照文件本身就是交付物
  前端 / 第三方要接 API，直接读 `backend/docs/api/openapi.json` 即可，
  不必起服务。所以它是**完整规格**，不是哈希、也不是路径清单。

★ 环境固定（顺序不可换）
  `core/config.py` 在 **import 时**实例化 Settings ⇒ 环境变量必须在
  `import main` **之前**写进 `os.environ`。本模块在文件顶部就做掉这件事。

  ★★ 为什么必须固定：CI 没有 `.env`（被 gitignore），本地有。若不固定，
     同一份代码在两处会导出**不同**的契约，门禁就退化成
     「一处恒绿、另一处恒红」的噪音。实测：本地 `.env` 里
     `VOICE_CLONE_ENABLED=true` ⇒ 236 条路径；落到默认值 ⇒ 228 条。

★ 契约的环境敏感轴：实测只有**一根**（下表是本轮实测结果，不是推测）
  ┌──────────────────────┬─────────────────────────┬──────────────────────────┐
  │ env                  │ 对契约的影响             │ 处置                      │
  ├──────────────────────┼─────────────────────────┼──────────────────────────┤
  │ VOICE_CLONE_ENABLED  │ **有**：off 少 8 条      │ 固定 true ⇒ 快照取        │
  │                      │ /api/v1/voice-clone 路径 │ **最大面**；差的这一面由  │
  │                      │ 与 5 个 schema           │ `--env-axes` 单独钉住     │
  │ AUTH_REQUIRED        │ 无                       │ 固定，并由 `--env-axes`   │
  │                      │                          │ 钉住（条件挂载回归即红）  │
  │ DEBUG                │ 无                       │ 只影响 /docs /redoc 挂不挂 │
  │                      │                          │ ——二者不在 schema 里      │
  │ APP_NAME             │ **有**：`info.title`     │ 固定（第 354 轮补 —— 无   │
  │                      │                          │ `.env` 的 CI 上会变）     │
  │ APP_VERSION          │ **有**：`info.version`   │ 固定（同上）              │
  │ METRICS_ENABLED      │ 无                       │ /metrics 是               │
  │                      │                          │ include_in_schema=False   │
  │                      │                          │ （main.py）⇒ 天然不入册   │
  │ DEMO_MODE            │ 无                       │ 演示是**请求期**行为      │
  │ ENVIRONMENT          │ **测不了**               │ production 下 import 会被 │
  │                      │                          │ `_enforce_production_     │
  │                      │                          │ safety` 拦下（缺          │
  │                      │                          │ METRICS_TOKEN 即拒启）    │
  │                      │                          │ ⇒ 本门禁固定 development  │
  └──────────────────────┴─────────────────────────┴──────────────────────────┘

★ `--env-axes` 为什么必需（不是"顺手多测一下"）
  上表「无影响」那三行如果**将来不再成立**，固定环境会让它**永久隐身**：
  例如有人再加一个 `if config.X: include_router(...)`，那么生产真实提供的
  契约与快照不同，而门禁全绿。本仓此前正是这个缺陷形态
  （`BUSINESS_AUTH = [Depends(...)] if config.auth_required else []`，
  2026-09-17 改为无条件挂载）。所以 `--env-axes` 用**子进程**把
  AUTH_REQUIRED 与 VOICE_CLONE_ENABLED 各翻一次，断言：
    · 前者 ⇒ 逐字节不变；
    · 后者 ⇒ 差集**恰好**是 voice-clone 前缀下的路径（且差集非空，
      否则 voice-clone 被整个删掉时这条会「差集为空 ⇒ 恒真」地假绿）。

用法：
    cd backend
    python scripts/check_openapi_contract.py             # 校验（pytest 包装用的就是它）
    python scripts/check_openapi_contract.py --env-axes  # 环境敏感轴体检
    python scripts/check_openapi_contract.py --write     # 契约**有意**变了之后重生成

退出码：0 = 一致；1 = 漂移（含环境轴断言失败）；
        2 = 环境 / 脚本自身的错（快照缺失或损坏、app 导不进来、
            路径数低于健全性下限）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = BACKEND / "docs" / "api" / "openapi.json"

#: 子进程用的覆盖通道：父进程把「本轴要翻成什么」用这个变量传给子进程。
#: ★ 之所以要有这个通道，是因为固定环境与「按轴切换」是**同一段代码**：
#:   没有它，子进程会被自己的固定值覆盖回原样 ⇒ 三条轴全都「逐字节不变」，
#:   这个体检就变成了永真断言。
_CHILD_ENV_KEY = "OPENAPI_GATE_ENV"

#: 固定环境。见文件顶部 docstring 的表：前四个决定契约形态，
#: LOG_LEVEL 只为让本门禁的输出不被 INFO 淹掉（不改行为）。
DEFAULT_FORCED_ENV = {
    "ENVIRONMENT": "development",  # production 会被启动护栏拒启（缺 METRICS_TOKEN）
    "DEBUG": "false",
    "AUTH_REQUIRED": "true",
    "VOICE_CLONE_ENABLED": "true",  # 取最大面
    "LOG_LEVEL": "ERROR",
    # ★ 第 354 轮补 —— 在**无 .env 的 git worktree** 里实跑才发现漏了这两个：
    #   `main.py` 的 `FastAPI(title=config.app_name, version=config.app_version, ...)`
    #   ⇒ 它们直接进 `info.title` / `info.version`。
    #   不固定的话，本地（`.env` 写 `APP_NAME=CrossBorder-AI-SaaS`）与 CI
    #   （无 `.env` ⇒ 代码默认值 `跨境电商AI SaaS`）导出**不同**契约，
    #   门禁退化成「本地恒绿、CI 恒红」—— 正是本文件开头警告的那件事。
    #   取值 = `.env.example` = 代码默认值（`docker-compose.yml` 未设 APP_NAME）。
    "APP_NAME": "跨境电商AI SaaS",
    "APP_VERSION": "0.1.0",
}

#: voice-clone 路由的挂载前缀（main.py: `app.include_router(voice_clone_router,
#: prefix="/api/v1", ...)` + 路由自带 `/voice-clone...`）。`--env-axes` 用它
#: 算「关掉语音克隆应当消失哪些路径」。前缀改了这条会红，属于预期信号。
VOICE_PREFIX = "/api/v1/voice-clone"

#: 健全性下限：当前 236 条。若低于此值，几乎一定是「路由没挂上」或
#: 「盘点失明」（本仓有过前例：FastAPI 0.141 起 `app.routes` 不再摊平
#: 子路由，逐条遍历读到 0 条却不报错），而不是真的删了 36 条端点。
#: ⇒ 归入退出码 2（环境错），避免与「契约漂移」混为一谈。
MIN_PATHS = 200

#: 漂移清单最多打印多少行（超出只报计数，避免 CI 日志被刷屏）。
MAX_DIFF_LINES = 120


# ─────────────────────────────────────────────────────────────────────────────
# ① 固定环境 —— 必须在 import core.config / main 之前
# ─────────────────────────────────────────────────────────────────────────────
_overrides: dict[str, str] = {}
try:
    _overrides = json.loads(os.environ.get(_CHILD_ENV_KEY) or "{}")
except json.JSONDecodeError:
    print(f"✘ {_CHILD_ENV_KEY} 不是合法 JSON，无法确定本进程该用哪套环境")
    raise SystemExit(2)

FORCED_ENV = {**DEFAULT_FORCED_ENV, **_overrides}
os.environ.update(FORCED_ENV)

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.config import config  # noqa: E402
import main as app_main  # noqa: E402

#: ★ 这里**必须**用别名 `app_main`：本文件末尾有一个同名的 CLI 入口 `main()`，
#:   若这里就绑定成 `main`，函数定义会把它从模块对象覆盖成函数
#:   ⇒ `main.app` 抛 AttributeError（名字解析在调用期，不在定义期）。


# ─────────────────────────────────────────────────────────────────────────────
# ② 规格导出与规范化
# ─────────────────────────────────────────────────────────────────────────────
def canonical(spec: dict) -> str:
    """规范化 JSON 文本（唯一真源）。

    三处约定必须同时成立，否则「逐字节比对」会变成「比不过就报漂移」：
      · `sort_keys=True` —— 不同 Python/pydantic 版本下 dict 插入序可能变，
        排序后与实现细节解耦；
      · `ensure_ascii=False` —— 中文 description 直接落盘，快照可读可 diff；
      · 末尾补一个换行 —— 文本文件的基本礼貌，也让 git 不报 "\\ No newline"。
    """
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_spec() -> dict:
    """导出当前进程环境下的 OpenAPI 规格。"""
    return app_main.app.openapi()


def _sanity(spec: dict) -> str | None:
    """健全性自检；返回错误说明（None = 通过）。

    ★ 先断言「固定环境真的生效」：pydantic-settings 里环境变量优先于 .env，
      但这依赖变量名与字段名对得上。对不上时不会报错，只会**静默**用默认值
      ⇒ 快照变成「运气产物」。所以这里把期望值与实际值对一次账。
    """
    want_voice = FORCED_ENV.get("VOICE_CLONE_ENABLED") == "true"
    got_voice = bool(getattr(config, "voice_clone_enabled", False))
    if got_voice != want_voice:
        return (
            f"环境固定未生效：VOICE_CLONE_ENABLED 期望 {want_voice}，"
            f"config 实际 {got_voice}（变量名与配置字段名可能已不同名）"
        )
    n = len(spec.get("paths") or {})
    if n < MIN_PATHS:
        return (
            f"只导出 {n} 条路径，低于健全性下限 {MIN_PATHS} ⇒ 判为**路由未挂载 / "
            f"盘点失明**，不是契约漂移（本仓 0.141 起 `app.routes` 不再摊平子路由）"
        )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# ③ 漂移比对
# ─────────────────────────────────────────────────────────────────────────────
def diff(old: dict, new: dict) -> list[str]:
    """列出 old → new 的漂移，按语义分组（而不是给一行 repr）。"""
    out: list[str] = []

    def section(title: str, items: list[str]) -> None:
        if items:
            out.append(f"【{title}】")
            out.extend(f"  - {i}" for i in items)

    op = old.get("paths") or {}
    np_ = new.get("paths") or {}
    section("新增路径", sorted(set(np_) - set(op)))
    section("删除路径", sorted(set(op) - set(np_)))

    added_m: list[str] = []
    removed_m: list[str] = []
    changed: list[str] = []
    for p in sorted(set(op) & set(np_)):
        om, nm = set(op[p]), set(np_[p])
        added_m.extend(f"{m.upper()} {p}" for m in sorted(nm - om))
        removed_m.extend(f"{m.upper()} {p}" for m in sorted(om - nm))
        for m in sorted(om & nm):
            a, b = op[p][m], np_[p][m]
            if a != b:
                fields = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
                changed.append(f"{m.upper()} {p} → 字段 {', '.join(f'`{k}`' for k in fields)}")
    section("新增方法", added_m)
    section("删除方法", removed_m)
    section("变更定义", changed)

    oc = old.get("components") or {}
    nc = new.get("components") or {}
    for grp in sorted(set(oc) | set(nc)):
        a, b = oc.get(grp) or {}, nc.get(grp) or {}
        section(f"components.{grp} 新增", sorted(set(b) - set(a)))
        section(f"components.{grp} 删除", sorted(set(a) - set(b)))
        section(
            f"components.{grp} 变更",
            [k for k in sorted(set(a) & set(b)) if a[k] != b[k]],
        )

    section(
        "顶层元信息",
        [
            f"{k}: {old.get(k)!r} → {new.get(k)!r}"
            for k in sorted((set(old) | set(new)) - {"paths", "components"})
            if old.get(k) != new.get(k)
        ],
    )
    return out


def _load_snapshot(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, f"找不到快照文件：{path}"
    try:
        raw = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"快照不是 UTF-8：{path}（{exc}）"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"快照不是合法 JSON：{path}（{exc}）"


# ─────────────────────────────────────────────────────────────────────────────
# ④ 环境敏感轴体检（子进程逐轴翻转）
# ─────────────────────────────────────────────────────────────────────────────
def _child_spec(overrides: dict[str, str], dest: Path) -> tuple[str | None, str]:
    """在**指定环境**下另起一个进程导出规格；返回（规范化文本, 说明）。"""
    if dest.exists():
        dest.unlink()
    env = dict(os.environ)
    env[_CHILD_ENV_KEY] = json.dumps(overrides)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--dump-spec", str(dest)],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0 or not dest.exists():
        tail = (r.stderr or r.stdout).strip().splitlines()
        return None, f"子进程退出码 {r.returncode}：{tail[-1] if tail else '无输出'}"
    return dest.read_text(encoding="utf-8"), ""


def run_env_axes(tmp_dir: Path) -> int:
    spec = export_spec()
    err = _sanity(spec)
    if err:
        print(f"✘ {err}")
        return 2
    base = canonical(spec)

    print("【环境敏感轴体检】")
    print(f"  基线：{ {k: v for k, v in FORCED_ENV.items() if k != 'LOG_LEVEL'} }")

    failures: list[str] = []

    # 轴 1：AUTH_REQUIRED 必须**不动契约**。
    # 它守的是「路由/依赖不得按开关条件挂载」这条铁律（本仓 2026-09-17 前违反过）。
    got, why = _child_spec({"AUTH_REQUIRED": "false"}, tmp_dir / "axis-auth-off.json")
    if got is None:
        failures.append(f"AUTH_REQUIRED=false 子进程失败：{why}")
    elif got != base:
        failures.append(
            "AUTH_REQUIRED 翻转后契约变了（应当逐字节不变）⇒ 有东西按它条件挂载了：\n"
            + "\n".join("    " + x for x in diff(json.loads(base), json.loads(got)))
        )
    else:
        print("  ✔ AUTH_REQUIRED=true → false：契约逐字节不变")

    # 轴 2：VOICE_CLONE_ENABLED 必须**恰好**差 voice-clone 前缀那些路径。
    off_text, why = _child_spec({"VOICE_CLONE_ENABLED": "false"}, tmp_dir / "axis-voice-off.json")
    if off_text is None:
        failures.append(f"VOICE_CLONE_ENABLED=false 子进程失败：{why}")
    else:
        on_paths = set((spec.get("paths") or {}).keys())
        off_paths = set((json.loads(off_text).get("paths") or {}).keys())
        expected_off = {p for p in on_paths if not p.startswith(VOICE_PREFIX)}
        dropped = on_paths - off_paths
        if not dropped:
            failures.append(
                f"关掉 VOICE_CLONE_ENABLED 后一条路径都没少 ⇒ 该开关已形同虚设，"
                f"或 `{VOICE_PREFIX}` 前缀已改（改前缀请同步本文件的 VOICE_PREFIX）"
            )
        elif off_paths != expected_off:
            failures.append(
                "关掉 VOICE_CLONE_ENABLED 的差集**不恰好**是 voice-clone 前缀：\n"
                f"    意外少了：{sorted(off_paths - expected_off) or '（无）'}\n"
                f"    意外多了：{sorted(off_paths - (on_paths - dropped)) or '（无）'}\n"
                f"    应当消失的 {len(dropped)} 条：{sorted(dropped)}"
            )
        else:
            print(f"  ✔ VOICE_CLONE_ENABLED=true → false：恰好少 {len(dropped)} 条（全部在 {VOICE_PREFIX}*）")

    # 轴 3：APP_NAME 必须**只**改 info.title（第 354 轮新增）。
    # 它的存在本身就是上一轮漏做的证据：当时的矩阵只比「有 .env」的那一档，
    # 而 `.env` 恰好把 APP_NAME 改成了非默认值 ⇒ 整条轴隐身。
    probe_title = "契约轴探针-用后即弃"
    got3, why = _child_spec({"APP_NAME": probe_title}, tmp_dir / "axis-appname.json")
    if got3 is None:
        failures.append(f"APP_NAME 覆写子进程失败：{why}")
    else:
        items = [x for x in diff(json.loads(base), json.loads(got3)) if x.startswith("  - ")]
        if len(items) != 1 or not items[0].startswith("  - info:"):
            failures.append(
                "覆写 APP_NAME 后的差异**不止** info.title 一项"
                "（说明还有别的东西在跟着 app_name 走）：\n"
                + "\n".join("    " + x for x in items)
            )
        elif probe_title not in items[0]:
            failures.append(f"info.title 没跟着 APP_NAME 走：{items[0]}")
        else:
            print("  ✔ APP_NAME 覆写：差异恰好 1 项（info），且 title 跟着走")

    if failures:
        print("\n".join(f"✘ {f}" for f in failures))
        return 1
    print("结果: 环境敏感轴全部符合预期")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 入口
# ─────────────────────────────────────────────────────────────────────────────
def _usage() -> None:
    print(__doc__)


def main(argv: list[str]) -> int:
    mode = "check"
    snapshot = SNAPSHOT
    dump_to: Path | None = None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--check",):
            mode = "check"
        elif a == "--write":
            mode = "write"
        elif a == "--env-axes":
            mode = "env-axes"
        elif a == "--dump-spec":
            i += 1
            dump_to = Path(argv[i]).resolve()
            mode = "dump"
        elif a == "--snapshot":
            i += 1
            snapshot = Path(argv[i]).resolve()
        elif a in ("-h", "--help"):
            _usage()
            return 0
        else:
            print(f"✘ 未知参数：{a}")
            _usage()
            return 2
        i += 1

    spec = export_spec()

    if mode == "dump":
        assert dump_to is not None
        dump_to.parent.mkdir(parents=True, exist_ok=True)
        dump_to.write_text(canonical(spec), encoding="utf-8", newline="\n")
        return 0

    err = _sanity(spec)
    if err:
        print(f"✘ {err}")
        return 2

    text = canonical(spec)
    n_paths = len(spec.get("paths") or {})
    n_schemas = len(((spec.get("components") or {}).get("schemas") or {}))

    if mode == "write":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(text, encoding="utf-8", newline="\n")
        print(f"✔ 已写入契约快照：{snapshot}")
        print(f"  路径 {n_paths} 条 / schema {n_schemas} 个 / {len(text)} 字节")
        return 0

    if mode == "env-axes":
        import tempfile

        with tempfile.TemporaryDirectory(prefix="openapi-axes-") as td:
            return run_env_axes(Path(td))

    old, load_err = _load_snapshot(snapshot)
    if load_err:
        print(f"✘ {load_err}")
        print("  重新生成： python scripts/check_openapi_contract.py --write")
        return 2

    old_text = canonical(old)
    if old_text == text:
        print(f"✔ OpenAPI 契约一致（路径 {n_paths} 条 / schema {n_schemas} 个）")
        return 0

    # ★ 传 `spec`（dict）而不是上面那个 `text`（str）：diff() 逐层 .get()，
    #   传字符串会直接 AttributeError —— 这条曾被本文件的反向用例抓出来过。
    lines = diff(old, spec)
    print(f"✘ OpenAPI 契约已漂移（快照 {snapshot}）")
    print(f"  快照：路径 {len(old.get('paths') or {})} 条 / "
          f"schema {len(((old.get('components') or {}).get('schemas') or {}))} 个")
    print(f"  当前：路径 {n_paths} 条 / schema {n_schemas} 个")
    for line in lines[:MAX_DIFF_LINES]:
        print(line)
    if len(lines) > MAX_DIFF_LINES:
        print(f"  …（另有 {len(lines) - MAX_DIFF_LINES} 行未打印）")
    print(
        "\n★ 若这次变更是**有意的**：python scripts/check_openapi_contract.py --write"
        " 重新生成快照并一并提交；\n"
        "  若是无意改动：请恢复代码，而不是重生成快照。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
