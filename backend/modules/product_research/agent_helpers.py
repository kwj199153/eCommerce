# -*- coding: utf-8 -*-
"""选品 Agent 的**领域纯逻辑层**（P0-6 第一刀：从 `agent_product_research.py` 外移）。

## 这一层是什么

11 个**不碰实例状态**的函数，加上它们消费的 2 个常量。入选判据是**形态**，不是口味：

    · 不引用 `self`（不是实例方法）
    · 不读数据库 / 不发网络请求 / 不 import Agent、adapter、router
    · 输入 → 输出，无副作用（两个 classmethod 只经由 `cls` 读本类常量）

## 为什么值得单独成层

它们在原文件里以 `@staticmethod` 挂在 `ProductResearchAgent` 上，于是
「类目映射表」「机会评分公式」「ASIN 正则与解析」这些**业务规则**，
只能通过「先造一个 Agent 实例」来测。外移后可被直接 import 单测
（见 `tests/test_product_research_helper_purity.py`），同时把约 216 行
从 2646 行的 God Class 里摘了出来。

## 归位约束（门禁会钉住）

`tests/test_product_research_helper_purity.py` 断言本模块：
  · 函数体里不出现 `self`；
  · 不 import `modules.product_research.agent_product_research`（不许反向回流）；
  · 不 import 数据库 / HTTP 客户端 / adapter（保持叶子节点）。
这样「纯逻辑层」不会随时间重新长回状态依赖。

## 与主文件的关系

`agent_product_research.py` 让 `ProductResearchAgent` 继承 `ResearchHelpersMixin`
—— 于是 `self._extract_asin(...)` / `cls._extract_ordinal(...)` 等**全部调用点零改动**；
并在主文件顶部 re-export `_TRENDING_KEYWORDS` / `_ASIN_RE`，
因为 `tests/test_product_research_blue_ocean.py` 与
`tests/test_product_research_intent_routing.py` 按**原模块路径**导入它们。
"""
from typing import List, Optional

from platforms.base import KeywordData


# ====== 常量（原住 agent_product_research.py:248-267）======

# 全类目高潜关键词——老板没指定类目时用它，替代原先的 "general" 泛化词表。
#
# 为什么不用泛化词（smart home / organizer / portable…）：这些词在关键词库里
# **命中不到**，会走 `AmazonAdapter.get_keyword_data` 的「未匹配 → 随机估算」
# 分支（search_volume 随机 5k~80k、competition 随机 0.2~0.85、trend 随机），
# 于是机会分数完全随机、「发现 6 个蓝海机会」这个结论不可信。
#
# 下面这批词取自 `platforms/amazon/client.py` 的 MOCK_KEYWORDS（有真实量级的
# 搜索量/竞争度/趋势），跨 kitchen / pet / office / garden / sports 五个类目。
_TRENDING_KEYWORDS = [
    "coffee grinder", "portable coffee maker", "pet feeder automatic",
    "desk organizer mesh", "led grow lights indoor", "yoga mat non slip",
    "cat food dispenser", "exercise mat alignment lines",
]

# ASIN 正则：真实 ASIN 是 `B0` + 8 位字母数字（如 B0C1234567、B01N4ABCD1），
# 共 10 位。**不是 `[Bb]\d{9}`**——那个要求 B 后 9 位纯数字，会把
# `B0C1234567`（第 3 位是字母 C）全部漏掉，导致「对比 B0C… B0C…」
# 被判成「未提供 ASIN」。
_ASIN_RE = r"[Bb]0[0-9A-Za-z]{8}"


