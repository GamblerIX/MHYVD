from __future__ import annotations

import asyncio
import signal
import unittest

from src.constants import EXIT_INTERRUPTED, EXIT_SUCCESS, EXIT_TIMEOUT
from src.runtime import (
    Deadline,
    ShutdownController,
    choose_exit_code,
    run_with_time_budget,
)

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


class ChooseExitCodeTests(unittest.TestCase):
    def test_normal_completion(self) -> None:
        self.assertEqual(choose_exit_code(False, False), EXIT_SUCCESS)

    def test_interrupt_only(self) -> None:
        self.assertEqual(choose_exit_code(False, True), EXIT_INTERRUPTED)

    def test_timeout_only(self) -> None:
        self.assertEqual(choose_exit_code(True, False), EXIT_TIMEOUT)

    def test_timeout_precedes_interrupt(self) -> None:

        self.assertEqual(choose_exit_code(True, True), EXIT_TIMEOUT)

    def test_known_exit_code_values(self) -> None:
        self.assertEqual((EXIT_SUCCESS, EXIT_TIMEOUT, EXIT_INTERRUPTED), (0, 124, 130))


class ExitCodePrecedencePropertyTests(unittest.TestCase):
    def _check(self, timed_out: bool, interrupted: bool) -> None:
        code = choose_exit_code(timed_out, interrupted)
        if timed_out:
            self.assertEqual(code, EXIT_TIMEOUT)
        elif interrupted:
            self.assertEqual(code, EXIT_INTERRUPTED)
        else:
            self.assertEqual(code, EXIT_SUCCESS)

    if _HAS_HYPOTHESIS:

        @settings(max_examples=100)
        @given(timed_out=st.booleans(), interrupted=st.booleans())
        def test_precedence_property(self, timed_out: bool, interrupted: bool) -> None:
            self._check(timed_out, interrupted)

    else:  # pragma: no cover

        def test_precedence_property(self) -> None:
            for timed_out in (False, True):
                for interrupted in (False, True):
                    with self.subTest(timed_out=timed_out, interrupted=interrupted):
                        self._check(timed_out, interrupted)


class ShutdownControllerTests(unittest.TestCase):
    def test_starts_not_requested(self) -> None:
        controller = ShutdownController()
        self.assertFalse(controller.shutdown_requested)

    def test_request_shutdown_sets_flag(self) -> None:
        controller = ShutdownController()
        controller.request_shutdown()
        self.assertTrue(controller.shutdown_requested)

    def test_request_shutdown_is_idempotent(self) -> None:
        controller = ShutdownController()
        controller.request_shutdown()
        controller.request_shutdown()
        self.assertTrue(controller.shutdown_requested)

    def test_reset_clears_flag(self) -> None:
        controller = ShutdownController()
        controller.request_shutdown()
        controller.reset()
        self.assertFalse(controller.shutdown_requested)

    def test_wait_returns_immediately_when_requested(self) -> None:
        controller = ShutdownController()
        controller.request_shutdown()
        self.assertTrue(controller.wait(timeout=0.01))

    def test_wait_times_out_when_not_requested(self) -> None:
        controller = ShutdownController()
        self.assertFalse(controller.wait(timeout=0.01))

    def test_signal_handler_requests_shutdown(self) -> None:
        controller = ShutdownController()

        controller._handle_signal(int(signal.SIGINT), None)
        self.assertTrue(controller.shutdown_requested)

    def test_install_registers_and_uninstall_restores(self) -> None:
        original = signal.getsignal(signal.SIGINT)
        controller = ShutdownController()
        try:
            installed = controller.install((signal.SIGINT,))
            self.assertIn(signal.SIGINT, installed)

            self.assertEqual(signal.getsignal(signal.SIGINT), controller._handle_signal)

            handler = signal.getsignal(signal.SIGINT)
            handler(int(signal.SIGINT), None)  # type: ignore[misc, operator]
            self.assertTrue(controller.shutdown_requested)
        finally:
            controller.uninstall()
        self.assertEqual(signal.getsignal(signal.SIGINT), original)

    def test_context_manager_installs_and_restores(self) -> None:
        original = signal.getsignal(signal.SIGINT)
        with ShutdownController() as controller:
            self.assertEqual(signal.getsignal(signal.SIGINT), controller._handle_signal)
        self.assertEqual(signal.getsignal(signal.SIGINT), original)


class DeadlineTests(unittest.TestCase):
    def _fake_clock(self, values: list[float]):

        state = {"i": 0}

        def clock() -> float:
            i = state["i"]
            if i < len(values):
                state["i"] = i + 1
            return values[min(i, len(values) - 1)]

        return clock

    def test_not_expired_before_budget(self) -> None:

        deadline = Deadline(10.0, clock=self._fake_clock([0.0, 5.0]))
        self.assertFalse(deadline.expired())
        self.assertEqual(deadline.remaining(), 5.0)

    def test_expired_after_budget(self) -> None:
        deadline = Deadline(10.0, clock=self._fake_clock([0.0, 11.0]))
        self.assertTrue(deadline.expired())

    def test_expired_exactly_at_budget(self) -> None:
        deadline = Deadline(10.0, clock=self._fake_clock([0.0, 10.0]))
        self.assertTrue(deadline.expired())

    def test_non_positive_budget_is_unlimited(self) -> None:
        deadline = Deadline(0.0, clock=self._fake_clock([0.0, 999.0]))
        self.assertTrue(deadline.unlimited)
        self.assertFalse(deadline.expired())
        self.assertIsNone(deadline.remaining())

    def test_none_budget_is_unlimited(self) -> None:
        deadline = Deadline(None, clock=self._fake_clock([0.0, 999.0]))
        self.assertTrue(deadline.unlimited)
        self.assertFalse(deadline.expired())


class RunWithTimeBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_completes_within_budget(self) -> None:
        async def work() -> str:
            await asyncio.sleep(0.0)
            return "done"

        result, timed_out = await run_with_time_budget(work(), budget=1.0)
        self.assertEqual(result, "done")
        self.assertFalse(timed_out)

    async def test_times_out_when_budget_exceeded(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(1.0)
            return "done"

        result, timed_out = await run_with_time_budget(slow(), budget=0.01)
        self.assertIsNone(result)
        self.assertTrue(timed_out)

    async def test_unlimited_budget_runs_to_completion(self) -> None:
        async def work() -> int:
            return 42

        for budget in (None, 0.0, -1.0):
            with self.subTest(budget=budget):
                result, timed_out = await run_with_time_budget(work(), budget=budget)
                self.assertEqual(result, 42)
                self.assertFalse(timed_out)


if __name__ == "__main__":
    unittest.main()
