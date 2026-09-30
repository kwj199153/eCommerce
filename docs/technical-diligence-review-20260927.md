# eCommerce 跨境电商 AI SaaS —— 技术尽职调查评审检查表

> 审查日期：2026-09-27　|　审查对象：`D:\ai\eCommerce`（FastAPI + Vue3 + LangGraph + PostgreSQL/Redis）
> 证据口径：**全部结论来自源码/配置实读**，每条附 `文件:行`。未找到的项明确标注「未找到」并列明搜索过的关键词，不做推测性打分。
> 评分基准：**对外商用 SaaS（多租户 + 真实付费客户）**。文末另给「内部/单租户试点」基准对照分。

---

## 0. 评分总览

### 0.1 评分图例

| 分 | 含义 |
|---|---|
| 5 | 生产就绪，且有自动化证据闭环（测试/门禁/监控三者至少二） |
| 4 | 基本到位，存在不影响主链路的小缺口 |
| 3 | 部分实现，关键环节有洞，靠约定或人工兜 |
| 2 | 有雏形，正确性强依赖开发者自觉 |
| 1 | 仅有痕迹 / 纸面配置，实际未生效 |
| 0 | 完全没有 |

### 0.2 分组得分

| # | 分组 | 权重 | 得分 | 加权 | 一句话结论 |
|---|---|---:|---:|---:|---|
| A | AI Agent 专项 | 15 | **2.6** | 39 | 架构与记忆很扎实，提示词与输出校验是硬伤 |
| B | 成本控制 | 10 | **2.2** | 22 | 计量真实，但无缓存、无金额闸门 |
| C | 可观测性 | 10 | **2.2** | 22 | 日志优秀，tracing 与告警缺失 |
| D | 多租户隔离（P0） | 20 | **3.0** | 60 | 模型清晰，但**存在 3 处实证越权** |
| E | 认证与权限 | 10 | **2.6** | 26 | JWT/RBAC 设计好，无 MFA、token 存 localStorage |
| F | 密钥与数据安全 | 10 | **3.0** | 30 | 无硬编码、无 SQL 注入；输入校验与 XSS 是短板 |
| G | 合规与法律风险 | 10 | **0.4** | 4 | **几乎空白**：无审计、无导出、无删除、无协议 |
| H | 部署运维 | 10 | **2.2** | 22 | CI 是亮点（5/5），CD/备份/告警全缺 |
| I | 质量、测试与风险 | 10 | **2.4** | 24 | 1674 用例很强，压测/熔断/风险登记为零 |
| J | 组织与工程 | 5 | **3.2** | 16 | 安全扫描入 CI 是亮点，无 PR 模板与 CODEOWNERS |
| | **合计** | **110** | **2.41** | **265** | |

### 0.3 双基准总分

| 基准 | 得分 | 判定 |
|---|---:|---|
| **对外商用 SaaS**（多租户 + 真实付费） | **48 / 100** | ❌ 不达标。9 项 P0 阻断未清 |
| **内部 / 单租户试点** | **61 / 100** | ⚠️ 可试运行。功能与工程质量高于平均，合规运维后补 |

> 两个基准差距不大的原因：本项目的**功能与代码质量**确实高于同类早期项目，扣分几乎全部集中在「多租户隔离实证越权」「合规」「运维（备份/告警/CD）」三块——这三块恰恰是「自用」时最容易被忽略、「对外商用」时最先爆炸的地方。

---

## A. AI Agent 专项（权重 15）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| A1 | **Agent 基类统一性** | 唯一基类 `ai_infra/base_agent.py:177` `BaseAgent`；8 个子类（`secretary/agent.py:145`、`ad_analysis/agent_ad.py:399`、`aigc_media/agent_aigc.py:251`、`listing_generator/agent_listing.py:215`、`product_research/agent_product_research.py:285`、`competitor_intel/agent_competitor.py:180`、`customer_service/agent_cs.py:299`、`review_analyst/agent.py:156`）；`tests/test_base_agent_unified.py:73` 钉住唯一性 | **4** | 无中心注册表：新增第 9 个 Agent 无一处代码感知；7 家用「new 裸 BaseAgent」组合式接入（`agent_ad.py:488` 等），非继承 | P2 |
| A2 | **工具调用治理** | 约 64 个工具定义 / 55 个实际绑定；HITL 审批双判据且 **fail-closed**：未声明 `metadata={"side_effects": False}` 一律进审批（`ai_infra/tools/side_effects.py:186-193`）；AST 门禁禁手写重试循环 | **3** | 无统一结果信封（成功/失败/耗时）；各模块抄了 4 份同名 `_dump()`（`ad_analysis/tools.py:55`、`customer_service/tools.py:49`、`review_analyst/tools.py:84`、`library/tools.py:169`）；工具耗时只在前端 SSE 计时（`ai_infra/sse.py:288-302`），服务端无落点 | P1 |
| A3 | **记忆管理** | 四层分离（LangGraph PG Checkpoint `core/checkpoint.py:34-60` / 会话记录 / Agent 槽位 / 长期记忆 `modules/memory/db_model.py`）；线程键 `ns:user_id:session_id`（`base_agent.py:1556`）；容量上限 `MAX_ENTRIES=60`、`MAX_PROMPT_CHARS=2000`（`ai_infra/memory/limits.py:101,110`）；淘汰按**来源权重**（manual 10 / distill 1，`limits.py:220-227`）；蒸馏有批量上限 100 + 20h 冷却（`:196,:184`） | **4** | `checkpoints` / `conversations` / `agent_session_state` 三张表**无任何 TTL、归档或清理**（搜 `retention`/`purge`/`delete(` 无命中）；`trim_history` 是读时裁剪，不释放库容 | P1 |
| A4 | **提示词版本管理** | — | **1** | **100% 硬编码 Python 字符串常量**（8 个业务 prompt：`ad_analysis/prompts.py:22`、`secretary/agent.py:39`、`memory/prompts.py:26` 等）+ import 副作用注册进内存 dict（`dashscope_client.py:200`、`prompt_sections.py:78`）；**无版本号、无历史表、无 A/B**（全仓 `prompt_version` 0 命中，21 个迁移文件 grep prompt 无输出）。改 prompt = 改代码 + 重新发版。两张注册表判据还不一致（一处静默覆盖、一处 raise） | **P0** |
| A5 | **幻觉防护 / 输出校验** | 唯一代码级 fail-closed 拒答：`product_research/context_target_gate.py:1-14`（缺作用对象直接拒答，不进 LLM）；RAG 路径有 sources/confidence（`base_agent.py:706-743`） | **1** | 无 schema 级结构化输出（`with_structured_output` 生产代码 0 命中）；JSON 解析失败**同形退化**为 `{"raw_text": ...}`（`dashscope_client.py:470-479`），下游 `agent_product_research.py:1448` 据此标 `enhanced=True`；`finish_reason` 解析了但全仓零读取（截断输出照样标 completed）；`guardrail`/`hallucinat` 全仓 0 命中；Listing / AIGC 明确「只注入不拒答」 | **P0** |

