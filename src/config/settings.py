from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_CONFIG, DEFAULT_CONFIG_PATH

REQUIRED_VALUES: tuple[str, ...] = (
    "source_key",
    "classifier",
    "output_dir",
    "concurrency",
    "retry_count",
    "timeout",
)


class ConfigError(Exception):
    pass


class ConfigMissingError(ConfigError):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(f"configuration file not found: {self.path}")


class ConfigUnreadableError(ConfigError):
    def __init__(self, path: str | Path, cause: BaseException) -> None:
        self.path = Path(path)
        self.cause = cause
        super().__init__(f"configuration file unreadable: {self.path} ({cause})")


class ConfigValueError(ConfigError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"missing required configuration value: {name}")


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class Config:
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
        obj = cls.__new__(cls)
        obj._defaults = copy.deepcopy(
            DEFAULT_CONFIG if defaults is None else dict(defaults)
        )
        obj.config_path = None  # type: ignore[assignment]
        obj._config = _deep_merge(obj._defaults, mapping)
        return obj

    @staticmethod
    def _load_file(path: Path) -> dict[str, Any]:
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
        value = self._config.get(name)
        if value is None:
            raise ConfigValueError(name)
        return value

    @property
    def source_key(self) -> str:
        return str(self._required("source_key"))

    @property
    def classifier(self) -> str:
        return str(self._required("classifier"))

    @property
    def output_dir(self) -> Path:
        return Path(self._required("output_dir"))

    @property
    def concurrency(self) -> int:
        return int(self._required("concurrency"))

    @property
    def retry_count(self) -> int:
        return int(self._required("retry_count"))

    @property
    def timeout(self) -> float:
        return float(self._required("timeout"))

    @property
    def rules(self) -> list[dict[str, Any]]:
        rules = self._config.get("rules")
        if rules is None:
            return []
        return list(rules)

    def upload_config(self, backend: str) -> dict[str, Any]:
        """Return the upload settings for a backend with env-var overrides.

        Environment variables win over file values so credentials can stay
        out of the YAML (e.g. in CI): MHYVD_WEBDAV_URL, MHYVD_WEBDAV_USERNAME,
        MHYVD_WEBDAV_PASSWORD, MHYVD_GDRIVE_CLIENT_SECRET,
        MHYVD_GDRIVE_TOKEN_PATH.
        """
        import os

        upload = self._config.get("upload") or {}
        section = dict(upload.get(backend) or {})
        env_overrides = {
            "webdav": {
                "url": "MHYVD_WEBDAV_URL",
                "username": "MHYVD_WEBDAV_USERNAME",
                "password": "MHYVD_WEBDAV_PASSWORD",
            },
            "gdrive": {
                "client_secret_path": "MHYVD_GDRIVE_CLIENT_SECRET",
                "token_path": "MHYVD_GDRIVE_TOKEN_PATH",
            },
        }.get(backend, {})
        for key, variable in env_overrides.items():
            value = os.environ.get(variable)
            if value:
                section[key] = value
        return section

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._config)


__all__ = [
    "Config",
    "ConfigError",
    "ConfigMissingError",
    "ConfigUnreadableError",
    "ConfigValueError",
    "REQUIRED_VALUES",
]
