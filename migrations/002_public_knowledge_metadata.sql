-- Metadata columns are added idempotently by core.portfolio_store.ensure_schema()
-- because SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS.
INSERT OR IGNORE INTO schema_migrations(version) VALUES ('002_public_knowledge_metadata');
