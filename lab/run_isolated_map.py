"""Isolated per-test maps (lab only): every test runs in its own fork of a
process that has imported all test modules (pytest's post-collection state),
so a test whose in-order run hit a cache filled by an earlier test still shows
the code it depends on.

  python /repo/lab/run_isolated_map.py OUT.pkl [--seed N] [--shard I/N]

Runs the tests with unittest (TestSuite of one class with the one test, so
setUpClass runs too), with mapplugin's recorders active in the child.
"""

import argparse
import importlib
import json
import os
import pickle
import shutil
import sys
import time
import unittest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seed", default="2")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--tests", default="/repo/sample/tests.json")
    a = ap.parse_args()
    if os.environ.get("PYTHONHASHSEED") != str(a.seed):
        os.environ["PYTHONHASHSEED"] = str(a.seed)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    work = "/tmp/w"
    if not os.path.isdir(work):
        shutil.copytree("/opt/sqlglot", work, symlinks=True)
    os.chdir(work)
    sys.path[:0] = [work, "/repo/lab", "/repo"]
    os.environ.update(SKIP_INTEGRATION="0", MAP_ROOT=work, MAP_TYPES="1")
    import mapplugin as mp  # installs fakepool + monitoring

    tests = json.load(open(a.tests))["tests"]
    i, n = map(int, a.shard.split("/"))
    mine = [t for k, t in enumerate(tests) if k % n == i]
    mods = sorted({t["file"][:-3].replace("/", ".") for t in tests})
    for m in mods:
        importlib.import_module(m)
    mp._snapshot()

    results = {}
    t0 = time.time()
    for t in mine:
        rfd, wfd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(rfd)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            mp._phase_start()
            ok = None
            try:
                mod_name, rest = t["id"].split("::", 1)
                cls_name, meth = rest.split("::")
                mod = importlib.import_module(mod_name[:-3].replace("/", "."))
                cls = getattr(mod, cls_name)
                suite = unittest.TestSuite([cls(meth)])
                res = unittest.TestResult()
                suite.run(res)
                ok = res.wasSuccessful()
            except BaseException as e:  # noqa: BLE001
                ok = repr(e)
            snap = mp._snapshot()
            snap["ok"] = ok
            data = pickle.dumps(snap, protocol=pickle.HIGHEST_PROTOCOL)
            with os.fdopen(wfd, "wb") as w:
                w.write(data)
            os._exit(0)
        os.close(wfd)
        with os.fdopen(rfd, "rb") as r:
            data = r.read()
        os.waitpid(pid, 0)
        results[t["id"]] = {"call": pickle.loads(data)} if data else {"call": None}
    with open(a.out, "wb") as f:
        pickle.dump(results, f, protocol=pickle.HIGHEST_PROTOCOL)
    bad = [k for k, v in results.items() if not v["call"] or v["call"].get("ok") is not True]
    print(f"isolated map: {len(results)} tests in {time.time() - t0:.0f}s; not ok: {len(bad)} {bad[:5]}", file=sys.__stderr__)


if __name__ == "__main__":
    main()
