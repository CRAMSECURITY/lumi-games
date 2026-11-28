CREATE TABLE date_blocks(blocker TEXT NOT NULL, blocked TEXT NOT NULL, PRIMARY KEY(blocker,blocked), CHECK(blocker<>blocked));
CREATE INDEX date_blocks_reverse ON date_blocks(blocked);
CREATE TRIGGER date_block_cancel AFTER INSERT ON date_blocks BEGIN
 UPDATE date_plans SET state='cancelled' WHERE state IN ('pending','accepted') AND ((sender=NEW.blocker AND recipient=NEW.blocked) OR (sender=NEW.blocked AND recipient=NEW.blocker));
END;
CREATE TRIGGER date_block_delete AFTER INSERT ON account_deletions BEGIN DELETE FROM date_blocks WHERE blocker=NEW.user_id OR blocked=NEW.user_id; END;
