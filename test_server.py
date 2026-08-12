import unittest
from unittest.mock import patch

import server
from server import (
    catalog_update_status,
    defect_research_cache_key,
    market_cache_key,
    market_estimate_from_sources,
    trusted_defect_source,
    verify_defect_online_entitlement,
    verify_google_play_subscription,
    developer_device_is_authorized,
    vehicle_defect_reports,
)


class MarketEvidenceTests(unittest.TestCase):
    def test_developer_device_authorization_only_accepts_render_hash(self):
        owner_hash = "a" * 64
        with patch.object(server, "DEVELOPER_DEVICE_ID_HASH", owner_hash):
            self.assertTrue(developer_device_is_authorized(owner_hash))
            self.assertFalse(developer_device_is_authorized("b" * 64))
            self.assertFalse(developer_device_is_authorized("not-a-hash"))

    def test_catalog_update_status_exposes_safe_update_metadata(self):
        status = catalog_update_status()

        self.assertGreater(status["catalogVersion"], 0)
        self.assertIn("updatedAt", status)
        self.assertIn("latestUpdate", status)
        self.assertIsInstance(status["latestUpdate"]["vehicles"], list)

    def test_gold_subscription_uses_google_play_subscriptions_endpoint(self):
        class FakeCredentials:
            pass

        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
                    "lineItems": [
                        {
                            "productId": "premium_gold_6_mesi",
                            "expiryTime": "2099-12-31T00:00:00Z",
                        }
                    ],
                }

        class FakeSession:
            last_endpoint = ""

            def __init__(self, credentials):
                self.credentials = credentials

            def get(self, endpoint, timeout):
                FakeSession.last_endpoint = endpoint
                return FakeResponse()

        class FakeServiceAccount:
            class Credentials:
                @staticmethod
                def from_service_account_info(info, scopes):
                    return FakeCredentials()

        with patch.object(server, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "{}"), patch.object(
            server, "AuthorizedSession", FakeSession
        ), patch.object(server, "service_account", FakeServiceAccount):
            result = verify_google_play_subscription(
                "token-123456789", "premium_gold_6_mesi"
            )

        self.assertTrue(result["active"])
        self.assertIn("/purchases/subscriptionsv2/tokens/", FakeSession.last_endpoint)

    def test_defect_online_entitlement_requires_both_premium_and_gold(self):
        payload = {
            "premiumPurchaseToken": "premium-token-123",
            "defectsGoldPurchaseToken": "gold-token-123",
        }
        calls = []

        def fake_subscription(token, product_id):
            calls.append((token, product_id))
            return {"active": True}

        with patch.object(server, "DEFECT_ENTITLEMENT_CACHE", {}), patch.object(
            server, "verify_google_play_subscription", fake_subscription
        ):
            entitlement = verify_defect_online_entitlement(payload)

        self.assertTrue(entitlement["ok"])
        self.assertEqual(
            calls,
            [
                ("premium-token-123", "premium_6_mesi"),
                ("gold-token-123", "premium_gold_6_mesi"),
            ],
        )

    def test_defect_online_entitlement_rejects_missing_tokens(self):
        entitlement = verify_defect_online_entitlement({})

        self.assertFalse(entitlement["ok"])
        self.assertEqual(entitlement["status"], 402)

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
        first_series = vehicle_defect_reports("Audi", "A1", 2011, "diesel 1598 cc CAYB")
        second_series = vehicle_defect_reports("Audi", "A1", 2021, "benzina 999 cc")

        self.assertEqual(
            [report["id"] for report in first_series["reports"]],
            [
                "audi-a1-injector-idle-knock-community",
                "audi-a1-cayb-injector-community",
                "audi-a1-cayb-egr-community",
                "audi-a1-cayb-dpf-pressure-sensor-community",
                "audi-a1-cayb-turbo-hoses-community",
            ],
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
        golf_mk7 = vehicle_defect_reports("Volkswagen", "Golf", 2017, "diesel 1968 cc")
        golf_mk8 = vehicle_defect_reports("Volkswagen", "Golf", 2022, "diesel 1968 cc")

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

    def test_dacia_diesel_injection_community_report_is_limited_by_year_and_engine(self):
        matching = vehicle_defect_reports("Dacia", "Duster", 2015, "diesel 1461 cc")
        different_engine = vehicle_defect_reports("Dacia", "Duster", 2015, "benzina 1598 cc")
        newer_vehicle = vehicle_defect_reports("Dacia", "Duster", 2021, "diesel 1461 cc")

        self.assertIn(
            "dacia-15-dci-delphi-metal-contamination-community",
            {report["id"] for report in matching["reports"]},
        )
        self.assertNotIn(
            "dacia-15-dci-delphi-metal-contamination-community",
            {report["id"] for report in different_engine["reports"]},
        )
        self.assertNotIn(
            "dacia-15-dci-delphi-metal-contamination-community",
            {report["id"] for report in newer_vehicle["reports"]},
        )

    def test_stelvio_and_tonale_community_profiles_are_available(self):
        stelvio = vehicle_defect_reports("Alfa Romeo", "Stelvio", 2020, "diesel 2143 cc")
        tonale = vehicle_defect_reports("Alfa Romeo", "Tonale", 2023, "ibrida")

        self.assertEqual(len(stelvio["reports"]), 1)
        self.assertEqual(len(tonale["reports"]), 1)

    def test_giulietta_and_tipo_include_community_trim_and_wiper_reports(self):
        giulietta = vehicle_defect_reports("Alfa Romeo", "Giulietta", 2016)
        tipo = vehicle_defect_reports("Fiat", "Tipo", 2020)

        for result in [giulietta, tipo]:
            report_ids = {report["id"] for report in result["reports"]}
            self.assertTrue(any("trim-chrome" in report_id for report_id in report_ids))
            self.assertTrue(any("headliner" in report_id for report_id in report_ids))
            self.assertTrue(any("gear-knob" in report_id for report_id in report_ids))
            self.assertTrue(any("wiper-wiring" in report_id for report_id in report_ids))

    def test_three_cylinder_reports_are_scoped_to_the_right_engine_and_year(self):
        dacia = vehicle_defect_reports("Dacia", "Sandero", 2014, "benzina 898 cc TCe")
        ford = vehicle_defect_reports("Ford", "Fiesta", 2018, "benzina 999 cc EcoBoost")
        newer_ford = vehicle_defect_reports("Ford", "Fiesta", 2021, "benzina 999 cc EcoBoost")
        seat = vehicle_defect_reports("SEAT", "Ibiza", 2020, "benzina 999 cc TSI")
        seat_mpi = vehicle_defect_reports("SEAT", "Ibiza", 2020, "benzina 999 cc MPI")

        self.assertIn("dacia-09-tce-timing-chain-community", {report["id"] for report in dacia["reports"]})
        self.assertIn("ford-10-ecoboost-wet-belt-community", {report["id"] for report in ford["reports"]})
        self.assertNotIn("ford-10-ecoboost-wet-belt-community", {report["id"] for report in newer_ford["reports"]})
        self.assertIn("seat-10-tsi-turbo-cooling-community", {report["id"] for report in seat["reports"]})
        self.assertNotIn("seat-10-tsi-turbo-cooling-community", {report["id"] for report in seat_mpi["reports"]})

    def test_evoque_ingenium_reports_distinguish_diesel_and_petrol(self):
        diesel = vehicle_defect_reports("Land Rover", "Evoque", 2017, "diesel 1999 cc TD4")
        petrol = vehicle_defect_reports("Land Rover", "Range Rover Evoque", 2021, "benzina 1997 cc P250")

        diesel_ids = {report["id"] for report in diesel["reports"]}
        petrol_ids = {report["id"] for report in petrol["reports"]}
        self.assertIn("land-rover-evoque-20-ingenium-diesel-oil-dilution-community", diesel_ids)
        self.assertNotIn("land-rover-evoque-20-ingenium-petrol-cooling-community", diesel_ids)
        self.assertIn("land-rover-evoque-20-ingenium-petrol-cooling-community", petrol_ids)
        self.assertNotIn("land-rover-evoque-20-ingenium-diesel-oil-dilution-community", petrol_ids)

    def test_evoque_22_diesel_matches_range_rover_marque_alias(self):
        result = vehicle_defect_reports(
            "Range Rover",
            "Evoque",
            2013,
            "diesel 2179 cc 2.2 TD4",
        )

        self.assertIsNotNone(result)
        report_ids = {report["id"] for report in result["reports"]}
        self.assertIn("land-rover-evoque-22-diesel-dpf-egr-community", report_ids)
        self.assertIn("land-rover-evoque-22-diesel-awd-electronics-community", report_ids)

    def test_evoque_22_diesel_matches_ocr_epoque_alias(self):
        result = vehicle_defect_reports(
            "Range Rover",
            "Epoque",
            2013,
            "diesel 2179 cc 2.2 TD4",
        )

        self.assertIsNotNone(result)
        self.assertEqual(4, len(result["reports"]))

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
        self.assertEqual(
            trusted_defect_source("https://forum-auto.caradisiac.com/topic/defaut-moteur"),
            ("Forum Auto Caradisiac", "community_candidate"),
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
