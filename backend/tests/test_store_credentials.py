"""按店凭据读取口的行为门禁（第 386 轮 · 商用审查 P0-1）。

这一组用例钉的是一条判据：**「这家店该用哪把钥匙」只有一个答案，且答案可复核。**

为什么值得单独一个文件
----------------------
改造前没有任何用例能发现「所有店铺共用一把钥匙」——因为那条链根本不查库：
`fetch_credentials(store_id)` 把 Settings 拼一条记录返回、`refresh_token` 写死 `"***"`。
判据必须钉在**读取口**上，而不是钉在取数结果上：取数结果错了还可以归因为
「平台没数据」，而读取口错了是**确定性**的错误。

★ 与 `test_data_source_per_store.py` 的分工：
  本文件管「选哪把钥匙」，那个文件管「钥匙真的用上了、且两店不串」。
"""

import uuid

import pytest
from sqlalchemy import update

from core.database import async_session_factory
from core.security.credentials import encrypt_credentials
from core.stores.models import StoreRecord
from modules.amazon_sp import (
    StoreNotConnected,
    UnsupportedMarketplace,
    load_store_credential,
)
from modules.amazon_sp.db_model import AmazonCredential
from modules.amazon_sp.oauth import seal_value


# ============================================================================
# 夹具
# ============================================================================
@pytest.fixture
def app_creds(monkeypatch):
    """应用级凭据（LWA 应用身份 + AWS 签名密钥）。

    ★ 为什么必须显式给：`_build_config` 在**应用级**缺 AWS 密钥时会抛
      `StoreNotConnected(reason="aws_credentials_missing")` —— 这是刻意的
      （见该函数注释：留空会表现为每个请求 403 + SignatureDoesNotMatch，
      排查方向会完全跑偏）。测试环境不配它，所有用例都会卡在这一步。
    """
    from core.config import config

    monkeypatch.setattr(config, "spapi_lwa_client_id", "amzn1.application-oa2-client.test", raising=False)
    monkeypatch.setattr(config, "spapi_lwa_client_secret", "test-lwa-secret", raising=False)
    monkeypatch.setattr(config, "spapi_aws_access_key", "AKIATESTAPPLEVEL000", raising=False)
    monkeypatch.setattr(config, "spapi_aws_secret_key", "test-aws-secret", raising=False)
    monkeypatch.setattr(config, "spapi_aws_region", "us-east-1", raising=False)
    monkeypatch.setattr(config, "spapi_use_sandbox", True, raising=False)
    return config


def _form_blob(refresh_token: str = "Atzr|form-token", **over) -> str:
    data = {
        "client_id": "amzn1.application-oa2-client.test",
        "client_secret": "test-lwa-secret",
        "refresh_token": refresh_token,
        "aws_access_key": "AKIATESTFORM000000",
        "aws_secret_key": "form-secret",
        "region": "us-east-1",
        "use_sandbox": "true",
    }
    data.update(over)
    return encrypt_credentials({k: v for k, v in data.items() if v is not None})


async def _set_store(shop_id: str, *, credentials=None, marketplace_id=None, region_code=None) -> None:
    """改店铺的凭据/市场字段。

    ★ 未传的字段**不动**（不是清空）：写成 `.values(region_code=region_code or "")`
      会把夹具里刚设好的站点顺手抹掉 —— 实测让 3 个用例报「站点未知」，
      看起来像生产代码的 bug，其实是造数据的助手在破坏前置条件。
    """
    values = {"api_credentials": credentials}
    if marketplace_id is not None:
        values["marketplace_id"] = marketplace_id
    if region_code is not None:
        values["region_code"] = region_code

    async with async_session_factory() as db:
        await db.execute(
            update(StoreRecord).where(StoreRecord.id == shop_id).values(**values)
        )
        await db.commit()


async def _set_oauth(
    shop_id: str,
    *,
    refresh_token: str = "Atzr|oauth-token",
    status: str = "active",
    with_refresh_at: bool = True,
    error_count: int = 0,
    participant_id: str = "ATVPDKIKX0DER",
    access_token: str = None,
    expires_at=None,
) -> None:
    from datetime import datetime

    async with async_session_factory() as db:
        row = (
            await db.execute(
                AmazonCredential.__table__.select().where(AmazonCredential.store_id == shop_id)
            )
        ).first()
        values = dict(
            store_id=shop_id,
            refresh_token=seal_value(refresh_token),
            credential_status=status,
            last_refresh_at=datetime.utcnow() if with_refresh_at else None,
            error_count=error_count,
            seller_id="A1SELLERTEST",
            marketplace_participant_id=participant_id,
            aws_region="us-east-1",
            access_token=seal_value(access_token) if access_token else None,
            token_expires_at=expires_at,
        )
        if row is None:
            db.add(AmazonCredential(**values))
        else:
            await db.execute(
                update(AmazonCredential)
                .where(AmazonCredential.store_id == shop_id)
                .values(**{k: v for k, v in values.items() if k != "store_id"})
            )
        await db.commit()


@pytest.fixture
async def shop(make_shop):
    """一家干净的 Amazon 店铺（无凭据、无市场）。"""
    return await make_shop()


