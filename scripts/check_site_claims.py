#!/usr/bin/env python3
"""官网宣传口径门禁（r385 · 商用审查 P0-3）。

==============================================================================
★ 为什么要这条门禁
==============================================================================
第三方审查指出：官网首屏写「亚马逊 / Shopee / TikTok Shop / TEMU」，
而后端只有 Amazon 有取数实现（`platforms/shopee|tiktok|shopify/client.py`
文件头自述「骨架实现」），`platforms/temu` **连目录都没有**。

规格上这不算"功能缺失"，而是**宣传口径风险**：客户冲着"多平台"进来，
接上 Shopee 会拿到空数据。本轮把首屏改成「已接通 Amazon SP-API」，
并加了一段主动披露。本门禁防的是**它再漂回去**。

==============================================================================
★ 判据（三条，互相不可替代）
==============================================================================
  C1  首屏 eyebrow 里点名的平台 ⊆ CONNECTED（已接通集合）
      —— 抓「首屏又列上未接通平台」。
  C2  `site/index.html` 必须存在 `.data-status` 披露条，且点名 Amazon SP-API
      —— 抓「披露段被顺手删掉」。删掉不等于撒谎，但会让 C1 的修改失去解释。
  C3  隐私政策的数据源表格行，不得把 Amazon 与未接通平台**并列**成数据源
      —— 抓「Amazon SP-API / Shopee Open Platform」这种并列表述（暗示两路都通）。

★ 反向自证：`CONNECTED` 里每个平台都必须有一个**非骨架**的取数适配器
  （文件头不含「骨架实现」）。这防的是「登记表过期」——把某个平台登记成
  已接通，而代码其实还是骨架。

用法：
    python scripts/check_site_claims.py [--root D:/ai/eCommerce]
退出码：0 全过 / 1 有 FAIL / 2 SKIP（site 目录不存在）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: 已接通取数的平台（**人工登记**，C4 会反证它没过期）。
#: 加平台时：先落地取数适配器，再登记到这里，最后才允许写进官网首屏。
CONNECTED: dict[str, str] = {
    "amazon": "Amazon",
}

#: 平台别名 → 标准键。文案里可能写中文名。
ALIASES: dict[str, str] = {
    "amazon": "amazon",
    "亚马逊": "amazon",
    "shopee": "shopee",
    "tiktok": "tiktok",
    "tiktok shop": "tiktok",
    "shopify": "shopify",
    "temu": "temu",
}

#: 未接通平台在文案里的典型写法（C3 用）
UNCONNECTED_TOKENS: tuple[str, ...] = ("Shopee", "TikTok", "Shopify", "TEMU", "Temu")

SKELETON_MARKERS: tuple[str, ...] = ("骨架实现", "骨架")


class Gate:
    def __init__(self) -> None:
        self.pass_ = 0
        self.fail: list[str] = []
        self.skip: list[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        self.pass_ += 1
        print(f"  PASS  {label}" + (f" —— {detail}" if detail else ""))

    def ng(self, label: str, detail: str) -> None:
        self.fail.append(f"{label} —— {detail}")
        print(f"  FAIL  {label} —— {detail}")

    def sk(self, label: str, detail: str) -> None:
        self.skip.append(f"{label} —— {detail}")
        print(f"  SKIP  {label} —— {detail}")


def _platforms_in(text: str) -> set[str]:
    found: set[str] = set()
    low = text.lower()
    for alias, key in ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low):
            found.add(key)
    return found


def _eyebrow(html: str) -> str | None:
    m = re.search(r'<p[^>]*class="[^"]*\beyebrow\b[^"]*"[^>]*>(.*?)</p>', html, re.S)
    return m.group(1) if m else None


def c1_eyebrow(g: Gate, index_html: str) -> None:
    raw = _eyebrow(index_html)
    if raw is None:
        g.ng("C1 首屏 eyebrow 可定位", "没找到 class=eyebrow 的段落（判据已失效，非页面正确）")
        return
    text = re.sub(r"<[^>]+>", "", raw)
    names = _platforms_in(text)
    extra = names - set(CONNECTED)
    if extra:
        g.ng(
            "C1 首屏只点名已接通平台",
            f"eyebrow 出现未接通平台 {sorted(extra)}；原文「{text.strip()}」",
        )
    else:
        named = ",".join(sorted(names)) or "（无平台名）"
        g.ok("C1 首屏只点名已接通平台", f"点名 {named} ⊆ {sorted(CONNECTED)}")


def c2_disclosure(g: Gate, index_html: str) -> None:
    m = re.search(r'<p[^>]*class="[^"]*\bdata-status\b[^"]*"[^>]*>(.*?)</p>', index_html, re.S)
    if not m:
        g.ng("C2 主动披露条在位", "site/index.html 没有 .data-status 段（披露被删）")
        return
    text = re.sub(r"<[^>]+>", "", m.group(1))
    if "Amazon SP-API" not in text:
        g.ng("C2 披露条点名 Amazon SP-API", f"段落存在但没点名当前数据源；原文「{text.strip()[:60]}…」")
        return
    g.ok("C2 主动披露条在位", f"{len(text.strip())} 字，点名 Amazon SP-API")


def c3_privacy(g: Gate, privacy_html: str) -> None:
    """隐私政策里「平台数据接入」那一行不得并列未接通平台。"""
    rows = re.findall(r"<tr>(.*?)</tr>", privacy_html, re.S)
    hit = 0
    bad: list[str] = []
    for row in rows:
        if "平台数据接入" not in row:
            continue
        hit += 1
        plain = re.sub(r"<[^>]+>", " ", row)
        if "Amazon" in plain:
            leaked = [t for t in UNCONNECTED_TOKENS if t in plain]
            if leaked:
                bad.append(f"并列出现 {leaked}：{' '.join(plain.split())[:90]}")
    if hit == 0:
        g.ng("C3 隐私政策声明数据源", "没找到「平台数据接入」行（判据失配，非页面正确）")
        return
    if bad:
        g.ng("C3 隐私政策不并列未接通平台", bad[0])
    else:
        g.ok("C3 隐私政策不并列未接通平台", f"扫描 {hit} 行「平台数据接入」，未出现并列")


def c4_registry_fresh(g: Gate, backend: Path) -> None:
    """CONNECTED 里每个平台都得有非骨架适配器（防登记表过期）。"""
    stale: list[str] = []
    missing: list[str] = []
    for key in CONNECTED:
        path = backend / "platforms" / key / "client.py"
        if not path.exists():
            missing.append(f"{key}（{path} 不存在）")
            continue
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:40])
        if any(mark in head for mark in SKELETON_MARKERS):
            stale.append(key)
    if missing:
        g.ng("C4 登记表与代码一致", f"登记的已接通平台没有适配器：{missing}")
    elif stale:
        g.ng("C4 登记表与代码一致", f"{stale} 登记为已接通，但适配器自述「骨架」")
    else:
        g.ok("C4 登记表与代码一致", f"{sorted(CONNECTED)} 均有非骨架适配器")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()
    root = Path(args.root)

    site = root / "site"
    if not site.is_dir():
        print("SKIP  找不到 site/ 目录（本仓未包含官网源码）")
        return 2

    index_path = site / "index.html"
    privacy_path = site / "privacy.html"
    for p in (index_path, privacy_path):
        if not p.exists():
            print(f"FAIL  缺少 {p}")
            return 1

    g = Gate()
    index_html = index_path.read_text(encoding="utf-8")
    privacy_html = privacy_path.read_text(encoding="utf-8")

    print("[C1~C2] 官网首屏与披露")
    c1_eyebrow(g, index_html)
    c2_disclosure(g, index_html)

    print("\n[C3] 隐私政策数据源口径")
    c3_privacy(g, privacy_html)

    print("\n[C4] 登记表反证（代码侧）")
    c4_registry_fresh(g, root / "backend")

    print(f"\n=== 汇总：{g.pass_} PASS / {len(g.fail)} FAIL / {len(g.skip)} SKIP ===")
    if g.fail:
        print("RESULT: FAIL")
        for line in g.fail:
            print("  ·", line)
        return 1
    print("RESULT: PASS（首屏只承诺已接通平台 · 披露条在位 · 隐私政策无并列 · 登记表未过期）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
