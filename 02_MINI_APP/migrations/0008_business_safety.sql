CREATE TABLE IF NOT EXISTS business_invite_history(id TEXT PRIMARY KEY,sender TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS business_history_sender ON business_invite_history(sender,created_at);
INSERT OR IGNORE INTO business_invite_history SELECT id,sender,created_at FROM business_invites;
CREATE TRIGGER IF NOT EXISTS business_history_record AFTER INSERT ON business_invites BEGIN
 INSERT INTO business_invite_history VALUES(NEW.id,NEW.sender,NEW.created_at);
END;
CREATE TABLE IF NOT EXISTS business_blocks(blocker TEXT NOT NULL,blocked TEXT NOT NULL,PRIMARY KEY(blocker,blocked),CHECK(blocker<>blocked));
CREATE TRIGGER IF NOT EXISTS business_block_cancel AFTER INSERT ON business_blocks BEGIN
 DELETE FROM business_invites WHERE (sender=NEW.blocker AND recipient=NEW.blocked) OR (sender=NEW.blocked AND recipient=NEW.blocker);
END;
CREATE TABLE IF NOT EXISTS business_reports(invite_id TEXT NOT NULL,reporter TEXT NOT NULL,reported TEXT NOT NULL,reason TEXT NOT NULL CHECK(reason IN ('spam','fraud','harassment','other')),created_at INTEGER NOT NULL,PRIMARY KEY(invite_id,reporter));
CREATE TRIGGER IF NOT EXISTS business_safety_delete AFTER INSERT ON account_deletions BEGIN
 DELETE FROM business_blocks WHERE blocker=NEW.user_id OR blocked=NEW.user_id;
 DELETE FROM business_reports WHERE reporter=NEW.user_id OR reported=NEW.user_id;
 DELETE FROM business_invite_history WHERE sender=NEW.user_id;
END;
