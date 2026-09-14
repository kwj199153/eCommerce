"""
平台规则库 - 种子数据预置

首次启动（platform_rules 表为空）时，预置一批演示规则与来源文档，让「平台规则库」
打开即有内容。与 products / candidates / monitors 的 `seed_xxx_if_empty()` 惯例一致，
在 main.py 的 lifespan 里调用。

**shop_id 不硬编码**：早期 candidates/products 的 seed 把 shop_id 写成 `"shop-1"`，
而真实租户 id 是 `X-Shop-ID` 头传进来的 `store_xxxxxxxx` —— 列表端点按租户过滤后
一条都查不到（灌了等于没灌）。本模块一律先查 `stores_store` 取真实店铺 id，
为每个店铺各灌一份；库里没有店铺则直接跳过。

**id 追加店铺后缀**：两张表都是 id 单主键，多店铺灌入必须区分，否则第二个店铺主键冲突。
规则的 `source_doc_id` 指向文档 id，多店铺时要跟着映射（见下方 doc_id_map）。

**文档带正文**：这 5 篇预置文档带完整正文，是「AI 拆分」功能开箱可用的输入。
（用户新上传的文档只登记元数据、正文为空，AI 拆分会对它明确报错而不是编造内容。）
"""

from typing import Dict, List

from sqlalchemy import select, func

from core.database import async_session_factory
from modules.platform_rules.db_model import PlatformRuleDocRecord, PlatformRuleRecord
from modules.platform_rules.service import build_doc_record, build_rule_record
from modules.stores.db_model import StoreRecord


# 预置规则（6 条；id 沿用前端 MOCK_RULES，多店铺灌入时追加店铺后缀）
SEED_RULES: List[Dict] = [{'id': 'rule-001',
  'platform': 'amazon',
  'category': 'listing',
  'title': '商品标题字符数限制（2026 更新）',
  'content': 'Amazon 商品标题最多 200 字符，部分类目（如服饰鞋包）建议控制在 80 字符以内。禁止包含促销信息（如"best sale"、"free '
             'shipping"）、主观夸大词、特殊符号。标题格式建议：品牌 + 型号 + 核心卖点 + 规格 + 颜色。',
  'effective_date': '2026-01-15',
  'status': 'auto',
  'tags': ['标题', '字符限制', 'Listing'],
  'source': 'https://sellercentral.amazon.com',
  'source_doc_id': 'doc-amazon-listing-2026',
  'created_at': '2026-01-10T00:00:00Z',
  'updated_at': '2026-01-10T00:00:00Z'},
 {'id': 'rule-002',
  'platform': 'amazon',
  'category': 'compliance',
  'title': '亚马逊合规要求：电子产品 FCC 认证',
  'content': '所有无线电子设备（含蓝牙/WiFi）需提供 FCC 认证编号，否则将被下架或限制销售。需在 Listing 图片或描述中展示 FCC '
             'ID。新品上架前务必确认合规文档齐全。',
  'effective_date': '2025-07-01',
  'status': 'auto',
  'tags': ['FCC', '合规', '电子产品'],
  'source_doc_id': 'doc-amazon-compliance-2025',
  'created_at': '2025-06-20T00:00:00Z',
  'updated_at': '2025-06-20T00:00:00Z'},
 {'id': 'rule-003',
  'platform': 'shopee',
  'category': 'logistics',
  'title': 'Shopee 跨境物流时效与超时赔付',
  'content': 'SLS 标准物流承诺时效：东南亚 5-15 天。若超过承诺时效 3 天未妥投，买家可申请退款，卖家承担运费。建议使用 SLS 官方仓或海外仓降低时效风险。',
  'effective_date': '2025-10-01',
  'expiry_date': '2026-06-30',
  'status': 'auto',
  'tags': ['物流', 'SLS', '时效'],
  'source_doc_id': 'doc-shopee-logistics-2025',
  'created_at': '2025-09-15T00:00:00Z',
  'updated_at': '2025-09-15T00:00:00Z'},
 {'id': 'rule-004',
  'platform': 'tiktok',
  'category': 'ad',
  'title': 'TikTok Shop 广告素材审核规范',
  'content': '广告素材禁止使用虚假夸大宣传、前后对比夸张效果、未授权明星/网红肖像。视频需包含真实产品展示，禁止纯文字堆砌。违规将被限流或封禁广告账户。',
  'effective_date': '2026-10-01',
  'status': 'auto',
  'tags': ['广告', '素材审核', 'TikTok'],
  'source_doc_id': 'doc-tiktok-ad-2026',
  'created_at': '2026-01-25T00:00:00Z',
  'updated_at': '2026-01-25T00:00:00Z'},
 {'id': 'rule-005',
  'platform': 'temu',
  'category': 'policy',
  'title': 'TEMU 半托管模式佣金与结算规则',
  'content': '半托管模式下平台佣金率 8%-15%（按类目），结算周期 T+15。卖家需自行负责海外仓储与尾程物流。注意：低价引流品佣金优惠期有限，需关注类目政策变动。',
  'effective_date': '2025-12-01',
  'status': 'auto',
  'tags': ['佣金', '结算', '半托管'],
  'source_doc_id': 'doc-temu-policy-2025',
  'created_at': '2025-11-20T00:00:00Z',
  'updated_at': '2025-11-20T00:00:00Z'},
 {'id': 'rule-006',
  'platform': 'amazon',
  'category': 'review',
  'title': '亚马逊评价政策：禁止刷单与诱导好评（旧版）',
  'content': '严禁通过折扣、返现、礼品等方式诱导买家留好评（包括第三方刷单服务）。违反将导致账号冻结、Listing 下架甚至永久封店。允许通过合规的"早期评论者计划"获取评价。',
  'effective_date': '2024-06-01',
  'expiry_date': '2025-12-31',
  'status': 'expired',
  'tags': ['评价', '刷单', '合规', '已作废'],
  'source_doc_id': 'doc-amazon-compliance-2025',
  'created_at': '2024-05-15T00:00:00Z',
  'updated_at': '2025-12-31T00:00:00Z'}]

