"""营销素材库的声明式查询元数据（第 218 轮 · P1）。

★ 与侧边栏菜单 key 对齐：`Sidebar/KnowledgeBase.vue` 里这一项是 `key="assets"`，
  本 spec 的 `key` 就取 `"assets"` —— 跨端对齐门禁按**同一张表**核对，
  避免「后端叫一个名、页面叫另一个名」那种只能靠人记住的对应关系。

★ `default_sort="created_at"`（倒序）与前端 `stores/assetLibrary.ts` 的两处
  `sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))` **同一口径**。
  ★ 而改前 REST 端点是**没有排序**的（DB 自然顺序）—— 前端自己重排过，
    所以那个未定义顺序从未被用户看见；现在收敛成确定性排序，Agent 才拿得到稳定结果。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.assets.db_model import AssetRecord

#: 营销素材库的声明式元数据（唯一真源）。
ASSET_SPEC = LibrarySpec(
    key="assets",
    label="营销素材库",
    model=AssetRecord,
    # ★ 列名是 camelCase（`createdAt` / `updatedAt`）—— 与前端 AssetItem 一致，
    #   不是 snake_case；写错的话 LibrarySpec 构造期就会炸（hasattr 核对）。
    sort_fields={
        "created_at": ("createdAt", "desc"),
        "updated_at": ("updatedAt", "desc"),
        "name": ("name", "asc"),
        "kind": ("kind", "asc"),
    },
    default_sort="created_at",
    filters={
        # 值域取自 `assets/db_model.py` 的列注释（image / video）。
        "kind": FilterSpec("kind", ("image", "video")),
        # category / source 自由文本：category 的取值是前端配置驱动的
        # （`white-bg` / `three-view` / …），后端再硬编码一份就会出现
        # 「前端能选、后端拒收」—— 与本仓 knowledge_base / platform_rules
        # 对枚举的两个既有取舍一致。
        "category": FilterSpec("category"),
        "source": FilterSpec("source", ("aigc", "upload", "video-gen", "manual")),
    },
)
