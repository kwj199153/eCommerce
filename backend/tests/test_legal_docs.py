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

  L5 仓库根 `LICENSE` 的**许可条款部分**必须与 `docs/legal/LICENSE` 逐字节一致。
     同一份许可有两份落地（维护副本 + 对外发行物），任一侧单独改动都会漂移，
     而漂移的方向通常是「发行物比维护副本旧」—— 客户看到的条款与仓库内的不一致。

  L6 根 `LICENSE` **不得**含维护者备注块。
     与上一轮删掉的 `<details> 工程侧事实核对表` 同族：「写给自己看的话」不能随
     对外发行物交付 —— 根 LICENSE 会被直接复制进 release / 分发镜像。

  L7 `subprocessors.md` 里引用的每个**代码取证锚点**必须在磁盘上真实存在。
     子处理者清单的可信度取决于「能否核对」：路径悬空 = 文件改名后清单没跟着改，
     或者锚点是凭印象编的。锚点数量下限挡住「把锚点全删、只留一句结论」的退化。

  L8 隐私政策与 DPA 都必须**链接到** `subprocessors.md`，且不得再出现
     `{{SUBPROCESSOR_LIST_URL}}`。防「清单建好了、对外文本却查不到」的悬空引用。

★ 本门禁**不**断言「占位符为 0」：余下的各项全部是主体信息 / 法务参数 / 部署事实 /
  客户侧字段（工商全称、注册地址、管辖法院、留存期的产品决策…），仓内零线索，
  编造等于往法律文本里写假事实。它们由业务方给值后回填 —— 这是**有意的未完成**，
  不是漏做；能由仓库客观确定的部分已按代码取证回填（见 `PLACEHOLDERS.md`「已处置」）。
