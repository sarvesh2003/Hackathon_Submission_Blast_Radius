"""In-process stand-in for ProcessPoolExecutor.

sqlglot's tests send work to spawn pools. A spawn worker would import the
pristine sqlglot from disk and costs about a CPU-second to start, so we run the
work in-process instead, while keeping what the pool does to the data:

- arguments and results make a pickle round trip (Expr.__reduce__ goes
  through sqlglot.serde, so serde bugs still surface);
- like CPython's pool, a result that cannot be unpickled breaks the pool:
  that future and every later submit fail with BrokenProcessPool;
- an exception raised by the task is pickled back and re-raised from
  future.result().
"""

import pickle
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

_dumps = pickle.dumps
_loads = pickle.loads

# Every pool created since the last reset; the probe inspects them.
POOLS = []


def _roundtrip(obj):
    return _loads(_dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))


class FakeProcessPoolExecutor:
    def __init__(self, max_workers=None, mp_context=None, initializer=None, initargs=(), **kwargs):
        self._broken = None
        self._shutdown = False
        self.roundtrip_errors = 0
        POOLS.append(self)
        if initializer is not None:
            try:
                initializer(*_roundtrip(tuple(initargs)))
            except BaseException as e:  # noqa: BLE001 - a failing initializer breaks a real pool
                self._broken = BrokenProcessPool(f"initializer failed: {e!r}")
                self.roundtrip_errors += 1

    def submit(self, fn, /, *args, **kwargs):
        if self._broken is not None:
            raise BrokenProcessPool("A child process terminated abruptly, the process pool is not usable anymore")
        if self._shutdown:
            raise RuntimeError("cannot schedule new futures after shutdown")
        fut = Future()
        try:
            fn2, args2, kwargs2 = _roundtrip((fn, args, kwargs))
        except BaseException as e:  # noqa: BLE001
            # Pickling the call item fails in the parent: the real pool reports it on the future.
            self.roundtrip_errors += 1
            fut.set_exception(e)
            return fut
        try:
            result = fn2(*args2, **kwargs2)
        except BaseException as e:  # noqa: BLE001
            try:
                exc = _roundtrip(e)
            except BaseException:  # noqa: BLE001
                self.roundtrip_errors += 1
                exc = e
            fut.set_exception(exc)
            return fut
        try:
            payload = _dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
        except BaseException as e:  # noqa: BLE001
            # The worker cannot pickle the result: CPython sends the error back on this future only.
            self.roundtrip_errors += 1
            fut.set_exception(e)
            return fut
        try:
            value = _loads(payload)
        except BaseException:  # noqa: BLE001
            # The parent cannot unpickle the result: the whole pool breaks.
            self.roundtrip_errors += 1
            self._broken = BrokenProcessPool(
                "A process in the process pool was terminated abruptly while the future was running or pending."
            )
            fut.set_exception(self._broken)
            return fut
        fut.set_result(value)
        return fut

    def map(self, fn, *iterables, timeout=None, chunksize=1):
        futs = [self.submit(fn, *a) for a in zip(*iterables)]
        return (f.result() for f in futs)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self._shutdown = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()
        return False


def install():
    """Replace ProcessPoolExecutor before the test modules import it."""
    import concurrent.futures
    import concurrent.futures.process

    concurrent.futures.ProcessPoolExecutor = FakeProcessPoolExecutor
    concurrent.futures.process.ProcessPoolExecutor = FakeProcessPoolExecutor
