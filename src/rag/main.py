"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from rag.auth.router import router as auth_router
from rag.chat.router import router as chat_router
from rag.config import settings
from rag.db import close_pool, init_db
from rag.documents.router import router as documents_router
from rag.processing.router import router as processing_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_pool()


app = FastAPI(title="RAG API", description="RAG 应用后端 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(processing_router)

# 挂载静态文件（认证测试页面）
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return {
        "message": "RAG API is running",
        "auth_demo": "http://127.0.0.1:8000/static/auth_demo.html"
    }


def main():
    """应用入口函数"""
    import uvicorn

    uvicorn.run(
        "rag.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True,
    )
