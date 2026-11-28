"""LUMI referrals: cosmetics only, no payment or competitive advantages."""
from lumi_economy import eligible_for_reward

REFERRAL_GOAL = 3
REFERRAL_DAILY_LIMIT = 30

def _valid_id(uid):
    return type(uid) is int and 0 < uid <= 2**63-1

def _suspended(db, uid):
    return db.execute("SELECT 1 FROM account_suspensions WHERE user_id=? AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP)", (uid,)).fetchone() is not None

def init_referrals(db):
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_referrals (
        invited_user_id INTEGER PRIMARY KEY,
        inviter_user_id INTEGER NOT NULL,
        invited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        CHECK (invited_user_id != inviter_user_id)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_lumi_referrals_inviter ON lumi_referrals(inviter_user_id,confirmed_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_lumi_referrals_daily ON lumi_referrals(inviter_user_id,invited_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_referral_rewards (
        user_id INTEGER PRIMARY KEY,
        unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')


def register_referral(db, invited_id, inviter_id):
    """Attribute a first visit once; only if invitee has no profile yet."""
    if not _valid_id(invited_id) or not _valid_id(inviter_id) or invited_id == inviter_id:
        return False
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    if _suspended(db, invited_id) or db.execute('SELECT 1 FROM profiles WHERE user_id=?', (invited_id,)).fetchone():
        return False
    # Referrer must be an existing adult with a completed profile.
    if not eligible_for_reward(db, inviter_id):
        return False
    if db.execute("SELECT COUNT(*) FROM lumi_referrals WHERE inviter_user_id=? AND invited_at>=date('now')", (inviter_id,)).fetchone()[0] >= REFERRAL_DAILY_LIMIT:
        return False
    cur = db.execute('''INSERT OR IGNORE INTO lumi_referrals(invited_user_id,inviter_user_id)
        VALUES(?,?)''', (invited_id, inviter_id))
    return cur.rowcount == 1


def confirm_registration(db, invited_id):
    """Confirm actual profile creation, never mere /start; unlock once at 3."""
    if not _valid_id(invited_id):
        return None
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    if not eligible_for_reward(db, invited_id):
        return None
    row = db.execute('SELECT inviter_user_id,confirmed_at FROM lumi_referrals WHERE invited_user_id=?', (invited_id,)).fetchone()
    if not row or row[1] is not None:
        return None
    inviter_id = row[0]
    if not eligible_for_reward(db, inviter_id):
        return None
    if not db.execute('UPDATE lumi_referrals SET confirmed_at=CURRENT_TIMESTAMP WHERE invited_user_id=? AND confirmed_at IS NULL', (invited_id,)).rowcount:
        return None
    count = referral_count(db, inviter_id)
    unlocked = False
    if count >= REFERRAL_GOAL:
        unlocked = db.execute('INSERT OR IGNORE INTO lumi_referral_rewards(user_id) VALUES(?)', (inviter_id,)).rowcount == 1
    return inviter_id, count, unlocked


def referral_count(db, user_id):
    return db.execute('SELECT COUNT(*) FROM lumi_referrals WHERE inviter_user_id=? AND confirmed_at IS NOT NULL', (user_id,)).fetchone()[0]


def has_referral_frame(db, user_id):
    return db.execute('SELECT 1 FROM lumi_referral_rewards WHERE user_id=?', (user_id,)).fetchone() is not None


def delete_referral_data(db, user_id):
    """Delete user-related invitation links on account deletion."""
    db.execute('DELETE FROM lumi_referrals WHERE invited_user_id=? OR inviter_user_id=?', (user_id, user_id))
    db.execute('DELETE FROM lumi_referral_rewards WHERE user_id=?', (user_id,))
