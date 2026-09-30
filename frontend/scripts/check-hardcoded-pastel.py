# -*- coding: utf-8 -*-
r"""门禁 —— 禁止「硬编码粉彩浅色**底**」：它在深色主题下不翻转，而字色跟着主题变
⇒ 深色下**不可见的白底白字/亮底浅字**。

为什么必须是独立的一条门禁（三条现成检查全是盲区）：
  · `check-theme-var-refs.py` 只管「引用的变量名存不存在」——**硬编码色它根本看不见**；
  · `vue-tsc` / `vite build` / 单测 —— 颜色值不是类型，全都不报；
  · `cdp-dark-contrast.mjs` 是**真机探针**：要组件被挂载才量得到，
    而这一类站点大量住在右栏面板 / 弹窗里，默认不渲染 ⇒ 探针扫不到。
本门禁补的正是这个洞：**静态、全仓、不依赖渲染**。

判据形态（= 缺陷形态，不是"见过哪些值"）：
  在 `background` / `background-color` 声明里（含 `linear-gradient()` 的色标）
  出现的 **hex / rgb() 字面量**，其 **WCAG 相对亮度 > 0.85** ⇒ 命中。
  说明：亮度阈值而不是"白名单具体色号"——色号会漂，形态不会。

棘轮（本仓纪律）：存量站点写进 WAIVER，**每条必须真的命中**（过期白名单要报红），
新出现的同类字面量一律红。

用法：
  python scripts/check-hardcoded-pastel.py           判定（有非豁免命中 ⇒ 退出码 1）
  python scripts/check-hardcoded-pastel.py --report  只打印命中清单，不判定
CI：`.github/workflows/ci.yml` 用 glob `scripts/check-*.*` 逐个执行 ⇒ 本文件自动纳入。
"""
import io
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                     # frontend/
SRC = Path(os.environ.get("PASTEL_SRC_ROOT") or (ROOT / "src"))
REPORT_ONLY = "--report" in sys.argv

LUM_MIN = 0.85
SUFFIXES = ("*.vue", "*.css")

BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")


def blank_keep_lines(m):
    """把注释替换成**等长空白并保留换行**。

    ★ 第一版用 `sub(" ", body)`：多行块注释被压成一个空格 ⇒ **整份文件的行号全部前移**，
      门禁报出的 `file:line` 是错的（诊断信息不可信 = 门禁的一半价值没了）。
      这里逐字符替换成空格、换行原样保留，行号才与编辑器一致。
    """
    return re.sub(r"[^\n]", " ", m.group(0))

