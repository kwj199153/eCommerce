# -*- coding: utf-8 -*-
r"""
第 291 轮 · 收尾补丁 + 靠谱自检。

★ 为什么要把注释挪出 `VIEW_IDS = [...]`：
  门禁 `check-review-library-view.cjs` 用 `/VIEW_IDS\s*=\s*\[([\s\S]*?)\]/`
  取这段再挑 `"xxx"` 字面量。注释留在列表里 ⇒ 提取窗口里多了垃圾，
  现在靠「注释里写的是反引号而不是双引号」侥幸没事，
  哪天有人把注释里的 `dispositions` 写成 "dispositions" 门禁立刻假绿/假红。

★ 为什么自检要「剥注释后再数」而不是数原文：
  本仓铁律 —— 源码字符串包含会被注释喂饱。墓碑注释**刻意**提到
  `DispositionLibrary` / 差评处置，那是给人看的；门禁看的是**代码形态**。
"""
import re
from pathlib import Path

ROOT = Path(r"D:\ai\eCommerce")
FE = ROOT / "frontend" / "src"
BE = ROOT / "backend"


def load(p: Path):
    raw = p.read_bytes().decode("utf-8")
    return raw, ("\r\n" if "\r\n" in raw else "\n")


# ---------------------------------------------------------------- 挪注释
nav = BE / "modules" / "secretary" / "navigation_tools.py"
src, nl = load(nav)

COMMENT = """    # ★ 第 291 轮：`dispositions`（差评处置）**从视图清单撤掉** ——
    #   它不是独立视图，而是「差评处理」这条能力的后半段（批准 / 发放），
    #   已并进客服功能栏「差评处理」右栏面板的**处置台账**。
    #   留在这里的后果有两个：① LLM 以为有个资料库可跳，跳过去是空白；
    #   ② 与前端 `AppView` 集合不等 ⇒ `check-review-library-view.cjs` 的 D5 红。
""".replace("\n", nl)
assert src.count(COMMENT) == 1, "墓碑注释未找到（count={}）".format(src.count(COMMENT))
src = src.replace(COMMENT, "", 1)

ANCHOR = "VIEW_IDS = [\n".replace("\n", nl)
assert src.count(ANCHOR) == 1, "VIEW_IDS 锚点未找到"

# ★ 注释放在 `VIEW_IDS = [` **之前**：提取窗口 /\[([\s\S]*?)\]/ 只到 `]`，
#   注释在窗外 ⇒ 无论注释里怎么写引号都不会污染集合。
NEW_HEAD = (ANCHOR + COMMENT).replace(
    COMMENT, COMMENT.replace("^", "")
)
# 逐行缩进出：注释原本是列表内缩进（4 空格），挪到顶层保持同样缩进即可
src = src.replace(ANCHOR, ANCHOR + COMMENT, 1)
nav.write_bytes(src.encode("utf-8"))
print("已在 VIEW_IDS 列表外挪好墓碑注释")

# ---------------------------------------------------------------- 剥注释自检
def code(t: str, lang: str = "js") -> str:
    t = re.sub(r"<!--[\s\S]*?-->", "", t)
    t = re.sub(r"/\*[\s\S]*?\*/", "", t)
    if lang == "py":
        t = re.sub(r"#[^\n]*", "", t)
    else:
        t = re.sub(r"//[^\n]*", "", t)
    return t


targets = [
    (FE / "views" / "Workspace.vue", "js"),
    (FE / "utils" / "appActions.ts", "js"),
    (FE / "components" / "Sidebar" / "KnowledgeBase.vue", "js"),
    (FE / "components" / "TaskConfigPanel" / "index.vue", "js"),
    (FE / "components" / "TaskConfigPanel" / "configs" / "ReviewDeskConfig.vue", "js"),
    (BE / "modules" / "secretary" / "navigation_tools.py", "py"),
]

print("\n=== 代码层残留自检（剥注释后，必须全为 0）===")
bad = 0
for p, lang in targets:
    t = code(p.read_bytes().decode("utf-8"), lang)
    n = t.count("dispositions") + t.count("DispositionLibrary") + t.count("差评处置")
    if n:
        bad += 1
    print("  {} {:<40} code_hits={}".format("OK  " if n == 0 else "BAD ", p.name, n))

print("\n=== 注释层残留（刻意保留的墓碑，给人看）===")
for p, lang in targets:
    raw = p.read_bytes().decode("utf-8")
    n = (raw.count("dispositions") + raw.count("DispositionLibrary")
         + raw.count("差评处置") - code(raw, lang).count("dispositions")
         - code(raw, lang).count("DispositionLibrary") - code(raw, lang).count("差评处置"))
    if n:
        print("  note {:<38} comment_hits={}".format(p.name, n))

gone = not (FE / "components" / "KnowledgeBase" / "DispositionLibrary.vue").exists()
print("\nDispositionLibrary.vue 已删除 =", gone)

# ---- 真正的判据：**写动作出口数**（比「代码里有没有这个词」可靠得多）
print("\n=== 核心判据：approve/reject/issue 被多少个 .vue import ===")
vues = sorted((FE).rglob("*.vue"))
hits = {}
for name in ("approveDisposition", "rejectDisposition", "issueDisposition"):
    owners = []
    for v in vues:
        body = code(v.read_bytes().decode("utf-8"), "js")
        if re.search(r"^\s*%s,?\s*$" % name, body, re.M) or re.search(
            r"import[^;]*\b%s\b" % name, body
        ):
            owners.append(v.relative_to(FE).as_posix())
    hits[name] = owners
    print("  {} -> {} 处: {}".format(name, len(owners), owners))
    if len(owners) != 1:
        bad += 1
print("\nRESULT:", "FAIL" if bad else "PASS")
