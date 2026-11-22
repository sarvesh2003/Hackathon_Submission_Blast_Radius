"""pytest plugin: record every test id that fails, errors, or times out.

Subtest reports carry the parent's nodeid, so a failing subtest fails its
test. A file that cannot be collected fails every test in it.
"""

import json
import os
import time

_failed = set()
_collect_errors = set()
_seen = set()
_durations = {}
_t0 = time.time()


def pytest_runtest_logreport(report):
    _seen.add(report.nodeid)
    if report.failed:
        _failed.add(report.nodeid)
    if report.when == "call":
        _durations[report.nodeid] = _durations.get(report.nodeid, 0.0) + report.duration


def pytest_collectreport(report):
    if report.failed:
        _collect_errors.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("FAILPLUGIN_OUT")
    if not out:
        return
    with open(out, "w") as f:
        json.dump(
            {
                "failed": sorted(_failed),
                "collect_errors": sorted(_collect_errors),
                "seen": len(_seen),
                "exitstatus": int(exitstatus),
                "wall": time.time() - _t0,
                "durations": _durations,
            },
            f,
        )
