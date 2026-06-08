"""Configuration loader for MHYVD.

:class:`Config` loads a YAML configuration file (from an explicit path or the
default location), merges it over the built-in defaults, and exposes the values
the rest of the system needs (Requirement 9).

Failure modes are made explicit and distinguishable (design "Error Handling"):

* :class:`ConfigMissingError` — the resolved file does not exist
  (Requirement 9.3). The loader never silently substitutes defaults for a
  missing file.
* :class:`ConfigUnreadableError` — the file exists but cannot be read or
  parsed (permissions, corruption, non-mapping content). A *distinct* type so
  callers can tell it apart from a missing file (Requirement 9.4).
* :class:`ConfigValueError` — a required value has neither a user value nor a
  default; the message names the missing value (Requirement 9.9, Property 25).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_CONFIG, DEFAULT_CONFIG_PATH

#: The configuration values that must always be resolvable.
REQUIRED_VALUES: tuple[str, ...] = (
    "source_key",
    "classifier",
    "output_dir",
    "concurrency",
    "retry_count",
    "timeout",
)


class ConfigError(Exception):
    """Base class for all configuration errors."""


class ConfigMissingError(ConfigError):
    """Raised when the resolved configuration file does not exist.

    Distinct from :class:`ConfigUnreadableError`: a missing file is reported as
    missing rather than silently replaced with defaults (Requirement 9.3).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(f"configuration file not found: {self.path}")


class ConfigUnreadableError(ConfigError):
    """Raised when the configuration file exists but cannot be read/parsed.

    Covers permission errors, corruption/invalid YAML, and content that is not
    a mapping. The originating exception is preserved as ``cause`` and chained
    via ``__cause__`` (Requirement 9.4).
    """

    def __init__(self, path: str | Path, cause: BaseException) -> None:
        self.path = Path(path)
        self.cause = cause
        super().__init__(f"configuration file unreadable: {self.path} ({cause})")


class ConfigValueError(ConfigError):
    """Raised when a required configuration value cannot be provided.

    The message names the missing value so the failure is actionable
    (Requirement 9.9, Property 25).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"missing required configuration value: {name}")


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``base`` merged with ``override`` (override wins).

    Nested mappings are merged recursively; any non-mapping value in
    ``override`` replaces the corresponding value in ``base`` wholesale. The
    inputs are never mutated.
    """
    merged: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class Config:
    """Loaded-and-merged MHYVD configuration.

    Construct with an explicit ``config_path`` to load a specific file, or with
    ``None`` to load the default location (Requirements 9.1, 9.2). The loaded
    user values are merged over ``defaults`` (the built-in
    :data:`~src.config.defaults.DEFAULT_CONFIG` unless overridden), so every
    required value is satisfied as long as it has a default (Property 24).

    Use :meth:`from_mapping` to build a configuration directly from an
    in-memory mapping without touching the filesystem.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self._defaults: dict[str, Any] = copy.deepcopy(
            DEFAULT_CONFIG if defaults is None else dict(defaults)
        )
        self.config_path: Path = (
            DEFAULT_CONFIG_PATH if config_path is None else Path(config_path)
        )
        user_config = self._load_file(self.config_path)
        self._config: dict[str, Any] = _deep_merge(self._defaults, user_config)

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, Any],
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> Config:
        """Build a :class:`Config` from an in-memory mapping (no file I/O).

        Useful for tests and programmatic configuration. ``mapping`` is merged
        over ``defaults`` exactly as a loaded file would be.
        """
        obj = cls.__new__(cls)
        obj._defaults = copy.deepcopy(
            DEFAULT_CONFIG if defaults is None else dict(defaults)
        )
        obj.config_path = None  # type: ignore[assignment]
        obj._config = _deep_merge(obj._defaults, mapping)
        return obj

    @staticmethod
    def _load_file(path: Path) -> dict[str, Any]:
        """Load and parse the YAML file at ``path``.

        Raises :class:`ConfigMissingError` when the file is absent and
        :class:`ConfigUnreadableError` when it exists but cannot be read or
        parsed into a mapping. An empty file parses to an empty mapping.
        """
        if not path.exists():
            raise ConfigMissingError(path)

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
            raise ConfigUnreadableError(path, exc) from exc

        if data is None:
            return {}
        if not isinstance(data, Mapping):
            raise ConfigUnreadableError(
                path,
                TypeError(
                    f"configuration root must be a mapping, got {type(data).__name__}"
                ),
            )
        return dict(data)

    def _required(self, name: str) -> Any:
        """Return required value ``name`` or raise :class:`ConfigValueError`.

        A value is "not provided" when its key is absent or its value is
        ``None`` (after merging defaults).
        """
        value = self._config.get(name)
        if value is None:
            raise ConfigValueError(name)
        return value

    @property
    def source_key(self) -> str:
        """The selected Source_Key (e.g. ``honkai-star-rail/cn``)."""
        return str(self._required("source_key"))

    @property
    def classifier(self) -> str:
        """The selected classifier name (e.g. ``rule_based``)."""
        return str(self._required("classifier"))

    @property
    def output_dir(self) -> Path:
        """The output directory videos are written under."""
        return Path(self._required("output_dir"))

    @property
    def concurrency(self) -> int:
        """The maximum number of concurrent downloads."""
        return int(self._required("concurrency"))

    @property
    def retry_count(self) -> int:
        """The number of resolution attempts before giving up."""
        return int(self._required("retry_count"))

    @property
    def timeout(self) -> float:
        """The per-operation timeout in seconds."""
        return float(self._required("timeout"))

    @property
    def rules(self) -> list[dict[str, Any]]:
        """The classification rules as a list of ``{category, keywords}`` maps.

        Rules are optional: when neither the user config nor the defaults
        define any, an empty list is returned (the classifier then falls back
        to its own built-in defaults).
        """
        rules = self._config.get("rules")
        if rules is None:
            return []
        return list(rules)

    def get(self, key: str, default: Any = None) -> Any:
        """Return an arbitrary merged configuration value (raw, unchecked)."""
        return self._config.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        """Return a deep copy of the fully merged configuration mapping."""
        return copy.deepcopy(self._config)


__all__ = [
    "Config",
    "ConfigError",
    "ConfigMissingError",
    "ConfigUnreadableError",
    "ConfigValueError",
    "REQUIRED_VALUES",
]
