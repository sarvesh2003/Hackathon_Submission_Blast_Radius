"""Build raw per-test maps on the clean tree (lab only).

  python /repo/lab/run_map.py OUT.pkl [--seed N] [--no-types] [-k EXPR]
"""

import argparse
import os
import shutil
import subprocess
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seed", default="0")
    ap.add_argument("--no-types", action="store_true")
    ap.add_argument("-k", default=None)
    ap.add_argument("--paths", nargs="*", default=["tests"])
    a = ap.parse_args()
    work = "/tmp/w"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree("/opt/sqlglot", work, symlinks=True)
    env = dict(os.environ)
    env.update(
        PYTHONPATH=f"{work}:/repo/lab",
        SKIP_INTEGRATION="0",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONHASHSEED=str(a.seed),
        MAP_ROOT=work,
        MAP_OUT=a.out,
        MAP_TYPES="0" if a.no_types else "1",
        FAILPLUGIN_OUT=a.out + ".fail.json",
    )
    cmd = [sys.executable, "-m", "pytest", *a.paths, "-q", "-p", "mapplugin", "-p", "failplugin",
           "-p", "no:cacheprovider", "--timeout=0"]
    if a.k:
        cmd += ["-k", a.k]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(p.stdout[-3000:], file=sys.stderr)
    print(f"map done in {time.time() - t0:.0f}s -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
