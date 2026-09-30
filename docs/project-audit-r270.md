# 全项目审查报告 · r270

> 审查对象：`D:\ai\eCommerce`（跨境电商 AI SaaS）
> 规模：后端 **433 个 .py / 58,525 行**（其中 `tests/` 52,713 行）· 前端 **188 个 .vue+.ts / 67,974 行** · 25 个业务模块 · 28 条前端门禁
> 方法：5 路并行深挖（后端核心／AI 编排／业务模块／前端／测试与工程化）→ 逐条回读源码复核 → 关键项用 AST / 全量扫描二次验证
> 图例：**★ 已亲自验证**（我回读了源码或跑了脚本，可直接复现）· ○ 待复核（审查者报告，行号可信但未逐条复现）

---

## 一、结论摘要

工程质量**显著高于同类项目**：门禁密度高、判据沉淀成体系（`MEMORY.md` 百余条）、测试代码量超过业务代码、大量"假门禁/静默退化"的历史教训已被修掉。

但审查暴露出**三类系统性问题**：

| # | 问题类别 | 一句话 | 严重度 |
|---|---|---|---|
| 1 | **代码正确性** | 3 条 P0：跨租户越权读、前端**把写失败伪装成成功**、失败回退假数据 | P0 |
| 2 | **护栏守错对象** | 多条门禁守的是"用了哪个函数 / 配了什么值"，而**风险点并不在那里** | P1 |
| 3 | **三态边界不清** | 演示态／真实态／降级态的行为差异不被界面表达 ⇒ 用户无法分辨"真数据 / 兜底数据" | P1（业务） |

分级计数：**P0 × 3 · P1 × 18 · P2 × 24**（P2 按类归并）。

---

## 二、P0 问题（3 条，建议立即处理）

### P0-1 ★ 读路径店铺作用域：4 个端点缺 `else` 分支 ⇒ 缺 `X-Shop-ID` 即可跨租户读

**位置**（形态完全一致，四处）：
- `backend/modules/assets/router.py:88-97` `GET /assets/{asset_id}`
- `backend/modules/products/router.py:128-137` `GET /spus/{spu_id}`
- `backend/modules/products/router.py:250-259` `GET /skus/{sku_id}`
- `backend/modules/monitors/router.py:63-72` `GET /monitors/{monitor_id}`

**现象**：
```python
q = select(MonitorRecord).where(MonitorRecord.id == monitor_id)
if shop_id:                       # ← 缺头时 shop_id=None ⇒ 这一支整个不进
    q = scoped(q, MonitorRecord, shop_id)
r = (await session.execute(q)).scalar_one_or_none()
if not r: raise HTTPException(404, "监控记录不存在")
```
即「按主键查到就返回」，**作用域过滤被跳过**。

**为什么这是可达的（完整证据链）**：
1. `core/tenant/middleware.py:153-154` 明写契约：**读方法返回 None，由端点自己回空列表**。
   同文件 `:177-182` 给出的正确范例是 `if shop_id: ... else: return {"items": [], "total": 0}`。
2. 400 守卫**只对写方法生效** —— `middleware.py:231-237`：
   `if require_for_write and request.method.upper() in WRITE_METHODS: raise 400`。
3. 但 `core/tenant/scoping.py:25-29` 论证「`if shop_id:` 为空时返回全部店铺**在当前不可达**」，
   使用的理由正是**那个只对写方法生效的 400**。⇒ **论证前提错误**，可达性结论不成立。
4. 反证：`knowledge_base/router.py:49-50` 写了 `if not shop_id: return {空}` —— 说明作者知道要这么做；
   上述 4 个端点**漏了**。
5. ID 可枚举：`asset-<UTC毫秒>`（`assets/router.py:103`）、`spu-<毫秒>`（`products/router.py:143`）、
   `sku-<毫秒>`（`:265`）—— 毫秒时间戳可暴力枚举。

**影响**：任一持有合法凭据的用户（生产环境亦然）不带 `X-Shop-ID` 请求上述端点，即可读取**其它租户**的素材 / 产品 / SKU / 监控记录。属 OWASP API #1（BOLA）在读路径的完整形态。

**门禁为什么没拦住**：`tests/test_shop_id_guard.py:122 EXPECTED_STRICT_MODULES` 只断言
「这些模块 **import 了**严格版依赖」，**不检查每个读端点是否处理了 `shop_id=None` 分支**。
⇒ 门禁守的是 import 形态，风险点在行为分支上——**守错了对象**。

