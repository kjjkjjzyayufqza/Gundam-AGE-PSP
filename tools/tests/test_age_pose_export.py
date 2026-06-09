from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_pose_export import (  # noqa: E402
    build_skinning_matrices,
    evaluate_animation_pose,
    pose_vertex,
    select_representative_frame,
    srt_matrix,
    transform_point,
)
from age_xmpr_tool import Vertex  # noqa: E402


class PoseExportTests(unittest.TestCase):
    def test_skinning_matrix_removes_bind_transform_before_target_transform(self) -> None:
        bind_pose = {
            "AAAABBBB": {
                "local_matrix": srt_matrix(
                    location=(10.0, 0.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                )
            }
        }
        target_pose = {
            "AAAABBBB": {
                "local_matrix": srt_matrix(
                    location=(12.0, 0.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                )
            }
        }

        matrices = build_skinning_matrices(target_pose, bind_pose, {"AAAABBBB": None})

        self.assertEqual(transform_point(matrices["AAAABBBB"], (10.0, 0.0, 0.0)), (12.0, 0.0, 0.0))

    def test_inverse_rotation_mode_is_explicit_diagnostic(self) -> None:
        data = {
            "tracks": [
                {
                    "Name": "BoneRotation",
                    "nodes": [
                        {
                            "Name": "AAAABBBB",
                            "frames": [
                                {
                                    "Key": 0,
                                    "value": {
                                        "X": 0.0,
                                        "Y": 0.0,
                                        "Z": 0.7071067811865476,
                                        "W": 0.7071067811865476,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        direct = evaluate_animation_pose(data, 0, "studioeleven")
        inverse = evaluate_animation_pose(data, 0, "inverse")
        direct_point = transform_point(direct["AAAABBBB"]["local_matrix"], (1.0, 0.0, 0.0))
        inverse_point = transform_point(inverse["AAAABBBB"]["local_matrix"], (1.0, 0.0, 0.0))

        self.assertAlmostEqual(direct_point[1], 1.0)
        self.assertAlmostEqual(inverse_point[1], -1.0)

    def test_representative_frame_prefers_visible_unit_scale_nodes(self) -> None:
        data = {
            "FrameCount": 10,
            "tracks": [
                {
                    "Name": "BoneScale",
                    "nodes": [
                        {
                            "Name": "AAAABBBB",
                            "frames": [
                                {"Key": 0, "value": {"X": 0.0001, "Y": 0.0001, "Z": 0.0001}},
                                {"Key": 10, "value": {"X": 1.0, "Y": 1.0, "Z": 1.0}},
                            ],
                        },
                        {
                            "Name": "CCCCDDDD",
                            "frames": [
                                {"Key": 0, "value": {"X": 0.0001, "Y": 0.0001, "Z": 0.0001}},
                                {"Key": 10, "value": {"X": 1.0, "Y": 1.0, "Z": 1.0}},
                            ],
                        },
                    ],
                }
            ],
        }

        frame = select_representative_frame(data, {"AAAABBBB", "CCCCDDDD"})

        self.assertEqual(frame, 10)

    def test_pose_vertex_transforms_normalized_position_not_raw_s16(self) -> None:
        vertex = Vertex(
            position=(1.0, -0.5, 0.25),
            uv0=None,
            packed_slot1_rgba=None,
            position_raw_s16=(32767, -16384, 8192),
            implicit_node_weights_u8=(128, 0, 0, 0, 0, 0, 0, 0),
        )
        matrix = srt_matrix(
            location=(10.0, 20.0, 30.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            scale=(2.0, 3.0, 4.0),
        )

        posed, transformed = pose_vertex(vertex, ["AABBCCDD"], {"AABBCCDD": matrix})

        self.assertTrue(transformed)
        self.assertAlmostEqual(posed.position[0], 12.0)
        self.assertAlmostEqual(posed.position[1], 18.5)
        self.assertAlmostEqual(posed.position[2], 31.0)


if __name__ == "__main__":
    unittest.main()



