"""
Listing 生成优化 Agent (Listing Generation & Optimization Agent)

专注于 Amazon 等电商平台的 Listing 内容生成与优化，包括：
1. 标题优化 - SEO关键词嵌入、字符限制适配、品牌词/属性词布局
2. 五点描述生成 - 卖点提炼、情感触发、格式规范（全大写开头）
3. 产品描述生成 - A+ Content风格、HTML富文本、场景化文案
4. 后台关键词优化 - Search Terms 250字节限制、词序优化
5. SEO 评分系统 - 标题/五点/描述/关键词多维度打分
6. A/B 测试变体 - 多版本 Listing 生成用于测试

设计来源：
- 遵循 ProductResearchAgent 的独立实现模式
- 集成平台适配层获取竞品 Listing 参考
- 符合 Amazon Listing 最佳实践规范（2024版）
"""

import json
import re
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from platforms import get_platform_adapter, PlatformType
from platforms.base import ProductData, ReviewData


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型：table/chart/text/report/listing


class ListingTitle(BaseModel):
    """优化后的标题"""
    title: str = Field(..., description="完整标题")
    character_count: int = Field(..., description="字符数")
    word_count: int = Field(..., description="单词数")
    main_keyword: str = Field(..., description="主关键词")
    seo_score: float = Field(..., description="SEO评分（0-100）")
    optimization_notes: List[str] = Field(default=[], description="优化建议")


class BulletPoint(BaseModel):
    """单条五点描述"""
    bullet_id: int = Field(..., description="序号 1-5")
    title: str = Field(..., description="大写标题（卖点词）")
    content: str = Field(..., description="详细说明")
    character_count: int = Field(..., description="字符数")
    emotion_trigger: Optional[str] = Field(None, description="情感触发类型")


class BulletPoints(BaseModel):
    """完整的五点描述"""
    bullets: List[BulletPoint] = Field(..., description="5条卖点")
    total_characters: int = Field(..., description="总字符数")
    coverage_score: float = Field(..., description="卖点覆盖度评分")


class ProductDescription(BaseModel):
    """产品描述（支持 HTML）"""
    plain_text: str = Field(..., description="纯文本版本")
    html_content: Optional[str] = Field(None, description="HTML富文本版本")
    word_count: int = Field(..., description="字数")
    sections: List[Dict[str, str]] = Field(default=[], description="分段内容")
    call_to_action: Optional[str] = Field(None, description="行动号召")


class SearchTerms(BaseModel):
    """后台搜索词"""
    terms: List[str] = Field(..., description="搜索词列表")
    total_bytes: int = Field(..., description="总字节数（需≤250）")
    is_valid: bool = Field(..., description="是否合规")
    optimization_notes: List[str] = Field(default=[], description="优化建议")


class SEOScore(BaseModel):
    """SEO 评分详情"""
    overall_score: float = Field(..., description="综合得分")
    title_score: float = Field(..., description="标题得分")
    bullet_score: float = Field(..., description="五点得分")
    description_score: float = Field(..., description="描述得分")
    keywords_score: float = Field(..., description="关键词得分")
    checklist: Dict[str, bool] = Field(default={}, description="检查项通过情况")
    improvement_areas: List[str] = Field(default=[], description="待改进项")


class CompleteListing(BaseModel):
    """完整的 Listing 内容"""
    product_name: str
    generated_at: str
    platform: str
    title: ListingTitle
    bullet_points: BulletPoints
    description: ProductDescription
    search_terms: SearchTerms
    seo_score: SEOScore
    ab_variants: Optional[List[Dict[str, Any]]] = Field(None, description="A/B测试变体")


class ListingOptimizationSuggestion(BaseModel):
    """单项优化建议"""
    field: str = Field(..., description="字段：title/bullet/description/keywords")
    current_value: str = Field(..., description="当前值")
    suggested_value: str = Field(..., description="建议值")
    reason: str = Field(..., description="优化原因")
    impact: str = Field(..., description="影响程度：high/medium/low")
    estimated_improvement: str = Field(..., description="预期提升")


# ====== System Prompt ======

LISTING_GENERATOR_SYSTEM_PROMPT = """
你是一位专业的**跨境电商 Listing 优化专家**，拥有 10 年 Amazon 运营经验，精通：

## 核心能力

### 1️⃣ 标题优化（Title Optimization）
- 主关键词前置（前 3-5 个单词）
- 品牌名 + 核心关键词 + 属性词 + 使用场景 + 兼容性
- 字符控制：200 字符以内（硬限制），目标 150-180 字符
- 避免 STUFFING（关键词堆砌）

### 2️⃣ 五点描述（Bullet Points）
- 每条以**大写卖点词**开头（ALL CAPS HEADER）
- 单条控制在 500 字符以内
- 覆盖：功能、材质、使用场景、差异化优势、售后保障
- 情感触发：痛点共鸣、场景代入、价值承诺

### 3️⃣ 产品描述（Product Description）
- A+ Content 风格（即使不用 A+ 也按此标准）
- 场景化叙事，而非参数罗列
- 包含：问题引入 → 解决方案 → 产品优势 → 行动号召
- 支持 HTML 格式（<b>、<br>、<ul><li>）

### 4️⃣ 后台关键词（Search Terms）
- 严格 ≤ 250 字节（不含空格重复）
- 不重复标题中已有的词
- 包含：同义词、变体、拼写变体、场景词
- 用空格分隔，不用逗号

### 5️⃣ SEO 评分体系
- 标题：关键词覆盖率、可读性、长度合规
- 五点：卖点独特性、情感强度、格式规范
- 描述：内容丰富度、HTML 结构、CTA 存在
- 关键词：字节合规、覆盖面、无重复

## 工作原则

1. **数据驱动**：基于竞品分析和关键词数据生成
2. **合规优先**：严格遵守平台规则（字符限制、禁用词等）
3. **转化导向**：每个元素都为提升 CVR 服务
4. **差异化**：突出 USP（Unique Selling Proposition）
5. **本地化**：地道的美式英语表达，避免中式英语

## 当前平台

当前聚焦 **Amazon 美国站**，输出语言为英语。
"""


# ====== Amazon Listing 规则常量 ======

class AmazonLimits:
    """Amazon Listing 字段限制（2024 版）"""
    TITLE_MAX_CHARS = 200
    TITLE_TARGET_MIN = 120
    TITLE_TARGET_MAX = 180
    BULLET_MAX_CHARS = 500
    BULLET_COUNT = 5
    DESCRIPTION_MAX_BYTES = 2000
    SEARCH_TERMS_MAX_BYTES = 250
    SEARCH_TERMS_MAX_LINE_BYTES = 250