**建议**（取其一，并补门禁）：
- 四条统一改为 `scoped()` 无条件过滤（`None ⇒ col IS NULL ⇒ 0 行`，安全失败方向），或补 `if not shop_id: return 404`；
- **补一条反向注入门禁**：扫所有 `Depends(get_current_shop_id)` 的 **GET** 端点，
  断言「函数体内要么无条件 `scoped()`，要么存在 `not shop_id` 提前返回」——当前扫描结果：17 个 GET 端点中 4 个不满足。

---

### P0-2 ★ 前端把「写失败」伪装成成功：新增失败时本地伪造记录并 `return` 成功

**位置**：`frontend/src/stores/productLibrary.ts:556-591`（`addSpu`）

**现象**：
```ts
try {
  const created = await createSpu(data)     // 真入库
  spus.value.unshift(created); return created
} catch (e) {
  console.warn('[ProductLibrary] 新增 SPU 失败，本地兜底', e)
  const newSpu: Spu = { id: `spu-${Date.now()}`, /* …全部字段来自入参… */ }
  spus.value.unshift(newSpu)                // ← 列表显示"新增成功"
  return newSpu                             // ← 上游据此继续走成功分支
}
```
同文件 `:617-630`（新增 SKU）、`:687+`（`promoteToSpu`）、`:808+`（新建分组）同型。
`frontend/src/stores/assetLibrary.ts` 亦需同口径排查。

**影响**：这是**最伤用户信任的一类缺陷**——
- 界面显示保存成功，数据库里没有 ⇒ 用户刷新或换设备后"**数据凭空消失**"；
- 调用方拿到"成功"返回值继续往下走（如再加子 SKU、再挂分组），制造出更多不存在的数据；
- 失败原因只进 `console.warn`，界面**零提示**，故障表现为"随机丢数据"，不可诊断。

**建议**：`catch` 分支改为**抛错 + 写错误态**（`loadError` / `ElMessage.error`），让调用方与用户都知道失败；
mock 兜底**仅在 `DEMO_MODE` 为真时**启用，且必须在界面常驻标注"演示数据"。

---

### P0-3 ★ 前端读失败回退假数据：非演示模式同样生效，界面无任何标记

**位置**：
- `frontend/src/stores/productLibrary.ts:545-548`（`catch → spus/skus = [...MOCK_SPUS/MOCK_SKUS]`）
- `frontend/src/stores/assetLibrary.ts:326-328`（`catch → items.value = [...MOCK_ASSETS]`）

**现象**：catch 内**无 `DEMO_MODE` 判定、无错误态**，直接灌入 mock：
`MOCK_ASSETS` 形如 `{ id: 'asset-000', name: '便携加湿器 - 白底主图', url: '/mock/products/B0CXXXX001.png' }`——
含**假 ASIN、假产品名**。两个页面全文无 mock/演示提示。

**影响**：任意一次 500 / 超时 / 网络抖动，产品库与素材库会**静默显示假产品、假 ASIN、假价格**，
与真实数据完全同形。用户据此做选品 / Listing 判断 ⇒ 直接命中老板已明确表达过的原则
（**「空状态优于虚构默认」**）。切店铺时若 `reloadLibraries()` 失败，旧店铺真实数据会被假数据整体替换。

**建议**：与 P0-2 同一改法——**保留旧值 + 错误横幅 + 重试**（安全失败方向），mock 仅演示态可用。

---

## 三、P1 问题（18 条）

### 安全与数据归属

