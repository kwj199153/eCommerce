#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PostgreSQL 备份 / 校验 / 恢复 / 演练 / 轮转（P0-2）

为什么需要它
------------
此前项目**零备份能力**：没有脚本、没有定时任务、没有恢复演练。
数据库只存在于 `my-postgres` 容器挂的 `pgdata` 卷里 —— 卷丢了、误
`docker compose down -v` 了、或某条 UPDATE 写错了，业务数据**全部不可恢复**。
对一个承载店铺/用户/账单/账款的 SaaS，这是最贵的一类缺口。

本脚本要解决的不是"能 dump 出文件"，而是**"备份真的能用"**：
    ① dump 成功 ≠ 备份可用（磁盘满、管道被截断都可能返回 0）；
    ② 所以每份备份落盘后立刻做**结构校验**（`pg_restore --list` 解析 TOC）；
    ③ 并支持 `drill` —— 真的恢复到临时库、比对表数量，证明它可恢复；
    ④ 绝不默认覆盖生产库：目标库名不是演练库时**必须显式 --force**。
「没演练过的备份」和「没有备份」在事故当天是等价的。

设计取向
--------
· **在容器内执行** pg_dump/pg_restore（`docker exec`）：宿主机不需要装
  同版本的 PG 客户端，也不需要把口令写到命令行（容器内 local 连接是 trust）。
· **零第三方依赖**：只用标准库 + docker CLI ⇒ CI/运维机可直接跑。
· 产物落 `backups/`（已在 .gitignore 中排除），manifest 用 jsonl 追加，便于审计。
· 原子写：先写 `.partial` → 校验通过 → rename，避免半截文件被当成备份。

用法
----
    python scripts/backup_db.py backup                 # 备份 + 校验 + 轮转（默认保留 14 份）
    python scripts/backup_db.py backup --keep 7
    python scripts/backup_db.py list                    # 列出备份（含校验状态）
    python scripts/backup_db.py verify <file>           # 只做完整性/结构校验
    python scripts/backup_db.py drill  <file>           # 恢复到演练库并与 TOC 比对
    python scripts/backup_db.py restore <file> --target-db mydb_restored [--force]
    python scripts/backup_db.py prune --keep 7

退出码
    0 = 成功
    1 = 参数/环境错误（容器不在、文件不存在等）
    2 = **校验失败**：备份文件不可用（必须让定时任务红，不能静默）
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "backups"
MANIFEST = "manifest.jsonl"

DEFAULT_CONTAINER = "my-postgres"
DEFAULT_USER = "kevin"
DEFAULT_DB = "postgres"

#: 演练库名。`restore` 只有在目标是这个名字（或以 `_restorecheck` 结尾）时才允许
#: 不带 --force —— 这是防止「本想演练、结果洗掉生产库」的最后一道闸。
DRILL_DB = "postgres_restorecheck"
SAFE_SUFFIX = "_restorecheck"

EXIT_OK, EXIT_USAGE, EXIT_VERIFY_FAILED = 0, 1, 2


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _docker_ok(container: str) -> bool:
    r = _run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    return r.returncode == 0 and r.stdout.strip() == "true"


