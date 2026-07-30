import unittest

from server import (
    defect_research_cache_key,
    market_cache_key,
    market_estimate_from_sources,
    trusted_defect_source,
    vehicle_defect_reports,
)


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

    def test_defect_catalog_keeps_official_and_community_sources_distinct(self):
        result = vehicle_defect_reports("Peugeot", "208")

        self.assertIsNotNone(result)
        report_types = {report["sourceType"] for report in result["reports"]}
        self.assertIn("manufacturer_support", report_types)
        self.assertIn("community_source", report_types)

    def test_defect_catalog_matches_brand_and_model_case_insensitively(self):
        result = vehicle_defect_reports("bmw", "serie 1")

        self.assertIsNotNone(result)
        self.assertEqual(result["reports"][0]["id"], "bmw-serie-1-n47-timing-chain-community")

    def test_defect_catalog_matches_model_aliases(self):
        result = vehicle_defect_reports("Fiat", "Punto")

        self.assertIsNotNone(result)
        self.assertIn("Grande Punto", {vehicle["model"] for vehicle in result["vehicles"]})

    def test_defect_catalog_returns_none_for_unknown_vehicle(self):
        self.assertIsNone(vehicle_defect_reports("Marca inesistente", "Modello inesistente"))

    def test_defect_research_only_accepts_trusted_domains(self):
        self.assertEqual(
            trusted_defect_source("https://www.peugeot.it/post-vendita"),
            ("Peugeot Italia", "manufacturer_candidate"),
        )
        self.assertIsNone(trusted_defect_source("https://example.com/peugeot-208"))

    def test_defect_research_cache_key_is_case_insensitive(self):
        self.assertEqual(
            defect_research_cache_key("Peugeot", "208"),
            defect_research_cache_key("peugeot", " 208 "),
        )


if __name__ == "__main__":
    unittest.main()
