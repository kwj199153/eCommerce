#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PostgreSQL **时间点恢复（PITR）**：WAL 归档 + 基础备份 + 恢复演练（第 351 轮 / P0-2）

为什么还需要它（`backup_db.py` 已经在做备份了）
----------------------------------------------
`backup_db.py` 做的是 **逻辑备份**（`pg_dump`）：产物是「某一张表当时长什么样」的
SQL 脚本，恢复粒度 = **一次 dump 的时间点**。它答不了这一类问题：

    「今天 14:03 那条 UPDATE 把 380 条订单的状态刷错了 —— 请把库恢复成 14:02 的样子，
      但 14:00 之后新签的那两单**要保留**。」

`pg_dump` 只有「整库回退到昨天 23:00」这一个答案，代价是丢掉从那以后的一切。
**PITR（point-in-time recovery）** 才是那个答案：一个物理全量基线 + 之后每一个
WAL 段 ⇒ 可以恢复到**任意一个 LSN / 时间点 / 具名还原点**。

缺的到底是什么（本仓 r350 的实测口径）
--------------------------------------
    ✘ `wal_level` / `archive_mode` / `pg_basebackup` 在**生产代码**中 0 命中

也就是说：`pgdata` 卷里只有一个「当前状态」，没有任何**增量历史**。
`archive_mode=off` 的库，两个检查点之间的数据只存在于 `pg_wal` 里，段被回收即永久消失
—— 误操作与备份之间的那段窗口**不可恢复**。

本脚本做四件事（子命令）
------------------------
    status          现算归档现状：`wal_level`/`archive_mode`/`archive_command` +
                    `pg_stat_archiver` 读数（**判据取自库本身，不是看配置文件**）
    enable          打开 WAL 归档（`ALTER SYSTEM` + 归档目录 + 重启 + **自证**：
                    真切一个段、真看到它落到归档目录、`failed_count` 必须为 0）
    archive-fetch   把容器内归档目录的段**外送**到宿主 `backups/wal/`（逐个核对字节数）
    basebackup      跑 `pg_basebackup` 落一份物理基线到 `backups/base/<ts>/` + 结构校验
    drill           真演练：基线 + 归档 ⇒ 起一个**临时容器**恢复到具名还原点，
                    并断言「还原点之前的写入在、之后的写入不在」

设计取向（与 `backup_db.py` 同源）
----------------------------------
· **在容器内执行** PG 客户端（`docker exec`）：宿主机不需要装同版本客户端，
  也不需要把口令写到命令行（容器内 local 连接是 trust）。
· **零第三方依赖**：只用标准库 + docker CLI。
· **绝不静默降级**：拿不到 `archive_mode=on` 就报错退出，不"退化成只 dump"。
  （本仓铁律：取不到禁静默退化 —— 全 0 兜底 = 假数据冒充实测。）

★★ 一条如实标注（不要把它当已解决）
-----------------------------------
归档目录落在**容器的可写层**（`/var/lib/postgresql/wal-archive`），而不是卷里 ——
因为 `my-postgres` 是 `docker run` 手工创建的，没有第二个挂载点，而给一个已有容器
**加挂载只能重建容器**。所以：

    `docker stop/start`  → 归档段**还在**（可写层存活）
    `docker rm -f`       → 未 `archive-fetch` 外送的段**丢失**

⇒ `archive-fetch` 是**必需步骤**而不是可选优化；生产部署应把该目录做成独立卷
   （见 `docker-compose.yml` 里 `postgres` 服务已预留的 `walarchive` 卷）。

用法
----
    python scripts/pg_pitr.py status
    python scripts/pg_pitr.py enable                  # 会重启 my-postgres
    python scripts/pg_pitr.py basebackup
    python scripts/pg_pitr.py archive-fetch
    python scripts/pg_pitr.py drill                   # 端到端真演练

退出码
    0 = 成功
    1 = 参数/环境错误（容器不在、归档未开启、docker 不可用…）
    2 = **校验失败**：拿到了产物但证明它不可用（基线结构坏 / 演练断言不成立）
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKUPS = REPO / "backups"
BASE_DIR = BACKUPS / "base"
WAL_DIR = BACKUPS / "wal"
MANIFEST = BACKUPS / "pitr-manifest.jsonl"

