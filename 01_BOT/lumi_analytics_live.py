"""Optional first-party bot activity; no message text or external services."""
import datetime as dt
import secrets
import sqlite3
import json
from pathlib import Path


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS lumi_analytics_consent (user_id INTEGER PRIMARY KEY, subject TEXT NOT NULL UNIQUE)')
    db.execute('CREATE TABLE IF NOT EXISTS lumi_analytics_activity (subject TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY(subject,day))')
    db.execute('CREATE INDEX IF NOT EXISTS lumi_analytics_day ON lumi_analytics_activity(day)')
    db.execute('''CREATE TRIGGER IF NOT EXISTS lumi_analytics_delete AFTER DELETE ON profiles BEGIN
        DELETE FROM lumi_analytics_activity WHERE subject=(SELECT subject FROM lumi_analytics_consent WHERE user_id=OLD.user_id);
        DELETE FROM lumi_analytics_consent WHERE user_id=OLD.user_id;
    END''')


def opt_in(db, uid):
    db.execute('INSERT OR IGNORE INTO lumi_analytics_consent SELECT user_id, ? FROM profiles WHERE user_id=?',(secrets.token_hex(32),uid))
    return db.execute('SELECT 1 FROM lumi_analytics_consent WHERE user_id=?',(uid,)).fetchone() is not None


def opt_out(db, uid):
    db.execute('DELETE FROM lumi_analytics_activity WHERE subject=(SELECT subject FROM lumi_analytics_consent WHERE user_id=?)',(uid,))
    db.execute('DELETE FROM lumi_analytics_consent WHERE user_id=?',(uid,))


def record(db, uid, day):
    db.execute('''INSERT OR IGNORE INTO lumi_analytics_activity SELECT c.subject, ? FROM lumi_analytics_consent c JOIN profiles p USING(user_id) WHERE c.user_id=?''',(day.isoformat(),uid))


def prune(db, today):
    db.execute('DELETE FROM lumi_analytics_activity WHERE day<?',((today-dt.timedelta(days=89)).isoformat(),))


def report(db,today):
    end=today-dt.timedelta(days=1)
    result={'through_utc':end.isoformat(),'scope':'Opted-in bot users only; coverage and outages not verified; no Mini App events or signup cohorts.'}
    for days in (1,7,30):
        start=end-dt.timedelta(days=days-1)
        result[f'observed_{days}d']=db.execute('SELECT count(DISTINCT subject) FROM lumi_analytics_activity WHERE day BETWEEN ? AND ?',(start.isoformat(),end.isoformat())).fetchone()[0]
    return result

if __name__=='__main__':
    import sys
    from contextlib import closing
    try:
        with closing(sqlite3.connect(Path(sys.argv[1]).resolve(strict=True).as_uri()+'?mode=ro',uri=True)) as db:
            print(json.dumps(report(db,dt.datetime.now(dt.timezone.utc).date()),indent=2))
    except (OSError, sqlite3.Error, IndexError):
        sys.exit('Analytics unavailable')
