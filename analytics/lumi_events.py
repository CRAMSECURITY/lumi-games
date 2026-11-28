"""Local, opt-in daily activity store. No message content or raw Telegram IDs."""
import datetime as dt
import hashlib
import hmac
import sqlite3

EVENTS = frozenset({'open', 'browse', 'match', 'game', 'signup'})
RETENTION_DAYS = 90

def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS activity (subject TEXT NOT NULL, day TEXT NOT NULL, event TEXT NOT NULL, PRIMARY KEY(subject,day,event))')
    db.execute('CREATE INDEX IF NOT EXISTS activity_day ON activity(day,event,subject)')
    db.commit()

def subject(key, user_id):
    if not isinstance(key, bytes) or len(key)<32 or type(user_id) is not int or user_id<=0:
        raise ValueError('Invalid analytics identity')
    return hmac.new(key, b'lumi-analytics-v1:'+str(user_id).encode(), hashlib.sha256).hexdigest()

def record(db,key,user_id,event,day,today):
    if event not in EVENTS or not today-dt.timedelta(days=RETENTION_DAYS-1)<=day<=today:
        raise ValueError('Invalid event or date')
    with db:
        db.execute('INSERT OR IGNORE INTO activity VALUES (?,?,?)',(subject(key,user_id),day.isoformat(),event))

def erase(db,key,user_id):
    with db:
        db.execute('DELETE FROM activity WHERE subject=?',(subject(key,user_id),))

def prune(db,today):
    with db:
        db.execute('DELETE FROM activity WHERE day<?',((today-dt.timedelta(days=RETENTION_DAYS-1)).isoformat(),))

def report(db,today,coverage_start):
    # Completed UTC days only. Coverage must be established by the operator.
    end=today-dt.timedelta(days=1)
    def active(days):
        start=end-dt.timedelta(days=days-1)
        if coverage_start>start: return None
        return db.execute('SELECT count(DISTINCT subject) FROM activity WHERE day BETWEEN ? AND ?', (start.isoformat(),end.isoformat())).fetchone()[0]
    result={'through_utc':end.isoformat(),'dau':active(1),'wau':active(7),'mau_30d':active(30),'retention':{}}
    for offset in (1,7,30):
        cohort=end-dt.timedelta(days=offset)
        if coverage_start>cohort:
            result['retention'][str(offset)]=None; continue
        n,r=db.execute('''SELECT count(*),coalesce(sum(EXISTS(SELECT 1 FROM activity b WHERE b.subject=a.subject AND b.day=?)),0) FROM activity a WHERE a.day=? AND a.event='signup' ''',(end.isoformat(),cohort.isoformat())).fetchone()
        result['retention'][str(offset)]={'cohort':cohort.isoformat(),'size':n,'returned':r,'rate':r/n if n else None}
    return result