class ResearchHelpersMixin:
    """纯函数层：主 Agent 继承它即获得全部解析 / 评分 / 文案能力。

    ★ 本类**刻意不是** `BaseAgent`：它不该有生命周期、不该有连接、不该有状态。
      一旦某个方法开始需要 `self.xxx`，那就是它该搬回主类的信号 ——
      `tests/test_product_research_helper_purity.py` 会把这件事打红。
    """

    # 中文数字（用于解析「第一个 / 第 2 个」这类序数指代）
    _CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    # ---------- 类目 / 关键词 ----------

    @staticmethod
    def _extract_category(query: str) -> Optional[str]:
        """从查询中提取类目"""
        categories = {
            "厨房": "kitchen", "家居": "home", "电子": "electronics",
            "户外": "outdoor", "运动": "sports", "宠物": "pet",
            "美妆": "beauty", "办公": "office", "母婴": "baby",
            "服装": "clothing", "玩具": "toys", "园艺": "garden",
        }
        for cn, en in categories.items():
            if cn in query or en in query.lower():
                return en
        return None

    @staticmethod
    def _generate_search_keywords(category: Optional[str]) -> List[str]:
        """
        生成搜索关键词列表

        Args:
            category: 平台英文类目标识；None / 未收录的类目 → 全类目高潜关键词

        Returns:
            关键词列表
        """
        keyword_templates = {
            "kitchen": ["coffee grinder", "portable blender", "air fryer accessories"],
            "home": ["desk organizer", "storage bins", "led strip lights"],
            "electronics": ["wireless charger", "bluetooth speaker", "usb hub"],
            "outdoor": ["camping gear", "solar lights", "garden tools"],
            "sports": ["yoga mat", "resistance bands", "water bottle"],
            "pet": ["automatic feeder", "cat tree", "dog harness"],
        }
        base = keyword_templates.get(category) if category else None
        if not base:
            # 未识别出具体类目（或类目未收录）→ 全类目高潜关键词，
            # 而不是原先的 general 泛化词表（那会走随机估算，分数不可信）
            return list(_TRENDING_KEYWORDS)
        # 添加修饰词（base 已以该修饰词开头时跳过，否则会拼出 "portable portable blender"）
        modifiers = ["portable", "smart", "mini", "professional", "premium"]
        expanded = [
            f"{m} {b}" for m in modifiers[:2] for b in base[:2] if not b.startswith(m)
        ]
        return base + expanded

    # ---------- 机会评分 / 文案 ----------

    @staticmethod
    def _calculate_opportunity_score(keyword_data: KeywordData) -> float:
        """
        计算机会评分（0-100）

        公式：
        score = (search_volume_factor * 40) +
               (low_competition_factor * 35) +
               (trend_factor * 25)
        """
        # 搜索量因子（对数缩放）
        import math
        if keyword_data.search_volume > 0:
            sv_normalized = min(math.log10(keyword_data.search_volume + 1) / 5, 1)
        else:
            sv_normalized = 0
        sv_score = sv_normalized * 40

        # 低竞争因子（竞争越低越好）
        comp_score = (1 - keyword_data.competition) * 35

        # 趋势因子
        trend_scores = {"rising": 25, "stable": 15, "declining": 0}
        trend_score = trend_scores.get(keyword_data.trend_direction, 15)

        return round(sv_score + comp_score + trend_score, 1)

    @staticmethod
    def _generate_reason(keyword_data: KeywordData) -> str:
        """生成推荐理由"""
        reasons = []

        if keyword_data.trend_direction == "rising":
            reasons.append(f"搜索量呈上升趋势 (+{keyword_data.search_volume:,}/月)")

        if keyword_data.competition < 0.5:
            reasons.append(f"竞争度较低 ({keyword_data.competition:.0%})")

        if keyword_data.search_volume > 20000:
            reasons.append("市场需求充足")

        if keyword_data.suggested_bid and keyword_data.suggested_bid < 1.5:
            reasons.append(f"广告成本低 (${keyword_data.suggested_bid:.2f})")

        return "；".join(reasons) if reasons else "综合指标表现良好"

    @staticmethod
    def _estimate_price_range(category: str) -> str:
        """估算建议售价区间"""
        ranges = {
            "kitchen": "$15-$45", "home": "$12-$35", "electronics": "$20-$80",
            "outdoor": "$18-$55", "sports": "$15-$40", "pet": "$20-$60",
        }
        return ranges.get(category, "$15-$50")

    @staticmethod
    def _estimate_margin(competition: float) -> str:
        """估算利润率"""
        if competition < 0.4:
            return "35%-50%"
        elif competition < 0.7:
            return "25%-35%"
        else:
            return "15%-25%"

    @staticmethod
    def _generate_improvement_suggestions(pain_points: List[dict]) -> List[str]:
        """基于痛点生成改进建议"""
        suggestions = []
        pain_mapping = {
            "电池续航不足": "开发长续航版本或支持快充",
            "连接不稳定": "优化蓝牙/WiFi模块，强调稳定连接",
            "质量问题": "提升材质和工艺，增加质保期",
            "APP问题": "重构 APP，简化操作流程",
            "缺少功能": "调研用户需求，补充核心功能",
            "使用困难": "优化产品设计，提供详细教程",
            "速度慢": "升级硬件配置，提升性能",
            "性价比低": "优化供应链降低成本，或提升附加值",
        }

        seen = set()
        for pp in pain_points[:5]:
            pain = pp["pain_point"]
            if pain in pain_mapping and pain not in seen:
                suggestions.append(pain_mapping[pain])
                seen.add(pain)

        return suggestions[:4]  # 最多返回4条建议

    # ---------- 商品 / ASIN 解析 ----------

    @staticmethod
    def _extract_product_info(query: str) -> dict:
        """从查询中提取产品信息"""
        info = {}

        # 尝试提取价格（`$29.99` / `售价 29.99` / `价格 29.99` 都认）
        import re
        prices = re.findall(r'(?:\$|售价|价格|定价)\s*(\d+(?:\.\d+)?)', query)
        if prices:
            info["price"] = float(prices[0])

        # 尝试提取 ASIN
        asin_match = re.search(_ASIN_RE, query)
        if asin_match:
            info["asin"] = asin_match.group().upper()
        else:
            # 尝试提取产品名称（简化处理）
            info["name"] = query.replace("分析", "").replace("利润", "").strip()[:50]

        return info

    @staticmethod
    def _extract_asin(query: str) -> Optional[str]:
        """提取单个 ASIN"""
        import re
        match = re.search(_ASIN_RE, query)
        return match.group().upper() if match else None

    @staticmethod
    def _extract_multiple_asins(query: str) -> List[str]:
        """提取多个 ASIN（**去重**，保持首次出现顺序）。

        ★ 去重不是性能优化，是**语义修正**：「多个 ASIN」指的是多个**不同**的商品。
          Amazon 商品链接里同一个 ASIN 常出现 3 次（`/dp/<ASIN>`、`pd_rd_i=<ASIN>`、
          `ref_=..._<ASIN>`），不去重则「把这个链接加进选品库」会被判成
          「给了 3 个 ASIN 要对比」（`>=2 => competitor`，实测确定性复现）。
        ★ 收口在**唯一真源**这里：4 个消费点（意图判定 / 竞品对比 / 待补槽位 /
          入库目标解析）同时受益 —— 只修 `_classify_intent` 会让其余三处继续按
          重复计数，属于「同一判定两份实现」。
        """
        import re
        out: List[str] = []
        for a in re.findall(_ASIN_RE, query):
            up = a.upper()
            if up not in out:
                out.append(up)
        return out

    @classmethod
    def _extract_ordinal(cls, query: str) -> Optional[int]:
        """
        从查询里抽「第几个」，返回 **0-based** 下标；没写返回 None。

        支持「第 1 个 / 第2个 / 第一个 / 第一款 / top1」等说法，
        供「把第 N 个加进选品库」定位目标商品。
        """
        import re

        m = re.search(r"第\s*([0-9]+|[一二两三四五六七八九十])\s*(?:个|款|条|名|项)?", query)
        if m:
            raw = m.group(1)
            n = int(raw) if raw.isdigit() else cls._CN_NUM.get(raw)
            if n and n >= 1:
                return n - 1

        m2 = re.search(r"top\s*([0-9]+)", query, re.IGNORECASE)
        if m2:
            n = int(m2.group(1))
            if n >= 1:
                return n - 1

        return None