| # | 位置 | 问题 | 备注 |
|---|---|---|---|
| 1 | `modules/aigc_media/job_service.py:326-327` + `router.py:689-696` | ★ `list_jobs` / `get_job` 的 **docstring 承诺「仍按 shop_id 收敛」，实现里根本没有 shop_id 参数**；匿名态（`user_id=""`）所有任务互相可见（含 `include_result` 的结果体与 `/static` 素材链接） | 签名即事实：文档承诺了不存在的收敛 |
| 2 | `modules/amazon_sp/data_sources/sp_api_source.py:192` | ★ `fetch_credentials(store_id)` **收下 store_id 却不用**，改读全局 `config.spapi_*`；而 `db_model.py:38` 明写"每店铺一条凭证"、表有 `store_id` 唯一外键 ⇒ **多店铺数据串台且无报错** | 多租户卖点在数据源层不成立 |
| 3 | `modules/amazon_sp/db_model.py:49-56` | `access_token` / `refresh_token` 是普通 `Text`，注释自承"应加密"但无实现；项目**已有** `core.security.credentials.encrypt_credentials`（`enc:v1:` 前缀）却绕开 | 当前无写入点，属"尚未通电的危险线路" |
| 4 | `modules/stores/router.py:404,415` | 费率模板接口**无账户维度、无鉴权参数**，写进程全局 dict ⇒ 任一用户新增的模板对所有租户可见可用（可篡改他人利润口径）；且**重启即丢**但返回 201 | ○ |
| 5 | `modules/stores/router.py:785` | `POST /stores/profit/calculate` 用 `X-Store-ID` 直取全量内存、**不调** `_ensure_store_access`；404/200 差异构成店铺存在性 oracle | ○ |

### 必错（运行时一调就 500）

| # | 位置 | 问题 |
|---|---|---|
| 6 | ★ `modules/customer_service/router.py:140,245` | 以**类**身份调用 `CustomerServiceService.get_cs_agent()`，但该函数是**模块级**的（`service.py:90`），类中无此方法。**AST 复核：类方法列表 = [chat, stream_chat, search_faq, create_ticket, track_order, analyze_sentiment, get_conversation_summary, get_capabilities, quick_reply]，确认无 `get_cs_agent`** ⇒ `GET /customer-service/faq/categories`、`/health` 必抛 `AttributeError`。前端 `api/customerService.ts:80` 已封装该端点 |
| 7 | `modules/listing_generator/service.py:60,251,262`；`modules/product_research/service.py:290,295,305` | `result.data.get(...)` **未判空**（同文件 `analyze_seo:219-225` 已修过同一缺陷，**只修了一半**）；`product_research` 还会把 `None` 直接 `return` 给响应层 |

### 性能与资源

| # | 位置 | 问题 |
|---|---|---|
| 8 | `core/database.py:34-38` vs `core/config.py:212` | `create_engine()` **只传了 echo 与 pool_pre_ping** ⇒ `database_pool_size=10` / `max_overflow=20` 全项目**无消费点**（除 checkpoint 那条独立池）。业务实际用 SQLAlchemy 默认 `QueuePool(5,10)`，且无 `pool_recycle`。**改 .env 无效**，排障会指向错误方向 |
| 9 | `core/auth/accounts_router.py:281` | 循环里逐账户 `resolve_account_role`（内部 1~2 次查询）⇒ **2N+ 次查询**；超管路径返回全表，最坏情形。同函数已把店铺数/成员数批量化，唯独角色漏了 |
| 10 | `conversation/db_model.py:75,55`；`amazon_sp/snapshot_repo.py:115` | `conversation_messages.created_at`、`conversations.updated_at` **无索引**却被 `order_by(desc)` / `max()` 使用；`func.upper(col).in_(...)` 使既有 B-tree 索引失效 |
| 11 | `platforms/amazon/sp_api/auth.py:204-227` | token 刷新走**裸 httpx**（业务请求有 `call_with_retry`）⇒ LWA 一次抖动即硬失败；且 `main.py` lifespan 收尾**无** `close_spapi_client/auth()` 调用点 ⇒ 客户端与 token 缓存不释放 |

### AI / Agent 层

| # | 位置 | 问题 |
|---|---|---|
| 12 | `ai_infra/llm/dashscope_client.py:578`；`ai_infra/base_agent.py:1314` | `finish_reason` **被解析但全仓零读取** ⇒ 输出被 `max_tokens` 截断时仍标 `completed`。仓内对**预算**截断有显式状态（`budget_truncated`），唯独模型长度截断被静默吞掉 |
| 13 | `ai_infra/llm/dashscope_client.py:203-212` | `register_prompt_template` **重名静默覆盖**，而同仓 `prompt_sections.py:92-96` 的两个注册表都是**重名即 raise** ⇒ 同一机制两套判据，且覆盖的那套无日志无红灯 |
| 14 | `ai_infra/base_agent.py:1271` + `prompt_sections.py:144` | `collect_prompt_sections` 在 **每次 LLM 迭代**都被 await，各 provider 各开 DB 会话（含技能**全表扫描**）⇒ 一轮 K 次工具调用 = K×2 次查询，纯成本 |
| 15 | `ai_infra/base_agent.py:1670,1698` | 同一 `thread_id` 的并发请求**无任何串行化**（全仓无 per-thread 锁）⇒ 从同一 checkpoint 起跑、交错回写 ⇒ 丢消息/重复回复且零报错 | ○ 疑似 |
| 16 | `ai_infra/tools/hitl_decorator.py:49,115` | `timeout_seconds=3600` 只写进中断载荷，**服务端无人消费**，`resume` 也无 `asyncio.timeout` ⇒ 待审批**永不超时**（注释承诺型假门禁） |

