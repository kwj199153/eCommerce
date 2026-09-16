# 店管家 AI · 跨境电商全链路 AI SaaS

一站式 AI 原生跨境电商运营平台：选品 → Listing → 广告 → 客服 → 竞品监控 → 素材生产，全链路 Agent 化。

> **当前状态（2026-09-15）**：功能面已可用（6 个业务 Agent + 资料库 + 监控大屏），
> 安全面已完成 P0 修复（租户授权隔离 / 配置 fail-closed / 配额挂载）。
> 上线前请务必读完 [上线前必读](#上线前必读)。

---

## 目录

- [技术栈](#技术栈)
- [快速开始（本地开发）](#快速开始本地开发)
- [容器化部署](#容器化部署)
- [环境变量](#环境变量)
- [项目结构](#项目结构)
- [可观测性](#可观测性)
- [测试](#测试)
- [上线前必读](#上线前必读)
- [已知缺口](#已知缺口)

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic v2 |
| Agent | LangChain · LangGraph · deepagents · 分层路由（主 Agent 工具 48→8） |
| LLM | 阿里云 DashScope（qwen-max / qwen-plus / qwen-turbo） |
| 数据 | PostgreSQL 15 · Redis 7 · Celery |
| 前端 | Vue 3.5 · TypeScript 5.6 · Vite 5 · Pinia · ant-design-vue 4 |
| 部署 | Docker · docker compose · Nginx |
| 观测 | loguru（统一日志出口）· 自研 Prometheus 指标（`/metrics`） |

---

## 快速开始（本地开发）

### 1. 依赖

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 建议用 conda 独立环境 |
| Node.js | 20+ | 前端构建 |
| PostgreSQL | 15 | 必需。**缺了接口会大面积报错**，但报错形态容易被误判成代码问题 |
| Redis | 7 | 可选但强烈建议：限流与 Celery 依赖它 |

### 2. 起依赖服务

```bash
# PostgreSQL（若已有 my-postgres 在跑，跳过）
docker compose up -d postgres

# Redis（Celery 与跨进程限流需要）
docker compose up -d redis
```

### 3. 后端

```bash
cd backend
cp .env.example .env          # 然后按「环境变量」一节填好

pip install -r requirements.txt
python main.py                # http://localhost:8000
```

> 数据库表会在启动时自动创建（`init_db()` + `metadata.create_all`），
> 同时还会跑各模块的 seed（产品库 / 素材 / 候选品 / 监控池 / 平台规则 / 话术库 / 套餐）。
> 首次启动日志里会看到一串 `✅ ...种子数据已预置`。

### 4. 前端

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

`vite.config.ts` 已配好 `/api` 与 `/static` 到 `localhost:8000` 的代理 —— 所以前端**不需要**配后端地址。

### 5. 演示模式 vs 生产模式

这是最容易踩的一个开关，两边必须一致：

| | 后端 `.env` | 前端 `.env.development` |
|---|---|---|
| 本地演示（免登录） | `AUTH_REQUIRED=false` | `VITE_DEMO_MODE=true` |
| 生产（强制登录） | `AUTH_REQUIRED=true` | `VITE_DEMO_MODE=false` |

> ★ **两边不一致会表现为「前端自动登录成功、但所有接口 401」或反之。**
>
> ★ 两个开关的**默认值都是「安全侧」**（后端默认 `true`、前端默认 `false`），
> 也就是说：忘记配 = 会报 401（立刻发现），而不是悄悄放行所有人。

---

## 容器化部署

```bash
# 1. 准备环境变量
cp backend/.env.example backend/.env
#    至少填：DASHSCOPE_API_KEY / JWT_SECRET_KEY；生产环境还要 ENVIRONMENT=production

# 2. 起全套（PG + Redis + API + Celery Worker + Nginx 前端）
docker compose up -d --build

# 3. 首次初始化：回填店铺归属
#    ★ 必须做。存量店铺 owner_id 为空时，生产模式下非 admin 访问一律 403。
docker compose exec backend python scripts/backfill_owner_id.py

# 4. 验证
curl -s localhost:8000/health?detail=true | python -m json.tool
curl -s localhost:8000/metrics | head -20
```

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | http://localhost:8080 | Nginx 托管，反代 `/api` 与 `/static` |
| 后端 | http://localhost:8000 | 只绑回环，公网请走前端 Nginx |
| 指标（API） | http://localhost:8000/metrics | 设了 `METRICS_TOKEN` 需带 `Authorization: Bearer` |
| 指标（Worker） | http://localhost:9100/metrics | ★ 任务类指标**只在 worker 进程**自增，只在 8000 上看会全是 0 |
| 健康 | http://localhost:8000/health?detail=true | 含 PG / Redis / LLM 探活 |
| Worker 健康 | http://localhost:9100/health | 未 ready 时返回 503，供 compose healthcheck 使用 |

> ⚠️ **关于 `my-postgres` 已存在的情况**
> compose 里给 postgres 写死了 `container_name: my-postgres` 且卷名固定为 `pgdata`
> （与既有环境一致，避免出现"PG 起来了但是空库"的假象）。
> 若该容器是手工 `docker run` 起的，compose 会提示名称冲突，两种处理：
> a) `docker rm -f my-postgres` 后 `docker compose up -d`（数据在 `pgdata` 卷里，不会丢）；
> b) 只起需要的服务：`docker compose up -d --build backend worker frontend`。

---

## 环境变量

完整清单见 `backend/.env.example`。以下是最容易出问题的几个：

| 变量 | 默认 | 说明 |
|---|---|---|
| `ENVIRONMENT` | `development` | 设为 `production` 会**启用启动期安全校验**（见下） |
| `AUTH_REQUIRED` | `true` | 业务接口是否强制 Bearer Token。`false` = 演示模式 |
| `JWT_SECRET_KEY` | 占位值 | 生产必须换成高熵随机串，否则**拒绝启动** |
| `DATABASE_URL` | `...@localhost:5432/postgres` | 容器内要用服务名 `postgres` 而非 `localhost` |
| `REDIS_URL` | `redis://localhost:6379/0` | 限流 + 缓存 |
| `PAYMENT_GATEWAY` | `mock` | 生产不能是 `mock`，也不能是未接入的网关名（`stripe`/`alipay`/`wechat`/`paypal`），否则**拒绝启动** |
| `DASHSCOPE_API_KEY` | 空 | LLM 调用凭据。为空时 LLM 相关接口会显式失败 |
| `PUBLIC_BASE_URL` | 空 | 声音复刻样本需公网可回源；生产必须 HTTPS（浏览器录音要求） |
| `METRICS_ENABLED` | `true` | 是否注册 `/metrics` |
| `METRICS_TOKEN` | 空 | 非空时 `/metrics` 要求 Bearer；生产裸露会打 WARNING |
| `SENTRY_DSN` | 空 | 为空则完全跳过 Sentry（不 import、零开销） |
| `LOG_JSON` | `false` | 出逐行 JSON，便于 Filebeat / Promtail / SLS 采集 |
| `VOICE_CLONE_ENABLED` | `false` | 附加模块开关，前端入口与后端路由同时受其控制 |
| `WORKER_METRICS_PORT` | `9100` | worker 的指标/健康端口，`0` = 关闭。未鉴权，只绑回环 |
| `WORKER_POOL` | `threads` | worker 执行池。**不要轻易改回 `prefork`**（原因见下） |
| `WORKER_CONCURRENCY` | `4` | worker 并发度（`solo` 池下忽略） |
| `AIGC_MAX_INFLIGHT_PER_USER` | `3` | 单用户同时进行中的 AIGC 任务上限，超出返回 429 |

### 生产环境启动期安全校验

设 `ENVIRONMENT=production` 后，以下任一条不满足会**直接拒绝启动**并列出原因：

1. `AUTH_REQUIRED` 必须为 `true`
2. `JWT_SECRET_KEY` 不能沿用占位默认值
3. `DEBUG` 必须为 `false`
4. `PAYMENT_GATEWAY` 不能为 `mock`，也不能是**只是占位名**的网关
   （`stripe`/`alipay`/`wechat`/`paypal` —— 填了名字但实现还没写）

> 设计判据：**「启动失败」是显式且立刻可见的；「静默放行」要等出事才知道。**
> 这几项都属于「配错就直接等于没有安全」，因此选择拦启动而不是打日志。
>
> 第 4 条的两个方向是同一个道理的背面：`mock` 会让用户白拿套餐（收不到钱），
> 而填一个未接入的真网关名会让**第一笔支付就失败**（收了钱的服务用不了）。
> 两种都在启动期拦住，比等第一个客户付款失败要好。
> 运行时还有一层兜底：真到了扣款那一步，未接入网关返回 **501** 并附带整改指引，
> **不会**静默降级成「模拟支付成功」。

### 支付链路说明

| 关注点 | 现状 |
|---|---|
| 抽象层 | `platforms/payment/gateway.py`：`PaymentGateway` 协议 + `ChargeIntent`/`ChargeResult`/`InvoiceDraft` + 工厂 |
| 当前实现 | 仅 `MockGateway`（模拟支付成功，**仅限开发/演示**） |
| 真实接入 | 见 `payment_gateway.py` 顶部「真实网关接入清单」6 步（含三家网关差异速查表） |
| 价目口径 | 唯一真源 `modules/billing/pricing.py`；年付 = 月付 × 10。展示与扣款共用同一函数 |
| 幂等 | `SELECT ... FOR UPDATE` 行锁串行化 + `invoices.idempotency_key` 唯一约束兜底 |
| 零元处理 | 金额为 0 时不建账单（没有资金流动就不该有资金凭证） |
| 账单落库 | `POST /billing/subscribe` 成功即写入 `invoices`；返回值带 `charged` 字段 |

> ★ **前端注意**：`POST /billing/subscribe` 返回 **200 不等于已扣款**，必须读 `charged`。
> `charged=false` 表示命中幂等（同一套餐同一周期重复提交）或金额为 0。

### 异步任务（AIGC 长任务）

出图是**分钟级**操作：单张 15~25s，`MAX_CONCURRENCY=2` 且最多 8 张，最坏 **720s**。
原先它跑在请求线程里，而前端 axios 超时是 250s/300s —— 720 > 300，结果是
**「钱花了、结果丢了」**（图已生成并计费，接口却已超时）。现在这条链路走异步：

```
POST /api/v1/aigc/jobs  ──► aigc_jobs 表（pending）──► Redis(default 队列)
                                    │                        │
                       前端轮询 GET /aigc/jobs/{id}      worker 消费
                                    │                        │
                                    └──── 终态（succeeded / failed）◄──┘
```

| 关注点 | 口径 |
|---|---|
| 提交 | `POST /api/v1/aigc/jobs`，体为 `{kind, params}`，成功返回 **202** + `{job, deduplicated}` |
| `kind` | `asset_generate`（静态素材批量）/ `image_generate`（商品图） |
| 查询 | `GET /api/v1/aigc/jobs/{job_id}`；列表 `GET /api/v1/aigc/jobs?limit=20`（不含 result，避免响应过大） |
| 状态源 | **PostgreSQL 表 `aigc_jobs`**，不是 Celery result backend（后者 1 小时就过期，而 `/static` 图是长期链接） |
| 去重 | 同用户 + 同参数 + 仍在 `pending/running` → 命中已有任务，返回 `deduplicated: true`，**不重复计费** |
| 进行中上限 | `AIGC_MAX_INFLIGHT_PER_USER`（默认 3），超出 **429** |
| 越权 | 按 `user_id` 归属过滤；别人的任务返回 **404**（不是 403 —— 403 会泄露 job_id 是否存在） |
| 投递失败 | broker 不可用时任务落 `failed` 并返回 **503**，**不会**停在 pending 假装排队 |
| 前端等待 | `submitAndWaitAigcJob()` 最长 240s、2.5s 一次轮询，且**容忍 429**（429 = 查得太快，≠ 任务失败） |
| 超时未完成 | 返回 `settled: false` + `pending_job_id`，提示「可稍后在『我的任务』查看」，**不谎报失败**（谎报会诱导用户重跑 = 重复花钱） |

> ★ **为什么 worker 默认用 `threads` 池而不是 Celery 默认的 `prefork`**：
> 任务类指标（`aigc_tasks_total` / `celery_task_results_total`）是**进程内**内存注册表。
> `prefork` 下任务跑在 billiard 子进程里，父进程的 `/metrics` 永远是 0 ——
> 「指标定义了、暴露了、永远是 0」，排查时会误判成「任务从没跑过」。
> `threads` 池下任务与 `/metrics` 同进程，数字是真的；本项目的瓶颈也在等 IO 而非算 CPU。
> 需要改回 `prefork` 时请同时接受这个指标缺口，或改用支持多进程聚合的指标后端。

---

## 项目结构

```
eCommerce/
├── backend/
│   ├── main.py                  FastAPI 入口：中间件链 / 路由注册 / /health / /metrics
│   ├── worker.py                Celery Worker 入口
│   ├── core/
│   │   ├── config.py            全局配置（含生产安全校验）
│   │   ├── logger.py            loguru 统一日志出口 + 标准库 logging 接管
│   │   ├── observability/       ★ request_id 上下文 / 指标注册表 / Sentry
│   │   ├── database.py          异步引擎与 session 工厂
│   │   ├── redis.py             Redis 连接 + Celery 配置
│   │   ├── auth/                JWT 与鉴权依赖
│   │   ├── billing/             套餐配额 / 支付网关抽象 / LLM 计量
│   │   ├── tenant/              多租户上下文（★ 含店铺归属校验）
│   │   ├── middleware/          限流 / 请求日志与指标
│   │   └── checkpoint.py        LangGraph 会话持久化
│   ├── modules/                 业务模块（每个含 router / service / db_model / seed）
│   │   ├── user_subscription/   账号 · 订阅 · 计费 · 支付方式
│   │   ├── stores/              店铺群管理 + 动态利润测算
│   │   ├── product_research/    选品分析
│   │   ├── listing_generator/   Listing 生成优化
│   │   ├── ad_analysis/         广告分析
│   │   ├── customer_service/    智能客服
│   │   ├── competitor_intel/    竞品情报监控
│   │   ├── aigc_media/          AIGC 素材生产（文生图 / 图生图 / 视频脚本）
│   │   ├── voice_clone/         声音复刻（附加模块，默认关）
│   │   ├── secretary/           店秘书（主 Agent / 编排层）
│   │   ├── knowledge_base/      业务话术库
│   │   ├── platform_rules/      平台规则库
│   │   └── ...
│   ├── platforms/amazon/sp_api/ Amazon SP-API 客户端
│   ├── ai_infra/                LLM 客户端 / RAG / SSE / HITL 装饰器
│   ├── alembic/                 数据库迁移
│   ├── scripts/                 运维脚本（回填 / 门禁自检 / 测试挑选）
│   └── tests/                   pytest 测试（500+ 用例）
├── frontend/
│   ├── src/
│   │   ├── theme/presets.ts     ★ 三套主题的唯一定义处（加主题只改这里）
│   │   ├── config/palette.ts    图表调色板
│   │   ├── config/demoMode.ts   演示模式开关（默认关闭 + 生产构建硬关闭）
│   │   ├── api/                 HTTP 封装（含 request_id 透传）
│   │   ├── stores/              Pinia
│   │   ├── views/               页面
│   │   └── components/          组件
│   ├── nginx.conf               生产站点配置（SPA 回退 / 反代 / 缓存策略）
│   └── Dockerfile               Node 构建 + Nginx 托管（多阶段）
├── .github/workflows/ci.yml     CI：后端测试 + 前端类型检查 + 部署资产自检
└── docker-compose.yml           全套编排
```

---

## 可观测性

三件套，各自独立、可单独关掉：

### 日志

- **统一出口**：loguru 一个 sink 同时写控制台与 `logs/YYYY-MM-DD.log`（按天轮转 / 30 天保留 / gz 压缩）
- **标准库 logging 已被接管**：项目里原本有 16 个模块用 `logging.getLogger`，
  而标准库侧没有任何 handler，导致那批日志**不进日志文件**。
  现在通过 `InterceptHandler` 归一到 loguru（同格式、同文件、同样带 request_id）
- **request_id 贯穿**：任意模块、任意层级的日志都自动带上当前请求的
  `request_id` 与 `shop_id`，可以用一个 ID 把一次请求的全部日志串起来

格式：

```
2026-09-15 12:41:56.147 | INFO | 089f434c1d164cd0 | - | sqlalchemy.engine.Engine:_execute_context:1848 | SELECT 1
                          ↑      ↑ request_id              ↑ shop_id
                          级别
```

### 指标

`GET /metrics`（Prometheus 文本格式，零额外依赖）：

| 指标 | 含义 |
|---|---|
| `http_requests_total{method,path,status}` | 请求计数（`path` 已归一化，UUID → `:id`） |
| `http_request_duration_ms` | 耗时直方图（5ms ~ 30s 分桶） |
| `http_requests_in_flight` | 在途请求数 |
| `dependency_up{name}` | PG / Redis / LLM 配置 / API 自身可用性 |
| `llm_calls_total` · `llm_tokens_total` | LLM 调用与 token 消耗 |
| `aigc_tasks_total` · `aigc_task_duration_ms` | AIGC 生成任务 |
| `quota_rejections_total` | 被配额拦截的请求 |
| `celery_task_results_total` | 异步任务终态 |

> ⚠️ 指标是**进程级**的（自研注册表未做多进程聚合）。
> 多 worker / 多副本部署时，Prometheus 侧需按 instance 聚合。

### 错误上报（可选）

配了 `SENTRY_DSN` 才启用，否则完全跳过（不 import、零开销）。
配了 DSN 但没装 `sentry-sdk` 会打 WARNING 说清装哪个包 —— **不静默降级**。

### 健康检查

`GET /health`（`?detail=true` 给详情）：

```json
{
  "status": "ok | degraded | unhealthy",
  "dependencies": {
    "postgres": { "up": true, "latency_ms": 6.7 },
    "redis":    { "up": true, "latency_ms": 1.2 },
    "llm":      { "up": true, "model": "qwen-max" }
  }
}
```

- `postgres` 是**关键依赖** → 挂 = `unhealthy`
- `redis` 是**可降级依赖** → 挂 = `degraded`（限流退化为进程内计数）
- `llm` 只检查密钥是否配置（不发网络请求，避免探针烧配额）

---

## 测试

```bash
cd backend
pytest tests/ -q                        # 全量
pytest tests/test_auth_and_tenant.py -q # 鉴权与多租户
python scripts/pick_tests.py <改动文件>  # 按改动挑相关测试（不必每次全量）
```

> ⚠️ **PostgreSQL 与 Redis 必须先起来**。
> 缺了会出现大量 F/E，但那是**环境问题不是代码问题** —— 排查前先探 5432 / 6379 是否在听。

前端类型检查：

```bash
cd frontend
npx vue-tsc --noEmit
```

---

## 上线前必读

按优先级排列，前三条不做就等于把客户数据与钱摆在公网上：

1. **挂 HTTPS**。语音录音走浏览器 `getUserMedia`，HTTP 下浏览器直接拒绝；
   同时 Token 明文传输等于没有鉴权。并在 `.env` 里把 `PUBLIC_BASE_URL` 设为 `https://` 开头。
2. **`PAYMENT_GATEWAY` 不能是 `mock`**。`MockGateway` 无条件返回"支付成功"，
   用户点一下就能白拿付费套餐。生产用 mock（或填一个未接入的网关名）会被启动校验拦住；
   真接入了还要补 **webhook 回调 + 验签 + 日对账**，否则"支付闭环"只对了一半 ——
   详见 `payment_gateway.py` 顶部接入清单第 4、6 条。
3. **跑 `backfill_owner_id.py`**。存量店铺 `owner_id` 为空时，
   生产模式下非 admin 访问业务数据一律 403（这是修 BOLA 漏洞后的预期行为）。
4. **设 `METRICS_TOKEN`**，或把 `METRICS_ENABLED` 设为 false。
5. 换掉 `JWT_SECRET_KEY`（占位值会被启动校验拦住，但别只换一半）。
6. **改掉宝塔面板密码** —— 该密码曾出现在本项目的历史对话记录中。
7. 确认 `VoiceClonePanel.vue` 等文件已纳入版本控制（曾长期处于未跟踪状态）。

---

## 已知缺口

如实记录，避免被当成"已经做完"：

| 缺口 | 影响 | 状态 |
|---|---|---|
| 真实支付网关未接入 | 无法真实收款 | 抽象层与接入清单已就绪（`PaymentGateway` 协议 + 工厂 + 6 步 checklist + 三家网关差异表）；账单落库链路已端到端验证；配置层拦住"生产用 mock / 占位网关名"，运行时未接入网关返回 501。**仍缺**：真实商户凭证、webhook 回调路由、日对账任务 |
| 无真实支付方式录入 | `payment_methods` 表为空 | `POST /billing/payment-methods` 已按 `PaymentMethod` 模型实现，需接 Stripe SetupIntent / 支付宝签约后才能真实录卡 |
| 订阅无到期调度 | 周期结束后 `status` 不会自动转 `cancelled`/`expired` | 本期内判定不重复扣款依赖 `current_period_end`，逻辑正确；但缺定时任务推进状态机 |
| AIGC 长任务仍同步阻塞 | 出图超时即丢结果 | Celery 基础设施与 Worker 已就绪，任务化改造进行中 |
| 端点测试覆盖约 50% | 回归风险 | 194 个端点中约 97 个无测试，其中 75 个前端在用 |
| 前端类型宽松 | `any` / `@ts-ignore` 约 490 处 | 增量收敛中 |
| 主包体积约 1.5MB | 首屏偏慢 | 未做 `manualChunks` 拆包 |
| 平台数据接入 | 商品池仍为自研 mock | 未接真实生产凭证；SP-API 客户端已就绪 |
| ESLint 未真正启用 | lint 脚本是死脚本 | `package.json` 有脚本但 devDeps 里没有 eslint |
| ruff / mypy 未进门禁 | 静态检查靠人 | 配置已在 `backend/pyproject.toml` 备好，需先生成基线再设门禁 |

---

## 许可

私有项目。
