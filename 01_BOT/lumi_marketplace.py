"""Offline marketplace prototype. Demo credits only; never Telegram Stars or EXP.
Caller supplies authenticated user ID. Use a separate disposable SQLite database.
"""
from types import MappingProxyType
import sqlite3

CATALOG = MappingProxyType({'aurora_frame': 100, 'obsidian_glow': 150, 'violet_badge': 75})


def init_demo(db):
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS demo_wallet(uid INTEGER PRIMARY KEY, balance INTEGER NOT NULL CHECK(balance>=0))')
        db.execute('CREATE TABLE IF NOT EXISTS demo_orders(uid INTEGER NOT NULL, request_id TEXT NOT NULL, sku TEXT NOT NULL, price INTEGER NOT NULL, PRIMARY KEY(uid,request_id), UNIQUE(uid,sku))')


def purchase(db, uid, sku, request_id):
    """Atomic demo purchase; price is resolved exclusively from the catalog."""
    if type(uid) is not int or not 0 < uid < 2**63 or type(sku) is not str or sku not in CATALOG:
        raise ValueError('invalid purchase')
    if type(request_id) is not str or not 1 <= len(request_id) <= 64 or not request_id.isascii() or not request_id.isalnum():
        raise ValueError('invalid request ID')
    if db.in_transaction:
        raise ValueError('purchase requires its own transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        previous = db.execute('SELECT sku,price FROM demo_orders WHERE uid=? AND request_id=?',(uid,request_id)).fetchone()
        if previous:
            if previous[0] != sku:
                raise ValueError('request conflict')
            result = 'replayed'
        elif db.execute('SELECT 1 FROM demo_orders WHERE uid=? AND sku=?',(uid,sku)).fetchone():
            result = 'owned'
        elif db.execute('UPDATE demo_wallet SET balance=balance-? WHERE uid=? AND balance>=?',(CATALOG[sku],uid,CATALOG[sku])).rowcount != 1:
            result = 'insufficient'
        else:
            db.execute('INSERT INTO demo_orders VALUES(?,?,?,?)',(uid,request_id,sku,CATALOG[sku]))
            result = 'purchased'
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
