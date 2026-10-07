"""认证 API 路由"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from rag.auth.deps import get_current_user
from rag.auth.models import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
)
from rag.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from rag.config import settings
from rag.db import get_connection

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_to_dict(user) -> dict:
    """将 asyncpg Record 转为 dict（Record 不支持属性访问，必须用字典式）"""
    return {k: user[k] for k in user.keys()}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, response: Response):
    """注册新用户"""
    async with get_connection() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE username = $1", request.username)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被注册")

        password_hash = hash_password(request.password)
        user = await conn.fetchrow(
            "INSERT INTO users (username, password_hash) VALUES ($1, $2) RETURNING id, username, created_at",
            request.username,
            password_hash,
        )

    user_id = str(user["id"])
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    response.set_cookie(key="access_token", value=access_token, max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/api")
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/api/v1/auth/refresh")

    return UserResponse.model_validate(_user_to_dict(user))


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """用户登录"""
    async with get_connection() as conn:
        user = await conn.fetchrow("SELECT id, username, password_hash, created_at FROM users WHERE username = $1", request.username)

    if user is None or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    user_id = str(user["id"])
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    response.set_cookie(key="access_token", value=access_token, max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/api")
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/api/v1/auth/refresh")

    return LoginResponse(user=UserResponse.model_validate(_user_to_dict(user)))


@router.post("/refresh")
async def refresh(response: Response, refresh_token: str | None = Cookie(default=None)):
    """刷新 access token"""
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供刷新 token")

    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh" or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的刷新 token")

    new_access_token = create_access_token(payload["sub"])
    response.set_cookie(key="access_token", value=new_access_token, max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/api")
    return {"message": "Token 已刷新"}


@router.post("/logout")
async def logout(response: Response):
    """登出 - 清除 cookies"""
    response.delete_cookie(key="access_token", path="/api")
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")
    return {"message": "已登出"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: UserResponse = Depends(get_current_user)):
    """获取当前用户信息"""
    return user
