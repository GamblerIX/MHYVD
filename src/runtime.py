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

    if timed_out:
        return EXIT_TIMEOUT
    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_SUCCESS


class ShutdownController:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._previous_handlers: dict[int, object] = {}
        self._installed_signals: list[int] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Future[Any] | None = None

    @property
    def shutdown_requested(self) -> bool:

        return self._event.is_set()

    def request_shutdown(self) -> None:

        self._event.set()

    def reset(self) -> None:

        self._event.clear()

    def wait(self, timeout: float | None = None) -> bool:

        return self._event.wait(timeout)

    def attach_async(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Future[Any],
    ) -> None:

        self._loop = loop
        self._task = task

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:

        self.request_shutdown()
        loop = self._loop
        task = self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def install(self, signals: Iterable[int] = (signal.SIGINT,)) -> tuple[int, ...]:

        installed: list[int] = []
        for sig in signals:
            try:
                previous = signal.signal(sig, self._handle_signal)
            except (ValueError, OSError, RuntimeError):
                continue
            self._previous_handlers[sig] = previous
            self._installed_signals.append(sig)
            installed.append(sig)
        return tuple(installed)

    def uninstall(self) -> None:

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

        return self._budget is None or self._budget <= 0

    def elapsed(self) -> float:

        return self._clock() - self._start

    def remaining(self) -> float | None:

        if self.unlimited:
            return None
        assert self._budget is not None
        return self._budget - self.elapsed()

    def expired(self) -> bool:

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
        return None, False
