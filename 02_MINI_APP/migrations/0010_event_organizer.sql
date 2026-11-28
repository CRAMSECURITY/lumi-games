CREATE TABLE organizer_events(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, city TEXT NOT NULL, kind TEXT NOT NULL, starts_at INTEGER NOT NULL, venue TEXT NOT NULL, description TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','approved','rejected','cancelled')), created_at INTEGER NOT NULL);
CREATE INDEX organizer_event_owner ON organizer_events(owner,created_at);
CREATE INDEX organizer_event_public ON organizer_events(state,starts_at);
CREATE TRIGGER organizer_event_delete AFTER INSERT ON account_deletions BEGIN DELETE FROM organizer_events WHERE owner=NEW.user_id; END;
