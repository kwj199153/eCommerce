"""长期记忆模块（第 149 轮批 C2）：跨会话的用户画像与偏好。

分工（与 `ai_infra/memory/` 的机制层成对）：

    ai_infra/memory/limits.py    口径真源（上限 / 配额 / 权重 / kind）
    ai_infra/memory/entry.py     数据形态（markdown ↔ 条目）
    ai_infra/memory/distill.py   规则（归一 / 去重 / 抽取 / 差异）
    **modules/memory/**          接线：建表 / 服务 / HTTP 端点 / Celery 定时任务

★★ 为什么 r141 把这里点成「假页面」
-----------------------------------
`frontend/src/views/MemoryEvolution.vue` 早就在界面上承诺「每晚自动整理更新」，
但后端**一行存储都没有**：记忆正文是组件里写死的一段文本、时间线是 7 条
硬编码记录、保存按钮只改本地 `ref`。整页**零 API 调用**。

所以本模块存在的唯一目的是让那句话变成事实，且**每一步都可被验证**：

  · 存储   `db_model.py`（三张表）+ 迁移 `b8d4e2f6c3a5` / `c9e5f3a7d4b6`
  · 写入   `service.py`（归属 / 上限 / 身份稳定性 / 留痕 四条不变量）
  · HTTP   `router.py`（五个端点，身份一律取自服务端）
  · 开关   `memory_profiles.enabled` —— 关掉之后任务跳过、注入块为空
  · 留痕   `memory_logs` —— 含 `distill_failed`：跑失败必须与「没跑」可分
  · 定时   `tasks.py` + `core.redis.beat_schedule`（含幂等游标）

★ 门面契约（`tests/test_module_facades.py` 钉住）
----------------------------------------------
跨模块引用只允许 `from modules.memory import <name>`，且 `<name>` 必须在
下面的 `__all__` 里；`__all__` 里不得出现**子模块名**
（`service` / `router` / `db_model` / `tasks` 都不行 —— 那等于把包内部结构
当出口，条款 1 会形同虚设）。

★★ 出口为什么只有 `load_entries` 一个
------------------------------------
读口（把长期记忆拼成注入块塞进 system prompt）住在**本包内**
（`prompt_section.py`），它走同包相对引用，因此**不需要**一个门面出口
—— 门面只解决「其它模块怎么取用本包」。

所以 `load_entries` 今天确实**没有跨模块消费者**。保留它的理由不是"以后再说"，
而是它已经是一份**声明过的契约**：本包对外承诺的读原语就是它，
将来任何模块要读某个人的记忆都从它进（而不是伸手进 `service`）。
反过来，先把 `save_memory` / `reset_memory` 这类只有本包 `router.py` 用的动作
也声明成出口，只会让契约面看起来很大、实际无人使用 ——
而没有人用的出口，改动时也不会有人知道自己破坏了它。

★★ 注册触发点（读口接线的最脆弱环节）
------------------------------------
`prompt_section.py` 的注册是 **import 副作用**。本文件那一行 import 就是
「保证它一定被 import」的地方 —— 跨模块访问一律从门面进，所以门面被加载
等价于「memory 包在用」。若把注册挪进 `router.py`，则任何不走 HTTP 的
进程（Celery worker 里的图、直接 new Agent 的测试）都不会注册，
表现为**注入静默失效**：不报错、不告警，只是模型永远不知道用户的偏好。
由 `tests/test_memory_injection.py::test_facade_triggers_registration` 钉住。
"""

from .service import load_entries

# ★ 只为**注册副作用**而 import（理由见上面「注册触发点」）：
#   本包被加载 ⇒ system prompt 段落注册完成。
from . import prompt_section as _prompt_section  # noqa: F401

__all__ = [
    # 读原语：读该 owner 的全部条目（顺序 = 展示顺序）。
    # 消费者：读口（system prompt 注入）。
    "load_entries",
]
