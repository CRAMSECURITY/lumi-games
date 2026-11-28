"""Offline checks: python test_ops_3_8_offline.py (no tokens needed)."""
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
from datetime import datetime, timezone
from lumi_operations import init_ops, toggle_notify, can_notify, record_metric, flag_due, alert_due, analytics

with sqlite3.connect(':memory:') as db:
    init_ops(db); init_ops(db)
    assert can_notify(db,1,'likes')
    toggle_notify(db,1,'likes'); assert not can_notify(db,1,'likes')
    toggle_notify(db,1,'likes'); assert can_notify(db,1,'likes')
    toggle_notify(db,1,'quiet')
    assert not can_notify(db,1,'likes',datetime(2026,11,24,23,tzinfo=timezone.utc))
    assert can_notify(db,1,'matches',datetime(2026,11,24,12,tzinfo=timezone.utc))
    assert flag_due(db,1) and not flag_due(db,1)
    assert alert_due(db,'slow') and not alert_due(db,'slow')
    record_metric(db,'update',5);record_metric(db,'update',3)
    assert db.execute("SELECT count FROM lumi_ops_daily WHERE metric='update'").fetchone()[0]==8
    for ddl in [
      'CREATE TABLE profiles(user_id INT)',
      'CREATE TABLE privacy_settings(user_id INT,discoverable INT)',
      'CREATE TABLE reactions(from_user INT,to_user INT,liked INT)',
      'CREATE TABLE browse_daily(user_id INT,day TEXT,views INT)',
      'CREATE TABLE support_tickets(id INT,status TEXT)',
      'CREATE TABLE verification_requests(user_id INT,status TEXT)',
      'CREATE TABLE premium_subscriptions(user_id INT,expires_at INT)',
      'CREATE TABLE premium_payments(charge_id TEXT,refunded INT)',
    ]:db.execute(ddl)
    db.execute('INSERT INTO profiles VALUES(1),(2),(3)')
    db.execute('INSERT INTO reactions VALUES(1,2,1),(2,1,1),(3,1,1)')
    assert analytics(db)['matches']==1
    assert analytics(db)['profiles']==3
    assert analytics(db)['likes']==3
print('LUMI 3.8 ops tests: PASS')
