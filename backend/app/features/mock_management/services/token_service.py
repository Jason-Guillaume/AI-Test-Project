"""Mock Runtime Token：生成 / 哈希 / 校验（§五十）。

明文只在创建 / 重置时返回一次；库中只存哈希。校验用 hmac.compare_digest 常量时间比较，
避免时序侧信道。哈希材料来自应用 SECRET_KEY（与令牌撤销同源，便于统一轮换）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.shared.config import settings


def generate_runtime_token() -> str:
    """生成一个新的 Runtime Token 明文（urlsafe，32 字节熵）。"""
    return "mtk_" + secrets.token_urlsafe(32)


def hash_token(plaintext: str | None) -> str:
    """把明文 token 哈希成可入库的摘要（sha256 + 应用密钥作盐）。"""
    if not plaintext:
        return ""
    material = (settings.SECRET_KEY or "mock-runtime-secret").encode("utf-8")
    digest = hashlib.sha256(material + plaintext.encode("utf-8")).hexdigest()
    return digest


def verify_token(plaintext: str | None, token_hash: str | None) -> bool:
    """常量时间校验明文 token 是否匹配哈希。空哈希表示未设置，一律拒绝。"""
    if not plaintext or not token_hash:
        return False
    expected = hash_token(plaintext)
    return hmac.compare_digest(expected, token_hash or "")


__all__ = ["generate_runtime_token", "hash_token", "verify_token"]
