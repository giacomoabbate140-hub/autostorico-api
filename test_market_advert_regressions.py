import unittest
from unittest.mock import patch

import server


class MarketAdvertRegressionTests(unittest.TestCase):
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
