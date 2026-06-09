from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_asset_pipeline import (  # noqa: E402
    animation_node_hashes,
    build_parser,
    compatibility_record,
    discover_animation_archives,
    discover_embedded_animations,
    model_archive_prefix,
    model_node_hashes,
    skeleton_archives_from_survey,
    source_matches,
    write_mtl,
)


class CharacterPipelineTests(unittest.TestCase):
    def test_character_pipeline_defaults_to_static_assets_only(self) -> None:
        args = build_parser().parse_args(
            ["from-character", "model_p000.xc", "--out-dir", "out"]
        )

        self.assertEqual(args.animation_policy, "none")

    def test_discovers_only_same_prefix_sibling_animation_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "fn024000_p000.xc"
            expected = [root / "fn024000_s240.xc", root / "fn024000_v360.xc"]
            for path in [model, *expected, root / "other_s240.xc", root / "fn024000_misc.xc"]:
                path.touch()

            self.assertEqual(model_archive_prefix(model), "fn024000")
            self.assertEqual(discover_animation_archives(model), expected)

    def test_discovers_only_embedded_mtn2_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = [root / "000.mtn2", root / "nested" / "001.mtn2"]
            for path in [*expected, root / "000.mtninf", root / "nested" / "ignored.txt"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            self.assertEqual(discover_embedded_animations(root), expected)

    def test_compatibility_uses_unique_node_hash_overlap(self) -> None:
        model_manifest = {
            "models": {
                "meshes": [
                    {"node_hashes": ["AAAABBBB", "CCCCDDDD"]},
                    {"node_hashes": ["CCCCDDDD", "EEEEFFFF"]},
                ]
            }
        }
        animation_data = {
            "tracks": [
                {
                    "nodes": [
                        {"Name": "ccccdddd"},
                        {"Name": "EEEEFFFF"},
                        {"Name": "11112222"},
                    ]
                }
            ]
        }

        model_nodes = model_node_hashes(model_manifest)
        animation_nodes = animation_node_hashes(animation_data)
        record = compatibility_record(model_nodes, animation_nodes)

        self.assertEqual(model_nodes, {"AAAABBBB", "CCCCDDDD", "EEEEFFFF"})
        self.assertEqual(animation_nodes, {"CCCCDDDD", "EEEEFFFF", "11112222"})
        self.assertEqual(record["overlap_count"], 2)
        self.assertAlmostEqual(record["model_coverage"], 2 / 3)
        self.assertAlmostEqual(record["animation_coverage"], 2 / 3)

    def test_reads_skeleton_archives_from_survey_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "survey.json"
            path.write_text(
                json.dumps({"greedy_archive_cover": [{"archive": r"D:\root\skel.xc"}]}),
                encoding="utf-8",
            )

            self.assertEqual(skeleton_archives_from_survey(path), [Path(r"D:\root\skel.xc")])

    def test_source_matches_accepts_relative_mapping_source(self) -> None:
        self.assertTrue(source_matches("001.prm", r"out\extracted\001.prm"))
        self.assertTrue(source_matches("nested/001.prm", r"out\extracted\nested\001.prm"))
        self.assertFalse(source_matches("002.prm", r"out\extracted\001.prm"))

    def test_write_mtl_adds_mesh_level_texture_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extracted = root / "extracted"
            texture = extracted / "047.xi"
            png = root / "textures" / "047.png"
            material_manifest = {
                "root": str(extracted),
                "materials": [
                    {
                        "material_name": "map.sky-",
                        "texture_name_candidates": [],
                        "xi_path_by_txp_stem": None,
                        "texture_image_binding_confidence": "unresolved",
                    }
                ],
                "meshes": [
                    {
                        "source": str(extracted / "001.prm"),
                        "mesh_name": "sky_tm",
                        "material_name": "map.sky-",
                    }
                ],
                "image_order_candidates": [],
            }
            texture_manifest = {"items": [{"source": str(texture), "png": str(png)}]}
            overrides = {
                "mesh_textures": [
                    {
                        "mesh_name": "sky_tm",
                        "material_name": "map.sky-",
                        "source": "001.prm",
                        "texture": "047.xi",
                        "confidence": "visual_reviewed_sky",
                        "reason": "reviewed sky texture",
                    }
                ]
            }

            mtl_path, records, material_overrides = write_mtl(
                root / "models",
                "sample",
                material_manifest,
                texture_manifest,
                overrides,
            )

            override_record = next(item for item in records if item.get("mesh_name") == "sky_tm")
            self.assertEqual(override_record["map_Kd"], "../textures/047.png")
            self.assertEqual(override_record["texture_mapping_confidence"], "visual_reviewed_sky")
            self.assertEqual(override_record["mapping_reason"], "reviewed sky texture")
            self.assertIn("map.sky-__sky_tm", mtl_path.read_text(encoding="utf-8"))
            self.assertEqual(
                material_overrides[str(extracted / "001.prm").replace("\\", "/").lower()],
                "map.sky-__sky_tm",
            )


if __name__ == "__main__":
    unittest.main()



