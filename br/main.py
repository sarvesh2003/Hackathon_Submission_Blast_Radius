"""Blast Radius selector: one JSON line per commit on stdout, logs on stderr.

v1 (static): list the tests the maps say a change can reach; print [] for
proven no-ops and for changes no test executes; list everything when anything
cannot be analysed.
"""

from __future__ import annotations

import json
import os
import sys
import time

from . import sched
from .analyze import analyze
from .maps import Maps

DATA = os.environ.get("BR_DATA", "/data")
TREE = os.environ.get("BR_TREE", "/opt/sqlglot")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def cgroup_cpu():
    try:
        for line in open("/sys/fs/cgroup/cpu.stat"):
            if line.startswith("usage_usec"):
                return int(line.split()[1]) / 1e6
    except OSError:
        pass
    return None


def main():
    t0 = time.time()
    out = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)  # anything else that writes to fd 1 lands on stderr
    sys.stdout = sys.stderr
    tests = json.load(open(os.path.join(DATA, "tests.json")))["tests"]
    nums = [t["number"] for t in tests]
    ms = [0] * (max(nums) + 1)
    for t in tests:
        ms[t["number"]] = round(t["seconds"] * 1000)
    all_nums = sorted(nums)
    num_of_id = {t["id"]: t["number"] for t in tests}

    maps = Maps()
    to_num = [num_of_id.get(tid) for tid in maps.tests]
    mapped = {x for x in to_num if x is not None}
    unmapped = [x for x in all_nums if x not in mapped]
    if unmapped:
        log(f"warning: {len(unmapped)} tests not in the map; always listed")

    cache = {}

    def read(path):
        if path not in cache:
            f = os.path.join(TREE, path)
            try:
                with open(f, "rb") as fh:
                    cache[path] = fh.read()
            except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                cache[path] = None
        return cache[path]

    commits = sorted(p for p in os.listdir(os.path.join(DATA, "commits")) if p.endswith(".patch"))
    total = 0
    for name in commits:
        cid = name[: -len(".patch")]
        try:
            patch = open(os.path.join(DATA, "commits", name), "rb").read()
            an = analyze(patch, read, maps)
            if an.everything:
                sel = all_nums
                why = "everything: " + "; ".join(an.notes)[:120]
            elif an.reach == 0:
                sel = []
                why = "noop" if an.noop else "unreached"
            else:
                r = an.reach
                sel = [to_num[i] for i in range(maps.n) if r >> i & 1 and to_num[i] is not None] + unmapped
                why = ",".join(f"{f.path}:{'/'.join(sorted({c for c, _ in f.regions})) or ('noop' if f.noop else f.kind)}" for f in an.files)
        except Exception as e:  # noqa: BLE001 - never crash: list everything
            sel = all_nums
            why = f"error {e!r}"
        cost, workers = sched.schedule(sel, ms) if sel else (0, [])
        total += cost
        out.write(json.dumps({"commit": cid, "workers": workers}, separators=(",", ":")) + "\n")
        log(f"{cid}: {len(sel)} tests, cost {cost / 1000:.3f}s  [{why}]")
    out.flush()
    cpu = cgroup_cpu()
    log(f"done {len(commits)} commits, simulated {total / 1000:.3f}s, wall {time.time() - t0:.2f}s, cgroup cpu {cpu}")


if __name__ == "__main__":
    main()
