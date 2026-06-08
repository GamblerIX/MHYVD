"""Process exit-code, interruption, and time-budget handling for MHYVD.

This module concentrates the process-level concerns described in Requirement 12
(Error Handling and Interruption):

* :func:`choose_exit_code` — the pure precedence rule that maps the
  ``timed_out``/``interrupted`` conditions onto an exit code. Timeout (124)
  takes precedence over a user interrupt (130), which in turn takes precedence
  over normal completion (0). This is Property 28 from the design document.
* :class:`ShutdownController` — a small, thread-safe shared flag plus a SIGINT
  handler installer. On interrupt the handler merely *requests* shutdown; the
  caches already persist their state on every ``add`` (Requirement 12.4), so no
  extra flushing is required here.
* :class:`Deadline` / :func:`run_with_time_budget` — helpers that enforce the
  configured overall time budget (Requirement 12.3) and report when it has been
  exceeded so the caller can select the timeout exit code.

Keeping these together lets ``main`` wire interruption and timeout handling
around the pipeline without spreading signal/asyncio details through the rest
of the codebase.
"""

from __future__ import annotations

import asyncio
import signal
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from types import FrameType
from typing import Any, Literal, TypeVar

from .constants import EXIT_INTERRUPTED, EXIT_SUCCESS, EXIT_TIMEOUT

__all__ = [
    "choose_exit_code",
    "ShutdownController",
    "Deadline",
    "run_with_time_budget",
]

T = TypeVar("T")


def choose_exit_code(timed_out: bool, interrupted: bool) -> int:
    """Return the process exit code for the given run conditions.

    Precedence (Property 28 / Requirements 12.3, 12.4):

    1. ``EXIT_TIMEOUT`` (124) when the overall time budget was exceeded — this
       wins even if an interrupt occurred simultaneously.
    2. ``EXIT_INTERRUPTED`` (130) when the user interrupted the run.
    3. ``EXIT_SUCCESS`` (0) on normal completion.

    This is a pure function: its result depends only on its arguments.
    """

    if timed_out:
        return EXIT_TIMEOUT
    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_SUCCESS


class ShutdownController:
    """Thread-safe shutdown flag with an optional SIGINT handler.

    A single controller is shared across the run. The signal handler only sets
    the flag (:meth:`request_shutdown`); cooperative callers poll
    :attr:`shutdown_requested` (or :meth:`wait`) and stop at a safe point. The
    caches persist their state on each ``add``, so requesting shutdown is
    sufficient to preserve completed work (Requirement 12.4).
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._previous_handlers: dict[int, object] = {}
        self._installed_signals: list[int] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Future[Any] | None = None

    @property
    def shutdown_requested(self) -> bool:
        """Whether a shutdown has been requested."""

        return self._event.is_set()

    def request_shutdown(self) -> None:
        """Request shutdown by setting the shared flag (idempotent)."""

        self._event.set()

    def reset(self) -> None:
        """Clear the shutdown flag (primarily for tests/reuse)."""

        self._event.clear()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until shutdown is requested or ``timeout`` elapses.

        Returns ``True`` if shutdown was requested, ``False`` on timeout.
        """

        return self._event.wait(timeout)

    def attach_async(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Future[Any],
    ) -> None:
        """Bind the running event loop and pipeline task for cancellation.

        Once attached, an interrupt cancels ``task`` (via
        :meth:`loop.call_soon_threadsafe`) so the in-flight run aborts promptly
        instead of being noticed only after it completes (Requirement 12.4).
        """

        self._loop = loop
        self._task = task

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        """Signal handler: request shutdown without doing heavy work.

        When an event loop and task have been attached (:meth:`attach_async`),
        the in-flight pipeline task is also cancelled so the run stops promptly.
        Cancellation is scheduled on the loop thread and guarded so a teardown
        race never raises inside the signal handler.
        """

        self.request_shutdown()
        loop = self._loop
        task = self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                # The loop may already be closed during teardown; ignore.
                pass

    def install(self, signals: Iterable[int] = (signal.SIGINT,)) -> tuple[int, ...]:
        """Install the shutdown handler for ``signals`` (default: SIGINT).

        Returns the signals actually installed. Signal handlers can only be
        registered from the main thread of the main interpreter; when that is
        not possible (e.g. a worker thread) the signal is skipped rather than
        raising, so callers in any context degrade gracefully.
        """

        installed: list[int] = []
        for sig in signals:
            try:
                previous = signal.signal(sig, self._handle_signal)
            except (ValueError, OSError, RuntimeError):
                # Not the main thread, or the platform rejects this signal.
                continue
            self._previous_handlers[sig] = previous
            self._installed_signals.append(sig)
            installed.append(sig)
        return tuple(installed)

    def uninstall(self) -> None:
        """Restore the signal handlers replaced by :meth:`install`."""

        while self._installed_signals:
            sig = self._installed_signals.pop()
            previous = self._previous_handlers.pop(sig, signal.SIG_DFL)
            try:
                signal.signal(sig, previous)  # type: ignore[arg-type]
            except (ValueError, OSError, RuntimeError):
                pass

    def __enter__(self) -> ShutdownController:
        self.install()
        return self

    def __exit__(self, *exc_info: object) -> Literal[False]:
        self.uninstall()
        return False


class Deadline:
    """Tracks an overall time budget for a run (Requirement 12.3).

    A non-positive ``budget`` means *no limit*: such a deadline never expires.
    The monotonic clock is injectable to keep the logic deterministically
    testable.
    """

    def __init__(
        self,
        budget: float | None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget = budget
        self._clock = clock
        self._start = clock()

    @property
    def budget(self) -> float | None:
        return self._budget

    @property
    def unlimited(self) -> bool:
        """Whether this deadline imposes no limit."""

        return self._budget is None or self._budget <= 0

    def elapsed(self) -> float:
        """Seconds elapsed since the deadline was created."""

        return self._clock() - self._start

    def remaining(self) -> float | None:
        """Seconds left before expiry, or ``None`` when unlimited."""

        if self.unlimited:
            return None
        assert self._budget is not None  # narrow for type-checkers
        return self._budget - self.elapsed()

    def expired(self) -> bool:
        """Whether the budget has been exceeded."""

        if self.unlimited:
            return False
        remaining = self.remaining()
        assert remaining is not None
        return remaining <= 0


async def run_with_time_budget(
    awaitable: Awaitable[T],
    budget: float | None,
    *,
    controller: ShutdownController | None = None,
) -> tuple[T | None, bool]:
    """Await ``awaitable`` under an overall time budget.

    Returns ``(result, timed_out)``. On timeout the pending operation is
    cancelled, ``result`` is ``None`` and ``timed_out`` is ``True``. A
    non-positive or ``None`` ``budget`` means no limit, so the awaitable runs
    to completion and ``timed_out`` is ``False``.

    When a ``controller`` is supplied it is bound to the running loop and the
    wrapping task (:meth:`ShutdownController.attach_async`) so an interrupt
    cancels the in-flight run promptly (Requirement 12.4). Such a
    cancellation surfaces as ``(None, False)`` -- a non-timeout incomplete run;
    the caller reads ``controller.shutdown_requested`` to map it to the
    interruption exit code.
    """

    task = asyncio.ensure_future(awaitable)
    if controller is not None:
        controller.attach_async(asyncio.get_running_loop(), task)

    try:
        if budget is None or budget <= 0:
            result = await task
        else:
            result = await asyncio.wait_for(task, timeout=budget)
        return result, False
    except TimeoutError:
        return None, True
    except asyncio.CancelledError:
        # Interrupt-driven cancellation: surface as a non-timeout incomplete run.
        return None, False
