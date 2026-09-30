# 待填清单（法务文本占位符）

> 本清单由**工具现算**，不是手抄。复核命令（在仓库根执行）：
>
> ```bash
> cd docs/legal
> grep -ohE '\{\{[A-Z0-9_]+\}\}' *.md LICENSE | sed 's/[{}]//g' | sort -u
> ```
>
> 回填完成后该命令应**输出为空**；若仍有输出，说明有漏填项。
> ★ 新增字段必须先写进对应文档、再登记到本表，否则就是"悄悄多出来的未填项"。

**当前共 36 个占位符。** 分五组：

---

## A. 运营主体与联系信息（最先填，其余文件都要用）

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
| `COMPANY_LEGAL_NAME` | 运营主体的**工商全称** | 业务方 | 福州某某科技有限公司 |
| `COMPANY_REGISTERED_ADDRESS` | 注册地址（与营业执照一致） | 业务方 | 福建省福州市… |
| `COMPANY_REGISTRATION_NO` | 统一社会信用代码 | 业务方 | 91350100MA… |
| `COMPANY_CONTACT_EMAIL` | 对外联系/客服邮箱 | 业务方 | support@example.com |
| `COMPANY_CONTACT_PHONE` | 对外联系电话 | 业务方 | 0591-… |
| `YEAR` | 版权年份（首个发布年份） | 业务方 | 2026 |
| `SERVICE_NAME` | 产品对外名称 | 业务方 | 店管家 AI |
| `SERVICE_DOMAIN` | 服务域名 | 业务方 | app.example.com |

## B. 生效与法律参数

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
| `EFFECTIVE_DATE` | 文本生效日期（三份对外文本建议同一天） | 法务 | 2026-11-01 |
| `GOVERNING_LAW` | 适用法律 | 法务 | 中华人民共和国法律 |
| `JURISDICTION_COURT` | 争议管辖机构 | 法务 | 被告住所地有管辖权的人民法院 |
| `NOTICE_DAYS` | 条款重大变更的提前通知天数 | 法务 | 30 |
| `RESPONSE_DAYS` | 响应数据主体请求的期限（日历日） | 法务 | 15 |
| `DPO_CONTACT` | 个人信息保护负责人及其联系方式 | 业务方 | privacy@example.com（张某某） |

## C. 数据与留存期（★ 必须与后端配置逐一核对）

> **这几项不能拍脑袋填**：政策里写的天数必须 **≥/==** 生产环境里对应配置的实际值。
> 写长了 = 虚假陈述；写短了 = 承诺未履行。回填后请按下表右列核对。

| 占位符 | 含义 | 与之核对的后端配置 |
|---|---|---|
| `DATA_STORAGE_LOCATION` | 数据存储地（地域/机房） | 部署实际情况 |
| `AUDIT_RETENTION_DAYS` | 审计日志留存天数 | `AUDIT_RETENTION_DAYS`（`config.audit_retention_days`，默认 90） |
| `LOGIN_RETENTION_DAYS` | 登录尝试记录留存天数 | `LOGIN_ATTEMPT_RETENTION_DAYS`（默认 30） |
| `EMAIL_TOKEN_RETENTION_DAYS` | 邮件一次性令牌留存天数 | `EMAIL_TOKEN_RETENTION_DAYS`（默认 7） |
| `CHAT_RETENTION_DAYS` | 对话/Agent 记忆留存天数 | 会话数据的实际清理策略（当前为随账号存续，需拍板） |
| `ACCOUNT_DELETION_GRACE_DAYS` | 注销后删除的宽限期 | 产品策略（需拍板） |
| `CROSS_BORDER_DESTINATION` | 数据出境目的地（如涉及） | 模型/存储服务商的部署地域 |
| `CROSS_BORDER_MECHANISM` | 出境合法性基础 | 法务（标准合同 / 安全评估 / 认证） |
| `CROSS_BORDER_LIST_URL` | 出境清单的在线地址 | 业务方维护 |

## D. 第三方与子处理者

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
| `PAYMENT_PROVIDER` | 支付服务商 | 业务方 | 支付宝（Alipay） |
| `EMAIL_PROVIDER` | 邮件发送服务商 | 业务方 | 阿里云邮件推送 |
| `STORAGE_PROVIDER` | 对象存储服务商 | 业务方 | 阿里云 OSS |
| `SUBPROCESSOR_LIST_URL` | 子处理者清单在线地址（须可公开访问并在变更前更新） | 业务方 | https://example.com/legal/subprocessors |
| `SUBPROCESSOR_NOTICE_DAYS` | 变更子处理者的提前通知天数 | 法务 | 15 |
| `BREACH_NOTICE_HOURS` | 数据泄露通知客户的时限（小时） | 法务 | 24 |

## E. 商务与责任参数（通常在 DPA / 服务条款中体现）

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
| `SLA_AVAILABILITY` | 目标可用性（如提供） | 业务方 | 99.5% |
| `LIABILITY_MONTHS` | 责任限额回溯的月数 | 法务 | 12 |
| `CONFIDENTIALITY_YEARS` | 保密义务的存续年数 | 法务 | 3 |
| `AUDIT_NOTICE_DAYS` | 客户现场审计的提前通知天数 | 法务 | 30 |
| `AUDIT_MAX_TIMES` | 每客户每年审计次数上限 | 法务 | 1 |

## F. 客户侧字段（仅在签署 DPA 时按该客户填写，不随模板定稿）

| 占位符 | 含义 | 填写方 |
|---|---|---|
| `CLIENT_LEGAL_NAME` | 客户主体工商全称 | 签约时填写 |
| `CLIENT_REGISTERED_ADDRESS` | 客户注册地址 | 签约时填写 |

---

## 回填后的三项必做核对

1. **占位符清零**：跑上面的 grep，输出为空。
2. **C 组与后端配置对账**：把 `AUDIT_RETENTION_DAYS` / `LOGIN_ATTEMPT_RETENTION_DAYS` /
   `EMAIL_TOKEN_RETENTION_DAYS` 的生产取值与文档中的天数**逐条比对**（这三项在本仓
   已由定时清理任务落地，是可验证的客观事实）。`CHAT_RETENTION_DAYS` 与
   `ACCOUNT_DELETION_GRACE_DAYS` 目前**尚无实现**——若不做，就必须把政策里的相应表述
   改为"随账号存续，注销后删除"，**不要**写一个做不到的天数。
3. **删除隐私政策里的「工程侧事实核对表」**：那份 `<details>` 块仅供审阅，
   对外发布前必须移除。

---

## 已知缺口（写文本时暴露出来的产品问题，需拍板）

| 缺口 | 现状 | 影响 | 建议 |
|---|---|---|---|
| 对话/Agent 记忆无留存期策略 | 随账号存续，无定时清理 | 隐私政策无法给出具体天数 | 要么定策略 + 落地清理任务，要么政策改表述 |
| 账号注销后的数据删除无宽限期实现 | 无实现 | `ACCOUNT_DELETION_GRACE_DAYS` 只能填"立即" | 实现注销流程或如实表述 |
| 数据出境路径未评估 | 若模型/存储含境外节点则需评估 | 无合法性基础即出境 = 违规 | 先确认服务商部署地域，再决定是否需要评估 |
| 子处理者清单无公开页 | 无 | DPA 引用了一个不存在的 URL | 建一个静态页（可放 `docs/legal/subprocessors.md` 并发布） |
