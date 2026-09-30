# -*- coding: utf-8 -*-
"""
第 291 轮 · 给「差评处理」接宽看板 / 双模式（对话模式 / 大屏模式）。

★ 为什么是**工具级**而不是 Agent 级（这点与 AIGC 相反，是本轮的判断点）：
  AIGC 是 Agent 级 —— 点 AIGC Agent 就该看到「对话/大屏」，因为它三个工具都是
  内容生成，大屏是主形态。而**客服的主形态是聊天**，进去就挂一个「大屏」开关
  是干扰；只有真的选中了「差评处理」（里面躺着一张 8 列的处置台账）才需要宽度。
  ⇒ 这里用 `currentSelectedTool` 收窄到具体工具，与 `isWideProfitTool` 同源。

★ 为什么复用 `review-data-mode` 而不是新写一套布局：
  那条 CSS 就是「对话收窄 400 + 右栏撑开」，台账要的正是这个；
  新写一套等于把同一条布局规则复制第二份（本仓铁律）。

★ 两种范式并存，别混：
  · `isWideProfitTool` —— 只加宽到 528，**无**双模式；
  · `hasWideBoard`     —— 加宽 + 顶栏 mode-switch + 整页看板（本轮加的成员）。
"""
from pathlib import Path

WS = Path(r"D:\ai\eCommerce\frontend\src\views\Workspace.vue")
raw = WS.read_bytes().decode("utf-8")
NL = "\r\n" if "\r\n" in raw else "\n"
src = raw
log = []


def rep(tag, old, new, expect=1):
    global src
    o = old.replace("\n", NL)
    n = new.replace("\n", NL)
    c = src.count(o)
    assert c == expect, "[{}] count {} != {}: {!r}".format(tag, c, expect, old[:70])
    src = src.replace(o, n, expect)
    log.append("  OK  {}".format(tag))


# ---------------------------------------------------------------- 1 新增 computed
rep(
    "1 isReviewDeskTool + hasWideBoard",
    """// 需要「宽看板」场景（复盘 / Listing / 广告 / 竞品监控 / AIGC）
""",
    """// ★ 第 291 轮：差评工作台（智能客服 → 差评处理）—— **工具级**宽看板。
//   里面第三个视图「处置台账」是 8 列表格（SKU / 评分 / 标题 / 通道 / 补偿 /
//   状态 / 更新 / 操作），340 与 528 都放不下 ⇒ 需要对话模式与大屏模式。
//   ★ 为什么不像 AIGC 那样做成 Agent 级：客服的主形态是聊天，点进去就挂一个
//     「大屏」开关是干扰；只有真的选中这个工具才需要。这与利润测算
//     （`isWideProfitTool`）的粒度一致，区别是它还要**双模式**而不只是加宽。
const isReviewDeskTool = computed(
  () =>
    currentAgent.value?.id === 'customer-service' &&
    currentSelectedTool.value?.id === 'review-desk'
)

// 需要「宽看板」场景（复盘 / Listing / 广告 / 竞品监控 / AIGC / 差评处理）
""",
)

rep(
    "2 hasWideBoard 汇总",
    """    isCompetitorIntelAgent.value ||
    isAigcAgent.value
)
""",
    """    isCompetitorIntelAgent.value ||
    isAigcAgent.value
)

// 是否拥有「对话模式 / 大屏模式」这套能力 —— 上面那五个是 Agent 级，
// 差评处理是工具级，两者汇总后给右侧的「是否被 hook 到双模式」用。
// ★ 不能把 `isReviewDeskTool` 直接并进 `isWideBoardAgent`：那个名字与其注释
//   明写「需要宽看板场景」是 **Agent 级**判定，混进工具级会让名字说谎。
const hasWideBoard = computed(() => isWideBoardAgent.value || isReviewDeskTool.value)
""",
)

# ---------------------------------------------------------------- 3 宽度 + 双模式改用汇总值
rep(
    "3 isWidePanel 加宽",
    """const isWidePanel = computed(
  () => isWideBoardAgent.value || isWideProfitTool.value
)""",
    """const isWidePanel = computed(
  () => isWideBoardAgent.value || isWideProfitTool.value || isReviewDeskTool.value
)""",
)

rep(
    "4 isReviewDataMode 改用 hasWideBoard",
    """const isReviewDataMode = computed(
  () => isWideBoardAgent.value && reviewMode.value === 'data' && !rightPanelCollapsed.value
)""",
    """const isReviewDataMode = computed(
  () => hasWideBoard.value && reviewMode.value === 'data' && !rightPanelCollapsed.value
)""",
)

# ---------------------------------------------------------------- 5 模板
rep(
    "5 mode-switch 显隐",
    """          <!-- 宽看板场景（复盘 / Listing / 广告 / 竞品监控 / AIGC）：双模式切换（对话模式 / 大屏模式；Listing 为文案模式）
               利润测算**不进**：它是工具级加宽（528），无大屏模式（详见 isWideProfitTool 注释）。 -->
          <div v-if="isWideBoardAgent && currentView === 'chat'" class="mode-switch">""",
    """          <!-- 宽看板场景（复盘 / Listing / 广告 / 竞品监控 / AIGC / 差评处理）：
               双模式切换（对话模式 / 大屏模式；Listing 为文案模式）
               利润测算**不进**：它是工具级加宽（528），无大屏模式（详见 isWideProfitTool 注释）。
               差评处理**进**：同样是工具级，但台账是 8 列表格，528 不够 ⇒ 要双模式
               （它不是 Agent 级 ⇒ 只在选中该工具时出现，见 isReviewDeskTool）。 -->
          <div v-if="hasWideBoard && currentView === 'chat'" class="mode-switch">""",
)

rep(
    "6 大屏模式下隐藏工具按钮（差评处理同款）",
    """            <template v-if="!isSecretaryAgent && !isCompetitorIntelAgent && !(isReviewAgent && reviewMode === 'data') && !(isAdAnalyst && reviewMode === 'data') && !(isAigcAgent && reviewMode === 'data')">""",
    """            <template v-if="!isSecretaryAgent && !isCompetitorIntelAgent && !(isReviewAgent && reviewMode === 'data') && !(isAdAnalyst && reviewMode === 'data') && !(isAigcAgent && reviewMode === 'data') && !(isReviewDeskTool && reviewMode === 'data')">""",
)

WS.write_bytes(src.encode("utf-8"))
print("Workspace.vue patches:")
for l in log:
    print(l)

# ---------------------------------------------------------------- 自检
after = WS.read_bytes().decode("utf-8")
print("\n=== 自检 ===")
for needle, want in [
    ("isReviewDeskTool", 4),   # 定义 + isWidePanel + hasWideBoard + 模板
    ("hasWideBoard", 3),       # 定义(+注释) + isReviewDataMode + 模板
    ("isWideBoardAgent", 3),   # 定义体 + isWidePanel + hasWideBoard
]:
    n = after.count(needle)
    print("  {:<22} x{} (期望 {}) {}".format(needle, n, want, "OK" if n == want else "CHECK"))
print("  CRLF:", after.count("\r\n"), " lines:", after.count("\n"))
