from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_gltf_tool import write_gltf  # noqa: E402
from age_xmpr_tool import GeometryStats, MeshInfo, Vertex, XpviInfo, XpvbInfo  # noqa: E402


def make_vertex(weights: tuple[int, ...], position: tuple[float, float, float]) -> Vertex:
    return Vertex(
        position=position,
        uv0=(0.0, 1.0),
        packed_slot1_rgba=None,
        position_raw_s16=(0, 0, 0),
        implicit_node_weights_u8=weights,
    )


def make_mesh_info() -> MeshInfo:
    return MeshInfo(
        source="sample.prm",
        mesh_name="sample_mesh",
        material_name="DefaultLib.sample",
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
            vertex_count=3,
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
        vertex_count=3,
        face_count=1,
        triangulation="strip",
        geometry=GeometryStats(
            bounds_min=(0.0, 0.0, 0.0),
            bounds_max=(1.0, 1.0, 0.0),
            unique_position_count=3,
            unique_position_ratio=1.0,
            inferred_face_count=1,
            exported_face_count=1,
            nondegenerate_face_count=1,
            degenerate_face_count=0,
            degenerate_face_ratio=0.0,
            max_triangle_area=0.5,
            position_semantic="skinned_bind_pose_position",
        ),
        warnings=[],
    )


class AgeGltfToolTests(unittest.TestCase):
    def test_write_gltf_preserves_skin_attributes_and_texture(self) -> None:
        vertices = [
            make_vertex((128, 0, 0, 0, 0, 0, 0, 0), (0.0, 0.0, 0.0)),
            make_vertex((64, 64, 0, 0, 0, 0, 0, 0), (1.0, 0.0, 0.0)),
            make_vertex((0, 128, 0, 0, 0, 0, 0, 0), (0.0, 1.0, 0.0)),
        ]
        material_records = [
            {
                "obj_material_name": "DefaultLib.sample",
                "map_Kd": "../textures/000.png",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            gltf_path = Path(temp_dir) / "sample.gltf"
            summary = write_gltf(gltf_path, [(make_mesh_info(), vertices, [(1, 2, 3)])], material_records)
            document = json.loads(gltf_path.read_text(encoding="utf-8"))

            self.assertTrue((Path(temp_dir) / "sample.bin").exists())
            self.assertEqual(summary["weighted_vertex_count"], 3)
            self.assertEqual(summary["skin_count"], 1)
            self.assertEqual(summary["texture_count"], 1)
            self.assertEqual(document["images"][0]["uri"], "../textures/000.png")

            primitive = document["meshes"][0]["primitives"][0]
            self.assertIn("JOINTS_0", primitive["attributes"])
            self.assertIn("WEIGHTS_0", primitive["attributes"])
            self.assertEqual(primitive["mode"], 4)
            self.assertEqual(document["nodes"][-1]["skin"], 0)
            self.assertEqual(document["skins"][0]["extras"]["node_hashes"], ["AAAABBBB", "CCCCDDDD"])

    def test_write_gltf_uses_mesh_material_override(self) -> None:
        vertices = [
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (0.0, 0.0, 0.0)),
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (1.0, 0.0, 0.0)),
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (0.0, 1.0, 0.0)),
        ]
        material_records = [
            {
                "obj_material_name": "DefaultLib.sample__sample_mesh",
                "map_Kd": "../textures/047.png",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            gltf_path = Path(temp_dir) / "sample.gltf"
            summary = write_gltf(
                gltf_path,
                [(make_mesh_info(), vertices, [(1, 2, 3)])],
                material_records,
                {"sample.prm": "DefaultLib.sample__sample_mesh"},
            )
            document = json.loads(gltf_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["texture_count"], 1)
            self.assertEqual(document["materials"][0]["name"], "DefaultLib.sample__sample_mesh")
            self.assertEqual(document["images"][0]["uri"], "../textures/047.png")
            self.assertEqual(document["meshes"][0]["primitives"][0]["material"], 0)

    def test_write_gltf_uses_mbn_bind_nodes_when_available(self) -> None:
        vertices = [
            make_vertex((128, 0, 0, 0, 0, 0, 0, 0), (0.0, 0.0, 0.0)),
            make_vertex((0, 128, 0, 0, 0, 0, 0, 0), (1.0, 0.0, 0.0)),
            make_vertex((128, 0, 0, 0, 0, 0, 0, 0), (0.0, 1.0, 0.0)),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_mbn(root / "root.mbn", 0xAAAABBBB, 0, (1.0, 2.0, 3.0))
            self.write_mbn(root / "child.mbn", 0xCCCCDDDD, 0xAAAABBBB, (4.0, 5.0, 6.0))

            gltf_path = root / "sample.gltf"
            summary = write_gltf(gltf_path, [(make_mesh_info(), vertices, [(1, 2, 3)])], mbn_root=root)
            document = json.loads(gltf_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["mbn_bind_node_count"], 2)
            self.assertEqual(summary["missing_mbn_joint_count"], 0)
            self.assertEqual(summary["joint_node_count"], 2)

            root_node = next(node for node in document["nodes"] if node["name"] == "joint_AAAABBBB")
            child_node = next(node for node in document["nodes"] if node["name"] == "joint_CCCCDDDD")
            self.assertEqual(root_node["matrix"][12:15], [1.0, 2.0, 3.0])
            self.assertEqual(child_node["extras"]["source"], "MBN bind pose")
            self.assertEqual(document["skins"][0]["extras"]["missing_mbn_node_hashes"], [])

    def test_write_gltf_skips_mbn_load_for_unweighted_meshes(self) -> None:
        unweighted_vertices = [
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (0.0, 0.0, 0.0)),
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (1.0, 0.0, 0.0)),
            make_vertex((0, 0, 0, 0, 0, 0, 0, 0), (0.0, 1.0, 0.0)),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gltf_path = root / "sample.gltf"
            with mock.patch(
                "age_gltf_tool.load_combined_mbn_bind_pose",
                side_effect=AssertionError("should not load mbn"),
            ):
                summary = write_gltf(gltf_path, [(make_mesh_info(), unweighted_vertices, [(1, 2, 3)])], mbn_root=root)

            document = json.loads(gltf_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["weighted_vertex_count"], 0)
            self.assertEqual(summary["skin_count"], 0)
            self.assertEqual(summary["mbn_bind_node_count"], 0)
            self.assertNotIn("skins", document)

    @staticmethod
    def write_mbn(path: Path, bone_id: int, parent_id: int, location: tuple[float, float, float]) -> None:
        data = bytearray(0x48)
        struct.pack_into("<II", data, 0, bone_id, parent_id)
        struct.pack_into("<3f", data, 0x0C, *location)
        struct.pack_into("<9f", data, 0x18, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        struct.pack_into("<3f", data, 0x3C, 1.0, 1.0, 1.0)
        path.write_bytes(data)


if __name__ == "__main__":
    unittest.main()



