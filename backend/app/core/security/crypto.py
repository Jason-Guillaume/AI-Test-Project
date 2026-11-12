"""通用密文加解密工具（Fernet）。

复用 model_configuration 的加密规则（Fernet + runtime_model_config_key 派生），
供飞书 Webhook URL / secret 等敏感配置加密存储。放在 shared 层避免 feature 之间
互相 import service（红线：feature 间不互 import service.py）。

密钥材料来自 runtime_model_config_key()：优先 MODEL_CONFIG_ENCRYPTION_KEY，
缺省回退 SECRET_KEY，与模型 API Key 加密同源，便于统一轮换。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import runtime_model_config_key

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    """用独立配置或应用 SECRET_KEY 派生稳定的 Fernet 密钥。"""
    material = runtime_model_config_key()
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    # urlsafe_b64encode 把 32 字节 sha256 摘要补齐为 Fernet 需要的 32 字节 base64 密钥。
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str | None) -> str:
    """加密明文敏感值，返回可入库的密文字符串；空输入返回空串。"""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str | None) -> str:
    """解密密文，返回明文；空串或非法密文返回空串（不抛错，避免阻断发送流程）。

    解密失败只记告警：webhook 配置损坏时 FeishuNotificationService 会以
    「webhook 无效」分支处理，不让整条发送链路抛异常（§二十八 通知失败独立记录）。
    """
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        logger.warning("密文解密失败，按空值处理：%s", exc)
        return ""
