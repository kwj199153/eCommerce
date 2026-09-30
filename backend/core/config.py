"""
全局配置模块

统一管理所有环境变量和系统配置，供全项目引用。
使用 pydantic-settings 进行类型安全的配置管理。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field, model_validator


# ★ 已知但尚未接入实现的真实支付网关名（P1-4，2026-09-15）
#
# 定义放在这里而不是 platforms/payment/gateway.py，是为了**避免循环导入**
# （payment_gateway 需要 import config）。payment_gateway 反过来 import 本常量，
# 于是「哪些网关算未接入」只有一处定义，不会出现两份清单各自漂移。
#
# 用途：生产环境护栏据此判定「配了一个只是占位名的网关」→ 拒绝启动。
# 见 Settings._enforce_production_safety() 与 payment_gateway.UnimplementedGateway。
#
# ★ 2026-09-25：`alipay` 已**摘除** —— 它不再是"占位名"，而是真实现
#   （platforms/payment/alipay.py）。摘除动作必须与 `_GATEWAYS` 的登记同时发生，
#   否则会出现最坏的中间态：配置写 alipay、实现没登记 ⇒ 502/501 看着像故障；
#   或者实现登记了、却仍被本清单拦在生产门外 ⇒ 明明配好了却起不来。
#   两者都由 tests/test_billing_payment.py 的参数化用例钉住。
KNOWN_UNIMPLEMENTED_GATEWAYS = ("stripe", "wechat", "wechatpay", "paypal")


# ★ 已接入的真实网关 → 生产环境启动前**必须非空**的配置项（2026-09-25）
#
# 用途：把「配了网关名但没配凭证」这类配置在**启动期**拦住。
# 为什么这一条不能省（与 payment_gateway=mock 是同一枚硬币的两面）：
#   漏配凭证时，应用能正常启动、页面能正常打开、下单接口也返回 200 ——
#   只是每次调支付宝都会拿到 `invalid-app-id` / `sign check fail`，
#   而我们把它转成一句「支付失败，请重试」交给用户。现象是
#   「支付功能时好时坏」，排查方向会被带到「用户网络/支付宝侧故障」上，
#   而真相只是一行空配置。
#   ⇒ 判据：能在启动期拦住就拦住；拦不住的（凭证错、余额不足）才留到运行期。
#
# 值为 (配置字段名, 人话说明) 元组；字段名用字符串而不是直接取值，
# 是因为这里只需要「名字」，而取值判定在 _enforce_production_safety 里统一做
# （避免清单与取值两处各自演进）。
IMPLEMENTED_GATEWAY_REQUIRED_CONFIG: dict[str, tuple[tuple[str, str], ...]] = {
    "alipay": (
        ("payment_alipay_app_id", "支付宝应用 APPID"),
        ("payment_alipay_app_private_key", "应用私钥（PKCS#8，用于请求签名）"),
        ("payment_alipay_public_key", "支付宝公钥（用于回调验签，不是应用公钥）"),
    ),
}


# ★ 支付回调的**路由路径**（唯一真源，2026-09-25）
#
# 为什么它住在 core/config.py 而不是计费模块：
#   这一条路径同时被两个**不能互相 import** 的地方需要 ——
#     · `modules/billing/payment_router.py`：真正把它挂到 FastAPI 上的地方；
#     · `core/config.py::Settings.resolve_payment_notify_url()`：把它拼成
#       完整 URL 交给支付宝的地方。
#   若各写一份，改路径时必然只改一半：支付宝打到旧路径 ⇒ 404 ⇒
#   它按重试策略反复投递 ⇒ 而我们的订阅永远不会激活，日志里只有一堆 404。
#   ⇒ 放 core，让"改路径"变成一次改动（`resolve_payment_notify_url` 与
#     路由挂载同时读它）。
PAYMENT_NOTIFY_PATH = "/api/v1/billing/webhook/alipay"


# ============================================================================
# 支付相关定时任务的节奏（唯一定义处，2026-09-25）
# ============================================================================
#
# ★ 为什么这些数字住在 core/config.py 而不是 modules/billing/tasks.py：
#   调度表在 `core/redis.py::beat_schedule` 里，而 **core 不允许 import modules**
#   （`tests/test_core_internal_layering.py` 守着这条边）。
#   若把数字写在任务模块里，core 就只能把 3 / 20 / 4 / 30 再手抄一遍 ——
#   于是"同一事实两份写法"，改了周期只会改一半：
#     · 改了任务模块里的常量 → 调度表没变 → 任务还是按旧时间跑（不报错）；
#     · 改了调度表 → 任务内部的窗口判定没变 → 扫的范围与频率不匹配。
#   两条都是"安静地跑错"。放在 core 之后，两个消费方 import 同一个值。
#
# ★ 这些是**运维节奏**，不是业务规则：改它们不需要动代码逻辑，
#   但必须同时意识到"更频繁 = 更多次网关调用"。
# ============================================================================

#: 回收「超时未支付」账单的间隔（分钟）。
#: ★ 取 5 分钟：TTL 是 30 分钟，回收频率远高于 TTL 即可保证
#:   "页面上的待支付"与"支付宝侧还活着的码"最多错开一个回收周期。
#:   再密没有收益（它只是一条 UPDATE，且 TTL 没到就不会命中）。
BILLING_EXPIRE_PENDING_INTERVAL_MINUTES = 5

#: 订阅到期清算的时刻（每天）。★ 凌晨低峰执行：它会批量 UPDATE 订阅行。
BILLING_SWEEP_HOUR = 3
BILLING_SWEEP_MINUTE = 20

#: 支付对账的时刻（每天）。★ 排在到期清算**之后**：
#:   对账可能把一笔"我们以为没付"的单补成已支付并开通订阅，
#:   而到期清算会撤销已过期订阅 —— 先清算再对账，当天的最终状态才收敛。
BILLING_RECONCILE_HOUR = 4
BILLING_RECONCILE_MINUTE = 30

#: 对账回看的窗口（天）。★ 不能只对"昨天"：
#:   支付宝的通知最长重投约 24 小时，而我们的服务可能连续几天没跑 beat
#:   （重启、维护窗口）。窗口太窄会把那几天的漏单永久漏掉。
#:   7 天 = 一个"人工发现问题的常规周期"，再多会让每天的查询量无谓增长。
BILLING_RECONCILE_LOOKBACK_DAYS = 7


class Settings(BaseSettings):
    """应用全局配置"""

    # ====== 应用基础 ======
    app_name: str = "跨境电商AI SaaS"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, description="调试模式")
    environment: str = Field(default="development", description="环境: development/staging/production")

    model_config = {
        "extra": "ignore",  # 允许额外字段，避免验证错误
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @model_validator(mode="after")
    def _derive_checkpoint_url(self):
        """checkpoint_database_url 缺省时从 database_url 派生（去 +asyncpg 驱动）。"""
        if not self.checkpoint_database_url or "+asyncpg" in self.checkpoint_database_url:
            self.checkpoint_database_url = self.database_url.replace("+asyncpg", "")
        return self

    def resolve_payment_notify_url(self) -> str:
        """支付回调地址（唯一真源）。

        优先级：显式 `PAYMENT_NOTIFY_URL` > 由 `PUBLIC_BASE_URL` + 回调路径拼出。

        ★ 为什么不在字段上直接给默认值：默认值必须是**推导**出来的
          （依赖另一个字段），而 pydantic 字段默认值看不到其它字段。
          写成「留空 = 自动推导」还有一个好处：用户看到 `.env` 里是空的，
          自然会去读 description，也就知道该配什么。

        ★ 返回值可能是空串（两个来源都空）。**调用方必须显式处理空串**：
          · 生产护栏把它当作"配置缺失"拒绝启动；
          · 网关侧把它交给支付宝时，宁可报错也不要传空 ——
            传空字符串给支付宝，它会退回"应用配置里的默认回调地址"，
            而那通常是另一个环境的地址（用户付了钱、回调打到别处）。
        """
        explicit = (self.payment_notify_url or "").strip()
        if explicit:
            return explicit
        base = (self.public_base_url or "").strip().rstrip("/")
        if not base:
            return ""
        return f"{base}{PAYMENT_NOTIFY_PATH}"

    @model_validator(mode="after")
    def _enforce_production_safety(self):
        """
        生产环境安全护栏（★ P0 安全修复 2026-09-15）

        修复前三处默认值全部朝「不安全」方向倒，且漏设时**没有任何报错**：
          1. auth_required 默认 False      → 鉴权整个关掉
          2. jwt_secret_key 沿用占位默认密钥 → 任何人可伪造 token
          3. debug 默认虽 False 但无人校验  → 生产环境可能带着调试模式上线

        现在：environment == "production" 时逐条强制校验，不满足直接拒绝启动。
        ★ 判据：「启动失败」是显式且立刻可见的；「静默放行」是隐式且要等出事。
        """
        if self.environment != "production":
            return self

        errors = []
        if not self.auth_required:
            errors.append("AUTH_REQUIRED 必须为 true（生产环境不能关闭鉴权）")
        # ★ 2026-09-17：演示哨兵在生产必须关闭。
        #   理由与 payment_gateway=mock 同构 —— 它不报错、不告警、接口一切正常，
        #   只是「任何知道 `demo-token` 这个字符串的人」都能以匿名身份读业务数据。
        #   而该字符串**就写在前端源码里**（frontend/src/config/demoMode.ts），
        #   等于把门敞开还贴了张告示。属典型的「静默削弱」，必须在启动期拦住。
        if self.demo_mode:
            errors.append(
                "DEMO_MODE 必须为 false（演示模式承认前端哨兵串 demo-token 为匿名身份，"
                "等于对任何知道该字符串的人开放全部业务数据）"
            )
        if not self.jwt_secret_key or "change-in-production" in self.jwt_secret_key:
            errors.append("JWT_SECRET_KEY 必须设为独立的高强度随机值（不能沿用占位默认密钥）")
        if self.debug:
            errors.append("DEBUG 必须为 false（生产环境不能开启调试模式）")
        # ★ P1-4 补充（2026-09-15）：生产环境不能拿模拟支付网关收钱。
        #   MockGateway 的 charge() 是「无条件返回支付成功」，也就是说
        #   用户点一下「升级到专业版」就直接变成付费用户，一分钱不收。
        #   这是「收了钱没到账」的反向事故，必须拦住。
        gw = (self.payment_gateway or "").strip().lower()
        if gw == "mock":
            errors.append(
                "PAYMENT_GATEWAY 不能为 mock（模拟网关无条件支付成功 ⇒ 用户白拿付费套餐）。"
                "接入真实网关后把 PAYMENT_GATEWAY 改为对应实现名"
            )
        elif gw in IMPLEMENTED_GATEWAY_REQUIRED_CONFIG:
            # ★ 2026-09-25 新增：已接入的**真**网关，凭证必须齐全。
            #   它与上下两条构成三段完整覆盖：
            #     mock            → 拒（不产生真实收款）
            #     已接入真实网关  → 查凭证（配了名，但可能没配钥匙）
            #     未接入占位名    → 拒（配了名，但实现还没写）
            #   ★ 三个分支的判据都是同一条：**让「看起来配好了」和「真的配好了」
            #     不可能长得一样**。
            missing = [
                f"{label}（{field}）"
                for field, label in IMPLEMENTED_GATEWAY_REQUIRED_CONFIG[gw]
                if not str(getattr(self, field, "") or "").strip()
            ]
            # 回调地址是第二个必须项，且它**不可从网关侧推导** —— 支付宝只能
            # 按我们给它的 notify_url 回调；地址为空或不是公网绝对地址，
            # 表现是「用户付了钱、订阅永远不激活」，而支付记录在支付宝侧是成功的。
            notify = self.resolve_payment_notify_url()
            if not notify:
                missing.append(
                    "回调地址（设 PUBLIC_BASE_URL，例如 https://api.example.com；"
                    "或显式设 PAYMENT_NOTIFY_URL）"
                )
            elif not notify.lower().startswith(("http://", "https://")):
                # ★ 相对路径 / 裸域名在这里必须拒：支付宝只会拿这个字符串去发
                #   HTTP 请求，它没有"我们的域名"这个概念。写成 `api.example.com/...`
                #   （少了 scheme）不会报错，只会让支付宝把回调发到一个不存在的
                #   主机上，而我们在这一侧什么日志都看不到。
                errors.append(
                    f"回调地址不是绝对 URL（当前 '{notify}'）：支付宝会原样拿它发请求，"
                    f"必须以 http:// 或 https:// 开头"
                )
            if missing:
                errors.append(
                    f"PAYMENT_GATEWAY='{gw}' 的接入配置不完整，缺少：" + "、".join(missing)
                    + "。★ 这类漏配不会让启动失败，只会让每一笔支付都"
                    "「看起来像支付宝那边出了问题」，必须在启动期拦住。"
                )
        elif gw in KNOWN_UNIMPLEMENTED_GATEWAYS:
            # ★ 这条与上一条方向相反，却是同一个道理的背面：
            #   把网关填成 stripe/alipay/wechat 只是**填了个名字**，
            #   实现还没写。这类配置在开发环境看起来一切正常（应用能起、
            #   页面能开），生产环境则会「第一笔支付就 500」。
            #   启动期拦住，比等第一个客户付款失败要好。
            errors.append(
                f"PAYMENT_GATEWAY='{gw}' 尚未接入实现（只是占位名）。"
                f"请先按 platforms/payment/gateway.py 顶部「真实网关接入清单」"
                f"完成 6 步接入，再把该值改为 '{gw}'"
            )

        # ★ 口令哈希轮数（2026-09-16 新增）：与上面「mock 网关」同一道理的反面 ——
        #   把 rounds 调低**不会**报错、不会告警、登录一切正常，只是哈希强度
        #   静默掉到 1/256。这类「静默削弱」正是最该在启动期拦住的形态。
        if self.password_hash_rounds < 12:
            errors.append(
                f"PASSWORD_HASH_ROUNDS 必须 >= 12（当前 {self.password_hash_rounds}）："
                f"降低轮数会静默削弱口令抗爆破强度。"
                f"测试提速请勿改这里，改用 tests/conftest.py 的会话级覆盖"
            )

        # ★ P1-d（2026-09-16）：/metrics 漏配令牌。
        #   为什么从 WARNING 升级为「拒绝启动」：原先 main.py 里只有一句告警，
        #   而告警**不改变任何行为** —— 端点照样 200 露出 QPS、错误率、
        #   接口清单（等于把系统拓扑直接送给扫描器）。这类「提示存在 ≠ 门禁执行」
        #   的形态，与 payment_gateway=mock 同构：默认结果必须朝安全侧倒。
        #   判据：不需要指标端点 = 显式 METRICS_ENABLED=false（一行，是有意为之）；
        #         漏配 = 起不来（立刻发现）。
        if self.metrics_enabled and not (self.metrics_token or "").strip():
            errors.append(
                "METRICS_TOKEN 不能为空（METRICS_ENABLED=true 时生产必须给 /metrics "
                "设访问令牌，否则 QPS、错误率、接口清单对任何扫到该路径的人可见）。"
                "不需要指标端点请显式设 METRICS_ENABLED=false"
            )

        # ★ P1-b（2026-09-16）：口令爆破防护的两个阈值。
        #   与 password_hash_rounds 同构 —— 调低不会报错，只会让防护静默消失。
        if self.login_max_failures < 3:
            errors.append(
                f"LOGIN_MAX_FAILURES 必须 >= 3（当前 {self.login_max_failures}）："
                f"阈值过大会让口令爆破在防护生效前就撞开弱口令"
            )
        if self.login_lockout_minutes < 5:
            errors.append(
                f"LOGIN_LOCKOUT_MINUTES 必须 >= 5（当前 {self.login_lockout_minutes}）："
                f"锁定窗口过短等于没有锁定（攻击者只需放慢节奏即可绕过）"
            )

        # ★ P1-b：邮件通道。分三段判，因为「不想发邮件」与「想发却没配好」
        #   必须被区分开 —— 前者用 disabled 显式声明，后者一律拒绝启动。
        provider = (self.email_provider or "").strip().lower()
        if provider not in ("console", "aliyun_dm", "disabled"):
            errors.append(
                f"EMAIL_PROVIDER='{self.email_provider}' 不是已知值"
                f"（可选：console / aliyun_dm / disabled）"
            )
        elif provider == "console":
            # console 只在单进程开发时把信写进日志，生产用它 =
            # 「用户点了发送验证邮件、界面说已发送、实际没人收到」，
            # 而且这个偏差**不会有任何报错**。必须拦住。
            errors.append(
                "EMAIL_PROVIDER=console 只能用于开发/测试（邮件只写日志不外发）。"
                "生产请配 aliyun_dm（并填 ACCESS_KEY_ID/SECRET/ACCOUNT_NAME），"
                "或显式设 disabled（此时会明确告知用户邮件服务未启用）"
            )
        elif provider == "aliyun_dm":
            missing = [
                name
                for name, val in (
                    ("ALIYUN_DM_ACCESS_KEY_ID", self.aliyun_dm_access_key_id),
                    ("ALIYUN_DM_ACCESS_KEY_SECRET", self.aliyun_dm_access_key_secret),
                    ("ALIYUN_DM_ACCOUNT_NAME", self.aliyun_dm_account_name),
                )
                if not (val or "").strip()
            ]
            if missing:
                errors.append(
                    f"EMAIL_PROVIDER=aliyun_dm 但缺少：{', '.join(missing)}。"
                    f"缺项时发信会在运行时失败，而注册/找回密码接口仍返回成功 —— "
                    f"这类「假成功」必须在启动期拦住"
                )

        # ★ EMAIL_VERIFICATION_REQUIRED=True 的两条前置：
        #   ① 必须真的能发信（否则用户注册完永远验证不了 ⇒ 账号永久死锁）；
        #   ② 必须能给用户一个可点的链接（PUBLIC_SITE_URL）。
        if self.email_verification_required:
            if provider in ("console", "disabled"):
                errors.append(
                    "EMAIL_VERIFICATION_REQUIRED=true 要求 EMAIL_PROVIDER 不是 "
                    f"'{self.email_provider}'：发不出验证邮件时，用户注册完将"
                    "永远无法完成验证 ⇒ 账号永久锁死"
                )
            if not (self.public_site_url or "").strip():
                errors.append(
                    "EMAIL_VERIFICATION_REQUIRED=true 要求 PUBLIC_SITE_URL 非空"
                    "（否则邮件里给不出可点的激活链接）"
                )

        # ★ P0-4（2026-09-30）：数据库弱口令 / 默认口令。
        #   为什么必须拦在启动期：compose 里 POSTGRES_PASSWORD 走
        #   ${POSTGRES_PASSWORD:-123456} 插值，默认值只为「本地一键起」保留 ——
        #   生产若忘了覆盖，服务会**正常启动、正常连库、接口全部 200**，
        #   唯一的现象是「库对公网开着 5432 且口令是 123456」，
        #   而这件事不会有任何报错、告警或异常日志。属典型「静默放行」。
        #   ★ 判据不是「口令够不够长」（那是口令学问题），而是
        #     **让「看起来配好了」和「真的配好了」不可能长得一样**。
        #   与上面几条同一精神：能在启动期拦住就拦住。
        _db_url = (self.database_url or "").strip().lower()
        for _weak in ("123456", "postgres", "password", "root", "admin"):
            if f":{_weak}@" in _db_url:
                errors.append(
                    f"DATABASE_URL 使用了默认/弱口令（命中 '{_weak}'）："
                    f"生产环境请把 POSTGRES_PASSWORD 设为高强度随机值，"
                    f"并同步 backend/worker/beat 的 DATABASE_URL（两处必须一致）"
                )
                break
        if errors:
            raise ValueError(
                "生产环境安全校验未通过，请修正以下配置后重启：\n  - " + "\n  - ".join(errors)
            )
        return self

    # ====== 服务器配置 ======
    api_host: str = Field(default="0.0.0.0", description="API 监听地址")
    api_port: int = Field(default=8000, description="API 端口")
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"], description="CORS 允许的源")

    # ====== 数据库 (PostgreSQL) ======
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ecommerce",
        description="PostgreSQL 异步连接 URL"
    )
    # LangGraph Checkpoint 专用连接串（psycopg3 驱动，与业务 asyncpg 分离）
    # AsyncPostgresSaver 硬依赖 psycopg3，故用 postgresql:// 而非 postgresql+asyncpg://
    checkpoint_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/ecommerce",
        description="LangGraph checkpoint 持久化连接 URL（psycopg3）"
    )
    database_pool_size: int = Field(default=10, description="连接池大小")
    database_max_overflow: int = Field(default=20, description="连接池最大溢出数")

    # ====== Redis & Celery ======
    # ⚠️ 用 127.0.0.1 而非 localhost（实测踩过的坑，别再改回去）：
    #   Windows 上 `localhost` 会先解析到 IPv6 的 ::1。若 Redis 只监听 IPv4
    #   （Docker 端口映射常见配置），连 ::1 会被拒绝，而系统要等约 2 秒才返回
    #   失败；更糟的是客户端一旦设了 connect timeout，会在 1 秒处主动放弃，
    #   **根本不会回退到 IPv4** ⇒ 限流中间件的 Redis 后端从未生效、静默降级为
    #   进程内计数（"门禁存在 ≠ 在执行"），/health 每次探活也白等 1 秒。
    #   直接写 127.0.0.1 省掉这段解析，Linux / Docker 下与 localhost 完全等价。
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", description="Redis 连接 URL")
    celery_broker_url: str = Field(default="redis://127.0.0.1:6379/1", description="Celery Broker URL")
    celery_result_backend: str = Field(default="redis://127.0.0.1:6379/2", description="Celery Result Backend")

    # ====== Mock 适配器仿真参数 ======
    #
    # 平台 mock 适配器（platforms/amazon/client.py）里有一组硬编码的
    # 「假网络延迟」（0.1~0.3s/次，见 AmazonAdapter._simulate_delay）。
    # 它模拟的对象**并不存在** —— 该适配器的数据来自内存 MOCK_PRODUCTS，
    # 没有任何网络往返；真实延迟要等 Phase 3+ 接 SP-API 时才由网络本身产生。
    #
    # 代价却是实在的（实测）：
    #   · `_analyze_blue_ocean` 一次调 8 次 get_keyword_data + 5 次
    #     match_products ⇒ 白等约 2.0 秒；
    #   · 全量测试 626 项里约 45 秒耗在此（占 41%）；
    #   · 产品上：老板在 UI 点一次「蓝海分析」就要多等 2 秒。
    #
    # 故默认 0.0（关闭）。若做演示想要「缓慢加载」的手感，设为 1.0
    # 即恢复原始量级。
    mock_latency_scale: float = Field(
        default=0.0,
        description="mock 适配器假延迟系数：0=关闭（默认），1.0=原始仿真值",
    )

    # ====== 口令哈希参数 ======
    # bcrypt 的「成本因子」= 2**rounds 次迭代。rounds=12 时本机实测
    # 单次 hash ≈ 209ms、verify ≈ 207ms。慢是**故意**的 —— 它保护的是离线爆破。
    #
    # 但它在测试里是纯开销：没有任何用例在测「哈希够不够慢」，而
    # tests/conftest.py 的 `user` / `job_user` 夹具**每一条用例**都要
    # register + login 一次 ⇒ 每例固定白花 ≈ 416ms。
    # 实测（2026-09-16）：全量 627 项里有 25 项依赖该夹具，合计 17.73s，
    # 其中 bcrypt 占 ≈ 10.4s（占剩余用例耗时的 23%）。
    #
    # 故做成配置项：**默认 12 不动**（生产强度不变），只由 tests/conftest.py
    # 在该测试进程内显式降到 4（≈0.8ms）。
    # ★ 生产护栏（_enforce_production_safety）会拒绝 < 12 的取值 ——
    #   「测试里调低」与「默认值调低」必须能被区分开，否则强度会静默掉一半。
    password_hash_rounds: int = Field(
        default=12,
        description="bcrypt 成本因子（轮数）。生产必须 >=12；测试由 conftest 降到 4",
    )

    # ====== 店铺平台凭证加密（P1-a 修复，2026-09-16）======
    # Fernet（AES-128-CBC + HMAC-SHA256）密钥，base64 urlsafe 编码 44 字符。
    #
    # ★ 留空 = **拒绝写入平台凭证**，不是明文落库。
    #   生成：python -c "from cryptography.fernet import Fernet;
    #                     print(Fernet.generate_key().decode())"
    #
    # ★ 为什么不列入 _enforce_production_safety 的启动硬拒绝：
    #   「暂时不接平台」是合法运营状态，强制要求密钥会让一个只想开店的部署
    #   起不来。改成在**写这一层**拒绝（core/security/credentials.py）：
    #   真去连接平台时才失败，且原因可读。漏配本项**不会**产生任何不安全的
    #   落库结果 —— 这与 auth_required / jwt_secret_key 那些「漏配=危险」的项
    #   方向不同，故档位也不同。
    # ★★★ 第 119 轮实测修掉的缺陷：**文档写的环境变量名，代码根本没读**
    #
    #   本字段名是 `credentials_encryption_key`，而 `Settings.model_config` 里
    #   既没有 `env_prefix`、字段也没有 alias ⇒ pydantic-settings 按默认规则
    #   直接大写字段名去找环境变量，也就是 **`CREDENTIALS_ENCRYPTION_KEY`**。
    #   但 `.env.example`、`core/security/credentials.py` 的报错文案、
    #   本字段的注释，一律写的是 `SHOP_CREDENTIALS_ENCRYPTION_KEY`。
    #
    #   对照实验（同一套 .env、同一段代码，只改环境变量名）：
    #       SHOP_CREDENTIALS_ENCRYPTION_KEY → 读到 0 字符
    #       CREDENTIALS_ENCRYPTION_KEY      → 读到 44 字符
    #
    #   后果形态：用户**照文档配了**、却依然拿到「未配置密钥，已拒绝写入」
    #   的报错，而报错文案还在指引他"把结果写进 .env 的
    #   SHOP_CREDENTIALS_ENCRYPTION_KEY" —— 照做，依然失败，无处可查。
    #   这正是本仓判据里的「注释承诺 ≠ 实现事实」，且**没有任何代码会报错**。
    #   （测试之所以没发现：`tests/test_credential_encryption.py` 用
    #     `monkeypatch.setattr(config, ...)` 直接改属性，**绕过了环境变量这条
    #     路径** ⇒ 环境变量名从未被任何用例覆盖过。）
    #
    #   修法：用 `AliasChoices` 把三个名字都接住 ——
    #     ① `SHOP_CREDENTIALS_ENCRYPTION_KEY`（文档/示例对外承诺的名字）
    #     ② `CREDENTIALS_ENCRYPTION_KEY`（修复前**唯一真正生效**的名字，
    #        可能已有部署在用，不能弃）
    #     ③ `credentials_encryption_key`（字段名本身；不列进来的话，
    #        `Settings(...)` 关键字构造与 `populate_by_name` 那条路会断）
    credentials_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SHOP_CREDENTIALS_ENCRYPTION_KEY",
            "CREDENTIALS_ENCRYPTION_KEY",
            "credentials_encryption_key",
        ),
        description=(
            "静态加密主密钥（Fernet，44 字符）：店铺平台凭证 + 本机登录凭据；"
            "留空=拒绝写入，不是明文落库"
        ),
    )

    # ====== JWT 认证 ======
    jwt_secret_key: str = Field(default="your-super-secret-key-change-in-production", description="JWT 密钥")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法")
    jwt_access_token_expire_minutes: int = Field(default=60, description="Access Token 过期时间(分钟)")
    jwt_refresh_token_expire_days: int = Field(default=7, description="Refresh Token 过期时间(天)")

    # ====== 邮件通道（阿里云邮件推送 DirectMail；★ P1-b 2026-09-16）======
    #
    # 用途：注册邮箱验证 + 忘记密码重置链接。
    #
    # ★★★ 为什么是「三档」而不是「配了就发、没配就不发」：
    #   后者是最典型的「假门禁」—— 没配邮件服务时，注册接口照样 200，
    #   用户以为验证邮件已发出，实际什么都没发生；而忘记密码更是
    #   彻底断链（用户永远收不到重置链接，也永远查不出为什么）。
    #   三档的判据是**每一档的行为都可预测、且不产生"假成功"**：
    #
    #     console（默认，开发/测试）—— 信不真发，写进日志 + 内存 outbox。
    #       测试据此断言「信确实被发了」，**永远不依赖外网**，也不会
    #       因为没配 SMTP 而静默跳过。生产护栏禁止这一档。
    #     aliyun_dm —— 真发。缺任一必填项 ⇒ 生产启动期直接拒绝。
    #     disabled —— 显式关闭。此时发信接口**明确回 503 + 原因**（不静默），
    #       且 EMAIL_VERIFICATION_REQUIRED 不允许为 true（否则用户注册完
    #       永远无法验证 ⇒ 账号永久死锁）。
    #
    # ★ 为什么自实现签名而不是装 aliyun SDK：
    #   DirectMail 的 SingleSendMail 是 RPC 风格 HMAC-SHA1 签名，
    #   用标准库 hmac/hashlib + 已有的 httpx 即可，≈60 行。
    #   少一个依赖 = 少一类「SDK 版本变了、签名算法变了」的静默失败。
    email_provider: str = Field(
        default="console",
        description="邮件通道：console（开发/测试，只记录不外发）/ aliyun_dm / disabled",
    )
    aliyun_dm_access_key_id: str = Field(default="", description="阿里云 AccessKey ID")
    aliyun_dm_access_key_secret: str = Field(default="", description="阿里云 AccessKey Secret")
    aliyun_dm_region: str = Field(default="cn-hangzhou", description="DirectMail 区域")
    aliyun_dm_endpoint: str = Field(
        default="https://dm.aliyuncs.com/", description="DirectMail API 端点"
    )
    aliyun_dm_account_name: str = Field(
        default="", description="发信地址（须已在控制台验证，如 noreply@mail.example.com）"
    )
    aliyun_dm_from_alias: str = Field(default="跨境电商AI", description="发件人显示名")

    # 注册后是否必须验证邮箱才能登录。
    # ★ 默认 False —— 这一条决定了「打开它」是不是安全的：
    #   若默认 True，则任何未配邮件的部署（含全部 CI / 本地开发）注册完
    #   就登不上，属"默认把系统锁死"。默认 False 时行为与改造前完全一致，
    #   要开启请显式设置，并由生产护栏保证邮件通道真的可用。
    email_verification_required: bool = Field(
        default=False,
        description="注册后是否必须完成邮箱验证才能登录（默认否）",
    )
    email_verify_token_ttl_hours: int = Field(default=24, description="邮箱验证链接有效期(小时)")
    email_reset_token_ttl_minutes: int = Field(default=30, description="密码重置链接有效期(分钟)")

    # 前端站点根地址，用于把 token 拼成用户可点的链接。
    # 留空 = 只返回 token 本身，不拼链接（本地联调可接受；生产护栏要求非空）。
    public_site_url: str = Field(
        default="", description="前端站点根地址，用于生成邮箱里的激活/重置链接"
    )

    # ====== 登录失败锁定（★ P1-b 2026-09-16）======
    #
    # ★ 判据：口令爆破的防护不是「让猜错变慢」（bcrypt 已做，≈200ms/次），
    #   而是「猜错够多次就换不了口」—— 否则每秒 5 次、一小时 18000 次，
    #   弱口令照样被撞开。
    #
    # ★ 为什么锁定后即使**密码正确**也拒绝：
    #   若密码正确就放行，攻击者只要持续猜，猜对的那一次就直接进 ——
    #   锁定窗口对攻击者零成本。所以判定顺序必须是
    #   「先看锁没锁，再看密码对不对」。
    #
    # ★ 阈值进生产护栏的理由同 password_hash_rounds：
    #   把 max_failures 调成 1000000 不会报错、不会告警、登录一切正常，
    #   只是防护静默消失。这类「静默削弱」必须能在启动期拦住。
    login_max_failures: int = Field(
        default=5, description="连续登录失败多少次后锁定账号（生产须 >=3）"
    )
    login_lockout_minutes: int = Field(
        default=15, description="锁定时长(分钟)（生产须 >=5）"
    )
    login_attempt_retention_days: int = Field(
        default=30, description="登录尝试审计记录保留天数（用于清理脚本）"
    )

    # ====== 通用审计保留期（★ 2026-09-30）======
    #
    # ★ 与 `login_attempt_retention_days` **分开**、不共用一个数字：
    #   两张表的写入速率与"留多久才有排查价值"完全不同 ——
    #     · `login_attempts` 每次登录都写（且可被脚本刷）⇒ 30 天足够；
    #     · `audit_logs` 只在业务写操作时写，是「谁对**什么对象**做了什么」的
    #       **问责证据**（成员变更 / 店铺归属 / 删除这类事件），
    #       追溯期应与这些事件的复查周期对齐 ⇒ 90 天。
    #   共用一个字段的后果：想延长审计追溯期时会顺手把登录审计表也撑大
    #   （反之亦然），而两边都不报错。
    #
    # ★ 为什么它是配置而不是常量：延长追溯期常来自合规要求或一次事故复盘，
    #   属于"当天就要生效"的需求 ⇒ 必须能改环境变量，
    #   而不是改代码 + 重新发版。
    audit_retention_days: int = Field(
        default=90, description="通用审计日志（audit_logs）保留天数（用于定时清理）"
    )

    # ====== 邮件一次性 token 保留期（★ 第 331 轮）======
    #
    # ★ 为什么它此前**不存在**、以及为什么这算缺陷：
    #   清理核 `core/identity/email_tokens.py::purge_spent_tokens` 从 P1-b 起
    #   就在，但保留期写死在函数签名里（`older_than_days: int = 7`）——
    #   于是"想多留几天排查邮件没收到"必须改代码 + 重新发版。
    #   而隔壁两张表都是配置（`login_attempt_retention_days=30` /
    #   `audit_retention_days=90`）。同一件事三张表两种形态 ⇒ 收口成配置。
    #
    # ★ 为什么默认 **7** 天（比另两张表短得多）：
    #   `email_tokens` 的行在 `used_at` 非空或 `expires_at` 过期之后**再无任何用途**
    #   （一次性凭据：已经被消费或已经失效，永远不会再被读）。
    #   它不像登录审计那样"留久点能复盘"，留久只是把"用户点过几次重发"的
    #   隐私残留堆在库里。7 天已足够覆盖"用户说邮件链接坏了"这类工单周期。
    #
    # ★ 为什么不是常量：同 `audit_retention_days` 的理由 —— 保留期属于
    #   运维/合规参数，要能改环境变量当天生效。
    #   ★ 下限由 `core/identity/retention.py::MIN_RETENTION_DAYS` 钳住：
    #     配成 0 / 负数会退化成"每次清空全表"，那是一条不可逆的销毁路径。
    email_token_retention_days: int = Field(
        default=7,
        description="邮件一次性 token（email_tokens）保留天数（用于定时清理；仅清已消费/已过期的行）",
    )

    # 业务接口强制鉴权开关（★ P0 安全修复 2026-09-15：默认 False → True）
    # True （默认）= 生产模式，全部业务接口要求 Bearer Token，未登录返回 401
    # False        = 演示模式，业务接口不校验 Token，方便本地演示与联调
    #
    # ★★ 为什么默认是 True（fail-closed）而不是 False：
    #     修复前默认 False ⇒ 部署时漏设环境变量 = 鉴权整个关掉，而且
    #     **没有任何报错**，等于把客户数据摆在公网上（实测：非 owner 带
    #     有效 token 可读全部业务数据，6/6 端点 200）。
    #     改默认 True 后：「忘记配置」= 安全（接口 401，立刻发现）；
    #     「要演示」= 显式设 AUTH_REQUIRED=false（一行，是有意为之）。
    auth_required: bool = Field(
        default=True,
        description="是否强制业务接口鉴权（默认开启，fail-closed；本地演示可显式设 false）",
    )

    # ====== 演示模式哨兵（★ 2026-09-17 新增）======
    #
    # ★ 背景：老板反馈「真实登录后在主页面仍看到别人的 4 个店铺」，
    #   排查后发现根因是「把演示模式表达成了『连 Authorization 头都不解析』」。
    #
    #   旧实现的 `require_auth_if_enabled` 在 auth_required=False 时**第一步就
    #   return None**，后果不是"演示模式不设限"，而是**连真实登录用户的身份也
    #   拿不到** —— 于是所有 `user is None → 放行` 的归属过滤分支被整体触发：
    #     · `accounts.filter_accessible_stores(db, None, stores)` → 返回全库店铺
    #       （★ 2026-09-17 已收紧为「无身份 ⇒ 空列表」；此处描述的是**当时**的形态）
    #       ⇒ 任何登录用户看到所有人的店铺（老板看到的就是这个）；
    #     · `accounts.can_access_store` / `_matches` → 恒真
    #       ⇒ 伪造 `X-Shop-ID` 即可读写任意店铺的业务数据（BOLA 回归）。
    #       （★ 2026-09-17 起已改为必须解析真身份；第 177 轮进一步收紧为
    #         「演示身份只放行演示店铺」，此处描述的是**当时**的形态。）
    #
    #   ⇒ 正确分工是**两件独立的事**，此前被搓成了一件事：
    #       · auth_required —— **匿名**访问（完全不带凭据）放不放行；
    #       · demo_mode     —— 是否承认前端那个演示哨兵串 `demo-token`。
    #
    #   两者的组合含义（四象限都有确定行为，没有"漏配就静默放行"）：
    #       auth_required=T + demo_mode=F → 生产：必须真身份，demo-token 一律 401
    #       auth_required=F + demo_mode=T → 本地演示：无凭据或 demo-token 均放行
    #       auth_required=F + demo_mode=F → 本地真实登录联调：匿名放行，
    #                                        但带了真 token 就**必须**被解析
    #       auth_required=T + demo_mode=T → 生产护栏拒绝启动（见下方校验）
    #
    # ★ 为什么 demo_mode 默认 False（fail-closed）：
    #   承认 `demo-token` 等于"任何知道这个字符串的人都能以匿名身份访问业务数据"。
    #   这个字符串就写在开源前端源码里，所以它**不能**是默认值。
    demo_mode: bool = Field(
        default=False,
        description="是否承认前端演示哨兵 token（demo-token）为匿名演示身份；默认关闭",
    )

    # ★ 第 182 轮：演示身份从「匿名旁路」升级为「**一个真实的账号**」。
    #
    #   需求原文：「演示模式也当作一个真实的账号，只是无需账号密码。也有全套功能」。
    #   于是 `demo-token` 不再映射到 `None`，而是映射到**这个 email 的主人**：
    #   他有 User 行、有 Account、有成员记录 ⇒ 整条归属链一行不改就能工作
    #   （`ensure_default_account` / `filter_accessible_skills` / `can_access_skill`）。
    #
    #   ⇒ 为什么必须由**服务端**决定是哪个人（而不是让前端传 `user_id`）：
    #     前端源码是公开的（`frontend/src/config/demoMode.ts` 里连哨兵串都写着）。
    #     直传 user_id 等于「任何人改一行就能让后端以任意身份行事」。
    #     正确分工：哨兵只表达「我要演演示账号」，**具体是谁由 .env 决定**。
    #
    #   ⇒ 为什么默认值写死成这个 email：它是库里唯一一个装满了演示数据的账号
    #     （第 175～177 轮把它定为演示店铺/技能的唯一落点）。默认值必须与
    #     `modules/stores/demo.py` 在**迁移前**用的 os.getenv 默认值逐字一致，
    #     否则本地不配 .env 时会出现「店铺挂在 A、技能挂在 B」的分叉
    #     —— 而演示身份只能命中其中一个。
    #
    #   ⇒ 与 `demo_mode` 的分工（两件独立的事，不能搓成一件）：
    #       demo_mode          —— 承不承认那个哨兵串；
    #       demo_account_email —— 承认之后，那份身份是**谁**。
    demo_account_email: str = Field(
        default="tenant-test-a@example.com",
        description=(
            "演示模式绑定的账号主人 email：demo-token 会被解析成这个真实用户。"
            "留空 ⇒ 演示身份降级为匿名（只见 is_demo 行），不影响真实账号。"
        ),
    )

    # ====== LLM (DashScope/Qwen) ======
    dashscope_api_key: str = Field(default="", description="阿里 DashScope API Key")
    llm_default_model: str = Field(default="qwen-max", description="默认 LLM 模型")
    llm_fallback_model: str = Field(
        default="qwen-plus",
        description="备用 LLM 模型（更快/更便宜）。第 238 轮起**真的被消费**",
    )
    llm_fast_first_round: bool = Field(
        default=True,
        description=(
            "第一轮决策是否改用备用（更快）模型 —— 见 `BaseAgent.FAST_FIRST_ROUND`。"
            "关掉即回到「所有轮次都用默认模型」"
        ),
    )
    llm_max_tokens: int = Field(default=4096, description="最大 Token 数")
    llm_temperature: float = Field(default=0.7, description="生成温度")
    llm_timeout_seconds: int = Field(default=120, description="LLM 调用超时(秒)")

    # ====== RAG 配置 ======
    rag_chunk_size: int = Field(default=500, description="文本分块大小")
    rag_chunk_overlap: int = Field(default=50, description="分块重叠大小")
    rag_top_k: int = Field(default=5, description="检索返回数量")

    # ====== 限流 & 计费 ======
    rate_limit_requests_per_minute: int = Field(default=60, description="每分钟请求限制")
    rate_limit_requests_per_day: int = Field(default=1000, description="每日请求限制")
    rate_limit_enabled: bool = Field(
        default=True,
        description="是否启用请求速率限制中间件（测试/压测时可关闭）",
    )
    request_log_enabled: bool = Field(
        default=True,
        description="是否启用请求日志中间件",
    )
    free_tier_monthly_quota: int = Field(default=100, description="免费套餐月度额度")

    # ====== 支付网关 ======
    payment_gateway: str = Field(
        default="mock",
        description="支付网关实现：mock（模拟支付，默认）/ alipay（支付宝当面付，已接入）"
                    " / stripe / wechat（待接入）",
    )

    # ====== 支付宝（当面付 / 扫码支付）======
    #
    # ★ 密钥字段的格式（`.env` 里必须写成一行，换行用字面量 `\n` 转义）：
    #     PAYMENT_ALIPAY_APP_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----
    #   解析由 platforms/payment/alipay.py::_load_private_key 统一处理，
    #   它同时接受「带 PEM 头尾」「纯 base64（密钥工具里复制出来的那种）」
    #   两种形态 —— 支付宝开放平台的密钥工具给的就是后者，直接贴进 .env
    #   是最常见的用法，要求用户自己加头尾是没必要的摩擦。
    payment_alipay_app_id: str = Field(
        default="", description="支付宝应用 APPID（开放平台应用详情页）"
    )
    payment_alipay_app_private_key: str = Field(
        default="", description="应用私钥（PKCS#8；RSA2 请求签名用）"
    )
    payment_alipay_public_key: str = Field(
        default="",
        description="支付宝公钥（**回调验签**用）。注意不是应用公钥 —— 用错了"
                    "表现为「每一条回调都验签失败」，而被误读成支付宝在乱发通知",
    )
    payment_alipay_gateway: str = Field(
        default="https://openapi.alipay.com/gateway.do",
        description="支付宝网关地址。沙箱环境为 "
                    "https://openapi-sandbox.dl.alipaydev.com/gateway.do",
    )
    payment_notify_url: str = Field(
        default="",
        description="支付回调地址。留空 = 由 PUBLIC_BASE_URL 派生（推荐）；"
                    "两者都为空 ⇒ 生产环境拒绝启动（收不到回调就永远不激活订阅）",
    )
    payment_return_url: str = Field(
        default="",
        description="用户支付完成后跳回的前端页面地址（仅用于展示引导）。"
                    "★ 截至 2026-09-26 本字段**无任何消费点** —— 当面付是扫码支付，"
                    "不需要跳回地址（全仓唯一提到它的地方是 gateway.py 的一行注释）。"
                    "字段保留是为了将来接入 JSAPI / H5 这类**会跳转**的支付方式；"
                    "在那之前，把它当成一个不生效的占位即可，别在部署文档里承诺它有用。",
    )

    # ====== 文件存储 ======
    upload_dir: str = Field(default="./uploads", description="文件上传目录")
    max_upload_size_mb: int = Field(default=10, description="最大上传文件大小(MB)")
    allowed_file_types: list[str] = Field(
        default=["pdf", "csv", "xlsx", "txt", "json", "jpg", "png"],
        description="允许上传的文件类型"
    )
    # 对外可访问的站点根地址（形如 https://api.example.com）。
    # 用途：声音复刻（CosyVoice）只接受「公网可访问的音频 URL」，不接受本地上传流，
    # 所以样本落盘后必须拼成公网地址。留空 = 未配置 → 语音克隆会显式报错并说明原因，
    # **不会**静默退回 localhost（那样服务端根本取不到文件）。
    public_base_url: str = Field(
        default="",
        description="对外可访问的站点根地址，用于生成第三方可回源的资源 URL（如声音复刻样本）",
    )

    # ====== 样本公网镜像（本地开发用，见 docs/voice-sample-mirror.md）======
    # 问题：CosyVoice 只收【公网可访问】的音频 URL，且是【服务端主动来拉】。
    #       本地开发的 localhost 它够不着 ⇒ 不解决就永远跑不通。
    # 方案：样本落盘后【额外推一份】到云端静态目录，public_base_url 指向云端。
    #       判据：本机没公网入口，但云端有 ⇒ 让云端只当"文件柜"，业务逻辑全在本地。
    # ⚠️ 与 PUBLIC_BASE_URL 的分工：
    #       PUBLIC_BASE_URL          = 拼给 DashScope 的地址前缀（指向【云端】）
    #       VOICE_SAMPLE_MIRROR_*    = 怎么把文件【送上去】（ssh/scp 凭据）
    #    ⚠️ 未配置 ssh_host 时，同步静默跳过（本地仍可用，只是克隆会失败——
    #       失败原因由 sample_public_url 的显式报错给出，不在这里制造第二个错误）。
    voice_sample_mirror_ssh_host: str = Field(
        default="",
        description="样本镜像目标主机（形如 root@1.2.3.4）。留空 = 不做镜像同步",
    )
    voice_sample_mirror_ssh_port: int = Field(
        default=22, description="样本镜像 SSH 端口"
    )
    voice_sample_mirror_remote_dir: str = Field(
        default="/www/wwwroot/voice-samples",
        description="样本镜像的远端目录（需与 nginx 站点根目录一致）",
    )
    voice_sample_mirror_ssh_key: str = Field(
        default="",
        description="样本镜像用的 SSH 私钥路径（留空 = 用默认 ssh-agent / ~/.ssh/id_*）",
    )

    # ====== 附加模块总开关 ======
    # 语音克隆（客服音色）属于**附加模块**：装了也不生效，必须显式打开。
    # 关闭时：前端入口直接隐藏 + 后端路由不注册（404 语义）；数据表保留，不做破坏性迁移。
    voice_clone_enabled: bool = Field(
        default=False,
        description="是否启用语音克隆附加模块（默认关闭）",
    )

    # ====== 可观测性（★ P1-8 补充 2026-09-15）======
    #
    # 日志：已有 loguru 全局配置（core/logger.py），这里只暴露两个可调项。
    #   - log_dir 必须可配：容器里 CWD 未必是项目根，写死 "logs" 会让日志
    #     落到意料之外的位置（或因只读挂载直接写入失败）。
    #   - log_json 打开后逐行 JSON，供 Filebeat / Promtail / SLS 采集；
    #     本地开发保持彩色单行，人眼看。
    log_dir: str = Field(default="logs", description="日志目录（相对 CWD 或绝对路径）")
    log_level: str = Field(default="", description="日志级别，留空=按 debug 自动（debug→DEBUG，否则 INFO）")
    log_json: bool = Field(default=False, description="是否输出 JSON 结构化日志（生产采集建议 true）")
    #   - log_file_max_mb 是**防爆闸门**：loguru 的 rotation 字符串只能表达
    #     「时间」或「体积」**其中之一**。原先写 rotation="00:00" 等于完全不设体积上限，
    #     实测单日单文件涨到 435 MB（backend/logs/2026-09-22.log），1.2 GB 里九成来自它。
    log_file_max_mb: int = Field(
        default=200,
        ge=1,
        description="单个日志文件体积上限（MB），超限即轮转（防止单日日志无界增长）",
    )

    # 指标：/metrics 按 Prometheus 文本格式暴露（自研，零新依赖）。
    #   - metrics_enabled=false 时不注册该路由（404 语义）
    #   - metrics_token 非空时要求 `Authorization: Bearer <token>`
    #   - ★ P1-d（2026-09-16）：生产环境 + enabled + token 为空 ⇒ **拒绝启动**。
    #     修复前这里只打一句 WARNING（"门禁存在 ≠ 在执行"）：漏配的后果是
    #     QPS/错误率/接口清单**安静地**对任何扫到该路径的人可见。
    #     判据同 auth_required：「漏配的默认结果必须是明显失败，不是安静暴露」。
    #     不需要指标端点请显式设 METRICS_ENABLED=false。
    metrics_enabled: bool = Field(default=True, description="是否注册 /metrics 指标端点")
    metrics_token: str = Field(default="", description="/metrics 访问令牌，留空=不鉴权")

    # Sentry：留空则完全不初始化（不 import、不发网络请求、零开销）。
    #   填了 DSN 但没装 sentry-sdk → 启动时打 WARNING 说明缺哪个包（显式降级，不静默）。
    sentry_dsn: str = Field(default="", description="Sentry DSN，留空=不上报")
    sentry_traces_sample_rate: float = Field(
        default=0.0, description="Sentry 性能追踪采样率，0=只上报错误"
    )

    # ====== AIGC 异步任务（★ P1-5 补充 2026-09-15）======
    #
    # 为什么要有「同时进行中任务数」上限：
    #   出图按张计费（≈¥0.14/张），而 worker 并发有限。一个用户连点 10 次就会把
    #   队列占满、其他用户全部排队 —— 拦在入口比为别的用户事后排队便宜得多。
    # 为什么必须可配而不是写死：
    #   这是**配额**，不同套餐/不同客户等级需要不同值；写死常数意味着改配额要改代码 + 重新发布。
    #   上限口径见 modules/aigc_media/job_service.py::count_inflight（只数 pending/running）。
    aigc_max_inflight_per_user: int = Field(
        default=3,
        description="同一用户同时进行中（pending/running）的 AIGC 任务数上限，超出返回 429",
    )

    # ====== Amazon SP-API ======
    spapi_lwa_client_id: str = Field(default="", description="LWA Client ID")
    spapi_lwa_client_secret: str = Field(default="", description="LWA Client Secret")
    spapi_refresh_token: str = Field(default="", description="LWA Refresh Token")
    spapi_aws_access_key: str = Field(default="", description="AWS Access Key ID")
    spapi_aws_secret_key: str = Field(default="", description="AWS Secret Access Key")
    spapi_aws_region: str = Field(default="us-east-1", description="AWS Region (SP-API)")
    spapi_use_sandbox: bool = Field(default=True, description="使用 Sandbox 环境")


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()


# 全局配置实例（方便直接导入）
config = get_settings()
