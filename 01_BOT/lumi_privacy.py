"""Remove obsolete administrative queue references during account deletion."""
def purge_admin_references(db, user_id):
    # Called inside the same transaction, before deleting source reports.
    db.execute("DELETE FROM admin_events WHERE type IN ('guard','verification') AND ref_id=?", (user_id,))
    db.execute("DELETE FROM admin_events WHERE type='report' AND ref_id IN (SELECT id FROM reports WHERE reporter_id=? OR reported_id=?)", (user_id, user_id))
