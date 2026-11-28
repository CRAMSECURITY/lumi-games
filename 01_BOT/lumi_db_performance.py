"""Additive SQLite indexes and batched daily recommendation filtering."""
INDEXES = (
    'CREATE INDEX IF NOT EXISTS idx_profile_views_target ON profile_views(target_id)',
    'CREATE INDEX IF NOT EXISTS idx_browse_daily_day ON browse_daily(day)',
    'CREATE INDEX IF NOT EXISTS idx_starter_daily_day ON lumi_starter_daily(day)',
    'CREATE INDEX IF NOT EXISTS idx_support_status_updated ON support_tickets(status,updated_at)',
)

def install_indexes(db):
    for statement in INDEXES:
        db.execute(statement)

def moment_candidates(db, uid, settings):
    # Preserve the original mystery_eligible rules, including both directions
    # of blocks and discoverability for both users.
    rows = db.execute('''SELECT p.user_id,p.age,p.city,p.interests,p.gender,p.seeking
        FROM profiles p JOIN profiles me ON me.user_id=?
        WHERE p.user_id != me.user_id AND me.age>=18 AND p.age>=18
          AND p.age BETWEEN ? AND ?
          AND (me.seeking='все' OR me.seeking=p.gender)
          AND (p.seeking='все' OR p.seeking=me.gender)
          AND NOT EXISTS (SELECT 1 FROM moderation_holds h WHERE h.user_id=me.user_id AND (h.expires_at IS NULL OR h.expires_at>CURRENT_TIMESTAMP))
          AND NOT EXISTS (SELECT 1 FROM moderation_holds h WHERE h.user_id=p.user_id AND (h.expires_at IS NULL OR h.expires_at>CURRENT_TIMESTAMP))
          AND NOT EXISTS (SELECT 1 FROM privacy_settings s WHERE s.user_id=me.user_id AND s.discoverable=0)
          AND NOT EXISTS (SELECT 1 FROM privacy_settings s WHERE s.user_id=p.user_id AND s.discoverable=0)
          AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.user_id=me.user_id AND b.blocked_id=p.user_id)
          AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.user_id=p.user_id AND b.blocked_id=me.user_id)
          AND NOT EXISTS (SELECT 1 FROM reactions r WHERE r.from_user=me.user_id AND r.to_user=p.user_id AND r.liked=1)
        ''', (uid, settings[0], settings[1])).fetchall()
    return [r for r in rows if not settings[2] or r[2].casefold()==settings[2].casefold()]
