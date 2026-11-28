"""Local operational check; never prints user IDs, secrets, or raw HTTP bodies."""
from contextlib import closing
import argparse,json,sqlite3,time,urllib.request,urllib.parse
from pathlib import Path

def check(dbpath,url=None):
    p=Path(dbpath).resolve();result={}
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5)) as db, db:
        result['sqlite_ok']=db.execute('PRAGMA quick_check').fetchall()==[('ok',)]
        result['pending_bans']=db.execute('SELECT COUNT(*) FROM ban_sync').fetchone()[0]
    if url:
        u=urllib.parse.urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('HTTPS required')
        start=time.monotonic()
        with urllib.request.urlopen(urllib.parse.urlunsplit((u.scheme,u.netloc,'/api/health','','')),timeout=10) as r:
            data=json.loads(r.read(4096));result['api_ok']=data.get('ok') is True and data.get('ban_sync_configured') is True
        result['api_ms']=round((time.monotonic()-start)*1000)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('database');p.add_argument('--url');a=p.parse_args()
    try:
        r=check(a.database,a.url);print(json.dumps(r));raise SystemExit(0 if r['sqlite_ok'] and not r['pending_bans'] and r.get('api_ok',True) else 1)
    except Exception as e:print(json.dumps({'error':type(e).__name__}));raise SystemExit(2)