"""

from __future__ import annotations

import re
from pathlib import Path

from core.config import Settings

#: 对外发布面；`PLACEHOLDERS.md` / `README.md` 是内部件，不在发布面内。
#: ★ `subprocessors.md` 是**客户/尽调方**要看的那一份，属于发布面。
PUBLISHED = (
    "LICENSE",
    "privacy-policy.md",
    "terms-of-service.md",
    "data-processing-agreement.md",
    "subprocessors.md",
)

_ROOT = Path(__file__).resolve().parents[2]
_LEGAL = _ROOT / "docs" / "legal"

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

#: 维护者备注块的起始标记：只应出现在 `docs/legal/LICENSE`（维护副本），不应进根 LICENSE
_MAINTAINER_MARKER = "★ 维护者备注"

#: 子处理者清单里的「代码取证锚点」形态：反引号包裹的 `backend/...` 路径
_EVIDENCE_PATH = re.compile(r"`(backend/[A-Za-z0-9_./\-]+)`")


def _read(name: str) -> str:
    """按字节读 + 行尾归一化：本仓维护窗内既有 LF 也有 CRLF，锚点不归一化会恒不命中。"""
    return (_LEGAL / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _license_terms(raw: str) -> str:
    """取「许可条款」部分：剥掉维护者备注块，以及它前面那两行 `====` 分隔线与尾部空行。

    ★ 两侧（根 LICENSE / docs/legal/LICENSE）必须走**同一个**剥离函数，
      否则比较的是两个不同口径的切片，差异会被剥离逻辑本身吃掉或凭空制造。
    """
    lines = raw.split(_MAINTAINER_MARKER)[0].split("\n")
    while lines and (lines[-1].strip() == "" or set(lines[-1].strip()) == {"="}):
        lines.pop()
    return "\n".join(lines) + "\n"


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


# ============================================================ L5 / L6 · LICENSE 两份落地


def test_root_license_terms_match_the_reference_copy() -> None:
    """L5：仓库根 `LICENSE` 的许可条款部分必须与 `docs/legal/LICENSE` 逐字节一致。

    ★ 为什么要钉：同一份许可在本仓有两处落地 ——
        `docs/legal/LICENSE`（维护副本，含维护者备注）与 `<repo>/LICENSE`（对外发行物）。
      两处并存意味着**每改一次条款都要改两遍**，而漏改一侧不会报错、只会静默漂移。
      漂移方向通常是「发行物比维护副本旧」：客户拿到的条款与仓库里的不一致。
    """
    root = _ROOT / "LICENSE"
    assert root.exists(), (
        "仓库根没有 LICENSE —— 权利状态默认不明"
        "（`README.md` 与 `terms-of-service.md` 都写着「详见仓库 LICENSE」）"
    )
    root_terms = _license_terms(root.read_bytes().decode("utf-8").replace("\r\n", "\n"))
    ref_terms = _license_terms(_read("LICENSE"))
    assert root_terms.strip(), "根 LICENSE 的条款部分为空（只剩维护者备注？）"
    assert root_terms == ref_terms, (
        "根 LICENSE 的条款部分与 docs/legal/LICENSE 不一致：\n"
        f"  根 LICENSE      : {len(root_terms.encode('utf-8'))} B\n"
        f"  docs/legal/LICENSE: {len(ref_terms.encode('utf-8'))} B\n"
        "改条款请同步两处：`docs/legal/LICENSE` 是维护副本，根文件是发行物"
    )


def test_root_license_carries_no_internal_maintainer_note() -> None:
    """L6：根 `LICENSE` 不得含维护者备注块（防「写给自己看的话」随发行物出厂）。

    ★ 同族形态：上一轮删掉的 `<details>` 工程侧事实核对表。那次的判据只扫
      `docs/legal/*.md`，管不到仓库根 —— 而根 LICENSE 恰恰是会被直接复制进
      release / 分发镜像的那一份，所以这里单独钉一条。
    """
    raw = (_ROOT / "LICENSE").read_bytes().decode("utf-8").replace("\r\n", "\n")
    offenders = [m for m in (_MAINTAINER_MARKER, "不应随对外发行物一同交付") if m in raw]
    assert not offenders, (
        f"根 LICENSE 里残留工程侧维护者标记：{offenders} —— "
        "该区块写的是「若本项目决定开源请如何替换」这类操作说明，不属于许可条款；"
        "它只应留在 docs/legal/LICENSE"
    )


# ============================================================ L7 / L8 · 子处理者清单


def test_subprocessors_evidence_anchors_actually_exist() -> None:
    """L7：子处理者清单里引用的每个代码锚点，必须在磁盘上真实存在。

    ★ 为什么判「路径存在」而不是「内容里含某个函数名」：清单的全部价值在于**可核对**。
      路径级核对已经能挡住两类失真 ——
        ① 文件改名/删除后清单没跟着改（引用悬空）；
        ② 有人凭印象补一条服务商，锚点路径是编的。
      再钉一个数量下限，挡住「把锚点全删掉、只留一句结论」的退化。
    """
    page = _LEGAL / "subprocessors.md"
    assert page.exists(), (
        "docs/legal/subprocessors.md 不存在 —— 隐私政策第四节与 DPA 第五条都引用了它，"
        "会形成悬空引用"
    )
    text = page.read_bytes().decode("utf-8").replace("\r\n", "\n")
    anchors = sorted(set(_EVIDENCE_PATH.findall(text)))
    assert len(anchors) >= 5, (
        f"子处理者清单里只找到 {len(anchors)} 个代码取证锚点（要求 ≥ 5）—— "
        "清单已经退化成一句结论，客户无法核对"
    )
    missing = [a for a in anchors if not (_ROOT / a).exists()]
    assert not missing, (
        f"子处理者清单引用的这些路径在仓库里不存在：{missing} —— "
        "要么文件改名后清单没跟着改，要么锚点是凭印象编的"
    )


def test_subprocessors_page_is_linked_from_the_published_texts() -> None:
    """L8：两份对外文本都要指到子处理者清单，且不得再留着「在线地址」占位符。

    ★ 防的是悬空引用的**反面**：清单文件建好了，对外文本却还写着
      `{{SUBPROCESSOR_LIST_URL}}` 或压根没有链接 ⇒ 客户按政策去查子处理者会落空。
    """
    for name in ("privacy-policy.md", "data-processing-agreement.md"):
        text = _read(name)
        assert "subprocessors.md" in text, (
            f"{name} 没有链接到 subprocessors.md —— 客户按政策去查子处理者清单会落空"
        )
        assert "{{SUBPROCESSOR_LIST_URL}}" not in text, (
            f"{name} 仍留着 {{SUBPROCESSOR_LIST_URL}} 占位 —— "
            "它已由本仓的 docs/legal/subprocessors.md 落地"
        )
