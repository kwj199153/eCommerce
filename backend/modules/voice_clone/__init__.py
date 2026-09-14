"""语音克隆（客服音色）附加模块。

可插拔约束（见 docs 与 MEMORY.md「附加模块与可插拔」）：
- 本模块只允许依赖 core/*（config / database / logger / tenant）。
- **禁止本模块 import 任何业务模块**（listing_generator / customer_service / ...）。
- 反过来，**禁止任何业务模块 import 本模块** —— 由 tests/test_voice_clone_isolation.py 断言。
- 通过 core/config.py 的 voice_clone_enabled 总开关决定是否挂载路由；关闭时前端入口隐藏、
  后端路由不注册，数据表保留不做破坏性迁移。
"""

__all__ = ["router", "db_model", "client", "service"]
