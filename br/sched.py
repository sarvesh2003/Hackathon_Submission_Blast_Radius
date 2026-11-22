"""Split tests over at most 8 workers: minimise max load + 2000 ms per worker.

All arithmetic is in whole milliseconds, exactly as the scorer computes it.
"""

from __future__ import annotations

import heapq

WORKER_MS = 2000
MAX_WORKERS = 8


def _lpt(items: list[tuple[int, int]], k: int) -> tuple[int, list[list[int]]]:
    heap = [(0, w) for w in range(k)]
    bins: list[list[int]] = [[] for _ in range(k)]
    loads = [0] * k
    for ms, num in items:
        load, w = heapq.heappop(heap)
        bins[w].append(num)
        loads[w] = load + ms
        heapq.heappush(heap, (loads[w], w))
    return max(loads), bins


def schedule(nums: list[int], ms: list[int]) -> tuple[int, list[list[int]]]:
    """Return (cost in ms, workers) for the tests `nums`; ms[n] is test n's duration."""
    if not nums:
        return 0, []
    items = sorted(((ms[n], n) for n in set(nums)), reverse=True)
    total = sum(m for m, _ in items)
    best = None
    for k in range(1, min(MAX_WORKERS, len(items)) + 1):
        lower = max(items[0][0], -(-total // k)) + WORKER_MS * k
        if best is not None and lower >= best[0]:
            if WORKER_MS * k >= best[0]:
                break
            continue
        mx, bins = _lpt(items, k)
        cost = mx + WORKER_MS * k
        if best is None or cost < best[0]:
            best = (cost, [b for b in bins if b])
    return best


def cost_of(workers: list[list[int]], ms: list[int]) -> int:
    ws = [w for w in workers if w]
    if not ws:
        return 0
    return max(sum(ms[n] for n in w) for w in ws) + WORKER_MS * len(ws)
