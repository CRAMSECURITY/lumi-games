"""Read-only aggregate analytics for LUMI 015.0; no external tracking."""
import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

def report(db, today):
    day=today.isoformat()
    week=(today-dt.timedelta(days=6)).isoformat()
    yesterday=(today-dt.timedelta(days=1)).isoformat()
    end=int(dt.datetime.combine(today+dt.timedelta(days=1),dt.time(),dt.timezone.utc).timestamp())
    start=end-7*86400
    def scalar(sql,args=()):
        return db.execute(sql,args).fetchone()[0]
    db.execute("BEGIN")
    try:
        daily=scalar("SELECT count(DISTINCT user_id) FROM browse_daily WHERE day=? AND views>0",(day,))
        weekly=scalar("SELECT count(DISTINCT user_id) FROM browse_daily WHERE day BETWEEN ? AND ? AND views>0",(week,day))
        prev=scalar("SELECT count(DISTINCT user_id) FROM browse_daily WHERE day=? AND views>0",(yesterday,))
        returning=scalar("""SELECT count(*) FROM browse_daily a JOIN browse_daily b USING(user_id)
            WHERE a.day=? AND b.day=? AND a.views>0 AND b.views>0""",(yesterday,day))
        orders,buyers,stars=db.execute("""SELECT count(*),count(DISTINCT user_id),coalesce(sum(stars),0)
            FROM premium_payments WHERE refunded=0 AND paid_at>=? AND paid_at<?""",(start,end)).fetchone()
        return dict(as_of_utc=day,profiles=scalar("SELECT count(*) FROM profiles"),
            daily_browsers=daily,seven_day_browsers=weekly,yesterday_browsers=prev,
            returning_yesterday_browsers=returning,
            next_day_browse_return_rate=returning/prev if prev else None,
            seven_day_nonrefunded_orders=orders,seven_day_distinct_buyers=buyers,
            seven_day_nonrefunded_stars=stars,
            caveat="Browse activity only; current UTC day may be incomplete. No MAU or signup cohort retention. Stars are not USD revenue.")
    finally:
        db.rollback()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("database",type=Path)
    args=parser.parse_args()
    try:
        path=args.database.resolve(strict=True)
        with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            print(json.dumps(report(db,dt.datetime.now(dt.timezone.utc).date()),indent=2))
    except (OSError,sqlite3.Error):
        parser.exit(1,"Analytics unavailable: check database and schema.\n")
if __name__=="__main__":
    main()