**A 组建议（按 ROI）**：① 提示词外置到 DB/文件 + 版本号字段（A4）；② 最终答复加 pydantic schema 约束 + `finish_reason` 读取（A5）；③ 会话类表加归档任务（A3）。

---

## B. 成本控制（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| B1 | **Token 计量真实性** | 读真实 usage：`base_agent.py:1304-1326` 取 `usage_metadata.input_tokens/output_tokens` 并 `record_llm_usage`；自研客户端流式路径请求 `stream_options.include_usage`（`dashscope_client.py:359`）；并发行锁修复（8 并发各 +1 曾只累加到 2，`usage_tracker.py:62-88`） | **4** | 估算口径 `chars/1.5`（`dashscope_client.py:36-54`）实测是**低估**，与注释「宁可高估」矛盾 | P2 |
| B2 | **配额与限额** | 三维预算 `BUDGET_ROUTER/INTERACTIVE/STANDARD`（`ai_infra/budget.py:84-90`）；预算截断显式写 `status="budget_truncated"`（`base_agent.py:1437-1458`） | **2** | 配额**只有次数，没有 token/金额上限**（`modules/billing/models.py:45-46` 的 `llm_tokens_used`/`llm_cost_used` **只累不判**）；无租户维度（一律按 `user_id`，`usage_tracker.py:204`）；`reset_meter()` 只挂在 2 个依赖上 —— **未挂 `meter_agent_chat` 的路由，LLM 消耗 0 计费** | **P1** |
| B3 | **缓存策略** | — | **0** | **零 LLM 响应缓存、零 prompt caching、零 embedding 缓存**（`ai_infra/` 内 `cache` 唯一命中是模型实例字典 `base_agent.py:484`）；embedding 每次裸 POST（`ai_infra/rag/hybrid_engine.py:226-252`）；`collect_prompt_sections` **每次 LLM 迭代**都 await，一轮 K 次工具调用 = K×2 次 DB 查询（含技能全表扫描） | **P1** |
| B4 | **节流与并发** | IP 级限流 60/min（`core/middleware/rate_limit.py:115-204`，`config.py:650-652`）；AIGC 出图并发门 `MAX_CONCURRENCY=2` + `asyncio.Semaphore`（`image_client.py:61,233`）；上下文裁剪两档（`ai_infra/context.py:119-124`） | **3** | 限流按 IP 非按用户/租户；`rate_limit_requests_per_day=1000` 疑似未接线；无全局并发闸门 | P2 |
| B5 | **成本可见性** | `llm_calls_total` / `llm_tokens_total` 指标（`core/observability/metrics.py:233-238`）；演示身份成本照记（`usage_tracker.py:418-420`） | **2** | 见 C2：LangChain 路径的 LLM 调用**完全不进这两个指标**；无成本阈值告警、无熔断 | P1 |

---

