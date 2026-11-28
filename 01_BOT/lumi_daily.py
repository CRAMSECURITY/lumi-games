"""LUMI daily hero EXP gifts. UTC dates, atomic and idempotent claim."""
from datetime import date, timedelta, datetime, timezone


def init_daily_rewards(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lumi_daily_rewards (
        user_id INTEGER PRIMARY KEY,
        last_claim_day TEXT NOT NULL,
        streak INTEGER NOT NULL DEFAULT 1,
        total_claims INTEGER NOT NULL DEFAULT 1,
        CHECK(streak >= 1 AND total_claims >= 1)
    )""")


def daily_reward_status(db, user_id, today=None):
    today = today or datetime.now(timezone.utc).date()
    row = db.execute("SELECT last_claim_day,streak,total_claims FROM lumi_daily_rewards WHERE user_id=?", (user_id,)).fetchone()
    return {"claimed_today": bool(row and row[0] == today.isoformat()),
            "streak": (row[1] if row else 0), "total_claims": (row[2] if row else 0)}


def claim_daily_reward(db, user_id, today=None):
    """Call inside BEGIN IMMEDIATE transaction; caller awards XP in same transaction."""
    today = today or datetime.now(timezone.utc).date()
    day = today.isoformat()
    row = db.execute("SELECT last_claim_day,streak,total_claims FROM lumi_daily_rewards WHERE user_id=?", (user_id,)).fetchone()
    if row and row[0] >= day:
        return {"awarded": False, "xp": 0, "streak": row[1]}
    streak = row[1] + 1 if row and row[0] == (today - timedelta(days=1)).isoformat() else 1
    xp = 35 if streak % 7 == 0 else 15
    if row:
        db.execute("UPDATE lumi_daily_rewards SET last_claim_day=?,streak=?,total_claims=total_claims+1 WHERE user_id=?", (day,streak,user_id))
    else:
        db.execute("INSERT INTO lumi_daily_rewards(user_id,last_claim_day,streak) VALUES(?,?,?)", (user_id,day,streak))
    return {"awarded": True, "xp": xp, "streak": streak}
