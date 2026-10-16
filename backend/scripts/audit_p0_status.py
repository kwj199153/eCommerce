#!/usr/bin/env python
"""P0 阻断项**证据采集器**（不是门禁，也**不替你下判断**）。

★ 为什么有这个脚本：`docs/technical-diligence-review-20260930.md` 是时点快照，
  它记的 P0 状态 15 天后就腐化了。本仓有体量棘轮守「代码不会悄悄变大」，
  却**没人守「文档不会悄悄说谎」**。与其每轮靠人肉重查，不如把**检索口径**脚本化。

★ 它的定位是**证据采集**，刻意不做「已修 / 未修」的自动判定：
  P0 状态含「部分修」（如 P0-4 端口改了、口令默认值没改）这类**非二值**情形，
  机器判定会把「部分」压成「是/否」⇒ 产出新的谎言。所以它只打印证据行，
  由人读完再写进文档。**读了它的输出不等于读了真相，跑它是为了少跑几次 grep。**

★ 用法：`python backend/scripts/audit_p0_status.py`
  验证某个 P0 是否仍成立时，看对应分区的「命中 / 未命中」行即可。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
COMPOSE = ROOT / "docker-compose.yml"


def _exists(rel: str) -> str:
    p = ROOT / rel
    if p.is_dir():
        n = len([x for x in p.iterdir() if x.is_file()])
        return f"命中  目录存在（{n} 个文件）  {rel}"
    if p.is_file():
        n = len(p.read_bytes().split(b"\n"))
        return f"命中  文件存在（{n} 行）      {rel}"
    return f"未命中 不存在                  {rel}"


def _grep(rel: str, pattern: str, limit: int = 3) -> list[str]:
    p = ROOT / rel
    if not p.exists():
        return [f"未命中 {rel} 不存在"]
    rx = re.compile(pattern)
    hits = []
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if rx.search(line):
            hits.append(f"命中  {rel}:{i}: {line.strip()[:96]}")
            if len(hits) >= limit:
                break
    return hits or [f"未命中 {rel} 无 `{pattern}` 命中"]


def p0_2() -> list[str]:
    out = [_exists("backend/core/backup/tasks.py")]
    out += _grep("backend/core/redis.py", r"core\.backup", 2)
    out += _grep("docker-compose.yml", r"walarchive", 1)
    out += _grep("backend/core/observability/metrics.py", r"archive_mode", 1)
    return out


def p0_3() -> list[str]:
    out = [_exists(f"observability/{n}") for n in
           ("prometheus.yml", "alert_rules.yml", "alertmanager.yml")]
    out += _grep("docker-compose.yml", r"^\s{2}(prometheus|alertmanager):", 2)
    return out


def p0_4() -> list[str]:
    out = _grep("docker-compose.yml", r'-\s*"[0-9.]+:\d+:\d+"', 8)
    out += _grep("docker-compose.yml", r"^\s*(POSTGRES_PASSWORD|DATABASE_URL):", 3)
    out += [f"说明  端口行若为 `127.0.0.1:...` 即已收窄；"
            f"口令若为 `${{POSTGRES_PASSWORD:-默认}}` 即「可覆盖但默认值明文」"]
    return out


def p0_5() -> list[str]:
    out = [_exists("backend/core/audit/models.py"),
           _exists("backend/core/audit/router.py")]
    out += _grep("backend/core/audit/models.py", r'__tablename__\s*=\s*"audit_logs"', 1)
    out += _grep("backend/main.py", r"audit_router", 2)
    return out


def p0_6() -> list[str]:
    out = [_exists("backend/modules/amazon_sp/router.py"),
           _exists("backend/modules/amazon_sp/oauth.py")]
    out += _grep("backend/main.py", r"amazon_sp_router", 2)
    return out


def p0_7() -> list[str]:
    out = [_exists("backend/modules/prompt_versions/")]
    mig = sorted((BACKEND / "alembic" / "versions").glob("*prompt_versions*.py"))
    out.append(f"命中  迁移文件 {mig[0].name}" if mig else "未命中 无 prompt_versions 迁移")
    out += _grep("backend/main.py", r"prompt_versions_router", 2)
    return out


def p0_9() -> list[str]:
    d = ROOT / "docs" / "legal"
    if not d.exists():
        return ["未命中 docs/legal/ 不存在"]
    out = [f"命中  docs/legal/ 下 {len([x for x in d.iterdir() if x.is_file()])} 个文件"]
    for x in sorted(d.iterdir()):
        if x.is_file():
            out.append(f"      · {x.name}")
    out.append(("命中  仓库根 LICENSE 存在" if (ROOT / "LICENSE").exists()
                else "未命中 仓库根无 LICENSE"))
    return out


def p0_10() -> list[str]:
    out = [_exists(".github/workflows/cd.yml")]
    out += _grep(".github/workflows/cd.yml", r"registry:|ssh .*deploy", 2)
    out.append("说明  ★ 流水线就位 ≠ 已生效：缺部署机密时它静默「只构建不部署」")
    return out


CHECKS = [
    ("P0-2", "零数据库备份 / 无 PITR", p0_2),
    ("P0-3", "零告警", p0_3),
    ("P0-4", "compose 明文口令 + 5432 全网卡", p0_4),
    ("P0-5", "无审计日志", p0_5),
    ("P0-6", "SP-API 授权链路未实现", p0_6),
    ("P0-7", "提示词 100% 硬编码、零版本", p0_7),
    ("P0-9", "无用户协议 / 隐私政策", p0_9),
    ("P0-10", "无 CD 流水线", p0_10),
]


def main() -> int:
    print("=" * 78)
    print("P0 阻断项 · 证据采集（口径见 docs/technical-diligence-review-20260930.md 附录 A）")
    print(f"仓库根：{ROOT}")
    print("★ 本脚本只打印证据行；「已修 / 未修」由人读完判定（含「部分修」这类非二值情形）")
    print("=" * 78)
    for pid, name, fn in CHECKS:
        print(f"\n[{pid}] {name}")
        for line in fn():
            print("  " + line)
    print("\n" + "=" * 78)
    print("采集完毕。若与文档不一致 ⇒ 更新文档（而不是相信文档）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
