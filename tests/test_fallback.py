"""Tests for the pure fallback decision policy (``pipeline/fallback.py``).

Covers:

* **Property 6 (fallback mode ordering)** -- ``decide_fetch_modes`` over every
  ``(selected_mode, fallback_enabled)`` combination.
  **Validates: Requirements 4.1, 4.2, 4.3, 4.6**
* **Property 7 (failure-reason aggregation)** -- ``aggregate_failure_reasons``
  over arbitrary non-empty attempt lists contains every attempt's reason.
  **Validates: Requirements 4.5**

Targeted unit/edge-case tests accompany the property tests. Hypothesis is used
when available; otherwise a deterministic random-generation fallback exercises
the same properties across many inputs.
"""

from __future__ import annotations

import dataclasses
import random
import unittest

from src.browser.driver import MODE_HEADED, MODE_HEADLESS
from src.pipeline.fallback import (
    AttemptFailure,
    FallbackDecision,
    aggregate_failure_reasons,
    build_failure_report,
    decide_fetch_modes,
)

try:  # pragma: no cover - exercised only when hypothesis is installed
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - fallback path
    _HAS_HYPOTHESIS = False


# Mode values that mean "headless/unspecified primary path" -- anything that is
# not an explicit headed selection.
_NON_HEADED_MODES = (MODE_HEADLESS, "", "headless", "auto", "default", "unspecified")


class DecideFetchModesUnitTests(unittest.TestCase):
    """Targeted examples for :func:`decide_fetch_modes` (Property 6)."""

    def test_explicit_headed_returns_headed_only_with_fallback_on(self) -> None:
        self.assertEqual(decide_fetch_modes(MODE_HEADED, True), [MODE_HEADED])

    def test_explicit_headed_returns_headed_only_with_fallback_off(self) -> None:
        # Requirement 4.6: explicit headed ignores the fallback flag.
        self.assertEqual(decide_fetch_modes(MODE_HEADED, False), [MODE_HEADED])

    def test_headless_with_fallback_returns_headless_then_headed(self) -> None:
        # Requirements 4.1/4.2.
        self.assertEqual(
            decide_fetch_modes(MODE_HEADLESS, True),
            [MODE_HEADLESS, MODE_HEADED],
        )

    def test_headless_without_fallback_returns_headless_only(self) -> None:
        # Requirement 4.3.
        self.assertEqual(decide_fetch_modes(MODE_HEADLESS, False), [MODE_HEADLESS])

    def test_unspecified_mode_treated_as_headless(self) -> None:
        self.assertEqual(
            decide_fetch_modes("", True),
            [MODE_HEADLESS, MODE_HEADED],
        )
        self.assertEqual(decide_fetch_modes("", False), [MODE_HEADLESS])

    def test_returned_list_is_fresh_each_call(self) -> None:
        first = decide_fetch_modes(MODE_HEADLESS, True)
        first.append("mutated")
        second = decide_fetch_modes(MODE_HEADLESS, True)
        self.assertEqual(second, [MODE_HEADLESS, MODE_HEADED])


class DecideFetchModesPropertyTests(unittest.TestCase):
    """Property 6: fallback mode ordering across all combinations."""

    def _check(self, selected_mode: str, fallback_enabled: bool) -> None:
        modes = decide_fetch_modes(selected_mode, fallback_enabled)

        if selected_mode == MODE_HEADED:
            # Explicit headed: headed only, regardless of fallback flag.
            self.assertEqual(modes, [MODE_HEADED])
            return

        # Headless/unspecified primary path.
        if fallback_enabled:
            self.assertEqual(modes, [MODE_HEADLESS, MODE_HEADED])
        else:
            self.assertEqual(modes, [MODE_HEADLESS])

        # Headless always appears first whenever it appears.
        self.assertIn(MODE_HEADLESS, modes)
        self.assertEqual(modes[0], MODE_HEADLESS)
        # And headed never precedes headless.
        if MODE_HEADED in modes:
            self.assertLess(modes.index(MODE_HEADLESS), modes.index(MODE_HEADED))

    def test_all_explicit_combinations(self) -> None:
        for mode in (MODE_HEADED, *_NON_HEADED_MODES):
            for fallback in (True, False):
                with self.subTest(mode=mode, fallback=fallback):
                    self._check(mode, fallback)

    if _HAS_HYPOTHESIS:

        @settings(max_examples=400)
        @given(
            selected_mode=st.sampled_from((MODE_HEADED, *_NON_HEADED_MODES))
            | st.text(),
            fallback_enabled=st.booleans(),
        )
        def test_property_mode_ordering(
            self, selected_mode: str, fallback_enabled: bool
        ) -> None:
            self._check(selected_mode, fallback_enabled)

    else:  # pragma: no cover - deterministic fallback when hypothesis absent

        def test_property_mode_ordering_random(self) -> None:
            rng = random.Random(20240601)
            pool = list((MODE_HEADED, *_NON_HEADED_MODES))
            for _ in range(2000):
                mode = rng.choice(pool + [_random_text(rng)])
                self._check(mode, rng.choice((True, False)))


