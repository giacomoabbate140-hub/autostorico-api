import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import server
from server import (
    build_market_queries,
    build_vin_recall_check,
    catalog_update_status,
    defect_research_cache_key,
    fetch_market_sources,
    market_cache_key,
    market_estimate_from_sources,
    plate_info_lookup,
    should_bypass_market_cache,
    trusted_defect_source,
    verify_defect_online_entitlement,
    verify_google_play_subscription,
    developer_device_is_authorized,
    vehicle_defect_reports,
)


class ConsultationPaymentTests(unittest.TestCase):
    def test_checkout_price_is_fixed_server_side_at_five_euro(self):
        captured = {}

        def create_session(**kwargs):
            captured.update(kwargs)
            return {"id": "cs_test_123", "url": "https://checkout.stripe.test/123"}

        fake_stripe = SimpleNamespace(
            api_key="",
            checkout=SimpleNamespace(Session=SimpleNamespace(create=create_session)),
        )
        payload = {
            "vehicleMake": "Fiat",
            "vehicleModel": "Panda",
            "vehicleEngine": "1.2 benzina",
            "subject": "Rumore motore",
            "body": "Il motore fa un rumore metallico a freddo.",
            "amount": 1,
        }
        with patch.object(server, "stripe", fake_stripe), patch.object(
            server, "STRIPE_SECRET_KEY", "sk_test"
        ), patch.object(server, "STRIPE_WEBHOOK_SECRET", "whsec_test"), patch.object(
            server, "SUPABASE_URL", "https://example.supabase.co"
        ), patch.object(server, "SUPABASE_SECRET_KEY", "sb_secret_test"), patch.object(
            server, "create_consultation_draft", return_value="draft-1"
        ), patch.object(server, "update_consultation_draft"):
            result = server.create_consultation_checkout(
                {"id": "user-1", "email": "user@example.test"}, payload
            )

        self.assertEqual(result["amount"], 500)
        self.assertEqual(captured["line_items"][0]["price_data"]["unit_amount"], 500)
        self.assertEqual(captured["line_items"][0]["price_data"]["currency"], "eur")
        self.assertEqual(captured["metadata"]["draft_id"], "draft-1")

    def test_developer_bypass_requires_authorized_device(self):
        payload = {
            "vehicleMake": "Fiat",
            "vehicleModel": "Panda",
            "vehicleEngine": "1.2",
            "subject": "Rumore motore",
            "body": "Il motore fa un rumore metallico a freddo.",
            "developerFree": True,
            "deviceIdHash": "a" * 64,
        }
        with patch.object(
            server, "create_consultation_draft"
        ) as create_draft, patch.object(
            server, "developer_device_is_authorized", return_value=False
        ):
            with self.assertRaises(PermissionError):
                server.create_consultation_checkout({"id": "user-1"}, payload)
        create_draft.assert_not_called()

    def test_paid_webhook_finalizes_once_through_database_rpc(self):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_123",
                    "metadata": {"draft_id": "draft-1"},
                }
            },
        }
        fake_stripe = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=lambda *_: event)
        )
        with patch.object(server, "stripe", fake_stripe), patch.object(
            server, "STRIPE_WEBHOOK_SECRET", "whsec_test"
        ), patch.object(
            server, "finalize_consultation_draft", return_value="consultation-1"
        ) as finalize:
            result = server.process_stripe_webhook(b"{}", "signature")

        self.assertEqual(result["consultationId"], "consultation-1")
        finalize.assert_called_once_with("draft-1", "cs_test_123", "pi_test_123")

    def test_unpaid_completed_webhook_does_not_open_consultation(self):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_status": "unpaid",
                    "metadata": {"draft_id": "draft-1"},
                }
            },
        }
        fake_stripe = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=lambda *_: event)
        )
        with patch.object(server, "stripe", fake_stripe), patch.object(
            server, "STRIPE_WEBHOOK_SECRET", "whsec_test"
        ), patch.object(server, "finalize_consultation_draft") as finalize:
            result = server.process_stripe_webhook(b"{}", "signature")

        self.assertTrue(result["received"])
        finalize.assert_not_called()