# 预置文档素材（5 篇平台官方文档，带完整正文）
SEED_DOCS: List[Dict] = [{'id': 'doc-amazon-listing-2026',
  'platform': 'amazon',
  'filename': 'Amazon_Listing_Guidelines_2026.pdf',
  'file_type': 'pdf',
  'size': 2457600,
  'uploaded_at': '2026-01-10T00:00:00Z',
  'description': 'Amazon 2026 Listing 完整规范（标题/图片/描述/搜索词）',
  'content': 'Amazon Listing Guidelines — 2026 Edition\n'
             '\n'
             '1. TITLE REQUIREMENTS (商品标题规范)\n'
             '\n'
             '1.1 Character Limits\n'
             '- Maximum length: 200 characters\n'
             '- Recommended length for Apparel/Shoes/Bags categories: 80 characters or fewer\n'
             '- Each word in the title must contribute to search relevance\n'
             '\n'
             '1.2 Prohibited Content in Titles\n'
             'The following are NOT allowed in product titles:\n'
             '- Promotional phrases such as "best seller", "free shipping", "100% quality", '
             '"guaranteed"\n'
             '- Subjective claims like "amazing", "high quality" (unless part of registered brand '
             'name)\n'
             '- Price or quantity information (e.g., "2-pack", "$9.99")\n'
             '- Special characters: !, ?, *, ~, etc.\n'
             '- All CAPS words (except brand acronyms)\n'
             '\n'
             '1.3 Title Format Guidelines\n'
             'Recommended structure:\n'
             '[Brand Name] + [Model/Series] + [Core Feature] + [Specification] + [Color/Size]\n'
             '\n'
             'Examples:\n'
             '✓ "Sony WH-1000XM5 Wireless Noise Cancelling Headphones - Black"\n'
             '✓ "Anker PowerCore 26800mAh Portable Charger, High-Capacity External Battery Pack"\n'
             '✗ "BEST SELLER!!! Premium Quality Amazing Bluetooth Headphones Black FREE SHIPPING"\n'
             '\n'
             '2. IMAGE REQUIREMENTS (图片要求)\n'
             '\n'
             '2.1 Main Image (主图)\n'
             '- Must be a professional product photograph on pure white background (RGB '
             '255,255,255)\n'
             '- Minimum resolution: 1000 x 1000 pixels for zoom capability\n'
             '- Product must occupy ≥85% of the image frame\n'
             '- No text, logos, watermarks, or borders on main image\n'
             '- No accessories shown unless they are included with the product\n'
             '\n'
             '2.2 Secondary Images (附图)\n'
             '- Up to 8 additional images allowed\n'
             '- Show product from multiple angles, in use, lifestyle context, and detail shots\n'
             '- Infographics showing dimensions, features, and comparisons are permitted\n'
             '- Text on secondary images should be minimal and informative only\n'
             '\n'
             '3. PRODUCT DESCRIPTION (商品描述)\n'
             '\n'
             '3.1 Key Product Features (五点描述)\n'
             '- Exactly 5 bullet points required\n'
             '- Each bullet point: max 500 characters\n'
             '- Start each bullet with CAPITAL LETTER (no lowercase start)\n'
             '- Focus on product benefits, not just features\n'
             '- Include key search terms naturally\n'
             '\n'
             '3.2 Product Description (长描述)\n'
             '- HTML formatting supported (<b>, <br>, <p> tags)\n'
             '- Max 2000 characters recommended\n'
             '- Use clear paragraphs with headers\n'
             '- Include care instructions, warranty info where applicable\n'
             '\n'
             '4. SEARCH TERMS (后台搜索词)\n'
             '- Backend search terms field (not visible to customers)\n'
             '- Limit: 249 bytes total\n'
             '- Do NOT repeat words already in title\n'
             '- Use generic descriptive terms, not brand names\n'
             '- Separate terms by spaces (commas not needed)\n'
             '\n'
             '5. CATEGORY-SPECIFIC RULES\n'
             '5.1 Electronics: Must display FCC/CE certification info if applicable\n'
             '5.2 Food/Supplements: Must include ingredients, allergen warnings, nutrition facts\n'
             '5.3 Beauty Products: Full ingredient list required; no unverified medical claims\n'
             '5.4 Toys: Age appropriatement labeling mandatory; safety compliance docs required\n'
             '5.5 Dietary Supplements: Cannot make disease treatment claims per FDA guidelines\n'
             '\n'
             '6. ENFORCEMENT & PENALTIES\n'
             '- First violation: Listing suppressed, warning issued\n'
             '- Repeated violations: Account health score degradation\n'
             '- Severe/pattern violations: ASIN suspension or account deactivation\n'
             '\n'
             'Document Version: 2026.01 | Last Updated: 2026-01-10 | Source: Seller Central'},
 {'id': 'doc-amazon-compliance-2025',
  'platform': 'amazon',
  'filename': 'Amazon_Compliance_Policies_2025.pdf',
  'file_type': 'pdf',
  'size': 5242880,
  'uploaded_at': '2025-06-20T00:00:00Z',
  'description': '亚马逊合规政策全集：认证要求、禁售品、知识产权',
  'content': 'Amazon Compliance Policies — Complete Reference (2025)\n'
             '\n'
             'SECTION A: PRODUCT CERTIFICATION REQUIREMENTS\n'
             '\n'
             'A.1 Electronic Devices (电子产品认证)\n'
             'All electronic products sold on Amazon MUST comply with:\n'
             '\n'
             '| Certification | Applicable Region | Required For |\n'
             '|--------------|-------------------|-------------|\n'
             '| FCC ID | USA market | All wireless devices (Bluetooth, WiFi, cellular) |\n'
             '| CE Marking | EU market | All electronic products sold to EU |\n'
             '| RoHS Directive | EU market | Products containing restricted substances |\n'
             '| UL/ETL Listing | USA market | Plug-in electrical devices |\n'
             '| FDA Registration | Global | Medical devices, food contact products |\n'
             '\n'
             'A.2 How to Submit Certifications\n'
             '1. Navigate to Seller Central → Catalog → Manage Your Compliance\n'
             '2. Upload documentation for each applicable ASIN\n'
             '3. Documents accepted: PDF, JPG, PNG (max 10MB each)\n'
             '4. Processing time: 3-5 business days\n'
             '5. Expired certifications will trigger listing suppression\n'
             '\n'
             'A.3 Consequences of Non-Compliance\n'
             '- Day 1-7: Warning email + listing suppression option\n'
             '- Day 8-30: Mandatory listing suppression until compliant\n'
             '- Day 30+: Account review possible; repeated offenses = account suspension\n'
             '\n'
             'SECTION B: PROHIBITED PRODUCTS (禁售品清单)\n'
             '\n'
             'B.1 Absolutely Prohibited (永久禁售)\n'
             '- Counterfeit products of any kind\n'
             '- Illegal drugs and controlled substances\n'
             '- Weapons (firearms, ammunition, certain knives)\n'
             '- Stolen property\n'
             '- Products promoting hate speech, violence, or discrimination\n'
             '- Endangered species products (CITES protected)\n'
             '- Human remains/body parts\n'
             '\n'
             'B.2 Restricted (需审批/特殊许可)\n'
             '- Dietary supplements (require proper labeling, no disease claims)\n'
             '- Cosmetics (must list all ingredients, no false advertising)\n'
             '- Batteries (lithium batteries require UN38.3 testing + proper packaging)\n'
             '- GPS jammers / signal blockers (illegal in most jurisdictions)\n'
             '- Lock-picking devices (age-gated in many markets)\n'
             '\n'
             'B.3 Condition-Specific Restrictions\n'
             '- Used products: Must be accurately described as used/refurbished\n'
             '- Hazardous materials: Require SDS (Safety Data Sheet) submission\n'
             '- Food products: Must have proper expiration date labeling\n'
             '\n'
             'SECTION C: INTELLECTUAL PROPERTY (知识产权)\n'
             '\n'
             'C.1 Trademark Infringement\n'
             "Using another company's registered trademark without permission constitutes "
             'infringement, including:\n'
             '- Using trademark in product title/description\n'
             '- Using similar-sounding brand names (passing off)\n'
             '- Selling counterfeit versions of branded products\n'
             '\n'
             'C.2 Copyright Infringement\n'
             '- Copying product images from other sellers without permission\n'
             '- Using copyrighted text descriptions\n'
             '- Selling unauthorized replicas of copyrighted designs\n'
             '\n'
             'C.3 Patent Infringement\n'
             '- Selling products that infringe utility/design patents\n'
             '- Neutral evaluation process available through Amazon Patent Evaluation Express\n'
             '\n'
             'C.4 Reporting IP Violations\n'
             'Rights owners can report via Amazon Brand Registry or Brand Protection\n'
             '- Average response time: 24-48 hours\n'
             '- Evidence required: registration numbers, test buy results, side-by-side '
             'comparisons\n'
             '\n'
             'SECTION D: REVIEW MANIPULATION POLICY (评价政策)\n'
             '\n'
             'D.1 What is PROHIBITED (严禁行为):\n'
             '- Offering refunds/discounts/gifts in exchange for positive reviews\n'
             '- Using third-party services to generate fake reviews\n'
             '- Asking friends/family to leave reviews\n'
             '- Creating multiple buyer accounts to review own products\n'
             '- Manipulating review ranking/suppression\n'
             '\n'
             'D.2 What IS ALLOWED (合规方式):\n'
             '- Amazon Vine program (invited trusted reviewers)\n'
             '- Early Reviewer Program (for new ASINs < 1 year old)\n'
             '- Request a Review button (one per order, Amazon-generated timing)\n'
             '- Including unbiased product insert cards (NO incentive language)\n'
             '\n'
             'D.3 Penalties for Review Manipulation\n'
             '- Detected manipulation: immediate review suppression\n'
             '- Pattern behavior: ASIN review privileges revoked\n'
             '- Severe cases: permanent account suspension + legal action\n'
             '\n'
             'SECTION E: ACCOUNT HEALTH METRICS (账户健康指标)\n'
             '\n'
             'E.1 Key Metrics Thresholds\n'
             '| Metric | Healthy Target | Warning Zone | Critical |\n'
             '|--------|---------------|-------------|----------|\n'
             '| Order Defect Rate (ODR) | < 1% | 1% - 2% | > 2% |\n'
             '| Late Shipment Rate | < 4% | 4% - 6% | > 6% |\n'
             '| Valid Tracking Rate | > 95% | 90-95% | < 90% |\n'
             '| Return Dissatisfaction Rate | < 2.5% | 2.5-4% | > 4% |\n'
             '\n'
             'E.2 Account Health Score\n'
             '- Scale: 0-1000 (higher = better)\n'
             '- Below 200: Risk of deactivation\n'
             '- Below 100: Immediate action required\n'
             '\n'
             'Document Version: 2025.06 | Last Updated: 2025-06-20 | Source: Amazon Seller '
             'Policies'},
 {'id': 'doc-shopee-logistics-2025',
  'platform': 'shopee',
  'filename': 'Shopee_SLS_Logistics_Policy_2025.pdf',
  'file_type': 'pdf',
  'size': 1572864,
  'uploaded_at': '2025-09-15T00:00:00Z',
  'description': 'Shopee 跨境物流 SLS 时效、赔付、海外仓规范',
  'content': 'Shopee Logistics Service (SLS) Policy — Cross-Border Operations (2025)\n'
             '\n'
             '1. SLS SERVICE OVERVIEW (服务概述)\n'
             '\n'
             'Shopee Logistics Service (SLS) is the official cross-border logistics solution '
             'connecting sellers to buyers across Southeast Asia.\n'
             '\n'
             'Supported Markets:\n'
             '- Singapore (SG), Malaysia (MY), Philippines (PH), Vietnam (VN)\n'
             '- Thailand (TH), Indonesia (ID), Brazil (BR), Mexico (MX)\n'
             '\n'
             '2. SHIPPING TIME STANDARDS (时效标准)\n'
             '\n'
             '2.1 Standard SLS Delivery Timeframes\n'
             '| Destination | Standard Delivery | First Mile Pickup |\n'
             '|------------|------------------|-------------------|\n'
             '| Singapore | 5-7 days | 1-2 days |\n'
             '| Malaysia | 6-12 days | 1-2 days |\n'
             '| Philippines | 8-15 days | 2-3 days |\n'
             '| Vietnam | 8-15 days | 2-3 days |\n'
             '| Thailand | 6-12 days | 1-2 days |\n'
             '| Indonesia | 8-18 days | 2-3 days |\n'
             '\n'
             '2.2 Late Delivery Compensation (超时赔付)\n'
             'If delivery exceeds promised time by MORE than 3 business days:\n'
             '- Buyer can request full refund at NO cost to buyer\n'
             '- Seller bears the return shipping cost (if any)\n'
             "- Seller's late delivery rate metric increases (affects shop rating)\n"
             '\n'
             '2.3 First Mile Collection (揽收规则)\n'
             '- Seller prepares package → SLS courier pickup OR self-drop at designated point\n'
             '- Pickup window: 09:00-20:00 local time\n'
             '- Package must be ready before pickup time slot\n'
             '- Maximum weight per package: depends on destination (typically ≤30kg)\n'
             '\n'
             '3. PACKAGING REQUIREMENTS (包装要求)\n'
             '\n'
             '3.1 General Rules\n'
             '- Use sturdy corrugated boxes (no damaged/reused boxes)\n'
             '- Internal cushioning required for fragile items\n'
             '- No excessive packaging (environmental policy)\n'
             '- Shipping label affixed flat on largest surface\n'
             '\n'
             '3.2 Prohibited Packaging Materials\n'
             '- Newspaper (ink may stain products)\n'
             '- Loose fill peanuts (not eco-friendly in some markets)\n'
             '- Used/recycled bags that may have odors\n'
             '\n'
             '3.3 Label Requirements\n'
             '- Shopee-provided SLS label MANDATORY\n'
             '- Barcode must be scannable (no creases/folds over barcode)\n'
             '- Invoice/packing list inside package (customs requirement)\n'
             '\n'
             '4. OVERSEAS WAREHOUSE (海外仓)\n'
             '\n'
             '4.1 Shopee Warehouse Options\n'
             '- Local Fulfillment Warehouse (LFW): Store inventory locally in destination country\n'
             '- Benefits: Faster delivery (1-3 days), lower shipping costs, better buyer '
             'experience\n'
             '- Eligibility: Shop rating ≥ 4.5, on-time shipment rate ≥ 90%\n'
             '\n'
             '4.2 Inventory Management\n'
             '- Real-time stock sync via API\n'
             '- Low-stock alerts when inventory falls below 7-day sales volume\n'
             '- Shelf-life tracking for perishables\n'
             '\n'
             '5. PROHIBITED ITEMS FOR SHIPMENT (物流禁运品)\n'
             '\n'
             '5.1 Not Accepted by SLS\n'
             '- Lithium batteries (use specialized channel)\n'
             '- Liquids > 500ml per item\n'
             '- Compressed gases/aerosols\n'
             '- Magnetic materials affecting aviation safety\n'
             '- Currency, precious metals, securities\n'
             '- Live animals and plants\n'
             '- Items requiring cold chain (perishable foods)\n'
             '\n'
             '5.2 Special Handling Categories\n'
             '- Cosmetics: MSDS required for liquids\n'
             '- Powders: Non-hazardous certificate needed\n'
             '- Textiles: Fumigation cert for some destinations\n'
             '\n'
             '6. DISPUTE & CLAIM PROCESS (纠纷处理)\n'
             '\n'
             '6.1 Lost Package Claims\n'
             '- File claim within 7 days of expected delivery\n'
             '- Proof of handover to SLS required\n'
             '- Compensation: Actual product value (max claim limit varies by tier)\n'
             '\n'
             '6.2 Damaged Package Claims\n'
             '- Photo evidence required (package + product damage)\n'
             '- File within 48 hours of delivery\n'
             '- SLS investigation: 5-10 business days\n'
             '\n'
             'Document Version: 2025.Q3 | Source: Shopee Seller Center'},
 {'id': 'doc-tiktok-ad-2026',
  'platform': 'tiktok',
  'filename': 'TikTok_Shop_Ad_Policy_2026.pdf',
  'file_type': 'pdf',
  'size': 3145728,
  'uploaded_at': '2026-01-25T00:00:00Z',
  'description': 'TikTok Shop 广告素材审核规范与违规处罚细则',
  'content': 'TikTok Shop Advertising Content Policy — 2026 Update\n'
             '\n'
             '1. ADVERTISING CONTENT STANDARDS (广告内容标准)\n'
             '\n'
             '1.1 Core Principles\n'
             'All advertising content on TikTok Shop MUST be:\n'
             '- TRUTHFUL: No false or misleading claims about product performance\n'
             '- AUTHENTIC: Show real product, real usage scenarios\n'
             '- SAFE: No dangerous activities or prohibited content\n'
             '- RESPECTFUL: No discrimination, harassment, or inappropriate content\n'
             '\n'
             '1.2 Video Ad Requirements\n'
             '- Minimum duration: 6 seconds | Maximum: 180 seconds\n'
             '- Product must appear within first 3 seconds\n'
             '- Audio must be clear and synchronized with video\n'
             '- Text overlays must remain on screen long enough to read (≥2 seconds)\n'
             '\n'
             '2. PROHIBITED CONTENT IN ADS (广告禁止内容)\n'
             '\n'
             '2.1 Misleading Claims (虚假宣传)\n'
             '❌ Before/after exaggeration (extreme photo editing)\n'
             '❌ Unrealistic results ("lose 10kg in 3 days")\n'
             '❌ False scarcity ("only 2 left!" when not true)\n'
             '❌ Fake endorsements (paid actors as "real users")\n'
             '❌ Comparative bashing competitors by name\n'
             '\n'
             '2.2 Visual Deception (视觉欺骗)\n'
             "❌ Showing wrong product in ad vs what's actually sold\n"
             '❌ Using stock photos without disclosure\n'
             '❌ Excessive filters that misrepresent product appearance\n'
             '❌ CGI/rendered images presented as real photos\n'
             '\n'
             '2.3 Unauthorized Content (未授权内容)\n'
             '❌ Celebrity/influencer likeness without written consent\n'
             '❌ Music without commercial license\n'
             "❌ Branded content from other platforms' exclusive creators\n"
             '❌ User Generated Content (UGC) reposted without permission\n'
             '\n'
             '2.4 Prohibited Categories (禁止品类)\n'
             '- Tobacco, e-cigarettes, vaping products\n'
             '- Alcohol (varies by region)\n'
             '- Weapons and dangerous items\n'
             '- Adult content and suggestive material\n'
             '- Gambling and betting services\n'
             '- Cryptocurrency investment schemes\n'
             '- Unregulated health supplements making medical claims\n'
             '\n'
             '3. CREATIVE GUIDELINES BY FORMAT (各格式创意指南)\n'
             '\n'
             '3.1 In-Feed Ads (信息流广告)\n'
             '- Aspect ratio: 9:16 (vertical) or 1:1 (square)\n'
             '- Resolution: min 720p, recommended 1080p\n'
             '- Duration: 5-60 seconds optimal\n'
             '- Hook (first 3 seconds): Critical for engagement\n'
             '\n'
             '3.2 Spark Ads (原生广告)\n'
             '- Must use organic TikTok content style\n'
             '- Branded content disclosure REQUIRED\n'
             '- No overly polished "TV commercial" feel\n'
             '- Encourage comments and engagement\n'
             '\n'
             '3.3 Collection Ads (Collection 广告)\n'
             '- Product card image: white background, high quality\n'
             '- Price must match actual selling price (±5% tolerance)\n'
             '- Stock availability must be accurate in real-time\n'
             '\n'
             '4. REVIEW & APPROVAL PROCESS (审核流程)\n'
             '\n'
             '4.1 Automated Pre-Check (AI 初审)\n'
             '- Submitted ads scanned by AI within minutes\n'
             '- Common rejections: prohibited keywords, low quality, policy violations\n'
             '- Resolution: Edit and resubmit\n'
             '\n'
             '4.2 Human Review (人工复审)\n'
             '- Triggered for: new advertisers, flagged content, high-spend campaigns\n'
             '- Turnaround: 24-48 hours\n'
             '- Feedback provided for rejected ads\n'
             '\n'
             '5. PENALTY FRAMEWORK (处罚框架)\n'
             '\n'
             '5.1 First Violation\n'
             '- Ad disapproval with explanation\n'
             '- Warning notification to advertiser account\n'
             '- No financial penalty\n'
             '\n'
             '5.2 Repeated Violations (within 30 days)\n'
             '- Ad account spending limit reduction\n'
             '- Temporary ad creation suspension (3-7 days)\n'
             '- Mandatory advertising policy training\n'
             '\n'
             '5.3 Severe/Persistent Violations\n'
             '- Permanent ad account ban\n'
             '- Associated TikTok Shop account review\n'
             '- Legal action for fraudulent advertising practices\n'
             '\n'
             '5.4 Appeal Process\n'
             '- Submit appeal within 15 days of penalty\n'
             '- Provide corrective evidence\n'
             '- Second-level review by senior moderation team\n'
             '\n'
             'Document Version: 2026.Q1 | Source: TikTok Shop Ads Help Center'},
 {'id': 'doc-temu-policy-2025',
  'platform': 'temu',
  'filename': 'TEMU_Semi_Managed_Policy_2025.pdf',
  'file_type': 'pdf',
  'size': 2097152,
  'uploaded_at': '2025-11-20T00:00:00Z',
  'description': 'TEMU 半托管模式佣金、结算、物流政策说明',
  'content': 'TEMU Semi-Managed Mode Policy Guide — November 2025\n'
             '\n'
             '1. SEMI-MANAGED MODE OVERVIEW (半托管模式概述)\n'
             '\n'
             "TEMU's Semi-Managed mode allows sellers to manage their own overseas warehousing and "
             "last-mile delivery while leveraging TEMU's traffic and customer service "
             'infrastructure.\n'
             '\n'
             'Key Differences from Full-Managed:\n'
             '| Aspect | Full-Managed | Semi-Managed |\n'
             '|--------|-------------|--------------|\n'
             '| Warehousing | TEMU warehouse | Seller-managed overseas warehouse |\n'
             '| Last-mile delivery | TEMU handles | Seller arranges |\n'
             '| Pricing | TEMU sets final price | Seller suggests, TEMU approves |\n'
             '| Customer service | TEMU fully handles | Shared responsibility |\n'
             '| Commission | Higher base | Lower base (reward for logistics capability) |\n'
             '\n'
             '2. COMMISSION STRUCTURE (佣金结构)\n'
             '\n'
             '2.1 Base Commission Rates (by Category)\n'
             '| Category | Commission Rate | Notes |\n'
             '|----------|----------------|-------|\n'
             '| Electronics | 12-15% | High-value items |\n'
             '| Fashion/Apparel | 10-13% | Volume-based discounts available |\n'
             '| Home & Garden | 8-11% | Bulky items surcharge may apply |\n'
             '| Beauty & Health | 10-14% | Cosmetic regulations vary by market |\n'
             '| Sports & Outdoors | 9-12% | Equipment category specific |\n'
             '| General Merchandise | 8-10% | Default rate |\n'
             '\n'
             '2.2 Additional Fees\n'
             '- Payment processing fee: 1.5% per transaction\n'
             '- Return handling fee: $2-5 per returned item (category dependent)\n'
             '- Overseas warehouse storage fee: $0.15-0.40/cubic foot/day\n'
             '- Long-tail storage fee (>90 days): 3x standard rate\n'
             '\n'
             '2.3 Settlement Cycle\n'
             '- Standard settlement: T+15 (15 days after order delivery)\n'
             '- Fast-track settlement: T+7 (requires premium seller status, 0.5% fee)\n'
             '- Minimum payout threshold: $20 USD\n'
             '- Payment methods: Payoneer / PingPong / Wire Transfer\n'
             '\n'
             '3. LOGISTICS REQUIREMENTS (物流要求)\n'
             '\n'
             '3.1 Overseas Warehouse Standards\n'
             '- Location: Must be in target market country (US/EU/etc.)\n'
             '- Processing SLA: Order shipped within 24 hours of receipt\n'
             '- Tracking integration: Real-time tracking API connection required\n'
             '- Accuracy: Pick error rate < 0.5%\n'
             '\n'
             '3.2 Last-Mile Delivery Partners\n'
             '- Approved carriers list maintained by TEMU\n'
             '- Sellers must use approved carriers for TEMU orders\n'
             '- Delivery SLA: Domestic delivery within 3-5 days\n'
             '- On-time delivery rate target: ≥ 95%\n'
             '\n'
             '3.3 Quality Control (入仓质检)\n'
             '- Random inspection rate: 5-15% of shipments\n'
             '- Inspection criteria: Packaging integrity, correct SKU, no damage\n'
             '- Non-compliant items: Returned at seller expense or disposed\n'
             '- Dispute process: 48-hour response window for QC appeals\n'
             '\n'
             '4. PRICING RULES (定价规则)\n'
             '\n'
             '4.1 Price Setting\n'
             '- Seller submits suggested retail price (SRP)\n'
             '- TEMU reviews and sets final selling price (may adjust ±20%)\n'
             '- Price changes require 48-hour advance notice\n'
             '- Flash sale prices cannot exceed 30% discount from regular price\n'
             '\n'
             '4.2 Price Floor Protection\n'
             '- TEMU guarantees minimum margin for sellers\n'
             '- If market price drops below cost floor, TEMU absorbs difference (limited)\n'
             '- Price protection period: 30 days from listing approval\n'
             '\n'
             '5. LOW-PRICE INCENTIVE PROGRAM (低价引流政策)\n'
             '\n'
             '5.1 Current Promotion (Q4 2025)\n'
             '- New listings under $10: 50% commission reduction for first 60 days\n'
             '- Bestseller items: Volume-based commission rebates\n'
             '- Program ends: December 31, 2025 (subject to extension)\n'
             '\n'
             '5.2 Eligibility\n'
             '- Seller rating ≥ 4.5 stars\n'
             '- On-time delivery rate ≥ 98%\n'
             '- Return rate ≤ 5%\n'
             '- No active policy violations\n'
             '\n'
             '6. PERFORMANCE METRICS & CONSEQUENCES (绩效指标)\n'
             '\n'
             '6.1 KPI Dashboard Metrics\n'
             '| Metric | Target | Warning | Penalty |\n'
             '|--------|--------|---------|---------|\n'
             '| Order fulfillment rate | ≥ 98% | 95-98% | < 95% |\n'
             '| On-time shipping | ≥ 96% | 93-96% | < 93% |\n'
             '| Return rate | ≤ 5% | 5-8% | > 8% |\n'
             '| Customer complaint rate | ≤ 1% | 1-2% | > 2% |\n'
             '| QC pass rate | ≥ 97% | 94-97% | < 94% |\n'
             '\n'
             '6.2 Consequence Ladder\n'
             'Level 1 (Warning): Performance improvement plan required\n'
             'Level 2 (Restriction): New listing quota reduced by 50%\n'
             'Level 3 (Suspension): Semi-managed privilege suspended for 14 days\n'
             'Level 4 (Termination): Permanent removal from program\n'
             '\n'
             'Document Version: 2025.11 | Source: TEMU Seller Portal'}]



