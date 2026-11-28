CREATE TABLE IF NOT EXISTS rooms (
 id TEXT PRIMARY KEY, host_id TEXT NOT NULL, guest_id TEXT,
 status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','playing','finished')),
 round INTEGER NOT NULL DEFAULT 0,
 round_started INTEGER,
 created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rooms_host_idx ON rooms(host_id,created_at);
CREATE INDEX IF NOT EXISTS rooms_guest_idx ON rooms(guest_id,created_at);
CREATE TABLE IF NOT EXISTS answers (
 room_id TEXT NOT NULL, round INTEGER NOT NULL,
 user_id TEXT NOT NULL, choice INTEGER NOT NULL,
 correct INTEGER NOT NULL, points INTEGER NOT NULL,
 answered_at INTEGER NOT NULL,
 PRIMARY KEY(room_id,round,user_id)
);
CREATE TABLE IF NOT EXISTS morning_results (
 day TEXT NOT NULL, user_id TEXT NOT NULL, category TEXT NOT NULL,
 score INTEGER NOT NULL, PRIMARY KEY(day,user_id,category)
);
