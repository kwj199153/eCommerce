# -*- coding: utf-8 -*-
"""
第 291 轮 · 收尾补丁（真漂移修复 + 门禁加固）

★ 为什么会有这份补丁：同一件事在后端有**两份清单** ——
    · `VIEW_IDS`（运行时清单，`check-review-library-view.cjs` 的 D5 判它）
    · `ViewId = Literal[...]`（**工具签名**，LLM 只能从这里取值）
  而现有门禁只判前者 ⇒ 本轮删 `dispositions` 时只改了前者，后者静止留着，
  LLM 签名里依然写着「可以跳到差评处置」，跳过去是空白，**零报错**。

本脚本做三件事：
  P1 把墓碑注释挪到 `VIEW_IDS = [` 之前（脱离门取的提取窗口）；
  P2 从 `ViewId` Literal 里同步删掉 `"dispositions"`；
  P3 在门禁里加 D8：`VIEW_IDS == ViewId Literal`（集合相等）+ B0k 自检。

★ 插入位置一律用「行定位」而不是多行大文本匹配 —— 后者在行尾/空格变化时
  会静默失配（症状是"补丁说没跑"，方向错很远）。
"""
from pathlib import Path

ROOT = Path(r"D:\ai\eCommerce")
BE = ROOT / "backend"
nav = BE / "modules" / "secretary" / "navigation_tools.py"
gate = ROOT / "frontend" / "scripts" / "check-review-library-view.cjs"


def load(p: Path):
    raw = p.read_bytes().decode("utf-8")
    return raw.splitlines(keepends=True), ("\r\n" if "\r\n" in raw else "\n")


def save(p: Path, lines):
    p.write_bytes("".join(lines).encode("utf-8"))


def find_line(lines, needle, expect=1):
    idx = [i for i, ln in enumerate(lines) if needle in ln]
    assert len(idx) == expect, "锚点 %r 命中 %d 次（期望 %d）" % (needle, len(idx), expect)
    return idx[0]


# ============================================================ P1 墓碑注释挪位
lines, nl = load(nav)
tomb_head = find_line(lines, "★ 第 291 轮：`dispositions`")
tomb_tail = tomb_head
while "D5 红" not in lines[tomb_tail]:
    tomb_tail += 1
tomb = lines[tomb_head : tomb_tail + 1]
del lines[tomb_head : tomb_tail + 1]

vid = find_line(lines, "VIEW_IDS = [")
# ★ 注释放在列表**之前**：门取的提取窗口是 /VIEW_IDS\s*=\s*\[([\s\S]*?)\]/，
#   注释在窗外 ⇒ 将来注释里怎么写引号都不会污染集合
lines[vid:vid] = tomb
save(nav, lines)
print("P1 墓碑注释已挪到 VIEW_IDS 之前（%d 行）" % len(tomb))

# ============================================================ P2 ViewId Literal
lines, nl = load(nav)
i = find_line(lines, '"dispositions", "competitors", "monitor",')
assert "ViewId" in "".join(lines[max(0, i - 4) : i + 2]), "这行不在 ViewId Literal 里，别误删"
lines[i] = lines[i].replace('"dispositions", ', "")
save(nav, lines)
print("P2 ViewId Literal 已同步删除 dispositions ->", lines[i].rstrip())

# ============================================================ P3 门禁加固
lines, nl = load(gate)

# 3a 在 beViewIds 抽取块之后插 ViewId Literal 抽取
bidx = find_line(lines, "const beViewIds = ")
j = bidx
while lines[j].strip() != ": []":
    j += 1
extract = [
    "\n",
    "const beViewIdTypes = /ViewId\\s*=\\s*Literal\\[([\\s\\S]*?)\\]/.exec(navPy)\n",
    "  ? [.../ViewId\\s*=\\s*Literal\\[([\\s\\S]*?)\\]/.exec(navPy)[1].matchAll(/\"([a-z_]+)\"/g)].map(\n",
    "      (m) => m[1]\n",
    "    )\n",
    "  : []\n",
]
insert_at = j + 1
lines[insert_at:insert_at] = [s.replace("\n", nl) for s in extract]

# 3b B0 自检：必须证明抽取没落空（否则 D8 会在两个空集上恒真）
anchor = find_line(lines, "'B0h 解析出后端 VIEW_IDS（≥7）'")
b0k = "check(beViewIdTypes.length >= 8, 'B0k 解析出后端 ViewId Literal（≥8）', JSON.stringify(beViewIdTypes))\n"
lines.insert(anchor + 1, b0k.replace("\n", nl))

# 3c D8 判据：插在 D5 之后
d5 = find_line(lines, "`后端=${JSON.stringify(uniq(beViewIds))}")
assert "AppView" in lines[d5] or "前端=" in lines[d5], lines[d5][:80]
d8 = [
    "\n",
    "check(eq(beViewIds, beViewIdTypes),\n",
    "  'D8 后端 VIEW_IDS == ViewId Literal（运行时清单 == LLM 工具签名，集合相等）',\n",
    "  `VIEW_IDS=${JSON.stringify(uniq(beViewIds))} ViewId=${JSON.stringify(uniq(beViewIdTypes))}",
    " —— 两者漂移 ⇒ LLM 能产出「跳到差评处置」，而那个视图已经不存在，跳过去是空白且零报错`)\n",
]
lines[d5 + 1 : d5 + 1] = [s.replace("\n", nl) for s in d8]

save(gate, lines)
print("P3 门禁已加 B0k + D8")

# ============================================================ 落盘复核
txt = "".join(load(nav)[0])
print("\n--- navigation_tools.py VIEW_IDS 段 ---")
start = txt.index("VIEW_IDS = [")
print(txt[start - 40 : txt.index("]", txt.index('"monitor"', start)) + 1])
