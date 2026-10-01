# 子处理者清单（Sub-processors）

> **草案状态**：工程侧模板，未经法务审阅，不得对外发布。
> 本文件与 [`privacy-policy.md`](./privacy-policy.md) 第四节、
> [`data-processing-agreement.md`](./data-processing-agreement.md) 第五条配套使用；
> **三处必须一致** —— 不一致时以本文件为准（它是唯一逐条附「代码取证锚点」的版本）。
> 字段说明见 [`PLACEHOLDERS.md`](./PLACEHOLDERS.md)。

## 1. 收录口径

本清单逐条列出**店管家 AI**（下称"本服务"）为运行服务而使用的**子处理者**
（受托处理者再委托的第三方），并为每一条附上**代码取证锚点** ——
即"能在本仓库的哪一处看到这个外部依赖真的会被调用"。

★ 收录口径（**这条口径是本文件能被客观核对的前提**）：

> **只有真的会向该方发送数据的依赖才算子处理者。**
> 仅出现在依赖清单、接口骨架或设计文档里、尚未接通外部调用的服务**不列入**
> —— 未接通 = 没有数据流动 = 不是子处理者。

这条口径把"清单是否完整"从"凭记忆"变成"可在代码里查证"。

## 2. 现行子处理者

| # | 子处理者 | 处理活动 | 涉及的数据 | 部署地域 | 代码取证锚点 |
|---|---|---|---|---|---|
| 1 | 阿里云百炼（DashScope，Qwen 系列） | 大模型推理、文本 / 向量嵌入 | 指令文本，以及为完成该次指令所必需的上下文（可能含商品标题、评价正文） | 中华人民共和国境内 | `backend/ai_infra/llm/dashscope_client.py`、`backend/core/config.py` |
| 2 | 阿里云百炼（图像生成模型） | 文生图 / 图像编辑 | 上传的商品图与生成参数 | 同上 | `backend/modules/aigc_media/image_client.py` |
| 3 | 阿里云百炼（语音模型 CosyVoice） | 语音合成 / 声音复刻 | 音色样本与待播报文本 | 同上 | `backend/modules/voice_clone/client.py` |
| 4 | 阿里云邮件推送（DirectMail） | 事务邮件发送 | 收件邮箱、邮件正文（验证 / 安全 / 账单） | 中华人民共和国境内（`cn-hangzhou`） | `backend/core/identity/mailer.py`、`backend/core/config.py` |
| 5 | 支付宝（Alipay，当面付） | 订阅收款与对账 | 订单号、金额、渠道返回的交易号（**不含**银行卡号 / 支付密码） | 中华人民共和国境内 | `backend/platforms/payment/alipay.py`、`backend/core/config.py` |
| 6 | Amazon SP-API | 经客户授权拉取店铺数据 | 商品、报价、库存、订单、广告、评价 | 由客户授权的站点所属区域决定 | `backend/platforms/amazon/sp_api/` |
| 7 | Shopee Open Platform | 经客户授权拉取店铺数据 | 同上（Shopee 站点） | 由客户授权的站点所属区域决定 | `backend/platforms/shopee/client.py` |

★ 第 1–5 项的服务端均在**中华人民共和国境内**（域名均为 `*.aliyuncs.com`；邮件区域默认
`cn-hangzhou`）⇒ 当前**不涉及个人信息出境**（见隐私政策第五节、DPA 第九条）。
★ 第 6–7 项的地域取决于**客户自己**授权的站点（例如北美站）。该部分数据由客户在其与平台
的既有关系中产生，本服务是按客户指示拉取与处理，不构成本服务主动将境内个人信息**传出**境外。

## 3. 明确**不**列入的项（以及为什么）

| 项 | 不是子处理者的理由 |
|---|---|
| 第三方对象存储（OSS / S3 / COS / MinIO） | **本服务不使用任何第三方对象存储**：仓库内无对应 SDK 依赖；上传素材与生成结果落本机 `uploads/`（`backend/core/storage/paths.py`），经服务自身 `/static` 提供 |
| Shopify 适配器 | 仅有骨架：`backend/platforms/shopify/client.py` 的全部方法 `raise NotImplementedError` ⇒ **没有数据流动** |
| TikTok Shop 适配器 | 同上：`backend/platforms/tiktok/client.py` 的全部方法 `raise NotImplementedError` |
| `mock` 支付网关 | 仅本地 / 演示环境使用（`PAYMENT_GATEWAY=mock`），不产生对外提供 |
| CDN / WAF / 独立反向代理 | 当前部署形态（`docker-compose.yml` + Nginx 同源反代）不引入独立第三方；若上线时启用第三方 CDN/WAF，须回到本表补登记 |

## 4. 变更规则

1. 处理者**新增或更换**子处理者前，按 [`data-processing-agreement.md`](./data-processing-agreement.md)
   第五条提前 `SUBPROCESSOR_NOTICE_DAYS` 日通知客户（该天数由法务给值）。
2. 本清单必须与**代码**保持一致：新增外部依赖**并接通数据流**时，应在**同一提交**内更新
   本文件 —— 否则就是"未披露的对外提供"。
3. 对外发布时，本文件应发布为**可公开访问的 URL**，并把 `privacy-policy.md` 与
   `data-processing-agreement.md` 中的仓库内相对链接替换为该 URL。

## 5. 核对方式（可复现；任一条不成立即本表已失真）

```bash
cd backend

# 1) 确认没有第三方对象存储 SDK（应无输出）
grep -rinE "oss2|boto3|minio|qcloud_cos" . --include=*.py --exclude-dir=.venv

# 2) 确认邮件真发通道只有 aliyun_dm（生产护栏也要求它）
grep -n "aliyun_dm" core/config.py

# 3) 确认支付只有 alipay 是「已接入」网关
grep -n "KNOWN_UNIMPLEMENTED_GATEWAYS" core/config.py

# 4) 确认 Shopify / TikTok 仍是未实现骨架
grep -c NotImplementedError platforms/shopify/client.py platforms/tiktok/client.py
```
