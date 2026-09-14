"""面板驱动的多类型素材出图。

与「对话驱动」的 ``agent_aigc.generate_product_image`` 分开，因为两者的前置契约不同：

- **对话驱动**：Agent 可以先追问缺参（材质/造型/视角/是否带 logo/产品细节/背景规则），
  补齐后再出图 —— 追问是特性。
- **面板驱动（本模块）**：老板在表单里已经把能填的都填了，点「开始生成素材」就该出图。
  这里若因为「没填材质」这类**可选增强**字段而拒绝生成，面板就永远出不了图。

出图模式（两条通道，按**是否拿到可用源图**自动选）：

- **有源图 → 图生图**：万相 ``wanx2.1-imageedit``（``function=description_edit``），
  ``base_image_url`` 收前端传来的 **base64 data URI**。★ 官方文档明确 base64 可直传，
  **不需要图床** —— 之前「必须公网地址」的说法是误判。
- **无源图 → 文生图**：万相 ``wanx2.1-t2i-turbo``，纯文字描述生成。

响应里的 ``source_image_used`` **如实反映实际走的那条通道**，绝不假装用了原图。
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from core.logger import get_logger

from . import image_client, storage

logger = get_logger(__name__)

#: 素材类型 → 中文名 + 两套提示词（与前端 StaticAssetConfig 的类型 id 保持一致）
#: 六类体系（09-14 老板重定义）：SPU 主图 / 白底副图 / 场景图 / 生活方式图 / 信息图解图 / 广告主图
#:
#: - ``prompt``：**描述式**，给文生图用（从零画出这个商品）
#: - ``edit_prompt``：**指令式**，给图生图用（原图已有商品，只改背景/场景，
#:   必须显式说 "keep the product exactly unchanged"，否则模型会把商品也重画一遍）
ASSET_TYPES: dict[str, dict[str, str]] = {
    "spu-main": {
        "label": "SPU 主图",
        "prompt": (
            "hero main image on pure white seamless background, product occupies 85% of frame, "
            "clean studio softbox lighting, subtle contact shadow, Amazon listing first image standard, "
            "strict compliance no props no text"
        ),
        "edit_prompt": (
            "Replace the background with a pure white seamless backdrop, keep the product exactly "
            "unchanged and fully visible, professional Amazon listing main image, clean studio softbox "
            "lighting, product occupies 85% of the frame, no props and no text"
        ),
    },
    "white-bg": {
        "label": "白底副图",
        "prompt": (
            "supplementary image on white seamless background, multiple angles showing the product, "
            "soft even lighting, clean e-commerce secondary image, slightly relaxed but still white background"
        ),
        "edit_prompt": (
            "Replace the background with clean white, keep the product exactly unchanged, "
            "produce a clean e-commerce supplementary image with soft even lighting"
        ),
    },
    "scene": {
        "label": "场景图",
        "prompt": (
            "placed in a realistic everyday-use scene, natural ambient light, "
            "clean composed background, showing the product in real use, conversion-focused lifestyle scene"
        ),
        "edit_prompt": (
            "Place the product into a realistic everyday-use scene, keep the product exactly unchanged, "
            "natural ambient light, clean composed background, conversion-focused"
        ),
    },
    "lifestyle": {
        "label": "生活方式图",
        "prompt": (
            "lifestyle editorial shot conveying an aspirational mood, warm natural light, "
            "tasteful minimal props, emotional appeal, real-world usage context"
        ),
        "edit_prompt": (
            "Place the product into an aspirational lifestyle setting, keep the product exactly unchanged, "
            "warm natural light, tasteful minimal props, emotional appeal"
        ),
    },
    "infographic": {
        "label": "信息图解图",
        "prompt": (
            "clean infographic-style image with key product parameters and selling points as visual callouts, "
            "icons and short labels, no long text, clear benefit communication, Amazon A+ image standard"
        ),
        "edit_prompt": (
            "Keep the product exactly unchanged and add clean infographic-style callouts around it: "
            "key product parameters and selling points with simple icons and short labels, "
            "no long text, clear benefit communication, Amazon A+ image standard"
        ),
    },
    "ad-main": {
        "label": "广告主图",
        "prompt": (
            "eye-catching advertising creative for sponsored ads, can include scene or lifestyle context, "
            "high click-through visual, bold composition, not for product detail main image"
        ),
        "edit_prompt": (
            "Keep the product exactly unchanged and place it in an eye-catching advertising composition, "
            "bold visual, high click-through scene context, sponsored ads creative"
        ),
    },
}

#: 单类型最多出几张（成本保护）
MAX_PER_TYPE = 4
#: 单次请求总张数上限（成本保护；turbo ≈ ¥0.14/张）
MAX_TOTAL = 8

#: 统一负向提示词：电商素材最怕出现乱码文字与水印
NEGATIVE_PROMPT = "text, letters, watermark, logo, blurry, distorted, low quality, extra limbs"


def build_asset_prompt(
    product_name: str,
    asset_type: str,
    *,
    category: str = "",
    extra_description: str = "",
    use_source: bool = False,
) -> str:
    """拼万相提示词。**两条通道写法不同**，别复用同一份：

    - ``use_source=True``（图生图）：用 ``edit_prompt`` 的**指令语气** —— 原图里已经有
      商品了，再把商品描述一遍反而会诱导模型重画主体。
    - ``use_source=False``（文生图）：用描述式，从零把商品画出来。
    """
    spec = ASSET_TYPES.get(asset_type) or ASSET_TYPES["spu-main"]

    if use_source:
        prompt = spec.get("edit_prompt") or spec["prompt"]
        if extra_description:
            prompt += f". Additional requirement: {extra_description}"
        return prompt

    prompt = f"Professional e-commerce product photography of {product_name}"
    if category and category != "general":
        prompt += f", category: {category}"
    prompt += f", {spec['prompt']}"
    if extra_description:
        prompt += f", additional details: {extra_description}"
    prompt += ", high resolution, sharp focus, centered composition"
    return prompt


def normalize_types(image_types: list[str] | None) -> list[str]:
    """过滤未知类型、去重、保序；空则回落到 SPU 主图。"""
    seen: list[str] = []
    for t in image_types or []:
        if t in ASSET_TYPES and t not in seen:
            seen.append(t)
    return seen or ["spu-main"]


async def generate_assets(
    *,
    product_name: str,
    image_types: list[str] | None = None,
    category: str = "general",
    extra_description: str = "",
    count_per_type: int = 1,
    size: str = image_client.DEFAULT_SIZE,
    source_image: str = "",
) -> dict[str, Any]:
    """按素材类型并发出图，返回可直接给前端渲染的结构。

    ``source_image``：产品原图（公网 URL 或 **base64 data URI**）。给了就走**图生图**
    （原图参与生成），空则退回**文生图**。

    任何一张失败都不影响其余（逐项降级，把失败原因带回去）；全部失败时
    ``degraded=True`` + ``degraded_reason``，**绝不用占位图凑数**。
    """
    types = normalize_types(image_types)
    per_type = max(1, min(int(count_per_type or 1), MAX_PER_TYPE))
    # 只有真正拿到非空源图才算「原图参与生成」——空串/纯空白一律按没有处理
    source_image = (source_image or "").strip()
    use_source = bool(source_image)

    # 组装任务：每个类型 × count_per_type
    jobs: list[tuple[str, str, str]] = []  # (asset_type, prompt, desc)
    for t in types:
        label = ASSET_TYPES[t]["label"]
        for i in range(per_type):
            desc = label if per_type == 1 else f"{label} {i + 1}"
            jobs.append((
                t,
                build_asset_prompt(
                    product_name,
                    t,
                    category=category,
                    extra_description=extra_description,
                    use_source=use_source,
                ),
                desc,
            ))

    # 成本保护：超出上限时按轮次裁剪（保证每个类型至少一张）
    if len(jobs) > MAX_TOTAL:
        kept: list[tuple[str, str, str]] = []
        round_idx = 0
        while len(kept) < MAX_TOTAL:
            added = False
            for t in types:
                matches = [j for j in jobs if j[0] == t]
                if round_idx < len(matches) and len(kept) < MAX_TOTAL:
                    kept.append(matches[round_idx])
                    added = True
            if not added:
                break
            round_idx += 1
        jobs = kept

    if not image_client.is_enabled():
        return {
            "mode": "disabled",
            "model": image_client.DEFAULT_EDIT_MODEL if use_source else image_client.DEFAULT_MODEL,
            "assets": [],
            "degraded": True,
            "degraded_reason": "真实出图已关闭（AIGC_IMAGE_REAL_GEN=0）",
            "failed": [],
            "source_image_used": False,
        }

    if use_source:
        # 图生图：同一张底图 + 各类型不同的编辑指令。
        # 注意本端点不吃 size / negative_prompt（传了会被拒）。
        results = await image_client.image_edit_many(
            [j[1] for j in jobs],
            base_image=source_image,
        )
    else:
        results = await image_client.text2image_many(
            [j[1] for j in jobs],
            size=size,
            negative_prompt=NEGATIVE_PROMPT,
        )

    assets: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")

    for idx, ((asset_type, prompt, desc), (_p, url, error)) in enumerate(zip(jobs, results)):
        if error or not url:
            failed.append({"type": asset_type, "type_label": ASSET_TYPES[asset_type]["label"], "error": error or "未返回图片"})
            continue
        try:
            # 万相链接 24h 过期 → 必须转存成 /static 长期链接
            local_url = await storage.persist_remote_image(url)
        except Exception as exc:  # noqa: BLE001 - 转存失败则退回临时链接，并记录
            logger.error(f"[aigc] 转存失败，暂用临时链接：{exc}")
            local_url = url
            failed.append({"type": asset_type, "type_label": ASSET_TYPES[asset_type]["label"], "error": f"转存失败（临时链接 24h 后失效）：{exc}"})

        assets.append({
            "id": f"asset_{stamp}_{idx}_{random.randint(100, 999)}",
            "type": asset_type,
            "type_label": ASSET_TYPES[asset_type]["label"],
            "desc": desc,
            "prompt": prompt,
            "url": local_url,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    degraded = not assets
    reason = None
    if degraded:
        reason = "全部素材生成失败：" + ("；".join(f"{f['type_label']}（{f['error']}）" for f in failed) or "原因未知")

    if use_source:
        notice = (
            "当前为图生图（原图参与生成）—— 以载入的产品原图为底图，按所选素材类型重绘"
            "背景/场景，产品主体保持不变。"
        )
    else:
        notice = (
            "当前为文生图（纯文字描述生成）—— 本次未取到可用的产品原图，"
            "生成结果与实物可能存在差异。重新载入产品原图后可切换为图生图。"
        )

    return {
        "mode": "image2image" if use_source else "text2image",
        "model": image_client.DEFAULT_EDIT_MODEL if use_source else image_client.DEFAULT_MODEL,
        "assets": assets,
        "failed": failed,
        "degraded": degraded,
        "degraded_reason": reason,
        "source_image_used": use_source,
        "notice": notice,
    }
