import unittest
from lumi_memory import UserWindows

class WindowTests(unittest.TestCase):
    def test_capacity_preserves_active_limits(self):
        w=UserWindows(2,20)
        q=w.acquire(1,0); q.extend([0]*25)
        w.acquire(2,1).append(1)
        for uid in range(3,10003):
            self.assertIsNone(w.acquire(uid,2))
        self.assertEqual(len(w),2)
        self.assertEqual(len(w.acquire(1,2)),25)

    def test_expiry_reclaims_capacity(self):
        w=UserWindows(2,20)
        w.acquire(1,0).append(0)
        w.acquire(2,10).append(10)
        self.assertIsNone(w.acquire(3,20))
        self.assertIsNotNone(w.acquire(3,21))
        self.assertEqual(len(w),2)
        self.assertEqual(list(w.acquire(2,21)),[10])

    def test_prune_old_events_without_resetting_active_user(self):
        w=UserWindows(2,20)
        w.acquire(1,0).append(0)
        w.acquire(1,10).append(10)
        self.assertEqual(list(w.acquire(1,21)),[10])

    def test_discard(self):
        w=UserWindows(1,600)
        w.acquire(1,0).append(0)
        w.discard(1)
        self.assertIsNotNone(w.acquire(2,1))

if __name__=='__main__': unittest.main()
