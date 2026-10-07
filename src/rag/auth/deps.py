"""认证依赖项 - FastAPI Depends 使用"""

from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status

from rag.auth.models import UserResponse
from rag.auth.security import decode_token
from rag.db import get_connection


def _user_to_dict(user) -> dict:
    """将 asyncpg Record 转为 dict"""
    return {k: user[k] for k in user.keys()}


async def get_current_user(
    access_token: str | None = Cookie(default=None),
) -> UserResponse:
    """从 cookie 中的 access_token 获取当前用户"""
    if access_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证 token")

    payload = decode_token(access_token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证 token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证 token")

    async with get_connection() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, created_at FROM users WHERE id = $1",
            UUID(user_id),
        )

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    return UserResponse.model_validate(_user_to_dict(user))
