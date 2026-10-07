"""数据库连接池管理"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import asyncpg

from rag.config import settings

# 全局连接池
_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """获取数据库连接池（懒初始化）"""
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool

        _pool = await asyncpg.create_pool(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            min_size=2,
            max_size=10,
        )
        return _pool


async def close_pool() -> None:
    """关闭数据库连接池"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db() -> None:
    """初始化数据库表结构（users 表 + RLS 策略）"""
    pool = await get_pool()

    # 查找 init.sql 文件
    sql_paths = [
        Path(__file__).parent / "sql" / "init.sql",  # src/rag/sql/init.sql
        Path("rag/sql/init.sql"),  # project root relative
    ]
    sql_path = None
    for path in sql_paths:
        if path.resolve().exists():
            sql_path = path
            break

    if sql_path is None:
        raise FileNotFoundError("无法找到 rag/sql/init.sql 文件")

    sql = sql_path.read_text(encoding="utf-8")

    async with pool.acquire() as conn:
        await conn.execute(sql)

    # 重置因服务重启卡在 processing 状态的文档
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT reset_stuck_documents()")
            if n:
                import logging
                _log = logging.getLogger(__name__)
                _log.info("重置了 %d 个卡住的文档", n)
    except Exception:
        pass

    # 重置因服务重启卡在 streaming 状态的聊天消息
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT reset_stuck_messages()")
            if n:
                import logging
                _log = logging.getLogger(__name__)
                _log.info("重置了 %d 条中断的聊天消息", n)
    except Exception:
        pass


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """获取单个数据库连接"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_user_connection(user_id: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """获取设置了 RLS 上下文的数据库连接

    set_config 第三参数 true 表示仅在当前事务内有效，因此必须开启显式事务，
    否则 set_config 的隐式事务立即提交，GUC 被重置，后续查询无法应用 RLS 上下文。
    整个事务在 with 块内提交，块外连接归还池时 GUC 随事务结束自动清理。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_user_id', $1, true)",
                user_id,
            )
            yield conn