@pytest.fixture
async def make_shop(ensure_shop):
    """造一家带唯一 id 的店铺；用完由 `ensure_shop` 级联清理。"""
    created = []

    async def _make() -> str:
        sid = await ensure_shop(f"store_r386_{uuid.uuid4().hex[:10]}")
        created.append(sid)
        # ★ 默认给一个合法站点：`_resolve_marketplace` 推不出来时**抛错**
        #   （绝不默认 US）。用例关心的是凭据与市场**各自**的判定，
        #   所以基线店铺要有一个明确的站点，需要测「推不出」的用例再覆盖它。
        await _set_store(sid, region_code="US")
        return sid

    yield _make


# ============================================================================
# 决策①：OAuth 优先 → 表单兜底
# ============================================================================
async def test_oauth_wins_over_form(shop, with_key, app_creds):
    """两条通道都有 ⇒ 取 OAuth。

    ★ 这条就是「卖家撤销授权」能被看见的唯一原因：表单通道表达不了撤销，
      如果表单优先，卖家在后台点了撤销，系统会一直拿死 token 撞 401。
    """
    await _set_store(shop, credentials=_form_blob("Atzr|form-token"))
    await _set_oauth(shop, refresh_token="Atzr|oauth-token")

    cred = await load_store_credential(shop)

    assert cred.source == "oauth"
    assert cred.config.lwa.refresh_token == "Atzr|oauth-token"
    assert cred.seller_id == "A1SELLERTEST"


async def test_form_used_when_no_oauth(shop, with_key, app_creds):
    await _set_store(shop, credentials=_form_blob("Atzr|only-form"))
    cred = await load_store_credential(shop)
    assert cred.source == "form"
    assert cred.config.lwa.refresh_token == "Atzr|only-form"
    # 表单里带了 AWS 密钥 ⇒ 用它，而不是退回应用级
    assert cred.config.aws.access_key == "AKIATESTFORM000000"


async def test_no_credentials_raises_store_not_connected(shop, with_key, app_creds):
    """两条通道都空 ⇒ 必须抛，**绝不返回 mock**。

    ★ 断言 reason 而不只是异常类型：`no_credentials` 与 `store_not_found`
      对客户是两句话（一个让他去授权，一个说明店铺传错了）。
    """
    with pytest.raises(StoreNotConnected) as ei:
        await load_store_credential(shop)
    assert ei.value.reason == "no_credentials"
    assert ei.value.store_id == shop


async def test_empty_store_id_rejected(app_creds):
    """没有 store_id ⇒ 抛，而不是「用全局那把钥匙」。

    ★ 这是「删掉全局工厂」的配套判据：只要允许空 store_id 走通，
      就还给「全局数据源」留了一条后门。
    """
    for bad in ("", "   ", None):
        with pytest.raises(StoreNotConnected) as ei:
            await load_store_credential(bad)
        assert ei.value.reason == "empty_store_id"


async def test_oauth_pending_status_falls_back_to_form(shop, with_key, app_creds):
    """OAuth 行 status != active ⇒ 不参与选择，退回表单。

    ★ 为什么 `pending` 也要排除：`last_refresh_at` 为空表示**从没成功换过 token**，
      那一行连「refresh_token 是否还有效」都还不知道，拿它当凭据等于赌。
    """
    await _set_store(shop, credentials=_form_blob("Atzr|ok-form"))
    await _set_oauth(shop, status="pending")
    cred = await load_store_credential(shop)
    assert cred.source == "form"


async def test_oauth_never_refreshed_falls_back(shop, with_key, app_creds):
    await _set_store(shop, credentials=_form_blob("Atzr|ok-form"))
    await _set_oauth(shop, with_refresh_at=False)
    cred = await load_store_credential(shop)
    assert cred.source == "form"


async def test_oauth_error_count_exceeded_falls_back(shop, with_key, app_creds):
    """连续失败 3 次 ⇒ 该行不再参与选择（卖家很可能已撤销）。

    ★ 为什么不是「直接排除所有非 active 行」就算完：`error_count` 是**渐进**信号
      （偶发 401 不该立刻放弃），`status` 是**二元**信号。两者都要看。
    """
    await _set_store(shop, credentials=_form_blob("Atzr|ok-form"))
    await _set_oauth(shop, error_count=3)
    cred = await load_store_credential(shop)
    assert cred.source == "form"


async def test_prefer_form_ignores_oauth(shop, with_key, app_creds):
    """`prefer="form"` 用于诊断/切换期：必须真的走表单。"""
    await _set_store(shop, credentials=_form_blob("Atzr|form-only"))
    await _set_oauth(shop, refresh_token="Atzr|oauth-only")
    cred = await load_store_credential(shop, prefer="form")
    assert cred.source == "form"
    assert cred.config.lwa.refresh_token == "Atzr|form-only"


