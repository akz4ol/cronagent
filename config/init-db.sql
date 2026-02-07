-- CronAgent PostgreSQL Initialization
-- This script runs when the PostgreSQL container is first created

-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Create schemas
CREATE SCHEMA IF NOT EXISTS cronagent;

-- Sessions table
CREATE TABLE IF NOT EXISTS cronagent.sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_path TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON cronagent.sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON cronagent.sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON cronagent.sessions(last_active);

-- Session messages table
CREATE TABLE IF NOT EXISTS cronagent.session_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cronagent.sessions(session_id) ON DELETE CASCADE,
    message_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON cronagent.session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_index ON cronagent.session_messages(session_id, message_index);

-- Session insights table
CREATE TABLE IF NOT EXISTS cronagent.session_insights (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cronagent.sessions(session_id) ON DELETE CASCADE,
    insight_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_insights_session ON cronagent.session_insights(session_id);
CREATE INDEX IF NOT EXISTS idx_insights_type ON cronagent.session_insights(insight_type);

-- Scheduled jobs table
CREATE TABLE IF NOT EXISTS cronagent.scheduled_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_data JSONB NOT NULL,
    execution_type TEXT NOT NULL,
    execution_data JSONB NOT NULL,
    retry_config JSONB DEFAULT '{}'::jsonb,
    notification_config JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'active',
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON cronagent.scheduled_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON cronagent.scheduled_jobs(next_run);

-- Job runs table
CREATE TABLE IF NOT EXISTS cronagent.job_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES cronagent.scheduled_jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    attempt INTEGER DEFAULT 1,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    output TEXT,
    error TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON cronagent.job_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON cronagent.job_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started ON cronagent.job_runs(started_at);

-- Knowledge documents table with vector embeddings
CREATE TABLE IF NOT EXISTS cronagent.knowledge_documents (
    id SERIAL PRIMARY KEY,
    doc_id TEXT UNIQUE NOT NULL,
    project_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    file_path TEXT,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding vector(1536),  -- OpenAI embedding dimension
    importance_score REAL DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_knowledge_project ON cronagent.knowledge_documents(project_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_source ON cronagent.knowledge_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON cronagent.knowledge_documents(content_hash);

-- Create vector similarity search index (IVFFlat for performance)
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON cronagent.knowledge_documents
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION cronagent.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_jobs_updated_at ON cronagent.scheduled_jobs;
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON cronagent.scheduled_jobs
    FOR EACH ROW EXECUTE FUNCTION cronagent.update_updated_at();

DROP TRIGGER IF EXISTS update_knowledge_updated_at ON cronagent.knowledge_documents;
CREATE TRIGGER update_knowledge_updated_at
    BEFORE UPDATE ON cronagent.knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION cronagent.update_updated_at();

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA cronagent TO cronagent;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA cronagent TO cronagent;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA cronagent TO cronagent;

-- Set default search path
ALTER DATABASE cronagent SET search_path TO cronagent, public;

-- Output success message
DO $$
BEGIN
    RAISE NOTICE 'CronAgent database initialized successfully';
END
$$;