## C. 可观测性（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| C1 | **结构化日志** | loguru 统一出口 + stdlib 拦截桥（`core/logger.py:47-119`，注释记录「16 个模块日志进不了文件」病史）；patcher 注入 `request_id`/`shop_id`/`user_id`（`:159-202`）；按天轮转 + 30 天保留 + gz（`:229-241`）；可选 JSON（`:214-215`） | **4** | 无 size 轮转 —— 实测单日 **435MB**（`backend/logs/2026-09-22.log`）；`log_json` 默认 False（`config.py:766`），生产不显式设则输出非结构化文本 | P1 |
| C2 | **指标与监控** | 自研 Prometheus 端点 `/metrics` 带 Bearer 鉴权（`main.py:312-340`，生产未设 token 启动期硬拒 `config.py:264`）；11 个指标含 `dependency_up`、`quota_rejections`；路径归一化防基数爆炸（`metrics.py:47-60`）；`/health` 真探活（PG 执行 `SELECT 1`、Redis `ping` 1s 超时，`main.py:196-265`），Redis 挂返回 `degraded` 而非判死 | **3** | ⚠️ **盲区**：`LLM_CALLS`/`LLM_TOKENS` 全仓只 4 个调用点，全在 `dashscope_client.py:150-154`；`BaseAgent` 走 LangChain `ChatOpenAI`（`base_agent.py:1294-1296`）**一次都不 +1** ⇒ 8 个 Agent 的主链路在 LLM 指标上完全不可见 | **P1** |
| C3 | **链路追踪** | — | **1** | 无 LangSmith / Langfuse / OTel（全仓含 `.env.example`、`requirements.txt` 0 命中）；LangChain `callbacks` / `BaseCallbackHandler` 全仓 0 命中 —— 标准挂点完全未接线；无 span/trace 概念 | P1 |
| C4 | **失败追踪与告警** | 重试有可观测性（`image_client.py:248-252` 退避 warning）；Sentry 可选接入，缺包显式 WARNING 不静默降级（`core/observability/sentry.py:46-51`） | **1** | **无任何告警**：无 Alertmanager / 告警规则 / 通知渠道（grep `alert|告警|webhook|钉钉|PagerDuty` 命中全为业务代码）；无 `prometheus.yml` / Grafana dashboard；Sentry `traces_sample_rate` 默认 0.0 | **P0** |
| C5 | **工具级可观测** | 前端 SSE 有 `run_id` 计时（`sse.py:288-302`） | **2** | 服务端无工具耗时/成败的结构化记录（见 A2） | P2 |
| C6 | **慢查询** | — | **0** | 无 `log_min_duration_statement` / `pg_stat_statements` / `statement_timeout`，compose 的 postgres 无 `command:` 覆盖 | P2 |

---

## D. 多租户隔离（权重 20 —— SaaS 重中之重）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| D1 | **隔离模型** | 共享库 + 共享 schema + 行级隔离。**归属唯一真源 `account_id`**（`core/stores/models.py:121-125`，注释明写「`tenant_id` 只剩历史兼容，不参与任何判定」）；业务表按 `shop_id` 分区（≥16 张，外键 `ON DELETE RESTRICT`）；团队表 `accounts`/`account_members`（`core/identity/account_models.py:124,164`） | **4** | 三层租户语义（tenant_id / owner_id / account_id）并存，`tenant_id` 是死列 | P2 |
| D2 | **隔离强制性** | 收口真源 `core/tenant/scoping.py`（`SHOP_SCOPE_ATTR="shop_id"` :44，`scoped()` 无条件挂 → 缺头时 `col IS NULL` → 0 行 → 404，**安全失败方向**）；AST 门禁禁手写过滤（`tests/test_tenant_scoping.py:21`） | **2** | **无 PostgreSQL RLS、无 SQLAlchemy 事件钩子自动注入 where**（`event.listens_for` / `with_loader_criteria` / `RLS` 全仓 0 命中）⇒ 隔离完全靠「每个调用点自己写」+ 事后门禁 | **P1** |
| D3 | **入口归属校验** | `get_current_shop_id` 三步：空守卫 → 认证 → **授权**（`core/tenant/middleware.py:214-301`）；不通过统一 **403 而非 404**（避免 ID 枚举）；写方法缺 `X-Shop-ID` 硬 400（`:231-237`）；演示档与超管档分支清晰 | **5** | — | — |
| D4 | **越权实证（IDOR）** | — | **2** | ⚠️ **3 处读端点退化为无租户过滤**（带任意有效 token、不带 `X-Shop-ID` 即可按 id 读任意租户数据）：① `platform_rules/service.py:315-320`（`if shop_id:`）② `knowledge_base/service.py:482-486`（`scoped_if` 假值明确跳过滤，见 `scoping.py:86-88`）③ `candidates/service.py:462-471`（`if shop_id:`）。另 **35 处 `if shop_id:` 条件式过滤**是同一缺陷的存量面。**同项目内 `products/router.py:127-133`、`assets/router.py:89-95`、`monitors/router.py:64-69` 用的是无条件 `scoped()`** ⇒ 属不一致而非有意设计 | **P0** |
| D5 | **隔离测试** | `test_account_store_hierarchy.py`(6) + `test_tenant_scoping.py`(6, AST) + `test_voice_clone_isolation.py`(48) + `test_shop_id_guard.py`(14) + `test_conversation_ownership.py`(18)；`scripts/check_tenant_isolation.py` 10 条用例（含「不存在店铺 403 而非 404」） | **4** | 该脚本只打 `get_current_shop_id*` 两个依赖函数，**不打业务端点** ⇒ D4 的 3 处 service 层退化不在它视野内 | P1 |
| D6 | **历史 P0 已修（留档）** | `tenant_context` 未校验注入通道曾致跨租户写入，该设施已物理删除（`core/tenant/middleware.py:28-34`） | — | 说明此类缺陷在本项目**真实发生过**，D4 不是理论风险 | — |

---

