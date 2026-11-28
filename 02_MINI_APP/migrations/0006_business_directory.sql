CREATE TABLE IF NOT EXISTS business_profiles (
 user_id TEXT PRIMARY KEY NOT NULL,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 60),
 role TEXT NOT NULL CHECK(role IN ('founder','investor','expert','mentor','other')),
 sector TEXT NOT NULL CHECK(length(sector) BETWEEN 1 AND 80),
 skills TEXT NOT NULL CHECK(length(skills)<=180),
 goal TEXT NOT NULL CHECK(goal IN ('partners','startup','learning')),
 revision TEXT NOT NULL,
 approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
 updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS business_directory_search ON business_profiles(approved,goal,updated_at DESC);
CREATE TRIGGER IF NOT EXISTS business_profile_account_delete AFTER INSERT ON account_deletions
BEGIN DELETE FROM business_profiles WHERE user_id=NEW.user_id; END;
