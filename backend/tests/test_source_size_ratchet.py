"""文件体量棘轮 —— 生产源码超阈值清单**只许降、不许升**（第 356 轮）。

━━━ 为什么需要 ━━━
`docs/reviews/2026-10-01-第353轮-项目复审.md` §P3 记着「生产源码 >800 行 **50 个**」，
但**全仓没有任何门禁钉住它**（实测：`grep -rn "max_lines|LOC|体量" backend/tests frontend/scripts`
命中的全是随机数棘轮 / 字段契约，没有一条管行数）。

后果是明确的：本轮刚拆掉 `trade/service.py`（2535 → 9 文件）与
`customer_service/agent_cs.py`（1992 → 8 文件）—— **拆完就没人拦着它长回去**。
棘轮要解决的问题就是「把当前基线冻住，只留下降通道」。

━━━ 口径（显式，否则读数不可比）━━━
只算**生产源码**：
  · `backend/**/*.py`，排除 `tests/` · `scripts/` · `.venv/` · `__pycache__/`
  · `frontend/src/**/*.{ts,vue}`，排除 `mock/`

★ 为什么排除测试与 mock：它们体量大是**正常**的（单文件塞几十条用例），
  纳进来会让棘轮变成噪音，最后被整个关掉 —— 那就等于没有棘轮。
  （`frontend/src/mock/` 的两份大文件是独立议题，见 353 轮 §6「决策 C」。）

━━━ 判据（五红一提示）━━━
  R1 **新增越限**：扫描出的超阈值文件集合 ⊆ 冻结表（新文件超线 ⇒ 红）
  R2 **恶化**：冻结表里仍在磁盘的每个文件，实际行数 <= 冻结值（长回去 ⇒ 红）
  R3 **自检·扫描面**：哨兵文件必须被扫到（后缀过滤 / 排除规则写坏 ⇒ 红）
  R4 **自检·冻结表**：表非空，且每项的值都 > 阈值（防塞 0 值把 R2 变成恒真）
  R5 **冻结项存在**：路径写错 / 文件被删 ⇒ 红
  H1 **陈旧项**（只打印，不红）：已降到阈值以下的冻结项 —— 建议移出表

★ 为什么 R1 与 R5 都要有：R1 抓「新的越限文件」（含**改名** —— 新名字不在表里
  且超限 ⇒ 红）；R5 抓「基线表腐烂」（文件没了、路径写错）。两条互补，缺一会留洞。

★★ 为什么 R5 会是**引导式红**，不是障碍：把一个文件**合法拆成包**之后，
  原文件消失 ⇒ R5 红 ⇒ 提示你把它从冻结表删掉并同步本节注释。
  这是**有意的**：一张会撒谎的基线表比没有基线更糟。

━━━ 已知边界（如实登记，不写成断言）━━━
  · 本门禁只管**行数**。「模板复制」是另一个维度（体量不大、重复度高），
    不在本判据覆盖内。★ 第 356 轮把该维度的**现状与承载判据**登记如下
    （改这两处符号前先看对应判据，别只数份数）：
      – `_dump`：8 份 → **4 份**。5 个「三态版」已收口到唯一真源
        `ai_infra/tools/serialization.py::dump_result`（5 个消费方均写
        `... import dump_result as _dump`）；剩 `aigc_media`（两态）与
        `library` / `trade`（单行）**有意不收** —— 统一会改变工具回给 LLM
        的字符串；行为对照表见 `ai_infra/tools/serialization.py` 模块 docstring。
        判据：`tests/test_tool_result_serialization.py`。
      – `_get_router`：仍 **7 份**，**有意不收进基类** —— 理由见
        `modules/product_research/agent_routing.py` 模块 docstring
        （「藏进基类只会让耦合从『可以数的参数』变成『看不见的继承链』」）。
        改为加**一致性门禁** `tests/test_agent_router_getter_uniform.py`：
        钉「7 份函数体逐字相同（docstring 除外）」，防漂移而不牺牲可数性。
  · `.vue` 行数**不可跨格式化版本比**（353 轮已记：F-2 格式化让
    `ReviewDeskConfig.vue` 从真码 1692 变成 2002 行）。
  · 阈值 800 沿用的是 353 轮既有口径，不是本轮新定的。

━━━ 反向注入（证明它真有牙齿）━━━
  见 `.workbuddy/probes/r356/inject_size_ratchet.py`：四组（新增越限 / 恶化 /
  冻结项消失 / 冻结表塞 0 值）+ 一组「期望保持绿」的反例。
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

#: 既有口径（353 轮复审 §P3 用的就是 >800 行）
THRESHOLD = 800


class StaleRatchetEntry(UserWarning):
    """棘轮表里有「已降到阈值以下」的项 —— **提示，不是失败**（见 H1）。

    ★ 为什么用 `warnings` 而不是 `print`：本仓 CI 的 ruff 棘轮只跑
      `--select T20`（禁 `print`），而 `tests/**` 的整体豁免里**没有** T201
      （只有按理由**单文件**豁免的个别文件，见 `pyproject.toml` 的 `per-file-ignores`）。
      更实际的原因是 **pytest 会捕获 stdout**：一条**通过**的用例里
      `print` 出来的东西在正常跑时**根本不可见** —— 那份「提示」等于没写。
      `warnings` 会进 pytest 的 warnings summary，是**真的看得见**的通道，
      且不改变用例结果（仍是 pass，不是 skip）。
    """

#: 冻结基线 —— 语义是**上限**（只许降不许升）。
#:
#: ★ 这张表**从实测产物逐字复制**，不是凭记忆手写。
#:   复现命令（在仓库根跑）：
#:       python .workbuddy/probes/r356/gen_size_ratchet_table.py
#:   ★ 下次改动本表（拆包后下调 / 新文件入列）时，**必须重跑上面这条命令**，
#:     不要手改单个数字 —— 手改正是「期望值靠记忆」的来源。
FROZEN_OVER_THRESHOLD: dict[str, int] = {
    "frontend/src/components/KnowledgeBase/ProductLibrary.vue": 2908,
    "frontend/src/components/KnowledgeBase/PlatformRules.vue": 2259,
    "backend/modules/skills/seed.py": 2086,
    "frontend/src/components/TaskConfigPanel/configs/ReviewDeskConfig.vue": 2002,
    "frontend/src/views/Subscription.vue": 1859,
    "backend/modules/aigc_media/agent_aigc.py": 1849,
    "backend/ai_infra/base_agent.py": 1847,
    "backend/modules/listing_generator/agent_listing.py": 1803,
    "backend/modules/product_research/agent_product_research.py": 1641,
    "backend/modules/competitor_intel/agent_competitor.py": 1577,
    "frontend/src/components/SkillStore/SkillManager.vue": 1533,
    "frontend/src/views/Workspace.vue": 1466,
    "frontend/src/components/KnowledgeBase/AssetLibrary.vue": 1440,
    "backend/modules/ad_analysis/agent_ad.py": 1366,
    "frontend/src/components/ChatPanel/results/BlueOceanResult.vue": 1324,
    "frontend/src/views/Settings.vue": 1315,
    "frontend/src/components/KnowledgeBase/CandidateLibrary.vue": 1230,
    "backend/modules/stores/router.py": 1221,
    "frontend/src/components/ChatPanel/index.vue": 1220,
    "frontend/src/components/ChatPanel/results/AIGCMediaResult.vue": 1208,
    "frontend/src/components/TaskConfigPanel/configs/VideoGeneratorConfig.vue": 1196,
    "frontend/src/components/Sidebar/AccountMenu.vue": 1188,
    "frontend/src/components/KnowledgeBase/FaqKnowledgeBase.vue": 1135,
    "frontend/src/components/TaskConfigPanel/configs/IntelBoardConfig.vue": 1012,
    "frontend/src/components/TaskConfigPanel/configs/AdDashboardConfig.vue": 1003,
    "frontend/src/stores/productLibrary.ts": 977,
    "frontend/src/components/Settings/VoiceClonePanel.vue": 971,
    "frontend/src/components/KnowledgeBase/ReviewLibrary.vue": 966,
    "frontend/src/components/ToolStore/ToolManager.vue": 950,
    "frontend/src/components/KnowledgeBase/MonitorPoolLibrary.vue": 945,
    "frontend/src/components/TaskConfigPanel/configs/ProfitConfig.vue": 941,
    "frontend/src/components/ChatPanel/results/TitleGenerator.vue": 937,
    "backend/platforms/amazon/client.py": 933,
    "backend/core/config.py": 929,
    "backend/core/auth/accounts.py": 928,
    "frontend/src/views/Login.vue": 922,
    "frontend/src/views/MemoryEvolution.vue": 918,
    "backend/modules/trade/risk_scan.py": 907,
    "backend/modules/skills/tools_catalog.py": 893,
    "frontend/src/components/TaskConfigPanel/configs/StaticAssetConfig.vue": 889,
    "frontend/src/components/TaskConfigPanel/configs/ReviewConfig.vue": 880,
    "backend/alembic/versions/0d44a915bbb8_baseline_full_schema_squashed.py": 875,
    "frontend/src/components/ChatPanel/results/DescriptionGenerator.vue": 869,
    "backend/modules/library/tools.py": 852,
    "backend/modules/aigc_media/router.py": 843,
    "backend/ai_infra/rag/hybrid_engine.py": 842,
    "frontend/src/stores/skills.ts": 824,
    "backend/ai_infra/llm/dashscope_client.py": 818,
}

#: 自检哨兵：这几个文件必然存在、且必然 < 阈值（不会进冻结表）。
#: 判据 = 「它们必须出现在扫描结果里」—— 后缀过滤 / 排除规则写坏时它们会消失。
#: ★ 用**锚点文件**而不是「文件数 >= N」：后者是手写期望，前者钉的是**扫描能力**。
SCAN_SENTINELS = (
    "backend/main.py",
    "frontend/src/main.ts",
)


@lru_cache(maxsize=1)
def _sources() -> dict[str, int]:
    """→ {仓库相对路径: 行数}，只含生产源码（口径见模块 docstring）。

    ★ `lru_cache` 不是过早优化：6 个用例各自调用一次会把全仓扫 6 遍
      （实测 7.4s → 1.2s）。门禁跑得慢就不会被留着跑，这是实际取舍。
      返回值只读，调用方一律不修改。

    行数口径 = 字节流按 `\\n` 切分的段数。★ 与生成器
    `gen_size_ratchet_table.py` **必须逐字相同** —— 两处口径一旦分叉，
    冻结表就会莫名其妙地全红（同族教训：「基线与现测同口径」）。
    """
    out: dict[str, int] = {}
    for p in (BACKEND).rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        # ★ **前缀式**排除 pytest basetemp（本仓约定 `--basetemp=.pytest-tmp-<tag>`）。
        #   ① 不能写成精确匹配（`".pytest-tmp" in p.parts`）：basetemp 实际叫
        #      `.pytest-tmp-r356` 这种 ⇒ 精确匹配**匹配不到**，看着修好了实则无效（r354 教训）。
        #   ② 不排除的后果**不是报错而是假红**：门禁自己的元测试（`test_ci_gate_coverage.py`）
        #      会往 basetemp 写 .py 夹具，那些文件一旦 >800 行就会撞 R1「新增越限」。
        #   判据由 `tests/test_ci_gate_coverage.py::test_backend_scanning_gates_exclude_pytest_basetemp` 守着。
        if any(part.startswith(".pytest-tmp") for part in p.parts):
            continue
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith(("backend/tests/", "backend/scripts/")):
            continue
        out[rel] = len(p.read_bytes().split(b"\n"))
    for p in (REPO / "frontend" / "src").rglob("*"):
        if not p.is_file() or p.suffix not in (".ts", ".vue"):
            continue
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith("frontend/src/mock/"):
            continue
        out[rel] = len(p.read_bytes().split(b"\n"))
    return out


def _oversized(live: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in live.items() if v > THRESHOLD}


def test_scan_face_is_not_vacuous() -> None:
    """R3 自检：扫描面必须真的扫到东西（防「空集恒绿」）。"""
    live = _sources()
    assert len(live) >= 100, f"只扫到 {len(live)} 个文件，扫描面可疑（后缀过滤写坏了？）"
    missing = [s for s in SCAN_SENTINELS if s not in live]
    assert not missing, (
        f"哨兵文件没被扫到：{missing} —— 说明扫描面已经失效，"
        "本门禁的其余判据都在**空跑**（这正是最危险的形态：全绿但什么也没查）。"
    )


def test_frozen_table_is_well_formed() -> None:
    """R4 自检：冻结表非空，且每项的值都 > 阈值（防塞 0 值把「恶化」判成恒真）。"""
    assert FROZEN_OVER_THRESHOLD, "冻结表是空的 —— 本门禁退化成恒真"
    bogus = sorted(k for k, v in FROZEN_OVER_THRESHOLD.items() if v <= THRESHOLD)
    assert not bogus, (
        f"冻结表里有 {len(bogus)} 项的值 <= 阈值 {THRESHOLD}：{bogus[:5]}\n"
        "      （塞一个不大于阈值的值进来，等于给「文件长大」发了许可证）"
    )


def test_no_new_oversized_source() -> None:
    """R1：不许有新的超阈值文件（含**改名** —— 新名字同样会被这条抓住）。"""
    live = _oversized(_sources())
    new = sorted(k for k in live if k not in FROZEN_OVER_THRESHOLD)
    assert not new, (
        f"出现 {len(new)} 个新的超阈值（>{THRESHOLD} 行）文件：\n  "
        + "\n  ".join(f"{k}  {live[k]} 行" for k in new[:10])
        + "\n      ⇒ 请拆到阈值以下；若确有理由保留，必须在**同一提交**里"
        "把它登记进 FROZEN_OVER_THRESHOLD 并写下理由（棘轮只许有据地放松）。"
    )


def test_no_source_grew() -> None:
    """R2：冻结表里的文件只许变短，不许变长。"""
    live = _sources()
    grew = []
    for rel, cap in FROZEN_OVER_THRESHOLD.items():
        now = live.get(rel)
        if now is not None and now > cap:
            grew.append((rel, cap, now))
    assert not grew, (
        f"{len(grew)} 个已超阈值的文件**又长大了**：\n  "
        + "\n  ".join(f"{r}  {c} → {n}（+{n - c}）" for r, c, n in sorted(grew)[:10])
        + "\n      ⇒ 棘轮语义是「只许降不许升」：请拆出独立模块，而不是继续往上加。"
    )


def test_frozen_entries_still_exist() -> None:
    """R5：冻结项必须仍在磁盘上（路径写错 / 文件被删 / 已被拆成包）。

    ★ 这条**刻意**在「合法拆包」后报红 —— 它要的是你**同步基线表**，
      而不是容忍一张会撒谎的表。若你这个文件已拆成包，请从
      FROZEN_OVER_THRESHOLD 里删掉它（重跑生成器即可）。
    """
    live = _sources()
    gone = sorted(k for k in FROZEN_OVER_THRESHOLD if k not in live)
    assert not gone, (
        f"冻结表里有 {len(gone)} 项在磁盘上找不到了：\n  " + "\n  ".join(gone[:10])
        + "\n      ⇒ 可能已拆成包 / 已改名 / 已被删。请重跑\n"
        "        `python .workbuddy/probes/r356/gen_size_ratchet_table.py`\n"
        "        用实测产物替换整张表（不要手改单行）。"
    )


def test_report_stale_entries() -> None:
    """H1：已降到阈值以下的冻结项 —— **只提示，不红**（棘轮允许你赢）。"""
    live = _sources()
    stale = sorted(
        (r, cap, live[r])
        for r, cap in FROZEN_OVER_THRESHOLD.items()
        if r in live and live[r] <= THRESHOLD
    )
    if stale:
        warnings.warn(
            "%d 项已降到阈值 %d 以下，可移出冻结表：\n    %s"
            % (len(stale), THRESHOLD,
               "\n    ".join(f"{r}  {cap} → {now}" for r, cap, now in stale)),
            StaleRatchetEntry,
            stacklevel=2,
        )
    # 恒真：本用例的产出是**提示**，不是判据
    assert True
