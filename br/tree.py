"""A writable view of the pristine sqlglot checkout under /tmp.

Files are symlinks to the read-only checkout (pristine .pyc stay valid because
stat() follows the link), except test .py files, which are real copies so that
Path(__file__).resolve() stays inside the view. A patch is applied by writing
real files over the links (and dropping the module's cached .pyc link), and
undone afterwards. Commits are probed one at a time, so one view is enough.
"""

from __future__ import annotations

import os
import shutil

TOPS = ("sqlglot", "tests", "sqlglotc")


class Tree:
    def __init__(self, src: str, dst: str):
        self.src = src.rstrip("/")
        self.dst = dst.rstrip("/")
        self._undo: list[tuple[str, str | None, str | None]] = []  # (path, link target or None, kind)

    def build(self):
        src, dst = self.src, self.dst
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            full = os.path.join(src, name)
            if name in TOPS or not os.path.isfile(full):
                continue
            os.symlink(full, os.path.join(dst, name))
        for top in TOPS:
            base = os.path.join(src, top)
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                rel = os.path.relpath(dirpath, src)
                out = os.path.join(dst, rel)
                os.mkdir(out)
                real_copy = top == "tests" and "fixtures" not in rel.split(os.sep) and "__pycache__" not in rel
                for f in filenames:
                    s = os.path.join(dirpath, f)
                    d = os.path.join(out, f)
                    if real_copy and f.endswith(".py"):
                        shutil.copy2(s, d)
                    else:
                        os.symlink(s, d)

    def _pyc_entries(self, path):
        d, base = os.path.split(path)
        if not base.endswith(".py"):
            return []
        cache = os.path.join(self.dst, d, "__pycache__")
        try:
            names = os.listdir(cache)
        except FileNotFoundError:
            return []
        stem = base[:-3] + "."
        return [os.path.join(cache, n) for n in names if n.startswith(stem)]

    def write(self, files: dict[str, bytes | None]):
        """Apply {relpath: bytes or None (delete)}; remember how to undo it."""
        for rel, data in files.items():
            full = os.path.join(self.dst, rel)
            for pyc in self._pyc_entries(rel):
                self._remember(pyc)
                os.remove(pyc)
            existed = os.path.lexists(full)
            self._remember(full)
            if existed:
                os.remove(full)
            if data is not None:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as fh:
                    fh.write(data)

    def _remember(self, full):
        if os.path.islink(full):
            self._undo.append((full, os.readlink(full), "link"))
        elif os.path.isfile(full):
            # a real copy of a pristine file: restore it with its mtime so the .pyc stays valid
            self._undo.append((full, self.src + full[len(self.dst):], "file"))
        else:
            self._undo.append((full, None, "absent"))

    def restore(self):
        for full, val, kind in reversed(self._undo):
            if os.path.lexists(full):
                os.remove(full)
            if kind == "link":
                os.symlink(val, full)
            elif kind == "file":
                shutil.copy2(val, full)
        self._undo.clear()
