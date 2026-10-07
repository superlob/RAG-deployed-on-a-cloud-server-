"""配置管理 - 从 rag.env 加载环境变量"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_path() -> str:
    """自动查找 rag.env 文件的位置（支持 src/ 结构和项目根目录）"""
    candidates = [
        Path(__file__).parent.parent.parent / "rag.env",  # src/rag/../rag.env
        Path("rag.env"),  # 当前工作目录
    ]
    for path in candidates:
        if path.resolve().exists():
            return str(path.resolve())
    raise FileNotFoundError("无法找到 rag.env 文件，请确保在项目根目录创建")


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=_find_env_path(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库配置
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "rag_paper_db"
    DB_USER: str = "rag_paper_user"
    DB_PASSWORD: str = ""

    # JWT 配置
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 服务器配置
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    # CORS 配置
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Cookie 配置
    COOKIE_SECURE: bool = False  # 生产环境设为 True

    # 阿里云百炼 (DashScope) Embedding
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_BATCH_SIZE: int = 10

    # 分块配置
    DEFAULT_CHUNK_SIZE: int = 512
    DEFAULT_CHUNK_OVERLAP: int = 64

    # ---- Chatting Interface: LLM (OpenAI 兼容代理) ----
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai-proxy.org/v1"
    CHAT_MODEL: str = "gpt-6-luna"
    # gpt-6-luna 在 /v1/chat/completions 下使用 function tools 时必须为 "none"
    CHAT_REASONING_EFFORT: str = "none"
    CHAT_MAX_COMPLETION_TOKENS: int = 2048
    CHAT_TEMPERATURE: float = 0.3
    CHAT_REQUEST_TIMEOUT: float = 120.0

    # ---- Chatting Interface: 上下文管理 ----
    CHAT_HISTORY_TURNS: int = 10        # 最多纳入最近 N 个完整轮次
    CHAT_MAX_CONTEXT_TOKENS: int = 8000  # 上下文 token 预算
    CHAT_MAX_TOOL_ROUNDS: int = 3       # 单条用户消息内最多工具往返次数
    CHAT_MAX_INPUT_CHARS: int = 8000    # 单条用户消息最大字符数

    # ---- Chatting Interface: 检索 ----
    RETRIEVAL_MODE: str = "mock"        # mock | null | real（real 由 Retrieval 模块提供）
    RETRIEVAL_TOP_K: int = 8            # 默认返回片段数（检索模块要求 5–10）

    # ---- Retrieval: 混合检索（向量 + 关键词 + RRF） ----
    RETRIEVAL_VECTOR_K: int = 20      # 向量检索候选数
    RETRIEVAL_KEYWORD_K: int = 20     # 关键词检索候选数
    RETRIEVAL_RRF_K: int = 60         # RRF 平滑常数


# 全局配置实例
settings = Settings()