async def seed_platform_rules_if_empty() -> int:
    """
    首次启动时，若 platform_rules 表为空，**为每个已存在的店铺**预置种子数据。

    Returns:
        实际写入的条数（规则 + 文档；表非空、或无店铺可归属时返回 0）。
    """
    async with async_session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(PlatformRuleRecord)
        )).scalar_one()
        if count > 0:
            return 0

        # 取真实店铺 id；一个都没有则跳过（无租户上下文，灌了也查不到）
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        total = 0
        for shop_id in shop_ids:
            # 文档先建：规则要引用文档 id，而多店铺下 id 带后缀，必须同步映射
            doc_id_map: Dict[str, str] = {}
            for data in SEED_DOCS:
                payload = {**data, "id": f"{data['id']}-{shop_id}"}
                record = build_doc_record(payload, shop_id=shop_id)
                doc_id_map[data["id"]] = record.id
                session.add(record)

            for data in SEED_RULES:
                payload = {**data, "id": f"{data['id']}-{shop_id}"}
                src = payload.get("source_doc_id")
                if src:
                    payload["source_doc_id"] = doc_id_map.get(src, src)
                session.add(build_rule_record(payload, shop_id=shop_id))

            total += len(SEED_DOCS) + len(SEED_RULES)

        await session.commit()

    return total
