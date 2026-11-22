# CLAUDE.md: Blast Radius (RWX track, Builders Buildathon)

You are the engineer on this repo. Read this file, then PLAN.md (imported below), then PROGRESS.md. Work through PLAN.md one milestone at a time.

@PLAN.md

## Mission
For each code change (a unified diff against sqlglot at commit `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`), print which sqlglot tests to run and how to split them over at most 8 workers. Never miss a failing test; run as little as possible.

Score per run (lower wins), in whole milliseconds:
- each commit: the recorded ms of its busiest worker + 2,000 ms per non-empty worker (an empty selection costs 0);
- plus 300,000 ms for every commit that leaves out any test that fails on it;
- plus the CPU time of every process in our container (user + system, measured in microseconds), from start to exit;
- 3 runs; the median total counts, rounded half-up to 0.1 s.

Where we stand (Saturday morning): baseline 1614.1 s; board #1 126.1 s, #2 130.3 s, #3 134.3 s, 15th about 152 s. Practice has exactly 40 commits. Listing exactly the failing tests with the best split would score about 94.4 s on the 30 sample commits, about 126 s scaled to 40, so the leaders are close to perfect while using very little CPU.

Final (after the Sun Nov 22, 11:00 AM ET cutoff): our chosen commit runs on unseen commits (about 60, including kinds of change the practice set never had), 3 runs, median. At least the top 5 are re-run 5 times on one idle machine. A score at most 1 s behind the best counts as a tie, and ties go to the earliest submission of the selected commit. Only the final counts; the winner takes $5,000.

## Cost facts (computed from tests.json and the sample; use them)
- 1,620 tests with 103.0 s recorded. All tests: 4 workers is the best split, 36.8 s per commit (3 workers 40.3 s, 7 workers 42.8 s).
- 14 tests take 1 s or more (78.5 s together): `test_max_nodes` 28.8 s, `test_execute_tpcds` 21.5 s, `test_generator_memory` 6.7 s, and 11 more. The other 1,606 tests total 24.5 s.
- 94 tests record 0 ms, and 726 tests record at most 2 ms (0.86 s together). Once a commit needs a worker, listing cheap tests is nearly free. The real costs are the 2 s worker fee on commits that break nothing, the expensive tests, misses, and CPU.
- So the best answer for a commit that breaks nothing is `[]` (cost 0).
- Spare capacity on workers that aren't the busiest is free: fill it with extra plausible tests as insurance.
- 58 test files; 34 of them (1,020 tests) are nested, such as `tests/dialects/...`. Always take test files from tests.json, never from a `tests/*.py` glob.
- Sample (30 commits): 12 break nothing, 13 break exactly one test. Kinds: code 16, fixture 8, comment 3, multi 3. Every fixture edit broke exactly the test that reads that fixture file. Sample `535z` changes a class constant (`TSQL.WEEK_OFFSET`) and breaks `test_optimizer::test_simplify`: lines that run at import time matter.

