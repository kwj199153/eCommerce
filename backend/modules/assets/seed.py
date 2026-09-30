"""
素材库种子数据

首次启动（assets 表为空）时，把前端 MOCK_ASSETS 的 7 条素材预置到 PG。

数据来源：frontend/src/stores/assetLibrary.ts 的 MOCK_ASSETS。
"""

from typing import Sequence
from sqlalchemy import select, func
from core.database import async_session_factory
from modules.assets.db_model import AssetRecord
from core.stores import StoreRecord

SEED_ASSETS = [
    {
        "id": "asset-000", "name": "便携加湿器 - 白底主图", "kind": "image", "category": "white-bg",
        "url": "https://picsum.photos/seed/asset-humidifier-white/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-humidifier-white/120/120",
        "productId": "prod-000", "productName": "Portable Mini Humidifier for Bedroom Desk USB Cool Mist", "asin": "B0CEXIZ001",
        "prompt": "Pure white background, portable mini humidifier, front 45° angle, studio lighting",
        "source": "aigc", "tags": ["主图", "白底"], "groups": [], "notes": "AI 静态素材生成 - 白底图",
        "createdAt": "2026-09-01T07:00:00Z",
    },
    {
        "id": "asset-001", "name": "无线蓝牙耳机 - 三视图 1", "kind": "image", "category": "three-view",
        "url": "https://picsum.photos/seed/asset-earphone-3v1/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-earphone-3v1/120/120",
        "productId": "prod-001", "productName": "无线蓝牙耳机 降噪头戴式 长续航40小时 HiFi音质", "asin": "B0DGXRLVLC",
        "prompt": "Product three-view: front, side, back on pure white background",
        "source": "aigc", "tags": ["三视图"], "groups": [], "notes": "AI 静态素材生成 - 多角度三视图",
        "createdAt": "2026-09-01T07:30:00Z",
    },
    {
        "id": "asset-002", "name": "无线蓝牙耳机 - 细节特写（耳罩）", "kind": "image", "category": "detail",
        "url": "https://picsum.photos/seed/asset-earphone-detail/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-earphone-detail/120/120",
        "productId": "prod-001", "productName": "无线蓝牙耳机 降噪头戴式 长续航40小时 HiFi音质", "asin": "B0DGXRLVLC",
        "source": "aigc", "tags": ["细节图"], "groups": [], "notes": "AI 静态素材生成 - 细节特写",
        "createdAt": "2026-09-01T07:31:00Z",
    },
    {
        "id": "asset-003", "name": "瑜伽垫 - 生活方式场景", "kind": "image", "category": "lifestyle",
        "url": "https://picsum.photos/seed/asset-yoga-lifestyle/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-yoga-lifestyle/120/120",
        "productId": "prod-004", "productName": "瑜伽垫 加厚10mm 双面防滑 TPE环保 无味", "asin": "B0GHI23456",
        "prompt": "Woman doing yoga on thick mat in bright living room, morning light, lifestyle photography",
        "source": "aigc", "tags": ["场景图", "A+ 配图"], "groups": [], "notes": "可作 A+ Content 配图",
        "createdAt": "2026-09-01T08:00:00Z",
    },
    {
        "id": "asset-004", "name": "加湿器带货视频 - 分镜首帧 01", "kind": "image", "category": "storyboard-frame",
        "url": "https://picsum.photos/seed/asset-frame-01/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-frame-01/120/120",
        "productId": "prod-000", "productName": "Portable Mini Humidifier for Bedroom Desk USB Cool Mist", "asin": "B0CEXIZ001",
        "source": "video-gen", "tags": ["首帧"], "groups": [], "notes": "短视频脚本 - 镜头 1 首帧",
        "createdAt": "2026-09-01T09:00:00Z",
    },
    {
        "id": "asset-005", "name": "智能保温杯 - 30s 种草短视频", "kind": "video", "category": "video",
        "url": "https://picsum.photos/seed/asset-video-cover/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-video-cover/120/120",
        "videoUrl": "/mock/generated_video.mp4",
        "productId": "prod-002", "productName": "智能保温杯 温度显示 304不锈钢 大容量500ml", "asin": "B0ABC12345",
        "source": "video-gen", "width": 1080, "height": 1920,
        "tags": ["短视频"], "groups": [], "notes": "AI 短视频生成 - 9:16 竖版",
        "createdAt": "2026-09-01T10:00:00Z",
    },
    {
        "id": "asset-006", "name": "电动牙刷 - 拍摄原图（用户上传）", "kind": "image", "category": "other",
        "url": "https://picsum.photos/seed/asset-toothbrush-raw/600/600",
        "thumbnail": "https://picsum.photos/seed/asset-toothbrush-raw/120/120",
        "productId": "prod-003", "productName": "电动牙刷 成人声波震动 5档模式 IPX7防水 续航90天", "asin": "B0DEF67890",
        "source": "upload", "tags": ["实拍原图"], "groups": [], "notes": "图生图输入原图",
        "createdAt": "2026-09-01T11:00:00Z",
    },
]


