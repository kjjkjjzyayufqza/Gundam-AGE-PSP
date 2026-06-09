from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_asset_index import build_group_summaries, entry_suffix, select_entries  # noqa: E402


class AgeAssetIndexTests(unittest.TestCase):
    def test_entry_suffix_handles_archive_paths(self) -> None:
        self.assertEqual(entry_suffix("folder\\000.prm"), ".prm")
        self.assertEqual(entry_suffix("textures/001.xi"), ".xi")
        self.assertEqual(entry_suffix("RES.bin"), ".bin")

    def test_select_entries_filters_model_and_texture_types(self) -> None:
        entries = [
            {"name": "000.prm"},
            {"name": "001.xi"},
            {"name": "002.txp"},
            {"name": "readme.txt"},
        ]

        self.assertEqual([item["name"] for item in select_entries(entries, {".prm"})], ["000.prm"])
        self.assertEqual([item["name"] for item in select_entries(entries, {".xi"})], ["001.xi"])
        self.assertEqual([item["name"] for item in select_entries(entries, {".txp"})], ["002.txp"])

    def test_group_summary_counts_model_texture_archives_and_exports(self) -> None:
        archives = [
            {
                "category": "map",
                "model_count": 2,
                "texture_count": 3,
                "material_count": 4,
                "has_model_and_texture": True,
                "pipeline_exports": [{"manifest": "a"}],
            },
            {
                "category": "map",
                "model_count": 1,
                "texture_count": 0,
                "material_count": 1,
                "has_model_and_texture": False,
                "pipeline_exports": [],
            },
            {
                "category": "mobile_suit",
                "model_count": 5,
                "texture_count": 2,
                "material_count": 2,
                "has_model_and_texture": True,
                "pipeline_exports": [{"manifest": "b"}, {"manifest": "c"}],
            },
        ]

        groups = {item["name"]: item for item in build_group_summaries(archives, "category")}

        self.assertEqual(groups["map"]["archive_count"], 2)
        self.assertEqual(groups["map"]["model_count"], 3)
        self.assertEqual(groups["map"]["texture_count"], 3)
        self.assertEqual(groups["map"]["model_texture_archive_count"], 1)
        self.assertEqual(groups["map"]["pipeline_export_count"], 1)
        self.assertEqual(groups["mobile_suit"]["pipeline_export_count"], 2)


if __name__ == "__main__":
    unittest.main()