### 前端

| # | 位置 | 问题 |
|---|---|---|
| 17 | ★ `components/TaskConfigPanel/index.vue:312-315` | 在**事件回调里**调用 `inject('clearWorkingProduct')`。Vue 要求 `inject` 在 setup 同步期执行，事件回调中 `currentInstance=null` ⇒ 恒返回 `undefined` ⇒ **「清除工作商品」的 × 点了没反应，且不报错**。全仓其余 20+ 处 `inject` 都在 setup 顶层，唯此一处例外 |
| 18 | `views/Workspace.vue:604-605` vs `:646-651`；`composables/useSpeechInput.ts:99,148`；`AIGCMediaResult.vue:567`；`TaskConfigPanel/configs/ListingBoard.vue:224,228` | **资源泄漏 4 处**：Workspace 注册 6 个监听只移除 4 个（两条是匿名函数，**永远无法移除**，每次登出重登叠加）；`ChatPanel/index.vue` **无任何生命周期钩子** ⇒ 切走视图后**麦克风识别仍在跑**并回调已卸载组件；两处定时器无 `onUnmounted` 清理 |
| 19 | `stores/productLibrary.ts:536`、`assetLibrary.ts:318`、`monitorPool.ts:315` | **请求瀑布**：分组接口与主列表无依赖，却串在一次 RTT 之后 |
| 20 | `KnowledgeBase/ProductLibrary.vue:1164`、`AssetLibrary.vue:734` | **重复请求**：Workspace 首屏已拉过，组件 `onMounted` 又无守卫地拉一次。同目录另外 5 个库都有 `ensured` 一次性标记（`knowledge.ts:214` 等），**只有 product/asset 两个 store 没有** |
| 21 | `components/ChatPanel/results/AIGCMediaResult.vue:521`；`views/Workspace.vue:603` | 事件名**无唯一真源**（11 个裸字符串散落 11 文件），且已存在**两条静默路径**：`asset-library-updated` **零监听**、`monitor-launch-analysis` **零派发**（死监听器） |

### 工程化

| # | 位置 | 问题 |
|---|---|---|
| 22 | `docker-compose.yml:66,71,133` | **PostgreSQL 明文弱口令 `123456` + `ports: "5432:5432"`（未绑 127.0.0.1 ⇒ 等于 0.0.0.0 对全网开放）**，`DATABASE_URL` 同文件硬编码同一口令；`.github/workflows/ci.yml:68` 复用。README 把 compose 定位为"一键部署"⇒ 照此在公网 `up -d`，**全库可被直接读写** |
| 23 | `.github/workflows/ci.yml:194-198` vs `backend/pyproject.toml:171` | 覆盖率命令**没有 `--cov-fail-under`**，阈值只在配置里（`fail_under=62`），而 CI 注释写的是 65 ⇒ 两处数值不一致 + 门禁可能退化为报表 | ○ 疑似 |
| 24 | `.github/workflows/ci.yml:196` | `--cov=core --cov=modules --cov=platforms --cov=ai_infra --cov=main --cov=worker` —— **漏了 `--cov=models`**（`models/` 703 行真实 schema）⇒ 它 0% 覆盖时总覆盖率照样达标 |
| 25 | `backend/requirements.txt:25,26,31` | **`langchain-core` / `langgraph` 零版本约束**（无任何说明符），`langgraph-checkpoint-postgres>=3.0` 无上界；全文件 24 行 `>=` 裸下界、无 lockfile/无 hash。而项目自身把 langgraph checkpoint 当作记忆持久化硬依赖 ⇒ 上游一次 minor 变更即可让长期记忆静默失效 |

---

## 四、P2 问题（按类归并）

