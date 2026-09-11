"""
pytest 根级 conftest（backend/ 下）

⚠️ 这里是**测试运行环境**的兜底配置，不要和 tests/conftest.py 里的业务 fixture 混淆：
tests/conftest.py 提供 client / user / auth_headers 等业务夹具；
本文件只在 pytest 启动最早期注入环境变量，供 core.config 单例读取。

为什么必须放在根目录：
    core.config.config 是模块级单例（import 时即实例化），
    环境变量必须在它被 import 之前设置。pytest 会在收集测试模块前先加载
    各层 conftest.py，所以根目录 conftest 是唯一可靠的注入点。

限流默认开启（生产语义），但测试套件会在几十秒内打出上百个请求，
必然触发 60 次/分钟的阈值，因此测试环境显式关闭。
限流中间件本身的行为由 tests/test_middleware.py 用独立的 app 实例验证。
"""

import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
