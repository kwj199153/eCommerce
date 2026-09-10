"""
素材库种子数据

首次启动（assets 表为空）时，把前端 MOCK_ASSETS 的 7 条素材预置到 PG。

数据来源：frontend/src/stores/assetLibrary.ts 的 MOCK_ASSETS。
"""

from sqlalchemy import select, func
from core.database import async_session_factory
from modules.assets.db_model import AssetRecord

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


async def seed_assets_if_empty() -> int:
    """首次启动时，若 assets 表为空，预置种子数据。返回预置条数。"""
    async with async_session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(AssetRecord))).scalar_one()
        if count > 0:
            return 0
        for data in SEED_ASSETS:
            record = AssetRecord(
                id=data["id"],
                name=data["name"],
                kind=data["kind"],
                category=data["category"],
                url=data["url"],
                thumbnail=data.get("thumbnail"),
                videoUrl=data.get("videoUrl"),
                productId=data.get("productId"),
                productName=data.get("productName"),
                asin=data.get("asin"),
                prompt=data.get("prompt"),
                source=data["source"],
                width=data.get("width"),
                height=data.get("height"),
                tags=data.get("tags") or [],
                groups=data.get("groups") or [],
                notes=data.get("notes") or "",
                createdAt=data["createdAt"],
                updatedAt=data["createdAt"],
            )
            session.add(record)
        await session.commit()
    return len(SEED_ASSETS)
