CREATE UNIQUE INDEX IF NOT EXISTS business_revision_unique ON business_profiles(revision);
CREATE TABLE IF NOT EXISTS business_invites (
 id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','accepted','declined','cancelled')),
 created_at INTEGER NOT NULL, CHECK(sender<>recipient), UNIQUE(sender,recipient)
);
CREATE INDEX IF NOT EXISTS business_invites_recipient ON business_invites(recipient,created_at);
CREATE TRIGGER IF NOT EXISTS business_invites_delete AFTER DELETE ON business_profiles BEGIN
 DELETE FROM business_invites WHERE sender=OLD.user_id OR recipient=OLD.user_id;
END;
CREATE TRIGGER IF NOT EXISTS business_invites_change AFTER UPDATE OF revision,approved ON business_profiles WHEN NEW.revision<>OLD.revision OR NEW.approved=0 BEGIN
 DELETE FROM business_invites WHERE sender=OLD.user_id OR recipient=OLD.user_id;
END;
