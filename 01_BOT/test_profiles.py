import ast, re, unittest, asyncio
from pathlib import Path
from html import escape, unescape
from types import SimpleNamespace
from contextlib import nullcontext
p=Path(__file__).parent/'bot.py'
tree=ast.parse(p.read_text(encoding='utf-8'))
class DB:
    def execute(self,*a): return self
    def fetchone(self): return (1,)
class APIError(Exception): pass
class Message:
    def __init__(self,fail=False): self.calls=[]; self.fail=fail
    async def answer_video(self,*a,**kw):
        if self.fail: raise APIError()
        self.calls.append(('video',kw))
    async def answer_photo(self,*a,**kw):
        if self.fail: raise APIError()
        self.calls.append(('photo',kw))
    async def answer(self,*a,**kw): self.calls.append(('text',kw))
viewer=('Друг',25,'Берлин','Люблю музыку и книги',None)
ns=dict(shop_enabled=lambda:False,re=re,html_escape=escape,connect_db=lambda:nullcontext(DB()),nickname_of=lambda _: 'Ник',premium_active=lambda *_:True,founder_badge=lambda *_:'\n🏅 <b>Первопроходец LUMI · №1</b>',has_referral_frame=lambda *_:True,profile_of=lambda _:viewer,InlineKeyboardButton=SimpleNamespace,InlineKeyboardMarkup=SimpleNamespace,KeyboardButton=SimpleNamespace,ReplyKeyboardMarkup=SimpleNamespace,TelegramAPIError=APIError,logger=SimpleNamespace(exception=lambda *_:None),menu=None)
names={'ui_safe','quick_caption','profile_shared_context','profile_caption','cosmetic_caption','interest_words','send_profile','browse_keyboard','browse_reply_keyboard'}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names],type_ignores=[]),str(p),'exec'),ns)
class Tests(unittest.TestCase):
    def test_city(self): self.assertIn('Один город',ns['profile_shared_context'](('А',25,' БЕРЛИН ','',None),viewer))
    def test_words(self): self.assertIn('общие слова',ns['profile_shared_context'](('А',25,'Париж','музыку',None),viewer))
    def test_no_match(self): self.assertEqual('',ns['profile_shared_context'](('А',25,'Париж','спорт',None),viewer))
    def test_missing_viewer(self): self.assertEqual('',ns['profile_shared_context'](viewer,None))
    def test_placeholder_city(self): self.assertEqual('',ns['profile_shared_context'](('А',25,'—','',None),('Б',25,'—','',None)))
    def test_html_and_badges(self):
        c=ns['profile_caption'](('<b>&',25,'Берлин','<a> музыку',None),user_id=1,viewer_id=2)
        for expected in ('&lt;b&gt;&amp;','&lt;a&gt;','Фото проверено','Premium','Первопроходец','Сердце LUMI'): self.assertIn(expected,c)
    def test_compact_caption(self):
        self.assertEqual(ns['profile_caption'](('Аня',24,'Москва','Люблю\nмузыку',None)), '<b>Аня, 24, Москва</b> — Люблю музыку')
    def test_own(self): self.assertNotIn('Один город',ns['profile_caption'](viewer,own=True,user_id=1,viewer_id=2))
    def test_empty(self): self.assertIn('Пока без описания',ns['quick_caption'](('А',25,'Б','',None)))
    def test_caption_limit(self):
        c=ns['profile_caption'](('😀'*100,25,'😀'*100,'😀'*600,None),user_id=1,viewer_id=2)
        self.assertLessEqual(len(unescape(re.sub(r'<[^>]+>','',c))),1024)
    def test_buttons(self):
        rows=ns['browse_keyboard'](42).inline_keyboard
        self.assertEqual([b.callback_data for b in rows[0]],['like:42','skip:42'])
        rows=ns['browse_keyboard'](42,True,True).inline_keyboard
        self.assertTrue({'block:42','report:42','listen:42','super:42','later:42','letter:42'}.issubset({b.callback_data for row in rows for b in row}))
    def test_bottom_bar(self):
        kb=ns['browse_reply_keyboard']()
        self.assertEqual([[b.text for b in row] for row in kb.keyboard], [['❤️ Нравится', '👎 Пропустить']])
    def test_video(self):
        m=Message(); asyncio.run(ns['send_profile'](m,viewer,user_id=1,viewer_id=2)); self.assertEqual(m.calls[0][0],'video'); self.assertTrue(m.calls[0][1]['protect_content'])
    def test_fallback(self):
        m=Message(True); asyncio.run(ns['send_profile'](m,('А',25,'Берлин','музыку','photo'),user_id=1,viewer_id=2)); self.assertEqual(m.calls[0][0],'text'); self.assertTrue(m.calls[0][1]['protect_content'])
if __name__=='__main__': unittest.main(verbosity=2)