## E. 认证与权限（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| E1 | **认证机制** | JWT（python-jose HS256，含 `jti`）；access/refresh 校验分离，`decode_expired_token` 仅诊断禁用于授权（`core/auth/jwt_handler.py:214-262`，注释记录「过期 refresh token 曾能换出全新 token 对」事故）；撤销两级（jti 黑名单 + `token_version` 整批失效） | **4** | — | — |
| E2 | **密码安全** | bcrypt 直接调用，`rounds` 生产强制 ≥12（`core/identity/router.py:106-127`、`config.py:250-255`） | **3** | 密码最小长度**仅 6 位**（`router.py:39,198`） | P2 |
| E3 | **MFA** | — | **0** | 全仓 `mfa|totp|2FA|authenticator` **0 命中**。邮箱一次性 token 只用于验证/重置，非二次因子 | P1 |
| E4 | **RBAC** | 权限矩阵唯一真源 `ACCOUNT_PERMISSIONS`（`core/identity/account_models.py:92-105`），`role_allows` 未知能力名**一律拒绝**（fail-closed）；依赖注入 `require_account_permission`（`core/auth/accounts.py:730-793`）；建店/转移双门校验 | **4** | `account_id` 为空的存量店铺跳过能力门（`modules/stores/router.py:342-347`），回填未完成前存在绕过路径 | P2 |
| E5 | **前端 token 处理** | 刷新有**并发锁**（`frontend/src/api/request.ts:107-120`）只重试一次；401 清态并清掉上一身份的 `current_shop_id`（`:265-273`）；刷新走 JSON body（注释记录曾走 query 泄漏到 access log 的 P0）；本机免密走 httpOnly+SameSite Cookie + 服务端 Fernet 托管（`core/identity/device_router.py:134-152`） | **2** | access/refresh token **存 localStorage**（`frontend/src/stores/user.ts:65-71`）⇒ XSS 即可窃取；与 F6 的未转义 `v-html` 叠加可升级为账户接管链 | **P1** |
| E6 | **API Key 管理** | 只存 sha256 + 掩码，明文仅创建响应出现一次（`core/identity/users_router.py:358`、`auth_models.py:163-165`）；生产启动硬拒绝清单 9 项（`config.py:156-330`：AUTH_REQUIRED / DEMO_MODE / JWT 非占位 / DEBUG / PAYMENT_GATEWAY≠mock / bcrypt rounds / METRICS_TOKEN / 登录失败次数 / 锁定时长） | **5** | — | — |

---

## F. 密钥与数据安全（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| F1 | **密钥硬编码** | 生产代码 **0 命中**（`sk-` / `api_key=` / `secret=` 全仓扫描，仅元数据键名）；统一走 pydantic Settings 读环境变量（`core/config.py:108`，密钥字段 `:449/:463/:494/:627/:680/:800`）；`.env` 已被 gitignore，未入库 | **4** | 本地 `backend/.env` 明文落盘（行业常见）；`docker-compose.yml:133/169/220` 三处**明文数据库口令 `kevin:123456` 已入库** | **P0** |
| F2 | **敏感字段加密** | Fernet 字段加密，缺密钥直接抛错**绝不退回明文**（`core/security/credentials.py:76-100`）；落点：`stores_store.api_credentials`（`core/stores/models.py:140-142`）、设备 refresh token（`core/auth/device_vault.py:209`） | **3** | `amazon_credentials.access_token/refresh_token` 是**明文 Text 列**（`modules/amazon_sp/db_model.py:50-56`），且与该文件 `:15` 的「加密存储」承诺矛盾。当前无生产写入者故无实际泄露，一旦接真实 OAuth 即成 P1 | **P1** |
| F3 | **密钥托管与轮换** | — | **1** | 无 Vault / KMS / SOPS；**无密钥轮换工具** —— 换 `SHOP_CREDENTIALS_ENCRYPTION_KEY` 会使历史密文不可解，`credentials.py:149-152` 只有报错提示 | P2 |
| F4 | **SQL 注入** | ORM 参数化全覆盖，`text(` / f-string SQL **生产代码 0 命中** | **5** | — | — |
| F5 | **输入校验** | 认证/账户链路 pydantic 全覆盖 | **2** | `modules/` 内 **89 处 `payload: dict`** 绕过校验（如 `products/router.py:142,174,198...`），字段靠 `payload.get("x") or default` 手工兜 ⇒ 脏数据直写 + 潜在批量赋值面；另有 12 处 `shop_id or payload.get("shop_id")` 信任请求体（当前因写方法缺头 400 而不可达，属纵深防御缺口） | P1 |
| F6 | **XSS** | 4 处走 MarkdownIt（默认 `html:false`，安全） | **2** | **10 处 `v-html`**；`AIGCMediaResult.vue:678-682` 是**手写正则渲染器，完全不转义**；`DescriptionGenerator.vue:78`、`TitleGenerator.vue:112` 直接渲染后端原样字符串；**全项目无 DOMPurify / sanitize-html**（0 命中）。源码注释本身已写明风险（`MemoryEvolution.vue:250-253`） | **P1** |
| F7 | **CSRF / CORS** | 认证走 Bearer 头天然免疫；唯一 Cookie 设 `samesite=lax` + httponly + 路径收窄；CORS 白名单无通配符（`main.py:152-158`） | **4** | — | — |
| F8 | **速率限制** | IP 级固定窗口 60/min（`rate_limit.py:115-204`），Redis 不可用时降级内存（fail-open 有论证），响应带 `X-RateLimit-*`/`Retry-After`；账号爆破锁定（`login_guard.py`） | **3** | 按 IP 非按用户/租户；`X-Forwarded-For` 取第一跳，直曝公网可伪造（`rate_limit.py:28-30` 自己注明） | P2 |

---

