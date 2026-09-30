# -*- coding: utf-8 -*-
"""
第 291 轮 · 一次性补丁：删除资料库「差评处置」入口及其全部消费方。

★ 能力不是被删，是被搬到 ReviewDeskConfig 的「处置台账」第三视图
  （由 `patch_review_desk_ledger.py` 完成）；本脚本只负责**摘掉多余的出口**。

★ 为什么要一并把后端 VIEW_IDS 删了：
  `check-review-library-view.cjs` 的 D3/D4/D5/D6/D7 全是**集合相等**
  （不是包含），少改任何一侧 ⇒ 门禁立刻红。
  而且留着它会让 LLM 以为有个叫「差评处置」的视图可跳 —— 跳过去是空白。

★ 行尾：每个文件各自探测 NL，不做全仓统一假设（本仓 CRLF / LF 混存）。
"""
from pathlib import Path

ROOT = Path(r"D:\ai\eCommerce")
FE = ROOT / "frontend" / "src"
BE = ROOT / "backend"

log: list[str] = []


def load(p: Path) -> tuple[str, str]:
    raw = p.read_bytes().decode("utf-8")
    return raw, ("\r\n" if "\r\n" in raw else "\n")


def apply(tag: str, path: Path, pairs: list, delete: bool = False) -> None:
    global log
    if delete:
        existed = path.exists()
        if existed:
            path.unlink()
        log.append("  DEL  {}  (existed={})".format(path.name, existed))
        return
    raw, nl = load(path)
    src = raw
    for old, new, expect in pairs:
        o = old.replace("\n", nl)
        n = new.replace("\n", nl)
        c = src.count(o)
        assert c == expect, "[{}] count {} != {}: {!r}".format(tag, c, expect, old[:70])
        src = src.replace(o, n, expect)
        log.append("  OK   {:<46} -{}B/+{}B".format(tag, len(o), len(n)))
    path.write_bytes(src.encode("utf-8"))


# ---------------------------------------------------------------- A. 删页面
apply(
    "A 删 DispositionLibrary.vue",
    FE / "components" / "KnowledgeBase" / "DispositionLibrary.vue",
    [],
    delete=True,
)

# ---------------------------------------------------------------- B. Workspace
apply(
    "B1 Workspace 渲染分支",
    FE / "views" / "Workspace.vue",
    [(
        """        <!-- 差评处置视图（第 287 轮；第 8 个资料库：`review_dispositions` 的出口。
             与复盘库不是一回事：复盘是「运营怎么看这个月」，处置是「这条差评后来怎么处理的」。） -->
        <DispositionLibrary v-else-if="currentView === 'dispositions'" />

""",
        "",
        1,
    )],
)
apply(
    "B2 Workspace import + 联合类型 + cast",
    FE / "views" / "Workspace.vue",
    [
        ("import DispositionLibrary from '@/components/KnowledgeBase/DispositionLibrary.vue'\n", "", 1),
        ("| 'dispositions' | 'skills'", "| 'skills'", 2),
    ],
)

# ---------------------------------------------------------------- C. 侧边栏
apply(
    "C1 侧边栏菜单项（留墓碑注释说明搬去了哪）",
    FE / "components" / "Sidebar" / "KnowledgeBase.vue",
    [(
        """      <!-- ★ 第 287 轮：差评处置（第 8 个资料库）。
           与复盘库**不是一回事**：复盘库存「运营周期报告」，本库存「每条差评
           后来怎么处理的」（含补偿、双语回复、券码、谁批的）。
           它按 `X-Shop-ID` 过滤 ⇒ 归属这一组，不进下面「能力」那组。 -->
      <a-menu-item key="dispositions">
        <SolutionOutlined />
        <span>差评处置</span>
      </a-menu-item>
""",
        """      <!-- ★ 第 291 轮：差评处置**从这个分组撤掉** —— 它不是独立的资料库，
           而是「差评处理」这条能力的后半段（批准 / 发放），已并入客服功能栏
           「差评处理」右栏面板的**处置台账**视图。留在这儿的结果是同一个
           不可逆的人审动作在两处都有按钮，HITL 的唯一把关点被架空。
           谁要是想把它加回来，请先去看 `TaskConfigPanel/configs/ReviewDeskConfig.vue`。
           注：删完本组 8 个 key 变 7 个 —— `check-review-library-view.cjs`
           的 B0 判的是「≥7」，正好卡在下界上，再删一个就该改那条门禁了。 -->
""",
        1,
    )],
)
apply(
    "C2 删掉不再被引用的 SolutionOutlined",
    FE / "components" / "Sidebar" / "KnowledgeBase.vue",
    [("  SolutionOutlined,\n", "", 1)],
)