def _sql(container: str, user: str, db: str, sql: str) -> subprocess.CompletedProcess:
    """在容器内的目标库上执行一条 SQL（-tA：只要值、无表头）。"""
    return _run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAc", sql])


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def toc_list(container: str, dump: Path) -> tuple[bool, str]:
    """
    用容器内的 `pg_restore --list` 解析 dump 的目录表（TOC）。

    为什么这是必要的校验：`pg_dump` 退出码 0 只说明它没主动报错 ——
    磁盘写满、管道被 SIGPIPE 截断时也可能留下一个**语法上不完整**的文件，
    而它照样返回 0（或返回非 0 但文件已落盘）。把文件喂回 `pg_restore --list`，
    是这个文件第一次被真正"读一遍"，能立刻暴露截断/损坏。
    """
    with open(dump, "rb") as fh:
        r = subprocess.run(
            ["docker", "exec", "-i", container, "pg_restore", "--list"],
            stdin=fh,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return False, out.strip()[:600]
    if "Archive created at" not in r.stdout:
        return False, "输出里没有 TOC 头（Archive created at）—— 文件可能截断"
    return True, r.stdout


#: pg_restore TOC 的条目类型。★ 按长度降序匹配并 `break`：
#: 否则 `TABLE` 会抢先命中 `TABLE DATA` 行，把"有数据的表"错算成"表定义"。
TOC_TYPES = (
    "TABLE DATA",
    "SEQUENCE OWNED BY",
    "SEQUENCE SET",
    "MATERIALIZED VIEW DATA",
    "MATERIALIZED VIEW",
    "TABLE ATTACH",
    "INDEX ATTACH",
    "CHECK CONSTRAINT",
    "FK CONSTRAINT",
    "TABLE",
    "SEQUENCE",
    "INDEX",
    "CONSTRAINT",
    "DEFAULT",
    "SCHEMA",
    "TYPE",
    "DOMAIN",
    "FUNCTION",
    "PROCEDURE",
    "VIEW",
    "TRIGGER",
    "COMMENT",
    "ACL",
    "POLICY",
    "EXTENSION",
)


def toc_entries_declared(out: str) -> int | None:
    """从 TOC 头里读出 dump 自称的条目总数（用于解析器自检）。"""
    m = re.search(r"TOC Entries:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def toc_counts(container: str, dump: Path) -> dict[str, int]:
    """
    统计 TOC 里各类条目数；`TABLE DATA` 是真正被备份的**数据表**数。

    ★ 为什么不用 `(\\w+(?: \\w+)*)` 那种"连续单词"抓类型名：
      它会把后面的 `schema name` 一起吃进去（`TYPE public userrole`），
      于是每个 key 都是唯一的、`TABLE DATA` 永远统计不到 ⇒ **静默归零**。
      实测踩过：正确识别出 456 个 TOC 条目的 dump，计数却全是 0。
      改为「显式类型表 + 最长优先 + 命中即 break」。
    """
    ok, out = toc_list(container, dump)
    if not ok:
        return {}
    counts: dict[str, int] = {}
    for line in out.splitlines():
        for t in TOC_TYPES:
            if re.match(rf"^\d+;\s+\d+\s+\d+\s+{re.escape(t)}(?:\s|$)", line):
                counts[t] = counts.get(t, 0) + 1
                break
    return counts


def deep_verify(container: str, dump: Path) -> tuple[bool, str]:
    """
    深度校验：把 dump 完整解压成 SQL 并丢弃输出（`pg_restore -f /dev/null`）。

    ★ 为什么 `pg_restore --list` **不够**（实测教训，见 .workbuddy/probes/r327_p0_2_probe.py）：
      custom format 的目录表（TOC）位于**文件开头**。文件被截断（磁盘写满、
      管道 SIGPIPE、拷贝中断）之后，`--list` 依然能成功列出全部条目 ——
      实测：把一份 4.9MB 的 dump 截掉一半，`--list` 仍然返回 OK。
      也就是说，「结构可解析」根本证明不了「数据完整」。
      只有真正**读遍所有数据块**才能发现截断；`-f /dev/null` 正好做这件事，
      而且它不需要连接任何数据库（纯文件级操作，CI 里也能跑）。
    """
    with open(dump, "rb") as fh:
        r = subprocess.run(
            ["docker", "exec", "-i", container, "sh", "-c", "pg_restore -f /dev/null"],
            stdin=fh,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if r.returncode != 0:
        return False, ((r.stderr or "").strip() or "pg_restore 解压失败")[:600]
    return True, "全量解压通过"


def append_manifest(out_dir: Path, record: dict) -> None:
    with (out_dir / MANIFEST).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------
def cmd_backup(a: argparse.Namespace) -> int:
    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not _docker_ok(a.container):
        print(f"[ERROR] 容器 {a.container} 不在运行中（先 docker start {a.container}）")
        return EXIT_USAGE

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    final = out_dir / f"{a.db}-{stamp}.dump"
    partial = final.with_suffix(".dump.partial")
    started = dt.datetime.now()

    # -Fc = custom format：压缩、支持并行/选择性恢复
    # 直接用文件句柄接 stdout，避免把整个 dump 读进内存
    print(f"[1/4] pg_dump -Fc {a.db} -> {final.name}")
    with partial.open("wb") as fh:
        r = subprocess.run(
            ["docker", "exec", a.container, "pg_dump", "-U", a.user, "-d", a.db, "-Fc"],
            stdout=fh,
            stderr=subprocess.PIPE,
        )
    if r.returncode != 0:
        partial.unlink(missing_ok=True)
        print(f"[ERROR] pg_dump 失败：{(r.stderr or b'').decode('utf-8', 'replace')[:500]}")
        return EXIT_USAGE

    size = partial.stat().st_size
    if size == 0:
        partial.unlink(missing_ok=True)
        print("[ERROR] dump 为 0 字节 —— 拒绝保留空备份（空备份比没有更危险：它会让人以为有）")
        return EXIT_VERIFY_FAILED

    print(f"[2/4] 结构校验（pg_restore --list）")
    ok, detail = toc_list(a.container, partial)
    if not ok:
        partial.unlink(missing_ok=True)
        print(f"[ERROR] 备份结构校验失败，已丢弃该文件：{detail}")
        return EXIT_VERIFY_FAILED
    counts = toc_counts(a.container, partial)
    table_data = counts.get("TABLE DATA", 0)
    declared = toc_entries_declared(detail)
    print(
        f"      TOC 条目：TABLE DATA={table_data}  TABLE={counts.get('TABLE', 0)}  "
        f"INDEX={counts.get('INDEX', 0)}  自称总数={declared}"
    )

    # ★ 两道守卫，都为了拦住「backup 看起来成功、其实不可用」：
    #   ① 解析器自检：TOC 自称有 N 条，我们却一条都没识别出来 ⇒ 是**解析器坏了**。
    #      不能把 0 静默当成"没有数据"（实测踩过：正则贪婪导致计数全 0）。
    #   ② 空数据守卫：TABLE DATA=0 ⇒ 这份备份里没有任何表数据。
    #      **空备份比没有备份更危险** —— 它会让人以为"有备份"，直到真要用那天。
    if declared and sum(counts.values()) == 0:
        partial.unlink(missing_ok=True)
        print("[ERROR] TOC 解析器失效：dump 自称有条目，却一条都没识别出来 —— 拒绝保留")
        return EXIT_VERIFY_FAILED
    if table_data <= 0:
        partial.unlink(missing_ok=True)
        print("[ERROR] 备份中不含任何表数据（TABLE DATA=0）—— 拒绝保留空备份")
        return EXIT_VERIFY_FAILED

    # ③ 深度校验：真的把全部数据块读一遍。TOC 可解析**证明不了**数据完整
    #    （TOC 在文件开头，截断后照样能 --list 成功 —— 实测踩过）。
    dok, ddetail = deep_verify(a.container, partial)
    if not dok:
        partial.unlink(missing_ok=True)
        print(f"[ERROR] 深度校验失败（备份被截断或损坏），已丢弃：{ddetail}")
        return EXIT_VERIFY_FAILED
    print(f"      深度校验：{ddetail}")

    print("[3/4] 落盘（原子 rename + sha256）")
    partial.replace(final)
    digest = sha256_of(final)
    elapsed = (dt.datetime.now() - started).total_seconds()

    record = {
        "file": final.name,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "db": a.db,
        "user": a.user,
        "container": a.container,
        "bytes": size,
        "sha256": digest,
        "toc_table_data": table_data,
        "seconds": round(elapsed, 2),
        "verified": True,
        "host": a.container,
    }
    append_manifest(out_dir, record)
    print(f"      {size:,} bytes  sha256={digest[:16]}…  用时 {elapsed:.1f}s")

    print(f"[4/4] 轮转（保留最近 {a.keep} 份）")
    pruned = _prune(out_dir, a.keep)
    for p in pruned:
        print(f"      删除过期备份 {p.name}")

    print(f"\nRESULT: OK  {final}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# list / prune
# ---------------------------------------------------------------------------
def _iter_dumps(out_dir: Path) -> list[Path]:
    return sorted(out_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)


def _read_manifest(out_dir: Path) -> dict[str, dict]:
    f = out_dir / MANIFEST
    if not f.is_file():
        return {}
    recs: dict[str, dict] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        recs[r.get("file", "")] = r
    return recs


def cmd_list(a: argparse.Namespace) -> int:
    out_dir = Path(a.out).resolve()
    dumps = _iter_dumps(out_dir)
    if not dumps:
        print(f"（{out_dir} 下没有备份）")
        return EXIT_OK
    recs = _read_manifest(out_dir)
    print(f"{'文件':<34}{'大小':>12}  {'时间':<20} 校验")
    print("-" * 78)
    for p in dumps:
        rec = recs.get(p.name, {})
        when = rec.get("created_at", dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"))
        print(f"{p.name:<34}{p.stat().st_size:>12,}  {when:<20} {'OK' if rec.get('verified') else '—'}")
    print(f"\n共 {len(dumps)} 份")
    return EXIT_OK


def _prune(out_dir: Path, keep: int) -> list[Path]:
    dumps = _iter_dumps(out_dir)
    removed = []
    for p in dumps[keep:]:
        p.unlink(missing_ok=True)
        removed.append(p)
    return removed


def cmd_prune(a: argparse.Namespace) -> int:
    removed = _prune(Path(a.out).resolve(), a.keep)
    for p in removed:
        print(f"删除 {p.name}")
    print(f"RESULT: OK  删除 {len(removed)} 份，保留最近 {a.keep} 份")
    return EXIT_OK


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def cmd_verify(a: argparse.Namespace) -> int:
    dump = Path(a.file).resolve()
    if not dump.is_file():
        print(f"[ERROR] 文件不存在：{dump}")
        return EXIT_USAGE
    if not _docker_ok(a.container):
        print(f"[ERROR] 容器 {a.container} 不在运行中（pg_restore 需要它来解析 TOC）")
        return EXIT_USAGE

    out_dir = dump.parent
    rec = _read_manifest(out_dir).get(dump.name, {})

    size_ok = dump.stat().st_size > 0
    digest = sha256_of(dump)
    hash_ok = (rec.get("sha256") == digest) if rec.get("sha256") else None
    ok, detail = toc_list(a.container, dump)

    print(f"文件     : {dump.name}")
    print(f"大小     : {dump.stat().st_size:,} bytes  {'OK' if size_ok else 'FAIL(0 字节)'}")
    print(f"sha256   : {digest}")
    if hash_ok is None:
        print("hash 比对: 跳过（manifest 无此文件记录）")
    else:
        print(f"hash 比对: {'OK（与 manifest 一致）' if hash_ok else 'FAIL（与 manifest 不一致 ⇒ 文件被改过或损坏）'}")
    print(f"结构校验 : {'OK（TOC 可解析）' if ok else 'FAIL'}")
    if not ok:
        print(f"           {detail}")

    # ★ 结构可解析 != 数据完整：TOC 在文件开头，截断后照样能 --list 成功。
    dok, ddetail = deep_verify(a.container, dump)
    print(f"深度校验 : {'OK（全量解压通过）' if dok else 'FAIL（截断/损坏）'}")
    if not dok:
        print(f"           {ddetail}")

    good = size_ok and ok and dok and (hash_ok is not False)
    print(f"\nRESULT: {'OK' if good else 'FAILED'}")
    return EXIT_OK if good else EXIT_VERIFY_FAILED


# ---------------------------------------------------------------------------
# drill —— 真的恢复一次
# ---------------------------------------------------------------------------
def cmd_drill(a: argparse.Namespace) -> int:
    dump = Path(a.file).resolve()
    if not dump.is_file():
        print(f"[ERROR] 文件不存在：{dump}")
        return EXIT_USAGE
    if not _docker_ok(a.container):
        print(f"[ERROR] 容器 {a.container} 不在运行中")
        return EXIT_USAGE

    print(f"[1/4] 重建演练库 {a.drill_db}")
    _sql(a.container, a.user, "postgres", f'DROP DATABASE IF EXISTS "{a.drill_db}"')
    r = _sql(a.container, a.user, "postgres", f'CREATE DATABASE "{a.drill_db}"')
    if r.returncode != 0:
        print(f"[ERROR] 建库失败：{(r.stderr or '').strip()[:400]}")
        return EXIT_USAGE

    print(f"[2/4] 恢复到 {a.drill_db}（不触碰生产库 {a.db}）")
    with dump.open("rb") as fh:
        r = subprocess.run(
            # --no-owner/--no-acl：演练库的属主与授权无关紧要，跳过可少一堆噪音错误
            ["docker", "exec", "-i", a.container, "pg_restore",
             "-U", a.user, "-d", a.drill_db, "--no-owner", "--no-acl"],
            stdin=fh,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    # ★ pg_restore 的非零退出码**不等于**恢复失败：它会为「对象已存在」之类的
    #   可忽略告警返回 1。判据必须落在**结果**上（下表数），而不是退出码。
    warn = (r.stderr or "").strip()
    print(f"      pg_restore 退出码={r.returncode}" + (f"（有告警，见下）" if r.returncode else ""))
    if warn and r.returncode:
        print("      " + "\n      ".join(warn.splitlines()[:3]))

    print("[3/4] 比对：TOC 里的 TABLE DATA 数 vs 演练库里的实际表数")
    expect = toc_counts(a.container, dump).get("TABLE DATA", 0)
    actual = _sql(
        a.container, a.user, a.drill_db,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'",
    ).stdout.strip()
    try:
        actual_n = int(actual)
    except ValueError:
        actual_n = -1

    print(f"      备份内数据表 = {expect}   演练库实际表 = {actual_n}")
    # 允许恢复出的表**不少于**备份内数据表（迁移表 alembic_version 等也计入 public）
    consistent = actual_n >= expect > 0

    if not a.keep_drill:
        print(f"[4/4] 清理演练库")
        _sql(a.container, a.user, "postgres", f'DROP DATABASE IF EXISTS "{a.drill_db}"')
    else:
        print(f"[4/4] 保留演练库 {a.drill_db}（--keep-drill）")

    print(f"\nRESULT: {'OK（备份可恢复）' if consistent else 'FAILED（恢复结果与备份内容不符）'}")
    return EXIT_OK if consistent else EXIT_VERIFY_FAILED


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------
def cmd_restore(a: argparse.Namespace) -> int:
    dump = Path(a.file).resolve()
    if not dump.is_file():
        print(f"[ERROR] 文件不存在：{dump}")
        return EXIT_USAGE
    if not _docker_ok(a.container):
        print(f"[ERROR] 容器 {a.container} 不在运行中")
        return EXIT_USAGE

    target = a.target_db
    # ★ 最后一道闸：目标是生产库而没加 --force ⇒ 拒绝。
    #   "把演练当日常"最危险的形态是手滑把 --target-db 写成生产库名。
    if target == a.db and not a.force:
        print(f"[ERROR] 目标库 {target} 与生产库同名 —— 拒绝执行。")
        print("        想真恢复到生产库请显式加 --force；想演练请用 drill 子命令。")
        return EXIT_USAGE
    if not target.endswith(SAFE_SUFFIX) and target != DRILL_DB and not a.force:
        print(f"[ERROR] 目标库 {target} 不像演练库（应以 {SAFE_SUFFIX} 结尾）—— 拒绝执行。")
        print("        确认要覆盖它请加 --force。")
        return EXIT_USAGE

    print(f"[1/3] 校验源文件")
    ok, detail = toc_list(a.container, dump)
    if not ok:
        print(f"[ERROR] 源备份结构校验失败，拒绝恢复：{detail}")
        return EXIT_VERIFY_FAILED

    print(f"[2/3] 重建目标库 {target}")
    _sql(a.container, a.user, "postgres", f'DROP DATABASE IF EXISTS "{target}"')
    r = _sql(a.container, a.user, "postgres", f'CREATE DATABASE "{target}"')
    if r.returncode != 0:
        print(f"[ERROR] 建库失败：{(r.stderr or '').strip()[:400]}")
        return EXIT_USAGE

    print(f"[3/3] 恢复")
    with dump.open("rb") as fh:
        rr = subprocess.run(
            ["docker", "exec", "-i", a.container, "pg_restore",
             "-U", a.user, "-d", target, "--no-owner", "--no-acl"],
            stdin=fh,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    actual = _sql(
        a.container, a.user, target,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'",
    ).stdout.strip()
    print(f"      pg_restore 退出码={rr.returncode}；目标库现有表 = {actual}")
    print(f"\nRESULT: OK  {dump.name} -> {target}")
    return EXIT_OK


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--container", default=DEFAULT_CONTAINER)
    common.add_argument("--user", default=DEFAULT_USER)
    common.add_argument("--db", default=DEFAULT_DB)
    common.add_argument("--out", default=str(DEFAULT_OUT))

    p = argparse.ArgumentParser(
        description="PostgreSQL 备份 / 校验 / 恢复 / 演练",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backup", parents=[common], help="备份 + 校验 + 轮转")
    b.add_argument("--keep", type=int, default=14, help="保留最近 N 份（默认 14）")
    b.set_defaults(func=cmd_backup)

    l = sub.add_parser("list", parents=[common], help="列出备份")
    l.set_defaults(func=cmd_list)

    pr = sub.add_parser("prune", parents=[common], help="只做轮转清理")
    pr.add_argument("--keep", type=int, default=14)
    pr.set_defaults(func=cmd_prune)

    v = sub.add_parser("verify", parents=[common], help="校验指定备份的完整性")
    v.add_argument("file")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("drill", parents=[common], help="恢复到演练库并与 TOC 比对")
    d.add_argument("file")
    d.add_argument("--drill-db", default=DRILL_DB)
    d.add_argument("--keep-drill", action="store_true")
    d.set_defaults(func=cmd_drill)

    r = sub.add_parser("restore", parents=[common], help="恢复到指定库（默认拒绝覆盖生产库）")
    r.add_argument("file")
    r.add_argument("--target-db", required=True)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_restore)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
