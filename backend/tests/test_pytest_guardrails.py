# -*- coding: utf-8 -*-
"""「护栏真的装了」门禁（第 247 轮）。

==============================================================================
★ 本文件钉的是什么
==============================================================================
`pytest.ini` 里有三行**依赖插件才生效**的配置：

    timeout = 120
    timeout_method = thread

它们交给 `pytest-timeout`。若那个包没装，pytest 只会打一条

    PytestConfigWarning: Unknown config option: timeout

然后**照常跑完并报绿** —— 于是「单条用例墙钟上限」这道护栏整个不存在。
症状要等到下次真的卡死才暴露（第 243 轮实测：卡在收尾 15 min，只能人工 kill；
而卡住的进程既不红也不绿，把整轮收敛拖住）。

⇒ 本仓已登记同族判据：**配置和依赖必须成对存在；只有配置没有依赖 =
  纸面门禁、承诺没有兑现**（见 `requirements-dev.txt` 开头那段关于 ruff 的说明 —— 
  那份 `[tool.ruff]` 配置从写下的那天起就没被执行过一次）。
本文件把这条从「注释」升级成「断言」。

★ 第 247 轮的来由（不是假想，是上一轮归因出来的最后一条红）
`requirements-dev.txt` 声明了 `pytest-timeout>=2.3`，但**从未安装** ⇒
`pytest.ini` 的 `timeout` 一直是未知配置项。它属于**声明承诺型假门禁**：
源码里有配置、装的时候没有包，中间没有任何东西会报错。

==============================================================================
★ 同样钉住 `requirements.txt` 的 fastapi 上界
==============================================================================
FastAPI 0.141 一次改了两处**静默型**库行为，本仓因此爆出 12 条红，**全部无报错**：
  ① `include_router()` 不再摊平子路由，改为往 `app.routes` 追加惰性容器
     `_IncludedRouter` ⇒ 一切「`for r in app.routes: r.path`」的路由盘点读到空
     （实测 198 条业务端点一条都数不到；连鉴权覆盖体检脚本都在「什么都没扫到」
     的情况下**退出码 0**）；
  ② yield 依赖的 teardown 移到响应发送**之后** ⇒ 依赖里 `add_task` 注册的
     后台任务**永远不执行** ⇒ 计费静默不记账（HTTP 一切正常）。

代码侧已按 0.141 修正（`scripts/route_inventory.py` + `core/metering/usage_tracker.py`）。
上界是**防复发机制**：下一次跨 minor 升级必须显式做，而不是被一条
`pip install -U` 顺手带上去。★ 注释里的承诺不算数，所以这里断言它。

==============================================================================
★ 反向注入（每条都必须让本文件转红，实测见 §894 的读数）
==============================================================================
  RI-1 删掉 `pytest.ini` 的 `timeout = 120` ⇒ 第 1 条转红（护栏读数拿不到）。
  RI-2 删掉 `requirements-dev.txt` 的 `pytest-timeout` 行 ⇒ 第 2 条转红。
  RI-3 把 `requirements.txt` 里 fastapi 改回 `fastapi>=0.104.0`（无上界）⇒ 第 3 条转红。
  RI-4 把上界改成 `<0.141`（挡住现装版本）⇒ 第 3 条转红。
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REQ_TXT = BACKEND / "requirements.txt"
REQ_DEV = BACKEND / "requirements-dev.txt"


def _requirement_lines(path: Path, name: str) -> list[str]:
    """取声明文件里以 `name` 开头的依赖行（剥 `#` 注释、剥行尾注释）。"""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0].strip()
        if body and body.replace("-", "_").startswith(name.replace("-", "_")):
            out.append(body)
    return out


# ============================================================================
# 1. 卡死护栏：`pytest-timeout` 真的装了，且 `pytest.ini` 的读数拿得到
# ============================================================================


def test_timeout_rail_is_actually_installed(pytestconfig):
    """★★★ `pytest.ini` 的 `timeout` 必须**真的**被插件认下来。

    ★ 为什么这件事需要一条断言：配置项写错/插件没装时，pytest **不报错**，
      只发一条 `PytestConfigWarning`，然后照常报绿。
      ⇒ 「声明了没装」这类缺陷在测试结果里**完全不可见**。
    """
    assert pytestconfig.pluginmanager.hasplugin("timeout"), (
        "`pytest-timeout` 插件没装 —— `pytest.ini` 里的 `timeout = 120` / "
        "`timeout_method = thread` 是**纸面配置**，卡死护栏不存在"
        "（症状：卡住的用例既不红也不绿，把整轮收敛拖住）。\n"
        "`pip install -r requirements-dev.txt` 之后重跑。"
    )

    raw = pytestconfig.getini("timeout")
    assert raw, (
        "`pytest.ini` 读不到 `timeout` —— 插件在但配置项没了 ⇒ 护栏同样不存在。"
    )
    assert float(raw) > 0, f"timeout 必须是正数（读到 {raw!r}）"

    method = pytestconfig.getini("timeout_method")
    assert method in {"signal", "thread"}, (
        f"`timeout_method` 只能是 signal / thread（读到 {method!r}）。"
        " ★ Windows 无 SIGALRM ⇒ 本仓必须用 `thread`。"
    )


def test_timeout_rail_is_declared_in_dev_requirements():
    """声明文件里必须在 —— 否则新机器/CI 装完就是「没装」。"""
    assert _requirement_lines(REQ_DEV, "pytest-timeout"), (
        "`requirements-dev.txt` 里没有 `pytest-timeout` 声明 —— "
        "`pytest.ini` 的 timeout 配置失去来源（本仓判据：配置和依赖必须成对存在）。"
    )


# ============================================================================
# 2. 框架升级护栏：fastapi 必须有上界，且现装版本落在区间内
# ============================================================================


def test_fastapi_has_upper_bound_and_installed_version_fits():
    """★★★ fastapi 必须**带上界**，且现装版本在区间内。

    ★ 为什么要这条：0.141 的两次静默行为变化一次爆出 12 条红（见模块 docstring）。
      上界是防复发机制。**注释里写「已加上界」不算数** —— 删掉 `<0.142` 不会
      有任何症状，直到下次一轮门禁集体失明。所以把它变成断言。

    ★ 第二条断言（现装版本必须落在区间内）是给**升级者**的提示：
      真要在本机装 0.142，本文件会先红 —— 逼你显式确认过新版本的行为，
      而不是让门禁静默失明。
    """
    from importlib.metadata import PackageNotFoundError, version as _dist_version

    from packaging.requirements import Requirement

    lines = _requirement_lines(REQ_TXT, "fastapi")
    assert len(lines) == 1, (
        f"`requirements.txt` 里 fastapi 的声明应恰好 1 行，实际 {len(lines)} 行：{lines}"
    )
    req = Requirement(lines[0])
    assert any(s.operator in ("<", "<=") for s in req.specifier), (
        f"fastapi 声明 `{lines[0]}` **没有版本上界** —— 这正是第 247 轮 12 条红的引爆器："
        "一次 `pip install -U` 就能把 0.141 的静默行为变化带进来。"
        " 请写成 `fastapi>=<下界>,<<下一个未验证的 minor>`。"
    )

    try:
        installed = _dist_version("fastapi")
    except PackageNotFoundError:  # pragma: no cover — 没装 fastapi 时其它用例早炸了
        return
    assert req.specifier.contains(installed, prereleases=True), (
        f"现装 fastapi {installed} **不在** `{lines[0]}` 允许的区间内。"
        " 要么把上界显式抬上去（并先按新版本重验 `scripts/route_inventory.py` 与 "
        "`meter_agent_chat` 的结算时机），要么把版本降回区间内。"
    )
