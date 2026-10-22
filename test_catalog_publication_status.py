import unittest
from unittest.mock import patch

import server


class CatalogPublicationStatusTests(unittest.TestCase):
    def row(self, status="published", reviewed_at="2026-10-09T20:47:37+00:00"):
        return dict(make="Audi", model="A1", status=status,
                    title="Audi A1: segnalazioni e manutenzione del cambio",
                    snippet="Audi A1: segnalazioni tecniche del cambio",
                    source_url="https://example.com/audi-a1-cambio",
                    reviewed_at=reviewed_at, reviewed_by="private-reviewer")

    def test_published_database_sources_advance_the_notification_version(self):
        with patch.object(server, "_catalog_publication_rows", return_value=[]):
            before = server.catalog_update_status()
        with patch.object(server, "_catalog_publication_rows", return_value=[self.row()]):
            after = server.catalog_update_status()
            lookup = server.vehicle_defects_response("Audi", "A1", 2011, "", False)
        self.assertGreater(after["catalogVersion"], before["catalogVersion"])
        self.assertIn("2026-10-09", after["updatedAt"])
        self.assertEqual(lookup["catalogVersion"], after["catalogVersion"])
        self.assertNotIn("private-reviewer", str(after))
        self.assertEqual(after["latestUpdate"]["sources"], [self.row()["source_url"]])

    def test_unchanged_reviews_do_not_repeat_notifications(self):
        with patch.object(server, "_catalog_publication_rows", return_value=[self.row()]):
            self.assertEqual(server.catalog_update_status(), server.catalog_update_status())

    def test_rejection_invalidates_cache_without_promoting_removed_source(self):
        with patch.object(server, "_catalog_publication_rows", return_value=[self.row()]):
            before = server.catalog_update_status()
        rejected = self.row("rejected", "2026-10-10T11:00:00+00:00")
        with patch.object(server, "_catalog_publication_rows", return_value=[rejected]):
            after = server.catalog_update_status()
        self.assertGreater(after["catalogVersion"], before["catalogVersion"])
        self.assertEqual(after["latestUpdate"]["sources"], [])

    def test_transient_database_failure_preserves_last_known_revision(self):
        cached = (0, [self.row()])
        with patch.object(server, "DEFECT_PUBLICATION_STATE_CACHE", cached), patch.object(
            server, "_defect_review_rows", side_effect=RuntimeError("offline")
        ):
            self.assertEqual(server._catalog_publication_rows(), cached[1])


if __name__ == "__main__":
    unittest.main()
