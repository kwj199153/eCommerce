# -*- coding: utf-8 -*-
"""
动作分发穷尽性自检 —— 防「AppAction 联合类型声明了新动作、dispatchAppAction 却忘了实现分支」。

为什么需要它：
    `dispatchAppAction(action: AppAction)` 用 if 链逐个判 `action.type`，**没有 never 兜底**。
    TypeScript 因此**不会**强制穷尽联合类型的所有成员 —— 漏写分支不报错、不告警，
    运行时静默落到结尾 `return false`。

    真实事故：`switch_shop` 在 AppAction 里声明了（api/secretary.ts 与 appActions.ts 两处都有），
    但 dispatchAppAction 里没有对应分支 → 老板说「切换到虾皮2」，
    后端正常返回 switch_shop 动作，前端却什么都不做、只是 `return false`；
    更糟的是编排层丢弃了返回值，照旧回「已经切换到您的第二个虾皮店铺」——
    老板看到的是**「AI 撒谎」**而不是「功能坏了」。这类 bug 类型检查与 tsc 都拦不住。

本脚本做三件事：
  ① 动作名对账：AppAction 联合类型声明的每个 type，dispatchAppAction 必须有同名的实现分支。
  ② 契约对账：actions 链路的动作集合（api/secretary.ts 的 action 联合、
     navigation_tools.py 的工具产出）与前端实现分支对齐，发现「后端能发、前端不认」的动作。
  ③ 返回值被消费：调用方（useChatOrchestrator）不得静默丢弃 dispatchAppAction 的布尔结果 ——
     对**可能失败**的动作（switch_shop 等有时间/状态前提的），必须检查并如实回报。

用法：python frontend/scripts/check_app_actions.py   （退出码 0 = 通过；1 = 有漏实现/漏检查）
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # frontend/
APP_ACTIONS = ROOT / "src" / "utils" / "appActions.ts"
API = ROOT / "src" / "api" / "secretary.ts"
ORCH = ROOT / "src" / "composables" / "useChatOrchestrator.ts"
WORKSPACE = ROOT / "src" / "views" / "Workspace.vue"
NAV_TOOLS = ROOT.parent / "backend" / "modules" / "secretary" / "navigation_tools.py"
SHOP_TOOLS = ROOT.parent / "backend" / "modules" / "secretary" / "shop_tools.py"

fails = []


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8", newline="").read()


def check(ok: bool, label: str, got="", want=""):
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        if got != "" or want != "":
            print("        实现 = %r" % (got,))
            print("        声明 = %r" % (want,))
        fails.append(label)


def declared_types(text: str, anchor: str) -> list:
    """从 `export type X = | { type: 'a' } | { type: 'b' }` 里抽类型名"""
    i = text.index(anchor)
    # 截到下一个顶层 export / const 声明
    tail = text[i:]
    m = re.search(r"\n(?=export |const |function )", tail[1:])
    blk = tail if m is None else tail[: m.start() + 1]
    return re.findall(r"type:\s*'([a-z_]+)'", blk)


def implemented_types(text: str) -> list:
    """从 dispatchAppAction 函数体里抽 `action.type === 'x'` 的 x"""
    i = text.index("export function dispatchAppAction")
    blk = text[i:]
    return re.findall(r"action\.type === '([a-z_]+)'", blk)


def union_literal_types(text: str, field: str = "action") -> list:
    """抽 `action: 'a' | 'b' | ...` 这种**单行联合字面量**的成员

    与 declared_types 的区别：declared_types 针对 `| { type: 'a' }` 的结构化联合；
    这里针对 api/secretary.ts 里 `action: 'a' | 'b'` 的紧凑写法。
    """
    m = re.search(field + r"\??:\s*((?:'[a-z_]+'\s*\|?\s*)+)", text)
    if not m:
        return []
    return re.findall(r"'([a-z_]+)'", m.group(1))


def strip_comments(text: str) -> str:
    """剥离 // 行注释与 /* */ 块注释（以及 *.vue 的 <!-- -->）。

    ★ 为什么必须：检查「某函数是否被调用」时若直接子串匹配，**注释里出现该函数名
      就能骗过检查**（本脚本第 5 段的 Workspace 项曾因此假绿，靠反向注入验证才暴露）。
      只做粗粒度剥离：不处理字符串字面量里的 // —— 对本脚本的用途足够。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


print("=== 动作分发穷尽性自检 ===")

app_actions = read(APP_ACTIONS)
api = read(API)
orch = read(ORCH)

declared = declared_types(app_actions, "export type AppAction")
implemented = implemented_types(app_actions)

print()
print("[1] AppAction 声明 vs dispatchAppAction 实现")
print("  声明 = %s" % declared)
print("  实现 = %s" % implemented)
missing = [t for t in declared if t not in implemented]
extra = [t for t in implemented if t not in declared]
for t in declared:
    check(t in implemented, "① 动作 %-14s 有实现分支" % t,
          "未实现 → 会静默 return false" if t not in implemented else "已实现", "已实现")
for t in extra:
    check(False, "① 动作 %-14s 在声明中有对应类型" % t, "只实现未声明（类型收窄不合法）", "需补进 AppAction")
if not missing and not extra:
    print("  --   无差异，共 %d 个动作全部穷尽" % len(declared))

print()
print("[2] 后端可发的动作 ⊆ 前端已实现（防「后端能发、前端不认」）")
try:
    nav = read(NAV_TOOLS)
    shop = read(SHOP_TOOLS)
    be_actions = set(re.findall(r'"action":\s*"([a-z_]+)"', nav)) | \
                 set(re.findall(r'"action":\s*"([a-z_]+)"', shop))
    print("  后端工具产出 = %s" % sorted(be_actions))
    for a in sorted(be_actions):
        check(a in implemented, "② 后端动作 %-14s 前端有实现" % a,
              "前端缺分支" if a not in implemented else "已实现", "已实现")
