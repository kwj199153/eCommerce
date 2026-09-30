#!/usr/bin/env bash
# ============================================================
#  服务器侧部署脚本（由 .github/workflows/cd.yml 经 ssh stdin 执行）
# ------------------------------------------------------------
#  本地手动跑也一样，便于排障（回滚某个版本也走这条）：
#     bash remote_deploy.sh <git_ref> <deploy_path> <api_image> <web_image>
#  例：
#     bash remote_deploy.sh v1.0.0 /srv/ecommerce \
#       ghcr.io/kwj199153/ecommerce/storekeeper-api:v1.0.0 \
#       ghcr.io/kwj199153/ecommerce/storekeeper-web:v1.0.0
#
#  ★ 为什么经 stdin 送达（`ssh host 'bash -s -- ...' < 本文件`）而不是 scp 过去再跑：
#    少一次文件落地，也就少一次「服务器上那份脚本与流水线这份不一致」的可能 ——
#    跑的永远是当前 commit 里的这一份。也因此**不需要可执行位**
#    （Windows 工作区里也设不了 chmod +x，这不成问题）。
#
#  ★★ 五条硬规则（每条都对应一次真实会踩的事故形态）：
#    1. **幂等**：同一个 (ref, image) 跑第二次必须成功，且不产生额外改动。
#       所以 git 切换前先比对、.env 写入用「先删旧行再追加」而不是盲追加。
#    2. **回滚点先记后动**：进任何破坏性动作之前，先把「上一次成功的
#       ref + 镜像」落盘。失败时按它**整组**还原，而不是只把镜像换回去 ——
#       compose 文件本身也随版本演进，只回镜像会得到「新编排 + 旧镜像」，
#       这种半成品比不回滚更难查。
#    3. **失败必须非 0 退出**：CI 判成功只认退出码。脚本失败却 exit 0，
#       流水线会显示绿灯而线上是新旧混合态 —— 最坏的一种「假绿」。
#    4. **不动数据面**：只 up 业务服务（backend/worker/beat/frontend），
#       绝不 recreate postgres/redis —— 重启数据库会中断连接，且期间无法回滚。
#    5. **不许无差别 checkout**：工作树有未提交改动就停下（`git checkout`
#       在有脏改动时可能静默覆盖，毁掉服务器上的现场）。
#
#  ⚠️ 本文件必须是 **LF 行尾**。CRLF 会让远端 `bash -s` 把 `\r` 当成命令的一部分，
#     报 `$'\r': command not found`。ci.yml 的 assets job 有一条门禁钉这一点。
# ============================================================

set -Eeuo pipefail

# ---------------- 参数与常量 ----------------
GIT_REF="${1:?用法: remote_deploy.sh <git_ref> <deploy_path> <api_image> <web_image>}"
DEPLOY_PATH="${2:?缺少参数 2：部署目录}"
API_IMAGE="${3:?缺少参数 3：后端镜像}"
WEB_IMAGE="${4:?缺少参数 4：前端镜像}"

COMPOSE_FILE="${DEPLOY_PATH}/docker-compose.yml"
ENV_FILE="${DEPLOY_PATH}/.env"
STATE_FILE="${DEPLOY_PATH}/.cd_images"      # 上一次**成功**的部署（正常回滚点）
ROLLBACK_FILE="${DEPLOY_PATH}/.cd_rollback" # 本次部署开始前的现场（异常兜底）

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"     # 秒
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"

# compose 里写死的容器名 —— 健康检查要按名字查，不能靠猜
C_API="storekeeper-api"
C_WORKER="storekeeper-worker"
C_BEAT="storekeeper-beat"
C_WEB="storekeeper-web"

log()  { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy][warn] %s\n' "$*" >&2; }
die()  { printf '[deploy][ERROR] %s\n' "$*" >&2; exit 1; }

# ---------------- 前置护栏 ----------------
case "$DEPLOY_PATH" in
  "/" | "" | "/root" | "/home") die "拒绝在危险路径上部署：${DEPLOY_PATH}" ;;
