CREATE TABLE date_keys(code TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL);
CREATE TABLE date_plans(id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, place_id TEXT NOT NULL, day TEXT NOT NULL, time TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','accepted','declined','cancelled')), created_at INTEGER NOT NULL, CHECK(sender<>recipient));
CREATE INDEX date_plans_sender ON date_plans(sender,created_at);
CREATE INDEX date_plans_recipient ON date_plans(recipient,created_at);
CREATE TRIGGER date_account_delete AFTER INSERT ON account_deletions BEGIN DELETE FROM date_keys WHERE owner=NEW.user_id; DELETE FROM date_plans WHERE sender=NEW.user_id OR recipient=NEW.user_id; END;
CREATE TRIGGER date_key_used AFTER INSERT ON date_plans BEGIN DELETE FROM date_keys WHERE owner=NEW.recipient; END;
