from __future__ import annotations

import random
import unittest

from src.sources.keys import (
    SOURCE_KEY_SEPARATOR,
    make_source_key,
    parse_source_key,
)


class TestMakeSourceKey(unittest.TestCase):
    def test_composes_expected_format(self) -> None:
        self.assertEqual(
            make_source_key("honkai-star-rail", "cn"),
            "honkai-star-rail/cn",
        )

    def test_uses_single_separator(self) -> None:
        key = make_source_key("genshin-impact", "global")
        self.assertEqual(key, "genshin-impact/global")
        self.assertEqual(key.count(SOURCE_KEY_SEPARATOR), 1)


class TestParseSourceKey(unittest.TestCase):
    def test_parses_expected_components(self) -> None:
        self.assertEqual(
            parse_source_key("honkai-star-rail/cn"),
            ("honkai-star-rail", "cn"),
        )

    def test_region_may_contain_separator(self) -> None:

        self.assertEqual(parse_source_key("game/a/b"), ("game", "a/b"))

    def test_missing_separator_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_source_key("no-separator-here")


class TestSourceKeyRoundTrip(unittest.TestCase):
    _GAME_ALPHABET = "abcdefghijklmnopqrstuvwxyz-0123456789星崩铁"
    _REGION_ALPHABET = "abcdefghijklmnopqrstuvwxyz-0123456789/国服"

    def _random_token(self, alphabet: str, rng: random.Random) -> str:
        length = rng.randint(1, 12)
        return "".join(rng.choice(alphabet) for _ in range(length))

    def test_round_trip_over_many_inputs(self) -> None:
        rng = random.Random(20240531)
        for _ in range(2000):
            game = self._random_token(self._GAME_ALPHABET, rng)
            region = self._random_token(self._REGION_ALPHABET, rng)

            key = make_source_key(game, region)

            with self.subTest(game=game, region=region):
                self.assertEqual(parse_source_key(key), (game, region))

                self.assertIn(game, key)
                self.assertIn(region, key)

    def test_round_trip_known_source_keys(self) -> None:
        known = [
            ("honkai-star-rail", "cn"),
            ("honkai-star-rail", "global"),
            ("genshin-impact", "cn"),
            ("genshin-impact", "global"),
        ]
        for game, region in known:
            with self.subTest(game=game, region=region):
                key = make_source_key(game, region)
                self.assertEqual(parse_source_key(key), (game, region))
                self.assertIn(game, key)
                self.assertIn(region, key)


if __name__ == "__main__":
    unittest.main()
