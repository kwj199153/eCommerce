"""
业务话术库 - AI 拆分（从文档正文提取客服话术条目）

数据流：
    `doc.content`（整篇文档）→ LLM → 结构化问答条目 → **草稿**（status=draft）
    → 人工确认 → 发布（status=active）→ 进入客服检索

==============================================================================
★ 与 `platform_rules/ai_split.py` 的三处**刻意**差异（别顺手"统一"掉）
==============================================================================

① 落库状态是 **draft，不是 active**（老板第 288 轮拍板）。
   `customer_service/faq_source.py::load_faq_items` 只查 `status == "active"`，
   ⇒ 拆出来的条目**未经人工确认就绝不进检索**。
   这不是"前端记得传 status"就能保证的：本模块在 `normalize_llm_faqs` 里
   **写死** `status="draft"`，service 侧落库时再强制一次（双保险）。
   理由不是流程洁癖：LLM 会把文档里的**内部口径**（成本价、利润率、
   供应商名、只对特定站点生效的承诺）当成答案的一部分写出来 —— 这类内容
   一旦 active，就是直接发给买家的。

② 不做 platform_rules 那套「_dupStatus 三层去重」。
   规则条目有**时效**（同一条规则会出新版 ⇒ 需要"重复/更新"二分类）；
   话术条目没有 —— 同问不同答就是**错误**，不是"新版本"。
   ⇒ 这里只做一层最朴素的判重：同 kb 下 `question` 完全相同的跳过
   （见 `service.create_faq_drafts`）。判定权交回给人。

③ 查重不在前端。platform_rules 把查重放前端是为了"预标注与终检共用一份
   算法"；这里没有终检环节（重复直接跳过、人看结果），放后端即可。

==============================================================================
★ LLM 不可用时绝不编造（本仓家规）
==============================================================================
返回 `degraded=True` + 空数组 + 明确原因，由前端提示"AI 拆分暂不可用"。
旧实现（平台规则库早期）用写死的 templateMap 冒充 AI 提取，会产出文档里
根本没有的条款 —— 比"提取失败"有害得多。
"""

import logging
from typing import Any, Dict, List, Optional

from modules.knowledge_base.db_model import KnowledgeDocRecord

try:
    from ai_infra.llm.dashscope_client import get_llm, is_llm_parse_failed
    LLM_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失时降级
    LLM_AVAILABLE = False

logger = logging.getLogger(__name__)


# 单次最多提取条数（一篇政策文档通常 5~10 条；上限防 LLM 一口气吐 50 条）
MAX_FAQS = 12
# 送进 LLM 的正文上限（超出截断并在提示里说明）
MAX_DOC_CHARS = 8000


#: `knowledge_faqs.category` 的**唯一合法取值**（表 owner 是本模块，故口径在此收口）。
#:
#: ★ 与 `customer_service/faq_source.py::CATEGORY_LABELS` 是**同一份口径的两处书写**：
#:   那边是 PLUGIN，本模块不能 import 它（PLUGIN→PLUGIN 不许 import 期依赖，
#:   见 `tests/test_module_layering.py`），反向也不行（会造成循环）。
#:   ⇒ 由 `tests/test_kb_doc_ai_split.py::test_category_codes_match_customer_service`
#:     断言两边集合**恒等**（测试层不受分层约束）。改任一侧都必须同步另一侧。
FAQ_CATEGORY_CODES: Dict[str, str] = {
    "shipping": "物流",
    "return": "退换货",
    "order": "订单",
    "aftersale": "售后",
    "product": "产品",
    "payment": "支付",
    "account": "账户",
    "policy": "政策",
    "review": "评价",
    "other": "其他",
}

#: LLM 常给的中文/别名 → canonical code（LLM 不受约束，只能事后归一）
_CATEGORY_ALIASES: Dict[str, str] = {
    "物流": "shipping", "发货": "shipping", "配送": "shipping", "运输": "shipping",
    "快递": "shipping", "时效": "shipping",
    "退换货": "return", "退货": "return", "退款": "return", "换货": "return",
    "订单": "order", "下单": "order", "查单": "order",
    "售后": "aftersale", "保修": "aftersale", "质保": "aftersale", "维修": "aftersale",
    "产品": "product", "商品": "product", "尺码": "product", "规格": "product",
    "支付": "payment", "付款": "payment", "发票": "payment", "开票": "payment",
    "账户": "account", "账号": "account", "注册": "account",
    "政策": "policy", "规则": "policy", "条款": "policy",
    "评价": "review", "差评": "review", "评分": "review",
}

_PRIORITY_CODES = ("high", "medium", "low")


SPLIT_FAQ_SYSTEM_PROMPT = (
    "你是跨境电商客服话术专家。任务：从给定的售后/政策文档中提取"
    "**买家会问、客服可直接照读发给买家**的问答条目，以 JSON 数组输出。\n"
    "每条包含字段：\n"
    f"- category：{' / '.join(FAQ_CATEGORY_CODES)} 之一\n"
    "- question：买家视角的中文问句（≤30 字，如「多久能收到货？」）\n"
    "- answer：客服可直接发送给买家的中文答复，保留原文的关键数值与时限\n"
    "- keywords：2~4 个中文检索关键词\n"
    "- priority：high / medium / low（买家最常问的标 high）\n"
    "硬性规则：\n"
    "1. 只提取文档中**真实存在**的内容。禁止补充文档里没有的时限、金额、承诺——\n"
    "   宁可少提几条，也不要编造一条。\n"
    "2. 数值与时限必须与原文一致（如「7 天」「30 天」），不要改写单位或四舍五入。\n"
    "3. answer 必须能独立读懂，禁止「如上所述」「见第 3 节」这类依赖上下文的指代。\n"
    "4. answer 面向买家：不得出现成本价、利润率、供应商名、内部流程等不宜外露的信息。\n"
    f"5. 最多提取 {MAX_FAQS} 条；优先提取买家最常问的。\n"
    "6. 只输出 JSON 数组本身，不要任何解释文字、不要 Markdown 代码块包裹。"
)


