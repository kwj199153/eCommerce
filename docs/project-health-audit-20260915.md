# 项目全量体检报告 · 2026-09-15（第五轮）

> **一句话结论**：功能面已经像产品了，安全面还停在 demo。

## 评级总览

| 维度 | 评级 | 依据 |
|---|---|---|
| 功能完整度 | ✅ 达标 | 6 Agent + 资料库 + 监控大屏 + 素材/AIGC 全链路 |
| 前端模块化 | ✅ 达标 | 三套主题收敛在 `presets.ts` 一个文件；`App.vue` 646→126 行 |
| **多租户授权隔离** | ⛔ **阻断** | 非 owner 带有效 token 实测 **6/6 端点 200** |
| **商业化闭环** | ⛔ **阻断** | 支付是 mock；配额函数 0 处调用 |
| 工程门禁 | ⚠️ 需补 | 端点测试覆盖 50%、无 CI、lint 是死脚本 |
| 可运维性 | ⚠️ 需补 | 无 Dockerfile / CI / README / logging / metrics |
| 平台数据接入 | ⬜ 未做 | 商品池仍是自研 mock，未接真实生产凭证 |

## P0 · 阻断项（3 项，全部本轮新发现）

| # | 标题 | 实测数字 | 为什么是问题 | 怎么修 |
|---|---|---|---|---|
| **1** | **租户授权缺失（BOLA）** | 带有效 token 的非 owner 打别家数据：6/6 端点 200（16 SPU / 11 候选品 / 9 素材 / 6 监控 / 6 规则 / 音色状态）；无 Token 全 401 | `core/tenant/middleware.py: get_current_shop_id()` 裸返 `X-Shop-ID` header，零校验。认证有效，授权完全没做 | 该函数返回前查一次 `stores_store.owner_id`；归属不符返回 403 |
| **2** | **配置 fail-open** | `AUTH_REQUIRED` 默认 false；`JWT_SECRET_KEY = dev-secret-key-change-in-production`；前端 `VITE_DEMO_MODE !== 'false'`（不设即演示模式） | 三处默认值全部朝不安全方向倒，部署时漏设一个就鉴权全关 | 三处默认值全翻过来：auth_required 默认 True、密钥强制从环境读、前端 demo 默认 false |
| **3** | **配额纯展示** | `check_quota`/`check_api_quota`/`check_agent_chat_quota` 定义齐全含 429，全项目调用点 0 处 | 用户开基础版可以把 LLM/AIGC 无限用下去，直接烧钱 | 把 `check_api_quota` 挂到 LLM 与 AIGC 端点，`check_agent_chat_quota` 挂到对话入口 |

**为什么这三项能活到今天**：`backend/scripts/check_tenant_isolation.py` 这个门禁脚本存在，但演示模式下只跑 1 个「放行」用例，真正该拦的路径从未执行过。**门禁存在 ≠ 门禁在执行**。

## P1 · 挡商业化与运维（9 项）

| # | 标题 | 实测数字 | 来源 |
|---|---|---|---|
| 4 | 支付是 mock | `payment_gateway.py` 含 mock 标记；`invoices`/`payment_methods` 两张表 0 行 | 上轮遗留 |
| 5 | **无异步任务** | `@celery_app.task` 0 个、`.delay()` 0 个 → AIGC 出图整段同步阻塞 | 本轮新发现 |
| 6 | 端点测试覆盖 50% | 194 个端点里 97 个无测试，其中 75 个前端真在用 | 上轮遗留 |
| 7 | 部署资产全缺 | Dockerfile×2 缺、.github 缺、README.md 缺、backend/pyproject.toml 缺 | 上轮遗留 |
| 8 | 零可观测性 | logging 配置 / /metrics / Sentry 全无（有 request_log 中间件 + request_id ✅） | 上轮遗留 |
| 9 | DB 完整性 | 外键 15 条但业务表无一条指向 stores_store；13 张空表；脏行 candidates.shop_id='' 1 条、conversations.shop_id IS NULL 10 行 | 上轮遗留 |
| 10 | 提交卫生 | 未提交 259 条（上轮基线 104，在涨） | 上轮遗留，恶化 |
| 11 | 前端类型与体积 | `any`/`@ts-ignore` 488 处（上轮 367，在涨）；14 个 >800 行组件；主包 1511 kB 无 manualChunks | 上轮遗留，恶化 |
| 12 | 死代码 | 347 行：`api/competitorIntelligence.ts`(228) + `types/index.ts`(119) 零引用 | 本轮复扫 |

## P2 · 工程债（8 项）

| # | 标题 |
|---|---|
| 13 | lint 脚本声明了但 devDeps 无 eslint（死脚本） |
| 14 | 无 CI |
| 15 | 后端无 ruff |
| 16 | 前端无测试框架 |
| 17 | 30 个 >80 行后端函数 |
| 18 | list 端点零分页 |
| 19 | 6 个 mock 文件被生产代码引用（toolExecutors.ts 1772 行最大） |
| 20 | backend/tests/_all.txt 垃圾文件 |

## ✅ 已做好、别重复动

- **主题体系**：三套全在 `presets.ts`(659 行) → 加一套主题=改 1 文件；`App.vue` 646→126 行；`html.dark` 仅 16 处；`var(--)` 5855 处
- 后端测试 **515 用例 / 22 文件**；`docs_url` 已按 debug 关闭；`shop_id` 列全部有索引；4 个 seed 的 `shop_id` 硬编码已全修；死代码 .vue 已清 11 个 / 5645 行

## 建议修复顺序

1. **先只做第 1 项**（租户归属校验）— 不改等于把客户数据摆在公网上，改动点集中在一个函数
2. 紧接着第 2、3 项（配置默认值 + 配额挂载）— 和 1 组成「可对外开账号」的最小集合
3. 第二段 4 项（支付/异步/部署/可观测性）— 决定能不能收钱并交付
4. 第三段持续做，重点压 #10 提交卫生和 #11 any 与体积这两条在涨的指标

## 体检方法与证据

本次体检使用 `project-health-audit` skill 的 14 个维度框架，产出的可复现证据归档于：

```
.workbuddy/probes/project-audit-20260915/
├── 01-前端静态维度.txt        (6985B)
├── 02-死代码闭包.txt          (613B)
├── 03-后端端点覆盖与静默失败.txt (8828B)
├── 04-DB卫生与SaaS基线.txt    (11959B)
├── 05-越权实证-结论表.txt     (2387B)  ← P0 核心证据
├── 06-计费配额部署资产.txt    (7086B)
├── script-a1_static.cjs
├── script-a2_deadcode.cjs
├── script-a3_backend.py
├── script-a4_saas.py
├── script-a5_idor.py          ← 可重跑的越权验证脚本
└── script-a6_saas2.py
```

**关键方法论沉淀**：
- 判据要下在「生效的那一层」，不是「定义的那一层」（`dependencies=BUSINESS_AUTH` 挂 main.py 不挂 router.py → 搜 router.py 全 0=假警报）
- 认证 ≠ 授权：router 级鉴权只管「你是谁」；按 header 租户 ID 过滤数据处必须额外查归属
- 门禁存在 ≠ 门禁在执行：`check_tenant_isolation.py` 演示模式下只跑放行路径
- 配额数调用点不数定义点；判异步任务看 `@task`/`.delay()` 非 worker.py 存在
