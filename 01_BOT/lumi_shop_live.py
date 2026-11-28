"""Opt-in demo shop; no monetary value. Caller supplies Telegram identity."""
from lumi_marketplace import CATALOG
from lumi_economy import eligible_for_reward
import secrets


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS lumi_shop_wallet(uid INTEGER PRIMARY KEY, balance INTEGER NOT NULL CHECK(balance>=0), epoch TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS lumi_shop_items(uid INTEGER NOT NULL, sku TEXT NOT NULL, price INTEGER NOT NULL, PRIMARY KEY(uid,sku))')
    db.execute('''CREATE TRIGGER IF NOT EXISTS lumi_shop_delete AFTER DELETE ON profiles BEGIN
        DELETE FROM lumi_shop_items WHERE uid=OLD.user_id;
        DELETE FROM lumi_shop_wallet WHERE uid=OLD.user_id;
    END''')

    db.execute('CREATE TABLE IF NOT EXISTS lumi_shop_equipped(uid INTEGER PRIMARY KEY, sku TEXT NOT NULL)')
    db.execute('CREATE TRIGGER IF NOT EXISTS lumi_shop_equip_delete AFTER DELETE ON profiles BEGIN DELETE FROM lumi_shop_equipped WHERE uid=OLD.user_id; END')


LABELS = {'aurora_frame': '✧ Aurora Frame', 'obsidian_glow': '✦ Obsidian Glow', 'violet_badge': '💜 Violet Badge'}


def equipped(db, uid):
    row = db.execute('SELECT e.sku FROM lumi_shop_equipped e JOIN lumi_shop_items i ON i.uid=e.uid AND i.sku=e.sku WHERE e.uid=?', (uid,)).fetchone()
    return row[0] if row and row[0] in LABELS and eligible_for_reward(db, uid) else None


def equip(db, uid, sku, epoch):
    if type(uid) is not int or not 0 < uid < 2**63 or type(epoch) is not str or (sku is not None and (type(sku) is not str or sku not in CATALOG)):
        raise ValueError('invalid selection')
    if db.in_transaction:
        raise ValueError('transaction already active')
    db.execute('BEGIN IMMEDIATE')
    try:
        wallet = db.execute('SELECT epoch FROM lumi_shop_wallet WHERE uid=?', (uid,)).fetchone()
        if not wallet or wallet[0] != epoch or not eligible_for_reward(db, uid):
            db.rollback()
            return False
        if sku is None:
            db.execute('DELETE FROM lumi_shop_equipped WHERE uid=?', (uid,))
        elif db.execute('SELECT 1 FROM lumi_shop_items WHERE uid=? AND sku=?', (uid, sku)).fetchone():
            db.execute('INSERT INTO lumi_shop_equipped VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET sku=excluded.sku', (uid, sku))
        else:
            db.rollback()
            return False
        db.commit()
        return True
    except BaseException:
        db.rollback()
        raise


def act(db, uid, sku=None, epoch=None):
    if type(uid) is not int or not 0 < uid < 2**63:
        raise ValueError('invalid identity')
    if sku is not None and (sku not in CATALOG or type(epoch) is not str):
        raise ValueError('invalid item')
    if db.in_transaction:
        raise ValueError('transaction already active')
    db.execute('BEGIN IMMEDIATE')
    try:
        if not eligible_for_reward(db, uid):
            db.rollback()
            return None
        if sku is None:
            db.execute('INSERT OR IGNORE INTO lumi_shop_wallet VALUES(?,300,?)', (uid,secrets.token_hex(8)))
        wallet=db.execute('SELECT balance,epoch FROM lumi_shop_wallet WHERE uid=?',(uid,)).fetchone()
        if wallet is None or (sku is not None and wallet[1]!=epoch):
            db.rollback()
            return None
        status='catalog'
        if sku is not None:
            if db.execute('SELECT 1 FROM lumi_shop_items WHERE uid=? AND sku=?',(uid,sku)).fetchone():
                status='owned'
            elif db.execute('UPDATE lumi_shop_wallet SET balance=balance-? WHERE uid=? AND balance>=?',(CATALOG[sku],uid,CATALOG[sku])).rowcount!=1:
                status='insufficient'
            else:
                db.execute('INSERT INTO lumi_shop_items VALUES(?,?,?)',(uid,sku,CATALOG[sku]))
                status='purchased'
        balance, current=db.execute('SELECT balance,epoch FROM lumi_shop_wallet WHERE uid=?',(uid,)).fetchone()
        owned=[r[0] for r in db.execute('SELECT sku FROM lumi_shop_items WHERE uid=? ORDER BY sku',(uid,))]
        db.commit()
        return balance,current,owned,status
    except BaseException:
        db.rollback()
        raise
