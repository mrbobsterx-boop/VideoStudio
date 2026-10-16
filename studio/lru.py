"""Кэш с ограничением по объёму (общий для kit и gfx)."""
from collections import OrderedDict


class _LRU(OrderedDict):
    """Кэш с ограничением по объёму (байты numpy-массивов) или по числу элементов."""

    def __init__(self, max_bytes=None, max_items=None):
        super().__init__()
        self.max_bytes, self.max_items, self.bytes = max_bytes, max_items, 0

    def get(self, k, d=None):
        if k in self:
            self.move_to_end(k)
            return self[k]
        return d

    def put(self, k, v):
        if k in self:
            self.bytes -= getattr(self[k], 'nbytes', 0)
        self[k] = v
        self.move_to_end(k)
        self.bytes += getattr(v, 'nbytes', 0)
        while len(self) > 1 and ((self.max_bytes and self.bytes > self.max_bytes) or
                                 (self.max_items and len(self) > self.max_items)):
            _, old = self.popitem(last=False)
            self.bytes -= getattr(old, 'nbytes', 0)
        return v