## Source of truth
- `SCORING.md`: the exact scoring and output rules (the kit's `score.py` implements them).
- `docs/KIT_README.md`: the kit's README (limits and gotchas).
- `docs/track-page.md`: the official limits, rules and final.
- Unsure what a rule means? Ask the human right away; they can ask the organizers.

## Hard rules (breaking one means disqualification or a zero)
- No answers worked out ahead of time and looked up by patch: no table from a patch, or from a kind of edit, to the tests it breaks. Maps built from the pinned commit (coverage, imports, fixtures) are allowed. The organizers read the top entries.
- Never ship anything learned from `sample/answers.json` or the test bench's labels (such as "edit kind X means tests Y" or per-test failure rates). Every shipped map must be regenerable from the clean pinned tree alone. If unsure whether a tuned threshold is allowed, ask the human to ask the organizers. `.dockerignore` keeps `sample/answers.json` and `bench/` out of every image.
- The build may download only from public package registries (PyPI, npm, Docker Hub), GitHub releases at a fixed tag, and sqlglot's own repository at commit eb11aec. So: no `apt-get` in the submission Dockerfile. Fetch sqlglot as a GitHub archive at the pinned commit, and apply patches in Python (`python:3.13-slim` has no git and no patch).
- Our stdout carries answers only. Send every child process's stdout to `/dev/null` (tests print, and some spawn processes).
- The repo at the submitted commit must be at most 20 MB. No Git submodules and no Git LFS: commit maps as plain files.
- Our own team's code and repository only. Keep the repo public, with every submitted commit, until the results are published.

## How the scorer runs us
- Build: linux/amd64, network on, 4 cores, 8 GB, 10 minutes. Every submission is built from nothing, so commit maps instead of building them in the Dockerfile.
- Run: no network, 2 cores, 4 GB, 3 minutes for the whole batch (4.5 minutes in the final). User `nobody` (uid 65534), `HOME=/tmp`, at most 256 processes (reap every child). Read-only disk; `/tmp` holds 64 MB and is empty at the start of every run. Every file our program reads must be readable by `nobody`.
- Input: `/data/commits/<id>.patch` (one unified diff per commit; each stands alone) and `/data/tests.json` (`{"tests": [{"number", "id", "file", "seconds"}], "skipped": [...]}`; numbers run from 0 with no gaps).
- Output on stdout: exactly one JSON line per commit, `{"commit": "<id>", "workers": [[12, 845], [3]]}`. `"workers": []` runs nothing. At most 8 non-empty workers, no test twice in a line, only numbers from tests.json, every commit exactly once. Anything else on stdout, or more than 2 MB, rejects the run. Logs go to stderr.
- Submission image settings: the kit's base image by digest, `requirements.lock`, `ENV SKIP_INTEGRATION=0` and `ENV PYTHONDONTWRITEBYTECODE=1`; precompile the pristine sqlglot `.pyc` files at build time.
- Stop running tests at about 150 s of wall time (220 s in the final) and answer the remaining commits by listing.

## What "fails" means (how the labels were made)
- A test fails when pytest reports a failure, an error or a timeout for it, or when its file cannot be imported. A test with subtests is one test, and one failing subtest fails it (pytest 9 prints PASSED next to SUBFAILED lines: that test failed).
- The labels were made on the kit's base image (`python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90`), with exactly `requirements.lock` installed, the sqlglot checkout on `PYTHONPATH` (not `pip install -e .[dev]`), and `SKIP_INTEGRATION=0` (so executor tests run and can fail).
- A change that only adds a comment is not promised to be harmless.

## Known traps (verify each in the lab)
- Isolated runs can under-report. A reviewer reports that on sample `3utz` the full suite fails 37 tests, but running those 37 alone fails only 28 (the tests depend on order or state). Until the bench proves otherwise, a probe may turn a commit into `[]` only when it finds 0 failures; if any candidate fails, list all candidates.
- Per-test coverage misses work done in process pools (reported for `TestOptimizer` and `test_executor`). Map those tests one test per process with subprocess coverage, or treat their reach conservatively.
- Lines that run at import time (class constants, dict tables such as `TRANSFORMS` and `KEYWORDS`) have no per-test coverage. Map them to every test that executes code in that module or in modules whose classes inherit from it.
- Map a changed line to its enclosing statement and function: continuation lines of multi-line statements look uncovered.
- Comment-only change: compare the file's AST before and after (`ast.dump`, which leaves out line numbers). Equal ASTs are probably harmless, but the organizers warn otherwise, so rely on the bench before printing `[]` for them. A comment inside a fixture `.sql` file is not harmless: sqlglot parses SQL comments.
- Never import sqlglot in a parent process that forks per commit: the child would run the pristine code. Preload only third-party libraries in the parent.
- Calling `unittest` directly is faster than pytest but can skip pytest fixtures and plugins. Use it only if it reproduces the labels on the bench.

## Local measurement
- `make sample` scores simulated seconds and misses only.
- CPU: read `/sys/fs/cgroup/cpu.stat` (`usage_usec`) from inside the container at exit and log it to stderr. Timing `docker run` from outside measures the Docker client, not the container.

## Local Docker limits
Use the kit Makefile's `RUN_FLAGS` as they are (2 CPUs, 4 GB, no swap, read-only, user nobody, 64 MB `/tmp`, no network).

## Working rules
- Follow PLAN.md. Ask the human before changing the plan or how a hard rule is read.
- After every milestone: run its checks, update PROGRESS.md, commit, `git push`, and post a summary of at most 5 lines.
- Never force-push, rebase pushed commits, delete branches or rewrite history.
- The human submits. When a candidate passes its checks: commit, push, print exactly `READY TO SUBMIT: <full 40-character SHA>` with what changed and the local result. Then keep working on the next independent task while the human submits.
- 1 submission per hour to start (the organizers may raise it); rejected ones count. Submit strong versions early: the tie advantage belongs to the commit we select.
- Time-box dead ends to 20 minutes. Raise rule questions and access problems with the human immediately.
- Confirm the final SHA with the human by Sun 10:00 AM ET.
- Everything we write is MIT-licensed. Name every open-source library we use in README.md.
- Windows/WSL: work under the WSL home folder, never under `/mnt/c` or `/mnt/d`. `.gitattributes` turns off line-ending conversion; patches must stay byte-exact.
