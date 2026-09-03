import unittest
from unittest.mock import patch

import patched_server
import server


class ProviderDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        with patched_server._PROVIDER_DIAGNOSTICS_LOCK:
            for provider in patched_server._PROVIDER_DIAGNOSTICS.values():
                provider.update(
                    {
                        "lastStatus": None,
                        "lastResults": None,
                        "lastSuccessAt": "",
                        "lastError": "",
                        "lastOperation": "",
                        "elapsedMs": None,
                    }
                )

    def test_tavily_success_message_reports_real_result_count(self):
        fake_results = [{"url": "https://example.test/1"}] * 7
        with patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "TAVILY_API_KEY", "test-key"
        ), patch.object(server, "TAVILY_DAILY_LIMIT", 30), patch.object(
            server, "TAVILY_DAILY_USAGE", {}
        ), patch.object(
            patched_server, "_ORIGINAL_TAVILY_MARKET_SEARCH", return_value=fake_results
        ):
            results = patched_server._diagnostic_tavily_market_search("query", {})
            payload = patched_server.provider_diagnostics_payload()

        self.assertEqual(len(results), 7)
        self.assertEqual(payload["providers"]["tavily"]["lastStatus"], 200)
        self.assertEqual(payload["providers"]["tavily"]["lastResults"], 7)
        self.assertEqual(
            payload["providers"]["tavily"]["message"],
            "Tavily: OK — 7 risultati trovati",
        )

    def test_brave_success_message_reports_real_result_count(self):
        fake_results = [{"url": "https://example.test/1"}] * 10
        with patch.object(server, "BRAVE_SEARCH_API_KEY", "test-key"), patch.object(
            server, "BRAVE_DAILY_LIMIT", 40
        ), patch.object(server, "BRAVE_DAILY_USAGE", {}), patch.object(
            patched_server, "_ORIGINAL_BRAVE_MARKET_SEARCH", return_value=fake_results
        ):
            results = patched_server._diagnostic_brave_market_search("query", {})
            payload = patched_server.provider_diagnostics_payload()

        self.assertEqual(len(results), 10)
        self.assertEqual(payload["providers"]["brave"]["lastStatus"], 200)
        self.assertEqual(payload["providers"]["brave"]["lastResults"], 10)
        self.assertEqual(
            payload["providers"]["brave"]["message"],
            "Brave: OK — 10 risultati trovati",
        )

    def test_diagnostics_endpoint_is_passive_and_does_not_call_search(self):
        with patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "TAVILY_API_KEY", "test-key"
        ), patch.object(server, "BRAVE_SEARCH_API_KEY", "test-key"), patch.object(
            patched_server, "_ORIGINAL_TAVILY_MARKET_SEARCH"
        ) as tavily, patch.object(
            patched_server, "_ORIGINAL_BRAVE_MARKET_SEARCH"
        ) as brave:
            payload = patched_server.provider_diagnostics_payload()

        self.assertTrue(payload["ok"])
        tavily.assert_not_called()
        brave.assert_not_called()
        self.assertIn("Diagnostica passiva", payload["note"])

    def test_provider_error_is_visible_without_changing_original_exception(self):
        with patch.object(server, "BRAVE_SEARCH_API_KEY", "test-key"), patch.object(
            patched_server,
            "_ORIGINAL_BRAVE_MARKET_SEARCH",
            side_effect=RuntimeError("provider unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                patched_server._diagnostic_brave_market_search("query", {})
            payload = patched_server.provider_diagnostics_payload()

        self.assertGreaterEqual(payload["providers"]["brave"]["lastStatus"], 400)
        self.assertIn("ERRORE", payload["providers"]["brave"]["message"])

    def test_tavily_unauthorized_message_points_to_render_key(self):
        with patched_server._PROVIDER_DIAGNOSTICS_LOCK:
            patched_server._PROVIDER_DIAGNOSTICS["tavily"].update(
                {"lastStatus": 401, "lastResults": 0, "lastError": "Unauthorized"}
            )
        with patch.object(server, "TAVILY_ENABLED", True), patch.object(
            server, "TAVILY_API_KEY", "configured-but-invalid"
        ):
            payload = patched_server.provider_diagnostics_payload()

        self.assertIn("CHIAVE API RIFIUTATA", payload["providers"]["tavily"]["message"])
        self.assertIn("Render", payload["providers"]["tavily"]["message"])


if __name__ == "__main__":
    unittest.main()
