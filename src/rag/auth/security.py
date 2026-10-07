"""安全工具函数 - 密码哈希和 JWT token 管理"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from rag.config import settings


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希处理"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否匹配"""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(user_id: str) -> str:
    """创建访问 token"""
    return _create_token(user_id, "access")


def create_refresh_token(user_id: str) -> str:
    """创建刷新 token"""
    return _create_token(user_id, "refresh")


def _create_token(user_id: str, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    expire_delta = (
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        if token_type == "access"
        else timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode = {
        "sub": user_id,
        "exp": now + expire_delta,
        "iat": now,
        "type": token_type,
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """解码 JWT token，无效时返回 None"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
