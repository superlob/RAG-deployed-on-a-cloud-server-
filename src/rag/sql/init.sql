-- 数据库初始化脚本
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_isolation ON users;
CREATE POLICY user_isolation ON users
    USING (id::text = current_setting('app.current_user_id', true))
    WITH CHECK (id::text = current_setting('app.current_user_id', true));

-- users 表不强制 RLS：登录/注册需要无 RLS 查询，认证隔离由应用层（JWT 解码 + 按 id 查询）保证
ALTER TABLE users NO FORCE ROW LEVEL SECURITY;

-- documents 表：存储用户上传的文档（文件内容以 BYTEA 形式存储）
CREATE TABLE IF NOT EXISTS documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_filename VARCHAR(255) NOT NULL,
    file_type         VARCHAR(50)  NOT NULL,
    file_size         BIGINT       NOT NULL,
    file_data         BYTEA        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents (user_id);

-- RLS 策略：用户只能访问自己的文档
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS documents_user_isolation ON documents;
CREATE POLICY documents_user_isolation ON documents
    USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

ALTER TABLE documents FORCE ROW LEVEL SECURITY;

-- ========================
-- Module 3: Chunking & Embedding
-- ========================

-- documents 表追加处理状态列（兼容已有数据）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) NOT NULL DEFAULT 'not_processed';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status_error TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

-- pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- document_chunks 表
CREATE TABLE IF NOT EXISTS document_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    content       TEXT NOT NULL,
    token_estimate INTEGER,
    section_title TEXT,
    page_number   INTEGER,
    metadata      JSONB NOT NULL DEFAULT '{}',
    embedding     vector(1024),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_user_id ON document_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

-- RLS: 文档块隔离
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_chunks_isolation ON document_chunks;
CREATE POLICY document_chunks_isolation ON document_chunks
    USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;

-- 进程重启时重置卡住的 processing 状态（需绕过 RLS）
CREATE OR REPLACE FUNCTION reset_stuck_documents() RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE n INTEGER;
BEGIN
  UPDATE documents
  SET processing_status = 'failed',
      status_error = '服务重启导致处理中断'
  WHERE processing_status = 'processing';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- ========================
-- Retrieval Module: 混合检索（关键词检索用 pg_trgm）
-- ========================

-- 中文关键词检索扩展：zhparser / pgroonga / pg_jieba 均不可用，
-- pg_trgm 以字符 trigram 方式工作，对 CJK 文本可用。
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- content 列 trigram GIN 索引（加速 ILIKE / % 相似度过滤）
CREATE INDEX IF NOT EXISTS idx_document_chunks_content_trgm ON document_chunks
    USING gin (content gin_trgm_ops);

-- ========================
-- Module 4: Chatting Interface
-- ========================

-- 会话表
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(255) NOT NULL DEFAULT '新对话',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(user_id, updated_at DESC);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversations_user_isolation ON conversations;
CREATE POLICY conversations_user_isolation ON conversations
    USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

ALTER TABLE conversations FORCE ROW LEVEL SECURITY;

-- 消息表（user / assistant / tool 三种角色，按 seq 单调递增）
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,
    seq             INTEGER NOT NULL,
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    tool_calls      JSONB,
    tool_call_id    VARCHAR(128),
    tool_name       VARCHAR(64),
    sources         JSONB,
    token_count     INTEGER,
    status          VARCHAR(20) NOT NULL DEFAULT 'completed',
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS messages_user_isolation ON messages;
CREATE POLICY messages_user_isolation ON messages
    USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));

ALTER TABLE messages FORCE ROW LEVEL SECURITY;

-- 服务重启时把卡在 streaming 状态的消息标记为中断（SECURITY DEFINER 绕过 RLS）
CREATE OR REPLACE FUNCTION reset_stuck_messages() RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE n INTEGER;
BEGIN
  UPDATE messages
  SET status = 'cancelled',
      error = COALESCE(error, '服务重启导致回复中断')
  WHERE status = 'streaming';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;