**业务真实性（与"假数据冒充实测"同源）**
- `modules/product_research/service.py:52-54,95-121` —— **蓝海挖掘结果全部来自 mock 池**（`# TODO: 接入真实数据源`），却照常输出 `analysis_summary` / `premium_count`，**无 `data_status`/`degraded` 标注** ⇒ 用户以为是对真实市场的分析。
- `modules/product_research/service.py:154-158` —— 筛选结果为空时**静默用"ROI 最高前 5"冒充匹配结果**，而响应仍回显 `filters_applied.min_roi=50%` ⇒ 条件与结果口径分裂。
- `platforms/shopee/client.py:33,40,44,90` —— Shopee 适配器是**空骨架**（`return []` / `None` / 全 0），但 `platforms/base.py:339` 的工厂会返回它 ⇒ 调用方把"未实现"当"真的没有该商品"。对比 `platforms/tiktok/client.py:35` 用 `raise NotImplementedError`（显式失败，正确范式）。
- `platforms/amazon/sp_api/client.py:490,530,542` —— 报告异常**吞掉返回空**；`health_check` 吞异常返回 False。

**孤儿 / 装饰性端点（8 个，前端 0 引用）**
`ad_analysis/router.py:226,235,245`（capabilities / quick/diagnose / quick/anomalies）、`aigc_media/router.py:632`（health，其中 `tools_count: 8` 与能力列表是**硬编码**）、`competitor_intel/router.py:50,103,158,191`（其中 `/intruders/{category}` 指向的 `detect_intruders` 是 `status="unsupported"` 空壳）。

**一致性与并发**
- `modules/monitors/service.py:263-288` —— `upsert_monitor` **先查后插非原子**，并发撞 `uq_monitor_shop_asin` 抛 IntegrityError 未捕获 ⇒ 500（同仓 `aigc_media` 用 `ON CONFLICT DO NOTHING` 是对的）。
- `modules/billing/models.py:44,85,123` —— **金额与 LLM 成本用 `Float`**，利润计算（`product_research/service.py:231-237`）也按 float 四则运算 ⇒ 对账/退款场景存在分位误差。
- `modules/products/router.py:116-125` —— `list_spus` **无分页无 LIMIT**，`total=len(items)`；同模块 `list_skus` 已走 `query_library` 内核 ⇒ 两个列表口径不一致。
- `products/router.py:141`、`listing_generator/router.py:143`、`platform_rules/router.py:52`、`knowledge_base/router.py:60`、`candidates/router.py:116` —— 写端点用**裸 `dict` / 裸标量 query**，pydantic 未收敛（前端注释 `api/listingGenerator.ts:23` 已记录该不一致）。

**AI 层残余**
- `ai_infra/llm/dashscope_client.py:46,54` —— `estimate_tokens` 注释称"宁可高估"，实际 `chars/1.5` 是**低估**（中文尤甚），而它是上下文裁剪与预算判定的唯一估算源。
- `ai_infra/llm/dashscope_client.py:477-479` —— `structured_chat` JSON 解析失败返回 `{"raw_text": ...}`，与成功结果**同形**；`product_research/agent_product_research.py:1448` 据此标 `enhanced=True`（同仓 `platform_rules/ai_split.py:85` 做了 `"raw_text" in data` 检查 ⇒ **同一约定两份实现，漏的那份静默退化**）。
- `modules/competitor_intel/agent_competitor.py:553` —— 意图兜底写成 `"compare"`，而 `_INTENT_ROUTES` 里**没有 `"general"`** ⇒ `:990` 的"对话类纯 LLM 流式"分支**永不可达**；工具环路不可用时**任何闲聊**都返回"至少需要2个竞品进行对比"。
- `modules/product_research/agent_product_research.py:1133` —— 流式路径**未用 `chunk_text()`**（唯一实现 `ai_infra/sse.py:158`，专治 content 为 list），分段列表会**静默变空答复**并掉进闲聊兜底。其余 5 家 Agent 都已走 `chunk_text`。
- `ai_infra/base_agent.py:1413-1415` —— 每次迭代重新 `bind_tools`，无缓存（工具多时重复序列化 schema）。
- `modules/product_research/agent_product_research.py:2503` —— `_process_query` 保留 `save_candidate` **零审批直写**分支，当前不可达但**无门禁钉住**，一旦分流条件变动即静默恢复直写。
- `modules/secretary/intent_shortcut.py:58-80,195` —— 业务动词按**裸子串**匹配（含单字"写/做/算/找"），与同文件 `:55-57` "必须按词边界"的注释矛盾（失败方向安全，但零 LLM 加速失效）。

