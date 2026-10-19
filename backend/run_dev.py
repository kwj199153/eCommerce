"""本地开发启动器 —— uvicorn 参数在 Python 里给定，不经 shell 命令行。

为什么需要这一层（三个已实测的坑，缺一不可）：

1. click >= 8.0 在 Windows 上**默认展开 sys.argv 里的通配符**
   （click/core.py: `if args is None: args = sys.argv[1:]`
                     `if os.name == "nt" and windows_expand_args: args = _expand_args(args)`）。
   于是 `--reload-exclude "logs/*"` 会被展开成 logs/ 下一堆真实路径，
   而 `--reload-exclude` 只消费第一个，其余全部退化成"多余位置参数"，
   uvicorn 连 app 都懒得导入就直接拒启：
       Error: Got unexpected extra arguments (logs\2026-09-13.log.gz ...)
   在本文件里 reload_excludes 是 Python 列表，命令行上没有任何通配符，坑消除。

2. `chcp 65001` + 批处理内含非 ASCII 字节，会让 cmd 读批处理时解析脱轨
   （实测：rem 注释行被当命令执行）。因此 start-backend.bat 保持纯 ASCII，
   中文提示一律由本文件打印。

3. ★★★ Windows 下**重复启动不会报错**，会造出「幽灵服务」
   ---------------------------------------------------------------------------
   uvicorn 的 `bind_socket()` 对 TCP 一律设置 `SO_REUSEADDR`。在 Linux 上这仍会
   撞 `EADDRINUSE`，但在 **Windows 上它允许两个进程绑同一个端口**：

     · 第二个进程照样打印 `Uvicorn running on http://0.0.0.0:8000`；
     · 但它**抢不到连接**，旧进程继续应答；
     · 于是症状是「窗口里看着起好了 / 改了代码不生效 / 页面又是通的」，
       最容易被误判成"起不来"或"热重载坏了"。

   实测（第 381 轮）：`netstat` 显示 PID 8324 仍在 LISTENING，同时新进程打印
   "Uvicorn running on 0.0.0.0:8000"，无任何报错。

   ⇒ 起服务前先探端口，占用就**明确拒绝**并给出 PID，不要静默双绑。
"""

import os
import socket
import subprocess
import sys

import uvicorn

# 与 P0-2 日志治理一致：排除 logs/ 与 .venv/，避免
# 「写日志 -> watchfiles 报告变更 -> 再写一条日志 -> ...」的自反馈。
RELOAD_EXCLUDES = ["logs/*", "*.log", "*.log.gz", ".venv/*", "__pycache__/*"]

HOST = "0.0.0.0"
# 允许换端口起第二个实例（调试对照用）；默认 8000。
PORT = int(os.environ.get("ECOM_PORT") or 8000)

# 退出码多态：0 = 正常退出；2 = 前置条件不满足（端口被占），不是代码错误。
EXIT_PORT_BUSY = 2


def _port_in_use(port: int) -> bool:
    """有没有人在这个端口上监听。

    ★ 用 connect 探而不是 bind 探：bind 探在 Windows 上会被 SO_REUSEADDR 骗过
      （正是本文件第 3 条要防的那件事），connect 探反映的是"连得上连不上"。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def _listener_pid(port: int) -> str:
    """从 netstat 里捞监听该端口的 PID。

    best-effort：拿不到（没 netstat / 输出格式变了 / 权限不足）就返回空串，
    **绝不因为查不到 PID 而中断启动判断** —— 端口被占这个结论已经由
    `_port_in_use` 独立得出。
    """
    try:
        # ★★★ 必须读**字节**，不能让 subprocess 解码：
        #   中文 Windows 的 netstat 输出是 GBK（实测 0xBB 开头的乱码段），
        #   而 text=True 默认按 UTF-8 解 ⇒ 解码线程抛 UnicodeDecodeError、
        #   `.stdout` 直接变成 None ⇒ 守卫自己崩成 AttributeError，
        #   那句"端口被占"的提示一个字都打不出来（本轮实测踩到）。
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or b""
    except Exception:  # noqa: BLE001 —— 探测失败不影响主判断
        return ""

    suffix = (":%d" % port).encode()
    for line in out.splitlines():
        parts = line.split()
        # 形如：TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  8324
        if len(parts) >= 5 and parts[3].upper() == b"LISTENING" and parts[1].endswith(suffix):
            return parts[4].decode("ascii", "ignore")
    return ""


def _refuse_port_busy(port: int) -> int:
    pid = _listener_pid(port)
    print()
    print("!! 端口 %d 已被占用%s —— 本次**没有**启动。" % (port, "（监听进程 PID %s）" % pid if pid else ""))
    print("   为什么不能硬起：Windows 允许两个进程绑同一端口（SO_REUSEADDR），")
    print("   uvicorn 不会报错，你会得到一个「窗口里看着起好了、实际是旧进程在答」的幽灵服务。")
    print()
    print("   三种处理：")
    if pid:
        print("     1) 停掉旧进程：  taskkill /PID %s /T /F" % pid)
    else:
        print("     1) 停掉旧进程：  netstat -ano | findstr :%d   再用 taskkill /PID <PID> /T /F" % port)
    print("     2) 直接复用旧的：浏览器打开 http://localhost:%d/docs 确认它跑的是不是最新代码" % port)
    print("     3) 换端口起：    set ECOM_PORT=8001  &&  start-backend.bat")
    return EXIT_PORT_BUSY


def main() -> int:
    print("  API Docs: http://localhost:%d/docs" % PORT)
    print("  Health:   http://localhost:%d/health" % PORT)
    print()
    print("  reload 排除: " + ", ".join(RELOAD_EXCLUDES))
    print("  按 Ctrl+C 停止")
    print("-" * 40)

    if _port_in_use(PORT):
        return _refuse_port_busy(PORT)

    # ★ 冷启动要导入整棵应用（十几组 Agent + 提示词模板 + 数据引导），
    #   实测约 60~90 秒，期间控制台**几乎没有输出**。先说清楚，避免被当成卡死。
    print("  正在导入应用（首次约 60~90 秒，控制台会静默一段时间，属正常）...")

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
        reload_excludes=RELOAD_EXCLUDES,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
