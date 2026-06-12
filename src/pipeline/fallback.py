from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..browser.driver import MODE_HEADED, MODE_HEADLESS

__all__ = [
    "FallbackDecision",
    "AttemptFailure",
    "decide_fetch_modes",
    "aggregate_failure_reasons",
    "build_failure_report",
]


@dataclass(frozen=True)
class FallbackDecision:
    should_attempt_headed: bool
    reason: str


@dataclass(frozen=True)
class AttemptFailure:
    mode: str
    reason: str


def decide_fetch_modes(selected_mode: str, fallback_enabled: bool) -> list[str]:
    if selected_mode == MODE_HEADED:
        return [MODE_HEADED]

    if fallback_enabled:
        return [MODE_HEADLESS, MODE_HEADED]
    return [MODE_HEADLESS]


def aggregate_failure_reasons(attempts: Iterable[AttemptFailure]) -> str:
    attempt_list = list(attempts)
    if not attempt_list:
        raise ValueError(
            "aggregate_failure_reasons requires at least one failed attempt"
        )
    segments = [f"{a.mode}: {a.reason}" for a in attempt_list]
    return "All fetch attempts failed -> " + "; ".join(segments)


def build_failure_report(attempts: Iterable[AttemptFailure]) -> str:
    return aggregate_failure_reasons(attempts)
