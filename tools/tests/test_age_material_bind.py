from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_material_bind import (  # noqa: E402
    apply_mesh_name_texture_candidates,
    parse_chrp_sections,
)


class AgeMaterialBindTests(unittest.TestCase):
    def test_parse_chrp_sections_reads_material_to_texture_index(self) -> None:
        # Minimal CHRP00 with 1 TextureData + 1 MaterialData linking image CRC.
        # Layout follows StudioEleven RES header: offsets are quarter-words.
        import struct
        import zlib

        texture_name = b"face_tex\x00"
        material_name = b"DefaultLib.sample_10\x00"
        # string pool starts at 0x100
        string_off = 0x100
        pool = texture_name + material_name
        tex_crc = zlib.crc32(b"face_tex") & 0xFFFFFFFF
        mat_crc = zlib.crc32(b"DefaultLib.sample_10") & 0xFFFFFFFF

        # Material table at 0x14 (5<<2), 2 entries: TextureData + MaterialData
        # TextureData at 0x40, count 1, type 240, length 20
        # MaterialData at 0x60, count 1, type 290, length 224
        payload = bytearray(0x200)
        payload[0:6] = b"CHRP00"
        struct.pack_into("<H", payload, 8, string_off >> 2)  # string offset
        struct.pack_into("<H", payload, 10, 1)
        struct.pack_into("<H", payload, 12, 0x14 >> 2)  # material table offset
        struct.pack_into("<H", payload, 14, 2)  # material table count
        struct.pack_into("<H", payload, 16, 0x30 >> 2)  # node table
        struct.pack_into("<H", payload, 18, 0)

        # section 0: TextureData
        struct.pack_into("<HHHH", payload, 0x14, 0x40 >> 2, 1, 240, 20)
        # section 1: MaterialData
        struct.pack_into("<HHHH", payload, 0x1C, 0x60 >> 2, 1, 290, 224)
        # TextureData entry
        struct.pack_into("<I", payload, 0x40, tex_crc)
        # MaterialData entry: name, pad text off, name1, name2, image0
        struct.pack_into("<I", payload, 0x60, mat_crc)
        struct.pack_into("<I", payload, 0x64, 0)
        struct.pack_into("<I", payload, 0x68, mat_crc)
        struct.pack_into("<I", payload, 0x6C, mat_crc)
        struct.pack_into("<Ii", payload, 0x70, tex_crc, 1)  # image0 enabled
        payload[string_off : string_off + len(pool)] = pool

        parsed = parse_chrp_sections(bytes(payload))
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["texture_data"]), 1)
        self.assertEqual(parsed["texture_data"][0]["index"], 0)
        self.assertEqual(parsed["texture_data"][0]["name"], "face_tex")
        self.assertEqual(len(parsed["material_data"]), 1)
        self.assertEqual(parsed["material_data"][0]["name"], "DefaultLib.sample_10")
        self.assertTrue(parsed["material_data"][0]["images"][0]["enabled"])
        self.assertEqual(parsed["material_data"][0]["images"][0]["name"], "face_tex")

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



