#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：docker-compose.yml 不得出现明文口令 / 数据库不得对公网暴露（P0-4）。

为什么必须有这道静态门禁
------------------------
这两条极易被"改回去"，而且**改回去不报错**：
  · 为了本机方便，把 `127.0.0.1:5432:5432` 改回 `5432:5432` —— 服务照跑，
    只是把库连同口令一起挂到了 0.0.0.0（扫描器几小时内就能撞上）；
  · 为了省事，把 `${POSTGRES_PASSWORD:-...}` 改回写死的口令 —— 同样照跑，
    口令从此进入 git 历史。
⇒ 都是"静默削弱"，只能在静态层面守住。

与运行期判据的分工（不是重复实现）
----------------------------------
  · 本脚本（静态）：守**文件里的形态** —— 值必须是插值、端口必须绑回环。
  · `core/config.py::_enforce_production_safety`（运行期）：守**部署时的值** ——
    生产若仍拿到弱口令，**拒绝启动**。
  两者互补：静态门禁防"改回明文"，运行期门禁防"插值默认值本身就是弱口令"。

★ 本脚本只用正则读文本，**不写任何口令字面量**，因此可安全放进 CI / 提交。

用法：python scripts/check_compose_secrets.py [--compose PATH]
退出码：0 = 全部通过；1 = 有违规；2 = 找不到文件 / 解析失败。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DB_PORT = "5432"
LOOPBACK = "127.0.0.1"


def locate(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for cand in (
        Path(__file__).resolve().parents[2] / "docker-compose.yml",  # 仓库根
        Path.cwd() / "docker-compose.yml",
    ):
        if cand.is_file():
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="docker-compose 明文口令 / 公网端口门禁")
    ap.add_argument("--compose", help="docker-compose.yml 路径（默认自动定位）")
    args = ap.parse_args()

    path = locate(args.compose)
    if path is None:
        print("[ERROR] 找不到 docker-compose.yml（用 --compose 显式指定）")
        return 2
    text = path.read_text(encoding="utf-8")
    print(f"检查文件：{path}")
    print("-" * 68)

    results: list[tuple[bool, str, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((ok, name, detail))

    # ---- 1. 数据库端口必须只绑回环 -------------------------------------
    port_entries = re.findall(r'^\s*-\s*["\']?([^"\'\s]+)["\']?\s*$', text, re.M)
    db_ports = [p for p in port_entries if p.endswith(f":{DB_PORT}") or f":{DB_PORT}:" in p]
    bare = [p for p in db_ports if p == f"{DB_PORT}:{DB_PORT}"]
    loopback = [p for p in db_ports if p == f"{LOOPBACK}:{DB_PORT}:{DB_PORT}"]
    check(
        f"postgres 端口只绑回环（{LOOPBACK}:{DB_PORT}:{DB_PORT}）",
        bool(loopback) and not bare,
        f"端口映射={db_ports}；裸暴露={bare}",
    )

    # ---- 2. POSTGRES_PASSWORD 必须是插值而非字面量 ----------------------
    m_pw = re.search(r"^\s*POSTGRES_PASSWORD:\s*(.+?)\s*$", text, re.M)
    pw_raw = m_pw.group(1) if m_pw else ""
    check(
        "POSTGRES_PASSWORD 走环境变量插值（非明文）",
        pw_raw.startswith("${"),
        f"当前值形态={'插值' if pw_raw.startswith('${') else pw_raw[:24]}",
    )

    # ---- 3. 三处 DATABASE_URL 都必须是插值 ------------------------------
    urls = re.findall(r"^\s*DATABASE_URL:\s*(.+?)\s*$", text, re.M)
    bad_urls = [u for u in urls if not u.startswith("${")]
    check(
        "backend/worker/beat 的 DATABASE_URL 均走插值（3 处）",
        len(urls) == 3 and not bad_urls,
        f"命中 {len(urls)} 处，非插值 {len(bad_urls)} 处",
    )

    # ---- 4. healthcheck 不得写死用户名/库名 ----------------------------
    check(
        "healthcheck 的用户名/库名与 POSTGRES_* 同源",
        "pg_isready -U ${POSTGRES_USER" in text,
        "写死用户名会让改 POSTGRES_USER 后健康检查永久 unhealthy",
    )

    # ---- 5. 跨文件一致性：两处默认口令必须相同 --------------------------
    #   这是实测踩到的真实陷阱：只改 POSTGRES_PASSWORD 而不改 DATABASE_URL，
    #   compose 照常起、容器连不上库 —— 现象是「服务起不来但看不出原因」。
    def default_of(var: str) -> str | None:
        m = re.search(rf"^\s*{var}:\s*\$\{{[^:}}]+:-([^}}]*)\}}", text, re.M)
        return m.group(1) if m else None

    pw_default = default_of("POSTGRES_PASSWORD")
    url_default = default_of("DATABASE_URL")
    url_pw = None
    if url_default:
        m = re.match(r"^[^:]+://[^:]+:([^@]*)@", url_default)
        url_pw = m.group(1) if m else None
    check(
        "POSTGRES_PASSWORD 与 DATABASE_URL 的默认口令一致",
        pw_default is not None and pw_default == url_pw,
        (
            "两处默认值不同 ⇒ 改一处漏改另一处会让容器连不上库"
            if pw_default != url_pw
            else "两处同源"
        ),
    )

    # ---- 输出 ----------------------------------------------------------
    failed = 0
    for ok, name, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if detail and not ok:
            print(f"         ↳ {detail}")
        failed += 0 if ok else 1

    print("-" * 68)
    total = len(results)
    if failed:
        print(f"RESULT: FAIL（{failed}/{total} 项未通过）")
        return 1
    print(f"RESULT: PASS（{total}/{total} 项通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
