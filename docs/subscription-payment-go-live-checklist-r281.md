# 订阅计费支付 · 上线清单（第 281 轮盘点）

> 盘点时间：2026-09-26 · 依据：磁盘源码 + 运行中服务实测（不凭记忆）
> 一句话结论：**技术链路已闭环，差的是「外部条件」+ 3 处运营面缺口。**

---

## 一、已经在位（磁盘核实，无需再动）

| 环节 | 实现 | 关键文件 |
|---|---|---|
| 下单出码 | `alipay.trade.precreate` 拿 `qr_code`，**自己实现 RSA2 签名**（不依赖 `alipay-sdk-python`） | `platforms/payment/alipay.py` |
| 二维码 | 后端直出 **SVG data URI**（`qrcode` 纯 Python，SVG 路径不需要 pillow） | `modules/billing/qr.py` |
| 支付回调 | 免鉴权但**强制验签** + `app_id` 比对 + 返回**纯文本** `success`（返 JSON 会被重投 24h） | `payment_router.py::alipay_notify` |
| 状态机 | 两段式 pending→paid，`charged=false` 时用 `requires_confirmation` 区分「未付」与「失败」 | `payments.py` |
| 定时任务 | ①超时单回收（分钟级）②到期清算 ③日对账（排在清算之后） | `modules/billing/tasks.py` + `core/redis.py::beat_schedule` |
| 时间口径 | 所有出 JSON 的时间走唯一真源 `utc_iso`（naive 补 UTC 偏移） | `core/timefmt.py` |
| 前端扫码 | 弹窗 + 倒计时（**现算不自减**）+ 3 秒轮询 + 409 当「已支付」处理 | `views/Subscription.vue` |
| 演示身份 | 无需扫码，点一下即开通（后端直通 `MockGateway` ⇒ `charged=true`） | `core/auth/demo_identity.py` |
| 生产护栏 | `PAYMENT_GATEWAY=alipay` 但缺凭证/回调地址 ⇒ **拒绝启动** | `core/config.py::_enforce_production_safety` |

---

## 二、真正还缺的（8 项，按优先级）

### P0-1 · 发票 PDF 从未生成
- `Invoice.pdf_url` 字段存在，但**全仓没有写入点**（只有读取与透传）⇒ 前端「下载发票」按钮 `v-if="record.pdf_url"` **永不出现**。
- ⚠️ 更根本的是**合规问题**：中国增值税发票必须由税局系统开具，**自己生成 PDF 发票不合规**。
- ⇒ 这是**产品决策**（对接第三方开票服务？还是改成"申请开票"工单？），不是补个函数就能完。

### P0-2 · 没有自动续费
- grep `自动续费|auto_renew|签约|代扣|agreement` —— **零命中**。
- 当面付（扫码）是**一次性收款**，不支持代扣；到期清算直接把 `active → expired`，用户必须**手动再付**。
- ⇒ 若要自动续费，需另签「支付宝周期扣款 / 免密支付」，属**新接入**（不是本链路的延伸）。

### P0-3 · Celery worker / beat 没有常驻运行
- `start-backend.bat` 只起 uvicorn，**不含 celery**；当前进程表只有 2 个 python，**无 worker/beat**。
- ⇒ **3 条定时任务全都没在跑**：超时单不回收、到期不清算、对账不跑。
- ⚠️ 最隐蔽的点：**不跑也不报错**，只是「该消失的待支付单一直挂着」，「到期订阅一直能用」。

### P1-4 · 「添加支付方式」是死按钮
- `handleAddPayment()`（`Subscription.vue:1067`）只弹一句 toast，注释自述「实际场景会跳转到 Stripe」。

### P1-5 · 支付方式列表没有真实来源
- 后端 `add_payment_method` docstring 自述「此处为模拟闭环：接受前端传的卡信息直接落库」。
- 前端文案却写「添加信用卡或借记卡**用于自动续费**」—— 与支付宝当面付路径**双重矛盾**（既没有卡，也没有自动续费）。

### P1-6 · `.env.example` 缺支付配置段
- 样例里只有 `PUBLIC_BASE_URL=`，缺 `PAYMENT_GATEWAY` / 3 个 `PAYMENT_ALIPAY_*` / `PAYMENT_NOTIFY_URL` ⇒ 运维照样例配不出来。

### P2-7 · `payment_return_url` 是死配置
- 仅 `gateway.py` 一处注释提及，无消费点（当面付不需要 return_url）。字段可留，但应注明「当前未消费」。

### P2-8 · 没有退款流程
- 只有 `status='refunded'` 枚举值，**无端点、无入口** ⇒ 退款只能在支付宝商户后台人工做。
- 当前可接受，但**必须写进运营手册**。

---

## 三、你要准备的（外部条件 · 7 项）

