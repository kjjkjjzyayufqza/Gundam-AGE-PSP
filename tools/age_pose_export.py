#!/usr/bin/env python3
"""Export an animation-posed OBJ for Gundam AGE PSP node-weighted meshes.

The animation JSON is produced by tools/StudioElevenAnimationProbe, which calls
Tiniifan's StudioElevenLib AnimationManager directly. This tool combines that
output with AGE PSP XMPR node tables, 8-byte implicit node weights, normalized
signed 16-bit bind-pose positions, and MBN bind transforms.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from age_xmpr_tool import (  # noqa: E402
    Vertex,
    decode_mesh,
    geometry_stats,
    iter_prm_inputs,
    write_obj,
)
from age_xpck_tool import XpckError  # noqa: E402


Matrix4 = tuple[float, ...]


def identity_matrix() -> Matrix4:
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


def matrix_multiply(a: Matrix4, b: Matrix4) -> Matrix4:
    out = [0.0] * 16
    for row in range(4):
        for col in range(4):
            out[row * 4 + col] = sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4))
    return tuple(out)


def affine_inverse(matrix: Matrix4) -> Matrix4:
    a, b, c = matrix[0], matrix[1], matrix[2]
    d, e, f = matrix[4], matrix[5], matrix[6]
    g, h, i = matrix[8], matrix[9], matrix[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) <= 1e-12:
        raise XpckError("cannot invert singular MBN bind matrix")
    inv_det = 1.0 / det
    inverse3 = (
        (e * i - f * h) * inv_det,
        (c * h - b * i) * inv_det,
        (b * f - c * e) * inv_det,
        (f * g - d * i) * inv_det,
        (a * i - c * g) * inv_det,
        (c * d - a * f) * inv_det,
        (d * h - e * g) * inv_det,
        (b * g - a * h) * inv_det,
        (a * e - b * d) * inv_det,
    )
    tx, ty, tz = matrix[3], matrix[7], matrix[11]
    inverse_translation = (
        -(inverse3[0] * tx + inverse3[1] * ty + inverse3[2] * tz),
        -(inverse3[3] * tx + inverse3[4] * ty + inverse3[5] * tz),
        -(inverse3[6] * tx + inverse3[7] * ty + inverse3[8] * tz),
    )
    return (
        inverse3[0], inverse3[1], inverse3[2], inverse_translation[0],
        inverse3[3], inverse3[4], inverse3[5], inverse_translation[1],
        inverse3[6], inverse3[7], inverse3[8], inverse_translation[2],
        0.0, 0.0, 0.0, 1.0,
    )


def transform_point(matrix: Matrix4, point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )


def quaternion_matrix(value: tuple[float, float, float, float]) -> Matrix4:
    x, y, z, w = value
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1e-12:
        return identity_matrix()
    x, y, z, w = x / length, y / length, z / length, w / length
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), 0.0,
        2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), 0.0,
        2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


def invert_quaternion(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, z, w = value
    length_squared = x * x + y * y + z * z + w * w
    if length_squared <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (-x / length_squared, -y / length_squared, -z / length_squared, w / length_squared)


def matrix3_to_quaternion(values: tuple[float, ...]) -> tuple[float, float, float, float]:
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = values
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        return ((m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, 0.25 * scale)
    if m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (0.25 * scale, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale)
    if m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m01 + m10) / scale, 0.25 * scale, (m12 + m21) / scale, (m02 - m20) / scale)
    scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m02 + m20) / scale, (m12 + m21) / scale, 0.25 * scale, (m10 - m01) / scale)


def srt_matrix(
    location: tuple[float, float, float],
    rotation: tuple[float, float, float, float],
    scale: tuple[float, float, float],
) -> Matrix4:
    rotation_matrix = quaternion_matrix(rotation)
    scale_matrix = (
        scale[0], 0.0, 0.0, 0.0,
        0.0, scale[1], 0.0, 0.0,
        0.0, 0.0, scale[2], 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    translation_matrix = (
        1.0, 0.0, 0.0, location[0],
        0.0, 1.0, 0.0, location[1],
        0.0, 0.0, 1.0, location[2],
        0.0, 0.0, 0.0, 1.0,
    )
    return matrix_multiply(translation_matrix, matrix_multiply(rotation_matrix, scale_matrix))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def quaternion_slerp(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    dot = sum(a[i] * b[i] for i in range(4))
    if dot < 0.0:
        b = tuple(-value for value in b)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        result = tuple(lerp(a[i], b[i], t) for i in range(4))
        length = math.sqrt(sum(value * value for value in result))
        return tuple(value / length for value in result) if length > 1e-12 else (0.0, 0.0, 0.0, 1.0)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    left = math.sin((1.0 - t) * theta) / sin_theta
    right = math.sin(t * theta) / sin_theta
    return tuple(left * a[i] + right * b[i] for i in range(4))


def frame_vector(frame: dict) -> tuple[float, ...]:
    value = frame["value"]
    return tuple(float(value[key]) for key in ("X", "Y", "Z", "W") if key in value)


def evaluate_frames(frames: list[dict], frame: float, default: tuple[float, ...], rotation: bool = False) -> tuple[float, ...]:
    if not frames:
        return default
    ordered = sorted(frames, key=lambda item: item["Key"])
    if frame <= ordered[0]["Key"]:
        return frame_vector(ordered[0])
    if frame >= ordered[-1]["Key"]:
        return frame_vector(ordered[-1])
    for left, right in zip(ordered, ordered[1:]):
        if left["Key"] <= frame <= right["Key"]:
            span = right["Key"] - left["Key"]
            t = 0.0 if span == 0 else (frame - left["Key"]) / span
            a, b = frame_vector(left), frame_vector(right)
            if rotation:
                return quaternion_slerp(a, b, t)  # type: ignore[arg-type]
            return tuple(lerp(a[i], b[i], t) for i in range(len(a)))
    return default


def animation_node_names(data: dict) -> set[str]:
    return {
        str(node["Name"]).upper()
        for track in data.get("tracks", [])
        for node in track.get("nodes", [])
        if node.get("Name")
    }


def select_representative_frame(
    data: dict,
    relevant_nodes: set[str],
    visibility_threshold: float = 0.01,
) -> int:
    scale_track = next((track for track in data.get("tracks", []) if track.get("Name") == "BoneScale"), None)
    if not scale_track:
        return 0

    normalized_nodes = {name.upper() for name in relevant_nodes}
    scale_nodes = {
        str(node["Name"]).upper(): node.get("frames", [])
        for node in scale_track.get("nodes", [])
        if node.get("Name") and (not normalized_nodes or str(node["Name"]).upper() in normalized_nodes)
    }
    if not scale_nodes:
        return 0

    frame_count = max(0, int(data.get("FrameCount", 0)))
    best_frame = 0
    best_score: tuple[int, float, int] | None = None
    for frame in range(frame_count + 1):
        visible = 0
        unit_distance = 0.0
        for frames in scale_nodes.values():
            scale = evaluate_frames(frames, frame, (1.0, 1.0, 1.0))
            magnitudes = [max(abs(component), 1e-8) for component in scale[:3]]
            if min(magnitudes) > visibility_threshold:
                visible += 1
            unit_distance += sum(abs(math.log(component)) for component in magnitudes)
        score = (visible, -unit_distance, -frame)
        if best_score is None or score > best_score:
            best_score = score
            best_frame = frame
    return best_frame


def evaluate_animation_pose(
    data: dict,
    frame: float,
    rotation_mode: str = "studioeleven",
    defaults: dict[str, dict] | None = None,
) -> dict[str, dict]:
    if rotation_mode not in {"studioeleven", "inverse"}:
        raise XpckError(f"unknown rotation mode: {rotation_mode}")
    tracks = {track["Name"]: track for track in data["tracks"]}
    defaults = defaults or {}
    node_names = animation_node_names(data) | set(defaults)
    pose = {}
    for name in node_names:
        default = defaults.get(name, {})
        location_node = next((node for node in tracks.get("BoneLocation", {}).get("nodes", []) if node["Name"].upper() == name), None)
        rotation_node = next((node for node in tracks.get("BoneRotation", {}).get("nodes", []) if node["Name"].upper() == name), None)
        scale_node = next((node for node in tracks.get("BoneScale", {}).get("nodes", []) if node["Name"].upper() == name), None)
        location = evaluate_frames(
            location_node["frames"] if location_node else [],
            frame,
            default.get("location", (0.0, 0.0, 0.0)),
        )
        rotation = evaluate_frames(
            rotation_node["frames"] if rotation_node else [],
            frame,
            default.get("rotation", (0.0, 0.0, 0.0, 1.0)),
            rotation=True,
        )
        if rotation_mode == "inverse" and rotation_node:
            rotation = invert_quaternion(rotation)  # type: ignore[arg-type]
        scale = evaluate_frames(
            scale_node["frames"] if scale_node else [],
            frame,
            default.get("scale", (1.0, 1.0, 1.0)),
        )
        pose[name] = {
            "location": location,
            "rotation": rotation,
            "scale": scale,
            "local_matrix": srt_matrix(location, rotation, scale),  # type: ignore[arg-type]
        }
    return pose


def load_animation_pose(
    path: Path,
    frame: float,
    rotation_mode: str = "studioeleven",
    defaults: dict[str, dict] | None = None,
) -> tuple[dict[str, dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return evaluate_animation_pose(data, frame, rotation_mode, defaults), data


def load_mbn_bind_pose(root: Path) -> tuple[dict[str, str | None], dict[str, dict]]:
    parents = {}
    bind_pose = {}
    for path in sorted(root.rglob("*.mbn")):
        data = path.read_bytes()
        if len(data) < 0x48:
            continue
        bone_id, parent_id = struct.unpack_from("<II", data, 0)
        name = f"{bone_id:08X}"
        parents[name] = f"{parent_id:08X}" if parent_id else None
        location = struct.unpack_from("<3f", data, 0x0C)
        file_rotation = struct.unpack_from("<9f", data, 0x18)
        rotation_matrix = (
            file_rotation[0], file_rotation[3], file_rotation[6],
            file_rotation[1], file_rotation[4], file_rotation[7],
            file_rotation[2], file_rotation[5], file_rotation[8],
        )
        rotation = matrix3_to_quaternion(rotation_matrix)
        scale = struct.unpack_from("<3f", data, 0x3C)
        bind_pose[name] = {
            "location": location,
            "rotation": rotation,
            "scale": scale,
            "local_matrix": srt_matrix(location, rotation, scale),
        }
    return parents, bind_pose


def build_global_matrices(pose: dict[str, dict], parents: dict[str, str | None]) -> dict[str, Matrix4]:
    global_matrices: dict[str, Matrix4] = {}
    visiting = set()

    def resolve(name: str) -> Matrix4:
        if name in global_matrices:
            return global_matrices[name]
        if name in visiting:
            raise XpckError(f"MBN parent cycle at {name}")
        visiting.add(name)
        local = pose.get(name, {}).get("local_matrix", identity_matrix())
        parent = parents.get(name)
        if parent and parent in pose:
            result = matrix_multiply(resolve(parent), local)
        else:
            result = local
        visiting.remove(name)
        global_matrices[name] = result
        return result

    for node_name in pose:
        resolve(node_name)
    return global_matrices


def build_skinning_matrices(
    target_pose: dict[str, dict],
    bind_pose: dict[str, dict],
    parents: dict[str, str | None],
) -> dict[str, Matrix4]:
    target_global = build_global_matrices(target_pose, parents)
    bind_global = build_global_matrices(bind_pose, parents)
    return {
        name: matrix_multiply(target_global[name], affine_inverse(bind_global[name]))
        for name in target_global.keys() & bind_global.keys()
    }


def pose_vertex(
    vertex: Vertex,
    node_hashes: list[str],
    matrices: dict[str, Matrix4],
) -> tuple[Vertex, bool]:
    if vertex.position_raw_s16 is None or vertex.implicit_node_weights_u8 is None or not node_hashes:
        return vertex, False

    weighted = [0.0, 0.0, 0.0]
    weight_sum = 0.0
    # XPVB type-2 positions are normalized signed 16-bit bind-pose values.
    # The supplied matrices remove the MBN bind transform before applying the
    # sampled XMTN target transform.
    local = vertex.position
    for index, raw_weight in enumerate(vertex.implicit_node_weights_u8):
        if raw_weight == 0 or index >= len(node_hashes):
            continue
        node_name = node_hashes[index].upper()
        matrix = matrices.get(node_name)
        if matrix is None:
            continue
        weight = min(raw_weight, 128) / 128.0
        point = transform_point(matrix, local)
        for axis in range(3):
            weighted[axis] += point[axis] * weight
        weight_sum += weight

    if weight_sum <= 1e-12:
        return vertex, False
    position = tuple(value / weight_sum for value in weighted)
    return replace(vertex, position=position), True


def export_posed_obj(
    root: Path,
    animation_json: Path,
    frame: float,
    out_path: Path,
    manifest_path: Path | None,
    triangulation: str,
    keep_degenerate_faces: bool,
    mtllib: str | None,
    rotation_mode: str = "studioeleven",
) -> dict:
    parents, bind_pose = load_mbn_bind_pose(root)
    pose, animation = load_animation_pose(animation_json, frame, rotation_mode, bind_pose)
    matrices = build_skinning_matrices(pose, bind_pose, parents)

    meshes = []
    transformed_vertices = 0
    for path in iter_prm_inputs([str(root)]):
        info, vertices, faces = decode_mesh(path, triangulation, not keep_degenerate_faces)
        posed_vertices = []
        for vertex in vertices:
            posed, transformed = pose_vertex(vertex, info.node_hashes, matrices)
            posed_vertices.append(posed)
            transformed_vertices += int(transformed)

        geometry, warnings = geometry_stats(
            posed_vertices,
            faces,
            faces,
            info.xpvb.position_format,
            skinned_bind_pose=False,
        )
        geometry = replace(geometry, position_semantic="animated_pose_position")
        info = replace(
            info,
            geometry=geometry,
            warnings=info.warnings
            + warnings
            + [
                f"Applied StudioElevenLib animation pose {animation['AnimationName']} at frame {frame:g}.",
                "Bind-pose positions were transformed by XMTN global matrices multiplied by inverse MBN bind matrices.",
                f"Animation quaternion mode: {rotation_mode}.",
            ],
        )
        meshes.append((info, posed_vertices, faces))

    write_obj(out_path, meshes, mtllib)
    manifest = {
        "obj": str(out_path),
        "mtllib": mtllib,
        "input": str(root),
        "animation_json": str(animation_json),
        "animation_name": animation["AnimationName"],
        "animation_parser": animation.get("parser"),
        "frame": frame,
        "rotation_mode": rotation_mode,
        "status": "experimental_animation_channel_space",
        "mesh_count": len(meshes),
        "transformed_vertices": transformed_vertices,
        "meshes": [asdict(mesh[0]) for mesh in meshes],
        "notes": [
            "Animation JSON was produced by the StudioElevenAnimationProbe wrapper around Tiniifan/StudioElevenLib.",
            "Pose export uses normalized signed 16-bit bind-pose positions and implicit 8-byte node weights.",
            "Skinning matrices use animated_global * inverse(bind_global), with bind SRT decoded from MBN.",
            "Animation channel-space reconstruction is not yet visually validated for complete mobile-suit meshes.",
            "studioeleven quaternion mode follows Tiniifan's current Blender importer; inverse is available for Metanoia-style comparison.",
        ],
    }
    manifest_path = manifest_path or out_path.with_suffix(".obj.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def command_export(args: argparse.Namespace) -> int:
    out_path = Path(args.out)
    manifest_path = Path(args.json) if args.json else out_path.with_suffix(".obj.json")
    manifest = export_posed_obj(
        root=Path(args.input),
        animation_json=Path(args.animation_json),
        frame=args.frame,
        out_path=out_path,
        manifest_path=manifest_path,
        triangulation=args.triangulation,
        keep_degenerate_faces=args.keep_degenerate_faces,
        mtllib=args.mtllib,
        rotation_mode=args.rotation_mode,
    )
    print(f"Wrote posed OBJ: {out_path}")
    print(f"Meshes: {manifest['mesh_count']}")
    print(f"Transformed vertices: {manifest['transformed_vertices']}")
    print(f"Manifest: {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export an XMTN-posed OBJ for Gundam AGE PSP node-weighted meshes.")
    parser.add_argument("input", help="extracted XPCK model directory")
    parser.add_argument("--animation-json", required=True, help="JSON from StudioElevenAnimationProbe")
    parser.add_argument("--frame", type=float, default=0.0, help="animation frame to sample")
    parser.add_argument("--out", required=True, help="posed OBJ output path")
    parser.add_argument("--json", help="posed OBJ manifest path")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--keep-degenerate-faces", action="store_true")
    parser.add_argument("--mtllib", help="optional MTL filename to reference")
    parser.add_argument(
        "--rotation-mode",
        choices=["studioeleven", "inverse"],
        default="studioeleven",
        help="quaternion convention; inverse is a Metanoia-style diagnostic",
    )
    parser.set_defaults(func=command_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())