# ============================================================================
# 解密失败必须显式上抛（本仓「不许静默降级」）
# ============================================================================
async def test_corrupted_form_ciphertext_raises_not_silently_absent(shop, with_key, app_creds):
    """密文坏掉 ⇒ 抛 `CredentialsDecryptError`，**不是**「这家店没配过」。

    ★ 这是本文件最重要的一条。静默当成「没配过」的后果是：
      用户看到「未授权」的提示 → 重新填一份凭据 → 覆盖掉那份**可能还能救回来**的
      密文（换个密钥就能解开的），损失不可逆。
    """
    from core.security.credentials import CredentialsDecryptError

    await _set_store(shop, credentials="enc:v1:this-is-not-valid-fernet-ciphertext")
    with pytest.raises(CredentialsDecryptError):
        await load_store_credential(shop)


async def test_plaintext_form_value_raises(shop, with_key, app_creds):
    """字段里存的是明文（历史遗留）⇒ 显式报错。

    ★ 明文意味着「凭据裸奔」，是安全事故；把它当「没配过」等于把事故
      伪装成功能未启用（`core/security/credentials.py` 顶部记录了这条）。
    """
    from core.security.credentials import CredentialsNotEncryptedError

    await _set_store(shop, credentials='{"refresh_token": "Atzr|plaintext"}')
    with pytest.raises(CredentialsNotEncryptedError):
        await load_store_credential(shop)


# ============================================================================
# 市场映射（宁可抛错，绝不默认 US）
# ============================================================================
async def test_marketplace_from_participant_id(shop, with_key, app_creds):
    from platforms.amazon.sp_api.models import Marketplace

    await _set_oauth(shop, participant_id="A1VC38T7YXB528")  # 日本
    cred = await load_store_credential(shop, prefer="oauth")
    assert cred.marketplace is Marketplace.JP


async def test_marketplace_from_store_region_code(shop, with_key, app_creds):
    """OAuth 行没给 participant_id 时，用店铺的 region_code 推。"""
    from platforms.amazon.sp_api.models import Marketplace

    await _set_store(shop, credentials=_form_blob(), region_code="DE")
    cred = await load_store_credential(shop)
    assert cred.marketplace is Marketplace.DE


async def test_marketplace_unknown_raises(shop, with_key, app_creds):
    """推不出来 ⇒ 抛 `UnsupportedMarketplace`，**不默认 US**。

    ★ 默认 US 的后果：新加坡站的订单拿美国站的 marketplaceIds 去查，
      返回 **0 条且不报错**。现象是「这家店怎么没订单」，排查会从授权一路查到
      同步调度，而真正的原因是站点映射。
    """
    await _set_store(shop, credentials=_form_blob(), region_code="AMAZON")
    with pytest.raises(UnsupportedMarketplace):
        await load_store_credential(shop)


async def test_marketplace_unsupported_site_raises(shop, with_key, app_creds):
    """枚举里没有的站点（如新加坡 B2C）⇒ 抛，不是静默落到某个默认值。"""
    await _set_oauth(shop, participant_id="A19VAU5U5O7RUS")  # 新加坡，不在枚举内
    with pytest.raises(UnsupportedMarketplace):
        await load_store_credential(shop, prefer="oauth")


# ============================================================================
# 决策③：DB 当 token 缓存
# ============================================================================
async def test_valid_access_token_is_reused(shop, with_key, app_creds):
    """库里的 access_token 还没过期 ⇒ 直接复用（省一次 LWA 往返）。"""
    from datetime import datetime, timedelta

    await _set_oauth(
        shop,
        access_token="Atza|still-valid",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    cred = await load_store_credential(shop, prefer="oauth")
    assert cred.access_token == "Atza|still-valid"
    assert cred.access_token_expires_at is not None


async def test_expiring_access_token_is_not_reused(shop, with_key, app_creds):
    """剩余不足 5 分钟 ⇒ 不预置（交给 auth 现场刷新）。

    ★ 这条挡的是「请求走到一半 token 过期」：用剩余 60 秒的 token 发起
      一次可能跑两分钟的多页拉取，会在中途 401，而错误看起来像「凭据失效」。
    """
    from datetime import datetime, timedelta

    await _set_oauth(
        shop,
        access_token="Atza|about-to-die",
        expires_at=datetime.utcnow() + timedelta(minutes=1),
    )
    cred = await load_store_credential(shop, prefer="oauth")
    assert cred.access_token is None
    # 但要保留到期时刻，供日志/诊断解释「为什么不复用」
    assert cred.access_token_expires_at is not None


async def test_snapshot_never_leaks_token(shop, with_key, app_creds):
    """`snapshot()` 里不能出现任何 token 字段（连 `***` 占位都不给）。

    ★ 改造前 `fetch_credentials()` 返回 `"refresh_token": "***"` ——
      看起来像「有值但打码」，实际调用方拿它做不了任何事，
      却让人以为凭据真的被读到了。要么给真值（服务端内部），要么不给这个字段。
    """
    await _set_oauth(shop, refresh_token="Atzr|secret-should-not-leak")
    cred = await load_store_credential(shop, prefer="oauth")
    snap = cred.snapshot()
    flat = repr(snap)
    assert "secret-should-not-leak" not in flat
    assert "refresh_token" not in snap
    assert "access_token" not in snap  # 只有 has_access_token / access_token_expires_at