## G. 合规与法律风险（权重 10 —— 跨境 SaaS 高危区）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| G1 | **审计日志** | 仅 `login_attempts`（`core/identity/auth_models.py:86-128`，覆盖登录撞库溯源） | **0** | **无「谁-何时-改了什么」的通用审计**（`audit` 命中全为 `profit_audit`/`seo_audit` 等业务语义）；`amazon_auth_logs` 表**零写入者**的空壳（`modules/amazon_sp/db_model.py:109-131`）；无审计中间件、无 `created_by`/`updated_by` 通用列。无法支撑 SOC2 / ISO27001 / GDPR 问责原则 | **P0** |
| G2 | **数据导出（可携权）** | 前端页面级导出（`frontend/src/utils/download.ts:17`，json/excel/csv/txt） | **1** | **后端无任何导出接口**（无 `Content-Disposition: attachment`，`StreamingResponse` 5 处全是 SSE）。导出的是当前页已加载数据，非全量店铺数据 ⇒ GDPR Art.20 未满足 | **P1** |
| G3 | **数据删除 / 注销** | — | **0** | 仅有 token 与登录日志的定期清理（`email_tokens.py:246`、`login_guard.py:161`）；**无用户级数据删除/匿名化端点** ⇒ 被遗忘权未满足 | **P1** |
| G4 | **SP-API 授权合规** | LWA 客户端实现完整（`platforms/amazon/sp_api/auth.py:187-210` refresh 交换、`:258` SigV4 签名） | **1** | ⚠️ **授权链路未实现**：`modules/amazon_sp/` 无 router，`main.py` 未挂载；`AmazonCredentialCreate`/`AuthUrlResponse` 是**无人调用的空壳 schema**（`models/amazon_sp.py:50-56`）；`get_spapi_auth()` 是**全局单例**，凭证来自 env 的**单一卖家** ⇒ 多租户下只能共用一份凭证，**不符合亚马逊按卖家独立授权规范，存在封店连带风险** | **P0** |
| G5 | **用户协议 / 隐私政策** | — | **0** | 无 LICENSE、无隐私政策、无用户协议、无数据处理协议（DPA）；README 仅标注「私有项目」。**数据所有权、责任边界、AI 输出致店铺处罚的免责条款全部未定义** | **P0** |
| G6 | **数据出境 / AI 训练授权** | — | **0** | 无数据出境说明、无 GDPR/CCPA 应对、无「禁止用客户数据训练模型」的显式声明或授权机制 | **P1** |
| G7 | **数据留存策略** | — | **0** | Amazon 系列表（`amazon_daily_sales`/`ad_metrics`/`listing_snapshots` 等）均为只增型，无 TTL / 无清理任务；无 PII 脱敏 | P1 |
| G8 | **爬虫 / IP 风险** | — | 未评 | 竞品情报模块的采集方式未在本次勘察范围，需单独确认是否触发平台反爬与禁令 | P1 |

---

## H. 部署、运维与容器（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| H1 | **Docker 打包** | 6 服务编排（postgres/redis/backend/worker/beat/frontend）；健康检查齐全（backend `Dockerfile:66`、worker `compose:187`、pg `:75`、redis `:108`）；后端非 root（uid 10001，`Dockerfile:57-61`）；前端**多阶段** node:22-alpine → nginx:1.27-alpine（`frontend/Dockerfile:22,46`）+ `npm ci`；命名卷持久化 + Redis AOF | **3** | 后端镜像**非多阶段**且保留 `build-essential`/`libpq-dev`（`Dockerfile:39-44`，注释自述未做瘦身）；compose 明文口令（见 F1）；**postgres 5432 全网卡暴露**（`compose:71`），而 backend/worker 都写了 `127.0.0.1:` 前缀 —— 同文件策略不一致 | **P0** |
| H2 | **环境隔离** | `config.py:115` 有 `environment` 字段；生产硬拒护栏 9 项（`config.py:156-330`）质量很高 | **2** | **只有一份 compose**，无 dev/staging/prod 变体；`staging` 是空头承诺（护栏只在 `=="production"` 生效 ⇒ staging 以 development 默认态运行，含 `payment_gateway=mock`）；`.env.example`（189 行）**缺 `METRICS_ENABLED`/`METRICS_TOKEN`/`SENTRY_DSN`/`LOG_JSON`**（README:162-165 列出了但 example 里没有）⇒ 新环境照抄会得到「/metrics 裸奔 + 无错误上报」 | **P1** |
| H3 | **CI 流水线** | **本项目最强项**：4 个 job —— 后端测试（真 PG/Redis service container）+ 前端门禁 + 资产完整性 + 安全扫描；真跑 `alembic upgrade head` → `downgrade base` → `upgrade head` **往返验证**（`ci.yml:142-157`）；`alembic check`；覆盖率棘轮 `fail_under=62`（`pyproject.toml:170`）；门禁**覆盖率自证**（磁盘 `check-*` 数 == 执行数，否则红，`ci.yml:277-278`）；pip/npm 缓存 | **5** | ruff 全量基线 2796 条，CI 只跑 `T20` 一条（棘轮式，有论证） | — |
| H4 | **CD / 灰度发布** | — | **0** | `.github/workflows` 只有 `ci.yml`；无 build-push / 无 deploy job / 无 registry / 无灰度 / 无蓝绿 / 无 feature flag；`docs/` grep `灰度|canary|蓝绿` 0 命中。发布 = 人工到目标机操作 | **P0** |
| H5 | **数据库迁移** | 20 个活跃迁移 **20/20 同时有 upgrade 与 downgrade**（含 squash baseline）；15 个归档；CI 真跑往返（这条很少见） | **4** | **生产无人执行迁移**：compose 的 backend 启动命令直接 `uvicorn`，无 `alembic upgrade head`；`main.py` lifespan 只 `seed_base_data()`。⇒ **CI 验证过的迁移链在生产从未被使用**；4 个 drop 类迁移的 downgrade 无法还原数据 | **P1** |
| H6 | **监控** | 见 C2：自研 Prometheus 11 指标 + `/health` 真探活 + 慢请求日志（>3000ms warning，`request_log.py:137-141`）+ Worker 独立指标端口 9100（只绑 loopback） | **3** | 无 APM、无慢查询日志（见 C6） | P2 |
| H7 | **告警** | — | **0** | 完全缺失（见 C4）。有指标无告警 = 出事只能靠客户投诉发现 | **P0** |
| H8 | **备份与灾备** | — | **0** | ⚠️ **备份类任务数量 = 0**：beat 调度 4 条全是业务任务（记忆蒸馏 03:00、超时单回收 每5分、到期清算 03:20、支付宝对账 04:30，`core/redis.py:114-151`）；全仓 `pg_dump|wal-g|PITR|archive_mode|basebackup|灾备` **无命中**（30 个命中全是业务代码与前端脚本）；postgres 未开 `wal_level=replica` ⇒ **PITR 前置条件都不满足**；无灾备文档。当前状态：**卷删了数据就没了** | **P0** |
| H9 | **日志运维** | 见 C1 | **3** | 无 size 轮转（单日实测 435MB）；无 logrotate / 采集 agent 配置 | P1 |
| H10 | **启动脚本生产可用性** | `start-*.bat` 三个脚本设计克制（三重命门检查、错误 pause、防双 beat） | **1** | 硬编码本机 conda 路径 `D:\work\anaconda\anaconda3\envs\reactAgents\python.exe`（`start-backend.bat:11`、`start-celery.bat:11`）；后端带 `--reload`（`:44`，Dockerfile 明确禁止生产用）；前端 `npm run dev`（`:37`）；靠 `start` 开 cmd 窗口管理进程，无守护无自动重启。**均非生产启动方式** | P2 |

