"""
店铺平台凭证的「静态加密」通道（P1-a 修复，2026-09-16）

★ 本模块是 `stores_store.api_credentials` 的**唯一**读写入口。绕过它直接
  `json.dumps(credentials)` 赋值，就是在把一个 P1 缺陷重新引进来。

★★★ 修复前的形态（值得记住，因为它**不会自己暴露**）
    模型注释写着：`api_credentials ... # 加密的 JSON 凭证`，
    而写入处是：  `shop.api_credentials = json.dumps(credentials)`
    全项目 `encrypt` / `Fernet` / `decrypt` 命中 **0 处**。

    也就是说 —— **注释在撒谎，而且没有任何代码会因此报错**。
    这个字段只写不读，永远没人去尝试解密，所以「文档承诺 vs 实现事实」
    的偏差可以一直躺着，等到某天真的接入 SP-API 要读凭证时才以
    「线上凭证明文裸奔」的形式爆出来。

    ⇒ 判据：凡是注释/文档里出现「加密」「脱敏」「只读」这类**承诺**，
      都必须配一条**可执行用例**去兑现它。本模块自带 round-trip 用例，
      并额外断言「密文里不含明文子串」—— 只做 round-trip 是骗得过自己的
      （明文塞进去、原样取回来，round-trip 一样通过）。

★★★ 为什么缺密钥时「拒绝写入」，而不是明文落库或自动生成密钥
    1. **明文落库** —— P1-a 原样保留，等于没修；
    2. **自动生成密钥** —— 密钥随进程消失 ⇒ 密文永久解不开（数据变砖），
       而界面上一片正常、日志里毫无动静，**比明文更坏**；
    3. **显式拒绝** —— 立刻可见、原因可读、修法明确。

    ★ 与项目「禁静默降级」一致，且门禁放在**写这一层**
      （与 P0-a 的 L2 同一判据）：不在这里写，就永远不会出现明文。

★ 密钥格式：Fernet key（`base64.urlsafe_b64encode(32 字节)`，44 字符）。
    生成：  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    配置：  SHOP_CREDENTIALS_ENCRYPTION_KEY=<上一步输出>

★ 为什么**不**把「生产必须有密钥」做成启动硬拒绝
    因为「暂时不接平台」是合法运营状态，强制要求密钥会让一个只想开店的
    部署起不来。改成在**写这一层**拒绝：真去连接平台时才失败，且原因可读。
    （与 `core/config.py::_enforce_production_safety` 里那些「漏配=危险」
      的项不同：漏配本项不会产生任何不安全的落库结果，只会让写入失败。）
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from core.config import config


# 密文前缀（带版本号）。用途有两个：
#   1. 把「本模块写下的密文」与「历史明文 / 别处写坏的值」区分开，
#      于是 `decrypt_credentials` 可以对后者**显式报错**而不是静默返回 None；
#   2. 将来更换算法时按前缀分流，不需要全表猜格式。
ENC_PREFIX = "enc:v1:"


class CredentialsKeyMissing(RuntimeError):
    """未配置（或配错）SHOP_CREDENTIALS_ENCRYPTION_KEY —— 拒绝写入平台凭证。"""


class CredentialsNotEncryptedError(RuntimeError):
    """字段里存的是**明文**（历史遗留），拒绝把它当密文用。"""


class CredentialsDecryptError(RuntimeError):
    """密文无法解密：密钥换过 / 值被破坏 / 不是本模块写下的。"""


def generate_key() -> str:
    """生成一个合法的 Fernet 密钥（供运维一次性使用，不参与运行时逻辑）。"""
    return Fernet.generate_key().decode()


def _get_fernet() -> Fernet:
    """
    按当前配置构造 Fernet。**每次调用都重新读 config** ——
    这样测试可以 `monkeypatch.setattr(config, "credentials_encryption_key", ...)`，
    也让「改环境变量后无需重启进程」在语义上成立（虽然是懒加载）。
    """
    raw = (config.credentials_encryption_key or "").strip()
    if not raw:
        raise CredentialsKeyMissing(
            "未配置 SHOP_CREDENTIALS_ENCRYPTION_KEY，已拒绝写入平台凭证"
            "（本项目不允许把平台凭证明文落库）。"
            "请先生成密钥：python -c \"from cryptography.fernet import Fernet;"
            " print(Fernet.generate_key().decode())\"，"
            "再把结果写进 .env 的 SHOP_CREDENTIALS_ENCRYPTION_KEY"
        )
    try:
        return Fernet(raw.encode("ascii"))
    except Exception as exc:
        # 密钥格式非法 = 配置错误，仍然走同一个异常类型：
        # 调用方只需要知道「密钥不可用 ⇒ 拒绝写入」，不需要区分是空还是写错。
        raise CredentialsKeyMissing(
            "SHOP_CREDENTIALS_ENCRYPTION_KEY 不是合法的 Fernet 密钥"
            "（应为 base64 urlsafe 编码的 44 字符）。"
            "请用 cryptography.fernet.Fernet.generate_key() 重新生成"
        ) from exc


def is_encrypted(stored: Optional[str]) -> bool:
    """判断库里存的值是不是本模块写下的密文。"""
    return bool(stored) and str(stored).startswith(ENC_PREFIX)


def encrypt_credentials(credentials: Dict[str, Any]) -> str:
    """
    把平台凭证 dict 加密成可直接入库的字符串。

    Raises:
        CredentialsKeyMissing: 未配置密钥（**绝不退回明文**）
        TypeError: 传入的不是 dict
    """
    if not isinstance(credentials, dict):
        raise TypeError("平台凭证必须是 dict")

    # sort_keys=True：同样的凭证得到同样的明文串，便于排查；
    # ensure_ascii=False：中文平台名不转义，密文长度也更短。
    plain = json.dumps(credentials, ensure_ascii=False, sort_keys=True)
    token = _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_credentials(stored: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    把库里存的密文解回 dict。空值返回 None。

    Raises:
        CredentialsNotEncryptedError: 存的是明文 —— **显式报错而不是返回 None**。
            返回 None 会让调用方以为「这家店没配凭证」，从而把「数据泄露风险」
            误判成「功能未配置」，归因方向完全错。
        CredentialsDecryptError: 解密失败（密钥换过 / 值被破坏）。
        CredentialsKeyMissing: 未配置密钥。
    """
    if not stored:
        return None

    if not is_encrypted(stored):
        raise CredentialsNotEncryptedError(
            "stores_store.api_credentials 里存的是明文（历史遗留数据），不是本模块写的密文。"
            "请先用一次性脚本加密回填，再启用读取路径"
        )

    try:
        plain = _get_fernet().decrypt(stored[len(ENC_PREFIX):].encode("ascii"))
    except InvalidToken as exc:
        raise CredentialsDecryptError(
            "平台凭证密文无法解密：密钥被更换过，或字段值已损坏。"
            "换密钥不会自动迁移历史密文，请确认 SHOP_CREDENTIALS_ENCRYPTION_KEY 未改动"
        ) from exc

    try:
        return json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialsDecryptError(
            "平台凭证解密后不是合法 JSON（字段可能被手工改过）"
        ) from exc
