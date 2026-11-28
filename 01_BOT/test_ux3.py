import ast, unittest, asyncio, sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
TREE=ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
def load(names, ns):
    nodes=[n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'bot.py','exec'),ns)
    return ns
class UX3(unittest.TestCase):
    def test_intervals(self):
        f=load({'reminder_stage'}, {})['reminder_stage']; d=86400
        self.assertEqual(f(0,0,0,d-1),0); self.assertEqual(f(0,0,0,d),1)
        self.assertEqual(f(0,1,d,3*d),2); self.assertEqual(f(0,2,3*d,7*d),3)
        self.assertEqual(f(0,3,7*d,10*d),0); self.assertEqual(f(0,1,3*d-1,3*d),0)
    def test_opt_in_default(self):
        db=sqlite3.connect(':memory:'); self.addCleanup(db.close)
        load({'init_return_reminders'}, {})['init_return_reminders'](db)
        db.execute('INSERT INTO lumi_return_activity(user_id,last_seen) VALUES(1,10)')
        self.assertEqual(db.execute('SELECT enabled,stage FROM lumi_return_activity').fetchone(),(0,0))
    def test_only_marked_messages_removed(self):
        bot=SimpleNamespace(delete_message=AsyncMock()); chat=SimpleNamespace(id=5)
        m=SimpleNamespace(chat=chat,bot=bot,answer=AsyncMock(side_effect=[SimpleNamespace(chat=chat,bot=bot,message_id=11),SimpleNamespace(chat=chat,bot=bot,message_id=13)]))
        ns=load({'clean_answer','clear_clean_ui'}, {'_CLEAN_UI':{},'TelegramAPIError':RuntimeError})
        async def run():
            await ns['clean_answer'](m,'menu'); await ns['clean_answer'](m,'next'); await ns['clear_clean_ui'](m)
        asyncio.run(run()); self.assertEqual([c.args for c in bot.delete_message.await_args_list],[(5,11),(5,13)])
    def test_reminder_filters_and_real_teaser(self):
        fn=next(n for n in TREE.body if getattr(n,'name',None)=='return_reminder_pass')
        self.assertIn('claim_reminder',ast.unparse(fn)); self.assertIn('reminder_users',ast.unparse(fn))
        claim=next(n for n in TREE.body if getattr(n,'name',None)=='claim_reminder')
        scan=next(n for n in TREE.body if getattr(n,'name',None)=='reminder_users')
        self.assertIn('eligible_candidates(uid)',ast.unparse(claim)); self.assertIn('a.enabled=1',ast.unparse(scan))
        fn=next(n for n in TREE.body if getattr(n,'name',None)=='send_like_teaser')
        self.assertIn('teaser_is_safe',ast.unparse(fn)); self.assertNotIn('bot.download',ast.unparse(fn)); self.assertNotIn('send_photo',ast.unparse(fn)); self.assertNotIn('LUMI_TEASER_PHRASES',ast.unparse(fn))