### ☐ 1. 支付宝企业账号 + 签约「当面付」
- 开放平台 **企业账号**，完成实名认证。
- 签约 **当面付** 产品 —— **需要营业执照**；个人账号签不了。
- 建应用，拿到 **APPID**。

### ☐ 2. 三件凭证
| 凭证 | 说明 |
|---|---|
| APPID | 应用详情页 |
| **应用私钥** | **PKCS#8** 格式，用于请求签名。`.env` 里写成一行，换行用字面量 `\n` |
| **支付宝公钥** | ⚠️ 是「**支付宝公钥**」，**不是**「应用公钥」。用错的表现是「**每一条回调都验签失败**」，而会被误读成「支付宝在乱发通知」 |

### ☐ 3. 公网 HTTPS 域名（已备案）+ 证书
- 支付宝回调**要求 https**。
- 当前 `PUBLIC_BASE_URL=http://111.229.201.117`（**http + 裸 IP**）⇒ 在生产护栏下会被**拒绝启动**。

### ☐ 4. 服务器安全组 / 防火墙放行 443
- 回调是**支付宝主动入站**，放行了才能收到。

### ☐ 5. 生产环境变量（5 项，任一不满足都会拒绝启动）
```dotenv
ENVIRONMENT=production
DEBUG=false
DEMO_MODE=false          # 演示模式承认前端哨兵串 demo-token 为匿名身份，等于敞开数据
AUTH_REQUIRED=true
JWT_SECRET_KEY=<独立高强度随机值>
PUBLIC_BASE_URL=https://你的域名
```
> 当前 `.env` 全是开发值：`development / debug=true / demo_mode=true / auth_required=false`。

### ☐ 6. Celery worker + beat 常驻方案
- Windows：`nssm` 注册为服务；Linux：`systemd` / `supervisor`。
- 至少要保证：worker 消费 `default` 队列 + beat 按 `beat_schedule` 投递。

### ☐ 7. 对公结算账户
- 企业支付宝绑定的收款账户（提现用）。

---

## 四、切换配置样例

```dotenv
# ---- 网关 ----
PAYMENT_GATEWAY=alipay

# ---- 应用凭证 ----
PAYMENT_ALIPAY_APP_ID=2021000000000000
PAYMENT_ALIPAY_APP_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIIEv...\n-----END PRIVATE KEY-----
PAYMENT_ALIPAY_PUBLIC_KEY=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...

# ---- 网关地址（沙箱联调时改这个）----
PAYMENT_ALIPAY_GATEWAY=https://openapi.alipay.com/gateway.do
# 沙箱：https://openapi-sandbox.dl.alipaydev.com/gateway.do

# ---- 回调地址 ----
# 留空即由 PUBLIC_BASE_URL 派生（推荐）；两者都空 ⇒ 生产拒绝启动
PAYMENT_NOTIFY_URL=
PUBLIC_BASE_URL=https://你的域名
```

回调最终地址 = `PUBLIC_BASE_URL` + `/api/v1/billing/webhook/alipay`

---

## 五、验证步骤（上线前逐条跑）

1. **配置自检**：以 `ENVIRONMENT=production` 启动。缺凭证 / 回调不是绝对 URL / `DEMO_MODE=true` 等，都会在**启动期直接报错**——这一步报错才是对的。
2. **回调连通性**：在支付宝开放平台用「沙箱」或商户后台的**回调测试**功能打一次，确认收到的是**纯文本 `success`**（不是带引号的 JSON）。
3. **扫一笔真单**：下单 → 扫码 → 确认 `invoices.status` 由 `pending` 变 `paid`，`subscriptions` 生效。
4. **验时间口径**：`GET /api/v1/billing/payment/{invoice_id}`，确认 `created_at` / `expires_at` **带 `+00:00` 偏移**。
   > 无偏移 ⇒ 浏览器按本地时区解析 ⇒ **倒计时一打开就显示「已过期」**（金额、状态全对，所以业务断言发现不了）。
5. **起 worker + beat**：确认三条任务被调度（看 worker 日志里的任务名）。
6. **超时单回收**：造一张 pending 单，等过 TTL（30 分钟）确认被回收。
7. **对账**：手动触发 `reconcile_alipay_orders`，确认能补漏单、揪幽灵单。

---

## 六、当前环境事实（记一笔，少踩坑）

- 后端真解释器：`D:\work\anaconda\anaconda3\envs\reactAgents\python.exe`（`start-backend.bat` 里写死的）。
- 依赖：`cryptography` / `qrcode` / `celery` **已装**；`alipay` SDK **刻意不装**（本仓自实现 RSA2 签名，见 `requirements.txt` 注释）。
- 运行中的服务：8000（uvicorn）、5173（vite）、5432（my-postgres）、6379（my-redis）；**无 worker/beat**。
- 本仓**没有任何发票 PDF 生成依赖**（`weasyprint` / `reportlab` / `fpdf` 零命中）。
