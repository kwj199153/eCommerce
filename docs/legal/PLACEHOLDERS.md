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

**当前共 22 个占位符**（累计已处置 14 项：第 351 轮 5 项 + 第 352 轮 9 项，逐项依据见文末「已处置」）。分六组（A–F）：

---

## A. 运营主体与联系信息（最先填，其余文件都要用）

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
| `COMPANY_LEGAL_NAME` | 运营主体的**工商全称** | 业务方 | 福州某某科技有限公司 |
| `COMPANY_REGISTERED_ADDRESS` | 注册地址（与营业执照一致） | 业务方 | 福建省福州市… |
| `COMPANY_REGISTRATION_NO` | 统一社会信用代码 | 业务方 | 91350100MA… |
| `COMPANY_CONTACT_EMAIL` | 对外联系/客服邮箱 | 业务方 | support@example.com |
| `COMPANY_CONTACT_PHONE` | 对外联系电话 | 业务方 | 0591-… |
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

## D. 第三方与子处理者

| 占位符 | 含义 | 填写方 | 示例 |
|---|---|---|---|
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

## 已处置（第 351–352 轮）

> 下列字段**不再需要业务方给值**：要么能由仓库自身客观确定（已按代码取证回填），
> 要么经核对后与产品实际不符（已按事实改写）。
> ★ 保留本表是为了留住「下一份合同复用同一套模板」的锚点，避免同一字段被反复重新推导；
> 同时也是 L3 门禁的登记面 —— 处置过的字段若被重新写回模板，会因为「未登记」而报红。

| 占位符 | 处置 | 依据（可复现） |
|---|---|---|
| `SERVICE_NAME` | 回填「店管家 AI」 | `frontend/src/views/Workspace.vue`（logo 文案）、`frontend/src/config/tourSteps.ts`、`README.md` |
| `YEAR` | 回填「2026」 | `git log --reverse` 首条提交日期 2026-09-10（首个发布年份） |
| `PAYMENT_PROVIDER` | 回填「支付宝（Alipay）」 | `backend/core/config.py`：`KNOWN_UNIMPLEMENTED_GATEWAYS` 只含 stripe / wechat / wechatpay / paypal，`PAYMENT_NOTIFY_PATH` 指向 alipay ⇒ 唯一已接入网关 |
| `EMAIL_PROVIDER` | 回填「阿里云邮件推送（DirectMail）」 | `backend/core/config.py`：`EMAIL_PROVIDER` 可选值仅 console / aliyun_dm / disabled，生产要求 `aliyun_dm` + `ALIYUN_DM_*`；实现在 `backend/core/identity/mailer.py` |
| `STORAGE_PROVIDER` | **改写为「无第三方对象存储」** | 全仓无 oss2 / boto3 / minio / qcloud_cos 引用；上传素材落本机 `uploads/`（`backend/core/storage/paths.py`），经 `/static` 提供 |
| `SUBPROCESSOR_LIST_URL` | 指向本仓 `subprocessors.md` | 新增 `docs/legal/subprocessors.md`（对外发布时须替换为可公开访问的 URL） |
| `CROSS_BORDER_DESTINATION` | **改写为「不涉及出境」** | 子处理者均境内部署：邮件 `aliyun_dm_region` 默认 `cn-hangzhou`、`dm.aliyuncs.com`；模型 / 图像 / 语音走 `dashscope.aliyuncs.com` |
| `CROSS_BORDER_MECHANISM` | **改写为「当前不涉及」** | 同上；原文的「标准合同 / 安全评估 / 认证」三选一保留为**未来情形**的表述 |
| `CROSS_BORDER_LIST_URL` | **改写为「不涉及」** | 同上 |

★ 计数口径：本文件顶部自报的个数 = **实测**出现在模板里的 `{{...}}` 个数（L4 门禁钉住）。
`subprocessors.md` 里的服务商表**不使用占位符**（服务商名已由代码取证确定）。

## 进度（第 352 轮更新）

| 核对项 | 状态 | 说明 |
|---|---|---|
| ① 占位符清零 | ⏳ **22/36** | 累计 14 项已处置（可确定项按代码取证回填、出境三项如实改写）；余 22 项需业务方/法务给值 |
| ② C 组与后端配置对账 | ✅ **已落地为门禁** | `backend/tests/test_legal_docs.py`：
从文档读出「由哪个配置决定」→ 去 `core/config.py` 取默认值比对，不一致即红 |
| ③ 删除 `<details>` 工程侧核对表 | ✅ 已删除 | 同一道门禁也钉住它不得回流 |

★ 新增第 4 条**机器核对**：模板里的占位符集合必须**全部登记在本表** —— 防「悄悄
多出来的未填项」（本表自己写的「新增字段必须先登记」原来只是一句注释约定，现在有牙齿）。

---

## 已知缺口（写文本时暴露出来的产品问题，需拍板）

| 缺口 | 现状 | 影响 | 建议 |
|---|---|---|---|
| 对话/Agent 记忆无留存期策略 | 随账号存续，无定时清理 | 隐私政策无法给出具体天数 | 要么定策略 + 落地清理任务，要么政策改表述 |
| 账号注销后的数据删除无宽限期实现 | 无实现 | `ACCOUNT_DELETION_GRACE_DAYS` 只能填"立即" | 实现注销流程或如实表述 |
| 数据出境路径未评估 | ✅ **已初判不涉及出境** | 子处理者均境内部署（见 [`subprocessors.md`](./subprocessors.md)）；更换服务商须重评 | 签约前复核部署地域，变更时按隐私政策第五节更新 |
| 子处理者清单无公开页 | ✅ **已建 [`subprocessors.md`](./subprocessors.md)**（逐条附代码取证锚点） | 对外发布时仍须把该文件发布为可公开访问的 URL | 上线前把该文件挂到站点 legal 路径 |
