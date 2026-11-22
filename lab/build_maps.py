"""Compile raw lab maps into the compact runtime map (maps/maps.bin.gz).

Runs inside the lab image (it imports the pristine sqlglot for the class
hierarchy):
  python /repo/lab/build_maps.py OUT raw1.pkl [raw2.pkl ...]

Everything here comes from the clean pinned tree: per-test coverage, file
access, argument types, the statement index and import-time references. No
labels are read.
"""

import ast
import gzip
import hashlib
import importlib
import inspect
import json
import os
import pickle
import pkgutil
import sys
from array import array

SRC = "/opt/sqlglot"
sys.path.insert(0, SRC)


def load_raw(paths, tests):
    """Union every run into per-test (lines, types, files)."""
    ids = [t["id"] for t in tests]
    idx = {tid: i for i, tid in enumerate(ids)}
    lines = [dict() for _ in ids]  # file -> set(line)
    types = [set() for _ in ids]
    files = [set() for _ in ids]
    unknown = set()

    def add(i, snap):
        if not snap:
            return
        for f, ls in snap["lines"].items():
            lines[i].setdefault(f, set()).update(ls)
        types[i].update(snap["types"])
        files[i].update(snap["files"])

    for p in paths:
        raw = pickle.load(open(p, "rb"))
        # class fixtures: setup of the first test and teardown of the last test of each class
        order = [k for k in raw if not k.startswith("__")]
        by_class = {}
        for k in order:
            base = k.split("[", 1)[0]
            by_class.setdefault(base.rsplit("::", 1)[0], []).append(base)
        for k, phases in raw.items():
            if k.startswith("__"):
                continue
            base = k.split("[", 1)[0]
            if base not in idx:
                unknown.add(base)
                continue
            for ph in ("setup", "call", "teardown"):
                add(idx[base], phases.get(ph))
        for cls, members in by_class.items():
            first, last = members[0], members[-1]
            extra = [raw[first].get("setup"), raw[last].get("teardown")]
            for m in members:
                if m in idx:
                    for snap in extra:
                        add(idx[m], snap)
    return lines, types, files, unknown


class Interner:
    def __init__(self):
        self.sets = []
        self.index = {}

    def add(self, bits: int) -> int:
        j = self.index.get(bits)
        if j is None:
            j = len(self.sets)
            self.index[bits] = j
            self.sets.append(bits)
        return j


def statement_index(path):
    """Per file: every statement with its span, depth, parent, kind and name."""
    src = open(path, "rb").read()
    tree = ast.parse(src)
    rows = []  # (start, end, depth, parent, kind, name, body_start, header_end)

    def visit(node, depth, parent):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                start = child.lineno
                decos = getattr(child, "decorator_list", None)
                if decos:
                    start = min([start] + [d.lineno for d in decos])
                kind = "stmt"
                name = ""
                body_start = 0
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "def"
                    name = child.name
                    body_start = child.body[0].lineno
                elif isinstance(child, ast.ClassDef):
                    kind = "class"
                    name = child.name
                    body_start = child.body[0].lineno
                me = len(rows)
                rows.append([start, child.end_lineno, depth, parent, kind, name, body_start])
                visit(child, depth + 1, me)
            elif isinstance(child, (ast.excepthandler, ast.match_case)) or not isinstance(child, ast.expr):
                visit(child, depth, parent)

    visit(tree, 0, -1)
    return rows


def resolve_imports(tree, modname, is_pkg):
    """name -> (module, attr or None) for the module's top-level imports."""
    table = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    table[a.asname] = (a.name, None)
                else:
                    table[a.name.split(".")[0]] = (a.name.split(".")[0], None)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                pkg = modname if is_pkg else modname.rsplit(".", 1)[0]
                for _ in range(node.level - 1):
                    pkg = pkg.rsplit(".", 1)[0]
                base = pkg + ("." + base if base else "")
            for a in node.names:
                table[a.asname or a.name] = (base, a.name)
    return table


