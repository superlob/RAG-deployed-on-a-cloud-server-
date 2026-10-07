# RAG App

RAG app with chat and document ingestion interfaces.

## 同时启动前后端（开发模式）

打开两个终端窗口：

```bash
# 终端 1：后端
uv sync          # 安装依赖（首次）
uv run rag       # 启动，默认 http://127.0.0.1:8000
```

```bash
# 终端 2：前端  
cd frontend
npm install      # 安装依赖（首次）
npm run dev      # 启动，默认 http://localhost:5173
```

访问 http://localhost:5173 即可使用。

> **注意**：需要先配置 `rag.env`，参考 `rag.env.example`