from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_material_bind import apply_mesh_name_texture_candidates  # noqa: E402


class AgeMaterialBindTests(unittest.TestCase):
    def test_apply_mesh_name_texture_candidates_backfills_unresolved_material(self) -> None:
        material_records = [
            {
                "material_name": "map.sample-",
                "texture_name_candidates": [],
                "texture_image_binding_confidence": "unresolved",
                "binding_confidence": "crc32_txp_owner",
            }
        ]
        mesh_records = [
            {
                "mesh_name": "a_firewall-_tm",
                "material_name": "map.sample-",
            }
        ]
        image_order_candidates = [
            {
                "texture_name": "a_firewall-_tm",
                "xi_path_by_resource_order": r"E:\textures\000.xi",
            }
        ]

        apply_mesh_name_texture_candidates(material_records, mesh_records, image_order_candidates)

        self.assertEqual(material_records[0]["texture_name_candidates"], ["a_firewall-_tm"])
        self.assertEqual(material_records[0]["texture_image_binding_confidence"], "mesh_name_resource_order_candidate")
        self.assertEqual(material_records[0]["binding_confidence"], "crc32_txp_owner+mesh_name_texture_candidate")

    def test_apply_mesh_name_texture_candidates_leaves_existing_candidates(self) -> None:
        material_records = [
            {
                "material_name": "map.sample-",
                "texture_name_candidates": ["existing"],
                "texture_image_binding_confidence": "txp_stem_xi_match",
                "binding_confidence": "crc32_txp_owner",
            }
        ]
        mesh_records = [{"mesh_name": "a_firewall-_tm", "material_name": "map.sample-"}]
        image_order_candidates = [{"texture_name": "a_firewall-_tm", "xi_path_by_resource_order": r"E:\textures\000.xi"}]

        apply_mesh_name_texture_candidates(material_records, mesh_records, image_order_candidates)

        self.assertEqual(material_records[0]["texture_name_candidates"], ["existing"])
        self.assertEqual(material_records[0]["texture_image_binding_confidence"], "txp_stem_xi_match")


if __name__ == "__main__":
    unittest.main()



