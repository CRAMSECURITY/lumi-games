"""Opt-in club membership pilot. No public member lists or messaging."""
import secrets
from datetime import datetime, timezone, timedelta
from types import MappingProxyType
from lumi_economy import eligible_for_reward

CLUBS = MappingProxyType({'games': 'Игры', 'music': 'Музыка', 'travel': 'Путешествия', 'art': 'Творчество'})
ACTIVITIES = MappingProxyType({"games": "Поделись любимой игрой в разговоре с другом", "music": "Обсуди любимую песню с другом", "travel": "Обсуди город мечты с другом", "art": "Поделись творческой идеей с другом"})
CAPACITY = 200
MAX_MEMBERSHIPS = 3


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS lumi_club_accounts(uid INTEGER PRIMARY KEY, epoch TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS lumi_club_members(uid INTEGER NOT NULL, club TEXT NOT NULL, PRIMARY KEY(uid,club))')
    db.execute('CREATE TABLE IF NOT EXISTS lumi_club_activity(uid INTEGER NOT NULL, club TEXT NOT NULL, week TEXT NOT NULL, PRIMARY KEY(uid,club,week))')
    db.execute('''CREATE TRIGGER IF NOT EXISTS lumi_club_activity_delete AFTER DELETE ON lumi_club_members BEGIN
        DELETE FROM lumi_club_activity WHERE uid=OLD.uid AND club=OLD.club;
    END''')
    db.execute('CREATE INDEX IF NOT EXISTS lumi_club_count ON lumi_club_members(club)')
    db.execute('''CREATE TRIGGER IF NOT EXISTS lumi_club_delete AFTER DELETE ON profiles BEGIN
        DELETE FROM lumi_club_members WHERE uid=OLD.user_id;
        DELETE FROM lumi_club_accounts WHERE uid=OLD.user_id;
    END''')


def act(db, uid, action='view', club=None, epoch=None):
    if type(uid) is not int or not 0 < uid < 2**63 or action not in ('view','join','leave'):
        raise ValueError('invalid request')
    if action != 'view' and (type(club) is not str or club not in CLUBS or type(epoch) is not str):
        raise ValueError('invalid club selection')
    if db.in_transaction:
        raise ValueError('transaction already active')
    db.execute('BEGIN IMMEDIATE')
    try:
        if not eligible_for_reward(db, uid):
            db.rollback()
            return None
        if action == 'view':
            db.execute('INSERT OR IGNORE INTO lumi_club_accounts VALUES(?,?)', (uid,secrets.token_hex(16)))
        row = db.execute('SELECT epoch FROM lumi_club_accounts WHERE uid=?',(uid,)).fetchone()
        if not row or (action != 'view' and row[0] != epoch):
            db.rollback()
            return None
        owned = {r[0] for r in db.execute('SELECT club FROM lumi_club_members WHERE uid=?',(uid,))}
        status = 'view'
        if action == 'join':
            if club in owned: status = 'owned'
            elif len(owned) >= MAX_MEMBERSHIPS: status = 'limit'
            elif db.execute('SELECT COUNT(*) FROM lumi_club_members WHERE club=?',(club,)).fetchone()[0] >= CAPACITY: status = 'full'
            else:
                db.execute('INSERT INTO lumi_club_members VALUES(?,?)',(uid,club))
                owned.add(club)
                status = 'joined'
        elif action == 'leave':
            db.execute('DELETE FROM lumi_club_members WHERE uid=? AND club=?',(uid,club))
            owned.discard(club)
            status = 'left'
        db.commit()
        return row[0], sorted(owned), status
    except BaseException:
        db.rollback()
        raise


def week_key():
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()

def activities(db, uid, epoch, club=None, week=None):
    if type(uid) is not int or not 0 < uid < 2**63 or type(epoch) is not str:
        raise ValueError('invalid request')
    if club is not None and (type(club) is not str or club not in CLUBS or type(week) is not str):
        raise ValueError('invalid activity')
    if db.in_transaction:
        raise ValueError('transaction already active')
    db.execute('BEGIN IMMEDIATE')
    try:
        current = week_key()
        account = db.execute('SELECT epoch FROM lumi_club_accounts WHERE uid=?', (uid,)).fetchone()
        if not eligible_for_reward(db, uid) or not account or account[0] != epoch:
            db.rollback(); return None
        owned = {r[0] for r in db.execute('SELECT club FROM lumi_club_members WHERE uid=?', (uid,))}
        if club is not None and (club not in owned or week != current):
            db.rollback(); return None
        db.execute('DELETE FROM lumi_club_activity WHERE uid=? AND week<>?', (uid,current))
        if club is not None:
            db.execute('INSERT OR IGNORE INTO lumi_club_activity VALUES(?,?,?)', (uid,club,current))
        completed = {r[0] for r in db.execute('SELECT club FROM lumi_club_activity WHERE uid=? AND week=?', (uid,current))}
        db.commit()
        return current, sorted(owned), sorted(completed)
    except BaseException:
        db.rollback(); raise
