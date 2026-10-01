"""门禁：OpenAPI 契约快照（第 353 轮 · L3-5）。

为什么用 pytest 驱动一个 scripts/ 脚本，而不是把断言抄进用例
-----------------------------------------------------------
门禁的真源必须是**一份**实现。抄一份到测试里，两份必然各自演进 ——
典型结局是「脚本守住了、测试守的还是旧形态」，两边都不报错。
所以这里只做两件事：跑脚本 + 断言退出码与关键行；**判据本身完全住在脚本里**
（同 `test_compose_secrets_gate.py` 对 `scripts/check_compose_secrets.py`、
`test_tenant_isolation_gate.py` 对 `scripts/check_tenant_isolation.py` 的做法）。

本文件在 CI 里的入口
--------------------
`ci.yml` 的后端 job 跑 `pytest tests/ -q` ⇒ 本文件自动纳入，无需新增步骤。
（这也是为什么没有在 workflow 里另加一个 `python scripts/check_openapi_contract.py`
步骤：同一份脚本跑两遍只会拖长 CI，不会多守任何东西。）

★ 本文件里有两条性质不同的用例，缺一不可
  · 正向：当前代码 ≡ 已提交的快照。**这才是门禁**。
  · 反向：把快照改坏 / 删掉，退出码必须跟着变（1 / 2）。
    没有这一条，「脚本恒返回 0」也能让正向用例全绿 —— 那就是没有门禁。
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "check_openapi_contract.py"
SNAPSHOT = BACKEND / "docs" / "api" / "openapi.json"

#: 与脚本里 `canonical()` 保持同一形态（sort_keys + ensure_ascii=False + 末尾换行）。
#: ★ 必须逐字一致：否则篡改出来的副本自己就与规范形态不同，
#:   漂移清单里会混进一堆"字段变了"的噪音，掩盖掉我们真正要断言的那一条。
_PROBE_PATH = "/api/v1/__openapi_gate_probe__"
_REAL_PATH = "/api/v1/skus"
_REAL_SCHEMA = "HTTPValidationError"

#: ★★ 漂移方向必须先想清楚，否则断言会整个写反（本轮实测踩过）：
#:   脚本里 `diff(快照, 当前app)` —— **快照是"过去"，app 是"现在"**。
#:   所以「快照里有、app 里没有」= **删除路径**（有人删了端点），
#:   「app 里有、快照里没有」= **新增路径**。
#:   本文件用「改坏快照副本」的方式模拟这两侧，标签按**代码侧**的动作来写。
_DRIFT_CASES = [
    (
        "code-added-path",  # 代码侧新增了端点 ⇒ 快照里不该有它
        lambda s: s["paths"].pop(_REAL_PATH),
        ("新增路径", _REAL_PATH),
    ),
    (
        "code-removed-path",  # 代码侧删掉了端点 ⇒ 快照里还留着它
        lambda s: s["paths"].__setitem__(_PROBE_PATH, {}),
        ("删除路径", _PROBE_PATH),
    ),
    (
        "code-added-schema",  # 代码侧新增了响应模型 ⇒ 快照里没有它
        lambda s: s["components"]["schemas"].pop(_REAL_SCHEMA),
        ("components.schemas 新增", _REAL_SCHEMA),
    ),
]


def _canonical(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _tampered(tmp_path: Path, mutate) -> Path:
    spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    mutate(spec)
    dest = tmp_path / "openapi.json"
    dest.write_text(_canonical(spec), encoding="utf-8", newline="\n")
    return dest


def test_snapshot_committed_and_matches_current_app():
    """正向：当前 app 导出的契约必须与已提交快照逐字节一致。"""
    assert SCRIPT.is_file(), f"门禁脚本缺失：{SCRIPT}"
    assert SNAPSHOT.is_file(), (
        f"契约快照缺失：{SNAPSHOT}\n"
        f"生成：python scripts/check_openapi_contract.py --write"
    )
    r = _run()
    assert r.returncode == 0, (
        f"OpenAPI 契约与快照不一致（退出码 {r.returncode}）：\n{r.stdout}\n{r.stderr}"
    )
    assert "契约一致" in r.stdout


def test_gate_names_the_drifting_path():
    """正向（可读性）：快照的路径数必须是真的很多 —— 防「空快照也能全绿」。

    ★ 这条不是在重复脚本里的健全性下限：那一条守的是**导出**这一侧，
      本条件守的是**已提交的快照**这一侧。两者可以独立坏掉
      （例如有人把 `--write` 生成的空壳提交了上去）。
    """
    spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(spec.get("paths") or {}) >= 200, (
        f"快照里只有 {len(spec.get('paths') or {})} 条路径 ⇒ 快照本身可疑"
    )
    assert spec.get("openapi", "").startswith("3."), (
        f"快照的 openapi 版本不是 3.x：{spec.get('openapi')!r}"
    )


@pytest.mark.parametrize(("label", "mutate", "expect"), _DRIFT_CASES)
def test_gate_detects_drift_in_tampered_snapshot(tmp_path, label, mutate, expect):
    """反向：把快照改坏 ⇒ 必须退出码 1，且清单里**指名道姓**地说出改了什么。"""
    tampered = _tampered(tmp_path, mutate)
    r = _run("--snapshot", str(tampered))
    assert r.returncode == 1, (
        f"[{label}] 期望退出码 1（漂移），实际 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    )
    section, needle = expect
    assert section in r.stdout, f"[{label}] 漂移清单缺少分组「{section}」：\n{r.stdout}"
    assert needle in r.stdout, f"[{label}] 漂移清单没有点名 `{needle}`：\n{r.stdout}"


def test_gate_reports_setup_error_when_snapshot_missing(tmp_path):
    """反向：快照不存在 ⇒ 退出码 2（环境错），而不是 0 或 1。

    ★ 为什么必须与「漂移(1)」分开：快照缺失时**无法**判断契约对不对。
      若它与漂移共用退出码，或干脆返回 0，那么「有人删掉快照」会表现为
      「契约是好的」—— 门禁从此名存实亡。
    """
    r = _run("--snapshot", str(tmp_path / "definitely-not-here.json"))
    assert r.returncode == 2, f"期望退出码 2，实际 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    assert "找不到快照文件" in r.stdout
    assert "--write" in r.stdout, "报错必须告诉人怎么修（重生成命令）"


def test_gate_reports_setup_error_when_snapshot_corrupt(tmp_path):
    """反向：快照不是合法 JSON ⇒ 退出码 2，不是崩栈。"""
    bad = tmp_path / "openapi.json"
    bad.write_text("{ this is not json", encoding="utf-8", newline="\n")
    r = _run("--snapshot", str(bad))
    assert r.returncode == 2, f"期望退出码 2，实际 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    assert "不是合法 JSON" in r.stdout


def test_env_axes_are_pinned():
    """守住「契约的环境敏感轴只有一根，且恰好是 voice-clone」。

    ★ 为什么这条值钱：固定环境让契约确定可复现，代价是**其它轴的影响会隐身**。
      例如有人再加一个 `if config.X: include_router(...)`，生产环境的真实契约
      就与快照不同，而上面的正向用例照样全绿 —— 那正是本仓 2026-09-17 修掉的
      缺陷形态（`BUSINESS_AUTH` 曾按 `auth_required` 条件挂载）。
      本条件把 AUTH_REQUIRED 与 VOICE_CLONE_ENABLED 各翻一次：
      前者必须**逐字节不变**，后者的差集必须**恰好**是 voice-clone 前缀。
    """
    r = _run("--env-axes")
    assert r.returncode == 0, (
        f"环境敏感轴体检失败（退出码 {r.returncode}）：\n{r.stdout}\n{r.stderr}"
    )
    assert "环境敏感轴全部符合预期" in r.stdout
    assert "AUTH_REQUIRED=true → false：契约逐字节不变" in r.stdout


#: ★ 已登记的「条件挂载轴」：`main.py` 里**按 config 字段决定挂不挂路由**的那些字段。
#:   登记在这里，是为了让**新增一根轴**无法静默发生（见下面两条用例的说明）。
#:   第 354 轮实测登记表 = `{voice_clone_enabled}`：
#:     · `voice_clone_enabled` —— `if config.voice_clone_enabled: app.include_router(voice_clone_router)`
#:     · `metrics_enabled` 不算：它那个块里只有 `@app.get("/metrics", include_in_schema=False)`，
#:       **没有** `include_router`，且 `include_in_schema=False` 天然不进 schema
#:     · `auth_required` 不算：`BUSINESS_AUTH` 自 2026-09-17 起是**无条件**常量
#:       （`[Depends(require_auth_if_enabled)]`，运行期判身份），AST 扫不到条件挂载
_CONDITIONAL_MOUNT_AXES = {"voice_clone_enabled"}


def _conditional_mount_axes() -> set[str]:
    """AST 实测：`main.py` 里「按 config 字段条件挂载路由」的字段集合。

    ★ 用 AST 而不是正则：正则会被注释 / docstring / 字符串里的同形文本骗过
      （本仓铁律：判据禁「源码字符串包含」，形态判据一律走 AST）。
    """
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        fields = {
            sub.attr
            for sub in ast.walk(node.test)
            if isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "config"
        }
        if not fields:
            continue
        mounts = [
            call
            for stmt in node.body
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "include_router"
        ]
        if mounts:
            found |= fields
    return found


def test_conditional_mount_axes_are_registered():
    """反向：`main.py` 的条件挂载轴必须**恰好**等于已登记的那一组。

    ★ 这条补的是 `--env-axes` 的结构性缺口：
      `--env-axes` 只翻**已登记**的轴 ⇒ 「新加一根轴」它天然看不见
      （它翻的那两根照样符合预期，退出码 0）。而新轴恰恰是
      「生产契约 ≠ 快照」的**唯一**来源 —— 本仓 2026-09-17 的 `BUSINESS_AUTH`
      就是这个形态，且当时没有任何流程会红。

    ★ 双向断言（不是只查 `added`）：登记表里留着已消失的轴 = 死登记，
      下一轮会照着它去翻一个不存在的开关，白跑。
    """
    found = _conditional_mount_axes()
    assert found, (
        "一条条件挂载都没扫到 ⇒ 扫描器自身失效（判据会退化成恒真），先查 `main.py` 结构"
    )
    added = sorted(found - _CONDITIONAL_MOUNT_AXES)
    removed = sorted(_CONDITIONAL_MOUNT_AXES - found)
    assert not added, (
        f"`main.py` 新增了未登记的条件挂载轴：{added}\n"
        "  ⇒ 快照只在「该字段取固定值」时成立，生产可能导出另一份契约。\n"
        "  修法（二选一）：\n"
        "    ① 该字段只该有一种取值 ⇒ 固定进 check_openapi_contract.py 的 FORCED_ENV；\n"
        "    ② 两种取值都合法       ⇒ 在 run_env_axes() 里补一条翻转断言；\n"
        "  两者都要把字段加进本文件的 _CONDITIONAL_MOUNT_AXES。"
    )
    assert not removed, (
        f"登记表里的轴已不在 `main.py`：{removed} ⇒ 死登记，请同步 _CONDITIONAL_MOUNT_AXES"
    )


def test_registered_axes_are_actually_flipped():
    """反向：登记表里的每个轴，`--env-axes` 必须**真的翻过它**（防「登记了不翻」）。

    与上一条配对：上一条守「代码里的轴都登记了」，这一条守「登记的轴都被守了」。
    少任何一半，登记表都能变成纯文档。
    """
    r = _run("--env-axes")
    assert r.returncode == 0, f"--env-axes 失败：\n{r.stdout}\n{r.stderr}"
    for field in sorted(_CONDITIONAL_MOUNT_AXES):
        assert field.upper() in r.stdout, (
            f"`{field}` 登记为条件挂载轴，但 `--env-axes` 的输出里没有它 ⇒ "
            f"登记表与实际守备不一致：\n{r.stdout}"
        )
