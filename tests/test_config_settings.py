"""Tests for the configuration loader (``config/settings.py``).

Covers:

* File loading and resolution (Requirements 9.1, 9.2).
* Missing-file vs unreadable/corrupt-file distinction (Requirements 9.3, 9.4).
* Merge-over-defaults and required-value exposure (Requirement 9.5).
* Property 24 (merge supplies all required keys).
* Property 25 (missing required value names the value).

YAML fixtures are written to temporary files so the loader exercises real
file I/O. Hypothesis drives the property tests when available, with a
deterministic random fallback otherwise.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from src.config.defaults import DEFAULT_CONFIG
from src.config.settings import (
    REQUIRED_VALUES,
    Config,
    ConfigMissingError,
    ConfigUnreadableError,
    ConfigValueError,
)

try:  # pragma: no cover - exercised only when hypothesis is installed
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - fallback path
    _HAS_HYPOTHESIS = False


def _write_yaml(directory: Path, name: str, content: object) -> Path:
    """Write ``content`` as YAML into ``directory/name`` and return the path."""
    path = directory / name
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(content, handle, allow_unicode=True)
    return path


class LoadFromFileTests(unittest.TestCase):
    """Loading and merging behaviour from real YAML files."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_loads_explicit_path_and_merges_over_defaults(self) -> None:
        path = _write_yaml(
            self.tmp_path,
            "config.yaml",
            {"source_key": "genshin-impact/global", "concurrency": 4},
        )
        config = Config(path)
        # User value wins.
        self.assertEqual(config.source_key, "genshin-impact/global")
        self.assertEqual(config.concurrency, 4)
        # Defaults fill the gaps.
        self.assertEqual(config.classifier, DEFAULT_CONFIG["classifier"])
        self.assertEqual(config.retry_count, DEFAULT_CONFIG["retry_count"])
        self.assertEqual(config.timeout, float(DEFAULT_CONFIG["timeout"]))

    def test_empty_file_falls_back_entirely_to_defaults(self) -> None:
        path = self.tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        config = Config(path)
        self.assertEqual(config.source_key, DEFAULT_CONFIG["source_key"])
        self.assertEqual(config.classifier, DEFAULT_CONFIG["classifier"])
        self.assertEqual(config.concurrency, DEFAULT_CONFIG["concurrency"])

    def test_output_dir_is_path(self) -> None:
        path = _write_yaml(self.tmp_path, "c.yaml", {"output_dir": "out/videos"})
        config = Config(path)
        self.assertEqual(config.output_dir, Path("out/videos"))

    def test_rules_returned_from_config(self) -> None:
        rules = [{"category": "videos/pv", "keywords": ["PV"]}]
        path = _write_yaml(self.tmp_path, "c.yaml", {"rules": rules})
        config = Config(path)
        self.assertEqual(config.rules, rules)

    def test_nested_mapping_merge_is_recursive(self) -> None:
        path = _write_yaml(
            self.tmp_path,
            "c.yaml",
            {"extra": {"a": 1}},
        )
        config = Config(path, defaults={**DEFAULT_CONFIG, "extra": {"a": 0, "b": 2}})
        self.assertEqual(config.get("extra"), {"a": 1, "b": 2})


class MissingFileTests(unittest.TestCase):
    """Requirement 9.3: a missing file raises ConfigMissingError."""

    def test_missing_explicit_path_raises_missing_error(self) -> None:
        missing = Path(tempfile.gettempdir()) / "definitely-not-here-12345.yaml"
        if missing.exists():  # pragma: no cover - defensive
            missing.unlink()
        with self.assertRaises(ConfigMissingError) as ctx:
            Config(missing)
        # Message names the path.
        self.assertIn(str(missing), str(ctx.exception))

    def test_missing_is_not_unreadable(self) -> None:
        missing = Path(tempfile.gettempdir()) / "definitely-not-here-67890.yaml"
        if missing.exists():  # pragma: no cover - defensive
            missing.unlink()
        # The two error types are distinct (Requirement 9.4).
        self.assertFalse(issubclass(ConfigMissingError, ConfigUnreadableError))
        self.assertFalse(issubclass(ConfigUnreadableError, ConfigMissingError))
        with self.assertRaises(ConfigMissingError):
            Config(missing)


