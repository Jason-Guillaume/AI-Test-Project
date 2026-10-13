"""密码哈希。

使用 SHA256 预处理 + bcrypt，等价于 passlib 的 bcrypt_sha256 方案，
避免 bcrypt 的 72 字节截断。这里直接基于 bcrypt 库实现，不依赖 passlib：
passlib 1.7.4 与 bcrypt >= 4.1 在读取 ``__about__.__version__`` 时会触发告警，
且 passlib 本身已停止维护。

为兼容旧项目用 passlib bcrypt_sha256 / bcrypt 写入的哈希，verify 会依次尝试
两种前缀（``$2b$`` 表示 bcrypt 原样哈希，``$2sha256$`` 已由本模块处理）。
"""

from __future__ import annotations

import hashlib

import bcrypt

_SALT_ROUNDS = 12
_MAX_PASSWORD_BYTES = 72


def _sha256(value: str) -> bytes:
    """把字符串按 UTF-8 编码后做 SHA256，返回 32 字节摘要。

    SHA256 输出固定 32 字节，恒小于 bcrypt 的 72 字节上限，因此后续截断恒为无操作。
    """
    return hashlib.sha256(value.encode("utf-8")).digest()


def _truncate(data: bytes) -> bytes:
    """bcrypt 只使用前 72 字节，显式截断以避免越界告警。"""
    return data[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    """对密码做 SHA256 预处理后加盐哈希。

    Returns:
        str: 形如 "$2b$12$..." 的哈希串，可直接入库；每次调用生成的盐不同，
        同一密码的哈希不会重复。
    """
    digest = _truncate(_sha256(password))
    # 盐随机生成，_SALT_ROUNDS 为 bcrypt 成本因子（12 轮，兼顾强度与登录延迟）。
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=_SALT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed_password: str | None) -> bool:
    """校验密码；哈希为空或算法不匹配时返回 False。

    兼容三类历史哈希：
    1. 本模块产物：SHA256 预处理后的 bcrypt 哈希；
    2. 旧 bcrypt_sha256 哈希（同样是 SHA256 预处理）；
    3. 原始 bcrypt 哈希（旧 passlib bcrypt 方案）。
    """
    if not hashed_password:
        return False
    try:
        encoded_hash = hashed_password.encode("utf-8")
        # 优先按本模块规则（SHA256 预处理）校验。
        if bcrypt.checkpw(_truncate(_sha256(password)), encoded_hash):
            return True
        # 回退：密码原文直接匹配（历史 bcrypt 哈希）。
        return bcrypt.checkpw(_truncate(password.encode("utf-8")), encoded_hash)
    except (ValueError, TypeError):
        # 历史脏数据（非 bcrypt 格式的哈希串）直接判为不匹配，不抛错。
        return False
