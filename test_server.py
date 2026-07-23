import unittest

from server import market_cache_key, market_estimate_from_sources


class MarketEvidenceTests(unittest.TestCase):
    def test_market_estimate_requires_three_comparable_listings(self):
        two_listings = [
            {"price": 8000, "weight": 1.0},
            {"price": 8200, "weight": 1.0},
        ]
        estimate, filtered = market_estimate_from_sources(two_listings, 8000)

        self.assertIsNone(estimate)
        self.assertEqual(len(filtered), 2)

    def test_market_estimate_keeps_three_comparable_listings(self):
        listings = [
            {"price": 7800, "weight": 1.0},
            {"price": 8000, "weight": 1.0},
            {"price": 8200, "weight": 1.0},
        ]
        estimate, filtered = market_estimate_from_sources(listings, 8000)

        self.assertIsNotNone(estimate)
        self.assertEqual(len(filtered), 3)

    def test_market_cache_key_does_not_include_plate_and_buckets_kilometres(self):
        first = {
            "plate": "AA000AA",
            "brand": "Opel",
            "model": "Corsa",
            "engineDisplacement": "1229",
            "km": 121100,
        }
        second = {**first, "plate": "ZZ999ZZ", "km": 124900}

        self.assertEqual(market_cache_key(first), market_cache_key(second))


if __name__ == "__main__":
    unittest.main()