def normalize_category(raw: Any) -> str:
    """把 LLM 给的任意分类值归一到 `FAQ_CATEGORY_CODES`（未知 ⇒ other，不猜）"""
    text = str(raw or "").strip()
    if not text:
        return "other"
    low = text.lower()
    if low in FAQ_CATEGORY_CODES:
        return low
    # 中文没有大小写之分，先查原文再查小写（英文场景）
    return _CATEGORY_ALIASES.get(text, _CATEGORY_ALIASES.get(low, "other"))


def normalize_priority(raw: Any) -> str:
    p = str(raw or "").strip().lower()
    return p if p in _PRIORITY_CODES else "medium"


def _build_user_prompt(doc: KnowledgeDocRecord, content: str) -> str:
    """构造 user 消息：文件名 + 正文（超长截断并**告知** LLM 已截断）"""
    body = content[:MAX_DOC_CHARS]
    truncated = (
        "\n\n（注：原文过长，以上为截断后的内容，请只依据已给出的部分提取）"
        if len(content) > MAX_DOC_CHARS else ""
    )
    return (
        f"文档名：{doc.filename}\n"
        f"文档说明：{doc.description or '（无）'}\n"
        f"文档正文如下：\n\n---\n{body}{truncated}\n---"
    )


def normalize_llm_faqs(
    data: Any,
    doc: KnowledgeDocRecord,
    *,
    kb_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    把 LLM 返回的任意结构清洗成**待落库**的话术条目数组（纯函数，便于单测）。

    清洗规则：
      - 结构化解析失败（判据走唯一真源 `is_llm_parse_failed`）⇒ 视为无结果（不猜）
      - 兼容 LLM 直接返回数组，或包一层 `{"faqs"/"items"/"data"/"result"/"list": [...]}`
      - **缺 question 或 answer 的条目直接丢弃**，不补空壳
      - `kb_id` 一律取文档的 kb_id（LLM 无权改归属）
      - ★ `status` **恒为 draft**（理由见模块 docstring ①）——
        即便 LLM 自作主张返回 `status: "active"`，这里也覆盖掉。
    """
    if isinstance(data, dict):
        # ★ 判定走唯一真源：不能写成 `"raw_text" in data` —— 那会把「LLM 合法
        #   返回了一个含 raw_text 字段的 JSON」误判成解析失败（假阴）。
        if is_llm_parse_failed(data):
            return []
        picked = None
        for key in ("faqs", "items", "data", "result", "list", "rules"):
            if isinstance(data.get(key), list):
                picked = data[key]
                break
        data = picked if picked is not None else []
    if not isinstance(data, list):
        return []

    kb = kb_id if kb_id is not None else (doc.kb_id or "")
    out: List[Dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question or not answer:
            continue
        keywords = [
            str(t).strip() for t in (raw.get("keywords") or [])
            if isinstance(t, (str, int, float)) and str(t).strip()
        ]
        out.append({
            "kb_id": kb,
            "question": question[:300],
            "answer": answer,
            "category": normalize_category(raw.get("category")),
            "keywords": keywords[:6],
            "priority": normalize_priority(raw.get("priority")),
            # ★ 写死草稿：拆出来的话术**未经人工确认不进检索**。
            #   LLM 返回值里的 status 一律不采纳。
            "status": "draft",
        })
        if len(out) >= MAX_FAQS:
            break
    return out


async def split_faqs_from_doc(doc: KnowledgeDocRecord) -> dict:
    """
    从文档正文提取话术条目（**只提取，不落库**；落库由 router → service 负责）。

    Returns:
        {
          "extracted": int,   # 提取条数
          "faqs": list,       # 待落库条目（status 恒为 draft）
          "degraded": bool,   # True = LLM 不可用/无正文/提取失败
          "reason": str,      # degraded 时的中文原因（直接给用户看）
        }
    """
    content = (doc.content or "").strip()
    if not content:
        return {
            "extracted": 0, "faqs": [], "degraded": True,
            "reason": "该文档没有正文内容，无法提取话术（上传时未提供正文）",
        }

    if not LLM_AVAILABLE:
        return {
            "extracted": 0, "faqs": [], "degraded": True,
            "reason": "AI 服务不可用，无法拆分文档",
        }

    try:
        llm = get_llm()
        data = await llm.structured_chat(
            user_message=_build_user_prompt(doc, content),
            system_prompt=SPLIT_FAQ_SYSTEM_PROMPT,
            output_format="json",
            # 提取类任务要稳定：同一篇文档两次提取应得到同一批条目
            temperature=0.2,
            max_tokens=3000,
        )
    except Exception as e:
        logger.warning(f"[knowledge_base] ai-split-faq LLM 调用失败: {e}")
        return {
            "extracted": 0, "faqs": [], "degraded": True,
            "reason": "AI 服务调用失败，请稍后重试",
        }

    faqs = normalize_llm_faqs(data, doc)
    if not faqs:
        return {
            "extracted": 0, "faqs": [], "degraded": True,
            "reason": "AI 未能从该文档中提取出可用于入库的话术，请检查文档内容",
        }
    return {"extracted": len(faqs), "faqs": faqs, "degraded": False, "reason": ""}
