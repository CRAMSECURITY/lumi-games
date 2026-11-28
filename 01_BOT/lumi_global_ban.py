"""Durable, ordered moderation replication; no reasons or moderator IDs leave SQLite."""
from contextlib import closing
import asyncio, hashlib, hmac, json, logging, random, time, urllib.request, urllib.parse


def init_sync(db):
    db.execute('CREATE TABLE IF NOT EXISTS ban_sync (seq INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, expires INTEGER NOT NULL)')
    for event, expr, uid in [('INSERT', "COALESCE(CAST(strftime('%s',NEW.expires_at) AS INTEGER),-1)", 'NEW.user_id'), ('UPDATE', "COALESCE(CAST(strftime('%s',NEW.expires_at) AS INTEGER),-1)", 'NEW.user_id'), ('DELETE','0','OLD.user_id')]:
        db.execute(f'CREATE TRIGGER IF NOT EXISTS ban_sync_{event.lower()} AFTER {event} ON account_suspensions BEGIN INSERT INTO ban_sync(uid,expires) VALUES({uid},{expr}); END')
    db.execute('CREATE TABLE IF NOT EXISTS ban_sync_state (id INTEGER PRIMARY KEY)')
    if db.execute('INSERT OR IGNORE INTO ban_sync_state VALUES(1)').rowcount:
        db.execute("INSERT INTO ban_sync(uid,expires) SELECT user_id,COALESCE(CAST(strftime('%s',expires_at) AS INTEGER),-1) FROM account_suspensions")


def send(url, secret, seq, uid, expires):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password: raise ValueError('invalid sync URL')
    ts=int(time.time()); uid=str(uid)
    body=dict(seq=seq,uid=uid,expires=expires,ts=ts)
    sig=hmac.new(secret.encode(),f'lumi:ban:v1:{seq}:{uid}:{expires}:{ts}'.encode(),hashlib.sha256).hexdigest()
    endpoint=urllib.parse.urlunsplit((p.scheme,p.netloc,'/api/internal/ban-sync','',''))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    req=urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Lumi-Ban-Signature':sig},method='POST')
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=8) as response:
        raw=response.read(1025)
        if len(raw)>1024 or response.status!=200: raise RuntimeError('sync rejected')
        result=json.loads(raw)
        if not isinstance(result,dict) or result.get('accepted') is not True: raise RuntimeError('sync rejected')


def drain(connect,url,secret):
    with closing(connect()) as db, db:
        rows=db.execute('SELECT seq,uid,expires FROM ban_sync ORDER BY seq LIMIT 50').fetchall()
    for seq,uid,expires in rows:
        send(url,secret,seq,uid,expires)
        with closing(connect()) as db, db: db.execute('DELETE FROM ban_sync WHERE seq=?',(seq,))


def retry_delay(failures):
    """Bounded exponential backoff with jitter; normal polling stays at 10s."""
    if failures <= 0:
        return 10
    ceiling=min(120, 10 * 2 ** min(failures, 4))
    return random.uniform(ceiling / 2, ceiling)


async def sync_loop(connect,url,secret):
    failures=0
    while True:
        try:
            await asyncio.to_thread(drain,connect,url,secret)
        except Exception as exc:
            failures=min(failures+1, 4)
            logging.getLogger(__name__).warning('Ban sync delayed: %s',type(exc).__name__)
        else:
            failures=0
        await asyncio.sleep(retry_delay(failures))