# `background` / `background-color` 的整条声明（含多值），到 `;` 或 `}` 为止
BG_DECL = re.compile(r"background(?:-color)?\s*:\s*([^;{}]+)", re.I)
# ★ `var(--x, #e6f7ff)` 里的字面量是**兜底值**，不是硬编码：它只在变量未定义时生效
#   （本仓 `--info-bg` / `--success-bg` 等都有定义 ⇒ 兜底永不生效）。
#   把它算进来会让门禁报一堆**假红**，正是「判据口径过宽 ⇒ 静默归零」的反面：
#   过度上报会让人把整条门禁关掉。故先剔除 `var(...)` 再找字面量。
VAR_CALL = re.compile(r"var\(\s*--[a-z0-9-]+[^)]*\)", re.I)
# 颜色字面量：#rgb / #rrggbb / rgb() / rgba(a=1)
COLOR_LIT = re.compile(r"#([0-9a-fA-F]{3,8})\b|rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def hex_to_rgb(h):
    if len(h) == 3:
        return [int(c * 2, 16) for c in h]
    if len(h) == 6:
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return None          # 4/8 位带 alpha 的形式本仓没有，跳过


def lum(rgb):
    def g(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * g(rgb[0]) + 0.7152 * g(rgb[1]) + 0.0722 * g(rgb[2])


def literals(text):
    """抽出该声明里所有**不透明**颜色字面量（半透明的会与底色融合，不属本形态）"""
    out = []
    for m in COLOR_LIT.finditer(text):
        if m.group(1):
            rgb = hex_to_rgb(m.group(1))
            if rgb:
                out.append((m.group(0), rgb))
        else:
            a = m.group(5)
            if a is None or float(a) >= 0.999:
                out.append((m.group(0), [float(m.group(2)), float(m.group(3)), float(m.group(4))]))
    return out


# ------------------------------------------------------------------ 棘轮白名单
# 每条 = (文件相对路径, 该文件里出现的字面量, 为什么可接受)。
# ★ 必须每条都真的命中，否则报红（防"永久免检区"）。
WAIVER = [
    ("components/ChatPanel/results/BulletGenerator.vue", "#fef6f8",
     "Listing 预览区：刻意做成「亚马逊商品页」的浅色外观（不受主题影响），"
     "块内文字也全部写死深色 ⇒ 不构成「亮底 + 跟随主题的浅字」这个缺陷形态"),
    ("components/ChatPanel/results/BulletGenerator.vue", "#fff5f7", "同上一处渐变第二档"),
    ("components/ChatPanel/results/DescriptionGenerator.vue", "#f5f7fa", "A+ 内容预览区，同上"),
    ("components/ChatPanel/results/TitleGenerator.vue", "#fef6e4", "标题预览卡，同上"),
    ("components/ChatPanel/results/TitleGenerator.vue", "#ffecd2", "同上一处渐变第二档"),
    ("views/Subscription.vue", "#fff",
     "支付二维码图的底（.pay-qr-img）：二维码是黑白点阵，深色主题下直接铺在暗底上"
     "会因对比度反转而**扫不出来** ⇒ 这一处必须固定白底。源码里已有同样的注释说明"),
]


def waive_for(rel, lit):
    for r, l, why in WAIVER:
        if r == rel and l.lower() == lit.lower():
            return why
    return None


files = sorted({p for s in SUFFIXES for p in SRC.rglob(s)})
hits, waived_hit, skip_fallback = [], set(), 0
for p in files:
    rel = p.relative_to(SRC).as_posix()
    body = read(p)
    body = BLOCK_COMMENT.sub(blank_keep_lines, body)
    body = HTML_COMMENT.sub(blank_keep_lines, body)
    for m in BG_DECL.finditer(body):
        decl = m.group(1)
        line = body[:m.start()].count("\n") + 1
        bare = VAR_CALL.sub(" ", decl)                     # 剔除 var() 兜底后再找字面量
        skip_fallback += len(literals(decl)) - len(literals(bare))
        for lit, rgb in literals(bare):
            if lum(rgb) <= LUM_MIN:
                continue
            why = waive_for(rel, lit)
            if why:
                waived_hit.add((rel, lit.lower()))
            hits.append({"file": rel, "line": line, "lit": lit,
                         "lum": round(lum(rgb), 3), "waived": bool(why)})

unwaived = [h for h in hits if not h["waived"]]
stale = [(r, l) for r, l, _ in WAIVER if (r, l.lower()) not in waived_hit]

if REPORT_ONLY:
    print("扫描面 = %d 个文件（%s）| 命中 %d 处（其中豁免 %d 处）"
          % (len(files), ",".join(SUFFIXES), len(hits), len(hits) - len(unwaived)))
    for h in sorted(hits, key=lambda x: (x["waived"], x["file"], x["line"])):
        print("  %s lum=%-5s %-52s:%-5s %s"
              % ("[豁免]" if h["waived"] else "**红**", h["lum"], h["file"], h["line"], h["lit"]))
    if stale:
        print("\n过期白名单（声明了但没命中）：")
        for r, l in stale:
            print("  %s  %s" % (r, l))
    sys.exit(0)

fails = []


def check(ok, label):
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        fails.append(label)


print("=== 硬编码粉彩底门禁（深色主题下的「亮底 + 浅字」形态）===")
print("阈值：background 声明里不透明字面量的 WCAG 相对亮度 > %s" % LUM_MIN)
print("扫描面 %d 个文件 | 命中 %d 处 | 豁免 %d 处 | 跳过 var() 兜底值 %d 个"
      % (len(files), len(hits), len(hits) - len(unwaived), skip_fallback))
print()
print("[1] 匹配器自检（防「正则写错 ⇒ 永远零命中」）")
probe_hi = literals("#f6ffed")
check(bool(probe_hi) and lum(probe_hi[0][1]) > LUM_MIN, "自检① 合成样本 #f6ffed 被判为粉彩（亮度 %s）"
      % (round(lum(probe_hi[0][1]), 3) if probe_hi else "N/A"))
probe_lo = literals("#141414")
check(bool(probe_lo) and lum(probe_lo[0][1]) <= LUM_MIN, "自检② 合成样本 #141414 不达标（深色不算）")
probe_alpha = literals("rgba(24, 144, 255, 0.12)")
check(not probe_alpha, "自检③ 半透明底 rgba(...,0.12) 被跳过（它会与底色融合，不属本形态）")
n_vue = sum(1 for p in files if p.suffix == ".vue")
n_css = sum(1 for p in files if p.suffix == ".css")
check(len(files) >= 100, "自检④ 扫描面规模达标（实测 %d 个 = %d 个 .vue + %d 个 .css，期望 ≥100；"
      "TS 里不写 CSS 声明故不纳入）" % (len(files), n_vue, n_css))
check(bool(hits), "自检⑤ 当前盘面确有命中（实测 %d 处）—— 零命中说明阈值或正则失效" % len(hits))
print()
print("[2] 非豁免命中必须为 0")
for h in unwaived:
    check(False, "%s:%s  %s（亮度 %s）—— 请改用主题变量；确属「刻意固定浅色」"
                 "（如商品页预览）的请写进 WAIVER 并说明理由" % (h["file"], h["line"], h["lit"], h["lum"]))
if not unwaived:
    check(True, "无非豁免命中（全部 %d 处均已在白名单内并说明理由）" % len(hits))
print()
print("[3] 白名单每条都必须真的命中（防「永久免检区」）")
for r, l in stale:
    check(False, "白名单过期：%s 的 %s 已不存在 —— 请删掉这条" % (r, l))
if not stale:
    check(True, "白名单 %d 条全部命中" % len(WAIVER))

print()
if fails:
    print("RESULT: FAIL（%d 处）" % len(fails))
    sys.exit(1)
print("RESULT: PASS（%d 处命中全部在白名单内，且白名单无过期项）" % len(hits))
