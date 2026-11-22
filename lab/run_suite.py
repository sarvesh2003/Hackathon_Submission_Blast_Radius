"""Label one patch by running sqlglot's full suite on a patched copy (lab only).

Usage (inside the br-lab image, repo mounted at /repo):
  python /repo/lab/run_suite.py PATCH OUT.json [--xdist N] [--timeout S] [--seed S]

PATCH may be "-" for the pristine tree. Prints failing test numbers to stderr
and writes a JSON result with the failing numbers.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, "/repo")
from br import patchlib  # noqa: E402

SRC = "/opt/sqlglot"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patch")
    ap.add_argument("out")
    ap.add_argument("--xdist", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--tests", default="/repo/sample/tests.json")
    ap.add_argument("--work", default="/tmp/w")
    args = ap.parse_args()

    tests = json.load(open(args.tests))["tests"]
    by_id = {t["id"]: t["number"] for t in tests}
    by_file = {}
    for t in tests:
        by_file.setdefault(t["file"], []).append(t["number"])

    shutil.rmtree(args.work, ignore_errors=True)
    shutil.copytree(SRC, args.work, symlinks=True)
    touched = {}
    if args.patch != "-":
        files = patchlib.parse(open(args.patch, "rb").read())

        def read(p):
            f = os.path.join(args.work, p)
            return open(f, "rb").read() if os.path.isfile(f) else None

        touched = patchlib.apply_to_tree(files, read)
        for p, data in touched.items():
            f = os.path.join(args.work, p)
            if data is None:
                if os.path.exists(f):
                    os.remove(f)
            else:
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f, "wb") as fh:
                    fh.write(data)
            # drop any cached bytecode for the touched module
            d, base = os.path.split(f)
            cache = os.path.join(d, "__pycache__")
            if base.endswith(".py") and os.path.isdir(cache):
                for c in os.listdir(cache):
                    if c.startswith(base[:-3] + "."):
                        os.remove(os.path.join(cache, c))

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{args.work}:/repo/lab"
    env["SKIP_INTEGRATION"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    res_path = os.path.join("/tmp", f"fp_{os.getpid()}.json")
    env["FAILPLUGIN_OUT"] = res_path
    if args.seed is not None:
        env["PYTHONHASHSEED"] = str(args.seed)
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "-p", "failplugin", "-p", "no:cacheprovider",
           f"--timeout={args.timeout}"]
    if args.xdist:
        cmd += ["-n", str(args.xdist)]
    t0 = time.time()
    subprocess.run(cmd, cwd=args.work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wall = time.time() - t0
    r = json.load(open(res_path))
    failing = set()
    unknown = []
    for nid in r["failed"]:
        base = nid.split("[", 1)[0]
        if base in by_id:
            failing.add(by_id[base])
        else:
            unknown.append(nid)
    for nid in r["collect_errors"]:
        f = nid.split("::", 1)[0]
        if f in by_file:
            failing.update(by_file[f])
        else:
            unknown.append(nid)
    out = {
        "patch": args.patch,
        "failing": sorted(failing),
        "unknown": unknown,
        "seen": r["seen"],
        "wall": wall,
        "xdist": args.xdist,
        "touched": sorted(touched),
        "durations": r["durations"],
    }
    json.dump(out, open(args.out, "w"))
    print(f"{os.path.basename(args.patch)}: {len(failing)} failing, wall {wall:.0f}s, unknown {unknown[:3]}", file=sys.stderr)


if __name__ == "__main__":
    main()
