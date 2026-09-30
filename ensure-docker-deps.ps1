<#
  ensure-docker-deps.ps1
  ---------------------------------------------------------------
  作用：启动后端之前，保证它依赖的 Docker 容器已就绪。

        后端本地跑 uvicorn 时依赖两份 Docker 服务：
          my-postgres  → localhost:5432   业务数据 + 店铺归属
          my-redis     → 127.0.0.1:6379   Celery broker / 限流 / 缓存

        ★ 为什么用 `docker start` 而不是 `docker compose up`：
          这两个容器是 `docker run` 手工创建的（docker inspect 的 compose 标签为空），
          compose 会因为 container_name 冲突直接报 "already in use"（README 里也记了这条）。

  退出码：0 = 依赖就绪，可以起后端；1 = 未就绪，调用方应中止
#>
[CmdletBinding()]
param(
    [string[]]$Containers = @("my-postgres", "my-redis"),
    [int]$EngineWaitSec = 90,
    [int]$ReadyWaitSec = 60,
    [string]$DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)

# ★ 刻意不用 "Stop"：native 命令（docker）往 stderr 写内容时，
#   $ErrorActionPreference='Stop' 会把它当成**终止性错误**抛出，
#   于是「引擎没起来」这种本来可判定的正常情况会变成异常栈中断脚本。
$ErrorActionPreference = "Continue"

function Say([string]$M)  { Write-Host $M }
function Ok([string]$M)   { Write-Host "  [OK]   $M" }
function Info([string]$M) { Write-Host "  ...    $M" }
function Bad([string]$M)  { Write-Host "  [FAIL] $M" }

function Get-EngineVersion {
    $v = (& docker info --format "{{.ServerVersion}}" 2>$null)
    if ($LASTEXITCODE -eq 0) { return "$v".Trim() }
    return $null
}

# 用 BeginConnect + WaitOne 手控超时：TcpClient.Connect 默认会挂很久，
# 且本机双栈下可能先试 ::1 再回落 —— 所以调用处一律显式传 127.0.0.1。
function Test-Tcp([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 1500) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $c.EndConnect($iar)
        return $true
    } catch { return $false } finally { $c.Close() }
}

function Get-ContainerState([string]$Name) {
    $s = (& docker inspect -f "{{.State.Status}}" $Name 2>$null)
    if ($LASTEXITCODE -ne 0) { return "missing" }
    return "$s".Trim()
}

function Get-ContainerHealth([string]$Name) {
    $h = (& docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $Name 2>$null)
    if ($LASTEXITCODE -ne 0) { return "unknown" }
    return "$h".Trim()
}

function Get-HostPort([string]$Name) {
    $j = (& docker inspect -f "{{json .NetworkSettings.Ports}}" $Name 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $j) { return $null }
    try { $o = $j | ConvertFrom-Json } catch { return $null }
    foreach ($p in $o.PSObject.Properties) {
        $b = $p.Value
        if ($b -and $b.Count -gt 0 -and $b[0].HostPort) { return [int]$b[0].HostPort }
    }
    return $null
}

# ---------------- 1. 引擎 ----------------
Say "[1/3] Docker engine"
$ver = Get-EngineVersion
if ($ver) {
    Ok "引擎已在运行（$ver）"
} else {
    Info "引擎未运行，尝试拉起 Docker Desktop ..."
    if (-not (Test-Path -LiteralPath $DockerDesktop)) {
        Bad "找不到：$DockerDesktop"
        Say "      请手动启动 Docker Desktop 后重试。"
        exit 1
    }
    Start-Process -FilePath $DockerDesktop | Out-Null
    $deadline = (Get-Date).AddSeconds($EngineWaitSec)
    Write-Host "  ...    等待引擎响应" -NoNewline
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        Write-Host "." -NoNewline
        if (Get-EngineVersion) { break }
    }
    Say ""
    if (-not (Get-EngineVersion)) {
        Bad "等待 $EngineWaitSec 秒后引擎仍未就绪"
        Say "      Docker Desktop 冷启动通常要 30~60 秒；再双击一次本脚本重试即可。"
        exit 1
    }
    Ok "引擎已就绪"
}

# ---------------- 2. 容器 ----------------
Say "[2/3] 依赖容器：$($Containers -join ', ')"
foreach ($c in $Containers) {
    $st = Get-ContainerState $c
    if ($st -eq "missing") {
        Bad "容器 $c 不存在"
        Say "      首次创建见 README「本地启动」；pgdata 是命名卷，重建容器不会丢数据。"
        exit 1
    }
    if ($st -eq "running") {
        Ok "$c 已在运行"
    } else {
        Info "$c 当前 $st -> 启动"
        $null = (& docker start $c 2>$null)
        if ($LASTEXITCODE -ne 0) { Bad "$c 启动失败"; exit 1 }
        Ok "$c 已启动"
    }
}

# ---------------- 3. 就绪 ----------------
Say "[3/3] 等待依赖就绪（最多 $ReadyWaitSec 秒）"
$deadline = (Get-Date).AddSeconds($ReadyWaitSec)
$ready = @{}
foreach ($c in $Containers) { $ready[$c] = $false }
$lastLine = ""

while ((Get-Date) -lt $deadline) {
    $allOk = $true
    $parts = @()
    foreach ($c in $Containers) {
        if ($ready[$c]) { $parts += "$c=ready"; continue }
        $h = Get-ContainerHealth $c
        if ($h -ne "none" -and $h -ne "unknown") {
            # 有 healthcheck 就以它为准（它才真正代表"服务能接受请求"）
            if ($h -eq "healthy") { $ready[$c] = $true; $parts += "$c=ready" }
            else { $parts += "$c=$h"; $allOk = $false }
        } else {
            # 没 healthcheck：用「宿主端口连得上」当判据（比"进程还在"强）
            $hp = Get-HostPort $c
            if ($hp -and (Test-Tcp "127.0.0.1" $hp)) { $ready[$c] = $true; $parts += "$c=ready" }
            else { $parts += "$c=waiting"; $allOk = $false }
        }
    }
    if ($allOk) { break }
    $line = "  ...     " + ($parts -join "  ")
    if ($line -ne $lastLine) { Say $line; $lastLine = $line }
    Start-Sleep -Seconds 1
}

Say ""
$fail = @()
foreach ($c in $Containers) { if (-not $ready[$c]) { $fail += $c } }
if ($fail.Count -eq 0) {
    Say "Docker 依赖已就绪：$($Containers -join ', ')"
    exit 0
}
Bad "未就绪：$($fail -join ', ')"
foreach ($c in $fail) { Say "      看日志：docker logs $c" }
Say "      手动重试：docker start $($fail -join ' ')"
exit 1
