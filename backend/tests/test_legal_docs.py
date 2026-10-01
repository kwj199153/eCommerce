"""法务文本门禁（第 351 轮 · P0-9）。

法务文本的缺陷形态与代码不同：它不会崩，只会**静默地不再为真**。
本仓已经踩过一次同族形态（「配置写了但没有任何东西会去调用它」），
法务文本对应的是「**文本写了但代码里没有这件事**」。

本门禁只钉**可客观判定**的四件事（钉不出客观判据的项一律留白，
见 `docs/legal/PLACEHOLDERS.md` 的进度表与「已知缺口」）：

  L1 对外发布的文本里**不得**残留仅供审阅的 `<details>` 工程侧事实核对表。
     那份表把「政策里的每一句」映射到「代码里的哪一处」，是给律师核对用的，
     发布出去等于把内部实现细节当隐私政策的一部分。

  L2 留存天数必须与后端配置**现算对账**。
     ★ 期望值**不手写**：从文档里读出「这项**由哪个配置**决定」（`由 `X` 配置`），
       再去 `core/config.py` 取该字段的默认值比对。
       于是两个方向都会红：改了配置默认值没改文档、或改了文档没改配置。
       为什么必须相等而不是「≥」：政策承诺的留存期**不得长于**实际清理行为
       （说 90 天却实际留 120 天 = 虚假陈述）。取等号后任一侧漂移都能被抓到。

  L3 模板里出现的占位符必须**全部登记**在 `PLACEHOLDERS.md`。
     那句「新增字段必须先写进对应文档、再登记到本表」原来只是一句注释约定，
     没有任何东西会让它失败 —— 这里给它装上牙齿。

  L4 `PLACEHOLDERS.md` 自报的「当前共 N 个占位符」必须等于**实测**个数。
     自报数与实测数脱节，是本仓「工具现算清单」这句话失效的起点。

★ 本门禁**不**断言「占位符为 0」：36 项里有 31 项是主体信息/法务参数
  （工商全称、注册地址、管辖法院…），仓内零线索，编造等于往法律文本里写假事实。
  它们由业务方给值后回填 —— 这是**有意的未完成**，不是漏做。
"""

from __future__ import annotations

import re
from pathlib import Path

from core.config import Settings

#: 对外发布的四件文本；`PLACEHOLDERS.md` / `README.md` 是内部件，不在发布面内
PUBLISHED = (
    "LICENSE",
    "privacy-policy.md",
    "terms-of-service.md",
    "data-processing-agreement.md",
)

_LEGAL = Path(__file__).resolve().parents[2] / "docs" / "legal"

#: 模板全集 —— 与 `PLACEHOLDERS.md` 顶部自证命令同口径：`*.md` + `LICENSE`
TEMPLATES = tuple(sorted(p.name for p in _LEGAL.glob("*.md"))) + ("LICENSE",)

#: `{{NAME}}` 形态的占位符（与自证 grep 的字符类一致）
_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

#: `PLACEHOLDERS.md` 用反引号登记占位符名
_REGISTERED = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")

#: 政策表里「该项留存 N 天，由 `CONFIG_NAME` 配置」——文档自己声明了它绑定哪个配置
_RETENTION_ROW = re.compile(
    r"^\s*\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<days>\d+)\s*天"
    r"(?P<tail>[^|]*?)由\s*`(?P<env>[A-Z][A-Z0-9_]+)`",
    re.MULTILINE,
)

#: 自报计数
_SELF_REPORTED = re.compile(r"当前共\s*(\d+)\s*个占位符")


def _read(name: str) -> str:
    """按字节读 + 行尾归一化：本仓维护窗内既有 LF 也有 CRLF，锚点不归一化会恒不命中。"""
    return (_LEGAL / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _used_placeholders() -> set[str]:
    used: set[str] = set()
    for name in TEMPLATES:
        used |= set(_PLACEHOLDER.findall(_read(name)))
    return used


# ============================================================ L1


def test_published_texts_carry_no_internal_engineering_table() -> None:
    """L1：对外文本不得残留 `<details>` 工程侧事实核对表。"""
    offenders = [n for n in PUBLISHED if "<details>" in _read(n) or "</details>" in _read(n)]
    assert not offenders, (
        f"这些对外文本里还留着内部审阅用的 <details> 块：{offenders} —— "
        "它是「政策里的每一句对应代码里的哪一处」的内部映射，发布出去等于泄露实现细节"
    )


def test_internal_table_is_not_left_in_the_wrong_place_either() -> None:
    """L1 补强：那份表也不能「搬个家」继续躺在别的对外文本里。

    ★ 为什么不与上一条合并：上一条只扫 `PUBLISHED` 白名单；白名单一旦漏登记
      新文本，上一条就**静默放行**。这里反向扫「任何 md 里含该表特征串」，
      两者一起才构成「既没留在原地、也没被挪到别处」。
    """
    marker = "工程侧事实核对表"
    offenders = [
        p.name
        for p in _LEGAL.glob("*.md")
        if marker in (p.read_bytes().decode("utf-8").replace("\r\n", "\n"))
    ]
    assert not offenders, f"内部核对表特征串 `{marker}` 仍出现在：{offenders}"


# ============================================================ L2


def test_retention_days_are_reconciled_with_backend_config() -> None:
    """L2：政策里声明的留存天数 == 它自己点名的那个后端配置的默认值。"""
    rows: list[tuple[str, str, str, str]] = []
    for name in PUBLISHED:
        for m in _RETENTION_ROW.finditer(_read(name)):
            rows.append((name, m.group("label"), m.group("days"), m.group("env")))
    assert rows, (
        "一行「N 天（由 `X` 配置）」都没匹配到 —— 要么政策改了写法，"
        "要么本门禁的正则已经失效（失效的门禁比没有更糟）"
    )

    bad: list[str] = []
    for name, label, days, env in rows:
        field = env.lower()
        if field not in Settings.model_fields:
            bad.append(f"{name}: {label.strip()} 点名了 `{env}`，但 core/config.py 里没有这个字段")
            continue
        default = Settings.model_fields[field].default
        if int(days) != int(default):
            bad.append(
                f"{name}: {label.strip()} 写 {days} 天，而 `{env}`（{field}）默认值是 {default} —— "
                "政策承诺的留存期不得长于实际清理行为"
            )
    assert not bad, "\n".join(bad)


# ============================================================ L3


def test_every_placeholder_is_registered_in_the_checklist() -> None:
    """L3：模板里的占位符必须全部登记在 `PLACEHOLDERS.md`。"""
    used = _used_placeholders()
    registered = set(_REGISTERED.findall(_read("PLACEHOLDERS.md")))
    missing = sorted(used - registered)
    assert not missing, (
        f"这些占位符出现在模板里，却没登记进 PLACEHOLDERS.md：{missing} —— "
        "「悄悄多出来的未填项」会一路带到发布态"
    )


# ============================================================ L4


def test_checklist_reports_the_real_placeholder_count() -> None:
    """L4：`PLACEHOLDERS.md` 自报的个数必须等于实测个数。"""
    m = _SELF_REPORTED.search(_read("PLACEHOLDERS.md"))
    assert m, "PLACEHOLDERS.md 里找不到「当前共 N 个占位符」这句自报 —— 工具现算清单的锚点丢了"
    reported = int(m.group(1))
    actual = len(_used_placeholders())
    assert reported == actual, (
        f"PLACEHOLDERS.md 自报 {reported} 个，实测 {actual} 个 —— "
        "自报数与实测数脱节，说明这份清单已经不再是被工具维护的"
    )
