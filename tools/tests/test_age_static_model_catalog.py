from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from research.age_static_model_catalog import archive_category, archive_variant, build_catalog  # noqa: E402


def prm(vertex_count: int, position_format: str, weighted: bool) -> dict:
    slot7 = {"slot": 7, "count": 12 if weighted else 0, "offset": 0, "size": 8 if weighted else 0, "type": 2}
    return {
        "xpvb": {
            "vertex_count": vertex_count,
            "position_format": position_format,
            "uv0_format": "u16_normx2" if weighted else "float32x2",
            "attributes": [slot7],
        }
    }


class StaticModelCatalogTests(unittest.TestCase):
    def test_archive_classification(self) -> None:
        self.assertEqual(
            archive_category(r"<PSP_RESOURCE_ROOT>\chr\ms008000\ms008000_p000.xc"),
            "mobile_suit",
        )
        self.assertEqual(
            archive_category(r"<PSP_RESOURCE_ROOT>\map\b0000.xc"),
            "map",
        )
        self.assertEqual(archive_variant(r"D:\x\ms008000_p210.xc"), "part_variant")

    def test_catalog_aggregates_weights_and_samples(self) -> None:
        survey = {
            "inputs": ["root"],
            "archives": [
                {
                    "archive": r"D:\root\psp\chr\ms001000\ms001000_p000.xc",
                    "file_count": 10,
                    "prm_count": 2,
                    "failed_prm_count": 0,
                    "prms": [prm(100, "s16_normx3", True), prm(200, "s16_normx3", True)],
                },
                {
                    "archive": r"D:\root\psp\map\b0000.xc",
                    "file_count": 10,
                    "prm_count": 1,
                    "failed_prm_count": 0,
                    "prms": [prm(50, "float32x3", False)],
                },
            ],
        }

        catalog = build_catalog(survey, sample_limit=1)

        self.assertEqual(catalog["archives_with_prm"], 2)
        self.assertEqual(catalog["prm_count"], 3)
        self.assertEqual(catalog["vertex_count"], 350)
        self.assertEqual(catalog["weighted_archive_count"], 1)
        self.assertEqual(catalog["weighted_prm_count"], 2)

        mobile = next(item for item in catalog["categories"] if item["name"] == "mobile_suit")
        self.assertEqual(mobile["vertex_count"], 300)
        self.assertEqual(mobile["weighted_archive_count"], 1)
        self.assertEqual(mobile["samples_by_vertices"][0]["variant"], "base_p000")


if __name__ == "__main__":
    unittest.main()