esac
case "$API_IMAGE" in *"/"*) ;; *) die "API_IMAGE 不是合法的镜像引用：${API_IMAGE}" ;; esac
case "$WEB_IMAGE" in *"/"*) ;; *) die "WEB_IMAGE 不是合法的镜像引用：${WEB_IMAGE}" ;; esac

command -v docker >/dev/null 2>&1 || die "服务器上没有 docker"
docker compose version >/dev/null 2>&1 || die "docker compose v2 不可用（需要 'docker compose' 而不是 'docker-compose'）"
[ -d "$DEPLOY_PATH" ] || die "部署目录不存在：${DEPLOY_PATH}"
[ -f "$COMPOSE_FILE" ] || die "找不到 ${COMPOSE_FILE}（首次部署请先人工 git clone + 配 .env + up -d --build）"
[ -f "${DEPLOY_PATH}/backend/.env" ] || warn "找不到 ${DEPLOY_PATH}/backend/.env（backend/worker/beat 的 env_file 指向它，缺了会起不来）"

# compose 的变量插值**只读与 compose 文件同目录的 .env** ⇒ 所有 compose 调用都要先 cd 过去
compose() { ( cd "$DEPLOY_PATH" && docker compose "$@" ); }

log "== 本次部署输入 =="
log "  git_ref     = ${GIT_REF}"
log "  deploy_path = ${DEPLOY_PATH}"
log "  api_image   = ${API_IMAGE}"
log "  web_image   = ${WEB_IMAGE}"

# ---------------- 工具函数 ----------------
# 幂等写 .env：先删所有同键行，再追加一行。
# 用 grep -v + 重写而不是 sed 原地替换：前者在「键不存在」与「键出现多次」下行为一致。
# 用 cat > 原文件（而不是 mv）以保留 inode 与权限位。
upsert_env() {
  local key="$1" value="$2" file="$3"
  [ -f "$file" ] || : > "$file"
  local tmp
  tmp="$(mktemp)"
  grep -v -E "^[[:space:]]*${key}=" "$file" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

# 等容器就绪。need_health=1 时要求 Docker healthcheck 判 healthy；
# need_health=0 时只要在跑（该容器在 compose 里没有 healthcheck）。
# 用 docker inspect 而不是 curl：免依赖宿主工具，且用的是镜像自带的判据。
wait_ready() {
  local container="$1" need_health="$2"
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
  while :; do
    if ! docker inspect "$container" >/dev/null 2>&1; then
      [ "$(date +%s)" -lt "$deadline" ] || return 1
      sleep "$HEALTH_INTERVAL"; continue
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || echo false)" != "true" ]; then
      return 1   # 容器已退出，不必等满超时
    fi
    if [ "$need_health" = "1" ]; then
      local health
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || echo none)"
      case "$health" in
        healthy) return 0 ;;
        none)    return 0 ;;   # 没定义 healthcheck ⇒ 在跑即通过
        unhealthy) return 1 ;;
        # starting / 其它 ⇒ 继续等
      esac
    else
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || return 1
    sleep "$HEALTH_INTERVAL"
  done
}

# 私有 GHCR 包需要登录才能 pull。这是「部署能连上但拉不到镜像」的最常见原因，
# 所以在 pull 之前先给提示（不致命：包设为 public 时无需登录）。
warn_if_registry_unauthenticated() {
  local host="ghcr.io"
  case "${API_IMAGE}${WEB_IMAGE}" in
    *"${host}"*) ;;
    *) return 0 ;;
  esac
  if grep -q "${host}" "${HOME}/.docker/config.json" 2>/dev/null; then
    return 0
  fi
  warn "未在 ${HOME}/.docker/config.json 里找到 ${host} 的登录凭据。"
  warn "若镜像是私有包，下一步 pull 会失败。先执行："
  warn "    echo '<PAT>' | docker login ${host} -u <用户名> --password-stdin   # PAT 需要 read:packages"
  warn "或者把该包设为 public（免登录）。"
}

