"""平台连接（凭据配置 + 真实验证）的**统一契约层**。

★★★ 为什么要有这一层（2026-09-29，第 318 轮）

  改造前，「连接平台」这件事在三个地方各缺一块，叠在一起形成一个
  **看起来正常、实际全空转** 的功能：

    ① 界面上根本没有连接入口 —— 店铺管理里只有「删除」，「未连接」是终态；
    ② 后端列表**不返回 `is_connected`** —— `Store.is_connected` 是 pydantic
       模型上的一个 `@property`，而 **pydantic v2 不会把普通 property 序列化
       进 `model_dump()`**（要 `@computed_field` 才行）。前端读
       `item.is_connected` 恒为 `undefined` ⇒ 连上了也永远显示「未连接」。
       ★ 注意这是**机制**，不是「漏写了一个字段」—— 属性在、值也对，
         只是没进 JSON。也正因为如此，类型检查（TS 声明了 `is_connected`）
         与后端自测（读属性为 True）**都不会报错**。
    ③ `POST /{id}/connect` 收下凭据加密落库后，**全仓没有生产消费方** ——
       真正取数的 `SpApiDataSource` 读的是环境变量 `SPAPI_LWA_*`。
       ⇒ 只补入口 = 「连接成功但调不通」，比没有入口更难排查。

  本包解决的是「怎么把凭据收上来、并且**真的去平台验一次**」。

★★★ 设计红线：**不要每个平台写一套**

  做法是把差异全部压成**声明**，执行逻辑只有一份：

    - 平台「长什么样」→ `fields()` 返回的 `CredentialField` 列表（后端下发、前端通用渲染）
    - 平台「怎么验」  → `verify()` 里拼参数、判响应；HTTP 本身一律走 `connect/http.py`
    - 签名算法        → `connect/signing.py`（HMAC-SHA256 等，多平台共用一份）
    - 新的「HTTP 出口」→ **禁止**。新增平台若需要自己 import httpx 才能验证，
      说明抽象漏了，应该扩 `http.py` 而不是在里面再开一条通路。

★★★ 验证结果必须**分三态**，禁止压成布尔

  `VerifyStatus` 刻意有四个值，其中最关键的是把
  **「凭据被平台拒绝」** 与 **「平台压根没连上」** 分开：

    - `INVALID`     —— 凭据错（401/签名不对/店铺不存在）⇒ 用户改凭据
    - `UNREACHABLE` —— 超时 / DNS / 平台 5xx ⇒ **凭据好坏未知**，不能判成坏

  合并成一个 `False` 是最常见的写法，也是最坏的一种：网络抖一下就把用户的
  正确凭据判成「无效」，用户会去反复改一个本来没错的东西。
  （同一条判据见「三态压两态＝静默洗白」。）

  同理，`UNSUPPORTED`（本平台尚未接入自动校验）**绝不能**被当成验证通过 ——
  它落到 `credentials_verified=False`，界面上必须显式区分
  「已连接（已验证）」与「已配置（未验证）」。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


# ====== 字段规格（后端下发 → 前端通用渲染）======

class FieldType(str, Enum):
    """输入控件类型。

    刻意只有三种：新增一种就要前端多一个分支，
    而「每个平台写一套」正是从这种分支开始长出来的。
    """
    TEXT = "text"
    PASSWORD = "password"
    SELECT = "select"


class CredentialField(BaseModel):
    """一个凭据字段的规格。

    ★ 这是前后端之间**唯一的**平台差异载体：前端不认识任何平台名，
      只认识这个结构。加平台 = 后端加几条声明，前端零改动。
    """
    key: str = Field(..., description="提交时的字段名（落库键名）")
    label: str = Field(..., description="界面标签")
    type: FieldType = Field(FieldType.TEXT, description="输入控件类型")
    required: bool = Field(True, description="是否必填（后端会复核，不信任前端）")
    placeholder: str = Field("", description="输入框占位提示")
    help: str = Field("", description="字段说明：去哪拿、长什么样")
    secret: bool = Field(False, description="是否敏感：回显一律掩码，绝不回明文")
    options: List[Dict[str, str]] = Field(
        default_factory=list, description="type=select 时的选项 [{'value','label'}]"
    )
    default: str = Field("", description="默认值（仅用于表单预填，不参与落库判据）")

    # ---- 构造糖：让平台声明读起来像一张表 ----
    @classmethod
    def text(cls, key: str, label: str, **kw: Any) -> "CredentialField":
        return cls(key=key, label=label, type=FieldType.TEXT, **kw)

    @classmethod
    def password(cls, key: str, label: str, **kw: Any) -> "CredentialField":
        return cls(key=key, label=label, type=FieldType.PASSWORD, secret=True, **kw)

    @classmethod
    def select(
        cls, key: str, label: str, options: List[Dict[str, str]], **kw: Any
    ) -> "CredentialField":
        return cls(
            key=key, label=label, type=FieldType.SELECT, options=options, **kw
        )


class PlatformSchema(BaseModel):
    """一个平台的连接表单规格（`GET /stores/connect/schema` 的返回单元）。"""
    platform: str = Field(..., description="平台家族键：amazon / shopee / shopify / tiktok")
    display_name: str = Field(..., description="界面展示名")
    docs_url: str = Field("", description="官方文档地址（界面给「去哪拿凭据」的出口）")
    fields: List[CredentialField] = Field(default_factory=list)
    notes: List[str] = Field(
        default_factory=list, description="界面提示（如 token 有效期、权限要求）"
    )
    verify_supported: bool = Field(
        True, description="本平台是否已接入自动校验；False ⇒ 只会存凭据，不会置「已验证」"
    )


# ====== 验证结果（分三态，禁压布尔）======

class VerifyStatus(str, Enum):
    OK = "ok"                    # 凭据有效且链路可达
    INVALID = "invalid"          # 平台明确拒绝（凭据/权限/参数问题）⇒ 用户改凭据
    UNREACHABLE = "unreachable"  # 超时 / DNS / 平台故障 ⇒ **凭据好坏未知**
    UNSUPPORTED = "unsupported"  # 本平台尚未接入自动校验


class VerifyCheck(BaseModel):
    """单个验证步骤的结果。

    ★ 为什么要逐步记录：一次验证往往有两段（先换 token、再用 token 取数），
      「哪一段断了」直接决定用户该改哪个字段。只回一个总失败文案，
      用户只能靠猜。这与「探针须把注入失败与注入没抓到分开报」是同一条判据。
    """
    name: str
    ok: bool
    message: str = ""


class VerifyResult(BaseModel):
    status: VerifyStatus
    message: str = Field(..., description="给用户看的一句话结论")
    checks: List[VerifyCheck] = Field(default_factory=list)
    detail: Dict[str, Any] = Field(
        default_factory=dict, description="平台返回的可展示信息（店铺名/区域/到期时间）"
    )
    refreshed: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "验证过程中**由连接器产出**、应当一并落库的值（如 Shopee 用 refresh_token "
            "换到的新 access_token）。★ 只能由连接器写；端点不得从请求体合并进这里 —— "
            "否则客户端就能凭请求体改写落库凭据。"
            " ★★ 本字段**绝不进入任何响应体**（响应里用 `VerifyReport`，它没有这个字段）—— "
            "里面装的是刚换到的令牌明文。"
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ok(self) -> bool:
        """是否「明确验证通过」。

        ★ 必须是 `@computed_field` 而不是普通 `@property` ——
          pydantic v2 不会把普通 property 序列化进 `model_dump()`，
          `is_connected` 那次踩的就是这个坑（见模块顶部 ②）。
        """
        return self.status == VerifyStatus.OK


# ====== 输入校验 ======

class CredentialsIncomplete(ValueError):
    """缺必填字段。**在发任何网络请求之前**抛出 —— 不浪费一次调用，
    也不让「少填了一个」伪装成「凭据无效」。"""

    def __init__(self, missing: List[str], labels: Optional[List[str]] = None):
        self.missing = list(missing)
        self.labels = list(labels or missing)
        super().__init__("缺少必填字段：" + "、".join(self.labels))


# ====== 连接器基类 ======

class PlatformConnector(ABC):
    """平台连接器。

    子类**只**提供两件东西：`fields()`（声明长得什么样）与
    `verify()`（怎么验）。HTTP、签名、超时、错误分类一律走共享层。
    """

    #: 平台家族键（与 `Store.platform` 的前缀一致：amazon_us → amazon）
    platform: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    docs_url: ClassVar[str] = ""

    #: 界面提示（子类覆盖）
    notes: ClassVar[List[str]] = []

    # ---------- 子类必须实现 ----------

    @abstractmethod
    def fields(self) -> List[CredentialField]:
        """本平台需要用户填哪些字段。"""

    # ---------- 子类可选覆写 ----------

    async def verify(self, values: Dict[str, Any]) -> VerifyResult:
        """真正去平台验一次。

        ★ 默认实现返回 `UNSUPPORTED`（**fail-closed**）：
          新接入一个平台却忘了写验证，结果必须是「未验证」，
          而不是「默认通过」。这与「禁静默降级」同一条判据。

        ★ 约定：本方法**不抛异常**（网络/解析异常在 `http.py` 里已被翻译成
          带 `error_kind` 的结果）。真抛了异常，端点按 UNREACHABLE 兜底。
        """
        return VerifyResult(
            status=VerifyStatus.UNSUPPORTED,
            message=(
                f"{self.display_name or self.platform} 暂未接入自动校验："
                "凭据会加密保存，但不会标记为「已验证」。"
            ),
        )

    # ---------- 通用实现（子类不应覆写）----------

    def schema(self) -> PlatformSchema:
        return PlatformSchema(
            platform=self.platform,
            display_name=self.display_name or self.platform,
            docs_url=self.docs_url,
            fields=self.fields(),
            notes=list(self.notes),
            verify_supported=type(self).verify is not PlatformConnector.verify,
        )

    def secret_keys(self) -> set[str]:
        return {f.key for f in self.fields() if f.secret}

    def required_fields(self) -> List[CredentialField]:
        return [f for f in self.fields() if f.required]

    def normalize(self, raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """把前端提交的任意 dict 收敛成「只含已声明字段的 str→str」。

        做三件事，每件都对应一种真实的坏输入：
          1. **白名单**：丢掉未声明的键（否则客户端能往密文里塞任意内容）；
          2. **去引号/空白**：老板从控制台复制粘贴时常带上前后空格与成对引号，
             这类值肉眼与正确值无异，直接发出去只会得到「签名错误」；
          3. 空值不进值集（`normalize` 后 `values` 里不会出现 `""`）。
        """
        out: Dict[str, str] = {}
        src = raw or {}
        for f in self.fields():
            if f.key not in src:
                continue
            v = src.get(f.key)
            if v is None:
                continue
            s = str(v).strip()
            # 去掉成对包裹的引号（'xxx' 或 "xxx"），只去一层
            if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
                s = s[1:-1].strip()
            if s:
                out[f.key] = s
        return out

    def require(self, values: Dict[str, str]) -> None:
        """复核必填项。**在联网之前**调用。

        Raises:
            CredentialsIncomplete: 缺必填字段（文案带中文标签，便于直接上屏）
        """
        missing = [f for f in self.required_fields() if not values.get(f.key)]
        if missing:
            raise CredentialsIncomplete(
                [f.key for f in missing], [f.label for f in missing]
            )

    def masked_echo(self, stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """回显「已配置了哪些字段」—— **绝不回明文**。

        ★ 只回两类信息：
          - `configured`: {字段名: bool}
          - `values`:     非敏感字段的原值 + 敏感字段的 `••••••`

        为什么要带上非敏感字段的原值（如亚马逊的 `client_id`、`region`）：
        用户重开弹窗时若全空，会以为「我配的东西丢了」而重填一遍；
        而敏感值一旦回显，就等于给「能打开这个弹窗的人」发了明文。
        """
        stored = stored or {}
        configured: Dict[str, bool] = {}
        values: Dict[str, Any] = {}
        for f in self.fields():
            v = stored.get(f.key)
            has = bool(v)
            configured[f.key] = has
            if not has:
                continue
            values[f.key] = "••••••" if f.secret else str(v)
        return {
            "configured": configured,
            "values": values,
            "any_configured": any(configured.values()),
        }


# ====== 端点响应模型（前后端契约）======
#
# ★ 为什么用 pydantic 模型而不是裸 dict：这三个结构是**前端唯一认识的东西**，
#   写成模型才能进 OpenAPI，也才能被「字段改名」时的类型检查照到。
#   裸 dict 的返回体改了键名不会有任何一方报错。

class PlatformSchemaList(BaseModel):
    """`GET /api/v1/stores/connect/schema` 响应：全部平台的连接表单规格。

    ★ 一次返回**全部**平台（而不是按 platform 查一个）：前端打开「添加店铺 /
      连接平台」时需要按平台即时切换表单，一次取回可以避免每切一次发一次请求，
      也让「平台清单」只有一个来源。
    """
    schemas: List[PlatformSchema] = Field(default_factory=list)


class StoreConnectSpec(BaseModel):
    """`GET /api/v1/stores/{id}/connect/schema` 响应：单店规格 + **掩码**回显。

    ★ `values` 里**只有非敏感字段的原值**；`secret=True` 的字段一律是 `••••••`。
      回显的目的是「让用户重开弹窗时知道配过什么」，不是「把凭据取回来」。
    """
    spec: PlatformSchema
    configured: Dict[str, bool] = Field(
        default_factory=dict, description="{字段名: 库里是否有值}"
    )
    values: Dict[str, Any] = Field(
        default_factory=dict, description="非敏感字段原值 + 敏感字段掩码，**绝不含明文**"
    )
    any_configured: bool = False
    connection_status: str = ""
    is_connected: bool = False
    has_credentials: bool = False


class VerifyReport(BaseModel):
    """`VerifyResult` 的**对外**形态 —— 剥掉 `refreshed`。

    ★★★ 为什么不直接把 `VerifyResult` 放进响应体（2026-09-29，第 318 轮）

      `VerifyResult.refreshed` 里装的是**刚换到的新令牌**
      （如 Shopee 用 refresh_token 换来的 `access_token`）。
      它是「应当落库」的东西，不是「应当回显」的东西 ——
      一旦跟着响应出去，就等于把刚拿到的凭据明文发给了浏览器
      （并留在浏览器缓存 / 日志 / 前端 store 里）。

      而这两个字段**在同一个模型上**，只差一个字段名 —— 稍不留神就会写成
      `verify=result` 把它一起带出去，而且**不会有任何报错**：
      功能照常工作，界面上一切正常，泄露是静默的。

      ⇒ 用**独立类型**把「对外形态」钉死：响应模型里出现的是本类，
        `refreshed` 在类型层面就不存在。
        （同类判据：`Store` 里刻意不放 `api_credentials`。）
    """
    status: VerifyStatus
    message: str
    checks: List[VerifyCheck] = Field(default_factory=list)
    detail: Dict[str, Any] = Field(default_factory=dict)
    ok: bool = False

    @classmethod
    def from_result(cls, result: "VerifyResult") -> "VerifyReport":
        """唯一构造入口 —— 「哪些字段对外」只在这里决定一次。"""
        return cls(
            status=result.status,
            message=result.message,
            checks=list(result.checks),
            detail=dict(result.detail),
            ok=result.ok,
        )


class StoreConnectResult(BaseModel):
    """`POST /api/v1/stores/{id}/connect` 成功响应（验证未通过时走 4xx/503）。

    ★ 为什么带整份 `verify`（含逐步骤 `checks`）而不是一句文案：
      「哪一步断了」直接决定用户该改哪个字段 —— 是 LWA 令牌换不出来，
      还是 AWS 签名没通过。只回一句「连接失败」，用户只能靠猜。

    ★ 这里用 `VerifyReport` 而**不是** `VerifyResult`：后者带 `refreshed`
      （新换到的令牌），不能出门（见 `VerifyReport` docstring）。
    """
    store_id: str
    platform: str
    family: str
    message: str
    verify: VerifyReport
    connection_status: str
    is_connected: bool
    has_credentials: bool
