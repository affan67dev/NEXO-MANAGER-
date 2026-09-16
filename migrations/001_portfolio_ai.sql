CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    repository TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('public','private','internal')),
    version_sha TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT,
    UNIQUE(repository, file_path, version_sha)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_public_project
    ON knowledge_documents(visibility, project, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_repository_path
    ON knowledge_documents(repository, file_path, version_sha);

CREATE TABLE IF NOT EXISTS visitor_conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel = 'portfolio_web')
);

CREATE INDEX IF NOT EXISTS idx_visitor_conversation_session
    ON visitor_conversation(session_id, id);
CREATE INDEX IF NOT EXISTS idx_visitor_conversation_channel_session
    ON visitor_conversation(channel, session_id, id);

INSERT OR IGNORE INTO schema_migrations(version) VALUES ('001_portfolio_ai');