#: 物理基线保留份数。★ 与 `backup_db.py` 的 dump 保留份数**分开**：一份基线
#: ~= 全库（实测 ~12MB，随库增长），而它的作用只是"从哪开始回放" ——
#: 留 7 份（≈ 七周）是为了「上周那份基线本身也坏了」时还有退路，
#: 而不是因为"越多越安全"（WAL 段才是恢复粒度的来源）。
BASE_KEEP = 7

CONTAINER = "my-postgres"
PGUSER = "kevin"
PGDB = "postgres"
PG_IMAGE = "postgres:15-alpine"

#: 容器内归档目录。★ 见文件头「一条如实标注」：它在可写层，`docker rm` 即丢，
#: 所以 `archive-fetch` 是必需步骤。
ARCHIVE_IN_CONTAINER = "/var/lib/postgresql/wal-archive"

#: `archive_command`。语义：**幂等**（已存在就不覆盖）+ 失败必须返回非 0。
#: `test ! -f` 这半句不能省：PG 在归档失败时会重试同一个段，覆盖写会让
#: 「归档成功但内容被后来者改过」成为可能，而 `.done` 标记已经写下了。
ARCHIVE_COMMAND = (
    f"test ! -f {ARCHIVE_IN_CONTAINER}/%f && cp %p {ARCHIVE_IN_CONTAINER}/%f"
)

#: 演练用的具名还原点 / 库 / 表。用具名还原点而不是 `recovery_target_time`：
#: 后者依赖时钟粒度与事务提交时间对齐，前者是 WAL 里一条明确定位的记录。
RESTORE_POINT = "r351_pitr_drill"
DRILL_DB = "pitr_drill"
DRILL_TABLE = "pitr_marker"

EXIT_OK, EXIT_USAGE, EXIT_VERIFY_FAILED = 0, 1, 2


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw
    )


def _die(msg: str, code: int = EXIT_USAGE) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _docker_ok(container: str) -> bool:
    r = _run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    return r.returncode == 0 and r.stdout.strip() == "true"


def _require_container() -> None:
    if shutil.which("docker") is None:
        _die("找不到 docker CLI")
    if not _docker_ok(CONTAINER):
        _die(f"容器 {CONTAINER} 不在运行 —— 先 `docker start {CONTAINER}`")


def _psql(sql: str, db: str = PGDB, *, container: str = CONTAINER, user: str = PGUSER) -> str:
    """在容器内跑一条 SQL，返回裸值（`-tA`：无表头、无对齐）。"""
    r = _run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAc", sql])
    if r.returncode != 0:
        _die(f"psql 失败（{db}）：{sql}\n{(r.stderr or '').strip()}")
    return (r.stdout or "").strip()


def _exec(script: str, *, container: str = CONTAINER) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", container, "sh", "-c", script])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _append_manifest(row: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _wait_ready(container: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _run(["docker", "exec", container, "pg_isready", "-U", PGUSER, "-d", PGDB])
        if r.returncode == 0:
            return True
        time.sleep(1)
    return False


def _archiver() -> dict:
    """`pg_stat_archiver` 一行读数（键 → 值）。"""
    out = _psql(
        "SELECT archived_count, failed_count, "
        "coalesce(last_archived_wal,''), coalesce(last_failed_wal,''), "
        "coalesce(last_archived_time::text,'') FROM pg_stat_archiver"
    )
    parts = out.split("|")
    if len(parts) != 5:
        _die(f"pg_stat_archiver 读数解析失败：{out!r}")
    return {
        "archived_count": int(parts[0]),
        "failed_count": int(parts[1]),
        "last_archived_wal": parts[2],
        "last_failed_wal": parts[3],
        "last_archived_time": parts[4],
    }


def _switch_and_wait(timeout: int = 60) -> dict:
    """切一个 WAL 段并等它**真的**进归档目录。

    ★ 为什么要主动切：`archive_mode=on` 只是"完成时归档"，而一个 16MB 的段
      在低写入量的库上可能几小时都填不满 —— 那样"归档开了"这句话在事故当天
      等价于"没有归档"。主动切一次，把"开关有没有生效"变成一个**当场可判**的事实。
    """
    before = _archiver()
    _psql("SELECT pg_switch_wal()")
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = _archiver()
        if now["failed_count"] > before["failed_count"]:
            _die(
                f"归档失败：failed_count {before['failed_count']} → {now['failed_count']}，"
                f"last_failed_wal={now['last_failed_wal']}",
                EXIT_VERIFY_FAILED,
            )
        if now["archived_count"] > before["archived_count"]:
            return now
        time.sleep(1)
    _die(f"等了 {timeout}s 也没等到新段归档（archived_count 未增长）", EXIT_VERIFY_FAILED)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
