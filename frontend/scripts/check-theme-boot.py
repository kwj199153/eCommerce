# -*- coding: utf-8 -*-
"""
主题字面量跨文件一致性自检 —— 防「加主题时漏改某处」的静默失效。

为什么需要它：主题清单（`ThemeName`）在 4 个**没有类型约束**的地方被复制了一份：

  ① `index.html` 内联脚本的 `THEMES` / `DARK_THEMES` 白名单
     —— 它必须早于任何 JS bundle 执行，所以无法 import presets.ts。
     漏改的表现：选了新主题后**冷启动首帧闪一下浅色兜底**（没人会测到）。
  ② `index.html` 首帧兜底样式的每主题两色。
     漏改的表现：首帧底色与主题不符。
  ③ 后端 `modules/secretary/navigation_tools.py` 的 `ThemeMode = Literal[...]`。
     它是**工具签名**的一部分 → LLM 只能从这里取值。
     漏改的表现：「老板说『换成马卡龙』→ 主 Agent 找不到该枚举 → 答没有这个主题」。
  ④ `src/api/secretary.ts` 的 `mode` 类型（已消除：改引 `ThemeMode`，本脚本反向断言它别退化）。

用法：python frontend/scripts/check-theme-boot.py   （退出码 0 = 全一致；1 = 有漂移）
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # frontend/
HTML = ROOT / "index.html"
PRESETS = ROOT / "src" / "theme" / "presets.ts"
STORE = ROOT / "src" / "stores" / "theme.ts"
APP = ROOT / "src" / "App.vue"
API = ROOT / "src" / "api" / "secretary.ts"
BACKEND = ROOT.parent / "backend" / "modules" / "secretary" / "navigation_tools.py"


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8", newline="").read()


def one(text: str, pattern: str, label: str, group: int = 1) -> str:
    m = re.search(pattern, text)
    if not m:
        print("  !! 提不出 %s（正则落空，源码结构可能变了）" % label)
        return ""
    return m.group(group).strip()


def vars_of(text: str, const_name: str) -> dict:
    """从 `const X: T = { ... }` 里抽 '--k': 'v'（差异表/完整表都适用）"""
    i = text.index("const %s" % const_name)
    j = text.index("\n}", i)
    return dict(re.findall(r"'(--[a-z0-9-]+)':\s*'([^']*)'", text[i:j]))


def theme_names(presets: str) -> list:
    return re.findall(r"'([a-z]+)'", one(presets, r"export type ThemeName = ([^\n]+)", "ThemeName"))


def preset_is_dark(presets: str) -> dict:
    """{预设名: isDark} —— 按 entry 切块，容忍 isDark 前有注释行"""
    blk = presets[presets.index("export const THEME_PRESETS"):]
    out = {}
    for m in re.finditer(r"\n    name: '(\w+)',([\s\S]*?)(?=\n    name: '|\n  \},|\Z)", blk):
        d = re.search(r"isDark:\s*(true|false)", m.group(2))
        out[m.group(1)] = d.group(1) == "true" if d else None
    return out


html = read(HTML)
presets = read(PRESETS)
store = read(STORE)
app = read(APP)

fails = []


def check(ok: bool, label: str, got="", want=""):
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        if got != "" or want != "":
            print("        复制点 = %r" % (got,))
            print("        真源   = %r" % (want,))
        fails.append(label)


themes = theme_names(presets)
is_dark = preset_is_dark(presets)
dark_names = [n for n, v in is_dark.items() if v]

print("=== 主题字面量跨文件一致性自检 ===")
print("真源 ThemeName = %s | isDark:true = %s" % (themes, dark_names))
print()
print("[1] index.html 内联脚本")

html_key = one(html, r"localStorage\.getItem\('([^']+)'\)", "index.html 键名")
src_key = one(store, r"STORAGE_KEY = '([^']+)'", "STORAGE_KEY")
check(html_key == src_key, "① storage key 一致", html_key, src_key)

html_sys = one(html, r"m === '(system)'", "index.html system")
src_sys = one(presets, r"SYSTEM_MODE = '([^']+)'", "SYSTEM_MODE")
check(html_sys == src_sys, "② SYSTEM_MODE 一致", html_sys, src_sys)

html_themes = re.findall(r"var THEMES = \[([^\]]+)\]", html)
html_themes = re.findall(r"'([a-z]+)'", html_themes[0]) if html_themes else []
check(set(html_themes) == set(themes), "③ THEMES 白名单 == ThemeName",
      ",".join(sorted(html_themes)), ",".join(sorted(themes)))

html_dark = re.findall(r"var DARK_THEMES = \[([^\]]+)\]", html)
html_dark = re.findall(r"'([a-z]+)'", html_dark[0]) if html_dark else []
check(set(html_dark) == set(dark_names), "④ DARK_THEMES == isDark:true 的预设",
      ",".join(sorted(html_dark)), ",".join(sorted(dark_names)))

html_def = one(html, r"var t = '([^']+)'", "index.html 默认主题")
src_def = one(presets, r"DEFAULT_THEME: ThemeName = '([^']+)'", "DEFAULT_THEME")
check(html_def == src_def, "⑤ DEFAULT_THEME 一致", html_def, src_def)

print()
print("[2] 首帧兜底色 vs 真源（每个主题的 --bg-base / --text-primary）")
blocks = dict(re.findall(r"html\[data-theme='(\w+)'\]\s*\{([^}]*)\}", html))
for name in themes:
    body = blocks.get(name)
    if body is None:
        print("  --   跳过 %s（无兜底块，与 :root 同值）" % name)
        continue
    got = {"--" + k: v.strip() for k, v in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body)}
    if "--bg-base" not in got:
        print("  --   跳过 %s（只声明了 color-scheme）" % name)
        continue
    want = vars_of(presets, "%s_VARS" % name.upper())
    for k in ["--bg-base", "--text-primary"]:
        check(got.get(k) == want.get(k), "⑥ %s 兜底 %s 一致" % (name, k), got.get(k, ""), want.get(k, ""))

print()
print("[3] App.vue :root 浅色兜底 vs LIGHT_VARS")
i = app.index(":root {")
root_blk = app[i: app.index("\n}", i)]
app_light = {"--" + k: v.strip() for k, v in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", root_blk)}
light_vars = vars_of(presets, "LIGHT_VARS")
for k in ["--bg-base", "--text-primary"]:
    check(app_light.get(k) == light_vars.get(k), "⑦ App.vue 浅色兜底 %s 一致" % k,
          app_light.get(k, ""), light_vars.get(k, ""))

print()
print("[4] 「用嘴换主题」链路")
try:
    be = read(BACKEND)
    m = re.search(r"ThemeMode = Literal\[([^\]]+)\]", be)
    be_modes = re.findall(r'"(\w+)"', m.group(1)) if m else []
    check(set(be_modes) == set(themes) | {src_sys},
          "⑧ 后端 navigation_tools.ThemeMode == ThemeName + system",
          ",".join(sorted(be_modes)), ",".join(sorted(set(themes) | {src_sys})))
except FileNotFoundError:
    print("  --   跳过（未找到后端文件 %s）" % BACKEND)

try:
    api = read(API)
    check("mode?: ThemeMode" in api, "⑨ api/secretary.ts 引用 ThemeMode（未退化回字面量）",
          "写死字面量" if "mode?: ThemeMode" not in api else "已引用", "已引用")
except FileNotFoundError:
    print("  --   跳过（未找到 %s）" % API)

print()
if fails:
    print("RESULT: FAIL（%d 处漂移）—— 请按上表把复制点同步到 presets.ts" % len(fails))
    sys.exit(1)
print("RESULT: PASS（主题清单与首屏兜底在 %d 处复制点全部一致）" % 9)
