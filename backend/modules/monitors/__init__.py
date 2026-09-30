"""竞品监控池模块门面包。

★ 门面契约（由 `tests/test_module_facades.py` 机械校验）：
  跨模块引用**只允许** `from modules.monitors import <name>`；
  `<name>` 必须在下面的 `__all__` 里。`from modules.monitors.db_model import ...`
  这类"伸手进包内部"的写法会被门禁拦下。

★ 为什么导出 `MonitorRecord`（而不是更厚的一层 API）：
  `modules/amazon_sp/seed.py` 需要把监控池的**时序**展开成竞品快照的逐日行。
  这是**只读**用途。导出 ORM 模型是为了让展开方与表结构同源 ——
  否则只能用原生 SQL 把列名与 JSON 结构再抄一遍，而抄一遍就多一处漂移点：
  将来 `snapshot.py` 改了时序点的字段名，原生 SQL 那边不会有任何报错，
  只会在运行时静默取到空值。
"""

from modules.monitors.db_model import MonitorRecord
from modules.monitors.service import count_monitors, list_monitors
from modules.monitors.spec import MONITOR_SPEC

#: ★ 第 218 轮（P1）扩出口：`list_monitors` / `count_monitors` ——
#: 「读监控池」的唯一实现（改前只有 `monitors/router.py` 的 handler 内联实现）。
#: 资料库工具经此读到监控池（老板拍的「竞品池就是竞品监控池，P1 全库覆盖」）。
#: ★ 第 218 轮（P1b）扩出口：`MONITOR_SPEC` ——
#:   资料库工具要用它生成「能按什么排 / 按什么筛」的 description（同 assets 包）。
__all__ = ["MonitorRecord", "MONITOR_SPEC", "count_monitors", "list_monitors"]
