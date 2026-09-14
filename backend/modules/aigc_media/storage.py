"""把远程图片转存为本地可长期访问的静态 URL。

万相出图返回的是 OSS 临时链接（实测 24 小时过期）。若把临时链接直接存进素材库，
第二天全部失效 —— 属于「静默失效」，本项目不允许（老板铁律：降级必须显式给原因）。
所以出图后立即落盘，对外只暴露 ``/static/aigc/<sha1>.<ext>``。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx

from core.config import config
from core.logger import get_logger

logger = get_logger(__name__)

#: 对外暴露的静态路径前缀（main.py 把 uploads 挂到它下面）
STATIC_PREFIX = "/static"
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def upload_root() -> Path:
    """``uploads`` 目录的绝对路径。

    ``config.upload_dir`` 默认是相对路径 ``./uploads`` —— 直接拼会受启动 CWD
    影响，统一按 ``backend/`` 解析（本文件位于 ``backend/modules/aigc_media/``）。
    """
    root = Path(config.upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root


async def persist_remote_image(url: str, *, subdir: str = "aigc", timeout: float = 60.0) -> str:
    """下载远程图片到 ``uploads/<subdir>/``，返回 ``/static/<subdir>/<文件名>``。

    文件名 = URL 的 sha1 前 16 位 + 原扩展名 → 同一张图重复转存不堆垃圾（幂等）。
    """
    if not url:
        raise ValueError("图片 URL 为空")

    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in _ALLOWED_EXT:
        ext = ".png"
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext

    target_dir = upload_root() / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name

    if not target.exists():
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(f"图片下载失败（HTTP {resp.status_code}）")
        target.write_bytes(resp.content)
        logger.info(f"[aigc-storage] 已转存 {subdir}/{name}（{len(resp.content)} 字节）")

    return f"{STATIC_PREFIX}/{subdir}/{name}"