---

## I. 质量、测试与风险（权重 10）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| I1 | **测试体量** | **1674 个用例 / 120 个文件 / 5.4 万行测试代码**；`timeout=120` + session 级事件循环 + 每用例 `engine.dispose()`（`pytest.ini:16-18`、`conftest.py:1149-1176`），均为事故驱动配置 | **5** | 测试连**真实 PostgreSQL**（`conftest.py:5`），隔离靠「建临时用户 + 外键拓扑序清理」而非事务回滚 ⇒ 存在顺序依赖，作者已自登记「单跑绿、全量红」（`:942-944`）；并行化（xdist）会直接崩 | P2 |
| I2 | **LLM/外部依赖隔离** | 三层结构性兜底，`autouse=True`：拦 `httpx.AsyncClient.send` 抛 ConnectError + 替换 `_get_default_llm` 为 `_OfflineChat` + 拦 `ssh/scp/curl` 的 `Popen`（`conftest.py:46-250`，注释记录「某用例真起 ssh 连生产服务器」事故）；桩保留 `_update_stats` 使计费链路仍被覆盖 | **5** | — | — |
| I3 | **核心链路覆盖** | 授权（80 用例，`test_auth_security_p1b.py:49`）＋ 计费支付（67，含**真 RSA2 签名**端到端 `test_billing_alipay_webhook.py`）＋ 多租户（101）＋ Agent（175）＋ 平台数据（51）全有，且多为「集成 + 真 DB + 外部已桩」 | **4** | SP-API 真实链路从未端到端测过（无凭据）；README 自述 **194 个端点中约 97 个无测试** | P2 |
| I4 | **前端测试** | 静态门禁 **29 个 + CI 覆盖率自证**，设计成熟 | **1** | **零单元测试**（无 vitest/jest，无 spec 文件，`package.json` 无 test 脚本）；9 个 CDP 浏览器探针中仅 1 个被 package.json 引用，其余是手工工具 | P1 |
| I5 | **幂等性** | 支付：`invoices.idempotency_key` 唯一索引 + 行锁 + 支付宝 `out_trade_no` 由 `sha256(key)` 确定性派生（`alipay.py:339-354`）+ **刻意零重试**（`gateway.py:15`）；Agent 任务：`aigc_jobs.dedupe_key` + **部分唯一索引只锁在途**（`WHERE status IN ('pending','running')`）+ 并发双击测试 | **4** | 向 LLM / SP-API 的请求**无幂等键**（`Idempotency-Key` 仅出现在文档表格里） | P2 |
| I6 | **降级与重试** | 重试唯一真源 `core/resilience.py`，语义严谨：4xx 除 429 不重试、流建立后绝不重试（否则用户看到重复正文）、`CancelledError` 永不重试；AST 门禁禁扩散（`tests/test_resilience.py`）；LLM/SP-API/Redis 各有明确且有论证的降级；多处刻意「不静默降级」 | **4** | **无熔断**（`circuit`/`熔断` 0 命中）；**队列重试弱**：无 `autoretry_for`/`retry_backoff`，仅靠 `task_acks_late=True` 重投 + 终态幂等出口；无统一超时原语；`base_agent.py:798` 自曝 `_mock_result` 子类无一实现 ⇒ 该降级分支**可能从未生效** | **P1** |
| I7 | **压力测试** | — | **0** | 无 locust / k6 / wrk / 任何基准；无吞吐断言、无性能回归防护；无全局并发闸门（仅出图链路 `MAX_CONCURRENCY=2`） | P2 |
| I8 | **故障演练** | 重试/降级有单元级验证 | **1** | 无第三方（SP/LLM）宕机的演练记录；无混沌工程；无降级开关的实操手册 | P2 |
| I9 | **风险登记册** | — | **0** | 无 risk register（`风险登记`/`risk register` 0 命中）；缺口散落在 `docs/project-audit-r270.md`、`docs/subscription-payment-go-live-checklist-r281.md` 等轮次文档里 | **P1** |

