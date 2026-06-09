from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from research.age_map_report import render_html, render_markdown, summarize_manifest  # noqa: E402


class AgeMapReportTests(unittest.TestCase):
    def test_summarize_manifest_counts_resolved_materials(self) -> None:
        report_root = Path(r"E:\report")
        manifest = {
            "source": r"D:\maps\b0000.xc",
            "triangulation": "strip",
            "output_dir": r"E:\report\samples\b0000",
            "textures": {
                "converted": 2,
                "items": [
                    {
                        "png": r"E:\report\samples\b0000\textures\000.png",
                        "header": {"width": 64, "height": 64, "bit_depth": 4},
                        "blocks": {"pixel_layout": "psp-swizzled"},
                    },
                    {
                        "png": r"E:\report\samples\b0000\textures\001.png",
                        "header": {"width": 128, "height": 128, "bit_depth": 8},
                        "blocks": {"pixel_layout": "psp-swizzled"},
                    },
                ],
            },
            "materials": {
                "material_count": 3,
                "mtl_records": [
                    {"material_name": "mat_resolved", "map_Kd": "../textures/000.png", "texture_mapping_confidence": "direct_xi_stem"},
                    {"material_name": "cl.helper", "map_Kd": None, "texture_mapping_confidence": "unresolved"},
                    {"material_name": "mat_resolved2", "map_Kd": "../textures/001.png", "texture_mapping_confidence": "resource_order_heuristic"},
                ],
            },
            "models": {
                "mesh_count": 2,
                "weights": {"weighted_vertex_count": 0},
                "gltf": {"texture_count": 2, "skin_count": 0},
                "meshes": [
                    {
                        "mesh_name": "col_01",
                        "material_name": "cl.helper",
                        "xpvb": {"uv0_format": "float32x2", "position_format": "float32x3"},
                        "geometry": {"nondegenerate_face_count": 10},
                    },
                    {
                        "mesh_name": "mesh_visual",
                        "material_name": "mat_resolved2",
                        "xpvb": {"uv0_format": "u16_normx2", "position_format": "float32x4_xyz"},
                        "geometry": {"nondegenerate_face_count": 4},
                    },
                ],
            },
        }

        summary = summarize_manifest(manifest, report_root)

        self.assertEqual(summary["resolved_material_count"], 2)
        self.assertEqual(summary["unresolved_material_count"], 1)
        self.assertEqual(summary["unresolved_collision_material_count"], 1)
        self.assertEqual(summary["unresolved_visual_material_count"], 0)
        self.assertEqual(summary["unresolved_visual_effect_material_count"], 0)
        self.assertEqual(summary["unresolved_visual_plain_material_count"], 0)
        self.assertEqual(summary["unresolved_visual_plain_face_count"], 0)
        self.assertEqual(summary["unresolved_visual_plain_face_ratio"], 0.0)
        self.assertEqual(summary["triangle_count"], 14)
        self.assertEqual(summary["uv_formats"], {"float32x2": 1, "u16_normx2": 1})
        self.assertEqual(summary["texture_sizes"], {"128x128@8": 1, "64x64@4": 1})
        self.assertEqual(summary["gltf_relative"], "samples/b0000/models/b0000_strip.gltf")

    def test_render_outputs_include_expected_paths(self) -> None:
        report = {
            "generated_at": "2026-06-09T00:00:00+08:00",
            "input_root": r"D:\maps",
            "texture_layout": "psp-swizzled",
            "samples": [
                {
                    "name": "b0000",
                    "source": r"D:\maps\b0000.xc",
                    "output_dir_relative": "samples/b0000",
                    "gltf_relative": "samples/b0000/models/b0000_strip.gltf",
                    "mtl_relative": "samples/b0000/models/b0000.mtl",
                    "texture_relatives": [
                        "samples/b0000/textures/000.png",
                        "samples/b0000/textures/001.png",
                    ],
                    "texture_count": 2,
                    "material_count": 3,
                    "resolved_material_count": 2,
                    "unresolved_material_count": 1,
                    "unresolved_visual_material_count": 0,
                    "unresolved_visual_effect_material_count": 0,
                    "unresolved_visual_plain_material_count": 0,
                    "unresolved_visual_plain_face_count": 0,
                    "unresolved_visual_plain_face_ratio": 0.0,
                    "mesh_count": 2,
                    "triangle_count": 14,
                    "weighted_vertex_count": 0,
                    "skin_count": 0,
                    "absent_uv_mesh_count": 0,
                    "absent_uv_collision_mesh_count": 0,
                    "absent_uv_non_collision_mesh_count": 0,
                    "unresolved_collision_material_count": 1,
                    "unresolved_aux_material_count": 0,
                    "uv_formats": {"float32x2": 1},
                    "texture_mapping_confidence": {"direct_xi_stem": 2, "unresolved": 1},
                    "texture_sizes": {"64x64@4": 1},
                    "pixel_layouts": {"psp-swizzled": 2},
                    "unresolved_visual_materials": [],
                }
            ],
        }

        markdown = render_markdown(report)
        html = render_html(report)

        self.assertIn("AGE PSP Map Validation Report", markdown)
        self.assertIn("samples/b0000/models/b0000_strip.gltf", markdown)
        self.assertIn("<model-viewer", html)
        self.assertIn("samples/b0000/textures/000.png", html)


if __name__ == "__main__":
    unittest.main()



