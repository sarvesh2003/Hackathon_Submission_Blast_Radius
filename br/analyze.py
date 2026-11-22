"""Change analysis: from a patch to the set of tests it can reach.

For every changed Python region we find the smallest enclosing statement of the
pristine file (offline statement index) and prove "no-op" by comparing the ASTs
of just that statement's old and new text. A real change is classified by where
it sits:

- body:     inside a function body -> tests that executed those lines;
- defhead:  a def's decorators or signature -> callers, plus the container;
- class:    a class body or header -> tests that used the class or a subclass,
            plus the import-time closure;
- module:   module-level code -> tests that ran any code in the module, plus the
            import-time closure of the names it defines.

Anything we cannot analyse sets `everything`.
"""

from __future__ import annotations

import ast
import os

from . import patchlib

CONFIG_NAMES = {"conftest.py", "pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini"}


class FileChange:
    __slots__ = ("path", "kind", "regions", "noop", "reach", "swap", "t2", "notes", "new", "old")

    def __init__(self, path):
        self.path = path
        self.kind = ""  # py | fixture | other | config
        self.regions = []  # (category, row) for real changes
        self.noop = False
        self.reach = 0
        self.swap = []  # [(class qualname or "", function name)] for T1 code swaps
        self.t2 = False  # needs a fresh import (class/module-level or structure change)
        self.notes = []
        self.new = None
        self.old = None


class Analysis:
    __slots__ = ("files", "everything", "reach", "notes")

    def __init__(self):
        self.files: list[FileChange] = []
        self.everything = False
        self.reach = 0
        self.notes: list[str] = []

    @property
    def noop(self):
        return not self.everything and all(f.noop for f in self.files)


# ---------------------------------------------------------------- line mapping


def _unchanged_map(hunks):
    """old line -> new line for context lines inside hunks; plus per-hunk offsets."""
    ctx = {}
    for h in hunks:
        o = h.old_start if h.old_len else h.old_start + 1
        n = h.new_start if h.new_len else h.new_start + 1
        # walk the hunk's sides in step: context lines appear in both lists
        oi = ni = 0
        removed = set(h.old_lines)
        added = set(h.new_lines)
        while oi < len(h.old) or ni < len(h.new):
            if oi < len(h.old) and o in removed:
                o += 1
                oi += 1
            elif ni < len(h.new) and n in added:
                n += 1
                ni += 1
            else:
                ctx[o] = n
                o += 1
                n += 1
                oi += 1
                ni += 1
    return ctx


class LineMapper:
    def __init__(self, hunks, n_old):
        self.hunks = hunks
        self.ctx = _unchanged_map(hunks)
        self.changed = set()
        for h in hunks:
            self.changed.update(h.old_lines)
        self.n_old = n_old

    def unchanged(self, line):
        return line not in self.changed

    def map(self, line):
        """New line number of an unchanged old line."""
        if line in self.ctx:
            return self.ctx[line]
        off = 0
        for h in self.hunks:
            end = h.old_start + h.old_len - 1 if h.old_len else h.old_start
            if end < line:
                off += h.new_len - h.old_len
        return line + off

    def new_span(self, start, end):
        # start
        s = start
        while s >= 1 and s in self.changed:
            s -= 1
        ns = 1 if s < 1 else (self.map(s) + (1 if s != start else 0))
        e = end
        while e <= self.n_old and e in self.changed:
            e += 1
        if e > self.n_old:
            ne = None  # to end of file
        else:
            ne = self.map(e) - (1 if e != end else 0)
        return ns, ne


# ---------------------------------------------------------------- slicing / AST


def _indent(line: bytes) -> int:
    return len(line) - len(line.lstrip(b" \t"))


def _parse_slice(lines: list[bytes]):
    """Parse a statement slice; returns a list of AST nodes or raises SyntaxError."""
    first = None
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith(b"#"):
            first = ln
            break
    if first is None:
        return []
    k = _indent(first)
    text = b"".join(lines)
    if k == 0:
        return ast.parse(text).body
    tree = ast.parse(b"if 1:\n" + text)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.If):
        raise SyntaxError("slice escapes its block")
    for n in ast.walk(tree):
        if hasattr(n, "lineno") and n.lineno is not None:
            n.lineno -= 1
            if getattr(n, "end_lineno", None) is not None:
                n.end_lineno -= 1
    return tree.body[0].body