# ---------------- 记录回滚点 ----------------
CUR_REF=""
CUR_API=""
CUR_WEB=""

if [ -f "$STATE_FILE" ]; then
  CUR_REF="$(sed -n 's/^REF=//p' "$STATE_FILE" | head -n1)"
  CUR_API="$(sed -n 's/^API_IMAGE=//p' "$STATE_FILE" | head -n1)"
  CUR_WEB="$(sed -n 's/^WEB_IMAGE=//p' "$STATE_FILE" | head -n1)"
fi
# 没有状态文件（首次 CD）⇒ 回退到当前 .env 的写法
if [ -z "$CUR_API" ] && [ -f "$ENV_FILE" ]; then
  CUR_API="$(sed -n 's/^API_IMAGE=//p' "$ENV_FILE" | head -n1)"
  CUR_WEB="$(sed -n 's/^WEB_IMAGE=//p' "$ENV_FILE" | head -n1)"
fi
# 再兜底：CD 之前是本地 build 出来的镜像
[ -n "$CUR_API" ] || CUR_API="storekeeper-api:latest"
[ -n "$CUR_WEB" ] || CUR_WEB="storekeeper-web:latest"
# 当前代码版本（供回滚时 checkout 回同一处）
if [ -z "$CUR_REF" ] && [ -d "${DEPLOY_PATH}/.git" ]; then
  CUR_REF="$(git -C "$DEPLOY_PATH" describe --tags --always 2>/dev/null || true)"
fi

{
  printf 'REF=%s\n' "$CUR_REF"
  printf 'API_IMAGE=%s\n' "$CUR_API"
  printf 'WEB_IMAGE=%s\n' "$CUR_WEB"
} > "$ROLLBACK_FILE"

log "回滚点（本次部署前的现场）：ref='${CUR_REF}' api='${CUR_API}' web='${CUR_WEB}'"

# ---------------- 回滚 ----------------
rollback() {
  trap - ERR   # 回滚过程中再失败不要递归触发 trap
  warn "===== 开始回滚 ====="
  warn "  目标 ref = ${CUR_REF:-<不回退代码>}"
  warn "  目标镜像 = ${CUR_API} ; ${CUR_WEB}"

  if [ -n "$CUR_REF" ] && [ -d "${DEPLOY_PATH}/.git" ]; then
    if git -C "$DEPLOY_PATH" rev-parse --verify --quiet "${CUR_REF}^{commit}" >/dev/null; then
      git -C "$DEPLOY_PATH" checkout --detach "$CUR_REF" || warn "回滚代码失败（继续尝试回滚镜像）"
    else
      warn "回滚点 ref '${CUR_REF}' 在本地不存在，跳过代码回退"
    fi
  fi

  upsert_env API_IMAGE "$CUR_API" "$ENV_FILE"
  upsert_env WEB_IMAGE "$CUR_WEB" "$ENV_FILE"
  compose pull backend frontend || warn "拉取回滚镜像失败（若镜像仍在本地则无碍）"
  compose up -d backend worker beat frontend || warn "回滚切换服务失败"

  if wait_ready "$C_API" 1; then
    warn "回滚后 ${C_API} 已恢复就绪"
  else
    warn "回滚后 ${C_API} 仍未就绪 —— **需要人工介入**"
  fi
  warn "===== 回滚结束 ====="
}

# 切服务之后才需要回滚；之前失败说明服务器状态没被改动
CUTOVER_STARTED=0
_on_err() {
  local rc=$?
  if [ "${CUTOVER_STARTED}" = "1" ]; then
    warn "切服务之后发生意外失败（rc=${rc}），执行整组回滚"
    rollback || warn "回滚过程本身也出错了，需要人工介入"
  else
    warn "切服务之前失败（rc=${rc}）：服务器状态未改变，无需回滚"
  fi
  exit "$rc"
}
trap '_on_err' ERR

