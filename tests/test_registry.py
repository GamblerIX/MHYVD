"""Tests for the generic ``Registry`` helper (``src/registry.py``).

Covers registration, lookup/get, listing, and membership checks via both
example-based ``unittest`` cases and a Hypothesis property test asserting the
registry contract (every registered name is listed, reported as registered,
and resolves to its registered value; absent names raise an error naming the
key). This is the generic form of Property 1 and validates Requirement 13.5.
"""

from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import strategies as st

from src.registry import Registry, RegistryKeyError


class RegistryBasicsTest(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("int", int)
        self.assertIs(registry.get("int"), int)

    def test_lookup_is_alias_for_get(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("str", str)
        self.assertIs(registry.lookup("str"), registry.get("str"))

    def test_is_registered_and_contains(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("a", int)
        self.assertTrue(registry.is_registered("a"))
        self.assertTrue(registry.contains("a"))
        self.assertIn("a", registry)
        self.assertFalse(registry.is_registered("missing"))
        self.assertNotIn("missing", registry)

    def test_names_in_registration_order(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("c", int)
        registry.register("a", str)
        registry.register("b", float)
        self.assertEqual(registry.names(), ["c", "a", "b"])

    def test_re_register_overwrites(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("x", int)
        registry.register("x", str)
        self.assertIs(registry.get("x"), str)
        # Overwriting must not duplicate the name in the listing.
        self.assertEqual(registry.names(), ["x"])

    def test_get_missing_raises_naming_key(self) -> None:
        registry: Registry[type] = Registry()
        with self.assertRaises(RegistryKeyError) as ctx:
            registry.get("nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertEqual(ctx.exception.name, "nope")

    def test_registry_key_error_is_key_error(self) -> None:
        registry: Registry[type] = Registry()
        with self.assertRaises(KeyError):
            registry.get("absent")

    def test_len_and_iter(self) -> None:
        registry: Registry[type] = Registry()
        registry.register("a", int)
        registry.register("b", str)
        self.assertEqual(len(registry), 2)
        self.assertEqual(sorted(iter(registry)), ["a", "b"])

    def test_can_store_non_class_values(self) -> None:
        registry: Registry[int] = Registry()
        registry.register("answer", 42)
        self.assertEqual(registry.get("answer"), 42)


class RegistryContractPropertyTest(unittest.TestCase):
    """Property: the generic registry contract holds for any registrations.

    Validates: Requirements 13.5
    """

    # Registry names are identifier-like keys: Source_Keys (e.g.
    # ``honkai-star-rail/cn``) and classifier/downloader names. The generator
    # is constrained to that realistic input space (alphanumerics plus the
    # ``-``, ``_`` and ``/`` separators) rather than arbitrary text.
    _names = st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-_/",
        ),
        min_size=1,
    )

    @given(
        registrations=st.lists(
            st.tuples(_names, st.integers()),
            max_size=20,
        ),
        absent=_names,
    )
    def test_registry_contract(
        self, registrations: list[tuple[str, int]], absent: str
    ) -> None:
        registry: Registry[int] = Registry()
        for name, value in registrations:
            registry.register(name, value)

        # The effective mapping: last registration under a name wins.
        expected: dict[str, int] = {}
        for name, value in registrations:
            expected[name] = value

        # Every registered name is reported and resolves to its value.
        self.assertEqual(set(registry.names()), set(expected))
        for name, value in expected.items():
            self.assertTrue(registry.is_registered(name))
            self.assertIn(name, registry)
            self.assertEqual(registry.get(name), value)

        # An absent name is not registered and raises an error naming the key.
        if absent not in expected:
            self.assertFalse(registry.is_registered(absent))
            with self.assertRaises(RegistryKeyError) as ctx:
                registry.get(absent)
            self.assertIn(absent, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
