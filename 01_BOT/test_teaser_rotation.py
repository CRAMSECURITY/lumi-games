"""Current notification contract: no photos, cooldown, opt-out, no identity."""
import ast, asyncio, sqlite3, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
func=next(n for n in ast.parse(Path(__file__).with_name('bot.py').read_text('utf-8')).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='send_like_teaser')
class FakeBot:
    def __init__(self): self.sent=[]
    async def send_message(self,uid,body,**kwargs): self.sent.append((uid,body,kwargs))
class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cooldown_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            @contextmanager
            def connect_db():
                db=sqlite3.connect(Path(tmp)/'test.db')
                try:
                    with db:
                        yield db
                finally:
                    db.close()
            with connect_db() as db: db.execute('CREATE TABLE lumi_like_teasers(user_id INTEGER PRIMARY KEY,last_sent INTEGER)')
            scope=dict(connect_db=connect_db,teaser_is_safe=lambda db,a,b:True,can_notify=lambda db,u,k:True,TEASER_COOLDOWN_SECONDS=86400,time=time,InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace,Bot=FakeBot)
            exec(compile(ast.Module(body=[func],type_ignores=[]),'<teaser>','exec'),scope)
            bot=FakeBot(); send=scope['send_like_teaser']
            await asyncio.gather(send(bot,111111,2),send(bot,333333,2))
            self.assertEqual(len(bot.sent),1)
            self.assertTrue(bot.sent[0][2]['protect_content'])
            self.assertNotIn('111111',str(bot.sent)); self.assertNotIn('333333',str(bot.sent))
            scope['can_notify']=lambda *a:False
            await send(bot,111111,4); self.assertEqual(len(bot.sent),1)
            scope['can_notify']=lambda *a:True;scope['teaser_is_safe']=lambda *a:False
            await send(bot,111111,4); self.assertEqual(len(bot.sent),1)
            scope['teaser_is_safe']=lambda *a:True
            with connect_db() as db: db.execute('UPDATE lumi_like_teasers SET last_sent=0')
            await send(bot,111111,2); self.assertEqual(len(bot.sent),2)

if __name__ == "__main__":
    unittest.main()
