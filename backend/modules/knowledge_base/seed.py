"""
业务话术库 - 种子数据

首次启动时为**每个已登录店铺**各预置一份演示话术库（默认库 + 6 条通用问答），
让「资料库 → 业务话术库」开箱就有内容可看、可编辑。

数据来源：由 `frontend/src/stores/knowledge.ts` 的 `DEFAULT_KNOWLEDGE_BASES` /
`MOCK_FAQS` 提取（脚本提取，非手抄），保证前后端演示数据一致。

**两个注意点**：

① `id` / `kb_id` 在这里是**逻辑 id**，灌库时统一加店铺后缀
   （`kb-default-{shop_id}` / `faq-001-{shop_id}`）。
   单主键表（id 全局唯一）多店铺灌入必须加后缀，否则第二个店铺主键冲突。

② 幂等靠 `if count > 0: return 0` 守卫 —— 表非空即视为「已初始化」。
   这与 candidates / monitors / platform_rules 的 seed 同构。
"""

from sqlalchemy import func, select

from core.database import async_session_factory
from modules.knowledge_base.db_model import (
    KnowledgeBaseRecord,
    KnowledgeFaqRecord,
)
from modules.stores.db_model import StoreRecord

# 知识库容器（逻辑 id，灌库时加店铺后缀；is_default 由 seed 强制置真）
SEED_BASES = [{'id': 'kb-default',
  'name': '通用话术库',
  'description': '默认通用问答，适用于全场景',
  'icon': '📚',
  'type': 'custom',
  'faq_count': 6,
  'doc_count': 0,
  'created_at': '2026-08-01T00:00:00Z',
  'updated_at': '2026-09-02T00:00:00Z',
  'is_default': True}]

# 话术条目（kb_id 为占位，seed 时映射为实际的带后缀 kb_id）
SEED_FAQS = [{'id': 'faq-001',
  'kb_id': 'kb-default',
  'question': '订单发货后多久可以收到？',
  'answer': '标准配送通常需要 3-7 个工作日。加急配送 1-3 个工作日。具体时间取决于收货地址和物流商。',
  'category': 'shipping',
  'keywords': ['发货', '配送', '快递', '多久', '几天'],
  'priority': 'high',
  'status': 'active',
  'usage_count': 156,
  'created_at': '2026-08-15T10:00:00Z',
  'updated_at': '2026-08-20T14:30:00Z'},
 {'id': 'faq-002',
  'kb_id': 'kb-default',
  'question': '如何申请退货？',
  'answer': '收到商品后 30 天内可在「我的订单」中点击「申请退货」，选择退货原因并提交。审核通过后寄回商品，退款将在 3-5 个工作日原路返回。',
  'category': 'return',
  'keywords': ['退货', '退款', '怎么退', '退换'],
  'priority': 'high',
  'status': 'active',
  'usage_count': 203,
  'created_at': '2026-08-10T09:00:00Z',
  'updated_at': '2026-08-25T11:00:00Z'},
 {'id': 'faq-003',
  'kb_id': 'kb-default',
  'question': '商品有质量问题怎么办？',
  'answer': '如收到商品存在质量问题，请在签收后 48 小时内联系客服，提供照片证据。我们将安排免费换货或全额退款，运费由我们承担。',
  'category': 'product',
  'keywords': ['质量', '问题', '损坏', '瑕疵', ' defective'],
  'priority': 'high',
  'status': 'active',
  'usage_count': 89,
  'created_at': '2026-08-12T16:00:00Z',
  'updated_at': '2026-08-22T10:00:00Z'},
 {'id': 'faq-004',
  'kb_id': 'kb-default',
  'question': '支持哪些支付方式？',
  'answer': '我们支持信用卡（Visa/Mastercard/AE）、PayPal、Apple Pay、Google Pay 以及本地支付方式（根据收货地区自动显示可用选项）。',
  'category': 'payment',
  'keywords': ['支付', '付款', '信用卡', 'PayPal', '方式'],
  'priority': 'medium',
  'status': 'active',
  'usage_count': 134,
  'created_at': '2026-08-08T12:00:00Z',
  'updated_at': '2026-08-18T09:00:00Z'},
 {'id': 'faq-005',
  'kb_id': 'kb-default',
  'question': '如何修改账户信息？',
  'answer': '登录后进入「账户设置」，可修改邮箱、手机号、收货地址等信息。修改邮箱和手机需验证原信息。',
  'category': 'account',
  'keywords': ['账户', '修改', '信息', '密码', '设置'],
  'priority': 'medium',
  'status': 'active',
  'usage_count': 67,
  'created_at': '2026-08-05T14:00:00Z',
  'updated_at': '2026-08-15T16:00:00Z'},
 {'id': 'faq-006',
  'kb_id': 'kb-default',
  'question': '可以更改收货地址吗？',
  'answer': '订单未发货前可在订单详情页修改地址。已发货订单无法更改，请联系客服尝试拦截。',
  'category': 'shipping',
  'keywords': ['地址', '收货', '更改', '修改', '配送地址'],
  'priority': 'medium',
  'status': 'active',
  'usage_count': 78,
  'created_at': '2026-08-14T11:00:00Z',
  'updated_at': '2026-08-20T15:00:00Z'}]


async def seed_knowledge_if_empty() -> int:
    """
    首次启动预置演示话术库。返回写入的行数（0 = 跳过）。

    跳过条件：① 容器表已有数据（幂等守卫）② 库里一个店铺都没有
    （无租户维度就无法归属，硬灌一份 shop_id="" 的数据会在任何店铺下都查不到）。
    """
    async with async_session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(KnowledgeBaseRecord)
        )).scalar_one()
        if count > 0:
            return 0

        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        total = 0
        for shop_id in shop_ids:
            for base in SEED_BASES:
                kb_id = f"{base['id']}-{shop_id}"
                session.add(KnowledgeBaseRecord(
                    id=kb_id,
                    shop_id=shop_id,
                    name=base.get("name", ""),
                    description=base.get("description", ""),
                    icon=base.get("icon", "\U0001F4DA"),
                    type=base.get("type", "custom"),
                    is_default=bool(base.get("is_default")),
                    created_at=base.get("created_at"),
                    updated_at=base.get("updated_at"),
                ))
                total += 1

                for faq in SEED_FAQS:
                    session.add(KnowledgeFaqRecord(
                        id=f"{faq['id']}-{shop_id}",
                        shop_id=shop_id,
                        kb_id=kb_id,
                        question=faq.get("question", ""),
                        answer=faq.get("answer", ""),
                        category=faq.get("category", "other"),
                        keywords=faq.get("keywords") or [],
                        priority=faq.get("priority", "medium"),
                        status=faq.get("status", "active"),
                        usage_count=int(faq.get("usage_count") or 0),
                        created_at=faq.get("created_at"),
                        updated_at=faq.get("updated_at"),
                    ))
                    total += 1

        await session.commit()
        return total
