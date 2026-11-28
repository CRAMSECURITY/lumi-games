ALTER TABLE organizer_events ADD COLUMN capacity INTEGER NOT NULL DEFAULT 20 CHECK(capacity BETWEEN 1 AND 500);
CREATE TABLE event_registrations(event_id TEXT NOT NULL,user_id TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(event_id,user_id));
CREATE INDEX event_registration_user ON event_registrations(user_id,event_id);
CREATE TRIGGER event_registration_event_delete AFTER DELETE ON organizer_events BEGIN DELETE FROM event_registrations WHERE event_id=OLD.id; END;
CREATE TRIGGER event_registration_account_delete AFTER INSERT ON account_deletions BEGIN DELETE FROM event_registrations WHERE user_id=NEW.user_id; END;
