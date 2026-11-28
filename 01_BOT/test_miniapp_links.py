import ast, asyncio, re, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

class MiniAppLinks(unittest.TestCase):
    def test_allowed_routes(self):
        source=Path(__file__).with_name('bot.py')
        fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='start')
        fn.decorator_list=[]
        names={'home':'lumi_navigation','gift':'daily4_command','invite':'referral_command','profile':'my_profile','safety':'safety4_command','notifications':'notifications_menu'}
        ns={name:AsyncMock() for name in names.values()}
        ns.update(re=re,Message=object,FSMContext=object,close_active_chat=Mock(),mobile_home=AsyncMock())
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns)
        state=object()
        for route,name in names.items():
            with self.subTest(route=route):
                m=SimpleNamespace(text='/start lumi_'+route,from_user=SimpleNamespace(id=1))
                asyncio.run(ns['start'](m,state))
                ns[name].assert_awaited_once_with(*((m,state) if route=='home' else (m,)))
        ns['close_active_chat'].assert_not_called()
if __name__=='__main__': unittest.main()
