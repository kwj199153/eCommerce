# -*- coding: utf-8 -*-
"""主题变量引用门禁 —— 「引用了不存在的 CSS 变量」必须红。

为什么值得单独一个门禁
====================
本仓主题色变量真源 = `src/theme/presets.ts` 的 `LIGHT_VARS` / `DARK_VARS`
（闭集 71 键；`ThemeVars` 类型保证**表内**一个都不缺）。但闭集只管**生产者**——
消费者侧写的 `var(--名字)` 只是个**裸字符串**，没有任何类型约束。

名字一旦写错（或照抄了主题改造前的旧变量表），发生的是**静默降级**：

    background: var(--bg-layout, #fafafa);   ← --bg-layout 在闭集里不存在
    color:      var(--text-secondary);       ← 深色下 = rgba(255,255,255,.65)

⇒ 底色永远取**浅色** fallback，文字却是深色主题的**白色** ⇒ 白底白字。

第 244 轮实锤（老板截图报的）：`Settings/VoiceClonePanel.vue` 的「跟读稿区」
与「授权条款区」在深色模式下**完全看不见字**，根因就是这一条；全仓同类共 9 处。
更狠的是**不写 fallback** 的那两个：`var(--space-32)` / `var(--border-secondary)`
会让 `padding` / `border` **整条声明失效**（空态挤成一团 / 虚线框消失）。

这类缺陷的形态特征与 `check-theme-boot.py` 要防的一模一样 ——
类型系统不报、`vite build` 不报、单测不报，只在**特定主题 + 特定屏幕**上
被人眼发现。⇒ 必须有一条能对它说不的静态断言。

与相邻门禁的分工
==============
  · `check-theme-boot.py` —— 主题**清单 / 首帧兜底色**跨文件一致（生产者侧）
  · 本门禁 —— 组件里 `var()` **引用的名字是否真实存在**（消费者侧）
互补：前者管「表里的值有没有抄错」，后者管「引用的名字有没有写错」。

怎么跑
======
  python scripts/check-theme-var-refs.py            做判定（有未定义 ⇒ 退出码 1）
  python scripts/check-theme-var-refs.py --report   只打印盘面读数、不判定

CI：`.github/workflows/ci.yml` 用 glob `scripts/check-*.*` 逐个执行 ⇒ 本文件自动纳入。

反向注入（证明本门禁不是空跑）
============================
扫描根可用环境变量指向**副本树**，于是能在不改工作区的前提下逐条打穿：
  THEME_SRC_ROOT=<副本 src 目录>
见 `.workbuddy/probes/tools/r244_gate_reverse.py`（4 条注入 + 1 条对照）。
"""
import io
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                   # frontend/
SRC = Path(os.environ.get("THEME_SRC_ROOT") or (ROOT / "src"))
PRESETS = ROOT / "src" / "theme" / "presets.ts"
APP = ROOT / "src" / "App.vue"
HTML = ROOT / "index.html"

REPORT_ONLY = "--report" in sys.argv

# 只剥**块注释 / HTML 注释 / 行首行注释**：
#   · 必须剥，否则文档里当示例写的 `var(--x)` 会被当成真引用（实测 2 处误报）
#   · 不处理行内 `//`（避免把 `https://` 里的 `//` 当注释起点而砍掉整行）
BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
LINE_COMMENT = re.compile(r"^[ \t]*//[^\n]*$", re.M)

REF = re.compile(r"var\(\s*(--[a-z0-9-]+)")
SCAN_SUFFIXES = ("*.vue", "*.css", "*.ts", "*.js")


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def vars_of(text, const_name):
    """从 `const X: T = { ... }` 里抽变量名（与 check-theme-boot.py 同口径）"""
    i = text.index("const %s" % const_name)
    j = text.index("\n}", i)
    return set(re.findall(r"'(--[a-z0-9-]+)':", text[i:j]))