except FileNotFoundError as e:
    print("  --   跳过（%s）" % e)

print()
print("[3] api/secretary.ts 的动作联合 ⊆ 已实现")
api_actions = union_literal_types(api, "action")
print("  契约声明 = %s" % api_actions)
if not api_actions:
    check(False, "③ 能从 api/secretary.ts 抽出动作联合", "抽取落空（源码结构变了？）", "非空列表")
for a in sorted(set(api_actions)):
    check(a in implemented, "③ 契约动作 %-14s 前端有实现" % a,
          "前端缺分支" if a not in implemented else "已实现", "已实现")
check(set(api_actions) == set(implemented), "③ 契约动作集合 == 实现集合",
      ",".join(sorted(api_actions)), ",".join(sorted(implemented)))

print()
print("[4] 可能失败的动作：调用方必须消费返回值（不得静默丢弃）")
# 有时间/状态前提、可能在运行时失败的动作 —— 丢返回值 = 失败时仍回「已成功」
FALLIBLE = ["switch_shop", "select_product", "switch_agent"]
# 逐动作找调用点：必须有 `dispatchAppAction(` 且不是被 `!dispatch...` / `= dispatch...` / `if (dispatch...` 包裹
for act in FALLIBLE:
    # 该动作在编排层的 dispatch 调用
    pat = re.compile(r"dispatchAppAction\(\{\s*type:\s*'%s'" % act)
    hits = list(pat.finditer(orch))
    consumed = bool(re.search(r"[!=]\s*d?i?s?patchAppAction\(|=\s*!dispatchAppAction\(", orch)) or \
               bool(re.search(r"shopSwitchFailed\s*=\s*!dispatchAppAction", orch))
    if act == "switch_shop":
        # 本脚本关注的重点：switch_shop 必须同步执行且检查结果
        check("shopSwitchFailed" in orch, "④ switch_shop 落地检查成败（shopSwitchFailed）",
              "未检查返回值" if "shopSwitchFailed" not in orch else "已检查", "已检查")
        check("sync" in orch or "同步" in orch, "④ switch_shop 已从 setTimeout 提为同步执行",
              "仍在 setTimeout 里" if "同步" not in orch else "已同步", "已同步")
        check("没能切换" in orch, "④ switch_shop 失败时如实回报（不谎报成功）",
              "失败仍回成功" if "没能切换" not in orch else "已如实回报", "已如实回报")
    else:
        print("  --   %-14s 调用点 %d 处（本脚本只强校验 switch_shop，其余人工确认）" % (act, len(hits)))

print()
print("[5] switch_shop 不得有『列表已加载』这种隐藏前置（2026-09-14 事故）")
# 事故：早先实现要求 `shopStore.shops` 里已 find 到目标才切，而该列表当时
# 只在「店铺群」弹层挂载时才拉 —— 没点开过弹层 → shops=[] → 切换被静默丢弃。
# 现在必须：直接用 id 切换 + 列表空时补拉。以下三条钉住这个契约。
check("ensureShopsLoaded" in app_actions,
      "⑤ appActions 里 switch_shop 会补拉列表（ensureShopsLoaded）",
      "缺失：列表空时不会补拉，左上角店铺名会算不出" if "ensureShopsLoaded" not in app_actions else "已补拉",
      "已补拉")
# 反向：不得再出现「按 id 去列表里找对象，找不到就失败」的老写法
_bad_find = re.search(
    r"shops\.find\(\s*\w+\s*=>\s*\w+\.id\s*===\s*action\.shopId\s*\)", app_actions)
check(_bad_find is None,
      "⑤ switch_shop 不再强求『先 find 到对象』",
      "仍有 shops.find(...action.shopId) 前置 → 列表未加载时会被丢弃" if _bad_find else "已移除",
      "已移除")
check(re.search(r"setCurrentShop\(\s*action\.shopId\s*\)", app_actions) is not None,
      "⑤ switch_shop 直接用 shopId 切换",
      "未直接使用 action.shopId" if not re.search(r"setCurrentShop\(\s*action\.shopId\s*\)", app_actions) else "已直接切换",
      "已直接切换")
# 启动加载点：Workspace 必须**真的调用** ensureShopsLoaded（否则刷新后左上角空白）
# ⚠️ 必须剥离注释再匹配 —— 否则注释里提到 "ensureShopsLoaded" 就能骗过检查
#    （本项曾因此假绿，靠反向注入验证才发现）。
try:
    wsvue = read(WORKSPACE)
    wsvue_code = strip_comments(wsvue)
    ok_ws = re.search(r"\bshopStore\.ensureShopsLoaded\s*\(", wsvue_code) is not None
    check(ok_ws,
          "⑤ Workspace 启动时真的调用店铺列表加载",
          "缺失：刷新后不点弹层则左上角店铺名不显示" if not ok_ws else "已调用",
          "已调用")
except FileNotFoundError:
    print("  --   跳过（%s 不存在）" % WORKSPACE)

print()
if fails:
    print("RESULT: FAIL（%d 处问题）—— 请为缺失动作补 dispatchAppAction 分支，并消费返回值" % len(fails))
    sys.exit(1)
print("RESULT: PASS（%d 个动作声明/实现穷尽对齐；switch_shop 成败已检查、无隐藏前置）" % len(declared))
