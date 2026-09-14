"""
平台规则库 - AI 拆分（从文档正文提取结构化规则）

数据流：
    `doc.content`（整篇文档）→ LLM → 结构化规则数组 → 前端查重标注 → 用户勾选确认 → 入库

**为什么查重留在前端**：
`stores/platformRules.ts` 的 `checkDuplicate()`（关键词 Jaccard 重叠率 + 数值 diff 判定
「版本更新」）是纯函数，且必须能在**用户勾选时**复用同一份逻辑做 Layer 3 终检 ——
那时不该再往返一次后端。若把查重搬到后端，「预标注」与「终检」就会变成两份实现，
迟早分叉。故后端只负责「提取」，标注交给前端沿用同一份算法。

**LLM 不可用时绝不编造**：
返回 `degraded=True` + 空数组 + 明确原因，由前端提示「AI 拆分暂不可用」。
这是本项目家规 —— 宁可空状态，不要虚构默认。
（旧实现是前端用写死的 templateMap 冒充「AI 提取」，会产出「需 FCC/CE 认证」
这类**文档里根本没有**的规则，属于典型的虚构默认。）
"""

import logging
from datetime import datetime
from typing import Optional

from modules.platform_rules.db_model import PlatformRuleDocRecord

try:
    from ai_infra.llm.dashscope_client import get_llm
    LLM_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失时降级
    LLM_AVAILABLE = False

logger = logging.getLogger(__name__)


# 单次最多提取条数（防止一篇长文档吐出 50 条把确认弹窗撑爆）
MAX_RULES = 12
# 送进 LLM 的正文上限（超出截断；一篇 4k 字符的文档远未触顶）
MAX_DOC_CHARS = 8000

SPLIT_SYSTEM_PROMPT = (
    "你是跨境电商平台规则分析专家。任务：从给定的平台官方文档中提取**卖家可执行的规则条目**，"
    "以 JSON 数组输出。\n"
    "每条规则包含字段：\n"
    "- category：listing / policy / compliance / payment / logistics / review / ad 之一\n"
    "- title：≤40 字的中文短语标题（不要序号、不要书名号）\n"
    "- content：中文规则正文，保留原文的关键数值与限制条件\n"
    "- tags：2~4 个中文关键词\n"
    "硬性规则：\n"
    "1. 只提取文档中**真实存在**的内容。禁止补充文档里没有的认证、法规、数据、时效——\n"
    "   宁可少提几条，也不要编造一条。\n"
    "2. 数值、字符数限制、时限必须与原文一致（如「200 字符」「< 1%」），不要改写单位或四舍五入。\n"
    "3. content 必须能独立读懂，禁止写「如上所述」「见第 3 节」这类依赖上下文的指代。\n"
    f"4. 最多提取 {MAX_RULES} 条；优先提取对卖家有明确行动指导意义的条款。\n"
    "5. 只输出 JSON 数组本身，不要任何解释文字、不要 Markdown 代码块包裹。"
)


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _build_user_prompt(doc: PlatformRuleDocRecord, content: str) -> str:
    """构造 user 消息：文件名 + 平台 + 正文（超长截断）"""
    body = content[:MAX_DOC_CHARS]
    truncated = "\n\n（注：原文过长，以上为截断后的内容）" if len(content) > MAX_DOC_CHARS else ""
    return (
        f"平台：{doc.platform}\n"
        f"文档名：{doc.filename}\n"
        f"文档正文如下：\n\n---\n{body}{truncated}\n---"
    )


def normalize_llm_rules(data, doc: PlatformRuleDocRecord) -> list:
    """
    把 LLM 返回的任意结构清洗成**前端 PlatformRule 形态**的规则数组（不含 id/时间戳，
    由入库时生成）。这是本模块的纯函数核心，便于单测。

    清洗规则：
      - `structured_chat` 解析失败会返回 `{"raw_text": ...}` → 视为无结果（不猜）
      - 兼容 LLM 直接返回数组、或包一层 `{"rules": [...]}` / `{"items": [...]}`
      - **缺 title 或 content 的条目直接丢弃**，不补空壳（补出来的规则对用户无意义）
      - 平台一律取文档的 platform（LLM 无权改归属）
    """
    if isinstance(data, dict):
        if "raw_text" in data:
            return []
        picked = None
        for key in ("rules", "items", "data", "result", "list"):
            if isinstance(data.get(key), list):
                picked = data[key]
                break
        data = picked if picked is not None else []
    if not isinstance(data, list):
        return []

    out = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        content = str(raw.get("content") or "").strip()
        if not title or not content:
            continue
        tags = [
            str(t).strip() for t in (raw.get("tags") or [])
            if isinstance(t, (str, int, float)) and str(t).strip()
        ]
        out.append({
            "platform": doc.platform,
            "category": str(raw.get("category") or "policy").strip() or "policy",
            "title": title[:200],
            "content": content,
            "effective_date": str(raw.get("effective_date") or _today()),
            "status": "auto",
            "tags": tags[:6],
            "source_doc_id": doc.id,
            "source": "",
        })
        if len(out) >= MAX_RULES:
            break
    return out


async def split_rules_from_doc(doc: PlatformRuleDocRecord) -> dict:
    """
    从文档正文提取结构化规则。

    Returns:
        {
          "extracted": int,        # 提取条数
          "rules": list,           # 原始规则（**未标注查重**，前端补 _dupStatus）
          "degraded": bool,        # True = LLM 不可用/无正文/提取失败
          "reason": str,           # degraded 时的中文原因（直接给用户看）
        }
    """
    content = (doc.content or "").strip()
    if not content:
        return {
            "extracted": 0, "rules": [], "degraded": True,
            "reason": "该文档没有正文内容，无法提取规则（上传时未提供正文）",
        }

    if not LLM_AVAILABLE:
        return {
            "extracted": 0, "rules": [], "degraded": True,
            "reason": "AI 服务不可用，无法拆分文档",
        }

    try:
        llm = get_llm()
        data = await llm.structured_chat(
            user_message=_build_user_prompt(doc, content),
            system_prompt=SPLIT_SYSTEM_PROMPT,
            output_format="json",
            # 提取类任务要稳定：同一篇文档两次提取应得到同一批规则
            temperature=0.2,
            max_tokens=3000,
        )
    except Exception as e:
        logger.warning(f"[platform_rules] ai-split LLM 调用失败: {e}")
        return {
            "extracted": 0, "rules": [], "degraded": True,
            "reason": "AI 服务调用失败，请稍后重试",
        }

    rules = normalize_llm_rules(data, doc)
    if not rules:
        return {
            "extracted": 0, "rules": [], "degraded": True,
            "reason": "AI 未能从该文档中提取出可用于入库的规则，请检查文档内容",
        }
    return {"extracted": len(rules), "rules": rules, "degraded": False, "reason": ""}
