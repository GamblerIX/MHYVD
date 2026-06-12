from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import strategies as st

from src.models import NewsItem, SourceMetadata
from src.registry import RegistryKeyError
from src.sources.base import SourceAdapter
from src.sources.registry import SourceRegistry, UnknownSourceKeyError


def _make_adapter_class(source_key: str) -> type[SourceAdapter]:

    game, _, region = source_key.partition("/")

    class _Adapter(SourceAdapter):
        key = source_key
        instances: list[_Adapter] = []
        metadata = SourceMetadata(
            source_key=source_key,
            game=game or source_key,
            region=region or "",
            base_url="https://example.test",
        )

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            type(self).instances.append(self)

        async def fetch_news(self, driver: object) -> list[NewsItem]:
            return []

    return _Adapter


class _RecordingAdapter(SourceAdapter):
    metadata = SourceMetadata(
        source_key="honkai-star-rail/cn",
        game="honkai-star-rail",
        region="cn",
        base_url="https://sr.mihoyo.com",
    )

    async def fetch_news(self, driver: object) -> list[NewsItem]:
        return []


class _NeverConstructedAdapter(SourceAdapter):
    constructed = False
    metadata = SourceMetadata(
        source_key="g/r", game="g", region="r", base_url="https://x"
    )

    def __init__(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        type(self).constructed = True
        raise AssertionError("adapter must not be constructed")

    async def fetch_news(self, driver: object) -> list[NewsItem]:  # pragma: no cover
        return []


class SourceRegistryBasicsTest(unittest.TestCase):
    def test_register_and_is_registered(self) -> None:
        registry = SourceRegistry()
        self.assertFalse(registry.is_registered("honkai-star-rail/cn"))
        registry.register("honkai-star-rail/cn", _RecordingAdapter)
        self.assertTrue(registry.is_registered("honkai-star-rail/cn"))

    def test_list_keys_in_registration_order(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "honkai-star-rail/cn", _make_adapter_class("honkai-star-rail/cn")
        )
        registry.register("genshin-impact/cn", _make_adapter_class("genshin-impact/cn"))
        registry.register(
            "genshin-impact/global", _make_adapter_class("genshin-impact/global")
        )
        self.assertEqual(
            registry.list_keys(),
            ["honkai-star-rail/cn", "genshin-impact/cn", "genshin-impact/global"],
        )

    def test_create_returns_instance_of_registered_class(self) -> None:
        registry = SourceRegistry()
        registry.register("honkai-star-rail/cn", _RecordingAdapter)
        adapter = registry.create(
            "honkai-star-rail/cn", base_url="https://sr.mihoyo.com"
        )
        self.assertIsInstance(adapter, _RecordingAdapter)
        self.assertEqual(adapter.base_url, "https://sr.mihoyo.com")

    def test_create_forwards_kwargs(self) -> None:
        registry = SourceRegistry()
        registry.register("honkai-star-rail/cn", _RecordingAdapter)
        adapter = registry.create(
            "honkai-star-rail/cn",
            base_url="https://sr.mihoyo.com",
            resume=True,
            max_interactions=7,
        )
        self.assertTrue(adapter.resume)
        self.assertEqual(adapter.max_interactions, 7)

    def test_re_register_overwrites(self) -> None:
        registry = SourceRegistry()
        first = _make_adapter_class("honkai-star-rail/cn")
        second = _make_adapter_class("honkai-star-rail/cn")
        registry.register("honkai-star-rail/cn", first)
        registry.register("honkai-star-rail/cn", second)
        adapter = registry.create(
            "honkai-star-rail/cn", base_url="https://sr.mihoyo.com"
        )
        self.assertIsInstance(adapter, second)
        self.assertEqual(registry.list_keys(), ["honkai-star-rail/cn"])

    def test_create_unknown_key_raises_naming_key(self) -> None:
        registry = SourceRegistry()
        with self.assertRaises(UnknownSourceKeyError) as ctx:
            registry.create("genshin-impact/global", base_url="https://x")
        self.assertIn("genshin-impact/global", str(ctx.exception))
        self.assertEqual(ctx.exception.source_key, "genshin-impact/global")
        self.assertEqual(ctx.exception.name, "genshin-impact/global")

    def test_unknown_key_error_is_registry_key_error_and_key_error(self) -> None:
        registry = SourceRegistry()
        with self.assertRaises(RegistryKeyError):
            registry.create("absent/key", base_url="https://x")
        with self.assertRaises(KeyError):
            registry.create("absent/key", base_url="https://x")

    def test_create_absent_key_does_not_construct_any_adapter(self) -> None:
        registry = SourceRegistry()

        registry.register("registered/key", _NeverConstructedAdapter)
        _NeverConstructedAdapter.constructed = False
        with self.assertRaises(UnknownSourceKeyError):
            registry.create("absent/key", base_url="https://x")
        self.assertFalse(_NeverConstructedAdapter.constructed)


class SourceRegistryContractPropertyTest(unittest.TestCase):
    _keys = st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-_/",
        ),
        min_size=1,
    )

    @given(
        keys=st.lists(_keys, max_size=20, unique=True),
        absent=_keys,
    )
    def test_registry_contract(self, keys: list[str], absent: str) -> None:
        registry = SourceRegistry()
        classes: dict[str, type[SourceAdapter]] = {}
        for key in keys:
            cls = _make_adapter_class(key)
            classes[key] = cls
            registry.register(key, cls)

        self.assertEqual(set(registry.list_keys()), set(keys))
        for key in keys:
            self.assertTrue(registry.is_registered(key))

            adapter = registry.create(key, base_url="https://example.test")
            self.assertIsInstance(adapter, classes[key])
            self.assertIs(type(adapter), classes[key])

        if absent not in classes:
            self.assertFalse(registry.is_registered(absent))
            instances_before = {k: len(c.instances) for k, c in classes.items()}  # type: ignore[attr-defined]
            with self.assertRaises(UnknownSourceKeyError) as ctx:
                registry.create(absent, base_url="https://example.test")
            self.assertIn(absent, str(ctx.exception))
            instances_after = {k: len(c.instances) for k, c in classes.items()}  # type: ignore[attr-defined]
            self.assertEqual(instances_before, instances_after)


if __name__ == "__main__":
    unittest.main()
