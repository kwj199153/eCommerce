"""本地开发启动器 —— uvicorn 参数在 Python 里给定，不经 shell 命令行。

为什么需要这一层（两个已实测的坑，缺一不可）：

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
"""

import sys

import uvicorn

# 与 P0-2 日志治理一致：排除 logs/ 与 .venv/，避免
# 「写日志 -> watchfiles 报告变更 -> 再写一条日志 -> ...」的自反馈。
RELOAD_EXCLUDES = ["logs/*", "*.log", "*.log.gz", ".venv/*", "__pycache__/*"]

HOST = "0.0.0.0"
PORT = 8000


def main() -> int:
    print("  API Docs: http://localhost:%d/docs" % PORT)
    print("  Health:   http://localhost:%d/health" % PORT)
    print()
    print("  reload 排除: " + ", ".join(RELOAD_EXCLUDES))
    print("  按 Ctrl+C 停止")
    print("-" * 40)

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
