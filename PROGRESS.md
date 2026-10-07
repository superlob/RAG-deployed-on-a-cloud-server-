# Progress

 Update this file as you complete modules - Claude Code reads this to understand where you are in the project.

## Convention
- `[ ]` = Not started
- `[-]` = In progress
- `[x]` = Completed

## Modules

### Module 1: Authentication
- [x] Build Cycle 1: Backend Foundation (config, db, auth API) ✅
  - 数据库 schema: users 表 + RLS 策略
  - JWT 认证: access token (30min) + refresh token (7 days)
  - 5 个 API endpoints: register, login, logout, refresh, /me
  - httpOnly cookies, bcrypt 密码哈希
  - 已验证: curl 测试全部通过
- [x] Build Cycle 2: Frontend Foundation (Vite + Tailwind + shadcn/ui) ✅
  - Vite + React + TypeScript 项目初始化
  - Tailwind CSS v4 配置 + shadcn/ui 基础组件
  - React Router 路由设置
  - API 客户端 + Vite proxy 配置
- [x] Build Cycle 3: Auth UI + Integration ✅
  - 登录页面 + 表单验证
  - 注册页面 + 表单验证
  - 首页 + 用户状态管理
  - API 集成（登录/注册/登出/获取用户信息）
- [x] Build Cycle 4: Bug Fix + Polish ✅
  - 修复 ApiError 导出问题：`export type` 导致 `instanceof` 失效，改为 `export class` + 属性检查
  - 修复 HashRouter 路由跳转：首页 `<a href>` 改为 `<Link to>`
  - TypeScript 类型导入规范：`type User` 使用 `import type` 语法
  - 已验证：首页/登录/注册页面渲染正常，路由跳转正常

### Module 3: Chunking and Embedding
- [x] Build Cycle 1: 依赖 + Schema + 文本提取 + 分块 ✅
  - 新增依赖: pypdf, python-docx, httpx; dev: pytest, pytest-asyncio, reportlab
  - 数据库 schema: document_chunks 表 (vector(1024) + HNSW) + documents 状态列 + RLS + reset_stuck_documents()
  - 文本提取: PDF (pypdf + 字号标题检测) + DOCX (python-docx, 标题/表格) + .doc 拒绝
  - 递归/Sentence 分块: 句边界分隔符 + overlap 合并 + section/page 元数据
  - 29 项单元测试全部通过
- [x] Build Cycle 2: Embedding 服务 + 处理流水线 + API ✅
  - pgvector 0.8.6 安装完成，模型 qwen3.7-text-embedding (1024维) 验证可用
  - DashScopeEmbedding: 兼容模式批量调用 (batch=10) + 瞬时错误指数退避重试 (3次)
  - EmbeddingProvider Protocol 抽象，实现可替换
  - 处理流水线: 提取→分块→embedding→事务入库，失败写 status_error
  - 3 个 API: POST /{id}/process (202 + 409 并发保护), GET /{id}/status, GET /{id}/chunks
  - 修复: JSONB 列需 json.dumps 序列化 (asyncpg 不自动转换 dict)
  - 启动时 reset_stuck_documents() 重置卡住的处理状态
  - E2E 31/31 通过: DOCX/PDF 完整流水线、向量维度、级联删除、跨用户隔离 (status/chunks/process/delete 均 404)
- [x] Build Cycle 3: 前端 UI ✅
  - api.ts: DocumentInfo 新增状态字段 + process/getStatus/getChunks 端点
  - DocumentsPage: 状态列 Badge (未处理/处理中/已嵌入/失败+错误提示)、向量化按钮、处理中每 3s 轮询、分块查看对话框
  - TypeScript 编译 + 生产构建通过
  - 注: 本会话无浏览器 MCP，页面交互未做可视化验证，建议用户手动验收

### Module 2: Document Ingestion
- [x] Build Cycle 1: Backend (数据库 + API) ✅
  ...
- [x] Build Cycle 2: Frontend (文档管理 UI) ✅
  ...

### Module 4: Chatting Interface
- [x] Build Cycle 1: 依赖 + Schema + 上下文管理 + 检索接口 Mock ✅
  - 新增依赖: openai
  - 数据库 schema: conversations 表 + messages 表 + RLS + FORCE ROW LEVEL SECURITY
  - 启动时 reset_stuck_messages() 重置卡住的消息
  - 配置新增: OPENAI_API_KEY, OPENAI_BASE_URL, CHAT_MODEL, CHAT_MAX_CONTEXT_TOKENS, RETRIEVAL_MODE 等
  - context.py: token估算(中英混合)、轮次分组、最近N轮、超预算丢最旧、tool_calls/tool结果保留
  - retrieval.py: RetrievalProvider Protocol + RETRIEVE_TOOL_SPEC + MockRetrieval + NullRetrieval
  - 55 项单元测试通过 (test_chat_context + test_chat_retrieval)
  - SQL 验证: conversations/messages 表存在、RLS+FORCE RLS 生效、reset_stuck_messages 函数存在
