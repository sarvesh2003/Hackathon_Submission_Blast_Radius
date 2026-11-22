"""Load the compact runtime map (maps/maps.bin.gz) and answer reach queries.

Bitsets are Python ints over the map's test order; `numbers()` converts them
to tests.json numbers. Built offline from the clean pinned tree only.
"""

from __future__ import annotations

import gzip
import os
import pickle
from array import array
from bisect import bisect_left, bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(os.path.dirname(HERE), "maps", "maps.bin.gz")


class Maps:
    def __init__(self, path: str = DEFAULT):
        with gzip.open(path, "rb") as f:
            d = pickle.load(f)
        self.d = d
        self.tests: list[str] = d["tests"]
        self.n = len(self.tests)
        self._raw_sets = d["sets"]
        self._sets: dict[int, int] = {}
        self._lines = {}
        self.ALL = (1 << self.n) - 1
        self.stmts = d["stmts"]
        self.units = d["units"]
        self.subclasses = d["subclasses"]
        self.types = d["types"]
        self.open = d["open"]
        self.dirs = d["dirs"]
        self.sha = d["sha"]
        self.names = d.get("names", {})
        self.class_files = d.get("class_files", {})
        self.proc = self.set(d["subprocess"])
        self._units_by_ref = None

    def set(self, i: int) -> int:
        s = self._sets.get(i)
        if s is None:
            s = int.from_bytes(self._raw_sets[i], "little")
            self._sets[i] = s
        return s

    def _file_lines(self, path):
        x = self._lines.get(path)
        if x is None:
            raw = self.d["lines"].get(path)
            if raw is None:
                x = (array("I"), array("I"))
            else:
                a, b = array("I"), array("I")
                a.frombytes(raw[0])
                b.frombytes(raw[1])
                x = (a, b)
            self._lines[path] = x
        return x

    def lines(self, path: str, lo: int, hi: int) -> int:
        """Tests that executed any line in [lo, hi] of `path` during a test."""
        ls, ss = self._file_lines(path)
        i, j = bisect_left(ls, lo), bisect_right(ls, hi)
        out = 0
        seen = set()
        for k in range(i, j):
            s = ss[k]
            if s not in seen:
                seen.add(s)
                out |= self.set(s)
        return out

    def file_any(self, path: str) -> int:
        return self.lines(path, 0, 1 << 31)

    def type_reach(self, key) -> int:
        """Tests that passed an instance (or the class itself) of `key` or a subclass to sqlglot code."""
        out = 0
        for k in [key] + list(self.subclasses.get(tuple(key), ())):
            i = self.types.get(tuple(k))
            if i is not None:
                out |= self.set(i)
        return out

    def opened(self, path: str) -> int:
        i = self.open.get(path)
        return 0 if i is None else self.set(i)

    def listed(self, path: str) -> int:
        """Tests that listed `path`'s directory or any parent directory."""
        out = 0
        d = os.path.dirname(path)
        while True:
            i = self.dirs.get(d)
            if i is not None:
                out |= self.set(i)
            if not d:
                break
            d = os.path.dirname(d)
        return out

    def units_by_ref(self):
        if self._units_by_ref is None:
            idx = {}
            for path, (mod, units) in self.units.items():
                for u in units:
                    for r in u["refs"]:
                        idx.setdefault(r, []).append((path, mod, u))
            self._units_by_ref = idx
        return self._units_by_ref
