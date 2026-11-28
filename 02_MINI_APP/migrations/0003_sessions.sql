CREATE TABLE IF NOT EXISTS web_sessions (
 init_hash TEXT PRIMARY KEY,
 token_hash TEXT UNIQUE,
 user_id TEXT,
 expires_at INTEGER NOT NULL,
 retain_until INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_user ON web_sessions(user_id);
CREATE INDEX IF NOT EXISTS web_sessions_retention ON web_sessions(retain_until);
