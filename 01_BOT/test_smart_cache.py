import unittest
from concurrent.futures import ThreadPoolExecutor
from lumi_cache import RecentMap, RecentSet, byte_cache

class CacheTests(unittest.TestCase):
    def test_map_bound(self):
        m=RecentMap(3)
        for i in range(10000): m[i]=i
        self.assertEqual(list(m), [9997,9998,9999])
    def test_setdefault_refresh(self):
        m=RecentMap(2); m[1]=1; m[2]=2
        self.assertEqual(m.setdefault(1,9),1)
        m[3]=3
        self.assertNotIn(2,m)
    def test_set_bound(self):
        s=RecentSet(2)
        for i in range(1000): s.add(i)
        self.assertEqual(len(s),2); self.assertNotIn(0,s)
        s.discard(999); self.assertNotIn(999,s); s.clear(); self.assertEqual(len(s),0)
    def test_byte_budget(self):
        calls=[]
        @byte_cache(10,10)
        def f(n): calls.append(n); return bytes(n)
        f(6); f(5); f(5); f(6)
        self.assertEqual(calls,[6,5,6])
        f(11); f(11); self.assertEqual(calls[-2:],[11,11])
    def test_concurrent(self):
        @byte_cache(100,5)
        def f(n): return bytes(n)
        with ThreadPoolExecutor(8) as pool:
            values=list(pool.map(f,range(200)))
        self.assertEqual([len(x) for x in values],list(range(200)))
