"""Host-side driver: label many patches with the full suite, N containers at a time.

  python lab/label.py OUTDIR PATCH... [-j 3]

Skips patches whose label file already exists. Runs from the repo root.
"""

import argparse
import concurrent.futures as cf
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def host_path(p):
    # Docker Desktop on Windows wants C:/... style paths
    return p.replace("\\", "/")


def run(i, patch, outdir, cpus_per, extra):
    name = os.path.basename(patch)[:-6] if patch.endswith(".patch") else os.path.basename(patch)
    out = os.path.join(outdir, name + ".json")
    if os.path.exists(out):
        return f"{name}: cached"
    rel_patch = os.path.relpath(os.path.abspath(patch), ROOT).replace("\\", "/")
    rel_out = os.path.relpath(out, ROOT).replace("\\", "/")
    lo = (i * cpus_per) % 12
    cmd = ["docker", "run", "--rm", f"--cpuset-cpus={lo}-{lo + cpus_per - 1}", "--memory", "3g",
           "-v", f"{host_path(ROOT)}:/repo", "br-lab", "python", "/repo/lab/run_suite.py",
           f"/repo/{rel_patch}", f"/repo/{rel_out}"] + extra
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return (p.stderr.strip().splitlines() or ["?"])[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("patches", nargs="+")
    ap.add_argument("-j", type=int, default=3)
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--extra", default="")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    extra = a.extra.split() if a.extra else []
    with cf.ThreadPoolExecutor(a.j) as ex:
        futs = [ex.submit(run, i % a.j, p, a.outdir, a.cpus, extra) for i, p in enumerate(a.patches)]
        for f in cf.as_completed(futs):
            print(f.result(), flush=True)


if __name__ == "__main__":
    main()
