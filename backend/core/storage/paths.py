"""上传目录与静态资源前缀的**唯一实现**。

==============================================================================
★ 为什么从 `modules/aigc_media/storage.py` 上收到这里
==============================================================================
原本只有一家在算 `uploads/` 的绝对路径（AIGC 出图转存）。
补 `POST /users/avatar`（头像上传）时出现了**第二个消费者**——
而头像属身份模块，位于 `core/identity/`。

若让 `core/identity` 反向 import `modules/aigc_media`，依赖方向就颠倒了：
**core 是更底层的一环，不该知道任何业务模块的存在**（即便本仓的
`test_infra_layering` 只把 `ai_infra` 列为硬红线，方向本身仍然不成立）。

⇒ 按项目判据「同一判定出现两份实现 ⇒ 至少有一份永远测不到」，
  把路径计算上收到 core，业务侧反向引用：

      core/storage/paths.py  ←─ core/identity/users_router.py（头像）
                             ←─ modules/aigc_media/storage.py（远程图转存，re-export）

★ `config.upload_dir` 默认是相对路径 `./uploads`，直接拼会受**启动 CWD** 影响
  （从 `backend/` 起、还是从仓库根起，结果不同）。这里统一按 `backend/` 解析：
  本文件位于 `backend/core/storage/paths.py` ⇒ `parents[2]` 即 `backend/`。
"""

from pathlib import Path

from core.config import config

#: 对外暴露的静态路径前缀（`main.py` 把 uploads 目录挂到它下面）
STATIC_PREFIX = "/static"

#: 允许的图片扩展名（头像与 AIGC 素材共用同一份白名单）
IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def upload_root() -> Path:
    """`uploads` 目录的绝对路径（相对 `config.upload_dir` 解析）。"""
    root = Path(config.upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root
