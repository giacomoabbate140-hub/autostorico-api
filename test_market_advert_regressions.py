import unittest
import urllib.parse
from unittest.mock import patch

import server


class MarketAdvertRegressionTests(unittest.TestCase):
    def test_price_queries_target_advert_paths_without_changing_plate_search(self):
        captured = []
        def fake_read(request, **kwargs):
            captured.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query))
            return {"web": {"results": []}}
        with patch.object(server, "brave_search_available", return_value=True), patch.object(
            server, "read_provider_json", side_effect=fake_read):
            for brand, model in (("BMW", "Serie 1 120d"), ("Audi", "A1"),
                                 ("Mercedes", "Classe A"), ("Alfa Romeo", "Giulietta")):
                server.brave_market_search(f"{brand} {model} 2011", {},
                    {"providers": [], "marketAdvertSearch": True})
            server.brave_market_search("AA123BB", {}, {"providers": []})
        for params in captured[:4]:
            rules = params["goggles"][0]
            self.assertTrue(rules.startswith("$discard\n"))
            self.assertIn("autoscout24.it/annunci/$boost=3,site=autoscout24.it", rules)
            self.assertIn("subito.it/auto/$boost=3,site=subito.it", rules)
            # /auto/ alone also matched Subito's /annunci-italia/vendita/auto/.
            self.assertNotIn("\n/auto/$boost", rules)
            self.assertEqual(params["extra_snippets"], ["true"])
        self.assertNotIn("goggles", captured[4])

    def test_rejections_are_counted_without_exposing_query_strings(self):
        diagnostics = {}
        server.listing_from_search_item({
            "title": "BMW Serie 1", "url": "https://www.autoscout24.it/lst/bmw/120?q=private",
            "snippet": "2011 158000 km 9500 EUR"},
            rejection_diagnostics=diagnostics)
        self.assertEqual(diagnostics["rejections"], {"aggregate_or_editorial": 1})
        self.assertEqual(diagnostics["rejectedSamples"], [{
            "url": "https://www.autoscout24.it/lst/bmw/120", "reason": "aggregate_or_editorial"}])

    def test_live_bmw_editorial_result_never_becomes_a_comparable(self):
        item = {
            "title": "BMW Serie 1 Coupè M.Y. 2011 - News",
            "url": "https://www.automoto.it/news/bmw-serie-1-coupe-my-2011.html",
            "snippet": "BMW Serie 1 120d 2011",
        }
        with patch.object(server, "extract_listing_page_metadata",
                          return_value={"price": 54548, "year": 2011, "km": 927}) as fetch:
            result = server.listing_from_search_item(item, payload={
                "brand": "BMW", "model": "Serie 1 120d", "year": 2011,
                "km": 158000, "fuelType": "Diesel"})
        self.assertIsNone(result)
        fetch.assert_not_called()

    def test_vehicle_information_page_never_becomes_a_comparable(self):
        item = {
            "title": "Quali sono i motori per una BMW Serie 1?",
            "url": "https://www.autohero.com/it/auto/info/bmw/serie-1/motore",
            "snippet": "BMW Serie 1 120d 2011",
        }
        with patch.object(server, "extract_listing_page_metadata",
                          return_value={"price": 2000, "year": 2011, "km": 123}) as fetch:
            result = server.listing_from_search_item(item, payload={
                "brand": "BMW", "model": "Serie 1 120d", "year": 2011,
                "km": 158000, "fuelType": "Diesel"})
        self.assertIsNone(result)
        fetch.assert_not_called()

    def test_car_equipment_in_description_does_not_remove_real_adverts(self):
        for brand, model in (("BMW", "120d"), ("Audi", "A1"),
                             ("Mercedes", "Classe A"), ("Alfa Romeo", "Giulietta")):
            with self.subTest(brand=brand):
                item = {
                    "title": f"{brand} {model} usata",
                    "url": "https://www.subito.it/auto/auto-usata-test-661489086.htm",
                    "snippet": f"{brand} {model} diesel 2011, 158.000 km, "
                               "9.500 EUR. Cerchi in lega, pneumatici nuovi.",
                }
                result = server.listing_from_search_item(item, payload={
                    "brand": brand, "model": model, "year": 2011, "km": 158000,
                    "fuelType": "Diesel"})
                self.assertIsNotNone(result)
                self.assertEqual(result["price"], 9500)
                self.assertEqual(result["km"], 158000)
                self.assertEqual(result["comparisonTier"], "direct")

    def test_equipment_in_title_still_rejects_parts_advert(self):
        for title in ("Cerchi in lega BMW 120d", "Pneumatici BMW 120d"):
            with self.subTest(title=title):
                item = {
                    "title": title,
                    "url": "https://www.subito.it/auto/parti-661489086.htm",
                    "snippet": "BMW 120d 2011, 158000 km, 9500 EUR",
                }
                self.assertIsNone(server.listing_from_search_item(item, payload={
                    "brand": "BMW", "model": "120d", "year": 2011, "km": 158000}))

    def test_bmw_response_uses_advert_and_excludes_editorial_price(self):
        payload = {"brand": "BMW", "model": "Serie 1 120d", "year": 2011, "km": 158000}
        items = [
            {
                "title": "BMW Serie 1 Coupè M.Y. 2011 - News",
                "url": "https://www.automoto.it/news/bmw-serie-1-coupe-my-2011.html",
                "snippet": "BMW Serie 1 120d 2011 - 158000 km - 54548 EUR",
            },
            {
                "title": "BMW 120D automatica 8marce",
                "url": "https://www.subito.it/auto/bmw-120d-automatica-8marce-trento-661489086.htm",
                "snippet": "BMW 120d diesel 10/2011 158.000 km 9.500 EUR, cerchi in lega",
            },
        ]
        listings = [listing for item in items
                    if (listing := server.listing_from_search_item(item, payload=payload))]
        estimate, accepted = server.market_estimate_from_sources(listings, 7000, 158000, 2011)
        self.assertIsNotNone(estimate)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["price"], 9500)
        self.assertEqual(accepted[0]["source"], "Subito Auto")


if __name__ == "__main__":
    unittest.main()
