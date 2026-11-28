"""LUMI 3.8 shared operational helpers; standard-library only.

No network, no raw profiles or messages in telemetry. Tables live in lumi.db.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone

METRIC_NAMES = frozenset({'update', 'slow', 'error', 'browse', 'like', 'match', 'security'})

def init_ops(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_notification_settings (
        user_id INTEGER PRIMARY KEY,
        likes INTEGER NOT NULL DEFAULT 1 CHECK(likes IN (0,1)),
        matches INTEGER NOT NULL DEFAULT 1 CHECK(matches IN (0,1)),
        quiet INTEGER NOT NULL DEFAULT 0 CHECK(quiet IN (0,1)))''')
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_ops_daily (
        day TEXT NOT NULL, metric TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(day,metric))''')
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_alert_cooldowns (
        category TEXT PRIMARY KEY, last_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS lumi_security_flags (
        user_id INTEGER PRIMARY KEY, last_alert_at TEXT NOT NULL)''')


def record_metric(db, metric: str, count: int = 1):
    if metric not in METRIC_NAMES or not 1 <= count <= 100_000:
        raise ValueError('Unsupported metric')
    db.execute('''INSERT INTO lumi_ops_daily(day,metric,count)
                  VALUES(date('now'),?,?)
                  ON CONFLICT(day,metric) DO UPDATE SET count=count+excluded.count''',
               (metric,count))


def can_notify(db, uid: int, kind: str, now=None) -> bool:
    if kind not in {'likes','matches'}:
        raise ValueError('Unknown notification type')
    row=db.execute('SELECT likes,matches,quiet FROM lumi_notification_settings WHERE user_id=?',(uid,)).fetchone()
    if not row: return True
    enabled=row[0] if kind=='likes' else row[1]
    if not enabled: return False
    # UTC by design: no inference of a user's timezone.
    h=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).hour
    return not (row[2] and (h >= 22 or h < 8))


def toggle_notify(db, uid: int, field: str):
    if field not in {'likes','matches','quiet'}:
        raise ValueError('Invalid setting')
    db.execute('INSERT OR IGNORE INTO lumi_notification_settings(user_id) VALUES(?)',(uid,))
    db.execute({'likes':'UPDATE lumi_notification_settings SET likes=1-likes WHERE user_id=?', 'matches':'UPDATE lumi_notification_settings SET matches=1-matches WHERE user_id=?', 'quiet':'UPDATE lumi_notification_settings SET quiet=1-quiet WHERE user_id=?'}[field],(uid,))


def flag_due(db, uid: int) -> bool:
    """Once per UTC day per account; does not automatically ban anybody."""
    db.execute('INSERT OR IGNORE INTO lumi_security_flags(user_id,last_alert_at) VALUES(?,datetime(\'now\',\'-2 days\'))',(uid,))
    changed=db.execute('''UPDATE lumi_security_flags SET last_alert_at=CURRENT_TIMESTAMP
        WHERE user_id=? AND last_alert_at <= datetime('now','-24 hours')''',(uid,))
    return changed.rowcount == 1


def alert_due(db, category: str, minutes: int = 30) -> bool:
    if category not in {'slow','error','backup','database'}: raise ValueError('Invalid alert')
    minutes=max(1,min(1440,minutes))
    db.execute("INSERT OR IGNORE INTO lumi_alert_cooldowns(category,last_at) VALUES (?,datetime('now','-2 days'))",(category,))
    updated=db.execute('''UPDATE lumi_alert_cooldowns SET last_at=CURRENT_TIMESTAMP
        WHERE category=? AND last_at <= datetime('now',?)''',(category,f'-{minutes} minutes'))
    return updated.rowcount == 1


def analytics(db):
    """Aggregate only; no user names, IDs, or message bodies in the result."""
    def num(sql): return db.execute(sql).fetchone()[0]
    return {
        'profiles':num('SELECT COUNT(*) FROM profiles'),
        'hidden':num('SELECT COUNT(*) FROM privacy_settings WHERE discoverable=0'),
        'likes':num('SELECT COUNT(*) FROM reactions WHERE liked=1'),
        'matches':num('''SELECT COUNT(*) FROM reactions a JOIN reactions b
                         ON a.from_user=b.to_user AND a.to_user=b.from_user
                         WHERE a.liked=1 AND b.liked=1 AND a.from_user<b.from_user'''),
        'views_today':num("SELECT COALESCE(SUM(views),0) FROM browse_daily WHERE day=date('now')"),
        'tickets_open':num("SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','delivery_unknown')"),
        'verification_pending':num("SELECT COUNT(*) FROM verification_requests WHERE status='review'"),
        'premium_active':num("SELECT COUNT(*) FROM premium_subscriptions WHERE expires_at>strftime('%s','now')"),
        'paid_orders':num("SELECT COUNT(*) FROM premium_payments WHERE refunded=0"),
        'errors_today':num("SELECT COALESCE((SELECT count FROM lumi_ops_daily WHERE day=date('now') AND metric='error'),0)"),
        'slow_today':num("SELECT COALESCE((SELECT count FROM lumi_ops_daily WHERE day=date('now') AND metric='slow'),0)"),
    }
