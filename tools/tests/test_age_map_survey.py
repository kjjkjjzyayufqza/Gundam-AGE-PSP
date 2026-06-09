from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from research.age_map_survey import classify_archive, collect_inputs, render_markdown  # noqa: E402


class AgeMapSurveyTests(unittest.TestCase):
    def test_collect_inputs_applies_include_and_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("b0000.xc", "b0000sky.xc", "b0000chr001.xc", "note.txt"):
                (root / name).write_text("", encoding="utf-8")

            paths = collect_inputs(root, ["*.xc"], ["*chr*.xc"])

            self.assertEqual([path.name for path in paths], ["b0000.xc", "b0000sky.xc"])

    def test_classify_archive_distinguishes_sky_and_chr(self) -> None:
        self.assertEqual(classify_archive(Path("b0000.xc")), "b")
        self.assertEqual(classify_archive(Path("b0000sky.xc")), "sky")
        self.assertEqual(classify_archive(Path("b0000chr001.xc")), "chr_companion")
        self.assertEqual(classify_archive(Path("fe0001.xc")), "fe")

    def test_render_markdown_includes_totals_and_ranked_samples(self) -> None:
        report = {
            "generated_at": "2026-06-09T01:00:00+08:00",
            "input_root": r"D:\maps",
            "texture_layout": "psp-swizzled",
            "cleanup_samples": True,
            "sample_count": 2,
            "failed_sample_count": 0,
            "clean_visual_count": 1,
            "plain_problem_count": 1,
            "effect_only_problem_count": 0,
            "group_summaries": [
                {
                    "archive_group": "b",
                    "sample_count": 2,
                    "failed_count": 0,
                    "clean_visual_count": 1,
                    "plain_problem_count": 1,
                    "effect_only_problem_count": 0,
                    "unexpected_weight_count": 0,
                    "unexpected_skin_count": 0,
                    "max_plain_face_ratio": 0.25,
                }
            ],
            "top_plain_samples": [
                {
                    "name": "b0101",
                    "unresolved_visual_plain_material_count": 3,
                    "unresolved_visual_plain_face_count": 250,
                    "triangle_count": 1000,
                    "unresolved_visual_plain_face_ratio": 0.25,
                    "unresolved_visual_materials": ["mat_a", "mat_b"],
                }
            ],
            "top_effect_only_samples": [],
            "samples": [],
        }

        text = render_markdown(report)

        self.assertIn("AGE PSP Map Survey Report", text)
        self.assertIn("`b0101`", text)
        self.assertIn("25.00%", text)


if __name__ == "__main__":
    unittest.main()



