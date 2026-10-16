"""
AIGC 媒体生成模块 - API 路由（包）
====================================
提供 RESTful API 端点（r363 时点 19 个；r367 删掉 `translate-image` 后 **18** 个 —— 现算
`grep -rh '^@router' modules/aigc_media/router/ | wc -l`）。
★ 命令别写成 `grep -rc … router/`：`-c` 在目录上给的是**每个文件各自的**计数（4/4/7/4），
  不是总数 —— 那会让人把「19」读成「7」。

★ 这里是本模块 HTTP 面的**唯一契约面**。
★ 这里只做三件事：定义 prefix/tags、include 四个子模块、把 `router` 暴露出去。
  `main.py` 的挂载点一行都不用改（`from modules.aigc_media.router import router`）——
  包与模块同名，导入路径自然不变。

★ 为什么拆成包（第 363 轮）：`tests/test_source_size_ratchet.py` 把 `router.py`
  钉在 843 行（>800 行冻结表，R2「只许降不许升」），而新端点让它涨到 882。
  拆包后最大的一份也只有 200 行出头 —— 每个文件都回到阈值以内，
  冻结表里那一项随之消失（R5 是**引导式红**：它提示你重跑生成器同步表）。

★ 子模块为什么**不带** prefix / tags：prefix 只能有一个定义处。分散到四个子模块
  就是四份实现，改一处就静默失配（同族教训：「同一判定两份实现 ⇒ 至少一份永远测不到」）。

★ 已核对的消费方（拆包会改变路径字面量的地方，共 3 个门禁 + 1 个棘轮表）：
  · `tests/test_context_target_gate.py`     对话端点清单 → 改指 `router/chat.py`
  · `tests/test_skill_selection.py`         流式端点清单 + 扫描面 → 同上，并补 `router/*.py`
  · `tests/test_shop_id_guard.py`           strict 依赖模块集合 + 扫描面 → 同上
  · `tests/test_conversation_ownership.py`  扫描面（`rglob("router.py")`）→ 补 `router/*.py`
  · `tests/test_source_size_ratchet.py`     冻结表删除本项（重跑生成器）
  ★ 那三处 `rglob("router.py")` 是**必须**一起改的：包里的 `chat.py` 一个都匹配不到，
    扫描面会**静默**少掉整个模块的端点 —— 门禁不会红，它只是不再检查（第 247 轮形态）。
"""

from fastapi import APIRouter

from . import assets, chat, content, translate

# 创建路由器（prefix / tags 的**唯一**定义处）
router = APIRouter(
    prefix="/aigc",
    tags=["AIGC 媒体生成 (Phase 7)"]
)

# 子模块的 include 顺序 = 端点清单的阅读顺序（不影响匹配：路径全互不重叠）
router.include_router(content.router)
router.include_router(translate.router)
router.include_router(chat.router)
router.include_router(assets.router)

__all__ = ["router"]
