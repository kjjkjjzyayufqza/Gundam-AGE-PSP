from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_blender_preview import (  # noqa: E402
    default_out_path,
    discover_model_inputs,
    find_blender,
    write_worker_script,
)


class AgeBlenderPreviewHostTests(unittest.TestCase):
    def test_discover_prefers_models_gltf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models = root / "models"
            models.mkdir()
            gltf = models / "unit_strip.gltf"
            obj = models / "unit_strip.obj"
            gltf.write_text("{}", encoding="utf-8")
            obj.write_text("v 0 0 0\n", encoding="utf-8")
            found = discover_model_inputs(root)
            self.assertEqual(found, [gltf.resolve()])

    def test_default_out_path_next_to_model(self) -> None:
        model = Path("outputs/age_fx_ms/ms042000_p000/models/ms042000_p000_strip.gltf")
        out = default_out_path(model, None)
        self.assertEqual(out.name, "ms042000_p000_strip_blender_preview.png")
        self.assertEqual(out.parent, model.parent)

    def test_worker_script_contains_entry_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_worker_script(Path(tmp) / "worker.py")
            text = path.read_text(encoding="utf-8")
            self.assertIn("AGE_BLENDER_PREVIEW_JSON:", text)
            self.assertIn("import_scene.gltf", text)

    def test_find_blender_or_skip(self) -> None:
        try:
            blender = find_blender()
        except FileNotFoundError:
            self.skipTest("Blender not installed on this machine")
        self.assertTrue(blender.is_file())
        self.assertEqual(blender.name.lower(), "blender.exe")


if __name__ == "__main__":
    unittest.main()
