from __future__ import annotations

import os
import random
import unittest

from src.config.proxy import (
    ENV_PROXY_VARS,
    resolve_env_proxy,
    resolve_proxy,
    resolve_system_proxy,
)

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


_PROXY_SAMPLES = (
    "http://127.0.0.1:10808",
    "https://proxy.example.com:8080",
    "http://user:pass@10.0.0.1:3128",
    "socks5://127.0.0.1:1080",
    "10.0.0.5:8888",
)


class ResolveEnvProxyTests(unittest.TestCase):
    def test_returns_none_when_no_vars_set(self) -> None:
        self.assertIsNone(resolve_env_proxy({}))

    def test_reads_https_proxy(self) -> None:
        self.assertEqual(
            resolve_env_proxy({"HTTPS_PROXY": "http://h:1"}),
            "http://h:1",
        )

    def test_https_takes_precedence_over_http(self) -> None:
        env = {"HTTPS_PROXY": "http://secure:1", "HTTP_PROXY": "http://plain:2"}
        self.assertEqual(resolve_env_proxy(env), "http://secure:1")

    def test_http_used_when_https_absent(self) -> None:
        self.assertEqual(
            resolve_env_proxy({"HTTP_PROXY": "http://plain:2"}),
            "http://plain:2",
        )

    def test_all_proxy_is_last_resort(self) -> None:
        self.assertEqual(
            resolve_env_proxy({"ALL_PROXY": "socks5://a:3"}),
            "socks5://a:3",
        )

    def test_uppercase_preferred_over_lowercase(self) -> None:
        env = {"HTTPS_PROXY": "http://upper:1", "https_proxy": "http://lower:2"}
        self.assertEqual(resolve_env_proxy(env), "http://upper:1")

    def test_lowercase_spelling_recognised(self) -> None:
        self.assertEqual(
            resolve_env_proxy({"https_proxy": "http://lower:2"}),
            "http://lower:2",
        )

    def test_whitespace_only_value_treated_as_absent(self) -> None:
        env = {"HTTPS_PROXY": "   ", "HTTP_PROXY": "http://plain:2"}
        self.assertEqual(resolve_env_proxy(env), "http://plain:2")

    def test_value_is_stripped(self) -> None:
        self.assertEqual(
            resolve_env_proxy({"HTTPS_PROXY": "  http://h:1  "}),
            "http://h:1",
        )

    def test_all_env_proxy_var_names_are_recognised(self) -> None:
        for name in ENV_PROXY_VARS:
            with self.subTest(name=name):
                self.assertEqual(
                    resolve_env_proxy({name: "http://x:1"}),
                    "http://x:1",
                )


class ResolveSystemProxyTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Non-Windows behaviour only")
    def test_returns_none_on_non_windows(self) -> None:
        self.assertIsNone(resolve_system_proxy())

    def test_never_raises(self) -> None:

        result = resolve_system_proxy()
        self.assertTrue(result is None or isinstance(result, str))


class ResolveProxyPrecedenceTests(unittest.TestCase):
    def test_env_proxy_wins_over_system(self) -> None:
        result = resolve_proxy(
            environ={"HTTPS_PROXY": "http://env:1"},
            system_proxy_lookup=lambda: "http://sys:2",
        )
        self.assertEqual(result, "http://env:1")

    def test_system_proxy_used_when_no_env(self) -> None:
        result = resolve_proxy(
            environ={},
            system_proxy_lookup=lambda: "http://sys:2",
        )
        self.assertEqual(result, "http://sys:2")

    def test_none_when_neither_present(self) -> None:
        result = resolve_proxy(
            environ={},
            system_proxy_lookup=lambda: None,
        )
        self.assertIsNone(result)

    def test_whitespace_env_falls_through_to_system(self) -> None:
        result = resolve_proxy(
            environ={"HTTPS_PROXY": "   "},
            system_proxy_lookup=lambda: "http://sys:2",
        )
        self.assertEqual(result, "http://sys:2")

    def test_system_lookup_not_called_when_env_present(self) -> None:
        calls: list[int] = []

        def lookup() -> str:
            calls.append(1)
            return "http://sys:2"

        result = resolve_proxy(
            environ={"HTTP_PROXY": "http://env:1"},
            system_proxy_lookup=lookup,
        )
        self.assertEqual(result, "http://env:1")
        self.assertEqual(calls, [])


def _expected(env_proxy: str | None, system_proxy: str | None) -> str | None:
    if env_proxy is not None:
        return env_proxy
    if system_proxy:
        return system_proxy
    return None


class ProxyPrecedenceProperty(unittest.TestCase):
    def _check(self, env_proxy: str | None, system_proxy: str | None) -> None:
        environ: dict[str, str] = {}
        if env_proxy is not None:
            environ["HTTPS_PROXY"] = env_proxy
        result = resolve_proxy(
            environ=environ,
            system_proxy_lookup=lambda: system_proxy,
        )
        self.assertEqual(result, _expected(env_proxy, system_proxy))

    def test_all_presence_combinations(self) -> None:

        for env_proxy in (None, "http://env:1"):
            for system_proxy in (None, "http://sys:2"):
                with self.subTest(env=env_proxy, system=system_proxy):
                    self._check(env_proxy, system_proxy)

    if _HAS_HYPOTHESIS:

        @settings(max_examples=300)
        @given(
            env_proxy=st.one_of(st.none(), st.sampled_from(_PROXY_SAMPLES)),
            system_proxy=st.one_of(st.none(), st.sampled_from(_PROXY_SAMPLES)),
        )
        def test_precedence_property(
            self, env_proxy: str | None, system_proxy: str | None
        ) -> None:
            self._check(env_proxy, system_proxy)

    else:  # pragma: no cover

        def test_precedence_property(self) -> None:
            rng = random.Random(20240531)
            options: list[str | None] = [None, *_PROXY_SAMPLES]
            for _ in range(300):
                env_proxy = rng.choice(options)
                system_proxy = rng.choice(options)
                with self.subTest(env=env_proxy, system=system_proxy):
                    self._check(env_proxy, system_proxy)


if __name__ == "__main__":
    unittest.main()
