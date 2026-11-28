CREATE TABLE IF NOT EXISTS api_rate_limits (
 user_id TEXT NOT NULL, window_start INTEGER NOT NULL, hits INTEGER NOT NULL,
 PRIMARY KEY(user_id,window_start)
);
CREATE INDEX IF NOT EXISTS api_rate_window_idx ON api_rate_limits(window_start);
CREATE INDEX IF NOT EXISTS rooms_updated_idx ON rooms(updated_at);