---

## J. 组织与工程管理（权重 5）

| # | 审查项 | 现状证据 | 分 | 缺口 | 优先级 |
|---|---|---|---:|---|:---:|
| J1 | **代码规范** | ruff 配置专业（每条 ignore 带理由，`pyproject.toml:39-97`）；pre-commit 设计克制（<1s、只拦密钥与大文件，`.githooks/pre-commit:3-15`，注释明说「慢 hook 的唯一结局是被 --no-verify 绕过」） | **3** | CI 只跑 1 条规则（2796 条技术债）；**ESLint 是死脚本**（有 lint 脚本但无配置、无 devDep）；无 Prettier | P2 |
| J2 | **安全扫描（SAST）** | **bandit + pip-audit + npm audit 三件套入 CI**（`ci.yml:374-405`）；bandit 与 ruff S 并存有论证 | **5** | 无 Dependabot / Snyk（`dependabot*`/`.snyk` 0 命中）；pip-audit 有 1 条忽略；npm audit 只拦 critical | P2 |
| J3 | **文档** | README 420 行覆盖技术栈/部署/环境变量/可观测性/测试/已知缺口；**证据留存文化强**（每轮审计有 docs + `.workbuddy/probes/` 实测） | **3** | 无独立 `ARCHITECTURE.md`；API 文档仅 `backend/docs/SP_API_INTEGRATION.md`、`LLM_RAG_INTEGRATION.md` 两篇；**无运维手册、无灾难恢复手册**；架构描述散在 `docs/` 与 `backend/docs/` 两处 | P2 |
| J4 | **评审与单点风险** | — | **2** | 无 PR 模板、无 CODEOWNERS（`.github/` 下只有 `workflows/`）；仓库只有 `main` 一个分支，无 develop/release；从注释与轮次文档看，核心架构决策高度集中于单人 ⇒ **明显的巴士因子风险** | **P1** |
| J5 | **前端工程质量（补充）** | — | **2** | README 自述：`any`/`@ts-ignore` 约 490 处；主包约 1.5MB 未做 `manualChunks` 拆包 | P2 |

---

## 1. P0 阻断项清单（对外商用前必须清零）

| # | 阻断项 | 证据 | 修复动作（可执行） |
|---:|---|---|---|
| **P0-1** | **3 处读端点跨租户可越权读取** | `platform_rules/service.py:315-320`、`knowledge_base/service.py:482-486`、`candidates/service.py:462-471` | 三处改为无条件 `scoped()`（对齐 `products/router.py:127-133` 写法）；把 `scoped_if` 的调用点收敛到 0，或强制要求调用点写「为何可跳过」并加门禁；扫平 35 处 `if shop_id:` |
| **P0-2** | **零数据库备份 / 无 PITR / 无灾备** | beat 4 条任务全业务（`core/redis.py:114-151`）；无 `pg_dump` | beat 加 `db.dump_and_upload`（每日 pg_dump + 上传对象存储）；postgres 开 `wal_level=replica`+`archive_mode=on`；写灾备恢复手册并**演练一次恢复** |
| **P0-3** | **零告警** | 无 Alertmanager/规则/通知渠道 | Prometheus + Alertmanager 规则，至少 4 条：`dependency_up{name="postgres"}==0`、`/health != ok`、ERROR 日志速率、LLM 日成本增幅 |
| **P0-4** | **compose 明文口令入库 + 5432 全网卡** | `docker-compose.yml:133/169/220`；`:71` | 口令改 `env_file`/secrets 引用并轮换；5432 收敛到 `127.0.0.1:`；拆 `docker-compose.prod.yml` |
| **P0-5** | **无审计日志** | 仅 `login_attempts`；`amazon_auth_logs` 空壳 | 建 `audit_logs` 表 + 写操作中间件/装饰器，记 `actor/time/action/target/before/after`；先覆盖店铺、凭证、订阅、成员权限四类写操作 |
| **P0-6** | **SP-API 授权链路未实现** | `amazon_sp` 无 router、不挂载；凭证是全局单例 env | 实现按店铺的 OAuth 授权/回调/解绑端点 + 凭证写入 `amazon_credentials`；删除 env 单例路径或仅限自用账号；补齐授权日志（`amazon_auth_logs` 目前零写入者） |
| **P0-7** | **提示词 100% 硬编码、零版本** | 8 个 prompt 常量；无版本号/历史/AB | 外置到 DB 表（`prompt_versions`，含 version/is_active/ab_bucket）+ 管理端可热更；至少先给每个 prompt 加版本号字段并落审计 |
| **P0-8** | **输出校验/幻觉防护缺失** | 无 schema 约束；JSON 失败同形退化 | 最终答复走 `with_structured_output`；读 `finish_reason` 并显式标记截断；把 `context_target_gate` 的 fail-closed 拒答模式推广到 Listing/AIGC |
| **P0-9** | **无用户协议 / 隐私政策 / 数据所有权声明** | 全仓无 LICENSE/隐私/协议 | 起草 ToS + 隐私政策 + DPA；明确「店铺数据归客户」「不用于训练模型（如需须单独授权）」「AI 输出致店铺处罚的责任边界」三条 |

