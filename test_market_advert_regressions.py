import unittest
import urllib.parse
from unittest.mock import patch

import server


class MarketAdvertRegressionTests(unittest.TestCase):
    def test_aliases_keep_generations_and_trim_only_names_specific(self):
        for brand, model, wanted, forbidden in (
            ("BMW", "Serie 1 120d", "BMW 120d", "BMW 1"),
            ("Mercedes", "Classe A A180", "Mercedes A180", "Mercedes A"),
            ("Audi", "Audi A1", "Audi A1", "Audi Audi A1"),
            ("Volkswagen", "Golf 7", "Volkswagen Golf 7", '"Volkswagen Golf"'),
            ("BMW", "Serie 1 M Sport", "BMW Serie 1 M Sport", '"BMW M Sport"'),
            ("Alfa Romeo", "Giulietta", "Alfa Romeo Giulietta", "Alfa Giulietta"),
        ):
            with self.subTest(model=model):
                query = server.market_vehicle_search_expression(brand, model)
                self.assertIn(wanted, query)
                self.assertNotIn('"' + forbidden + '"' if '"' not in forbidden else forbidden, query)

    def test_market_url_validates_hostname_not_brand_in_path_or_query(self):
        for url in ("https://autoscout24.it.evil.test/annunci/car",
                    "https://evil.test/?site=subito.it",
                    "https://subito.it@evil.test/auto/car.htm",
                    "ftp://subito.it/auto/car.htm",
                    "https://subito.it:9000/auto/car.htm",
                    "https://[invalid/auto/subito.it"):
            with self.subTest(url=url):
                self.assertFalse(server.is_market_url(url))
        self.assertTrue(server.is_market_url("https://www.autoscout24.it/annunci/car"))
        self.assertTrue(server.is_market_url("https://auto.trovit.it/annunci/123456-car"))
        url = "https://www.autouncle.it/it/d/123456-car?source=subito.it"
        self.assertEqual(server.market_source_name(url), "AutoUncle")
        self.assertEqual(server.source_weight(url), 0.65)

    def test_tracking_links_do_not_count_as_multiple_comparables(self):
        self.assertNotEqual(
            server.market_listing_dedupe_key("https://www.autohero.com/it/car?id=1"),
            server.market_listing_dedupe_key("https://www.autohero.com/it/car?id=2"))
        def advert(url):
            return {"url": url, "price": 9500, "year": 2011,
                    "km": 158000, "matchScore": 1, "source": "Subito"}
        first = "https://www.subito.it/auto/bmw-120d-661489086.htm?utm_source=brave"
        second = "https://subito.it/auto/bmw-120d-661489086.htm?utm_source=tavily#details"
        with patch.object(server, "brave_search_available", return_value=True), patch.object(
            server, "tavily_market_search_available", return_value=True), patch.object(
            server, "TAVILY_ENABLED", True), patch.object(server, "TAVILY_API_KEY", "test"), patch.object(
            server, "brave_market_search", side_effect=[[advert(first)], []]), patch.object(
            server, "tavily_market_search", return_value=[advert(second)]):
            listings, _ = server.fetch_market_sources({"brand": "BMW", "model": "120d"}, 2011)
        self.assertEqual(len(listings), 1)

    def test_raw_primary_content_recovers_mileage_without_an_extra_page_request(self):
        payload = {"brand": "BMW", "model": "Serie 1 120d", "year": 2011, "km": 158000}
        raw = ("Navigation\n# Usata 2011 BMW 120d\n"
               "* Anno 2011\n* Km: **158.000**\nDiesel\n9500 EUR\n"
               "## Auto simili\nBMW 120d 2025 30000 km 29000 EUR")
        item = {"title": "BMW 120d usata", "url": "https://www.autouncle.it/it/d/123456-car",
                "content": "BMW 120d 2011 9500 EUR", "raw_content": raw}
        with patch.object(server, "tavily_market_search_available", return_value=True), patch.object(
            server, "read_provider_json", return_value={"results": [item]}), patch.object(
            server, "extract_listing_page_metadata") as page:
            listings = server.tavily_market_search("BMW 120d 2011", payload)
        page.assert_not_called()
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["km"], 158000)
        self.assertEqual(listings[0]["year"], 2011)
        self.assertEqual(listings[0]["metadataSource"], "provider_page")

    def test_raw_primary_mileage_cannot_be_replaced_by_a_closer_recommendation(self):
        item = {"title": "BMW 120d usata", "url": "https://www.autouncle.it/it/d/123456-car",
                "content": "BMW 120d 2011 158000 km 5500 EUR",
                "raw_content": "# BMW 120d\nAnno 2011\nKm 287.000\n5500 EUR\n"
                               "## Offerte selezionate\nBMW 120d 2011 158000 km 9500 EUR"}
        with patch.object(server, "tavily_market_search_available", return_value=True), patch.object(
            server, "read_provider_json", return_value={"results": [item]}):
            listings = server.tavily_market_search("BMW 120d 2011", {
                "brand": "BMW", "model": "120d", "year": 2011, "km": 158000})
        self.assertEqual(listings, [])

    def test_recovered_page_mileage_overrides_stale_search_mileage(self):
        item = {"title": "BMW 120d", "url": "https://www.autouncle.it/it/d/123456-car",
                "snippet": "2011 Diesel 158000 km"}
        with patch.object(server, "extract_listing_page_metadata", return_value={
            "price": 5500, "year": 2011, "km": 287000}):
            listing = server.listing_from_search_item(item, payload={
                "brand": "BMW", "model": "120d", "year": 2011, "km": 158000})
        self.assertIsNone(listing)

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