**前端**
- **超大 SFC 26 个**（>700 行）：`ProductLibrary.vue` 2068、`PlatformRules.vue` 1916、`SkillManager.vue` 1291、`BlueOceanResult.vue` 1205、`AssetLibrary.vue` 1170、`Workspace.vue` 1139 … 最该拆 `ProductLibrary.vue`（同时承担表格/抽屉/4 个弹窗/分组 CRUD/竞品绑定/900 行样式；已拆出 3 个 modal，模式已验证）。
- `components/ChatPanel/index.vue:52` + `composables/useChatOrchestrator.ts:155` —— 消息列表**全量渲染无虚拟滚动**，且 `watch(messages, …, {deep:true})` 使**每个流式 token 都深比较整棵消息树**；50 条工具结果卡 ≈ 4000–7500 DOM。
- `api/request.ts:313-367` —— 五个方法泛型默认 `T = any`；`stores/shop.ts:172-173` 用 `as unknown as Shop[]` 双断言抹平结构差异（`api/accounts.ts:133-136` 注释记录了同型事故：`res.id` 恒 undefined 且无异常）。
- `composables/chat/useChatRuntime.ts:116` —— 「当前选中工具」在编排层另存一份（`useChatEventBridge.ts:172` 只写不读），UI 真源是 `Workspace.vue:316` 的 `currentSelectedTool` ⇒ **状态双份**，当前无可见 bug 仅因镜像没人读。

**工程化**
- `.githooks/*` 依赖本地 `core.hooksPath`（**不随仓库传播**），README/docs **无任何启用说明** ⇒ 新克隆后 pre-commit **完全不执行**，而它是密钥/大文件进历史前的唯一拦截点。且其 env 规则与现状矛盾（拦 `.env.development`，但该文件**已入库**且只含 `VITE_DEMO_MODE`）。
- `.github/workflows/ci.yml:343-350` —— 敏感文件检查**硬编码只校验 2 条路径**，不覆盖 `*.pem`/`*.key`/`backend/.env.production`，无高熵扫描。
- `docker-compose.yml:119,244` —— 4 处 `image: *:latest`；`frontend.depends_on: [backend]` **短语法无 `condition: service_healthy`**（backend 镜像已有 HEALTHCHECK）⇒ 冷启动窗口 `/api` 全 404；各服务**无 `mem_limit`/`cpus`**（AIGC 出图可打爆宿主）。
- `start-backend.bat:11` —— **硬编码本机 conda 绝对路径** `D:\work\anaconda\anaconda3\envs\reactAgents\python.exe`（不可移植）。
- 仓库残留：根目录 `50`（0 字节）、`frontend/_win*.txt`（约 92 KB，计 5 个）**未被 .gitignore 覆盖**；未跟踪文件共 228 个。
- 门禁重复：`frontend/scripts/check-hitl-approval.cjs:162-166` 把 HITL 四档 `['accept','reject','edit','response']` **写死**，不读后端 Literal ⇒ 后端新增第 5 档时前端门禁**不会红**（`backend/tests/test_frontend_api_field_contract.py:16-17` 已承认该重叠）。
- 少量假绿残余：`backend/tests/test_import_boundaries.py:297` 的 `assert t is not None`（`t` 由 `ast.parse` 生成，**恒真**）；`test_pytest_guardrails.py:144` 缺包时 `return`（应 `pytest.skip`）；`test_agent_budget.py:163`、`test_agent_plan.py:232` 的 `pytest.raises(Exception)` 过宽。
  **说明**：AST 全量扫描 117 个测试文件，**未发现系统性假绿**（无 `assert True`、无 `except: pass` 包断言、无断言函数仅 10 个且均为合法"不抛即通过"型）。整体假绿率**远低于**一般项目。

---

## 五、业务层面建议（3 条主线）

### 5.1 把「数据真实性分级」做成横切契约（最高优先）

