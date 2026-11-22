# PROGRESS.md: Blast Radius

Claude updates this after every milestone. The human reads it to see where things stand.

Last updated: Sat Nov 21, ~7:30 PM ET

## Status
| Milestone | State | Notes |
| --- | --- | --- |
| M0 Setup | done | starter `make sample`: 1210.470 s, 0 misses |
| M1 Lab and maps | in progress | |
| M2 Static selector v1 (first submission) | not started | |
| M3 Small test bench | not started | |
| M4 Probes, selector v2 | not started | |
| M5 Improve | not started | |
| M6 Final hardening | not started | |

## Machine
CPU: Intel Core Ultra 5 225U (laptop, 16 GB RAM) | docker NCPU: 14 | docker MemTotal: 10427756544 (~9.7 GB)

- Windows 11 + Docker Desktop 29.1.2 (linux/amd64). The repo lives at the Windows path the human chose (`C:/Users/sarve/Videos/Hackathon-Nov21/blast_radius_files_v2`), with `core.autocrlf=false`.
- `make` runs inside WSL (Ubuntu-24.04) on the `/mnt/c/...` path with `DOCKER_CONFIG=~/.docker-wsl` (a `{}` config; the default one names `desktop.exe` as credential store, which WSL cannot exec).
- Docker memory (~9.7 GB) caps how many full-suite lab containers run in parallel.

## Latest local results
| Commit | Change | Sample simulated (s) | Sample misses | Bench misses (holdout) | Bench cost | CPU via cgroup (s) |
| --- | --- | --- | --- | --- | --- | --- |
| 2e3d976 | starter (all tests, 3 workers) | 1210.470 | 0 | - | - | - |

## Submissions
| Time (ET) | Commit | Leaderboard result | Notes |
| --- | --- | --- | --- |

## Open questions and blockers
- none yet

## Next step
- M1 Lab and maps
