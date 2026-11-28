"""Bounded disposable UI caches; never use for authorization or rate limits."""
from collections import OrderedDict
from functools import wraps
from threading import RLock

class RecentMap(OrderedDict):
    def __init__(self, capacity):
        super().__init__()
        self.capacity = capacity
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.capacity:
            self.popitem(last=False)
    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        self.move_to_end(key)
        return self[key]

class RecentSet:
    def __init__(self, capacity):
        self.items = RecentMap(capacity)
    def add(self, value): self.items[value] = None
    def discard(self, value): self.items.pop(value, None)
    def clear(self): self.items.clear()
    def __contains__(self, value): return value in self.items
    def __len__(self): return len(self.items)


def byte_cache(max_bytes, max_entries):
    """Thread-safe byte-weighted LRU; rendering runs outside the lock."""
    def decorate(fn):
        entries = OrderedDict()
        lock = RLock()
        total = 0
        @wraps(fn)
        def wrapped(*args):
            nonlocal total
            with lock:
                if args in entries:
                    entries.move_to_end(args)
                    return entries[args]
            value = fn(*args)
            if len(value) > max_bytes:
                return value
            with lock:
                if args in entries:
                    entries.move_to_end(args)
                    return entries[args]
                entries[args] = value
                total += len(value)
                while total > max_bytes or len(entries) > max_entries:
                    _, old = entries.popitem(last=False)
                    total -= len(old)
            return value
        return wrapped
    return decorate