现状：**同一份代码在不同配置/故障下产出三种数据，界面完全不区分**——
① 真实数据 ② 降级/mock（蓝海挖掘、Shopee 空骨架、SP-API 空结果）③ 兜底假数据（前端 4 处 mock 回退 + 写失败伪造）。
而仓内已有**正确范式**（`review_analyst`/`ad_analysis` 的 `no_data` 显式空状态、`budget_truncated` 显式状态），只是没有推广。

建议：所有取数/生成端点统一返回 `data_status ∈ {real, degraded, mock, empty}`（或复用既有 `degraded_reason`），
前端对非 `real` 一律**常驻角标 + 说明**。这一条同时收口 P0-2 / P0-3 / 蓝海 mock / Shopee 空骨架 / `_apply_filters` 放宽冒充 —— **一处契约解决五类问题**。

### 5.2 多租户是卖点，但链路仍有多处「单租户假设」

已实证：SP-API 全局单套凭据（`sp_api_source.py:192`）、费率模板进程全局表（`stores/router.py:404`）、
匿名任务混池（`aigc_media/job_service.py`）、4 个读端点缺作用域。
⇒ 一旦真实上多店铺运营，这些点会**成片暴露且都不报错**。
建议：做一次「多租户就绪度」专项——把所有 `config.*` 全局凭据、模块级可变容器、无 shop 归属的查询逐条列出并收敛。

### 5.3 护栏质量很高，但需要一次「门禁守的对象 = 风险点」对账

本仓门禁的**数量与深度远超同类项目**，但审查发现至少 5 处**守错对象**：
| 门禁 | 守的是 | 风险实际在 |
|---|---|---|
| `test_shop_id_guard.py:122` | 模块 **import 了**严格依赖 | 读端点有没有处理 `shop_id=None` 分支（P0-1） |
| `pyproject.toml:171` + CI | 配置里写了 `fail_under` | 命令行有没有 `--cov-fail-under`（P1-23） |
| CI `--cov` 列表 | 6 个顶层目录 | **漏了 `models/`**（P1-24） |
| `check-hitl-approval.cjs:162` | 前端写死的 4 档 | 后端 Literal 实际取值（P2） |
| `core/config.py:212` | 配置项**声明**了池大小 | `create_engine` 有没有**消费**它（P1-8） |

⇒ 建议立一条判据并落成门禁：**「每条门禁必须能回答『哪一处改动能把它打红』，且注入点必须在风险路径上」**
（仓内已有此判据的雏形，只是未覆盖上述 5 处）。这也是投入产出比最高的一项。

---

## 六、建议行动顺序

| 批次 | 内容 | 理由 |
|---|---|---|
| **第一批（立即）** | P0-1 四端点补作用域 + 补反向注入门禁；P0-2 / P0-3 改为「保留旧值 + 错误态」；P1-6 `get_cs_agent` 两处改模块级调用 + 补回归用例 | 越权与假数据是唯一"会被用户看见且无法解释"的两类 |
| **第二批（本周）** | P1-22 compose 弱口令 + 绑 127.0.0.1；P1-25 依赖加上界 + lockfile；P1-8 连接池参数落地；P1-7 `result.data or {}`；P1-12 `finish_reason` 消费 | 安全基线与"配置声称 ≠ 实际生效" |
| **第三批（按需）** | 5.1 数据真实性契约 → 收口 5 类假数据；5.3 门禁对账；P1-2/3 SP-API 多店铺凭据与加密 | 需要产品侧确认口径后再动 |
| **第四批（技术债）** | 前端 4 处泄漏 / 事件名真源 / 超大 SFC 拆分 / 虚拟滚动；孤儿端点决定接通或下线；业务模块一致性（N+1、索引、金额 Decimal） | 无即时风险，随迭代顺手还 |

---

## 七、附：本报告的验证方法（可复现）

- **AST 复核**：`customer_service` 类方法清单（确认无 `get_cs_agent`）；GET 端点作用域守卫扫描（17 个 GET 端点、4 个缺空分支）。
- **全量扫描脚本**：遍历 `modules/**/router.py` + `core/**/router.py`，对每个路由函数提取路由方法、依赖默认值、`if <name>:` 真值守卫及其有无 `else`，筛出「GET + 条件式过滤 + 无 else」。
- **逐条回读**：P0 全部、P1 的 6/7/8/17/18/22/25 均已回读源码确认。
- **未复现项**：并发竞态（P1-15）与覆盖率门禁传导（P1-23）标注为疑似，需运行期验证（建议各补一条反向注入）。
