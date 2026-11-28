"""Bound retention of verification material without changing completed verification."""
def expire_verification_material(db):
    # Pending video reviews expire after 30 days; never revoke verified profiles.
    db.execute("UPDATE profile_extras SET verification_status='none' WHERE verified=0 AND verification_status IN ('review','pending') AND user_id IN (SELECT user_id FROM verification_requests WHERE status='review' AND COALESCE(submitted_at,created_at) < datetime('now','-30 days'))")
    db.execute("DELETE FROM admin_events WHERE type='verification' AND ref_id IN (SELECT user_id FROM verification_requests WHERE status='review' AND COALESCE(submitted_at,created_at) < datetime('now','-30 days'))")
    db.execute("DELETE FROM verification_requests WHERE status='review' AND COALESCE(submitted_at,created_at) < datetime('now','-30 days')")
    # Completed decisions are represented in profile_extras, not in this queue.
    db.execute("DELETE FROM verification_requests WHERE status IN ('approved','rejected') AND created_at < datetime('now','-30 days')")


def purge_closed_support_events(db):
    db.execute("DELETE FROM admin_events WHERE type='ticket' AND ref_id IN (SELECT id FROM support_tickets WHERE status='closed' AND updated_at < datetime('now','-90 days'))")