> 次级但强烈建议：**P0-10 无 CD 流水线与回滚手段**（H4）。当前发布纯人工，回滚只能靠迁移 downgrade，而 4 个 drop 类迁移不可还原数据。

---

## 2. 亮点清单（评审会应明确认可，不要只扣分）

| 项 | 证据 |
|---|---|
| CI 质量高于同类早期项目 | 真 PG service container + 迁移**往返验证** + 覆盖率棘轮 + 门禁覆盖率自证 + bandit/pip-audit/npm audit（`ci.yml`） |
| 测试体量与外部依赖隔离策略 | 1674 用例；三层网络出口结构性兜底，非逐个打补丁（`conftest.py:46-250`） |
| 幂等性设计（钱相关） | 支付幂等键 + 部分唯一索引 + 真 RSA2 签名测试 + 刻意零重试（`gateway.py:15`） |
| 生产启动硬拒绝护栏 | 9 项启动期校验，不合规直接拒绝启动（`config.py:156-330`） |
| 凭据加密不静默退化 | 缺密钥直接抛错，绝不退回明文（`core/security/credentials.py:76-100`） |
| 长期记忆治理 | 分层 + 权重淘汰 + 注入上限 + 蒸馏批量/冷却闸门（`ai_infra/memory/limits.py`） |
| 入口归属校验 | 403 而非 404 防枚举；写方法缺租户头硬 400（`core/tenant/middleware.py:214-301`） |
| 重试语义严谨 | 流建立后不重试、4xx 不重试、CancelledError 不重试 + AST 门禁禁扩散（`core/resilience.py`） |
| 证据留存文化 | 每轮审计留 docs + 实测探针，缺陷有据可查（这在早期项目里罕见） |

---

## 3. 整改路线图（建议 90 天）

| 阶段 | 目标 | 任务 |
|---|---|---|
| **第 1–30 天（合规与安全止血）** | 清 P0-1/2/3/4/5/9 | 越权三处改无条件 scoped；建备份任务 + PITR 前置 + 演练恢复；上 Alertmanager 4 条规则；compose 口令外置轮换 + 端口收敛；建审计表（先覆盖 4 类写操作）；起草 ToS/隐私/DPA |
| **第 31–60 天（AI 治理与成本）** | 清 P0-6/7/8 + B/C 组 | SP-API 按店铺 OAuth + 凭证加密落库；提示词外置版本化；结构化输出 + finish_reason；LangChain 路径接入 LLM 指标；会话表归档任务；加 token/金额配额 |
| **第 61–90 天（工程化收口）** | H/I/J 组 | CD 流水线 + 回滚方案；生产启动加 `alembic upgrade head`；`.env.example` 补观测段；补数据导出/删除端点；压测基线；建风险登记册；PR 模板 + CODEOWNERS |

---

## 4. 一页纸审查框架（评审会 / PPT 用）

```
┌───────────────────────────────────────────────────────────────┐
│  eCommerce AI SaaS 技术尽调 · 48/100（商用基准）· 61/100（试点）│
├───────────────────────────────────────────────────────────────┤
│ 技术  架构耦合低、Agent 基类统一            A 2.6  ██████░░░░  │
│       成本无缓存、无金额闸门                B 2.2  █████░░░░░  │
│       可观测日志强、tracing/告警缺          C 2.2  █████░░░░░  │
│ 安全  多租户 3 处实证越权（P0）             D 3.0  ██████░░░░  │
│       鉴权 JWT/RBAC 好、无 MFA              E 2.6  ██████░░░░  │
│       密钥无硬编码、XSS/输入校验薄          F 3.0  ██████░░░░  │
│ 合规  审计/导出/删除/协议 全缺（P0）        G 0.4  █░░░░░░░░░  │
│ 运维  CI 满分 5/5；CD/备份/告警 全 0        H 2.2  █████░░░░░  │
│ 质量  1674 用例强；压测/熔断/风险登记 0     I 2.4  ██████░░░░  │
│ 组织  SAST 入 CI 强；无 PR 模板/单点风险    J 3.2  ███████░░░  │
├───────────────────────────────────────────────────────────────┤
│ 9 项 P0：①3处越权 ②零备份 ③零告警 ④compose明文口令             │
│ ⑤无审计 ⑥SP-API授权未实现 ⑦提示词硬编码无版本                 │
│ ⑧无输出校验 ⑨无协议隐私政策                                    │
├───────────────────────────────────────────────────────────────┤
│ 最强三块：CI 流水线 / 测试体量与外部隔离 / 幂等与凭据加密        │
│ 最弱三块：合规 / 备份灾备 / AI 治理（提示词+输出校验）          │
│ 一句话：功能与代码质量领先，商业化基础设施尚未开工              │
└───────────────────────────────────────────────────────────────┘
```

---

## 5. 使用说明

- 复制进 Notion / 语雀时，建议按 A–J 拆成 10 个折叠块，顶部保留 §0 总览。
- 每项「分」可在季度复评时直接更新，加权公式：`总分 = Σ(权重×得分) / 110 / 5 × 100`。
- 复评触发条件：任一 P0 清零后、或任一分组得分变动 ≥1 分。
