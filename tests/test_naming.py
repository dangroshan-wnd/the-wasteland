import unittest
from pathlib import Path

from naming import names_for

ROOT = Path(__file__).resolve().parent.parent


class NamingConventionTests(unittest.TestCase):
    def test_captains_log_folder_maps_to_landing(self) -> None:
        names = names_for("pj__captains-log", root=ROOT)
        self.assertEqual(names.project, "captains_log")
        self.assertEqual(names.database, "captains_log")
        self.assertEqual(names.local_database, "captains_log_dev")
        self.assertEqual(names.schema, "landing")
        self.assertEqual(names.qualified, "captains_log.landing")
        self.assertEqual(names.table("entries"), "landing.entries")

    def test_career_page_snapshots_folder(self) -> None:
        names = names_for("pj__career-page-snapshots", root=ROOT)
        self.assertEqual(names.database, "career_page_snapshots")
        self.assertEqual(names.local_database, "career_page_snapshots_dev")
        self.assertEqual(names.table("career_page_snapshots"), "landing.career_page_snapshots")


if __name__ == "__main__":
    unittest.main()