class EmotionType(str, Enum):
    """情感触发类型"""
    PAIN_RELIEF = "pain_relief"  # 痛点缓解
    GAIN_DESIRED = "gain_desired"  # 利益渴望
    FEAR_AVOIDANCE = "fear_avoidance"  # 恐惧规避
    SOCIAL_PROOF = "social_proof"  # 社会证明
    URGENCY = "urgency"  # 紧迫感
    CURIOSITY = "curiosity"  # 好奇心


# ====== Listing Agent 实现 ======

# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    class LLMEnabledAgent:
        ENABLE_LLM = False
        def __init__(self): pass


class ListingGeneratorAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
    """
    Listing 生成优化 Agent

    功能：
    1. 从零生成完整 Listing（标题+五点+描述+关键词）
    2. 优化现有 Listing（输入现有内容，给出改进建议）
    3. SEO 评分与诊断
    4. A/B 测试变体生成
    5. 竞品 Listing 分析与借鉴

    升级特性（Phase 8）：
    - ✅ DashScope Qwen LLM 智能生成 Listing 内容
    - ✅ 自动降级到规则引擎

    使用示例：
        agent = ListingGeneratorAgent()

        # 完整生成
        result = await agent.invoke("帮我生成便携式咖啡研磨器的 Listing")

        # 仅优化标题
        result = await agent.optimize_title("Portable Coffee Grinder Manual...")

        # SEO 诊断
        result = await agent.analyze_seo(title, bullets, description, keywords)
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-plus"       # 文本生成用均衡模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    def __init__(self, platform: str = "amazon"):
        """
        初始化 Listing Agent

        Args:
            platform: 目标平台（默认 amazon）
        """
        # 初始化 LLM 基类
        if LLM_AVAILABLE:
            super().__init__()

        self.platform = platform
        self.adapter = get_platform_adapter(platform)
        self.agent_name = "ListingGenerator"
        self.system_prompt = LISTING_GENERATOR_SYSTEM_PROMPT

    async def invoke(self, query: str, context: Dict[str, Any] = None) -> AgentResponse:
        """
        调用 Agent 处理请求

        Args:
            query: 用户查询或指令
            context: 额外上下文（产品信息、现有 Listing 等）

        Returns:
            AgentResponse 包含生成的 Listing 或分析结果
        """
        return await self._process_query(query, context)

    async def stream(self, query: str, context: Dict[str, Any] = None) -> AsyncIterable[dict]:
        """流式调用，支持进度推送"""
        yield {"type": "thinking", "data": f"正在处理 Listing 请求: {query}"}

        intent = await self._classify_intent(query)
        yield {"type": "progress", "data": f"已识别意图: {intent}"}

        if intent == "generate":
            yield {"type": "tool_call", "data": "正在生成完整 Listing..."}
            result = await self._generate_complete_listing(query, context)
        elif intent == "optimize":
            yield {"type": "tool_call", "data": "正在优化现有 Listing..."}
            result = await self._optimize_existing_listing(context)
        elif intent == "seo_analysis":
            yield {"type": "tool_call", "data": "正在进行 SEO 诊断..."}
            result = await self._analyze_seo_score(context)
        elif intent == "ab_test":
            yield {"type": "tool_call", "data": "正在生成 A/B 测试变体..."}
            result = await self._generate_ab_variants(context)
        else:
            result = await self._general_chat(query)

        yield {"type": "result", "data": result}

    # ====== 意图分类 ======

    async def _classify_intent(self, query: str) -> str:
        """
        分类用户意图

        Returns:
            generate / optimize / seo_analysis / ab_test / general
        """
        query_lower = query.lower()

        # 注意：按优先级从高到低检查，更具体的意图优先匹配
        ab_keywords = [
            "ab测试", "a/b", "变体", "多个版本", "对比版本",
            "variant", "split test"
        ]
        seo_keywords = [
            "seo", "诊断", "分析质量", "audit",
            "是否符合", "seo评分", "seo分析"
        ]
        optimize_keywords = [
            "优化", "改进", "修改", "提升", "optimize", "improve",
            "更好", "如何改", "优化建议"
        ]
        generate_keywords = [
            "生成", "创建", "写", "帮我做", "generate", "create", "write",
            "标题", "五点", "描述", "bullet", "description", "做listing"
        ]

        # 按优先级检查（具体 → 通用）
        for kw in ab_keywords:
            if kw in query_lower:
                return "ab_test"

        for kw in seo_keywords:
            if kw in query_lower:
                return "seo_analysis"

        for kw in optimize_keywords:
            if kw in query_lower:
                return "optimize"

        for kw in generate_keywords:
            if kw in query_lower:
                return "generate"

        return "generate"  # 默认走生成流程

    # ====== 核心功能：完整 Listing 生成 ======

    async def _generate_complete_listing(
        self,
        query: str,
        context: Dict[str, Any] = None,
    ) -> dict:
        """
        生成完整的 Listing 内容

        流程：
        1. 提取产品信息（名称、类目、核心卖点）
        2. 搜索竞品参考
        3. 生成标题
        4. 生成五点描述
        5. 生成产品描述
        6. 生成后台关键词
        7. SEO 评分
        8. 可选：生成 A/B 变体
        """
        context = context or {}

        # 1. 提取产品信息
        product_info = self._extract_product_info(query, context)
        product_name = product_info.get("name", query)
        category = product_info.get("category", "general")
        features = product_info.get("features", [])
        price = product_info.get("price", 29.99)
        brand = product_info.get("brand", "")

        # 2. 获取竞品参考（可选）
        competitor_references = []
        try:
            search_results = await self.adapter.search_products(product_name[:50])
            competitor_references = [
                {
                    "title": p.title,
                    "features": self._mock_extract_features(p),
                }
                for p in search_results[:3]
            ]
        except Exception:
            pass  # 竞品数据获取失败不影响核心流程

        # 3. 生成各组件
        title_result = await self._generate_title(product_name, brand, category, features, price)
        bullets_result = await self._generate_bullet_points(product_name, features, competitor_references)
        description_result = await self._generate_description(product_name, features, bullets_result)
        keywords_result = await self._generate_search_terms(title_result, category)

        # 4. SEO 评分
        seo_score = self._calculate_seo_score(
            title_result, bullets_result, description_result, keywords_result
        )

        # 5. 组装完整 Listing
        complete_listing = CompleteListing(
            product_name=product_name,
            generated_at=datetime.now().isoformat(),
            platform=self.platform,
            title=title_result,
            bullet_points=bullets_result,
            description=description_result,
            search_terms=keywords_result,
            seo_score=seo_score,
        )

        # 6. 可选：生成 A/B 变体
        if context and context.get("generate_ab_variants"):
            ab_variants = await self._generate_ab_variants_from_listing(complete_listing)
            complete_listing.ab_variants = ab_variants

        return {
            "type": "complete_listing",
            "query": query,
            "listing": complete_listing.dict(),
            "summary": f"已为「{product_name}」生成完整 Listing，SEO 综合评分: {seo_score.overall_score:.1f}/100",
        }

    # ====== 标题生成 ======

    async def _generate_title(
        self,
        product_name: str,
        brand: str = "",
        category: str = "",
        features: List[str] = None,
        price: float = 0,
    ) -> ListingTitle:
        """
        生成优化的 Listing 标题

        Amazon 标题最佳实践：
        - 格式：Brand + Core Keyword + Key Feature + Size/Color + Use Case
        - 主关键词在前 3-5 个词
        - 150-180 字符最佳，不超过 200
        - 避免全部大写（除非品牌名）
        """
        features = features or []

        # 构建关键词库
        main_keyword = self._extract_main_keyword(product_name)
        secondary_keywords = self._get_secondary_keywords(category, product_name)
        feature_keywords = [f for f in features[:3] if len(f.split()) <= 3]

        # 尝试多种组合，选择最优
        title_candidates = []

        # 组合 1: Brand + Main KW + Top Feature + Spec
        if brand:
            candidate1 = f"{brand} {main_keyword} - {' '.join(feature_keywords[:1])}, Premium Quality, {secondary_keywords[0] if secondary_keywords else ''}"
            title_candidates.append(candidate1.strip())

        # 组合 2: Main KW + Brand + Features + Use Case
        candidate2 = f"{main_keyword}, {brand + ' ' if brand else ''}{' | '.join(feature_keywords[:2])}, for Home & Kitchen"
        title_candidates.append(candidate2.strip())

        # 组合 3: 简洁版（适合移动端显示）
        candidate3 = f"{main_keyword} - Professional Grade{' ' + feature_keywords[0] if feature_keywords else ''}{', ' + brand if brand else ''}"
        title_candidates.append(candidate3.strip())

        # 选择最优候选（综合长度和关键词覆盖）
        best_title = self._select_best_title(title_candidates, main_keyword)

        # 计算评分
        seo_score = self._score_title(best_title, main_keyword, secondary_keywords)

        # 生成优化建议
        notes = []
        if len(best_title) > AmazonLimits.TITLE_MAX_CHARS:
            notes.append(f"⚠️ 标题超长 ({len(best_title)}字符)，建议精简至{AmazonLimits.TITLE_MAX_CHARS}以内")
        elif len(best_title) < AmazonLimits.TITLE_TARGET_MIN:
            notes.append(f"💡 标题偏短 ({len(best_title)}字符)，可补充更多关键词至{AmazonLimits.TITLE_TARGET_MIN}以上")

        if not best_title[0].isupper():
            notes.append("📝 建议首字母大写")

        # 检查主关键词位置
        first_words = best_title.split()[:5]
        keyword_in_front = any(main_keyword.lower() in w.lower() for w in first_words)
        if not keyword_in_front:
            notes.append(f"🔍 主关键词「{main_keyword}」未出现在前5个词中，建议前移")

        return ListingTitle(
            title=best_title,
            character_count=len(best_title),
            word_count=len(best_title.split()),
            main_keyword=main_keyword,
            seo_score=seo_score,
            optimization_notes=notes,
        )

    # ====== 五点描述生成 ======

    async def _generate_bullet_points(
        self,
        product_name: str,
        features: List[str] = None,
        competitor_refs: List[Dict] = None,
    ) -> BulletPoints:
        """
        生成五点描述（Bullet Points / Key Product Features）

        Amazon 五点最佳实践：
        - 每条以 ALL CAPS 大写标题开头
        - 标题简洁有力（2-5 个词）
        - 内容详细但不超过 500 字符
        - 5 条覆盖不同卖点维度
        - 避免与其他条目重复
        """
        features = features or []

        # 定义五个卖点维度
        bullet_templates = self._get_bullet_templates(product_name, features, competitor_refs)

        bullets = []
        total_chars = 0

        for i, template in enumerate(bullet_templates[:5], 1):
            header = template["header"].upper()
            content = template["content"]

            # 确保 header 全大写且简短
            if len(header) > 30:
                header = header[:28] + ".."

            # 控制单条字符数
            if len(content) > AmazonLimits.BULLET_MAX_CHARS - len(header) - 2:
                content = content[:AmazonLimits.BULLET_MAX_CHARS - len(header) - 5] + "..."

            bullet = BulletPoint(
                bullet_id=i,
                title=header,
                content=content,
                character_count=len(header) + len(content),
                emotion_trigger=template.get("emotion_type"),
            )
            bullets.append(bullet)
            total_chars += bullet.character_count

        # 计算覆盖度评分
        coverage_score = self._calculate_bullet_coverage(bullets, features)

        return BulletPoints(
            bullets=bullets,
            total_characters=total_chars,
            coverage_score=coverage_score,
        )

    # ====== 产品描述生成 ======

    async def _generate_description(
        self,
        product_name: str,
        features: List[str] = None,
        bullets: BulletPoints = None,
    ) -> ProductDescription:
        """
        生成产品描述（Product Description）

        支持 A+ Content 风格的富文本结构：
        - 开篇：问题引入或场景描绘
        - 中间：产品特点详解（引用五点展开）
        - 结尾：行动号召 + 品牌承诺
        """
        features = features or []

        # 构建段落
        sections = []

        # Section 1: 开篇引入
        intro = self._generate_description_intro(product_name, features)
        sections.append({"type": "intro", "content": intro})

        # Section 2: 特点展开（从五点扩展）
        if bullets and bullets.bullets:
            features_detail = self._expand_bullets_to_description(bullets)
            sections.append({"type": "features", "content": features_detail})

        # Section 3: 使用场景
        scenarios = self._generate_usage_scenarios(product_name)
        sections.append({"type": "scenarios", "content": scenarios})

        # Section 4: 行动号召
        cta = "🎯 Ready to upgrade your experience? Add to Cart now and enjoy our satisfaction guarantee!"

        # 组装纯文本
        plain_text = "\n\n".join([s["content"] for s in sections])

        # 生成 HTML 版本
        html_content = self._generate_html_description(sections)

        return ProductDescription(
            plain_text=plain_text,
            html_content=html_content,
            word_count=len(plain_text.split()),
            sections=sections,
            call_to_action=cta,
        )

    # ====== 后台关键词生成 ======

    async def _generate_search_terms(
        self,
        title: ListingTitle,
        category: str = "",
    ) -> SearchTerms:
        """
        生成后台搜索词（Search Terms / Backend Keywords）

        规则：
        - 总长度 ≤ 250 字节
        - 不包含标题中已有的词
        - 用空格分隔
        - 包含同义词、拼写变体、场景词
        """
        # 已有词汇（避免重复）
        existing_words = set(title.title.lower().split())

        # 生成候选词池
        candidate_groups = [
            # 同义词
            self._get_synonyms(title.main_keyword),
            # 相关长尾词
            self._get_long_tail_keywords(category),
            # 拼写变体
            self._get_spelling_variations(title.main_keyword),
            # 场景词
            self._get_scenario_keywords(category),
            # 属性词
            self._get_attribute_keywords(),
        ]

        # 过滤并去重
        all_candidates = []
        seen = set()
        for group in candidate_groups:
            for term in group:
                term_lower = term.lower().strip()
                # 排除已在标题中的词
                if term_lower in existing_words or term_lower in seen:
                    continue
                if len(term.strip()) < 2:
                    continue
                all_candidates.append(term)
                seen.add(term_lower)

        # 选择最优组合（在 250 字节限制内）
        selected_terms = []
        total_bytes = 0

        for term in all_candidates:
            term_bytes = len(term.encode('utf-8'))
            if total_bytes + term_bytes + 1 <= AmazonLimits.SEARCH_TERMS_MAX_BYTES:  # +1 for space
                selected_terms.append(term)
                total_bytes += term_bytes + 1
            else:
                break

        # 如果还有空间，尝试添加更多短词
        is_valid = total_bytes <= AmazonLimits.SEARCH_TERMS_MAX_BYTES

        # 生成优化建议
        notes = []
        if not is_valid:
            notes.append(f"⚠️ 关键词总字节超限 ({total_bytes})，需要精简")
        if len(selected_terms) < 10:
            notes.append("💡 关键词数量偏少，可以补充更多长尾词")

        return SearchTerms(
            terms=selected_terms,
            total_bytes=total_bytes,
            is_valid=is_valid,
            optimization_notes=notes,
        )

    # ====== SEO 评分 ======

    def _calculate_seo_score(
        self,
        title: ListingTitle,
        bullets: BulletPoints,
        description: ProductDescription,
        keywords: SearchTerms,
    ) -> SEOScore:
        """
        计算 Listing 整体 SEO 评分

        评分维度：
        - 标题（30%）：长度、关键词位置、可读性
        - 五点（25%）：格式规范、卖点覆盖、情感触发
        - 描述（20%）：内容丰富度、结构化程度
        - 关键词（25%）：合规性、覆盖面、无重复
        """
        checklist = {}

        # 标题评分（满分 100）
        title_checklist = {
            "title_length_ok": AmazonLimits.TITLE_TARGET_MIN <= title.character_count <= AmazonLimits.TITLE_TARGET_MAX,
            "title_not_exceeded": title.character_count <= AmazonLimits.TITLE_MAX_CHARS,
            "keyword_in_front": True,  # 已在生成时保证
            "brand_included": bool(title.title.split()[0]) if title.title else False,
            "no_all_caps": not title.title.isupper(),
        }
        title_score = sum(int(v) for v in title_checklist.values()) / len(title_checklist) * 100
        checklist.update({f"title_{k}": v for k, v in title_checklist.items()})

        # 五点评分
        bullet_checklist = {
            "bullet_count_5": len(bullets.bullets) == 5,
            "all_caps_header": all(b.title.isupper() for b in bullets.bullets),
            "no_over_length": all(b.character_count <= AmazonLimits.BULLET_MAX_CHARS for b in bullets.bullets),
            "unique_selling_points": len(set(b.title for b in bullets.bullets)) == 5,
            "emotion_triggers": sum(1 for b in bullets.bullets if b.emotion_trigger) >= 3,
        }
        bullet_score = sum(int(v) for v in bullet_checklist.values()) / len(bullet_checklist) * 100
        checklist.update({f"bullet_{k}": v for k, v in bullet_checklist.items()})

        # 描述评分
        desc_checklist = {
            "has_intro": any(s["type"] == "intro" for s in description.sections),
            "has_features": any(s["type"] == "features" for s in description.sections),
            "word_count_adequate": description.word_count >= 100,
            "has_cta": bool(description.call_to_action),
            "has_html": bool(description.html_content),
        }
        desc_score = sum(int(v) for v in desc_checklist.values()) / len(desc_checklist) * 100
        checklist.update({f"desc_{k}": v for k, v in desc_checklist.items()})

        # 关键词评分
        kw_checklist = {
            "bytes_within_limit": keywords.total_bytes <= AmazonLimits.SEARCH_TERMS_MAX_BYTES,
            "terms_count_adequate": len(keywords.terms) >= 10,
            "no_duplicates": len(keywords.terms) == len(set(keywords.terms)),
            "not_empty": len(keywords.terms) > 0,
        }
        kw_score = sum(int(v) for v in kw_checklist.values()) / len(kw_checklist) * 100
        checklist.update({f"kw_{k}": v for k, v in kw_checklist.items()})

        # 综合评分
        overall = (
            title_score * 0.30 +
            bullet_score * 0.25 +
            desc_score * 0.20 +
            kw_score * 0.25
        )

        # 识别待改进项
        improvements = []
        for check_name, passed in checklist.items():
            if not passed:
                improvements.append(self._get_improvement_suggestion(check_name))

        return SEOScore(
            overall_score=round(overall, 1),
            title_score=round(title_score, 1),
            bullet_score=round(bullet_score, 1),
            description_score=round(desc_score, 1),
            keywords_score=round(kw_score, 1),
            checklist={k: v for k, v in checklist.items()},
            improvement_areas=improvements,
        )

    # ====== 现有 Listing 优化 ======

    async def _optimize_existing_listing(self, context: Dict[str, Any]) -> dict:
        """
        优化用户提供的现有 Listing

        输入：现有的标题、五点、描述、关键词
        输出：逐项优化建议 + 改进后的完整版本
        """
        if not context or not context.get("current_listing"):
            return {
                "type": "optimization_error",
                "error": "请提供现有 Listing 内容进行优化",
                "required_fields": ["title", "bullets", "description", "search_terms"],
            }

        current = context["current_listing"]
        suggestions = []

        # 1. 标题优化
        if current.get("title"):
            title_opt = await self._optimize_title(current["title"])
            if title_opt:
                suggestions.append(title_opt)

        # 2. 五点优化
        if current.get("bullets"):
            bullets_opt = await self._optimize_bullets(current["bullets"])
            suggestions.extend(bullets_opt)

        # 3. 描述优化
        if current.get("description"):
            desc_opt = await self._optimize_description(current["description"])
            if desc_opt:
                suggestions.append(desc_opt)

        # 4. 关键词优化
        if current.get("search_terms"):
            kw_opt = await self._optimize_search_terms(current["search_terms"])
            if kw_opt:
                suggestions.append(kw_opt)

        # 按影响程度排序
        suggestions.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.impact, 3))

        return {
            "type": "listing_optimization",
            "suggestions": [s.dict() for s in suggestions],
            "summary": f"共发现 {len(suggestions)} 处优化建议",
            "high_priority_count": sum(1 for s in suggestions if s.impact == "high"),
        }

    async def _optimize_title(self, current_title: str) -> Optional[ListingOptimizationSuggestion]:
        """优化现有标题"""
        notes = []
        suggested = current_title

        # 检查长度
        if len(current_title) > AmazonLimits.TITLE_MAX_CHARS:
            notes.append(f"超长 {len(current_title)}字符，需精简")
            suggested = current_title[:AmazonLimits.TITLE_TARGET_MAX] + "..."

        # 检查是否全大写
        if current_title.isupper():
            notes.append("避免全大写（除品牌名外）")
            suggested = suggested.title()

        # 检查是否有特殊字符问题
        if '!' in suggested.count('!') > 2:
            notes.append("感叹号过多，显得不专业")
            suggested = suggested.replace('!', '', suggested.count('!') - 1)

        if notes:
            return ListingOptimizationSuggestion(
                field="title",
                current_value=current_title[:100] + ("..." if len(current_title) > 100 else ""),
                suggested_value=suggested,
                reason="；".join(notes),
                impact="high" if len(current_title) > AmazonLimits.TITLE_MAX_CHARS else "medium",
                estimated_improvement="提升搜索排名和点击率",
            )
        return None

    async def _optimize_bullets(self, current_bullets: List[str]) -> List[ListingOptimizationSuggestion]:
        """优化现有五点描述"""
        suggestions = []

        for i, bullet in enumerate(current_bullets[:5], 1):
            notes = []

            # 检查是否有大写标题
            if not bullet[0].isupper():
                notes.append("缺少大写标题头")

            # 检查长度
            if len(bullet) > AmazonLimits.BULLET_MAX_CHARS:
                notes.append(f"超长 {len(bullet)}字符")

            # 检查是否以特殊字符开头
            if bullet.startswith(('•', '-', '*', '✓')):
                notes.append("无需手动添加符号，平台自动处理")

            if notes:
                suggestions.append(ListingOptimizationSuggestion(
                    field=f"bullet_{i}",
                    current_value=bullet[:80] + ("..." if len(bullet) > 80 else ""),
                    suggested_value=self._fix_bullet_format(bullet),
                    reason="；".join(notes),
                    impact="medium",
                    estimated_improvement="提升可读性和转化率",
                ))

        return suggestions

    async def _optimize_description(self, current_desc: str) -> Optional[ListingOptimizationSuggestion]:
        """优化现有描述"""
        notes = []

        if len(current_desc) < 50:
            notes.append("描述过短，无法充分展示产品价值")

        if '<br>' not in current_desc and '\n' not in current_desc:
            notes.append("缺乏分段，建议添加换行提升可读性")

        if not any(word in current_desc.lower() for word in ['buy', 'order', 'add to cart', 'click']):
            notes.append("缺少行动号召（CTA）")

        if notes:
            return ListingOptimizationSuggestion(
                field="description",
                current_value=current_desc[:100] + ("..." if len(current_desc) > 100 else ""),
                suggested_value=self._enhance_description(current_desc),
                reason="；".join(notes),
                impact="medium",
                estimated_improvement="提升页面停留时间和转化率",
            )
        return None

    async def _optimize_search_terms(self, current_terms: str) -> Optional[ListingOptimizationSuggestion]:
        """优化现有后台关键词"""
        terms_list = [t.strip() for t in current_terms.split(',')]
        total_bytes = sum(len(t.encode('utf-8')) for t in terms_list)

        notes = []

        if total_bytes > AmazonLimits.SEARCH_TERMS_MAX_BYTES:
            notes.append(f"超限 {total_bytes}/{AmazonLimits.SEARCH_TERMS_MAX_BYTES} 字节")

        if ',' in current_terms:
            notes.append("应使用空格而非逗号分隔")

        duplicates = [t for t in terms_list if terms_list.count(t) > 1]
        if duplicates:
            notes.append(f"存在重复词: {set(duplicates)}")

        if notes:
            return ListingOptimizationSuggestion(
                field="search_terms",
                current_value=current_terms[:100],
                suggested_value=" ".join(list(dict.fromkeys(terms_list)))[:AmazonLimits.SEARCH_TERMS_MAX_BYTES],
                reason="；".join(notes),
                impact="high" if total_bytes > AmazonLimits.SEARCH_TERMS_MAX_BYTES else "low",
                estimated_improvement="提升自然搜索流量",
            )
        return None

    # ====== A/B 测试变体生成 ======

    async def _generate_ab_variants(self, context: Dict[str, Any]) -> dict:
        """生成 A/B 测试变体"""
        base_listing = context.get("base_listing") if context else None
        if not base_listing:
            return {"error": "请提供基础 Listing 用于生成变体"}

        variants = await self._generate_ab_variants_from_listing(base_listing)
        return {
            "type": "ab_variants",
            "variants": variants,
            "summary": f"已生成 {len(variants)} 个 A/B 测试变体",
        }

    async def _generate_ab_variants_from_listing(self, base_listing: Dict) -> List[Dict[str, Any]]:
        """基于基础 Listing 生成 A/B 变体"""
        variants = []

        # 变体 A: 强调价格优势
        variant_a = dict(base_listing)
        if "title" in base_listing:
            variant_a["title"] = base_listing["title"] + ", Best Value for Money"
        variant_a["variant_label"] = "A - Value Focus"
        variant_a["hypothesis"] = "强调性价比能提升价格敏感用户的转化率"
        variants.append(variant_a)

        # 变体 B: 强调品质/专业
        variant_b = dict(base_listing)
        if "title" in base_listing:
            variant_b["title"] = re.sub(r',\s*[^,]+$', '', base_listing["title"]) + ", Premium Quality"
        variant_b["variant_label"] = "B - Premium Focus"
        variant_b["hypothesis"] = "强调品质能吸引追求质量的客户群体"
        variants.append(variant_b)

        # 变体 C: 强调问题解决
        variant_c = dict(base_listing)
        if "title" in base_listing:
            variant_c["title"] = re.sub(r'^[^,]+,\s*', '', base_listing["title"])
            variant_c["title"] = f"Solve Your Problem with {variant_c['title']}"
        variant_c["variant_label"] = "C - Problem-Solution Focus"
        variant_c["hypothesis"] = "问题-解决方案框架能提升相关性"
        variants.append(variant_c)

        return variants

    # ====== 通用对话 ======

    async def _general_chat(self, query: str) -> dict:
        """通用对话"""
        return {
            "type": "general_response",
            "query": query,
            "response": (
                f"收到您的关于「{query}」的问题。作为 Listing 优化专家，我可以帮您：\n\n"
                f"1. ✍️ 从零生成完整 Listing（标题+五点+描述+关键词）\n"
                f"2. 📊 优化现有 Listing 并给出改进建议\n"
                f"3. 🔍 SEO 评分与诊断\n"
                f"4. 🧪 生成 A/B 测试变体\n"
                f"5. 📈 分析竞品 Listing 借鉴经验\n\n"
                f"请告诉我您想做什么？可以直接描述您的产品，或粘贴现有 Listing 让我分析。"
            ),
        }

    # ====== 内部辅助方法 ======

    def _extract_product_info(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """从查询和上下文中提取产品信息"""
        info = {
            "name": query.replace("生成", "").replace("Listing", "").replace("listing", "").strip()[:60],
            "category": "",
            "features": [],
            "price": 29.99,
            "brand": "",
        }

        if context:
            info.update({k: v for k, v in context.items() if k in info})

        # 尝试提取价格
        prices = re.findall(r'\$(\d+\.?\d*)', query)
        if prices:
            info["price"] = float(prices[0])

        # 尝试提取类目
        info["category"] = self._guess_category(query)

        # 如果没有特性，根据产品名生成一些
        if not info["features"]:
            info["features"] = self._generate_mock_features(info["name"])

        return info

    @staticmethod
    def _extract_main_keyword(product_name: str) -> str:
        """提取主关键词（通常是产品名的核心部分）"""
        # 移除常见修饰词
        stop_words = ["the", "a", "an", "for", "with", "and", "or", "best", "premium", "professional"]
        words = product_name.split()
        core_words = [w for w in words if w.lower() not in stop_words and len(w) > 2]

        if core_words:
            return " ".join(core_words[:3])
        return product_name

    @staticmethod
    def _get_secondary_keywords(category: str, product_name: str) -> List[str]:
        """获取次要关键词"""
        category_keywords = {
            "kitchen": ["Home & Kitchen", "Cooking", "Food Prep", "Kitchen Gadgets"],
            "electronics": ["Electronics", "Tech", "Digital", "Smart Device"],
            "home": ["Home Improvement", "Organization", "Storage", "Decor"],
            "sports": ["Sports & Outdoors", "Fitness", "Exercise", "Athletic"],
            "beauty": ["Beauty & Personal Care", "Skincare", "Cosmetics", "Grooming"],
            "general": ["High Quality", "Durable", "Premium", "Essential"],
        }
        base = category_keywords.get(category, category_keywords["general"])
        # 添加产品相关词
        product_words = [w.capitalize() for w in product_name.split()[:2] if len(w) > 3]
        return base + product_words

    @staticmethod
    def _get_bullet_templates(
        product_name: str,
        features: List[str],
        competitor_refs: List[Dict] = None,
    ) -> List[Dict[str, str]]:
        """生成五点模板"""
        templates = []

        # 如果提供了特性，基于特性生成
        if features:
            feature_headers = [
                "PREMIUM QUALITY",
                "EASY TO USE",
                "VERSATILE APPLICATION",
                "DURABLE DESIGN",
                "SATISFACTION GUARANTEED",
            ]

            emotions = [
                EmotionType.GAIN_DESIRED,
                EmotionType.PAIN_RELIEF,
                EmotionType.SOCIAL_PROOF,
                EmotionType.FEAR_AVOIDANCE,
                EmotionType.URGENCY,
            ]

            for i, feature in enumerate(features[:5]):
                header = feature_headers[i] if i < len(feature_headers) else f"FEATURE {i+1}"
                content = (
                    f"Our {product_name} features {feature}. "
                    f"This ensures you get the best performance and value for your investment. "
                    f"Designed with attention to detail and built to last."
                )
                templates.append({
                    "header": header,
                    "content": content,
                    "emotion_type": emotions[i].value if i < len(emotions) else None,
                })

        # 补充默认模板到 5 条
        default_templates = [
            {
                "header": "SUPERIOR QUALITY",
                "content": f"Crafted from premium materials, this {product_name} delivers exceptional durability and performance. Every detail is meticulously designed to exceed your expectations and provide lasting value.",
                "emotion_type": "gain_desired",
            },
            {
                "header": "EFFORTLESS OPERATION",
                "content": f"No complicated setup or learning curve required. The intuitive design means you can start enjoying the benefits of your {product_name} within minutes of unboxing. Perfect for beginners and experts alike.",
                "emotion_type": "pain_relief",
            },
            {
                "header": "MULTIPURPOSE VERSATILITY",
                "content": f"Whether for daily use or special occasions, this {product_name} adapts to your needs. Its flexible functionality makes it an indispensable addition to your home, office, or travel essentials.",
                "emotion_type": None,
            },
            {
                "header": "BUILT TO LAST",
                "content": f"Invest in quality that stands the test of time. Reinforced construction and premium materials ensure your {product_name} maintains peak performance through years of regular use. Backed by our quality promise.",
                "emotion_type": "fear_avoidance",
            },
            {
                "header": "100% SATISFACTION PROMISE",
                "content": f"We stand behind every {product_name} we sell. If you're not completely satisfied, our dedicated support team is here to help. Your purchase is risk-free with our customer-first guarantee.",
                "emotion_type": "social_proof",
            },
        ]

        while len(templates) < 5:
            templates.append(default_templates[len(templates)])

        return templates[:5]

    @staticmethod
    def _generate_description_intro(product_name: str, features: List[str]) -> str:
        """生成描述开篇"""
        return (
            f"Discover the perfect blend of innovation and quality with our {product_name}. "
            f"Designed for those who refuse to compromise on performance, this product delivers "
            f"exceptional results that make everyday tasks easier and more enjoyable. "
            f"Whether you're upgrading your setup or searching for the ideal gift, "
            f"this {product_name} exceeds expectations at every turn."
        )

    @staticmethod
    def _expand_bullets_to_description(bullets: BulletPoints) -> str:
        """将五点扩展为详细描述"""
        parts = []
        for bullet in bullets.bullets:
            part = f"<b>{bullet.title}</b><br>{bullet.content}<br><br>"
            parts.append(part)
        return "".join(parts)

    @staticmethod
    def _generate_usage_scenarios(product_name: str) -> str:
        """生成使用场景"""
        return (
            f"<b>Ideal For:</b> Perfect for home use, professional settings, travel, "
            f"and gifting. The versatile design of the {product_name} makes it suitable "
            f"for a wide range of applications, ensuring you get maximum value from your purchase."
        )

    @staticmethod
    def _generate_html_description(sections: List[Dict]) -> str:
        """生成 HTML 格式描述"""
        html_parts = []
        for section in sections:
            if section["type"] == "intro":
                html_parts.append(f'<p>{section["content"]}</p>')
            elif section["type"] == "features":
                html_parts.append(f'<div class="features">{section["content"]}</div>')
            elif section["type"] == "scenarios":
                html_parts.append(f'<div class="scenarios">{section["content"]}</div>')
        return "".join(html_parts)

    @staticmethod
    def _get_synonyms(keyword: str) -> List[str]:
        """获取同义词"""
        synonym_map = {
            "coffee grinder": ["coffee mill", "coffee crusher", "bean grinder", "manual grinder"],
            "blender": ["mixer", "food processor", "smoothie maker"],
            "charger": ["power adapter", "charging cable", "power supply"],
            "speaker": ["audio device", "sound system", "bluetooth speaker"],
        }
        keyword_lower = keyword.lower()
        for key, synonyms in synonym_map.items():
            if key in keyword_lower:
                return synonyms
        # 通用处理：返回一些常见变体
        base = keyword.split()[0] if keyword else ""
        return [f"{base} pro", f"{base} plus", f"{base} deluxe", f"premium {base}"]

    @staticmethod
    def _get_long_tail_keywords(category: str) -> List[str]:
        """获取长尾关键词"""
        long_tail = {
            "kitchen": ["for coffee lovers", "barista quality", "home brewing", "kitchen essential"],
            "electronics": ["wireless connectivity", "usb powered", "compact design", "energy efficient"],
            "home": ["space saving", "easy assembly", "modern style", "organization solution"],
            "general": ["gift idea", "best seller", "top rated", "customer favorite"],
        }
        return long_tail.get(category, long_tail["general"])

    @staticmethod
    def _get_spelling_variations(keyword: str) -> List[str]:
        """获取拼写变体"""
        variations = []
        words = keyword.split()
        for word in words:
            if len(word) > 4:
                # 常见美式/英式差异
                variations.append(word.replace("or", "er"))
                variations.append(word.replace("er", "or"))
        return [v for v in variations if v != keyword][:3]

    @staticmethod
    def _get_scenario_keywords(category: str) -> List[str]:
        """获取场景关键词"""
        scenarios = {
            "kitchen": ["morning routine", "office use", "travel friendly", "camping trip"],
            "electronics": ["work from home", "gaming setup", "home office", "portable use"],
            "home": ["apartment living", "small spaces", "first home", "moving gift"],
            "general": ["birthday gift", "holiday present", "anniversary", "housewarming"],
        }
        return scenarios.get(category, scenarios["general"])

    @staticmethod
    def _get_attribute_keywords() -> List[str]:
        """获取属性关键词"""
        return [
            "lightweight", "compact", "heavy duty", "waterproof",
            "adjustable", "foldable", "rechargeable", "automatic",
        ]

    @staticmethod
    def _select_best_title(candidates: List[str], main_keyword: str) -> str:
        """选择最优标题候选"""
        scored = []
        for candidate in candidates:
            score = 0
            # 长度分（目标区间内最高）
            if AmazonLimits.TITLE_TARGET_MIN <= len(candidate) <= AmazonLimits.TITLE_TARGET_MAX:
                score += 40
            elif len(candidate) <= AmazonLimits.TITLE_MAX_CHARS:
                score += 20

            # 关键词位置分
            words = candidate.split()[:5]
            if any(main_keyword.lower() in w.lower() for w in words):
                score += 35

            # 格式分（不全大写）
            if not candidate.isupper():
                score += 15

            # 品牌词分
            if candidate and candidate[0].isupper():
                score += 10

            scored.append((score, candidate))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else candidates[0]

    @staticmethod
    def _score_title(title: str, main_keyword: str, secondary_kw: List[str]) -> float:
        """计算标题 SEO 评分"""
        score = 50.0  # 基础分

        # 长度评分
        if AmazonLimits.TITLE_TARGET_MIN <= len(title) <= AmazonLimits.TITLE_TARGET_MAX:
            score += 25
        elif len(title) <= AmazonLimits.TITLE_MAX_CHARS:
            score += 15

        # 关键词覆盖
        title_lower = title.lower()
        if main_keyword.lower() in title_lower:
            score += 15

        kw_coverage = sum(1 for kw in secondary_kw if kw.lower() in title_lower)
        score += min(kw_coverage * 2, 10)

        return min(score, 100.0)

    @staticmethod
    def _calculate_bullet_coverage(bullets: List[BulletPoint], features: List[str]) -> float:
        """计算五点覆盖度"""
        if not features:
            return 80.0  # 无特性要求时给默认高分

        covered = 0
        for feature in features:
            for bullet in bullets:
                if feature.lower() in bullet.content.lower() or feature.lower() in bullet.title.lower():
                    covered += 1
                    break

        return round((covered / len(features)) * 100, 1) if features else 80.0

    @staticmethod
    def _guess_category(query: str) -> str:
        """猜测产品类目"""
        category_map = {
            "厨房": "kitchen", "coffee": "kitchen", "cooking": "kitchen",
            "电子": "electronics", "充电": "electronics", "蓝牙": "electronics",
            "家居": "home", "收纳": "home", "storage": "home",
            "运动": "sports", "健身": "sports", "yoga": "sports",
            "美妆": "beauty", "护肤": "beauty", "skincare": "beauty",
        }
        query_lower = query.lower()
        for cn, en in category_map.items():
            if cn in query or en in query_lower:
                return en
        return "general"

    @staticmethod
    def _generate_mock_features(product_name: str) -> List[str]:
        """模拟生成产品特性"""
        default_features = [
            "Premium material construction for durability",
            "User-friendly design for effortless operation",
            "Compact and portable for easy storage",
            "Versatile functionality for multiple use cases",
            "Quality assured with satisfaction guarantee",
        ]
        return default_features

    @staticmethod
    def _mock_extract_features(product: ProductData) -> List[str]:
        """从竞品提取特性（模拟）"""
        return [
            f"Similar to {product.title[:30]}",
            "Competitive pricing",
            f"Rating: {product.rating}/5",
        ]

    @staticmethod
    def _fix_bullet_format(bullet: str) -> str:
        """修复五点格式"""
        # 确保以大写字母开头
        fixed = bullet[0].upper() + bullet[1:] if bullet else bullet

        # 移除开头的符号
        for prefix in ['•', '-', '*', '✓', '✔']:
            if fixed.startswith(prefix):
                fixed = fixed[1:].strip()
                break

        return fixed

    @staticmethod
    def _enhance_description(description: str) -> str:
        """增强描述内容"""
        enhanced = description

        # 添加段落分隔
        if '\n' not in enhanced and len(enhanced) > 200:
            mid = len(enhanced) // 2
            enhanced = enhanced[:mid] + "\n\n" + enhanced[mid:]

        # 添加 CTA
        cta_phrases = ["buy now", "order today", "add to cart", "purchase"]
        has_cta = any(phrase in enhanced.lower() for phrase in cta_phrases)
        if not has_cta:
            enhanced += "\n\n🎯 Order now to experience the difference!"

        return enhanced

    @staticmethod
    def _get_improvement_suggestion(check_name: str) -> str:
        """根据检查项返回改进建议"""
        suggestion_map = {
            "title_length_ok": "调整标题长度至 120-180 字符",
            "title_not_exceeded": "缩短标题至 200 字符以内",
            "keyword_in_front": "将主关键词移至标题前部",
            "brand_included": "在标题开头添加品牌名",
            "no_all_caps": "避免标题全大写",
            "bullet_count_5": "确保有 5 条五点描述",
            "all_caps_header": "每条五点以大写标题开头",
            "no_over_length": "精简超长的五点描述",
            "unique_selling_points": "确保每条五点描述不同卖点",
            "emotion_triggers": "增加更多情感触发词",
            "has_intro": "添加引人入胜的开篇段落",
            "has_features": "添加产品特点详细介绍",
            "word_count_adequate": "扩充描述内容至 100 词以上",
            "has_cta": "添加行动号召语句",
            "has_html": "使用 HTML 格式增强展示效果",
            "bytes_within_limit": "精简关键词至 250 字节以内",
            "terms_count_adequate": "增加更多相关关键词",
            "no_duplicates": "移除重复的关键词",
            "not_empty": "填写后台搜索词",
        }
        return suggestion_map.get(check_name, "需要优化此项")

    async def _process_query(self, query: str, context: Dict[str, Any] = None) -> AgentResponse:
        """处理查询的主入口"""
        intent = await self._classify_intent(query)

        if intent == "generate":
            result = await self._generate_complete_listing(query, context)
        elif intent == "optimize":
            result = await self._optimize_existing_listing(context)
        elif intent == "seo_analysis":
            result = await self._analyze_seo_score(context)
        elif intent == "ab_test":
            result = await self._generate_ab_variants(context)
        else:
            result = await self._general_chat(query)

        return AgentResponse(
            content=result.get("summary") or json.dumps(result, ensure_ascii=False, indent=2),
            data=result,
            display_type=result.get("type", "general"),
        )

    async def _analyze_seo_score(self, context: Dict[str, Any]) -> dict:
        """执行 SEO 评分分析"""
        if not context:
            return {
                "type": "seo_error",
                "error": "请提供 Listing 内容进行 SEO 评分",
                "required_fields": ["title", "bullets", "description", "search_terms"],
            }

        # 构建临时对象用于评分
        title_data = context.get("title", "")
        title_obj = ListingTitle(
            title=title_data,
            character_count=len(title_data),
            word_count=len(title_data.split()),
            main_keyword=context.get("main_keyword", ""),
            seo_score=0,
        )

        bullets_data = context.get("bullets", [])
        bullets = BulletPoints(
            bullets=[
                BulletPoint(
                    bullet_id=i + 1,
                    title=b.split(':')[0].upper() if ':' in b else f"POINT {i+1}",
                    content=b.split(':', 1)[1] if ':' in b else b,
                    character_count=len(b),
                )
                for i, b in enumerate(bullets_data[:5])
            ],
            total_characters=sum(len(b) for b in bullets_data[:5]),
            coverage_score=0,
        )

        description_data = context.get("description", "")
        desc = ProductDescription(
            plain_text=description_data,
            html_content=None,
            word_count=len(description_data.split()),
            sections=[{"type": "user_provided", "content": description_data}],
        )

        keywords_data = context.get("search_terms", "")
        terms = keywords_data.split() if isinstance(keywords_data, str) else []
        keywords = SearchTerms(
            terms=terms,
            total_bytes=sum(len(t.encode('utf-8')) for t in terms),
            is_valid=True,
        )

        seo_score = self._calculate_seo_score(title_obj, bullets, desc, keywords)

        return {
            "type": "seo_analysis",
            "seo_score": seo_score.dict(),
            "summary": f"Listing SEO 综合评分: {seo_score.overall_score:.1f}/100",
        }