class MarketEvidenceTests(unittest.TestCase):
    def test_provider_secret_normalizes_render_paste_formats(self):
        self.assertEqual(
            server.normalize_provider_secret(
                "TAVILY_API_KEY='Bearer tvly-test'", "TAVILY_API_KEY"
            ),
            "tvly-test",
        )
        self.assertEqual(
            server.normalize_provider_secret('  "tvly-test"  ', "TAVILY_API_KEY"),
            "tvly-test",
        )

    def test_only_private_developer_v2_flag_bypasses_market_cache(self):
        self.assertTrue(
            should_bypass_market_cache({"developerFreshMarketCheck": True})
        )
        self.assertFalse(should_bypass_market_cache({"forceMarketSearch": True}))
        self.assertFalse(should_bypass_market_cache({}))

    def test_market_queries_are_nationwide_and_prioritize_national_portals(self):
        queries = build_market_queries(
            {
                "brand": "BMW",
                "model": "Serie 1 120d",
                "fuelType": "Diesel",
                "km": 120000,
            },
            2010,
        )

        self.assertGreaterEqual(len(queries), 2)
        self.assertIn("Italia", queries[0])
        self.assertIn("site:subito.it", queries[1])
        self.assertIn("site:autoscout24.it", queries[1])
        self.assertIn("Trovit", queries[2])
        self.assertTrue(any("Subito Auto" in query for query in queries))
        self.assertNotIn("Palermo", " ".join(queries))

    def test_market_fallback_runs_only_when_first_search_is_insufficient(self):
        payload = {"brand": "Audi", "model": "A1", "km": 100000}
        first = {
            "source": "AutoScout24",
            "url": "https://autoscout24.it/a1-one",
            "price": 9000,
            "weight": 1.0,
        }
        second = {
            "source": "Subito Auto",
            "url": "https://subito.it/a1-two",
            "price": 8800,
            "weight": 1.0,
        }
        with patch.object(server, "TAVILY_API_KEY", "tavily-key"), patch.object(
            server, "MARKET_MAX_TAVILY_QUERIES", 2
        ), patch.object(
            server, "tavily_market_search", side_effect=[[first], [second]]
        ) as tavily:
            listings, _ = fetch_market_sources(payload, 2011)

        self.assertEqual(len(listings), 2)
        self.assertEqual(tavily.call_count, 2)

    def test_market_search_uses_brave_as_market_fallback_after_tavily(self):
        payload = {"brand": "Audi", "model": "A1", "km": 100000}
        tavily_listing = {
            "source": "AutoScout24",
            "url": "https://example.test/a1",
            "price": 9000,
            "weight": 1.0,
        }
        brave_listing = {
            "source": "Subito Auto",
            "url": "https://example.test/a1-brave",
            "price": 8800,
            "weight": 1.0,
        }
        with patch.object(server, "BRAVE_SEARCH_API_KEY", "brave-key"), patch.object(
            server, "TAVILY_API_KEY", "tavily-key"
        ), patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "tavily_market_search", return_value=[tavily_listing]
        ) as tavily, patch.object(
            server, "brave_market_search", return_value=[brave_listing]
        ) as brave:
            listings, diagnostics = fetch_market_sources(payload, 2011)

        self.assertEqual(len(listings), 2)
        self.assertEqual(tavily.call_count, 1)
        self.assertEqual(brave.call_count, 1)
        self.assertTrue(diagnostics["configuredProviders"]["tavily"])
        self.assertTrue(diagnostics["configuredProviders"]["brave"])

    def test_market_search_stops_after_the_configured_nationwide_queries(self):
        payload = {"brand": "Audi", "model": "A1", "km": 100000}
        with patch.object(server, "TAVILY_API_KEY", "tavily-key"), patch.object(
            server, "MARKET_MAX_TAVILY_QUERIES", 2
        ), patch.object(server, "tavily_market_search", return_value=[]) as tavily:
            fetch_market_sources(payload, 2011)

        self.assertEqual(tavily.call_count, 2)

    def test_tavily_market_search_does_not_overconstrain_results_with_domains(self):
        class FakeResponse:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"results": []}'

        request_bodies = []

        def fake_urlopen(request, timeout):
            request_bodies.append(request.data.decode("utf-8"))
            return FakeResponse()

        with patch.object(server, "TAVILY_API_KEY", "tavily-key"), patch.object(
            server, "urllib"
        ) as urllib_mock:
            urllib_mock.request.Request.side_effect = lambda *args, **kwargs: type(
                "Request", (), {"data": kwargs.get("data")}
            )()
            urllib_mock.request.urlopen.side_effect = fake_urlopen
            server.tavily_market_search(
                "Alfa Romeo Giulietta auto usata prezzo Italia",
                {"brand": "Alfa Romeo", "model": "Giulietta"},
            )

        self.assertEqual(len(request_bodies), 1)
        request_payload = json.loads(request_bodies[0])
        self.assertNotIn("include_domains", request_payload)
        self.assertFalse(request_payload["include_answer"])
        self.assertFalse(request_payload["include_raw_content"])
        self.assertFalse(request_payload["include_images"])
        self.assertEqual(request_payload["language"], "it")

    def test_tavily_request_normalizes_bearer_prefix_from_render(self):
        captured_headers = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"results": []}'

        original_request = server.urllib.request.Request

        def capture_request(*args, **kwargs):
            request = original_request(*args, **kwargs)
            captured_headers.append(dict(request.header_items()))
            return request

        with patch.object(server, "TAVILY_API_KEY", "Bearer tvly-test"), patch.object(
            server.urllib.request, "Request", side_effect=capture_request
        ), patch.object(server.urllib.request, "urlopen", return_value=FakeResponse()):
            server.tavily_market_search(
                "Audi A1 2011 auto usata prezzo Italia",
                {"brand": "Audi", "model": "A1"},
            )

        self.assertEqual(captured_headers[0]["Authorization"], "Bearer tvly-test")

    def test_tavily_retries_once_after_a_transient_network_error(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b'{"results": []}'

        with patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "TAVILY_API_KEY", "tavily-key"
        ), patch.object(server, "TAVILY_DAILY_LIMIT", 30), patch.object(
            server, "TAVILY_DAILY_USAGE", {}
        ), patch.object(server.time, "sleep"), patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=[server.urllib.error.URLError("temporary"), FakeResponse()],
        ) as urlopen:
            results = server.tavily_market_search(
                "Audi A1 2011 auto usata prezzo Italia",
                {"brand": "Audi", "model": "A1"},
            )

        self.assertEqual(results, [])
        self.assertEqual(urlopen.call_count, 2)

    def test_brave_runs_market_search_when_tavily_is_missing(self):
        payload = {"brand": "Audi", "model": "A1", "km": 100000}
        brave_listing = {
            "source": "Subito Auto",
            "url": "https://example.test/brave-only",
            "price": 8700,
            "weight": 1.0,
        }
        with patch.object(server, "BRAVE_SEARCH_API_KEY", "brave-key"), patch.object(
            server, "TAVILY_API_KEY", ""
        ), patch.object(
            server, "brave_market_search", return_value=[brave_listing]
        ) as brave, patch.object(server, "tavily_market_search") as tavily:
            listings, diagnostics = fetch_market_sources(payload, 2011)

        self.assertEqual(len(listings), 1)
        self.assertEqual(brave.call_count, 2)
        tavily.assert_not_called()
        self.assertTrue(diagnostics["configuredProviders"]["brave"])
        self.assertFalse(diagnostics["configuredProviders"]["tavily"])

    def test_tavily_is_the_capped_market_provider(self):
        payload = {"brand": "Audi", "model": "A1", "km": 100000}
        fallback_listing = {
            "source": "Fallback",
            "url": "https://example.test/fallback",
            "price": 8500,
            "weight": 1.0,
        }
        with patch.object(server, "BRAVE_SEARCH_API_KEY", ""), patch.object(
            server, "TAVILY_API_KEY", "tavily-key"
        ), patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "TAVILY_DAILY_LIMIT", 30), patch.object(
            server, "TAVILY_DAILY_USAGE", {}
        ), patch.object(server, "tavily_market_search", return_value=[fallback_listing]) as tavily:
            listings, _ = fetch_market_sources(payload, 2011)

        self.assertEqual(len(listings), 1)
        # With a single listing the focused nationwide fallback is allowed,
        # while the daily Tavily cap still remains in force.
        self.assertEqual(tavily.call_count, 2)

    def test_plate_info_never_consumes_tavily_market_credits(self):
        with patch.object(server, "brave_search_available", return_value=False), patch.object(
            server, "tavily_market_search_available", return_value=True
        ), patch.object(server, "tavily_market_search") as tavily:
            status, payload = plate_info_lookup({"plate": ["AB123CD"]})

        self.assertEqual(status, 200)
        self.assertFalse(payload["configuredProviders"]["tavily"])
        tavily.assert_not_called()

    def test_developer_device_authorization_only_accepts_render_hash(self):
        owner_hash = "a" * 64
        with patch.object(server, "DEVELOPER_DEVICE_ID_HASH", owner_hash):
            self.assertTrue(developer_device_is_authorized(owner_hash))
            self.assertFalse(developer_device_is_authorized("b" * 64))
            self.assertFalse(developer_device_is_authorized("not-a-hash"))

    def test_gold_research_does_not_depend_on_optional_admin_token(self):
        with patch.object(server, "DEFECT_RESEARCH_ENABLED", True), patch.object(
            server, "DEFECT_RESEARCH_API_KEY", ""
        ), patch.object(server, "BRAVE_SEARCH_API_KEY", "brave-key"), patch.object(
            server, "BRAVE_DAILY_LIMIT", 40
        ), patch.object(server, "BRAVE_DAILY_USAGE", {}):
            self.assertTrue(server.defect_research_configured())

    def test_gold_response_explicitly_reports_missing_online_provider(self):
        with patch.object(server, "defect_research_configured", return_value=False):
            result = server.vehicle_defects_response(
                "Alfa Romeo", "Giulietta", 2014, "2.0 Diesel", True
            )

        self.assertTrue(result["onlineResearchUnavailable"])
        self.assertEqual(result["onlineCandidates"], [])
        self.assertIn("Render", result["onlineResearchMessage"])

    def test_public_source_url_rejects_non_clickable_or_local_values(self):
        self.assertEqual(
            server.safe_public_source_url("https://www.alfaromeo.it/richiami"),
            "https://www.alfaromeo.it/richiami",
        )
        self.assertEqual(server.safe_public_source_url("javascript:alert(1)"), "")
        self.assertEqual(server.safe_public_source_url("http://localhost/source"), "")

    def test_catalog_update_status_exposes_safe_update_metadata(self):
        status = catalog_update_status()

        self.assertGreater(status["catalogVersion"], 0)
        self.assertIn("updatedAt", status)
        self.assertIn("latestUpdate", status)
        self.assertIsInstance(status["latestUpdate"]["vehicles"], list)
        self.assertIsInstance(status["latestUpdate"]["details"], list)

    def test_catalog_update_sources_are_clickable_public_links(self):
        sources = catalog_update_status()["latestUpdate"].get("sources", [])

        self.assertTrue(sources)
        for source in sources:
            parsed = urlparse(source)
            self.assertIn(parsed.scheme, {"https", "http"})
            self.assertTrue(parsed.netloc)

    def test_research_update_exposes_the_latest_collected_batch(self):
        queue = {
            "updatedAt": "2026-08-13T11:00:00+00:00",
            "candidates": [{"status": "pending_review"}],
            "latestUpdate": {
                "id": "2026-08-13T10:59:00+00:00",
                "updatedAt": "2026-08-13T10:59:00+00:00",
                "addedCount": 2,
                "summary": "Raccolte 2 nuove fonti per Ford Puma, in revisione.",
                "details": ["Ford Italia: Campagne di richiamo"],
                "vehicles": [{"make": "Ford", "model": "Puma"}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            with patch.object(server, "DEFECT_RESEARCH_QUEUE_PATH", queue_path):
                update = server.defect_research_update_status()

        self.assertEqual(update["id"], "2026-08-13T10:59:00+00:00")
        self.assertEqual(update["addedCount"], 2)
        self.assertEqual(update["vehicles"], [{"make": "Ford", "model": "Puma"}])

    def test_research_update_prefers_newer_pending_candidates_over_stale_metadata(self):
        queue = {
            "latestUpdate": {
                "id": "old",
                "updatedAt": "2026-08-18T00:00:00+00:00",
                "summary": "Vecchio aggiornamento",
            },
            "candidates": [
                {
                    "status": "pending_review",
                    "collectedAt": "2026-08-20T10:00:00+00:00",
                    "make": "Peugeot",
                    "model": "3008",
                    "sourceUrl": "https://example.test/peugeot-3008",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            with patch.object(server, "DEFECT_RESEARCH_QUEUE_PATH", queue_path):
                update = server.defect_research_update_status()

        self.assertEqual(update["id"], "2026-08-20T10:00:00+00:00")
        self.assertEqual(update["vehicles"], [{"make": "Peugeot", "model": "3008"}])
        self.assertEqual(update["sources"], ["https://example.test/peugeot-3008"])

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
                            "productId": "goldseimesi",
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
                "token-123456789", "goldseimesi"
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
                ("gold-token-123", "goldseimesi"),
            ],
        )

    def test_defect_online_entitlement_rejects_missing_tokens(self):
        entitlement = verify_defect_online_entitlement({})

        self.assertFalse(entitlement["ok"])
        self.assertEqual(entitlement["status"], 402)

    def test_market_relevance_keeps_nationwide_listings_with_different_km(self):
        payload = {
            "brand": "BMW",
            "model": "BMW SERIE 1 120D",
            "year": 2005,
            "km": 120000,
        }
        listing_text = (
            "BMW 120d usata 2005 - 330000 km - 3500 EUR "
            "https://www.autoscout24.it/annunci/bmw-120d"
        )

        self.assertTrue(server.is_relevant_listing_text(listing_text, payload))

    def test_market_relevance_still_rejects_wrong_year_when_present(self):
        payload = {
            "brand": "BMW",
            "model": "BMW SERIE 1 120D",
            "year": 2005,
            "km": 120000,
        }
        listing_text = (
            "BMW 120d usata 2008 - 210000 km - 3500 EUR "
            "https://www.autoscout24.it/annunci/bmw-120d"
        )

        self.assertFalse(server.is_relevant_listing_text(listing_text, payload))

    def test_market_filter_rejects_explicit_wrong_fuel(self):
        item = {
            "title": "Audi A1 1.4 TFSI benzina 2011 - 6.900 EUR",
            "url": "https://www.autoscout24.it/annunci/audi-a1-benzina",
            "snippet": "Audi A1 benzina usata",
        }
        self.assertIsNone(
            server.listing_from_search_item(
                item,
                payload={
                    "brand": "Audi",
                    "model": "A1",
                    "fuelType": "Diesel",
                    "firstRegistrationDate": "2011-01-01",
                },
            )
        )

    def test_market_filter_keeps_matching_or_unspecified_fuel(self):
        diesel = {
            "title": "Audi A1 1.6 TDI diesel 2011 - 6.900 EUR",
            "url": "https://www.autoscout24.it/annunci/audi-a1-diesel",
        }
        generic = {
            "title": "Audi A1 usata 2011 - 6.900 EUR",
            "url": "https://www.autoscout24.it/annunci/audi-a1",
        }
        payload = {
            "brand": "Audi",
            "model": "A1",
            "fuelType": "Diesel",
            "firstRegistrationDate": "2011-01-01",
        }
        self.assertIsNotNone(server.listing_from_search_item(diesel, payload=payload))
        self.assertIsNotNone(server.listing_from_search_item(generic, payload=payload))

    def test_market_estimate_returns_prudent_estimate_with_two_comparable_listings(self):
        two_listings = [
            {"price": 8000, "weight": 1.0},
            {"price": 8200, "weight": 1.0},
        ]
        estimate, filtered = market_estimate_from_sources(two_listings, 8000)

        self.assertIsNotNone(estimate)
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

    def test_market_estimate_corrects_for_higher_target_mileage(self):
        listings = [
            {"price": 8000, "km": 130000, "weight": 1.0},
            {"price": 8200, "km": 140000, "weight": 1.0},
            {"price": 8400, "km": 150000, "weight": 1.0},
        ]

        estimate, filtered = market_estimate_from_sources(
            listings,
            8000,
            target_km=200000,
        )

        self.assertEqual(len(filtered), 3)
        self.assertIsNotNone(estimate)
        self.assertLess(estimate, 8000)

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

    def test_defect_catalog_matches_bmw_120d_2005_m47_generation(self):
        result = vehicle_defect_reports("BMW", "BMW SERIE 1 120D", 2005, "diesel 1995 cc")

        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "Serie 1")
        self.assertIn(
            "bmw-serie-1-e87-m47-swirl-flaps-community",
            {report["id"] for report in result["reports"]},
        )
        self.assertNotIn(
            "bmw-serie-1-n47-timing-chain-community",
            {report["id"] for report in result["reports"]},
        )

    def test_defect_catalog_matches_bmw_120d_as_serie_1(self):
        result = vehicle_defect_reports("BMW", "120d", 2010, "diesel 1995 cc")

        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "Serie 1")
        self.assertIn(
            "bmw-serie-1-n47-timing-chain-community",
            {report["id"] for report in result["reports"]},
        )

    def test_defect_catalog_matches_full_bmw_series_and_trim_label(self):
        result = vehicle_defect_reports(
            "BMW", "BMW SERIE 1 120D", 2010, "diesel 1995 cc"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "Serie 1")
        self.assertIn(
            "bmw-serie-1-n47-timing-chain-community",
            {report["id"] for report in result["reports"]},
        )

    def test_defect_catalog_matches_bmw_series_120_alias_only_for_diesel(self):
        diesel = vehicle_defect_reports(
            "BMW", "BMW SERIE 1 SERIE 120", 2010, "diesel 1995 cc"
        )
        petrol = vehicle_defect_reports(
            "BMW", "BMW SERIE 1 SERIE 120", 2010, "benzina 1995 cc"
        )

        self.assertIsNotNone(diesel)
        self.assertIn(
            "bmw-serie-1-n47-timing-chain-community",
            {report["id"] for report in diesel["reports"]},
        )
        self.assertIsNotNone(petrol)
        self.assertNotIn(
            "bmw-serie-1-n47-timing-chain-community",
            {report["id"] for report in petrol["reports"]},
        )

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
        self.assertEqual(5, len(result["reports"]))

    def test_evoque_22_diesel_accepts_common_avoque_typo(self):
        result = vehicle_defect_reports(
            "Land Rover",
            "Avoque",
            2013,
            "diesel 2179 cc 2.2 TD4",
        )

        self.assertIsNotNone(result)
        self.assertEqual(5, len(result["reports"]))
        self.assertIn(
            "land-rover-evoque-22-diesel-dpf-egr-community",
            {report["id"] for report in result["reports"]},
        )

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


class VinRecallCheckTests(unittest.TestCase):
    def test_land_rover_vin_is_masked_and_linked_to_compatible_recalls(self):
        reports = [
            {"sourceType": "official_recall"},
            {"sourceType": "community"},
        ]

        result = build_vin_recall_check(
            "SALVA2BG1DH715356",
            "Land Rover",
            reports,
        )

        self.assertTrue(result["valid"])
        self.assertEqual("possible_match", result["status"])
        self.assertEqual(1, result["possibleRecallCount"])
        self.assertEqual("SAL••••••••715356", result["maskedVin"])
        self.assertNotIn("SALVA2BG1DH715356", json.dumps(result))
        self.assertTrue(result["verificationUrl"].startswith("https://"))

    def test_vin_make_mismatch_is_reported(self):
        result = build_vin_recall_check(
            "SALVA2BG1DH715356",
            "Audi",
            [],
        )

        self.assertTrue(result["valid"])
        self.assertEqual("vehicle_mismatch", result["status"])
        self.assertEqual(0, result["possibleRecallCount"])

    def test_invalid_vin_is_not_accepted(self):
        result = build_vin_recall_check("SAL123", "Land Rover", [])

        self.assertFalse(result["valid"])
        self.assertEqual("invalid", result["status"])
        self.assertEqual("", result["maskedVin"])


if __name__ == "__main__":
    unittest.main()
