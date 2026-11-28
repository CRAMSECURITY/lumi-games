CREATE TABLE IF NOT EXISTS account_deletions (
 user_id TEXT NOT NULL,
 request_ts INTEGER NOT NULL,
 block_until INTEGER NOT NULL,
 PRIMARY KEY(user_id,request_ts)
);
CREATE INDEX IF NOT EXISTS account_deletions_retention ON account_deletions(block_until);
