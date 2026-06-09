from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_xmpr_tool import (  # noqa: E402
    GeometryStats,
    MeshInfo,
    Vertex,
    XpviInfo,
    XpvbInfo,
    build_weight_manifest,
    vertex_weight_records,
    weight_manifest_summary,
)


def make_vertex(weights: tuple[int, ...] | None, position: tuple[float, float, float]) -> Vertex:
    return Vertex(
        position=position,
        uv0=(0.25, 0.75),
        packed_slot1_rgba=None,
        position_raw_s16=(8192, 16384, 24576),
        implicit_node_weights_u8=weights,
    )


def make_mesh_info() -> MeshInfo:
    return MeshInfo(
        source="sample.prm",
        mesh_name="sample_mesh",
        material_name="sample_material",
        draw_priority=21,
        mesh_type=1,
        nodes_count=2,
        node_hashes=["AAAABBBB", "CCCCDDDD"],
        xpvb=XpvbInfo(
            offset=0,
            length=0,
            att_buffer_offset=0,
            unknown_offset=0,
            vertex_buffer_offset=0,
            stride=0,
            vertex_count=2,
            att_compression="none",
            att_decoded_size=0,
            vertex_compression="none",
            vertex_decoded_size=0,
            unknown_bytes_hex="",
            attributes=[],
            position_format="s16_normx3",
            uv0_format="u16_normx2",
            warnings=[],
        ),
        xpvi=XpviInfo(
            offset=0,
            length=12,
            primitive_type=2,
            faces_offset=0,
            face_count=0,
            has_embedded_index_payload=False,
        ),
        vertex_count=2,
        face_count=0,
        triangulation="points",
        geometry=GeometryStats(
            bounds_min=(0.0, 0.0, 0.0),
            bounds_max=(1.0, 1.0, 1.0),
            unique_position_count=2,
            unique_position_ratio=1.0,
            inferred_face_count=0,
            exported_face_count=0,
            nondegenerate_face_count=0,
            degenerate_face_count=0,
            degenerate_face_ratio=0.0,
            max_triangle_area=0.0,
            position_semantic="skinned_bind_pose_position",
        ),
        warnings=[],
    )


class AgeWeightManifestTests(unittest.TestCase):
    def test_vertex_weight_records_preserve_raw_and_normalize(self) -> None:
        vertex = make_vertex((64, 64, 0, 128, 0, 0, 0, 0), (1.0, 2.0, 3.0))

        records = vertex_weight_records(vertex, ["AAAABBBB", "CCCCDDDD"])

        self.assertEqual([record["slot"] for record in records], [0, 1, 3])
        self.assertEqual(records[0]["node_hash"], "AAAABBBB")
        self.assertEqual(records[1]["node_hash"], "CCCCDDDD")
        self.assertIsNone(records[2]["node_hash"])
        self.assertEqual(records[2]["raw_u8"], 128)
        self.assertAlmostEqual(records[0]["weight_raw128"], 0.5)
        self.assertAlmostEqual(records[0]["weight_normalized"], 0.25)
        self.assertAlmostEqual(records[2]["weight_normalized"], 0.5)

    def test_weight_manifest_maps_vertices_to_obj_indices(self) -> None:
        info = make_mesh_info()
        vertices = [
            make_vertex((128, 0, 0, 0, 0, 0, 0, 0), (0.0, 0.0, 0.0)),
            make_vertex(None, (1.0, 1.0, 1.0)),
        ]

        manifest = build_weight_manifest([(info, vertices, [])], Path("sample.obj"))
        summary = weight_manifest_summary(manifest, Path("sample.weights.json"))

        self.assertEqual(manifest["weighted_mesh_count"], 1)
        self.assertEqual(manifest["vertex_count"], 2)
        self.assertEqual(manifest["vertices_with_raw_weight_count"], 1)
        self.assertEqual(manifest["weighted_vertex_count"], 1)
        self.assertEqual(manifest["weight_record_count"], 1)
        self.assertEqual(summary["manifest"], "sample.weights.json")

        mesh = manifest["meshes"][0]
        self.assertEqual(mesh["obj_vertex_start"], 1)
        self.assertEqual(mesh["unweighted_vertex_count"], 1)
        self.assertEqual(mesh["vertices"][0]["index"], 0)
        self.assertEqual(mesh["vertices"][0]["obj_vertex_index"], 1)
        self.assertEqual(mesh["vertices"][0]["weights"][0]["node_hash"], "AAAABBBB")


if __name__ == "__main__":
    unittest.main()