def css_vars(text):
    """抽 `--名字:` 形式的声明（`:root` 块 / index.html 内联兜底都适用）"""
    return {"--" + k for k in re.findall(r"--([a-z0-9-]+)\s*:", text)}


presets = read(PRESETS)
app = read(APP)
html = read(HTML)

# 变量名权威全集 = 主题色两表 ∪ App.vue :root 尺度变量 ∪ index.html 首屏兜底
known = set()
known |= vars_of(presets, "LIGHT_VARS")
known |= vars_of(presets, "DARK_VARS")
i = app.index(":root {")
known |= css_vars(app[i: app.index("\n}", i)])
known |= css_vars(html)

files = sorted({p for s in SCAN_SUFFIXES for p in SRC.rglob(s)})
undef = {}
ref_names = set()
for p in files:
    body = read(p)
    body = BLOCK_COMMENT.sub(" ", body)
    body = HTML_COMMENT.sub(" ", body)
    body = LINE_COMMENT.sub("", body)
    for ln, line in enumerate(body.split("\n"), 1):
        for m in REF.finditer(line):
            name = m.group(1)
            ref_names.add(name)
            if name not in known:
                undef.setdefault(name, []).append(
                    ("%s:%d" % (p.relative_to(SRC).as_posix(), ln))
                )

if REPORT_ONLY:
    print("定义全集 = %d 个变量名" % len(known))
    print("扫描面   = %d 个文件；被引用的变量名 = %d 个" % (len(files), len(ref_names)))
    print("未定义引用 = %d 个变量 / %d 处" % (len(undef), sum(len(v) for v in undef.values())))
    for k in sorted(undef):
        print("  %-24s %d 处  %s" % (k, len(undef[k]), ", ".join(undef[k][:3])))
    sys.exit(0)

fails = []


def check(ok, label):
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        fails.append(label)


print("=== 主题变量引用门禁（消费者侧 var() 名字存在性）===")
print("定义全集 %d 个 | 扫描面 %d 个文件 | 被引用 %d 个名字"
      % (len(known), len(files), len(ref_names)))
print()
print("[1] 匹配器与扫描面自检（防「什么都没扫到 ⇒ 永远通过」）")
probe_good = REF.search("color: var(--text-primary);")
check(bool(probe_good) and probe_good.group(1) in known,
      "自检① 合成样本 var(--text-primary) 被识别为**已定义**的引用")
probe_bad = REF.search("background: var(--definitely-not-a-real-token, #fff);")
check(bool(probe_bad) and probe_bad.group(1) not in known,
      "自检② 合成样本 var(--definitely-not-a-real-token) 被判为**未定义**")
# 注释必须被剥掉（否则文档里当示例写的 var(--x) 会误报）
check(not REF.search(BLOCK_COMMENT.sub(" ", "/* var(--fake-in-comment) */")),
      "自检③ 块注释里的 var(--fake-in-comment) 不被当成引用")
check(len(files) >= 150, "自检④ 扫描面规模达标（实测 %d 个文件，期望 ≥150）" % len(files))
check(len(ref_names) >= 100,
      "自检⑤ 被引用变量名数量达标（实测 %d 个，期望 ≥100）" % len(ref_names))

print()
print("[2] 逐个名字判定")
if undef:
    for k in sorted(undef):
        locs = undef[k]
        check(False, "%s 未定义（%d 处）—— %s%s"
              % (k, len(locs), ", ".join(locs[:3]),
                 " …" if len(locs) > 3 else ""))
else:
    check(True, "全部 %d 个被引用的变量名均已定义" % len(ref_names))

print()
if fails:
    print("RESULT: FAIL（%d 处）—— 请把 var() 里的名字换成 presets.ts / App.vue 里"
          "**真实存在**的 token；若确实需要新语义，先往 presets.ts 的 LIGHT_VARS +"
          " DARK_VARS（及其余主题）补定义。" % len(fails))
    sys.exit(1)
print("RESULT: PASS（被引用的 %d 个变量名全部有定义）" % len(ref_names))