def _dump(nodes):
    return "\n".join(ast.dump(n) for n in nodes)


class _BlankLambdas(ast.NodeTransformer):
    def visit_Lambda(self, node):
        return ast.Lambda(args=node.args, body=ast.Constant(value=None))


def _lambda_diff(old_nodes, new_nodes):
    """If old and new differ only inside lambda bodies, return the differing
    old lambdas as (lineno, end_lineno) relative to the slice; else None."""
    import copy

    sk_old = [_BlankLambdas().visit(copy.deepcopy(n)) for n in old_nodes]
    sk_new = [_BlankLambdas().visit(copy.deepcopy(n)) for n in new_nodes]
    if _dump(sk_old) != _dump(sk_new):
        return None
    lo = [n for t in old_nodes for n in ast.walk(t) if isinstance(n, ast.Lambda)]
    ln = [n for t in new_nodes for n in ast.walk(t) if isinstance(n, ast.Lambda)]
    if len(lo) != len(ln):
        return None
    out = []
    for a, b in zip(lo, ln):
        if ast.dump(a) != ast.dump(b):
            # a lambda nested inside another changed lambda is covered by the outer one
            out.append((a.lineno, a.end_lineno))
    return out


# ---------------------------------------------------------------- statement lookup


def _smallest(rows, lo, hi):
    best = -1
    best_key = None
    for i, r in enumerate(rows):
        if r[0] <= lo and r[1] >= hi:
            key = (r[2], -(r[1] - r[0]))
            if best_key is None or key > best_key:
                best, best_key = i, key
    return best


def _ancestors(rows, i):
    out = []
    p = rows[i][3]
    while p != -1:
        out.append(p)
        p = rows[p][3]
    return out


def _qualname(rows, i):
    names = []
    j = i
    while j != -1:
        r = rows[j]
        if r[4] in ("def", "class"):
            names.append(r[5])
        j = r[3]
    return ".".join(reversed(names))


