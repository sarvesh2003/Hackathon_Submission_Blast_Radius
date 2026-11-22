# PLAN.md: Blast Radius

Cutoff: **Sun Nov 22, 11:00 AM ET**. Target times are ET. Work top to bottom and keep PROGRESS.md current.

Strategy: a conservative static selector first (maps from the pinned commit plus exact scheduling), submitted early. Then probes: run cheap candidate tests inside the container only to prove that a commit breaks nothing, so it can print `[]`. Never risk a 300 s miss to save a second.

## M0. Setup (about 30 min)
- [ ] Ask the human to keep the laptop awake while it is plugged in.
- [ ] Check tools: `docker version`, `make`, `python3 --version` (3.9 or newer), `git`. Record `docker info --format '{{.NCPU}} {{.MemTotal}}'` and the CPU model in PROGRESS.md.
- [ ] `make sample` with the starter selector: expect 1,210.5 s simulated, 0 misses.
- Done when: `make sample` works.

## M1. Lab and maps (about 2.5 h; run the parts in parallel)
- [ ] `lab/Dockerfile` (local only, so `apt-get` is fine here): the kit's base image by digest, `requirements.lock`, sqlglot at eb11aec on `PYTHONPATH`, `SKIP_INTEGRATION=0`. Install coverage tools with `--no-deps` so the labeled environment stays exact.
- [ ] `lab/run_suite.py`: apply a patch (in Python) to a fresh copy, run the full suite (pytest-xdist is fine), and print the failing test numbers (failures, errors, timeouts, import errors, SUBFAILED).
- [ ] Reproduce 3 sample labels quickly, then all 30 in the background. Probe results may drop tests only after 30/30 match.
- [ ] Build maps from the clean pinned tree only. Store them compactly under `maps/` (gzip or a binary format, not raw JSON) and keep the repo under 20 MB:
    - line to tests, from per-test coverage (try `COVERAGE_CORE=sysmon` for speed; run process-pool tests one test per process with subprocess coverage);
    - import-time lines and the class hierarchy: module to every test that executes code in it or in its subclasses' modules;
    - fixture file to the tests that read it (wrap `open` during the run);
    - test file to test numbers and each test function's line range, for every file listed in tests.json, nested ones included.
- Done when: the maps exist, load in under 0.2 s, and for all 30 sample patches the selection covers every failing test.

## M2. Static selector v1 (about 1.5 h; submit by Sat about 3 PM)
- [ ] Parse each diff robustly: several files per patch, added, deleted and renamed files, `\ No newline at end of file`.
- [ ] Per commit, in this order:
    1. Anything we can't parse or have no map for (new, deleted or renamed files; non-`.py`/`.sql` files; packaging; `conftest.py` or test helpers): list every test on 4 workers (36.8 s). Never guess.
    2. Code edits under `sqlglot/`: the tests that cover the enclosing statements and functions; import-time lines use the module and subclass reach.
    3. Fixture edits: the tests that read that file.
    4. Test-file edits: the edited test functions; a module-level edit selects the whole file.
    5. Comment-only `.py` edits with an identical AST: list the candidate tests for now (they are cheap). The bench decides later whether `[]` is safe.
    6. Include an expensive test (1 s or more) only when the maps say the change reaches it.
- [ ] Scheduler: integer milliseconds; try 1 to 8 non-empty workers; exact search for small sets, largest-first otherwise; fill spare capacity on workers that aren't the busiest with extra plausible tests.
- [ ] `make sample`: 0 misses. Record the cost. Commit, push, READY TO SUBMIT.

## M3. Small test bench (start right after M1, in the background)
- [ ] `tools/bench/mutate.py`: 60 to 100 changes first, weighted to kinds the sample lacks: dialect table entries, class constants, comments (including inside docstrings and fixture `.sql` files), whitespace-only edits, added functions, test-file edits, multi-file changes. Keep 20 aside as an untouched holdout.
- [ ] Label each with the lab; keep results in `bench/` (git-ignored, never shipped). Cap parallel suites to what the laptop's memory allows.
- [ ] `tools/bench/evaluate.py`: misses (must be 0), cost per kind, CPU time.
- [ ] Add more changes overnight while the laptop is otherwise idle.