class AggregateFailureReasonsUnitTests(unittest.TestCase):
    """Targeted examples for :func:`aggregate_failure_reasons` (Property 7)."""

    def test_single_attempt_reason_present(self) -> None:
        report = aggregate_failure_reasons(
            [AttemptFailure(MODE_HEADLESS, "browser crashed")]
        )
        self.assertIn("browser crashed", report)
        self.assertIn(MODE_HEADLESS, report)

    def test_both_modes_reasons_present(self) -> None:
        report = aggregate_failure_reasons(
            [
                AttemptFailure(MODE_HEADLESS, "zero items"),
                AttemptFailure(MODE_HEADED, "timeout"),
            ]
        )
        self.assertIn("zero items", report)
        self.assertIn("timeout", report)

    def test_empty_attempts_raises(self) -> None:
        with self.assertRaises(ValueError):
            aggregate_failure_reasons([])

    def test_build_failure_report_is_equivalent(self) -> None:
        attempts = [
            AttemptFailure(MODE_HEADLESS, "a"),
            AttemptFailure(MODE_HEADED, "b"),
        ]
        self.assertEqual(
            build_failure_report(attempts),
            aggregate_failure_reasons(attempts),
        )


class AggregateFailureReasonsPropertyTests(unittest.TestCase):
    """Property 7: every attempt's reason appears in the aggregated report."""

    def _check(self, attempts: list[AttemptFailure]) -> None:
        report = aggregate_failure_reasons(attempts)
        for attempt in attempts:
            self.assertIn(attempt.reason, report)

    def test_examples(self) -> None:
        self._check([AttemptFailure("m0", "r0")])
        self._check([AttemptFailure("m0", "r0"), AttemptFailure("m1", "r1")])

    if _HAS_HYPOTHESIS:

        @settings(max_examples=400)
        @given(
            attempts=st.lists(
                st.builds(
                    AttemptFailure,
                    mode=st.text(min_size=1, max_size=16),
                    reason=st.text(min_size=1, max_size=64),
                ),
                min_size=1,
                max_size=8,
            )
        )
        def test_property_all_reasons_present(
            self, attempts: list[AttemptFailure]
        ) -> None:
            self._check(attempts)

    else:  # pragma: no cover - deterministic fallback when hypothesis absent

        def test_property_all_reasons_present_random(self) -> None:
            rng = random.Random(20240602)
            for _ in range(2000):
                n = rng.randint(1, 8)
                attempts = [
                    AttemptFailure(_random_text(rng, 1), _random_text(rng, 1))
                    for _ in range(n)
                ]
                self._check(attempts)


class FallbackDecisionTests(unittest.TestCase):
    """The :class:`FallbackDecision` model is a frozen value object."""

    def test_fields_round_trip(self) -> None:
        decision = FallbackDecision(should_attempt_headed=True, reason="why")
        self.assertTrue(decision.should_attempt_headed)
        self.assertEqual(decision.reason, "why")

    def test_is_frozen(self) -> None:
        decision = FallbackDecision(should_attempt_headed=False, reason="x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.reason = "y"  # type: ignore[misc]


def _random_text(rng: random.Random, min_len: int = 0) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz -_/0123456789崩铁星"
    length = rng.randint(max(min_len, 1), 20)
    return "".join(rng.choice(alphabet) for _ in range(length))


if __name__ == "__main__":
    unittest.main()
