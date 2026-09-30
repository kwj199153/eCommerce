#!/usr/bin/env python3
"""CD 资产门禁：把「无 CD」这件事钉成可执行判据。

为什么需要它（而不是"看着没问题就行"）：
  CD 的三份资产（workflow / 部署脚本 / compose 插值）分居三个文件，
  它们之间的**一致性**没有任何编译器或测试会替你检查：
    · 脚本被写成 CRLF      → 远端 `bash -s` 报 `$'\\r': command not found`，
                             而本地 Git Bash 的 `bash -n` 照样通过（本地绿、远端红）
    · 镜像名两边改歪        → 构建推的是 A，compose 拉的是 B ⇒ 部署拉不到镜像
    · 回滚/健康检查被删掉  → 部署"看起来成功"，出事时无法恢复
    · 数据面被写进 up 列表 → 每次发版都 recreate 数据库
  这四条都属于「静默失效」：出错前毫无征兆，出错后极难定位。

★ 判据形态（按本仓铁律）：
  · 结构化判据优先：cd.yml 走 YAML 解析，不靠 grep 字符串包含；
  · shell 能力判据用**行首定义形态**（`^rollback\\(\\)`）而不是「文中出现过 rollback」——
    后者会被注释里的一个词骗过；
  · 镜像名对账用**集合相等**，不是「包含」：改名一侧立刻红。

反向注入自检（必须真能转红）：见 .workbuddy/probes/r333_cd_gate_injection.py
"""
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    print("[FAIL] 缺少 pyyaml：CI 里请先 `pip install pyyaml`（门禁不允许静默跳过）")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CD_YML = os.path.join(ROOT, ".github", "workflows", "cd.yml")
DEPLOY_SH = os.path.join(ROOT, "scripts", "deploy", "remote_deploy.sh")
COMPOSE = os.path.join(ROOT, "docker-compose.yml")

FAILS = []
PASSES = []
SKIPPED = []


def find_bash():
    """找一个**真正的 POSIX shell**。

    ★ 为什么不能直接 `subprocess.run(["bash", ...])`：
      Windows 上按 PATH 查找会命中 `C:\\Windows\\System32\\bash.exe` ——
      那是 **WSL 启动器**，不是 bash；它启动失败时只吐一段乱码，
      于是门禁报出「bash -n 不通过」而真因（找到了错的可执行文件）完全看不出来。
      本机实测就是这样假红了一次。
    ★ 找不到就返回 None，由调用方**显式 SKIP**（CI 的 ubuntu runner 必定有 /bin/bash，
      那才是这道门禁真正生效的地方）—— 绝不静默放过。
    """
    import shutil

    cands = []

    env_bash = os.environ.get("CD_GATE_BASH")
    if env_bash and os.path.isfile(env_bash):
        cands.append(env_bash)

    which = shutil.which("bash")
    if which:
        cands.append(which)

    # 从 git 的安装位置反推 Git Bash（git 一定在 PATH 里，本项目天天用）
    try:
        gp = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=10).stdout.strip()
        if gp:
            # <root>/mingw64/libexec/git-core  ->  <root>/bin/bash.exe
            root = os.path.dirname(os.path.dirname(os.path.dirname(gp)))
            for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe"), ("bin", "bash")):
                c = os.path.join(root, *rel)
                if os.path.isfile(c):
                    cands.append(c)
    except Exception:  # noqa: BLE001
        pass

    for c in cands:
        low = c.lower()
        # System32\bash.exe / wsl.exe 都是 WSL 入口，不是我们要的 shell
        if "system32" in low or "wsl" in low:
            continue
        return c
    return None


def check(name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        PASSES.append(name)
        print(f"  [PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILS.append(f"{name}" + (f"  ({detail})" if detail else ""))
        print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))
    return ok


def read_bytes(path: str):
    with open(path, "rb") as fh:
        return fh.read()


