"""平台连接层门面（`modules/stores/connect`）。

★ 公开面（改这里必须同步核对全部消费点）
  - `PlatformConnector` / `PlatformSchema` / `CredentialField` —— 契约与数据模型
  - `VerifyResult` / `VerifyStatus` / `CredentialsIncomplete`   —— 验证结果与错误
  - `get_connector` / `list_schemas` / `schema_for` / `supported_platforms`

★ 设计说明见 `base.py` 顶部：把平台差异全压成**声明**，
  HTTP / 签名 / 三态分流各只有一份实现。
"""
from modules.stores.connect.base import (
    CredentialField,
    CredentialsIncomplete,
    FieldType,
    PlatformConnector,
    PlatformSchema,
    PlatformSchemaList,
    StoreConnectResult,
    StoreConnectSpec,
    VerifyCheck,
    VerifyReport,
    VerifyResult,
    VerifyStatus,
)
from modules.stores.connect.registry import (
    UnknownPlatform,
    get_connector,
    list_schemas,
    resolve_family,
    schema_for,
    supported_platforms,
)

__all__ = [
    "CredentialField",
    "CredentialsIncomplete",
    "FieldType",
    "PlatformConnector",
    "PlatformSchema",
    "PlatformSchemaList",
    "StoreConnectResult",
    "StoreConnectSpec",
    "UnknownPlatform",
    "VerifyCheck",
    "VerifyReport",
    "VerifyResult",
    "VerifyStatus",
    "get_connector",
    "list_schemas",
    "resolve_family",
    "schema_for",
    "supported_platforms",
]
