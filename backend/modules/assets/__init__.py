"""营销素材库门面包。

★ 门面契约（由 `tests/test_module_facades.py` 机械校验）：
  跨模块引用**只允许** `from modules.assets import <name>`；`<name>` 必须在
  `__all__` 里；"伸手进包内部"（`from modules.assets.db_model import ...`）会被拦下。

★ 第 218 轮（P1）才建 `__all__`：此前本文件是**空文件** ——
  因为本包**从来没有跨模块消费者**（门禁的另一条：只在真有跨模块引用时才要求
  有契约面，给 19 个包都硬加 `__all__` 在没有消费者时只是装饰）。
  第 218 轮 `modules/library/tools.py` 的资料库工具要读素材库
  （老板拍的「P1 扩展到资料库中所有库」），于是第一次有了跨模块引用
  ⇒ 按门禁要求补上契约面。
"""

from modules.assets.service import count_assets, list_assets
from modules.assets.spec import ASSET_SPEC

#: ★ 为什么把 spec 也作为出口（第 218 轮 P1b）：
#:   `modules/library/tools.py` 生成工具 description 时，需要**这个库能按什么排、
#:   按什么筛、值域是什么** —— 那份真源就是 spec，不在工具层再抄一份
#:   （抄一份必然与内核真正校验的那份漂移）。
#:   语义上读 spec 与读 `__all__` 里的读口是同一类事：都是「本库对外承诺的形状」。
__all__ = ["ASSET_SPEC", "count_assets", "list_assets"]
