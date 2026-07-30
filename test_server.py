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

    def test_defect_catalog_filters_audi_a1_reports_by_year_and_engine(self):
        first_series = vehicle_defect_reports("Audi", "A1", 2011, "benzina 1390 cc")
        second_series = vehicle_defect_reports("Audi", "A1", 2021, "benzina 999 cc")

        self.assertEqual(
            [report["id"] for report in first_series["reports"]],
            ["audi-a1-injector-idle-knock-community"],
        )
        self.assertEqual(
            [report["id"] for report in second_series["reports"]],
            ["audi-a1-ignition-coil-misfire-community"],
        )

    def test_defect_catalog_filters_duplicate_model_generations_by_year(self):
        a3_2009 = vehicle_defect_reports("Audi", "A3", 2009, "diesel 1968 cc")
        a3_2017 = vehicle_defect_reports("Audi", "A3", 2017, "diesel 1968 cc")

        self.assertEqual({vehicle["generation"] for vehicle in a3_2009["vehicles"]}, {"8P"})
        self.assertEqual({vehicle["generation"] for vehicle in a3_2017["vehicles"]}, {"8V"})

    def test_independent_reliability_profiles_keep_golf_generations_separate(self):
        golf_mk7 = vehicle_defect_reports("Volkswagen", "Golf", 2017)
        golf_mk8 = vehicle_defect_reports("Volkswagen", "Golf", 2022)

        self.assertEqual(
            {report["id"] for report in golf_mk7["reports"]},
            {"volkswagen-golf-mk7-dsg-electrical-independent"},
        )
        self.assertEqual(
            {report["id"] for report in golf_mk8["reports"]},
            {"volkswagen-golf-mk8-software-adblue-independent"},
        )

    def test_shared_engine_family_applies_only_to_matching_multijet(self):
        multijet = vehicle_defect_reports("Fiat", "Doblo", 2018, "diesel 1248 cc")
        different_engine = vehicle_defect_reports("Fiat", "Doblo", 2018, "diesel 1598 cc")

        self.assertIn(
            "fiat-13-multijet-oil-pump-o-ring-community",
            {report["id"] for report in multijet["reports"]},
        )
        self.assertIsNone(different_engine)

    def test_stelvio_and_tonale_community_profiles_are_available(self):
        stelvio = vehicle_defect_reports("Alfa Romeo", "Stelvio", 2020, "diesel 2143 cc")
        tonale = vehicle_defect_reports("Alfa Romeo", "Tonale", 2023, "ibrida")

        self.assertEqual(len(stelvio["reports"]), 1)
        self.assertEqual(len(tonale["reports"]), 1)

    def test_defect_catalog_returns_none_for_unknown_vehicle(self):
        self.assertIsNone(vehicle_defect_reports("Marca inesistente", "Modello inesistente"))

    def test_defect_research_only_accepts_trusted_domains(self):
        self.assertEqual(
            trusted_defect_source("https://www.peugeot.it/post-vendita"),
            ("Peugeot Italia", "manufacturer_candidate"),
        )
        self.assertEqual(
            trusted_defect_source("https://www.whatcar.com/ford/fiesta/reliability"),
            ("What Car? Reliability Survey", "independent_candidate"),
        )
        self.assertIsNone(trusted_defect_source("https://example.com/peugeot-208"))

    def test_defect_research_cache_key_is_case_insensitive(self):
        self.assertEqual(
            defect_research_cache_key("Peugeot", "208"),
            defect_research_cache_key("peugeot", " 208 "),
        )

    def test_defect_research_cache_key_changes_with_vehicle_context(self):
        self.assertNotEqual(
            defect_research_cache_key("Audi", "A1", 2011, "benzina 1390 cc"),
            defect_research_cache_key("Audi", "A1", 2021, "benzina 999 cc"),
        )


if __name__ == "__main__":
    unittest.main()