# ---------------- 1. 拉齐代码 ----------------
if [ -d "${DEPLOY_PATH}/.git" ]; then
  # ★ 先查脏污再切版本：`git checkout` 在有未提交改动时可能静默覆盖工作树
  dirty="$(git -C "$DEPLOY_PATH" status --porcelain --untracked-files=no || true)"
  if [ -n "$dirty" ]; then
    warn "部署目录工作树有未提交改动，拒绝切换版本："
    printf '%s\n' "$dirty" >&2
    die "请先在服务器上处理这些改动（git stash / commit / 还原）后重试"
  fi
  log "同步远端 tags ..."
  git -C "$DEPLOY_PATH" fetch --tags --force --prune origin
  head_now="$(git -C "$DEPLOY_PATH" rev-parse --short HEAD 2>/dev/null || echo '?')"
  log "切换代码：HEAD ${head_now} → ${GIT_REF}"
  git -C "$DEPLOY_PATH" checkout --detach "$GIT_REF" \
    || die "切换代码到 ${GIT_REF} 失败（tag 是否存在？工作树是否有冲突文件？）"
  log "当前 HEAD = $(git -C "$DEPLOY_PATH" rev-parse --short HEAD)"
else
  warn "部署目录不是 git 仓库（${DEPLOY_PATH}/.git 不存在）"
  warn "⇒ 跳过代码更新，只更新镜像。若 compose 文件也随版本演进，"
  warn "  这会积累「新镜像 + 旧编排」的漂移，请尽快改成 git 部署。"
fi

# ---------------- 2. 写入镜像指向 ----------------
log "写入镜像指向到 ${ENV_FILE} ..."
upsert_env API_IMAGE "$API_IMAGE" "$ENV_FILE"
upsert_env WEB_IMAGE "$WEB_IMAGE" "$ENV_FILE"

# ---------------- 3. 拉镜像 ----------------
warn_if_registry_unauthenticated
log "拉取镜像 ..."
# 只拉 backend / frontend：worker 与 beat 共用 backend 的镜像，pull 是幂等的。
compose pull backend frontend

# ---------------- 4. 切服务 ----------------
# ★ 不带 --no-deps：compose 会等 postgres/redis 健康再起业务服务。
#   它们镜像/配置没变 ⇒ 不会被 recreate，数据面安全。
# ★ 显式列服务名：不动 postgres / redis / prometheus / alertmanager。
CUTOVER_STARTED=1
log "切换业务服务（backend / worker / beat / frontend）..."
compose up -d backend worker beat frontend

# ---------------- 5. 健康检查 ----------------
FAILED=""
for spec in "${C_API}:1" "${C_WORKER}:1" "${C_WEB}:1" "${C_BEAT}:0"; do
  c="${spec%%:*}"; n="${spec##*:}"
  if [ "$n" = "1" ]; then need="需要 healthcheck"; else need="仅需运行中"; fi
  log "等待 ${c} 就绪（${need}，上限 ${HEALTH_TIMEOUT}s）..."
  if wait_ready "$c" "$n"; then
    log "${c} 就绪 ✓"
  else
    warn "${c} 未就绪"
    FAILED="$c"
    break
  fi
done

if [ -n "$FAILED" ]; then
  rollback
  die "部署失败：${FAILED} 未在规定时间内就绪（已按回滚点整组还原）"
fi

# ---------------- 6. 成功：推进回滚点 ----------------
{
  printf 'REF=%s\n' "$GIT_REF"
  printf 'API_IMAGE=%s\n' "$API_IMAGE"
  printf 'WEB_IMAGE=%s\n' "$WEB_IMAGE"
} > "$STATE_FILE"

log "回滚点已推进 ⇒ ${STATE_FILE}"
log "部署成功：ref=${GIT_REF}"
log "  api=${API_IMAGE}"
log "  web=${WEB_IMAGE}"