def cmd_status(_a: argparse.Namespace) -> int:
    _require_container()
    print("=== PostgreSQL 归档现状（判据取自库本身）===")
    for name in ("wal_level", "archive_mode", "archive_command", "data_directory"):
        print(f"  {name:<18} = {_psql(f'SHOW {name}')}")
    a = _archiver()
    for k, v in a.items():
        print(f"  {k:<18} = {v}")

    ok = _psql("SHOW archive_mode") == "on"
    print(f"\n归档：{'已开启' if ok else '**未开启**（PITR 不可用）'}")
    print(f"宿主 WAL 外送目录：{WAL_DIR}"
          f"（{'存在，' + str(len(list(WAL_DIR.glob('*')))) + ' 个文件' if WAL_DIR.exists() else '尚不存在'}）")
    print(f"宿主物理基线目录：{BASE_DIR}"
          f"（{'存在，' + str(len(list(BASE_DIR.iterdir()))) + ' 份' if BASE_DIR.exists() else '尚不存在'}）")
    return EXIT_OK if ok else EXIT_USAGE


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------
def cmd_enable(a: argparse.Namespace) -> int:
    _require_container()

    _exec(f"mkdir -p {ARCHIVE_IN_CONTAINER} && chown postgres:postgres {ARCHIVE_IN_CONTAINER} "
          f"&& chmod 700 {ARCHIVE_IN_CONTAINER}")

    already = _psql("SHOW archive_mode") == "on" and _psql("SHOW archive_command") == ARCHIVE_COMMAND
    if already and not a.force:
        print("归档已经是目标状态（archive_mode=on 且 archive_command 一致）—— 跳过重启")
    else:
        # ALTER SYSTEM 写进 postgresql.auto.conf（← 不碰人手维护的 postgresql.conf）
        _psql("ALTER SYSTEM SET archive_mode = 'on'")
        _psql(f"ALTER SYSTEM SET archive_command = '{ARCHIVE_COMMAND}'")
        print("已写入 postgresql.auto.conf：archive_mode=on")
        if a.no_restart:
            print("★ --no-restart：archive_mode 从 off → on **必须重启**才生效，"
                  "现在还没生效（status 会显示 off）")
            return EXIT_USAGE
        print(f"重启 {CONTAINER} …（archive_mode 是 postmaster 级参数，reload 不够）")
        r = _run(["docker", "restart", CONTAINER])
        if r.returncode != 0:
            _die(f"docker restart 失败：{(r.stderr or '').strip()}")
        if not _wait_ready(CONTAINER):
            _die(f"{CONTAINER} 重启后 60s 仍未就绪")

    # ---------------------------------------------------------------- 自证
    wal_level = _psql("SHOW wal_level")
    mode = _psql("SHOW archive_mode")
    cmd = _psql("SHOW archive_command")
    if mode != "on":
        _die(f"archive_mode 仍是 {mode!r}，不是 on", EXIT_VERIFY_FAILED)
    if wal_level != "replica" and wal_level != "logical":
        _die(f"wal_level={wal_level!r} —— 归档需要 replica 或更高", EXIT_VERIFY_FAILED)
    if cmd != ARCHIVE_COMMAND:
        _die(f"archive_command 与预期不一致：{cmd!r}", EXIT_VERIFY_FAILED)

    a2 = _switch_and_wait()
    listed = _exec(f"ls -1 {ARCHIVE_IN_CONTAINER}").stdout.split()
    if a2["last_archived_wal"] not in listed:
        _die(
            f"库说已归档 {a2['last_archived_wal']}，但归档目录里没有它（目录内容：{listed}）",
            EXIT_VERIFY_FAILED,
        )
    size = _exec(f"stat -c %s {ARCHIVE_IN_CONTAINER}/{a2['last_archived_wal']}").stdout.strip()
    print(f"\nRESULT: OK  归档已生效；刚归档的段 = {a2['last_archived_wal']}（{size} bytes）")
    print(f"             archived_count={a2['archived_count']}  failed_count={a2['failed_count']}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# archive-fetch
# ---------------------------------------------------------------------------
def _prune_base(keep: int) -> list[str]:
    """只保留最近 `keep` 份物理基线（按目录名 = 时间戳排序）。

    返回被删掉的目录名。★ 刻意**不**按 `META.json` 里的 `created_at` 排：
    目录名就是 `_stamp()` 的产物（`YYYYmmdd-HHMMSS`），同精度、且不会因为
    META 被改坏而排序错乱 —— 排序键要选**不会被人手编辑**的那个。
    """
    if not BASE_DIR.is_dir() or keep <= 0:
        return []
    dirs = sorted((p for p in BASE_DIR.iterdir() if p.is_dir()), key=lambda p: p.name)
    if len(dirs) <= keep:
        return []
    removed: list[str] = []
    for d in dirs[:-keep]:
        _run(["rm", "-rf", str(d)])
        removed.append(d.name)
    return removed


def cmd_archive_fetch(_a: argparse.Namespace) -> int:
    """把容器内的归档段**外送**到宿主，并逐个核对字节数。

    ★ 为什么这不是可选优化：归档目录在容器可写层（见文件头），`docker rm` 即丢。
      且这里必须**核对大小**而不是"cp 完就算" —— 本仓 `backup_db.py` 已经记过
      「dump 返回 0 ≠ 备份可用」，同一条道理对 `docker cp` 同样成立。
    """
    _require_container()
    WAL_DIR.mkdir(parents=True, exist_ok=True)

    r = _exec(f"ls -1 {ARCHIVE_IN_CONTAINER} 2>/dev/null")
    names = [n for n in r.stdout.split() if n.endswith(".partial") is False]
    if not names:
        print("归档目录里暂无可外送的段（还没产生过切换）")
        return EXIT_OK

    sizes_in: dict[str, int] = {}
    for n in names:
        s = _exec(f"stat -c %s {ARCHIVE_IN_CONTAINER}/{n}").stdout.strip()
        sizes_in[n] = int(s)

    copied = 0
    bad: list[str] = []
    for n in names:
        target = WAL_DIR / n
        if target.exists() and target.stat().st_size == sizes_in[n]:
            continue  # 幂等：同名同大小 = 已外送过
        r = _run(["docker", "cp", f"{CONTAINER}:{ARCHIVE_IN_CONTAINER}/{n}", str(target)])
        if r.returncode != 0:
            bad.append(f"{n}: docker cp 失败 {(r.stderr or '').strip()}")
            continue
        if target.stat().st_size != sizes_in[n]:
            bad.append(f"{n}: 大小不符 容器={sizes_in[n]} 宿主={target.stat().st_size}")
            continue
        copied += 1

    if bad:
        _die("外送校验失败：\n  " + "\n  ".join(bad), EXIT_VERIFY_FAILED)

    total = sum(p.stat().st_size for p in WAL_DIR.glob("*"))
    print(f"RESULT: OK  外送 {copied} 个新段（目录现有 {len(list(WAL_DIR.glob('*')))} 个 / {total} bytes）")
    return EXIT_OK


# ---------------------------------------------------------------------------
# basebackup
# ---------------------------------------------------------------------------
def _basebackup(label: str) -> Path:
    """跑一次 `pg_basebackup`，落盘到 `backups/base/<ts>/` 并做结构校验。"""
    tmp = "/tmp/pg_basebackup"
    _exec(f"rm -rf {tmp}")
    r = _exec(
        f"pg_basebackup -U {PGUSER} -D {tmp} -Ft -z -X fetch -c fast -l '{label}'"
    )
    if r.returncode != 0:
        _die(f"pg_basebackup 失败：{(r.stderr or '').strip()[:400]}", EXIT_VERIFY_FAILED)

    # ★ 结构校验必须在**删掉容器内副本之前**做：
    #   `pg_basebackup` 返回 0 只说明它没主动报错；磁盘写满 / 管道截断同样可能
    #   留下一个不完整的 tar。把它真正读一遍（`tar tzf` 会逐块校验 gzip CRC）。
    chk = _exec(f"tar tzf {tmp}/base.tar.gz > /tmp/_toc 2>/tmp/_err; echo $?; "
                f"grep -c . /tmp/_toc; grep -E '^(PG_VERSION|backup_label)$' /tmp/_toc")
    lines = (chk.stdout or "").split("\n")
    if lines[0].strip() != "0":
        err = _exec("cat /tmp/_err").stdout.strip()
        _die(f"基线 tar 解不开（可能被截断）：{err[:300]}", EXIT_VERIFY_FAILED)
    entries = int(lines[1]) if len(lines) > 1 and lines[1].strip().isdigit() else 0
    names = {ln.strip() for ln in lines[2:] if ln.strip()}
    missing = {"PG_VERSION", "backup_label"} - names
    if missing:
        _die(f"基线 tar 缺关键条目 {sorted(missing)}（entries={entries}）", EXIT_VERIFY_FAILED)

    outdir = BASE_DIR / _stamp()
    outdir.mkdir(parents=True, exist_ok=True)
    r = _run(["docker", "cp", f"{CONTAINER}:{tmp}/.", str(outdir)])
    if r.returncode != 0:
        _die(f"docker cp 基线失败：{(r.stderr or '').strip()}")
    _exec(f"rm -rf {tmp}")

    tar = outdir / "base.tar.gz"
    if not tar.is_file():
        _die(f"外送后找不到 {tar}", EXIT_VERIFY_FAILED)

    lsn = _psql("SELECT pg_current_wal_lsn()")
    (outdir / "META.json").write_text(
        json.dumps(
            {
                "label": label,
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                "wal_lsn_at_backup": lsn,
                "entries": entries,
                "bytes": tar.stat().st_size,
                "sha256": _sha256(tar),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  基线 tar 条目数 = {entries}（含 PG_VERSION / backup_label）")
    print(f"  LSN@backup = {lsn}")
    return outdir


def cmd_basebackup(a: argparse.Namespace) -> int:
    _require_container()
    if _psql("SHOW archive_mode") != "on":
        _die("archive_mode=off —— 没有 WAL 归档，单有物理基线**无法**做 PITR。"
             "先跑 `pg_pitr.py enable`")
    label = a.label or f"r351-{_stamp()}"
    print(f"pg_basebackup（label={label}）…")
    outdir = _basebackup(label)
    tar = outdir / "base.tar.gz"
    _append_manifest({
        "kind": "basebackup",
        "label": label,
        "path": str(tar.relative_to(REPO)).replace("\\", "/"),
        "bytes": tar.stat().st_size,
        "sha256": _sha256(tar),
        "at": dt.datetime.now().isoformat(timespec="seconds"),
    })
    # ★ 轮转：一份基线 ~= 全库（实测 ~12MB）。不轮转的话 `backups/base/` 会
    #   无界增长，和 `backup_db.py` 的 `--keep` 精神不一致。
    #   ★ 只在**这个子命令**里轮转，不在 `_basebackup()` 里 —— `drill` 也要调
    #     `_basebackup()`，如果轮转写在那里，一次演练可能把上一份基线删掉，
    #     而那时候它正被用来证明"恢复可用"。
    pruned = _prune_base(a.keep)
    if pruned:
        print(f"  轮转：删除 {len(pruned)} 份旧基线（保留最近 {a.keep} 份）")
    print(f"RESULT: OK  {tar}（{tar.stat().st_size} bytes）")
    return EXIT_OK


# ---------------------------------------------------------------------------
# drill
# ---------------------------------------------------------------------------
def _drill_setup_marker() -> None:
    """建演练库/表（幂等）。★ 用**独立库**，绝不往业务表里写演练数据。"""
    exists = _psql(f"SELECT 1 FROM pg_database WHERE datname='{DRILL_DB}'")
    if exists != "1":
        _psql(f'CREATE DATABASE {DRILL_DB}')
    _psql(
        f"DROP TABLE IF EXISTS {DRILL_TABLE}; "
        f"CREATE TABLE {DRILL_TABLE}(id serial PRIMARY KEY, note text NOT NULL, at timestamptz DEFAULT now())",
        db=DRILL_DB,
    )


def _drill_cleanup(container: str, volume: str) -> None:
    _run(["docker", "rm", "-f", container])
    _run(["docker", "volume", "rm", "-f", volume])


def cmd_drill(a: argparse.Namespace) -> int:
    """端到端演练：**基线 + 归档 ⇒ 恢复到具名还原点**，并断言前后两侧的写入。

    判据设计（这是本脚本真正的"牙齿"）：
        ① 在还原点**之前**写一行 A  → 恢复到该点后 **A 必须在**；
        ② 在还原点**之后**写一行 B  → 恢复到该点后 **B 必须不在**。
    只有"在"或只有"不在"都可能恒真（比如恢复根本没跑、库是空的）；
    两条一起才证明**恢复确实停在了那个点**上。
    """
    _require_container()
    if _psql("SHOW archive_mode") != "on":
        _die("archive_mode=off —— 先跑 `pg_pitr.py enable`")

    # ★ 一次演练只取**一个**时间戳：卷名 / 容器名 / 工作目录必须成组对应，
    #   否则排查时看到的名字对不上，清理也会漏。
    run_id = _stamp()
    volume = f"pgpitr-{run_id}"
    container = f"pgpitr-drill-{run_id}"
    workdir = BACKUPS / f"pitr-drill-{run_id}"
    keep = bool(a.keep)
    print("[1/6] 建演练库/表（独立库，不碰业务表）")
    _drill_setup_marker()

    print("[2/6] 取物理基线（必须在还原点**之前**）")
    outdir = _basebackup(f"drill-{_stamp()}")

    print("[3/6] 写还原点两侧的数据")
    _psql(f"INSERT INTO {DRILL_TABLE}(note) VALUES ('A-before-restore-point')", db=DRILL_DB)
    _psql(f"SELECT pg_create_restore_point('{RESTORE_POINT}')")
    _psql(f"INSERT INTO {DRILL_TABLE}(note) VALUES ('B-after-restore-point')", db=DRILL_DB)
    side = _psql(
        f"SELECT count(*) FILTER (WHERE note LIKE 'A-%'), "
        f"count(*) FILTER (WHERE note LIKE 'B-%') FROM {DRILL_TABLE}",
        db=DRILL_DB,
    )
    print(f"      源库当前：A={side.split('|')[0]} B={side.split('|')[1]}")

    print("[4/6] 切段 + 等归档 + 外送到宿主")
    _switch_and_wait()
    rc = cmd_archive_fetch(argparse.Namespace())
    if rc != EXIT_OK:
        _die("外送 WAL 失败", rc)

    print("[5/6] 起临时容器恢复")
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "extra.conf").write_text(
        f"restore_command = 'cp /wal-archive/%f %p'\n"
        f"recovery_target_name = '{RESTORE_POINT}'\n"
        f"recovery_target_action = 'promote'\n"
        f"archive_mode = 'off'\n",  # 演练容器不需要再归档，避免它去写不存在的目录
        encoding="utf-8",
    )
    _run(["docker", "volume", "create", volume])
    prep = _run([
        "docker", "run", "--rm", "--entrypoint", "sh",
        "-v", f"{volume}:/pgdata",
        "-v", f"{outdir}:/src:ro",
        "-v", f"{workdir}:/work:ro",
        PG_IMAGE,
        "-c",
        "set -e; "
        "tar xzf /src/base.tar.gz -C /pgdata; "
        "cat /work/extra.conf >> /pgdata/postgresql.auto.conf; "
        "touch /pgdata/recovery.signal; "
        "chown -R postgres:postgres /pgdata; "
        # ★ PG 拒绝启动在权限过宽的 data dir 上（FATAL: data directory has invalid
        #   permissions，要求 0700 或 0750）。`docker volume create` 出来的挂载点
        #   默认 0755，tar 解包**不会**改它 —— 必须显式收权限。
        #   同一坑也会发生在 pg_wal 上：那里的权限从 tar 里带出来，通常没问题。
        "chmod 0700 /pgdata; "
        "chmod 0700 /pgdata/pg_wal 2>/dev/null || true",
    ])
    if prep.returncode != 0:
        _drill_cleanup(container, volume)
        _die(f"铺基线失败：{(prep.stderr or '').strip()[:400]}", EXIT_VERIFY_FAILED)

    r = _run([
        "docker", "run", "-d", "--name", container,
        "-u", "postgres", "--entrypoint", "postgres",
        "-v", f"{volume}:/var/lib/postgresql/data",
        "-v", f"{WAL_DIR}:/wal-archive:ro",
        PG_IMAGE,
        "-D", "/var/lib/postgresql/data",
    ])
    if r.returncode != 0:
        _drill_cleanup(container, volume)
        _die(f"启动演练容器失败：{(r.stderr or '').strip()[:400]}", EXIT_VERIFY_FAILED)

    if not _wait_ready(container, timeout=90):
        logs = _run(["docker", "logs", "--tail", "40", container]).stdout
        if not keep:
            _drill_cleanup(container, volume)
        _die(f"演练容器 90s 未就绪。日志尾部：\n{logs[-1500:]}", EXIT_VERIFY_FAILED)

    print("[6/6] 断言：还原点之前**在**、之后**不在**")
    in_recovery = _psql("SELECT pg_is_in_recovery()", container=container)
    a_cnt = _psql(
        f"SELECT count(*) FROM {DRILL_TABLE} WHERE note LIKE 'A-%'", db=DRILL_DB, container=container
    )
    b_cnt = _psql(
        f"SELECT count(*) FROM {DRILL_TABLE} WHERE note LIKE 'B-%'", db=DRILL_DB, container=container
    )
    last = _psql(
        "SELECT coalesce(max(at)::text,'') FROM " + DRILL_TABLE, db=DRILL_DB, container=container
    )
    print(f"      pg_is_in_recovery = {in_recovery}")
    print(f"      A（还原点之前）= {a_cnt}   B（还原点之后）= {b_cnt}")
    print(f"      恢复后最后一行时间 = {last}")

    problems: list[str] = []
    if in_recovery != "f":
        problems.append(f"pg_is_in_recovery={in_recovery} —— 没完成 promote，仍是只读备库")
    if a_cnt != "1":
        problems.append(f"还原点**之前**的 A 行没恢复出来（count={a_cnt}）")
    if b_cnt != "0":
        problems.append(f"还原点**之后**的 B 行不该出现，却出现了（count={b_cnt}）—— 目标点没生效")

    _append_manifest({
        "kind": "pitr-drill",
        "restore_point": RESTORE_POINT,
        "base": str(outdir.relative_to(REPO)).replace("\\", "/"),
        "in_recovery": in_recovery,
        "a_before": a_cnt,
        "b_after": b_cnt,
        "ok": not problems,
        "at": dt.datetime.now().isoformat(timespec="seconds"),
    })

    if keep:
        print(f"★ --keep：演练容器 {container} / 卷 {volume} 保留（排查用）；"
              f"清理：docker rm -f {container} && docker volume rm {volume}")
    else:
        _drill_cleanup(container, volume)
        _psql(f'DROP DATABASE IF EXISTS {DRILL_DB}')
        _run(["rm", "-rf", str(workdir)])

    if problems:
        _die("PITR 演练断言不成立：\n  " + "\n  ".join(problems), EXIT_VERIFY_FAILED)
    print(f"RESULT: OK  恢复到还原点 {RESTORE_POINT}：之前的写入保留、之后的写入被丢弃")
    return EXIT_OK


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pg_pitr.py",
        description="PostgreSQL WAL 归档 / 物理基线 / 时间点恢复演练（P0-2 · 第 351 轮）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="现算归档现状（含 pg_stat_archiver 读数）")

    e = sub.add_parser("enable", help="打开 WAL 归档（会重启 my-postgres）")
    e.add_argument("--no-restart", action="store_true", help="只写配置不重启（用于排错）")
    e.add_argument("--force", action="store_true", help="已是目标状态也重写 + 重启")

    sub.add_parser("archive-fetch", help="把容器内归档段外送到 backups/wal/（逐个核对大小）")

    b = sub.add_parser("basebackup", help="取一份物理基线到 backups/base/<ts>/")
    b.add_argument("--label", default="", help="pg_basebackup 的 label")
    b.add_argument("--keep", type=int, default=BASE_KEEP, help=f"保留最近 N 份基线（默认 {BASE_KEEP}）")

    d = sub.add_parser("drill", help="端到端 PITR 演练（起临时容器恢复到具名还原点）")
    d.add_argument("--keep", action="store_true", help="保留演练容器/卷以便排查")
    return p


def main() -> int:
    args = build_parser().parse_args()
    handlers = {
        "status": cmd_status,
        "enable": cmd_enable,
        "archive-fetch": cmd_archive_fetch,
        "basebackup": cmd_basebackup,
        "drill": cmd_drill,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
