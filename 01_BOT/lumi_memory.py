"""Bounded per-user sliding windows, confined to a single asyncio event loop."""
from collections import OrderedDict, deque


class UserWindows:
    def __init__(self, capacity, period):
        if capacity < 1 or period <= 0:
            raise ValueError('invalid window limits')
        self.capacity = capacity
        self.period = period
        self._entries = OrderedDict()

    def acquire(self, uid, now):
        # Entries are ordered by last touch. Never evict an active window
        # to admit a new user: doing so would reset rate limits under load.
        while self._entries:
            first = next(iter(self._entries))
            touched, _ = self._entries[first]
            if now - touched <= self.period:
                break
            self._entries.popitem(last=False)
        entry = self._entries.get(uid)
        if entry is None:
            if len(self._entries) >= self.capacity:
                return None
            queue = deque()
        else:
            _, queue = entry
        while queue and now - queue[0] > self.period:
            queue.popleft()
        self._entries[uid] = (now, queue)
        self._entries.move_to_end(uid)
        return queue

    def discard(self, uid):
        self._entries.pop(uid, None)

    def __len__(self):
        return len(self._entries)
