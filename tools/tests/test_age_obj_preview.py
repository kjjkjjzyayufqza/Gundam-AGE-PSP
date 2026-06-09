from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from research.age_obj_preview import load_obj_geometry  # noqa: E402


class ObjPreviewTests(unittest.TestCase):
    def test_loads_vertices_and_triangulates_polygon_faces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quad.obj"
            path.write_text(
                "\n".join(
                    [
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 1 1 0",
                        "v 0 1 0",
                        "f 1 2 3 4",
                    ]
                ),
                encoding="utf-8",
            )

            vertices, faces = load_obj_geometry(path)

            self.assertEqual(len(vertices), 4)
            self.assertEqual(faces, [(0, 1, 2), (0, 2, 3)])


if __name__ == "__main__":
    unittest.main()



