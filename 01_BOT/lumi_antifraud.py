"""Deduplicate repeat complaints without preventing the user from blocking a peer."""
def record_report_once(db, reporter, target):
    if not db.in_transaction:
        raise RuntimeError('report requires caller write transaction')
    if reporter == target:
        return None
    row = db.execute("SELECT 1 FROM reports WHERE reporter_id=? AND reported_id=? AND created_at>=datetime('now','-24 hours') LIMIT 1", (reporter,target)).fetchone()
    if row:
        return None
    return db.execute('INSERT INTO reports(reporter_id,reported_id) VALUES (?,?)', (reporter,target)).lastrowid


def isolate_pair(db, user_id, peer_id):
    """Block and revoke pair-specific pending interactions in one write transaction."""
    if not db.in_transaction or user_id == peer_id:
        raise ValueError('Pair isolation requires a transaction and distinct users')
    pair = (user_id, peer_id, peer_id, user_id)
    db.execute('INSERT OR IGNORE INTO blocks(user_id,blocked_id) VALUES (?,?)', pair[:2])
    db.execute("UPDATE arena_challenges SET status='cancelled',resolved_at=CURRENT_TIMESTAMP WHERE status='pending' AND ((challenger=? AND defender=?) OR (challenger=? AND defender=?))", pair)
    for sql in (
        'DELETE FROM game_sessions WHERE (user_a=? AND user_b=?) OR (user_a=? AND user_b=?)',
        'DELETE FROM active_chats WHERE (user_id=? AND peer_id=?) OR (user_id=? AND peer_id=?)',
        'DELETE FROM contact_requests WHERE (requester_id=? AND recipient_id=?) OR (requester_id=? AND recipient_id=?)',
    ):
        db.execute(sql, pair)