def main() -> int:
    print("=== CD 资产门禁 ===\n")

    # ---------- A. 存在性 ----------
    print("[A] 必需文件")
    for path, label in ((CD_YML, ".github/workflows/cd.yml"), (DEPLOY_SH, "scripts/deploy/remote_deploy.sh")):
        check(f"存在 {label}", os.path.isfile(path), path)

    if not os.path.isfile(CD_YML) or not os.path.isfile(DEPLOY_SH):
        print("\n[中止] 必需文件缺失，后续检查无意义")
        return 1

    cd_raw = read_bytes(CD_YML)
    sh_raw = read_bytes(DEPLOY_SH)
    sh_text = sh_raw.decode("utf-8")
    cd_text = cd_raw.decode("utf-8")

    # ---------- B. 行尾 ----------
    # ★ 用**字节计数**判 CRLF。踩过的坑：`grep -c $'\\r'` 在某些 shell 下
    #   `$'\\r'` 被展开成空串 ⇒ 变成 `grep -c ''` ⇒ 匹配每一行 ⇒ 得出
    #   「文件全是 CRLF」的**假警报**（本仓 r333 实测）。字节计数不会骗人。
    print("\n[B] 行尾")
    check("remote_deploy.sh 无 CR 字节（必须 LF）", sh_raw.count(b"\r") == 0,
          f"CR={sh_raw.count(b'\r')}；CRLF 会让远端 bash -s 报 $'\\r': command not found")
    check("cd.yml 无 CR 字节", cd_raw.count(b"\r") == 0, f"CR={cd_raw.count(b'\r')}")

    # ---------- C. shell 语法 ----------
    print("\n[C] 部署脚本语法")
    bash = find_bash()
    if bash is None:
        SKIPPED.append("bash -n 语法检查（本机未找到 Git Bash，仅 CI 执行）")
        print("  [SKIP] bash -n 语法检查（本机未找到 Git Bash —— 这一步在 CI 上才是真门禁）")
    else:
        try:
            proc = subprocess.run([bash, "-n", DEPLOY_SH], capture_output=True, text=True, timeout=30)
            # ★ bash -n 在 Git Bash 下**容忍 CRLF**，所以它绿**不能**替代 B 项。
            check(f"bash -n 通过（{os.path.basename(bash)}）", proc.returncode == 0,
                  (proc.stderr or "").strip()[:200])
        except Exception as exc:  # noqa: BLE001
            check("bash -n 通过", False, f"调用 bash 失败：{exc}")

    # ---------- D. 脚本能力形态 ----------
    print("\n[D] 部署脚本能力（行首定义形态，不靠「文中出现过」）")
    for fn in ("rollback", "upsert_env", "wait_ready"):
        check(f"定义了函数 {fn}()", re.search(rf"^{fn}\s*\(\)\s*\{{", sh_text, re.M) is not None)
    check("用 docker inspect 读容器真实状态", re.search(r"docker inspect", sh_text) is not None)
    check("幂等写 .env（upsert_env 被调用）",
          re.search(r"^\s*upsert_env\s+\w+", sh_text, re.M) is not None)
    # 只切业务服务：backend/worker/beat/frontend
    check("只 up 业务服务（backend worker beat frontend）",
          re.search(r"up -d backend worker beat frontend", sh_text) is not None)
    # 数据面护栏：绝不把 postgres/redis 写进 up 列表
    bad_data = re.findall(r"up -d[^\n]*\b(postgres|redis)\b", sh_text)
    check("up 列表不含数据面服务（postgres/redis）", not bad_data, f"命中 {bad_data}")
    check("失败以非 0 退出（die 定义）", re.search(r"^die\s*\(\)", sh_text, re.M) is not None)
    check("切服务前记录回滚点（.cd_rollback）", ".cd_rollback" in sh_text)

    # ---------- E. cd.yml 结构（YAML 解析） ----------
    print("\n[E] cd.yml 结构（YAML 解析）")
    try:
        doc = yaml.safe_load(cd_text)
    except Exception as exc:  # noqa: BLE001
        check("cd.yml 可被 YAML 解析", False, str(exc)[:200])
        doc = None
    if doc is not None:
        check("cd.yml 可被 YAML 解析", True)
        check("name == CD", doc.get("name") == "CD", repr(doc.get("name")))
        # YAML 1.1 把裸 `on:` 解析成布尔 True（不是字符串 'on'）
        triggers = doc.get("on") if "on" in doc else doc.get(True)
        check("声明了触发条件", triggers is not None)
        jobs = doc.get("jobs") or {}
        check("含 build job", "build" in jobs, f"jobs={sorted(jobs)}")
        check("含 deploy job", "deploy" in jobs, f"jobs={sorted(jobs)}")
        build = jobs.get("build") or {}
        deploy = jobs.get("deploy") or {}
        perms = build.get("permissions") or {}
        check("build 有 packages: write（推 GHCR 必需）", perms.get("packages") == "write", repr(perms))
        needs = deploy.get("needs")
        needs_set = {needs} if isinstance(needs, str) else set(needs or [])
        check("deploy 依赖 build", needs_set == {"build"}, repr(needs))
        env = deploy.get("environment")
        env_name = env if isinstance(env, str) else (env or {}).get("name")
        check("deploy 绑定 environment: production", env_name == "production", repr(env))
        # deploy 里必须有 ssh 调用（形态：run 里出现 `bash -s`）
        runs = "\n".join(str(s.get("run", "")) for s in (deploy.get("steps") or []) if isinstance(s, dict))
        check("deploy 含 ssh + `bash -s` 远端执行", "bash -s" in runs and "ssh " in runs)
        # 机密必须来自 secrets（不得硬编码）
        for key in ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_SSH_KEY", "DEPLOY_PATH"):
            check(f"引用 secrets.{key}", f"secrets.{key}" in cd_text)
        # matrix 里两个镜像名
        include = ((build.get("strategy") or {}).get("matrix") or {}).get("include") or []
        suffixes = {item.get("suffix") for item in include if isinstance(item, dict)}
        check("matrix 构建 2 个镜像", len(include) == 2, f"include={len(include)}")
    else:
        suffixes = set()

    # ---------- F. 镜像名对账（集合相等，不是包含） ----------
    print("\n[F] 镜像名对账：cd.yml 构建的 == compose 插值的默认值")
    if os.path.isfile(COMPOSE):
        compose_text = read_bytes(COMPOSE).decode("utf-8")
        # ★ 只取「**同时有 build 段**的服务」的 image 插值默认值 ——
        #   有 build 段 = 我们自己构建的镜像，那才是 CD 必须构建、compose 必须拉取的那组。
        #   第一版写成「扫全文所有 ${VAR:-...}」，把 POSTGRES_PASSWORD:-123456、
        #   DATABASE_URL:-postgresql+asyncpg://... 一并抓进来 ⇒ 集合必然不等 ⇒ **假红**。
        #   这是门禁自身的实现缺陷，不是资产缺陷 —— 假红同样有害（会逼人绕过门禁）。
        defaults = set()
        try:
            compose_doc = yaml.safe_load(compose_text) or {}
        except Exception as exc:  # noqa: BLE001
            compose_doc = {}
            print(f"  [WARN] compose YAML 解析失败：{exc}")
        for _svc, _cfg in (compose_doc.get("services") or {}).items():
            if not isinstance(_cfg, dict) or "build" not in _cfg:
                continue
            m = re.search(r"\$\{[A-Z_]+:-([^}]+)\}", str(_cfg.get("image") or ""))
            if m:
                defaults.add(m.group(1).rsplit(":", 1)[0])
        check("compose 里存在自建镜像的插值", bool(defaults), f"defaults={sorted(defaults)}")
        check("cd.yml 镜像集合 == compose 默认值集合", suffixes == defaults,
              f"cd={sorted(suffixes)} compose={sorted(defaults)}")
        # 必须用插值而不是写死（否则 CD 拉不到 GHCR 镜像）
        check("compose 的 image 已插值化（无裸 image: storekeeper-*）",
              re.search(r"^\s+image:\s+(storekeeper-(api|web):)", compose_text, re.M) is None)
    else:
        check("docker-compose.yml 存在", False)
        suffixes = suffixes or set()

    # ---------- G. 无明文凭据 / 硬编码主机 ----------
    print("\n[G] 无明文凭据 / 硬编码主机")
    for path, text, label in ((CD_YML, cd_text, "cd.yml"), (DEPLOY_SH, sh_text, "remote_deploy.sh")):
        # IPv4 字面量（放行回环/通配 —— 它们不是"某台真实主机"）
        ips = [ip for ip in re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)
               if ip not in ("127.0.0.1", "0.0.0.0")]
        check(f"{label} 无硬编码 IPv4", not ips, f"命中 {ips}")
        check(f"{label} 无私钥块", "-----BEGIN" not in text)
        leaks = re.findall(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", text)
        check(f"{label} 无令牌字面量", not leaks, f"命中 {leaks}")
        # 明文口令赋值（形如 password=xxx 且右值不是 ${{ ... }} / 变量引用）
        pw = [m for m in re.findall(r"(?i)\b(password|passwd|secret)\s*[:=]\s*([^\s\"']+)", text)
              if not m[1].startswith("$")]
        check(f"{label} 无明文口令赋值", not pw, f"命中 {pw}")

    # ---------- 汇总 ----------
    print(f"\n=== 结果：{len(PASSES)} 通过 / {len(FAILS)} 失败 / {len(SKIPPED)} 跳过 ===")
    if SKIPPED:
        print("跳过项（本机环境不满足；CI 上会真跑）：")
        for s in SKIPPED:
            print(f"  - {s}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
