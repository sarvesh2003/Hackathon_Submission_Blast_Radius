# Blast Radius: Builders Buildathon, RWX track

Given a code change to sqlglot, pick the tests that can catch it and split them across up to 8 workers: run as little as possible without missing a failing test.

- Scoring: [SCORING.md](SCORING.md). Kit README: [docs/KIT_README.md](docs/KIT_README.md). Track facts: [docs/track-page.md](docs/track-page.md).
- Plan and status: [PLAN.md](PLAN.md), [PROGRESS.md](PROGRESS.md). Instructions for Claude Code: [CLAUDE.md](CLAUDE.md).

## Build and test
```sh
make sample   # build, run on the 30 sample commits with the scorer's limits, and score
make check    # output format only
```

## Third-party material
- Official Buildathon starter kit: `Dockerfile`, `Makefile`, `score.py`, `selector.py` (starter), `requirements.lock`, `SCORING.md`, `sample/`, `docs/KIT_README.md`.
- sqlglot (MIT), cloned at commit eb11aec4be8cb2122afe713a4816662c3f0fb2fa.
- Other libraries: listed here as they are added.

## License
MIT. See [LICENSE](LICENSE).
