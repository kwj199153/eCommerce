"""业务模块层（`modules/`）。

本包下每个子包是一个**业务域**（选品 / Listing / 广告 / 客服 / 竞品 / AIGC /
复盘 / 店秘书 / 技能 / 记忆 / 知识库 …）。跨包引用只走各包的门面
（`from modules.B import <已声明出口>`，判据见 `tests/test_module_facades.py`）。

==============================================================================
★★ 本文件的第二个身份：**横切段落的公共注册点**（第 257 轮）
==============================================================================
`register_prompt_section()` 的调用点必须在业务层（机制层自己注册一段内容 =
内容住进基础设施层，硬红线），但**不隶属任何业务域**的那一段没有"自己的模块"
可住 —— 典型是「本次请求的作用对象」：它对全部 Agent 生效，业务词却由前端
随请求带上。

第 251 轮把它的注册写在了 `modules/product_research/` 里（当时只有那一条链路
下发该字段）。后果是可预期的：第 257 轮要给 Listing / AIGC 也接上时，
**没有人的第一反应是去选品模块里找那个文件** —— 机制被一个业务域的目录
悄悄私有化了，而这个约定从未写在任何地方。

⇒ 现在注册点搬到这里（`modules/` 根，**横切位置**），并由**本文件**触发：
`modules/__init__.py` 是包初始化，任何 `import modules.<任意子包>` 都会先执行它
⇒ 「谁负责 import 它」这件事不再依赖"某个特定 Agent 的 router 恰好被导入"，
Celery worker、直接 new Agent 的测试、脚本全都覆盖到。

★ 为什么这一行 import 必须留在这里、而不是搬回某个 router：
  注册是 import 副作用。触发点若住在一个业务 router 里，那条 router 一旦
  不再被某个进程导入，注入就**静默失效**：不报错、日志全绿，
  模型只是永远看不到「不得从历史里挑一个顶上」那一段 —— 于是回到本洞。
  判据：`tests/test_context_target_gate.py::test_reader_section_is_imported_at_module_level`。

★ 这份「谁在往 system prompt 里注入内容」的全量名单另有门禁
  （`tests/test_memory_injection.py::test_registration_call_sites_are_confined_to_business_layer`）：
  新增一个注入段就往那份名单里加一项，本条 import 只是**触发**、不是注册本身。
"""

# ★ 只为**注册副作用**而 import（理由见上面「公共注册点」）：
#   本包被加载 ⇒ system prompt 段落注册完成。
#   ★ 相对 import 是刻意的：本模块就在 `modules` 包内，写成绝对名会被
#     `test_module_facades.py` 判成"取模块对象"（`from modules import x` 形态）。
from . import context_target_section as _context_target_section  # noqa: F401