## M4. Probes, selector v2 (Sat night): design approved by the human on Sat Nov 21 after an external review
Cost identity: every candidate test costs its runtime once (CPU if probed, simulated if listed), so probing only ever wins the 2 s worker fee on commits that break nothing. Levers in order: zero misses, a smaller candidate set, less fixed CPU, then probing.
- [ ] Submission image like the lab but without `apt-get`: sqlglot from the GitHub archive at the pinned commit, patches applied in Python (bytes, split on `\n` only), `ENV SKIP_INTEGRATION=0`, `ENV PYTHONDONTWRITEBYTECODE=1`, precompiled pristine `.pyc`.
- [ ] At start, copy the sqlglot tree (sqlglot/, tests/, sqlglotc/; mtimes kept so the `.pyc` stay valid) to `/tmp`. Patched files are written there (and their `.pyc` deleted) so tests that read sources from disk (`test_typing`, `test_sqlglotc`, the subprocess in `test_dialect`) see them. Commits run strictly one at a time; restore files after each.
- [ ] A warm zygote preloads the third-party libraries, pristine sqlglot and every test module (as pytest's collection does), with `sys.monitoring` recording which functions ran during preload. Build the code-to-functions index once in the zygote.
- [ ] Per commit:
    - T0 (no fork): compiled code identical to pristine, or fixture-loader output identical: `[]` unless a source-reading or line-sensitive test maps to the file.
    - T1 (fork + `__code__` swap): only if the change is confined to function bodies, no changed function ran during preload, and closures match.
    - T2 (fork from a pre-sqlglot zygote, fresh import from the patched `/tmp` tree): everything else (class bodies, constants, decorators, new or deleted modules).
- [ ] The child replaces spawn pools with an in-process pool that pickle-round-trips arguments and results AND models brokenness (one unpickling error breaks the pool; verified in the lab). Any error in that round trip lists every pool-using test in the class.
- [ ] Contagion: `setUpClass` failure lists the class; test-module import failure lists the file; sqlglot import failure lists everything; `__init__.py`, `conftest.py`, `pyproject.toml`, `setup.*` edits list everything.
- [ ] Decision: candidates over about 8 s in total, or any reached test over about 2 s, means list without probing (the fee is sunk). Otherwise probe cheapest-first and stop at the first failure; list that failure plus every unprobed candidate. All pass with no risk channel triggered: `[]`. Crash, timeout (over 5x recorded, plus slack), unparsable patch or map mismatch: list all candidates (or everything).
- [ ] Scheduler: integer ms, k = 1..8, LPT, minimum of max load + 2k. Insurance only into slack on already-open workers.
- [ ] Wall budget guard: list the remaining commits if the run nears the limit.
- [ ] Gate: bench 0 misses (holdout included), `make sample` 0 misses, total (simulated + cgroup CPU) lower than v1. Then READY TO SUBMIT.

## M5. Improve (Sat night to Sun about 6 AM)
- [ ] Fix every miss first. Then cut cost where the bench shows it. Print `[]` for AST-identical comment edits only if many comment changes on the bench show zero failures.
- [ ] Heavy-test cuts, only if the bench shows they pay: TPC fixture edits that leave the (meta, sql) side unchanged cannot affect `test_execute_tpch/tpcds`; changed TPC queries can be run alone; precomputed pristine hashes of the duckdb SQL strings.
- [ ] Trim boot CPU (load pandas/duckdb only when needed), gated on bench equality.
- [ ] Submit hourly whenever there are 0 misses and a lower cost. Log every result in PROGRESS.md.

## M6. Final hardening (Sun 6:00 to 9:30 AM)
- [ ] No new features after 8:00 AM.
- [ ] Fresh clone, `docker build --no-cache .` (check that every download follows the rules), `make sample`, full bench and holdout: 0 misses.
- [ ] README: approach, how to build and test, every library used, MIT license.
- [ ] Recommend the final SHA by 10:00 AM: the most robust low-cost version (0 misses matters more than the last second). The human selects it on the track page before 11:00 AM.