class UnreadableFileTests(unittest.TestCase):
    """Requirement 9.4: an existing but unreadable/corrupt file is distinct."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_corrupt_yaml_raises_unreadable_error(self) -> None:
        path = self.tmp_path / "corrupt.yaml"
        # Invalid YAML (unterminated flow mapping / bad indentation).
        path.write_text("source_key: [unclosed\n  : : :", encoding="utf-8")
        with self.assertRaises(ConfigUnreadableError) as ctx:
            Config(path)
        self.assertIn(str(path), str(ctx.exception))
        self.assertIsNotNone(ctx.exception.cause)

    def test_non_mapping_root_raises_unreadable_error(self) -> None:
        path = _write_yaml(self.tmp_path, "list.yaml", [1, 2, 3])
        with self.assertRaises(ConfigUnreadableError):
            Config(path)

    def test_unreadable_error_chains_cause(self) -> None:
        path = self.tmp_path / "bad.yaml"
        path.write_text(":\n  - : :", encoding="utf-8")
        try:
            Config(path)
        except ConfigUnreadableError as exc:
            self.assertIsNotNone(exc.__cause__)
        else:  # pragma: no cover
            self.fail("expected ConfigUnreadableError")


class RequiredValueTests(unittest.TestCase):
    """Requirement 9.9 / Property 25 example cases."""

    def test_missing_required_value_names_it(self) -> None:
        # Empty defaults + mapping missing 'timeout' -> accessing it raises.
        config = Config.from_mapping(
            {
                "source_key": "g/r",
                "classifier": "rule_based",
                "output_dir": "out",
                "concurrency": 1,
                "retry_count": 0,
            },
            defaults={},
        )
        with self.assertRaises(ConfigValueError) as ctx:
            _ = config.timeout
        self.assertIn("timeout", str(ctx.exception))
        self.assertEqual(ctx.exception.name, "timeout")

    def test_explicit_none_is_treated_as_missing(self) -> None:
        config = Config.from_mapping({"source_key": None}, defaults={})
        with self.assertRaises(ConfigValueError) as ctx:
            _ = config.source_key
        self.assertIn("source_key", str(ctx.exception))

    def test_all_required_values_available_from_defaults(self) -> None:
        config = Config.from_mapping({})
        # None of these should raise.
        self.assertIsInstance(config.source_key, str)
        self.assertIsInstance(config.classifier, str)
        self.assertIsInstance(config.output_dir, Path)
        self.assertIsInstance(config.concurrency, int)
        self.assertIsInstance(config.retry_count, int)
        self.assertIsInstance(config.timeout, float)

    def test_zero_retry_count_is_valid(self) -> None:
        # Requirement 14.6: zero retries is a valid value, not "missing".
        config = Config.from_mapping({"retry_count": 0})
        self.assertEqual(config.retry_count, 0)


class Property24MergeSuppliesAllRequiredKeys(unittest.TestCase):
    """Property 24: Config merge supplies all required keys.

    *For any* partial user configuration, the merged Config exposes every
    required value (Source_Key, classifier, output directory, concurrency,
    retry count, timeout), with built-in defaults filling any gaps.

    **Validates: Requirements 9.5**
    """

    def _assert_property(self, partial: dict[str, object]) -> None:
        config = Config.from_mapping(partial)
        # Every required value resolves without raising.
        accessors = {
            "source_key": lambda: config.source_key,
            "classifier": lambda: config.classifier,
            "output_dir": lambda: config.output_dir,
            "concurrency": lambda: config.concurrency,
            "retry_count": lambda: config.retry_count,
            "timeout": lambda: config.timeout,
        }
        for name in REQUIRED_VALUES:
            value = accessors[name]()
            self.assertIsNotNone(value)
        # User-provided required values win over defaults.
        if "concurrency" in partial:
            self.assertEqual(config.concurrency, int(partial["concurrency"]))  # type: ignore[call-overload]
        if "source_key" in partial:
            self.assertEqual(config.source_key, str(partial["source_key"]))

    if _HAS_HYPOTHESIS:

        @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
        @given(
            st.fixed_dictionaries(
                {},
                optional={
                    "source_key": st.text(min_size=1, max_size=20).filter(
                        lambda s: s.strip() != ""
                    ),
                    "classifier": st.sampled_from(["rule_based", "custom"]),
                    "output_dir": st.text(min_size=1, max_size=20).filter(
                        lambda s: s.strip() != ""
                    ),
                    "concurrency": st.integers(min_value=1, max_value=64),
                    "retry_count": st.integers(min_value=0, max_value=10),
                    "timeout": st.integers(min_value=1, max_value=600),
                },
            )
        )
        def test_property_hypothesis(self, partial: dict[str, object]) -> None:
            self._assert_property(partial)

    else:  # pragma: no cover - fallback path

        def test_property_random_fallback(self) -> None:
            import random

            rng = random.Random(20240612)
            keys = list(REQUIRED_VALUES)
            for _ in range(500):
                partial: dict[str, object] = {}
                for key in keys:
                    if rng.random() < 0.5:
                        continue
                    if key in ("concurrency",):
                        partial[key] = rng.randint(1, 64)
                    elif key == "retry_count":
                        partial[key] = rng.randint(0, 10)
                    elif key == "timeout":
                        partial[key] = rng.randint(1, 600)
                    else:
                        partial[key] = f"val{rng.randint(0, 999)}"
                self._assert_property(partial)


class Property25MissingValueNamesIt(unittest.TestCase):
    """Property 25: missing required value names the value.

    *For any* required configuration value that cannot be provided (no user
    value and no default), the Config raises an error whose message names the
    missing value.

    **Validates: Requirements 9.9**
    """

    def _assert_property(self, present_keys: frozenset[str]) -> None:
        # Build a user mapping that supplies exactly `present_keys` and use
        # empty defaults so any absent required key is genuinely unprovidable.
        sample_values = {
            "source_key": "game/region",
            "classifier": "rule_based",
            "output_dir": "out",
            "concurrency": 2,
            "retry_count": 1,
            "timeout": 30,
        }
        mapping = {k: sample_values[k] for k in present_keys}
        config = Config.from_mapping(mapping, defaults={})

        accessors = {
            "source_key": lambda: config.source_key,
            "classifier": lambda: config.classifier,
            "output_dir": lambda: config.output_dir,
            "concurrency": lambda: config.concurrency,
            "retry_count": lambda: config.retry_count,
            "timeout": lambda: config.timeout,
        }
        for name in REQUIRED_VALUES:
            if name in present_keys:
                # Provided -> resolves fine.
                self.assertIsNotNone(accessors[name]())
            else:
                # Missing -> raises an error naming the value.
                with self.assertRaises(ConfigValueError) as ctx:
                    accessors[name]()
                self.assertIn(name, str(ctx.exception))
                self.assertEqual(ctx.exception.name, name)

    if _HAS_HYPOTHESIS:

        @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
        @given(st.sets(st.sampled_from(list(REQUIRED_VALUES))).map(frozenset))
        def test_property_hypothesis(self, present_keys: frozenset[str]) -> None:
            self._assert_property(present_keys)

    else:  # pragma: no cover - fallback path

        def test_property_random_fallback(self) -> None:
            import itertools
            import random

            rng = random.Random(20240613)
            names = list(REQUIRED_VALUES)
            # Exhaustively cover all subsets (2**6 = 64) plus random repeats.
            for r in range(len(names) + 1):
                for combo in itertools.combinations(names, r):
                    self._assert_property(frozenset(combo))
            for _ in range(100):
                size = rng.randint(0, len(names))
                self._assert_property(frozenset(rng.sample(names, size)))


if __name__ == "__main__":
    unittest.main()
