"""样本公网镜像：把本地落盘的音频样本推送到云端静态目录。

## 为什么需要它

CosyVoice 的 ``url`` 参数要求**公网可访问**，且是**服务端主动来拉**（见 ``client.py``
顶部注释）。本地开发的 ``http://localhost:8000`` 它够不着 —— 这是协议约束，不是 bug。

而不解决它，「创建音色」这一步在本地**永远跑不通**。

## 方案判据

**本机没有公网入口，但云服务器有。** ⇒ 让云端只当「文件柜」（纯静态，不跑业务），
业务逻辑全部留在本地开发机。这样：

- 本地继续热重载开发，不用每次改代码都重新部署；
- 语音克隆能真跑通（DashScope 从云端拉得到文件）；
- 将来真要全栈上云（SaaS 终局），本模块**置空即可失效**，不会成为障碍。

## 与 PUBLIC_BASE_URL 的分工（★ 别混）

| 配置 | 作用 | 指向 |
|---|---|---|
| ``PUBLIC_BASE_URL`` | 拼给 DashScope 的地址前缀 | **云端** |
| ``VOICE_SAMPLE_MIRROR_*`` | 怎么把文件送上去 | 传输凭据 |

## 失败策略（项目铁律：显式报错，禁静默）

同步失败**不吞掉**，而是返回失败原因由调用方决定如何呈现。
但**不影响本地落盘** —— 本地文件已经写好了，远端失败是「公网回源不可用」，
不是「上传失败」，两者的用户提示不同（见 ``service.sample_public_url`` 的注释）。

传输用系统 ``scp``（避免引入 paramiko 新依赖，与项目「按需最小依赖」一致）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)

#: scp 超时（秒）。样本最大 10MB，正常内网/公网几秒内应完成。
_SCP_TIMEOUT = 60.0


class MirrorError(RuntimeError):
    """镜像同步失败。message 可直接展示给用户。"""


def _cfg():
    """延迟取配置：避免模块级 import 引发循环依赖。"""
    from core.config import config

    return config


def is_enabled() -> bool:
    """是否配置了镜像目标。未配置 ⇒ 全部同步操作静默跳过（这是刻意的）。"""
    return bool((_cfg().voice_sample_mirror_ssh_host or "").strip())


def _ssh_target() -> str:
    host = (_cfg().voice_sample_mirror_ssh_host or "").strip()
    if not host:
        raise MirrorError("未配置 VOICE_SAMPLE_MIRROR_SSH_HOST")
    return host


def _scp_argv(local: Path, remote_dir: str) -> list[str]:
    """组装 scp 命令。私钥可选（留空则用 ssh-agent / 默认密钥）。"""
    cfg = _cfg()
    argv = ["scp", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    port = int(cfg.voice_sample_mirror_ssh_port or 22)
    if port != 22:
        argv += ["-P", str(port)]
    key = (cfg.voice_sample_mirror_ssh_key or "").strip()
    if key:
        argv += ["-i", key]
    argv += [str(local), f"{_ssh_target()}:{remote_dir.rstrip('/')}/"]
    return argv


def _remote_mkdir(remote_dir: str) -> None:
    """确保远端目录存在（scp 不会自动建目录）。"""
    cfg = _cfg()
    argv = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    port = int(cfg.voice_sample_mirror_ssh_port or 22)
    if port != 22:
        argv += ["-p", str(port)]
    key = (cfg.voice_sample_mirror_ssh_key or "").strip()
    if key:
        argv += ["-i", key]
    argv += [_ssh_target(), f"mkdir -p {remote_dir}"]
    subprocess.run(argv, capture_output=True, timeout=_SCP_TIMEOUT, check=True)


def push_file(local_path: Path, *, remote_dir: Optional[str] = None) -> str:
    """把单个文件推到远端静态目录，返回远端的**绝对路径**。

    调用方负责把返回值拼成公网 URL。

    Raises:
        MirrorError: scp/ssh 缺失、认证失败、网络不通、目标目录不可写。
    """
    if not is_enabled():
        # 未配置 ⇒ 静默跳过（不是错误）。调用方应据此决定是否用本地地址。
        return ""

    if not local_path.exists():
        raise MirrorError(f"待镜像的本地文件不存在：{local_path}")

    target_dir = (remote_dir or _cfg().voice_sample_mirror_remote_dir or "").strip()
    if not target_dir:
        raise MirrorError("未配置 VOICE_SAMPLE_MIRROR_REMOTE_DIR")

    if shutil.which("scp") is None:
        raise MirrorError("本机找不到 scp 命令（Windows 需开启 OpenSSH 客户端）")

    try:
        _remote_mkdir(target_dir)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise MirrorError(
            f"无法在云端建目录 {target_dir}（ssh 返回 {exc.returncode}）：{err or '无输出'}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MirrorError(f"ssh 建目录超时（{_SCP_TIMEOUT:.0f}s），请检查网络与本机密钥") from exc
    except FileNotFoundError as exc:
        raise MirrorError("本机找不到 ssh 命令") from exc

    try:
        subprocess.run(
            _scp_argv(local_path, target_dir),
            capture_output=True,
            timeout=_SCP_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise MirrorError(
            f"样本推送云端失败（scp 返回 {exc.returncode}）：{err or '无输出'}"
            "。常见原因：未配置免密登录（需 ssh-copy-id）、目标目录无写权限、安全组未放行 22 端口。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MirrorError(f"样本推送超时（{_SCP_TIMEOUT:.0f}s）") from exc

    remote_abs = f"{target_dir.rstrip('/')}/{local_path.name}"
    logger.info(f"[voice-mirror] 样本已推送云端 {remote_abs}")
    return remote_abs


def check_connectivity() -> dict:
    """自检：ssh 能否连通 + 远端目录是否可写。

    供 ``/voice-clone/config`` 暴露给前端做「配置体检」，
    避免用户点了「开始克隆」才发现密钥没配好。
    """
    if not is_enabled():
        return {"ok": False, "enabled": False, "reason": "未配置镜像主机（VOICE_SAMPLE_MIRROR_SSH_HOST 为空）"}

    cfg = _cfg()
    argv = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    port = int(cfg.voice_sample_mirror_ssh_port or 22)
    if port != 22:
        argv += ["-p", str(port)]
    key = (cfg.voice_sample_mirror_ssh_key or "").strip()
    if key:
        argv += ["-i", key]
    argv += [_ssh_target(), "echo ok"]

    try:
        r = subprocess.run(argv, capture_output=True, timeout=15.0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "enabled": True, "reason": "ssh 连接超时（15s）"}
    except FileNotFoundError:
        return {"ok": False, "enabled": True, "reason": "本机找不到 ssh 命令"}

    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "enabled": True, "reason": f"ssh 失败：{err or '无输出'}"}

    return {
        "ok": True,
        "enabled": True,
        "reason": "ssh 连通",
        "host": _ssh_target(),
        "remote_dir": cfg.voice_sample_mirror_remote_dir,
    }