def import_time_units(path, modname, is_pkg):
    """Import-time statements (outside any function) with what they define and reference.

    owner: ("module", name) for module-level, ("class", qualname) for class bodies.
    refs: set of (module, name) after resolving imports; local names resolve to
    this module. Attribute chains like mod.X or Cls.ATTR add (module, X) / class refs.
    """
    tree = ast.parse(open(path, "rb").read())
    imports = resolve_imports(tree, modname, is_pkg)
    units = []

    def ref_of(node):
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                tgt = imports.get(n.id)
                if tgt is None:
                    out.add((modname, n.id))
                elif tgt[1] is None:
                    out.add((tgt[0], "*"))
                else:
                    out.add((tgt[0], tgt[1]))
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                tgt = imports.get(n.value.id)
                if tgt is not None and tgt[1] is None:
                    out.add((tgt[0], n.attr))
                    # "import a.b" style: also the submodule
                    out.add((tgt[0] + "." + n.attr, "*"))
                elif tgt is not None:
                    out.add((tgt[0] + "." + tgt[1], n.attr))
        return out

    def defined(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return {node.name}
        names = set()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
            return names
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
        return names

    def walk_body(body, owner_kind, qual):
        for st in body:
            if isinstance(st, ast.ClassDef):
                q = f"{qual}.{st.name}" if qual else st.name
                header = ast.Module(body=[], type_ignores=[])
                refs = set()
                for b in st.bases + [k.value for k in st.keywords] + st.decorator_list:
                    refs |= ref_of(b)
                units.append({"owner": (owner_kind, qual) if owner_kind == "class" else ("module", st.name),
                              "cls": q, "defines": {st.name}, "refs": refs, "lines": (st.lineno, st.end_lineno)})
                walk_body(st.body, "class", q)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                refs = set()
                for d in st.decorator_list:
                    refs |= ref_of(d)
                for d in st.args.defaults + [x for x in st.args.kw_defaults if x is not None]:
                    refs |= ref_of(d)
                if refs:
                    units.append({"owner": (owner_kind, qual if owner_kind == "class" else st.name),
                                  "cls": qual if owner_kind == "class" else None,
                                  "defines": {st.name}, "refs": refs, "lines": (st.lineno, st.end_lineno)})
            else:
                units.append({"owner": (owner_kind, qual if owner_kind == "class" else None),
                              "cls": qual if owner_kind == "class" else None,
                              "defines": defined(st), "refs": ref_of(st), "lines": (st.lineno, st.end_lineno)})

    walk_body(tree.body, "module", "")
    return units


def class_hierarchy():
    """(module, qualname) -> sorted list of all subclasses (module, qualname), transitively."""
    import sqlglot  # noqa: F401

    for info in pkgutil.walk_packages([os.path.join(SRC, "sqlglot")], prefix="sqlglot."):
        if info.name.endswith("__main__"):
            continue
        try:
            importlib.import_module(info.name)
        except Exception as e:  # noqa: BLE001
            print("import fail", info.name, e, file=sys.stderr)
    seen = {}

    def key(c):
        return (c.__module__, c.__qualname__)

    allc = set()
    stack = [object]
    while stack:
        c = stack.pop()
        try:
            subs = type.__subclasses__(c) if c is not type else []
        except TypeError:
            subs = []
        for s in subs:
            if s not in allc:
                allc.add(s)
                stack.append(s)
    sq = [c for c in allc if (getattr(c, "__module__", "") or "").startswith("sqlglot")]
    out = {}
    for c in sq:
        subs = set()
        st = [c]
        while st:
            x = st.pop()
            for s in type.__subclasses__(x) if x is not type else []:
                if s not in subs:
                    subs.add(s)
                    st.append(s)
        out[key(c)] = sorted(key(s) for s in subs if (s.__module__ or "").startswith("sqlglot"))
        # bases outside sqlglot are irrelevant; within sqlglot, record file for each class
    files = {}
    for c in sq:
        try:
            files[key(c)] = os.path.relpath(inspect.getfile(c), SRC)
        except TypeError:
            pass
    return out, files


def main():
    out_path = sys.argv[1]
    raws = sys.argv[2:]
    tests = json.load(open("/repo/sample/tests.json"))["tests"]
    lines, types, files, unknown = load_raw(raws, tests)
    if unknown:
        print("unknown test ids in raw maps:", sorted(unknown)[:10], file=sys.stderr)
    n = len(tests)
    intern = Interner()

    # line map: file -> (lines array, set index array)
    per_file = {}
    for i in range(n):
        bit = 1 << i
        for f, ls in lines[i].items():
            d = per_file.setdefault(f, {})
            for ln in ls:
                d[ln] = d.get(ln, 0) | bit
    line_map = {}
    for f, d in per_file.items():
        ks = sorted(d)
        line_map[f] = (array("I", ks).tobytes(), array("I", [intern.add(d[k]) for k in ks]).tobytes())

    type_map = {}
    for i in range(n):
        for t in types[i]:
            type_map[t] = type_map.get(t, 0) | (1 << i)
    type_map = {k: intern.add(v) for k, v in type_map.items()}

    open_map, dir_map, proc = {}, {}, 0
    for i in range(n):
        for kind, p in files[i]:
            if kind == "open":
                if "__pycache__" in p:
                    continue
                open_map[p] = open_map.get(p, 0) | (1 << i)
            elif kind in ("os.listdir", "os.scandir"):
                dir_map[p.rstrip("/")] = dir_map.get(p.rstrip("/"), 0) | (1 << i)
            else:
                proc |= 1 << i
    open_map = {k: intern.add(v) for k, v in open_map.items()}
    dir_map = {k: intern.add(v) for k, v in dir_map.items()}

    stmts, units, shas = {}, {}, {}
    for top in ("sqlglot", "tests", "sqlglotc"):
        for dp, dn, fn in os.walk(os.path.join(SRC, top)):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fn:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, SRC)
                shas[rel] = hashlib.sha256(open(full, "rb").read()).hexdigest()[:16]
                if f.endswith(".py"):
                    stmts[rel] = statement_index(full)
                    mod = rel[:-3].replace("/", ".")
                    is_pkg = f == "__init__.py"
                    if is_pkg:
                        mod = mod[: -len(".__init__")]
                    units[rel] = (mod, import_time_units(full, mod, is_pkg))
    hier, class_files = class_hierarchy()

    # name index: lines that mention a module-level global or a class name
    import io
    import tokenize

    wanted = set()
    for rel, (mod, us) in units.items():
        if rel.startswith("sqlglot/"):
            for u in us:
                if u["owner"][0] == "module":
                    wanted |= set(u["defines"])
    for (m_, q_) in hier:
        wanted.add(q_.rsplit(".", 1)[-1])
    names = {}
    for rel in stmts:
        try:
            toks = tokenize.tokenize(io.BytesIO(open(os.path.join(SRC, rel), "rb").read()).readline)
            per = {}
            for tok in toks:
                if tok.type == tokenize.NAME and tok.string in wanted:
                    per.setdefault(tok.string, set()).add(tok.start[0])
                elif tok.type == tokenize.STRING:
                    for w in set(tok.string.strip("'\"").split()) & wanted:
                        per.setdefault(w, set()).add(tok.start[0])
        except (tokenize.TokenError, SyntaxError):
            continue
        for nm, ls in per.items():
            names.setdefault(nm, []).append((rel, array("I", sorted(ls)).tobytes()))

    proc_idx = intern.add(proc)
    data = {
        "version": 1,
        "tests": [t["id"] for t in tests],
        "test_ms": [round(t["seconds"] * 1000) for t in tests],
        "sets": [s.to_bytes((n + 7) // 8, "little") for s in intern.sets],
        "lines": line_map,
        "types": type_map,
        "open": open_map,
        "dirs": dir_map,
        "subprocess": proc_idx,
        "stmts": stmts,
        "units": units,
        "subclasses": hier,
        "class_files": class_files,
        "names": names,
        "sha": shas,
    }
    blob = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    with gzip.open(out_path, "wb", compresslevel=9) as f:
        f.write(blob)
    print(f"maps: {len(intern.sets)} sets, {len(line_map)} files, {len(type_map)} types, "
          f"raw {len(blob) / 1e6:.1f} MB, gz {os.path.getsize(out_path) / 1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