async def seed_assets_if_empty(*, only_for_shop_ids: Sequence[str] = ()) -> int:
    """
    首次启动时，若 assets 表为空，**为每个已存在的店铺**预置种子数据。

    Returns:
        实际写入的素材条数（表非空、或无店铺可归属时返回 0）。

    ★★ 2026-09-15 修复（P0：全新库上「素材库预置」从未成功过）
    ------------------------------------------------------------------
    修复前本函数**根本不写 shop_id** ⇒ 落到 `server_default=''`。两个后果：
      1) 可见性：`GET /api/v1/assets` 是 `where(AssetRecord.shop_id == shop_id)`，
         空串匹配不上任何店铺 ⇒「灌了但等于没灌」（与 2026-09-12 修掉的
         `shop-1` 硬编码是同一类 bug）；
      2) 完整性：本轮补上的外键 `fk_assets_shop_id_stores_store` 要求 shop_id
         指向真实店铺 ⇒ 空串直接违约，实测（探针 script-r51_seed_fresh_db.py，
         空库 + 1 店铺）：
             ForeignKeyViolationError: insert or update on table "assets"
               violates foreign key constraint "fk_assets_shop_id_stores_store"

    开发库为什么没暴露：assets 表早已非空（真实上传素材），开头的
    `if count > 0: return 0` 守卫把这条插入路径**永久短路**了 ——
    正是 test_seed_shop_ids.py 文件头警告的那颗「定时炸弹」。

    ⇒ 改为与 products / candidates / monitors 同款写法：查 stores 表取真实
      店铺 id；无店铺则返回 0；多店铺下 id 追加店铺后缀（assets 是 id 单主键，
      不追加会在第二个店铺上主键冲突）。
    ★★★ `only_for_shop_ids`（第 175 轮新增）：**只给点名店铺补灌**，绕过全表守卫
    ★★ 当前状态（第 176 轮）：**启动流程不再自动调用它**。第 175 轮的演示店铺是
       「新建一家空店」，必须补灌；第 176 轮的演示店铺是「演示账号名下那 4 家本来
       就有数据的店」，自动补灌只会把 `SEED_*` 里的 `https://picsum.photos/...`
       随机图灌进原本干净的店铺（实测：虾皮1/2、亚马逊2 各多出 3~7 行，图片与商品
       完全无关 —— 正是老板抱怨的「图与商品不对应」）。
       参数保留，供将来「给指定店铺补灌」使用。
    ----------------------------------------------------------------------
    本函数原本的守卫是「**全表**非空 ⇒ 整个函数不执行」。它保证了幂等，但也意味着
    **任何在此之后新建的店铺，一份种子数据都拿不到** —— 演示店铺
    （`is_demo=true`，见 `modules/stores/demo.py`）正是这种情况：它由
    第 175 轮那家演示店铺当时是「**按需新建**」出来的，而那时本表早就非空。
    （第 176 轮起演示店铺改为「演示账号名下那 4 家**本来就有数据**的店」，
      启动流程已**不再**自动调用本参数 —— 见下文 `only_for_shop_ids` 段。）

    传这个参数就跳过全表守卫，改为**按店铺判空**：已有数据的店铺不动（幂等），
    点名的空店铺灌一份。不传时行为与改造前**逐字一致** ——
    `tests/test_seed_shop_ids.py::test_seed_is_idempotent_when_table_not_empty`
    断言"表非空 ⇒ 返回 0"，那条契约不能被稀释（它连的是开发库，表恒非空）。

    ★ 只灌**真实存在于 stores 表**的店铺（`s in known`）：调用方传错 id 时
      静默跳过，而不是造出一批永久孤儿数据。
    """
    async with async_session_factory() as session:
        # 取真实店铺 id；一个都没有则跳过（无租户上下文，灌了也查不到）
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        if only_for_shop_ids:
            # ---- 只给点名店铺补灌（第 175 轮：演示店铺走这条通道）----
            already = set((await session.execute(
                select(AssetRecord.shop_id).distinct()
            )).scalars().all())
            known = set(shop_ids)
            targets = [s for s in only_for_shop_ids if s in known and s not in already]
        else:
            # ---- 默认：全表非空即跳过（与改造前**逐字一致**）----
            existing = (await session.execute(
                select(func.count()).select_from(AssetRecord)
            )).scalar_one()
            if existing > 0:
                return 0
            targets = list(shop_ids)

        total = 0
        for shop_id in targets:
            for data in SEED_ASSETS:
                record = AssetRecord(
                    id=f"{data['id']}-{shop_id}",
                    name=data["name"],
                    kind=data["kind"],
                    category=data["category"],
                    url=data["url"],
                    thumbnail=data.get("thumbnail"),
                    videoUrl=data.get("videoUrl"),
                    # ★ 与 products seed 保持一致：那里的 SPU id 是
                    #   `f"{data['id']}-{shop_id}"`（多店铺必须加后缀，否则主键冲突）。
                    #   这里若仍写死 "prod-000"，素材关联的产品在库里根本不存在
                    #   ⇒ 素材页显示不出关联产品。同源后缀，引用才对得上。
                    productId=(
                        f"{data['productId']}-{shop_id}" if data.get("productId") else None
                    ),
                    productName=data.get("productName"),
                    asin=data.get("asin"),
                    prompt=data.get("prompt"),
                    source=data["source"],
                    width=data.get("width"),
                    height=data.get("height"),
                    tags=data.get("tags") or [],
                    groups=data.get("groups") or [],
                    notes=data.get("notes") or "",
                    shop_id=shop_id,
                    createdAt=data["createdAt"],
                    updatedAt=data["createdAt"],
                )
                session.add(record)
                total += 1
        await session.commit()
    return total
