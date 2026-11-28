"""Server-side economy checks; mutations run inside caller's write transaction."""
from datetime import datetime, timezone


def eligible_for_reward(db, uid):
    return db.execute('''SELECT 1 FROM profiles p WHERE p.user_id=? AND p.age>=18
        AND NOT EXISTS (SELECT 1 FROM account_suspensions s WHERE s.user_id=p.user_id
        AND (s.expires_at IS NULL OR s.expires_at>CURRENT_TIMESTAMP))''', (uid,)).fetchone() is not None


def pair_battles_today(db, a, b):
    return db.execute('''SELECT COUNT(*) FROM arena_battle_log l
        JOIN arena_challenges c ON c.id=l.challenge_id
        WHERE ((c.challenger=? AND c.defender=?) OR (c.challenger=? AND c.defender=?))
        AND l.created_at>=date('now')''', (a,b,b,a)).fetchone()[0]


def claim_training(db, uid, today=None):
    day = (today or datetime.now(timezone.utc).date()).isoformat()
    return db.execute('''UPDATE arena_heroes SET last_daily=? WHERE user_id=?
        AND (last_daily IS NULL OR last_daily<?)''', (day,uid,day)).rowcount == 1