# ---------------------------------------------------------------- D. appActions
apply(
    "D appActions：AppView / VIEW_LABELS / VALID_VIEWS",
    FE / "utils" / "appActions.ts",
    [
        ("  | 'dispositions'\n", "", 1),
        ("  dispositions: '差评处置',\n", "", 1),
        ("'reviews', 'dispositions', 'competitors'", "'reviews', 'competitors'", 1),
    ],
)

# ---------------------------------------------------------------- E. 后端 VIEW_IDS
apply(
    "E 后端 VIEW_IDS",
    BE / "modules" / "secretary" / "navigation_tools.py",
    [(
        """    # ★ 第 287 轮新增 `dispositions`（差评处置，第 8 个资料库）。
    #   它是 `review_dispositions` 的出口：与 `reviews`（复盘库）不是一回事 ——
    #   复盘库存「运营周期报告」，处置库存「这条差评后来怎么处理的」。
    "faq", "candidates", "products", "assets", "rules", "reviews",
    "dispositions", "competitors", "monitor",
""",
        """    # ★ 第 291 轮：`dispositions`（差评处置）**从视图清单撤掉** ——
    #   它不是独立视图，而是「差评处理」这条能力的后半段（批准 / 发放），
    #   已并进客服功能栏「差评处理」右栏面板的**处置台账**。
    #   留在这里的后果有两个：① LLM 以为有个资料库可跳，跳过去是空白；
    #   ② 与前端 `AppView` 集合不等 ⇒ `check-review-library-view.cjs` 的 D5 红。
    "faq", "candidates", "products", "assets", "rules", "reviews",
    "competitors", "monitor",
""",
        1,
    )],
)

# ---------------------------------------------------------------- F. 失效指针
apply(
    "F TaskConfigPanel 注释改指新落点",
    FE / "components" / "TaskConfigPanel" / "index.vue",
    [(
        """      <!-- ★ 差评工作台（第 289 轮 P1）：客服 Agent 功能栏「差评处理」按钮的落点。
           以**差评**为主语（区别于资料库里以**处置**为主语的 DispositionLibrary），
           没有它则「还没处置过的差评」永远不出现在任何界面上。 -->
""",
        """      <!-- ★ 差评工作台（第 289 轮 P1 / 第 291 轮收敛）：客服 Agent 功能栏
           「差评处理」按钮的落点，内含 近期差评 / 未关联产品 / 处置台账 三视图。
           ★★ 它是 approve / reject / issue 这三个**不可逆人审动作的唯一出口**
           —— 资料库那个同名入口（DispositionLibrary）已在第 291 轮删除。
           再加第二个带这些按钮的面板前，先读 ReviewDeskConfig.vue 头部的说明。 -->
""",
        1,
    )],
)

print("patches:")
for line in log:
    print(line)

# ---------------------------------------------------------------- 自检：零残留
print("\n=== 残留自检（必须全为 0）===")
targets = [
    FE / "views" / "Workspace.vue",
    FE / "utils" / "appActions.ts",
    FE / "components" / "Sidebar" / "KnowledgeBase.vue",
    BE / "modules" / "secretary" / "navigation_tools.py",
    FE / "components" / "TaskConfigPanel" / "index.vue",
]
bad = 0
for p in targets:
    t = p.read_bytes().decode("utf-8")
    n = t.count("dispositions") + t.count("DispositionLibrary") + t.count("差评处置")
    flag = "OK  " if n == 0 else "BAD "
    if n:
        bad += 1
    print("  {} {:<52} hits={}".format(flag, p.name, n))
print("  {} DispositionLibrary.vue 已删除 = {}".format(
    "OK  " if not (FE / "components" / "KnowledgeBase" / "DispositionLibrary.vue").exists() else "BAD ",
    not (FE / "components" / "KnowledgeBase" / "DispositionLibrary.vue").exists(),
))
assert bad == 0, "还有残留 —— 门禁的集合相等会立刻转红"
print("\n全部清理干净")
