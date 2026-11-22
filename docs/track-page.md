# RWX: Blast Radius (official track page, copied 2026-11-21)

Source: https://www.joinbuilders.org/buildathon/tracks/blast-radius. Exact scoring: [../SCORING.md](../SCORING.md). Prize: $5,000, winner takes all.

> Given a code change, pick the tests that can catch it. Run less and you win; miss a failure and it costs you.

## The problem
Every fast CI system makes one decision on every commit: which tests does this change need? Run them all and you wait. Skip the wrong one and a bug ships.

You get a batch of code changes to sqlglot, a Python SQL parser. For each change, say which of its tests to run and how to split them across up to 8 workers. Most changes break at least one test. Some break nothing at all, and the right answer for those is to run nothing.

## What you hand in
A public GitHub repository with a Dockerfile at its top, and the commit to score. Any language, any libraries, any amount of AI. The starter kit is a working submission that runs every test; `make sample` builds the image, runs it on the 30 sample commits under the limits below and scores what it printed (needs Docker, make and Python 3.9 or newer).

## What your program gets
Every change is a patch against sqlglot at commit eb11aec4be8cb2122afe713a4816662c3f0fb2fa. Each one stands alone: none builds on another.
- /data/commits/<id>.patch: one unified diff a commit.
- /data/tests.json: every test, numbered, with its file and how long it took us to run.
- Print one JSON line a commit to stdout: {"commit": "k7q2", "workers": [[12, 845, 901], [3, 77]]}. Each inner list is one worker's test numbers. "workers": [] runs nothing.
- Send logs to stderr. Anything else on stdout, or more than 2 MB of it, rejects the run.

## How it runs
- The build has the network, 4 cores, 8 GB of memory and 10 minutes. It may clone sqlglot, install it and run its tests to make coverage or import maps.
- Every submission is built from nothing, so a build that runs sqlglot's tests takes minutes each time you submit. A map you make once and commit builds in seconds: your repository may hold 20 MB. Git submodules and Git LFS files are not fetched: clone sqlglot in the Dockerfile and commit maps as plain files.
- No network while running.
- Your program runs as user nobody, with HOME=/tmp and at most 256 processes.
- 2 cores, 4 GB of memory, 3 minutes for the whole batch (4.5 in the final, which has about one and a half times as many commits).
- A read-only disk. /tmp holds 64 MB and is empty at the start of every run.
- Running sqlglot's tests while you decide is allowed. Its CPU time is charged like any other.

## What fails means
A test fails on a commit when pytest reports a failure, an error or a timeout for it, or when its file cannot be imported. A test with subtests is one test, and one failing subtest fails it. A change that only adds a comment is not promised to be harmless.

## Scoring
- Metric: simulated CI seconds, lower is better. Baseline to beat: 1614.1 s (starter: run every test, split across 3 workers).
- Formula: test seconds on the busiest worker + 2 s a worker + 300 s a missed commit + your CPU seconds; middle of 3 runs.
- Ties: equal scores rank the earlier submission first. In the final, a score at most 1 second behind the best counts as equal to it: those entries rank by when each was submitted, earliest first, and the rest are ranked the same way, starting from the best of them. The final board shows this order, and first place wins.
- For every commit you choose which tests run and on which of up to 8 workers. A commit costs its busiest worker's recorded test time plus 2 seconds for each worker. Leaving out a test that fails on a commit adds 300 seconds for that commit. The CPU time your program uses is added, so running tests to decide is allowed and paid for.

## Rules
- A commit costs the recorded seconds of its busiest worker, plus 2 seconds for every worker. An empty selection costs 0.
- A commit whose selection leaves out a test that fails on it adds 300 seconds. With your score you are told each run's simulated seconds, CPU seconds and how many commits missed, never which commit.
- Your program's CPU seconds are added. The image runs 3 times and the middle total counts, rounded to 0.1 s.
- In the final, the best entries are scored again with 5 runs on one machine with nothing else running, so a busy machine's CPU time cannot decide the winner.
- One line a commit, at most 8 workers, no test twice in a commit, only test numbers from tests.json.
- A broken rule, a crash, a run over the time or memory limit, or a build that fails rejects the submission and says which. It never changes your best score.
- You never see what your program printed. Test on the sample set, where the answers are in the kit.
- Your team may submit once an hour to start. We raise it if the queue stays short.
- One team a person, and your own team's repository. No sharing code between teams: top entries are compared, and you may be asked to explain yours. A submission with the same repository, commit or archive as another team's is disqualified, the later one.
- Your build may download only from public package registries (PyPI, npm, Docker Hub), GitHub releases at a fixed tag, and sqlglot's own repository at commit eb11aec. Nothing from an address your team controls. The final rebuilds every image after the cutoff, so anything else could change a submission after the deadline.
- No answers worked out ahead of time and looked up by patch: no table from a patch, or from a kind of edit, to the tests it breaks. Maps built from the pinned commit (coverage, imports, fixtures) are allowed. Top entries are read.
- Keep your repository public, with every commit you submitted still in it, until the results are published: the final builds your chosen commit again, and an entry we can neither restore nor fetch scores nothing.
- Only the final counts. The practice board carries no prize.
- If we find a commit labeled wrongly before results are published, we correct it for every team.

## The final
At the cutoff your team's chosen commit (your best, unless you pick another) is scored once on commits nobody has seen, including kinds of change the practice set never had. Then at least the 5 best entries are scored again on the same commits, 5 runs each instead of 3, one at a time on one scoring machine with nothing else running on it. For each of them, that middle total replaces the first one.

The cutoff is Sun Nov 22, 11:00 AM ET.

## General Buildathon rules that apply
- Teams of up to 2. Any tools, AI included. Code written before the weekend and open-source libraries are allowed; name them in the README.
- Everything built must be released under the MIT License.
- Every submission counts toward the hourly limit, even a rejected one. One entry per team per track at a time, including entries waiting in line.
- Pick your final submission on the track page before the cutoff; if you don't, your best-scoring entry is used.
