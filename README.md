# RAG App

RAG app with chat (default) and document ingestion interfaces.

## Stack

- Frontend: React + Vite + Tailwind + shadcn/ui
- Backend: Python + FastAPI
- Database: PostgreSQL + pgvector
- LLM: Alibaba Cloud Bailian
- Observability: LangSmith

## Prerequisites

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | >= 3.11 | 后端运行环境 |
| uv | 最新 | Python 包管理（替代 pip/poetry） |
| Node.js | >= 18 | 前端运行环境 |
| PostgreSQL | >= 15 | 需安装 `pgvector` 和 `pg_trgm` 扩展 |

## 环境变量

在项目根目录创建 `rag.env`，按需填写以下配置：

```env
# 数据库
DB_HOST=xxx
DB_PORT=5432
DB_NAME=rag_paper_db
DB_USER=xxx
DB_PASSWORD=xxx

# LLM（阿里云百炼）
DASHSCOPE_API_KEY=xxx

# 可选
RETRIEVAL_MODE=real
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=
```

## 启动后端

```bash
# 1. 安装 Python 依赖
uv sync

# 2. 启动（默认 http://127.0.0.1:8000，热重载）
uv run rag
```

后端入口为 `src/rag/main.py` 中的 `main()` 函数，启动后会：
- 初始化数据库连接池
- 执行 `src/rag/sql/init.sql`（建表/扩展/索引）
- 监听 `127.0.0.1:8000`

## 启动前端

```bash
# 1. 安装前端依赖（首次）
cd frontend
npm install

# 2. 启动开发服务器（默认 http://localhost:5173）
npm run dev
```

前端会自动代理 `/api` 请求到后端 `http://127.0.0.1:8000`。

## 同时启动前后端（开发模式）

打开两个终端窗口：

```bash
# 终端 1：后端
uv run rag

# 终端 2：前端
cd frontend && npm run dev
```

然后访问 http://localhost:5173 即可使用。

## 测试

```bash
# 运行全部非 live 测试（不依赖外部 LLM API）
uv run pytest

# 运行 live 测试（调用真实 LLM API，需 RUN_LIVE_TESTS=1）
RUN_LIVE_TESTS=1 uv run pytest tests/live/
```