- [x] Build Cycle 2: LLM 客户端 + 工具循环 + SSE + API ✅
  - ChatLLM Protocol + OpenAIChatLLM (流式+工具) + ScriptedLLM 测试替身
  - run_chat_turn 编排: 历史载入→context→工具循环→SSE事件流→持久化
  - API 路由: 创建/列表/重命名/删除会话 + SSE流式发送消息
  - 集成测试(test_chat_service=14, test_chat_live=4)
  - 验证: 非 live 98 项全部通过；live 4 项全部通过（真实 LLM + SSE + HTTP 全链路）
- [x] Build Cycle 3: 前端聊天 UI ✅
  - `api.ts`: 新增 ConversationInfo/MessageItem/SourceItem/StreamHandlers 类型 + conversationsApi + streamChat SSE 解析器
  - `ChatPage.tsx`: 主聊天页面，侧栏会话列表 + 消息区 + 输入区，SSE 流式逐字渲染，自动滚动
  - `ConversationList.tsx`: 会话侧栏（新建/选中/重命名/删除/空状态），Dialog 确认
  - `MessageBubble.tsx`: 用户/助手气泡，流式光标动画，错误提示，来源卡片
  - `SourceList.tsx`: 来源折叠面板（文档名 + 页码/章节 + 摘要 snippet + score）
  - `ChatInput.tsx`: textarea 自适应高度，Enter 发送/Shift+Enter 换行，流式时切换停止按钮
  - 路由: App.tsx 添加 /chat 路由，HomePage 添加 AI 对话入口
  - TypeScript 编译通过，Vite 生产构建通过

### Module 5: Retrieval
- [x] Build Cycle 1: 混合检索（向量 + 关键词 + RRF）✅
  - SQL: 启用 pg_trgm 扩展 + content 列 trigram GIN 索引 (idx_document_chunks_content_trgm)
    - 中文关键词方案: 验证后确认 zhparser / pgroonga / pg_jieba 不可用，选用 pg_trgm（字符 trigram）
    - word_similarity + ILIKE 子串匹配，GREATEST 取高者排序
  - 配置新增: RETRIEVAL_VECTOR_K=20 / RETRIEVAL_KEYWORD_K=20 / RETRIEVAL_RRF_K=60
  - RETRIEVAL_TOP_K 4→8（符合检索模块要求的 5–10）；rag.env: RETRIEVAL_MODE=real
  - src/rag/retrieval/: rrf.py（纯函数融合）+ provider.py（HybridRetrieval）+ __init__.py
    - HybridRetrieval.is_mock=False，可注入 embedding_provider 便于测试
    - 向量检索: embedding <=> query::vector (HNSW cosine)，关键词检索: word_similarity Top 20
    - rrf_merge 去重融合 (k=60)，并列按 best_rank，返回 top_k（夹取 1..10）
    - 全部参数化 SQL；RLS + 显式 user_id 双重隔离；空查询/空用户返回 []
  - 集成进 Chatting Interface: get_retrieval_provider('real') 现返回 HybridRetrieval（不再回退 Mock）
  - 测试: tests/test_retrieval.py = TestRRF(6) + TestHybridRetrievalIntegration(6)
    - 集成测试用 FakeEmbedding 注入，验证向量语义、元数据、关键词分支贡献、top_k、跨用户隔离
  - 更新: test_chat_retrieval.py（real→HybridRetrieval）+ live/test_chat_live.py（真实检索流：上传+处理文档后验证来源）
  - 验证: 非 live 112 项全部通过；真实 DashScope embedding 冒烟测试通过（语义片段排第一）
- [x] Bug Fix: 工具轮次达上限时直接兜底、不生成回答 ✅
  - 现象：模型连续检索多轮（逐步细化查询）达 CHAT_MAX_TOOL_ROUNDS 后，直接输出兜底文案，无最终回答
  - 根因：service.py 达上限时直接 break，未给模型基于检索结果收尾生成的机会
  - 修复：达上限后追加一次无工具的强制收尾 LLM 调用（流式输出最终回答），异常路径照旧 error+persist
  - 测试：test_max_tool_rounds_limited 改为断言「3 轮工具 + 1 次无工具收尾（共 4 次调用）+ 最终回答」
  - 验证：非 live 112 通过；live 真实检索流通过（上传→处理→提问→检索→生成回答）
