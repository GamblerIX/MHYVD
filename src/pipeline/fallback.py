"""Pure headless->headed fallback decision policy (Requirement 4).

This module holds the *pure* branching logic for MHYVD's browser-mode fallback
so that the orchestrator in :mod:`pipeline.pipeline` stays thin and the policy
itself is exhaustively testable without launching a browser.

It answers two questions:

* **Which modes, in what order, should the Fetch_Stage attempt?**
  :func:`decide_fetch_modes` maps a *selected* mode plus a *fallback enabled*
  flag onto an ordered list of modes:

  ===================================  ==============================
  Selection                            Ordered modes
  ===================================  ==============================
  Headed explicitly selected           ``['headed']``  (Requirement 4.6)
  Headless/unspecified + fallback on    ``['headless', 'headed']`` (Req 4.1/4.2)
  Headless/unspecified + fallback off   ``['headless']``  (Requirement 4.3)
  ===================================  ==============================

  Headless always appears first whenever it appears (Requirement 4.1: headless
  is the primary path).

* **When every attempt fails, what is the combined failure report?**
  :func:`aggregate_failure_reasons` (and the convenience
  :func:`build_failure_report`) fold a non-empty sequence of per-attempt
  :class:`AttemptFailure` records into a single message that contains every
  attempt's reason (Requirement 4.5).

:class:`FallbackDecision` captures the single yes/no fallback choice (with its
reason) used when reasoning about an individual headless outcome.

Requirements: 4.1, 4.2, 4.3, 4.5, 4.6.
"""

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
    """The decision of whether to attempt a Headed_Mode fallback.

    Attributes:
        should_attempt_headed: ``True`` when a Headed_Mode fallback should be
            attempted after a Headless_Mode failure; ``False`` otherwise.
        reason: A human-readable explanation of the decision, suitable for the
            fallback log entry (Requirement 4.4) or the failure report.
    """

    should_attempt_headed: bool
    reason: str


@dataclass(frozen=True)
class AttemptFailure:
    """A single failed fetch attempt, carrying the mode and its failure reason.

    Attributes:
        mode: The browser mode the attempt ran in (e.g. ``"headless"``).
        reason: Why the attempt failed (a browser error or "zero items").
    """

    mode: str
    reason: str


def decide_fetch_modes(selected_mode: str, fallback_enabled: bool) -> list[str]:
    """Return the ordered list of browser modes the Fetch_Stage should attempt.

    The ordering encodes the fallback policy of Requirement 4:

    * **Headed explicitly selected** -> ``['headed']``: run Headed_Mode directly
      without first attempting Headless_Mode (Requirement 4.6). The
      ``fallback_enabled`` flag is irrelevant here because there is no headless
      attempt to fall back *from*.
    * **Headless/unspecified + fallback enabled** -> ``['headless', 'headed']``:
      treat Headless_Mode as primary (Requirement 4.1) and retry in Headed_Mode
      when headless fails (Requirement 4.2).
    * **Headless/unspecified + fallback disabled** -> ``['headless']``: never
      attempt a Headed_Mode fallback (Requirement 4.3).

    Headless always appears first whenever it appears.

    Args:
        selected_mode: The requested browser mode. :data:`MODE_HEADED`
            (``"headed"``) means an explicit headed selection; any other value
            (including :data:`MODE_HEADLESS` or an empty/unspecified value) is
            treated as the headless/unspecified primary path.
        fallback_enabled: Whether a Headed_Mode fallback is permitted.

    Returns:
        A new ordered list of mode strings to attempt in sequence.
    """
    if selected_mode == MODE_HEADED:
        # Explicit headed selection: go straight to headed, no headless attempt.
        return [MODE_HEADED]

    # Headless or unspecified: headless is always the primary attempt.
    if fallback_enabled:
        return [MODE_HEADLESS, MODE_HEADED]
    return [MODE_HEADLESS]


def aggregate_failure_reasons(attempts: Iterable[AttemptFailure]) -> str:
    """Combine every attempt's reason into a single failure report (Req 4.5).

    The report lists each attempt in order as ``"{mode}: {reason}"`` segments
    joined by ``"; "``. Every attempt's reason is guaranteed to appear in the
    output, so a caller (or test) can assert that no attempt was dropped.

    Args:
        attempts: A non-empty iterable of :class:`AttemptFailure` records, one
            per failed mode attempt, in attempt order.

    Returns:
        A combined, human-readable failure report containing every reason.

    Raises:
        ValueError: If ``attempts`` is empty. A failure report only makes sense
            when at least one attempt actually failed.
    """
    attempt_list = list(attempts)
    if not attempt_list:
        raise ValueError(
            "aggregate_failure_reasons requires at least one failed attempt"
        )
    segments = [f"{a.mode}: {a.reason}" for a in attempt_list]
    return "All fetch attempts failed -> " + "; ".join(segments)


def build_failure_report(attempts: Iterable[AttemptFailure]) -> str:
    """Alias for :func:`aggregate_failure_reasons` for orchestrator readability.

    Provided so the pipeline layer can call ``build_failure_report(...)`` to
    construct the Requirement 4.5 message while tests target the lower-level
    :func:`aggregate_failure_reasons` name directly. Both behave identically.
    """
    return aggregate_failure_reasons(attempts)
