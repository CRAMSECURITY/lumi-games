ALTER TABLE business_profiles ADD COLUMN moderation_decision TEXT NOT NULL DEFAULT 'pending' CHECK(moderation_decision IN ('pending','approved','rejected'));
UPDATE business_profiles SET moderation_decision='approved' WHERE approved=1;
ALTER TABLE business_reports ADD COLUMN reviewed_at INTEGER;
CREATE INDEX business_moderation_queue ON business_profiles(approved,moderation_decision,updated_at);
CREATE INDEX business_report_queue ON business_reports(reviewed_at,created_at);
