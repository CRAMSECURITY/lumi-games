"""Офлайн-тесты приватности тизера; не требуют токена Telegram."""
import ast
from pathlib import Path
import sqlite3
from io import BytesIO
from PIL import Image

source=Path(__file__).with_name('bot.py').read_text('utf-8')
tree=ast.parse(source)
selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'teaser_is_safe','make_anonymous_teaser'}]
assert len(selected)==2
ns={}
exec(compile(ast.Module(body=selected,type_ignores=[]),'teaser','exec'),ns)
ns['is_discoverable']=lambda db, uid: not bool(db.execute('SELECT 1 FROM moderation_holds WHERE user_id=?',(uid,)).fetchone())
db=sqlite3.connect(':memory:')
db.executescript('''CREATE TABLE profiles(user_id INTEGER PRIMARY KEY);
CREATE TABLE reactions(from_user INTEGER,to_user INTEGER,liked INTEGER);
CREATE TABLE blocks(user_id INTEGER,blocked_id INTEGER);
CREATE TABLE moderation_holds(user_id INTEGER);''')
db.executemany('INSERT INTO profiles VALUES (?)',[(1,),(2,)])
assert not ns['teaser_is_safe'](db,1,2)
db.execute('INSERT INTO reactions VALUES(1,2,1)')
assert ns['teaser_is_safe'](db,1,2)
db.execute('INSERT INTO reactions VALUES(2,1,1)')
assert not ns['teaser_is_safe'](db,1,2), 'mutual match must remain free'
db.execute('DELETE FROM reactions WHERE from_user=2')
db.execute('INSERT INTO blocks VALUES(2,1)')
assert not ns['teaser_is_safe'](db,1,2), 'blocked identities must not tease'
db.execute('DELETE FROM blocks')
db.execute('INSERT INTO moderation_holds VALUES(1)')
assert not ns['teaser_is_safe'](db,1,2), 'moderation hold must hide identity'
db.execute('DELETE FROM moderation_holds')
image=Image.new('RGB',(800,1000),'pink')
f=BytesIO(); image.save(f,format='JPEG')
result=ns['make_anonymous_teaser'](f.getvalue())
with Image.open(BytesIO(result)) as im:
    assert im.size == (420,520)
    assert not im.getexif(), 'EXIF must be removed'
assert len(result)>0
db.close()
assert 'F.data == "teaser:reveal"' in source
assert 'asyncio.create_task(send_like_teaser(callback.bot,user_id,target_id))' in source
assert 'asyncio.create_task(send_like_teaser(message.bot, user_id, target_id))' in source
print('OK: 8 privacy/visibility/image checks')