def module_of(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    return mod


# ---------------------------------------------------------------- reach


class Reach:
    def __init__(self, maps):
        self.m = maps

    def class_level(self, path, qual, seen):
        m = self.m
        mod = module_of(path)
        key = (mod, qual)
        if key in seen:
            return 0
        seen.add(key)
        out = m.type_reach(key)
        # tests that ran the class's own code
        span = self._class_span(path, qual)
        if span:
            out |= m.lines(path, span[0], span[1])
        # class name mentioned elsewhere (direct class-attribute access)
        names = {qual.rsplit(".", 1)[-1]}
        for sub in m.subclasses.get(key, ()):
            names.add(sub[1].rsplit(".", 1)[-1])
        for nm in names:
            out |= self.name_reach(nm)
        # import-time consumers of this class and of its subclasses
        out |= self.closure({(mod, qual.split(".")[0])} | {(s[0], s[1].split(".")[0]) for s in m.subclasses.get(key, ())}, seen)
        if not m.subclasses.get(key) and m.types.get(key) is None and not span:
            out |= self.module_level(path, {qual.split(".")[0]}, seen)
        return out

    def _class_span(self, path, qual):
        rows = self.m.stmts.get(path, [])
        for i, r in enumerate(rows):
            if r[4] == "class" and _qualname(rows, i) == qual:
                return (r[0], r[1])
        return None

    def name_reach(self, name):
        out = 0
        for path, lines in self.m.names.get(name, ()):
            from array import array

            a = array("I")
            a.frombytes(lines)
            for ln in a:
                out |= self.m.lines(path, ln, ln)
        return out

    def module_level(self, path, names, seen):
        m = self.m
        mod = module_of(path)
        key = (mod, "<module>", tuple(sorted(names)))
        if key in seen:
            return 0
        seen.add(key)
        out = m.file_any(path)
        for nm in names:
            out |= self.name_reach(nm)
        out |= self.closure({(mod, n) for n in names} | {(mod, "*")}, seen)
        return out

    def closure(self, symbols, seen):
        m = self.m
        idx = m.units_by_ref()
        out = 0
        for sym in symbols:
            for path, mod, u in idx.get(sym, ()):
                if mod == sym[0] and path.endswith(".py") and u["owner"][0] == "module" and sym[1] in u["defines"]:
                    continue  # the defining statement itself
                if u.get("cls"):
                    out |= self.class_level(path, u["cls"], seen)
                else:
                    out |= self.module_level(path, set(u["defines"]), seen)
        return out


# ---------------------------------------------------------------- analysis


def analyze(patch: bytes, read, maps) -> Analysis:
    """`read(path)` returns pristine bytes or None."""
    an = Analysis()
    try:
        fps = patchlib.parse(patch)
        result = patchlib.apply_to_tree(fps, read)
    except (patchlib.PatchError, UnicodeDecodeError, ValueError) as e:
        an.everything = True
        an.notes.append(f"patch: {e}")
        return an
    reach = Reach(maps)
    by_path = {}
    for fp in fps:
        for p in {fp.old_path, fp.new_path} - {None}:
            by_path.setdefault(p, []).append(fp)
    for path, new in result.items():
        fc = FileChange(path)
        an.files.append(fc)
        old = read(path)
        fc.old, fc.new = old, new
        base = os.path.basename(path)
        if old == new:
            fc.noop = True
            continue
        if base in CONFIG_NAMES or (path.startswith("tests/") and base == "__init__.py"):
            fc.kind = "config"
            an.everything = True
            an.notes.append(f"config file {path}")
            continue
        fps_here = [fp for fp in by_path.get(path, []) if fp.hunks]
        if path.endswith(".py") and (path.startswith("sqlglot/") or path.startswith("tests/")):
            fc.kind = "py"
            _analyze_py(fc, old, new, fps_here, maps, reach, an)
        elif path.startswith("tests/fixtures/") or path.startswith("tests/"):
            fc.kind = "fixture"
            fc.reach = maps.opened(path) | maps.listed(path)
            if old is None or new is None:
                fc.reach |= maps.listed(path)
        else:
            fc.kind = "other"
            fc.reach = maps.opened(path) | maps.listed(path)
            if path.startswith("sqlglot/") or path.startswith("sqlglotc/"):
                fc.reach |= maps.listed(path)
        an.reach |= fc.reach
    return an


def _analyze_py(fc, old, new, fps, maps, reach, an):
    path = fc.path
    if old is None or new is None:
        # new or deleted module
        fc.t2 = True
        if old is None:
            fc.reach = maps.listed(path)
            fc.notes.append("new module")
        else:
            fc.reach = maps.file_any(path) | maps.listed(path) | maps.opened(path)
            an.everything = True  # importers break; be safe
            fc.notes.append("deleted module")
        an.reach |= fc.reach
        return
    rows = maps.stmts.get(path)
    hunks = [h for fp in fps for h in fp.hunks]
    if rows is None or not hunks:
        fc.t2 = True
        fc.reach = maps.file_any(path) | maps.opened(path)
        an.everything = True
        fc.notes.append("no statement index")
        return
    # encoding cookie edits: fall back to full-file comparison
    touches_head = any(min(h.old_lines + [h.ins_after[0] + 1 if h.ins_after else 10**9]) <= 2 for h in hunks)
    old_lines = patchlib.split_keep(old)
    new_lines = patchlib.split_keep(new)
    mapper = LineMapper(hunks, len(old_lines))

    regions = []
    for h in hunks:
        for ln in h.old_lines:
            regions.append((ln, ln))
        for a in sorted(set(h.ins_after)):
            regions.append((max(a, 1), a + 1))
    targets = {}
    for lo, hi in regions:
        i = _smallest(rows, lo, hi)
        targets.setdefault(i, []).append((lo, hi))

    full_cmp = None

    def full_equal():
        nonlocal full_cmp
        if full_cmp is None:
            try:
                full_cmp = ast.dump(ast.parse(old)) == ast.dump(ast.parse(new))
            except SyntaxError:
                full_cmp = False
        return full_cmp

    real = []
    for i, regs in targets.items():
        if i == -1:
            # module-level gap (between top-level statements)
            if full_equal():
                continue
            real.append((i, regs, None))
            continue
        r = rows[i]
        ns, ne = mapper.new_span(r[0], r[1])
        old_slice = old_lines[r[0] - 1 : r[1]]
        new_slice = new_lines[ns - 1 : (ne if ne is not None else len(new_lines))]
        same = None
        lambdas = None
        if not touches_head:
            try:
                on, nn = _parse_slice(old_slice), _parse_slice(new_slice)
                same = _dump(on) == _dump(nn)
                if not same:
                    lam = _lambda_diff(on, nn)
                    if lam:
                        lambdas = [(r[0] - 1 + a, r[0] - 1 + b) for a, b in lam]
            except (SyntaxError, ValueError, UnicodeDecodeError, RecursionError):
                same = None
        if same is None:
            same = full_equal()
        if not same:
            real.append((i, regs, lambdas))

    if not real:
        fc.noop = True
        # tests that read this source file as text still see the change
        fc.reach = maps.opened(path)
        an.reach |= fc.reach
        return

    seen = set()
    out = maps.opened(path)
    mod = module_of(path)
    for i, regs, lambdas in real:
        if i == -1:
            fc.t2 = True
            out |= reach.module_level(path, _module_names_near(maps, path, regs), seen)
            fc.regions.append(("module", None))
            continue
        r = rows[i]
        anc = _ancestors(rows, i)
        cat = None
        if r[4] == "def":
            body_start = r[6]
            in_body = all(lo >= body_start - 1 and (lo != hi or lo >= body_start) for lo, hi in regs)
            cat = "body" if in_body else "defhead"
        elif r[4] == "class":
            cat = "class"
        else:
            # nearest def/class ancestor decides
            cat = "module"
            for a in anc:
                if rows[a][4] == "def":
                    cat = "body"
                    break
                if rows[a][4] == "class":
                    cat = "class"
                    break
        if lambdas and cat in ("class", "module"):
            # only lambda bodies changed: a function-body change of those lambdas
            cat = "lambda"
        fc.regions.append((cat, i))
        if cat == "lambda":
            for a, b in lambdas:
                out |= maps.lines(path, a, b)
                fc.swap.append(("<lambda>", a, b))
        elif cat == "body":
            out |= maps.lines(path, r[0], r[1])
            # outermost function directly in a class or module: the T1 swap unit
            chain = [i] + anc
            top = None
            for j in chain:
                if rows[j][4] == "def":
                    top = j
            if top is not None:
                p = rows[top][3]
                fc.swap.append((_qualname(rows, p) if p != -1 else "", rows[top][5], top))
            else:
                fc.t2 = True
        elif cat == "defhead":
            fc.t2 = True
            out |= maps.lines(path, r[0], r[1])
            p = r[3]
            if p != -1 and rows[p][4] == "class":
                out |= reach.class_level(path, _qualname(rows, p), seen)
            else:
                out |= reach.module_level(path, {r[5]}, seen)
        elif cat == "class":
            fc.t2 = True
            k = i if r[4] == "class" else next(a for a in anc if rows[a][4] == "class")
            out |= reach.class_level(path, _qualname(rows, k), seen)
        else:
            fc.t2 = True
            top = i
            for a in anc:
                top = a
            out |= reach.module_level(path, _defines_of(maps, path, rows[top]), seen)
    fc.reach = out
    an.reach |= out


def _defines_of(maps, path, row):
    mod, units = maps.units.get(path, (None, []))
    names = set()
    for u in units:
        lo, hi = u["lines"]
        if lo <= row[0] <= hi or row[0] <= lo <= row[1]:
            names |= set(u["defines"])
    return names


def _module_names_near(maps, path, regs):
    mod, units = maps.units.get(path, (None, []))
    names = set()
    for lo, hi in regs:
        for u in units:
            a, b = u["lines"]
            if a - 1 <= hi and b + 1 >= lo:
                names |= set(u["defines"])
    return names
