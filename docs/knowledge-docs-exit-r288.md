# `knowledge_docs` 出口落地（第 288 轮 · 老板拍板 B 方案）

> 老板指令：「走 B，演示素材你按通用电商政策写，拆出的条目默认草稿、人工确认后再进」。
> 本文是落地记录；方案对比见 `docs/knowledge-docs-exit-plan-r287.md`。

---

## 一、做了什么

`knowledge_docs` 此前**全库 0 行**，且文档没有出口（只能被列出来看一眼，不参与任何检索）。
本轮把这条链接通：

```
文档正文 content
   ↓ AI 拆分（ai_split_faq.split_faqs_from_doc）
话术条目（status=draft）      ← 落库即草稿，**不进检索**
   ↓ 人工确认（点「发布」）
status=active                 ← 客服 load_faq_items 只查 active
   ↓
客服检索命中
```

| # | 改动 | 文件 |
|---|---|---|
| 1 | 拆分内核（LLM 提取 + 归一 + **写死 draft** + 空正文/LLM 不可用明确降级） | `backend/modules/knowledge_base/ai_split_faq.py`（新） |
| 2 | 落草稿（服务端强制 draft + 同 kb 同问题判重）、发布（只转 draft） | `backend/modules/knowledge_base/service.py` |
| 3 | 两个端点：`POST /docs/{doc_id}/ai-split-faq`、`POST /faqs/publish` | `backend/modules/knowledge_base/router.py` |
| 4 | 演示素材：5 篇通用电商政策（带正文）+ 27 条**逐条对照正文**的预拆草稿 | `backend/scripts/seed_knowledge_docs.py`（新） |
| 5 | 改掉假注释（「RAG 切片检索的输入源」→ 如实） | `backend/modules/knowledge_base/db_model.py` |
| 6 | 前端：文档项「AI 拆成话术」按钮 + 草稿徽标 + 单条/一键发布 | `api/knowledge.ts`、`stores/knowledge.ts`、`FaqKnowledgeBase.vue` |
| 7 | 23 条测试（含分类口径防漂移、作用域形态判据、反向注入） | `backend/tests/test_kb_doc_ai_split.py`（新） |

---

## 二、三个关键决策

### ① 为什么「默认草稿」要写在**后端 normalize 里**，而不是靠前端传 status

`normalize_llm_faqs` **写死** `status="draft"`，LLM 返回的 status 一律不采纳；
`service.create_faq_drafts` 再强制一次（双保险）。

理由不是流程洁癖：LLM 会把文档里的**内部口径**（成本价、供应商、
只对某站点生效的承诺）写进 answer。草稿不进检索 ⇒ 人工确认前这些内容
**不可能**被发给买家。靠前端传值 = 把这道闸交给「调用方记得传」。

### ② 为什么连「预拆草稿」一起灌，而不是只灌文档等用户点按钮

LLM 在本机环境未必可用（第 287 轮实测：一批用例因 LLM 不可用而环境性变红）。
只灌文档的话，LLM 不可用时这条链**整条演示不出来**，「草稿 → 发布 → 命中」
这段也无法验证。27 条草稿由我**逐条对照正文**手写，每条都能在对应文档里
找到依据 —— 不是"为了让页面有数据"编的默认值，而是把「AI 拆分会产出什么」
预先物化。全部以 draft 落库，**不改变客服现有的回答内容**。

### ③ 为什么不做 platform_rules 那套三层去重

规则条目有**时效**（同一条规则会出新版 ⇒ 需要「重复/更新」二分类）；
话术条目没有 —— 同问不同答是**错误**，不是"新版本"。
⇒ 只做「同 kb 下 question 完全相同则跳过」，判定权交回给人。

---

## 三、验收（真库实测，非推断）

```
[0] knowledge_docs 行数 = 20              （4 店 × 5 篇）
[1] faqs 按(店铺,状态) = 每店 active 18 / draft 26
[3] 发布前：客服可见 18 条，含上述草稿 0 条（应为 0）   ← 草稿确实不进检索
[4] 发布 '退款多久能到账？' → published=1
[5] 发布后：客服可见 21 条（+1），含该条=True          ← 发布后进入检索
[6] search_knowledge_base('退款多久能到账？') 命中 3 条  ← 客服能检索到
[7] 重复发布 → published=0，skipped=[status=active]   ← 不重复发布
```

灌库结果：文档新建 20 / 草稿新建 104（27×4 里有 4 条撞上库里已有的同问题，已跳过）。

---

## 四、素材清单（通用电商政策，老板授权由我撰写）

| 文档 | 条数 | 覆盖 |
|---|---|---|
| 退货与退款政策 | 6 | 30 天无理由、运费归属、退款时效、优惠券、破损、退款失败 |
| 物流与配送时效 | 6 | 发货时效、三段配送时效、查轨迹、轨迹不更新、清关、改址 |
| 质保与售后维修 | 5 | 12/6 个月质保、申请流程、维修时效、换新、运费归属 |
| 尺码与商品规格 | 5 | 服装/鞋类选码、换码、色差、赠品 |
| 支付、发票与关税 | 5 | 支付方式、优惠券叠加、开票、抬头重开、关税 |

**下一步**：这些是通用口径。若要接真实业务，替换成老板自己的退货/物流/质保
政策文本即可 —— 直接在文档管理面板上传（txt/md 会自动带正文），
或改 `scripts/seed_knowledge_docs.py` 里的 `DOCS`。

---

## 五、测试覆盖了什么（`tests/test_kb_doc_ai_split.py`，23 条）

- **草稿强制**：LLM 给 active/archived/空 五种 status 都被覆盖为 draft
- **分类口径防漂移**：`ai_split_faq.FAQ_CATEGORY_CODES` 与
  `customer_service.faq_source.CATEGORY_LABELS` 必须恒等（两边都是 PLUGIN，
  不能互相 import，只能由测试钉住）
- **作用域**：查重与发布两条查询的语句文本必须含 `knowledge_faqs.shop_id =`
  （★ 店铺值是绑定参数，不在文本里 —— 第一版判据写 `SHOP in text` 恒假）
- **降级不编造**：空正文 / LLM 不可用 / 提取为空，三种都 `degraded=True` 且给中文 reason
- **发布边界**：archived **不复活**；「不存在」与「不属于本租户」同进 `not_found`
- **假注释已修**：断言新注释存在且旧说法消失（旧注释里刻意**不复述**旧文案）

---

## 六、遗留

- LLM 可用时，「上传自己的政策文档 → 点 AI 拆成话术」这条会走真实 LLM；
  本机 LLM 不可用时按钮会给出明确原因（`degraded` + reason），不会静默失败。
- 拆出的条目目前**不支持**「编辑后再发布」以外的批量操作（如批量删除草稿）——
  已有单条删除与批量导入，够用；不够时再补。
- 文档区空态文案已改成「上传后可一键拆成话术草稿（文档本身不参与检索）」，
  不再声称文档参与 RAG。
