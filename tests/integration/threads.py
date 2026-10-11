"""Helpers for the tests that race a request against a held lock."""

import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text


def wait_until_blocked(holder, deadline=5.0):
    """Poll pg_stat_activity for some *other* backend waiting on a lock,
    so the test cannot pass just because the request happened to arrive
    late. Postgres reports a row-lock wait via wait_event_type='Lock'
    (wait_event='transactionid'); the query text it shows alongside a
    blocked backend is not reliable (it can lag behind the statement
    actually stuck), so filter on the wait state, not the query text.

    Postgres caches the activity statistics for the rest of a transaction,
    so each poll clears that snapshot first; otherwise a request that
    connects after the first poll is never seen. Only this database's
    backends count, so another database's lock wait cannot pass it.
    """
    my_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        holder.execute(text("SELECT pg_stat_clear_snapshot()"))
        waiting = holder.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND pid != :pid "
                "AND datname = current_database()"
            ),
            {"pid": my_pid},
        ).scalar()
        if waiting:
            return True
        time.sleep(0.05)
    return False


class ThreadHandle:
    """A started thread and its outcome. result() joins and then returns
    what fn returned, or re-raises what it raised, so a request that
    fails inside the thread fails the test with that error rather than
    with a KeyError on a result dict."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self._value: Any = None
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, args=(fn,))
        self._thread.daemon = True
        self._thread.start()

    def _run(self, fn: Callable[[], Any]) -> None:
        try:
            self._value = fn()
        except Exception as e:
            self._error = e

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def result(self, timeout: float = 5.0) -> Any:
        self._thread.join(timeout)
        assert not self._thread.is_alive(), (
            f"the thread did not finish within {timeout} s"
        )
        if self._error is not None:
            raise self._error
        return self._value


def run_in_thread(fn: Callable[[], Any]) -> ThreadHandle:
    """Run fn on a daemon thread; see ThreadHandle."""
    return ThreadHandle(fn)
