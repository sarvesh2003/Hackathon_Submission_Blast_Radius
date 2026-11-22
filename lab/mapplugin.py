"""pytest plugin (lab only): per-test execution maps from the clean tree.

For each test and phase (setup / call / teardown) it records:
- lines executed in files under the tree root (sys.monitoring LINE, each
  location reported once per phase, then re-armed with restart_events);
- the sqlglot types seen as arguments of sqlglot functions (PY_START), which
  lets a class-level edit be mapped to the tests that use that class;
- files opened or listed, and subprocesses started (audit hook).
Work sent to process pools runs in-process (br.fakepool), so it is attributed
to the test that submitted it. Output: a pickle at $MAP_OUT.
"""

import os
import pickle
import sys

sys.path.insert(0, "/repo")
from br import fakepool  # noqa: E402

fakepool.install()

ROOT = os.environ.get("MAP_ROOT", "/tmp/w").rstrip("/") + "/"
OUT = os.environ.get("MAP_OUT", "/tmp/map.pkl")
TRACK_TYPES = os.environ.get("MAP_TYPES", "1") == "1"

mon = sys.monitoring
TOOL = 3
mon.use_tool_id(TOOL, "brmap")

_lines = set()  # (code, line)
_types = set()
_files = set()
_in_root = {}
_getframe = sys._getframe
DISABLE = mon.DISABLE


def _is_root(code):
    r = _in_root.get(code)
    if r is None:
        r = code.co_filename.startswith(ROOT)
        _in_root[code] = r
    return r


def on_line(code, line):
    if _is_root(code):
        _lines.add((code.co_filename, line))
    return DISABLE


_sqlglot_prefix = ROOT + "sqlglot/"
_is_sqlglot = {}


def on_start(code, offset):
    s = _is_sqlglot.get(code)
    if s is None:
        s = code.co_filename.startswith(_sqlglot_prefix)
        _is_sqlglot[code] = s
    if not s:
        return DISABLE
    n = code.co_argcount + code.co_kwonlyargcount
    if n:
        f = _getframe(1)
        loc = f.f_locals
        add = _types.add
        for name in code.co_varnames[:n]:
            v = loc.get(name)
            if v is not None:
                t = v if isinstance(v, type) else type(v)
                add(t)
    return None


def audit(event, args):
    if event == "open":
        p = args[0]
        if isinstance(p, (str, bytes, os.PathLike)):
            _files.add(("open", os.fsdecode(p)))
    elif event in ("os.listdir", "os.scandir"):
        p = args[0]
        if isinstance(p, (str, bytes, os.PathLike)):
            _files.add((event, os.fsdecode(p)))
    elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.system"):
        _files.add((event, repr(args[:2])[:300]))


sys.addaudithook(audit)
mon.register_callback(TOOL, mon.events.LINE, on_line)
mon.set_events(TOOL, mon.events.LINE | (mon.events.PY_START if TRACK_TYPES else 0))
if TRACK_TYPES:
    mon.register_callback(TOOL, mon.events.PY_START, on_start)

RESULTS = {}
_current = None


def _snapshot():
    global _lines, _types, _files
    lines = {}
    for fn, ln in _lines:
        lines.setdefault(fn[len(ROOT):], set()).add(ln)
    types = set()
    for t in _types:
        m = getattr(t, "__module__", "") or ""
        if m.startswith("sqlglot"):
            types.add((m, getattr(t, "__qualname__", t.__name__)))
    files = set()
    for kind, p in _files:
        if kind in ("open", "os.listdir", "os.scandir"):
            ap = os.path.abspath(p) if not os.path.isabs(p) else os.path.normpath(p)
            if ap.startswith(ROOT):
                files.add((kind, ap[len(ROOT):]))
            elif ap.startswith("/opt/sqlglot/"):
                files.add((kind, ap[len("/opt/sqlglot/"):]))
        else:
            files.add((kind, p))
    _lines = set()
    _types = set()
    _files = set()
    return {"lines": lines, "types": types, "files": files}


def _phase_start():
    _snapshot()  # discard anything recorded outside the phase
    mon.restart_events()


import pytest  # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_collection(session):
    yield
    RESULTS["__collect__"] = {"call": _snapshot()}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    _phase_start()
    yield
    RESULTS.setdefault(item.nodeid, {})["setup"] = _snapshot()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _phase_start()
    yield
    RESULTS.setdefault(item.nodeid, {})["call"] = _snapshot()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    _phase_start()
    yield
    RESULTS.setdefault(item.nodeid, {})["teardown"] = _snapshot()


def pytest_sessionfinish(session, exitstatus):
    RESULTS["__session_end__"] = {"call": _snapshot()}
    with open(OUT, "wb") as f:
        pickle.dump(RESULTS, f, protocol=pickle.HIGHEST_PROTOCOL)
