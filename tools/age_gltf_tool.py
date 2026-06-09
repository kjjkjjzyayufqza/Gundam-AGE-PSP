"""Static glTF 2.0 exporter for decoded Gundam AGE PSP meshes.

This exporter preserves decoded skin weights without executing animation data.
Skinned meshes use static MBN bind nodes when available, with identity
fallbacks for missing hashes. This keeps bind-pose geometry stable while
carrying JOINTS_0/WEIGHTS_0 data for later skeleton refinement.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from age_xmpr_tool import (  # noqa: E402
    MeshExport,
    Vertex,
    decode_mesh,
    iter_prm_inputs,
    material_name_for_mesh,
    obj_identifier,
    vertex_weight_records,
)
from age_pose_export import affine_inverse, build_global_matrices, load_mbn_bind_pose  # noqa: E402
from age_xpck_tool import XpckError  # noqa: E402


COMPONENT_FLOAT = 5126
COMPONENT_UNSIGNED_BYTE = 5121
COMPONENT_UNSIGNED_SHORT = 5123
COMPONENT_UNSIGNED_INT = 5125
TARGET_ARRAY_BUFFER = 34962
TARGET_ELEMENT_ARRAY_BUFFER = 34963
MODE_POINTS = 0
MODE_TRIANGLES = 4
IDENTITY_MAT4 = (
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)


def gltf_matrix_from_row_major(matrix: tuple[float, ...]) -> list[float]:
    return [
        matrix[0], matrix[4], matrix[8], matrix[12],
        matrix[1], matrix[5], matrix[9], matrix[13],
        matrix[2], matrix[6], matrix[10], matrix[14],
        matrix[3], matrix[7], matrix[11], matrix[15],
    ]


def load_combined_mbn_bind_pose(roots: list[Path]) -> tuple[dict[str, str | None], dict[str, dict]]:
    parents: dict[str, str | None] = {}
    bind_pose: dict[str, dict] = {}
    for root in roots:
        root_parents, root_bind_pose = load_mbn_bind_pose(root)
        for name, pose in root_bind_pose.items():
            if name not in bind_pose:
                bind_pose[name] = pose
                parents[name] = root_parents.get(name)
    return parents, bind_pose


class GltfBufferBuilder:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.buffer_views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add_view(self, payload: bytes, target: int | None = None) -> int:
        while len(self.buffer) % 4:
            self.buffer.append(0)
        offset = len(self.buffer)
        self.buffer.extend(payload)
        while len(self.buffer) % 4:
            self.buffer.append(0)
        view: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(payload),
        }
        if target is not None:
            view["target"] = target
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def add_accessor(
        self,
        payload: bytes,
        component_type: int,
        accessor_type: str,
        count: int,
        target: int | None = None,
        min_values: list[float] | None = None,
        max_values: list[float] | None = None,
    ) -> int:
        view_index = self.add_view(payload, target)
        accessor: dict[str, Any] = {
            "bufferView": view_index,
            "byteOffset": 0,
            "componentType": component_type,
            "count": count,
            "type": accessor_type,
        }
        if min_values is not None:
            accessor["min"] = min_values
        if max_values is not None:
            accessor["max"] = max_values
        self.accessors.append(accessor)
        return len(self.accessors) - 1


def pack_floats(values: list[float]) -> bytes:
    if not values:
        return b""
    return struct.pack("<" + "f" * len(values), *values)


def pack_unsigned(values: list[int], component_type: int) -> bytes:
    if not values:
        return b""
    if component_type == COMPONENT_UNSIGNED_BYTE:
        return bytes(values)
    if component_type == COMPONENT_UNSIGNED_SHORT:
        return struct.pack("<" + "H" * len(values), *values)
    if component_type == COMPONENT_UNSIGNED_INT:
        return struct.pack("<" + "I" * len(values), *values)
    raise ValueError(f"unsupported unsigned component type: {component_type}")


def vector_min_max(vertices: list[Vertex]) -> tuple[list[float], list[float]]:
    xs = [vertex.position[0] for vertex in vertices]
    ys = [vertex.position[1] for vertex in vertices]
    zs = [vertex.position[2] for vertex in vertices]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def material_texture_map(material_records: list[dict[str, Any]] | None) -> dict[str, str]:
    if not material_records:
        return {}
    result = {}
    for record in material_records:
        name = record.get("obj_material_name")
        map_kd = record.get("map_Kd")
        if name and map_kd:
            result[str(name)] = str(map_kd).replace("\\", "/")
    return result


def build_joint_weight_payloads(
    vertices: list[Vertex],
    node_hashes: list[str],
) -> tuple[dict[str, list[int] | list[float]], int, int]:
    all_influences: list[list[tuple[int, float]]] = []
    max_influence_count = 0
    weighted_vertex_count = 0

    for vertex in vertices:
        records = [record for record in vertex_weight_records(vertex, node_hashes) if record["node_hash"] is not None]
        influences = [(int(record["slot"]), float(record["weight_raw128"])) for record in records]
        total = sum(weight for _slot, weight in influences)
        if total > 0:
            influences = [(slot, weight / total) for slot, weight in influences]
            weighted_vertex_count += 1
        else:
            influences = [(0, 1.0)]
        max_influence_count = max(max_influence_count, len(influences))
        all_influences.append(influences)

    set_count = 2 if max_influence_count > 4 else 1
    joints_0: list[int] = []
    weights_0: list[float] = []
    joints_1: list[int] = []
    weights_1: list[float] = []
    for influences in all_influences:
        padded = influences[:8] + [(0, 0.0)] * max(0, 8 - len(influences))
        for slot, weight in padded[:4]:
            joints_0.append(slot)
            weights_0.append(weight)
        if set_count > 1:
            for slot, weight in padded[4:8]:
                joints_1.append(slot)
                weights_1.append(weight)

    payloads: dict[str, list[int] | list[float]] = {
        "JOINTS_0": joints_0,
        "WEIGHTS_0": weights_0,
    }
    if set_count > 1:
        payloads["JOINTS_1"] = joints_1
        payloads["WEIGHTS_1"] = weights_1
    return payloads, weighted_vertex_count, max_influence_count


def write_gltf(
    path: Path,
    meshes: list[MeshExport],
    material_records: list[dict[str, Any]] | None = None,
    material_name_overrides: dict[str, str] | None = None,
    mbn_root: Path | None = None,
    mbn_roots: list[Path] | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    bin_path = path.with_suffix(".bin")
    buffer = GltfBufferBuilder()

    gltf: dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "Gundam AGE PSP research age_gltf_tool.py",
            "extras": {
                "note": "Static bind-pose export; animations are intentionally not executed.",
                "joint_nodes": "MBN bind nodes are used when available; missing nodes fall back to identity placeholders.",
            },
        },
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "buffers": [{"uri": bin_path.name, "byteLength": 0}],
        "bufferViews": buffer.buffer_views,
        "accessors": buffer.accessors,
    }

    texture_by_material = material_texture_map(material_records)
    image_index_by_uri: dict[str, int] = {}
    texture_index_by_uri: dict[str, int] = {}
    material_index_by_name: dict[str, int] = {}

    def ensure_texture(uri: str) -> int:
        if uri not in image_index_by_uri:
            gltf.setdefault("images", []).append({"uri": uri})
            image_index_by_uri[uri] = len(gltf["images"]) - 1
        if uri not in texture_index_by_uri:
            gltf.setdefault("samplers", [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}])
            gltf.setdefault("textures", []).append({"sampler": 0, "source": image_index_by_uri[uri]})
            texture_index_by_uri[uri] = len(gltf["textures"]) - 1
        return texture_index_by_uri[uri]

    def ensure_material(name: str) -> int:
        if name in material_index_by_name:
            return material_index_by_name[name]
        material: dict[str, Any] = {
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "extras": {"source": "AGE PSP MTR/TXP binding heuristic"},
        }
        texture_uri = texture_by_material.get(name)
        if texture_uri:
            material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": ensure_texture(texture_uri)}
        gltf["materials"].append(material)
        material_index_by_name[name] = len(gltf["materials"]) - 1
        return material_index_by_name[name]

    root_nodes: list[int] = gltf["scenes"][0]["nodes"]
    weighted_mesh_count = 0
    weighted_vertex_count = 0
    max_influence_count = 0
    referenced_joint_count = 0
    missing_mbn_joint_hashes: set[str] = set()

    referenced_hashes = {
        node_hash.upper()
        for info, vertices, _faces in meshes
        if any(vertex_weight_records(vertex, info.node_hashes) for vertex in vertices)
        for node_hash in info.node_hashes
    }
    mbn_parents: dict[str, str | None] = {}
    mbn_bind_pose: dict[str, dict] = {}
    mbn_global: dict[str, tuple[float, ...]] = {}
    roots = list(mbn_roots or [])
    if mbn_root is not None:
        roots.insert(0, mbn_root)
    if roots and referenced_hashes:
        mbn_parents, mbn_bind_pose = load_combined_mbn_bind_pose(roots)
        mbn_global = build_global_matrices(mbn_bind_pose, mbn_parents)

    joint_node_by_hash: dict[str, int] = {}

    def ensure_joint_node(node_hash: str) -> int:
        node_hash = node_hash.upper()
        if node_hash in joint_node_by_hash:
            return joint_node_by_hash[node_hash]
        parent = mbn_parents.get(node_hash)
        parent_index = ensure_joint_node(parent) if parent and parent in mbn_bind_pose else None
        local_matrix = mbn_bind_pose.get(node_hash, {}).get("local_matrix", IDENTITY_MAT4)
        if node_hash not in mbn_bind_pose:
            missing_mbn_joint_hashes.add(node_hash)
        gltf["nodes"].append(
            {
                "name": f"joint_{node_hash}",
                "matrix": gltf_matrix_from_row_major(local_matrix),
                "extras": {
                    "node_hash": node_hash,
                    "source": "MBN bind pose" if node_hash in mbn_bind_pose else "XMPR node table identity fallback",
                },
            }
        )
        node_index = len(gltf["nodes"]) - 1
        joint_node_by_hash[node_hash] = node_index
        if parent_index is not None:
            gltf["nodes"][parent_index].setdefault("children", []).append(node_index)
        else:
            root_nodes.append(node_index)
        return node_index

    for mesh_index, (info, vertices, faces) in enumerate(meshes):
        if not vertices:
            continue

        positions: list[float] = []
        texcoords: list[float] = []
        has_uv = any(vertex.uv0 is not None for vertex in vertices)
        for vertex in vertices:
            positions.extend(vertex.position)
            if has_uv:
                uv = vertex.uv0 or (0.0, 0.0)
                texcoords.extend(uv)

        pos_min, pos_max = vector_min_max(vertices)
        attributes: dict[str, int] = {
            "POSITION": buffer.add_accessor(
                pack_floats(positions),
                COMPONENT_FLOAT,
                "VEC3",
                len(vertices),
                TARGET_ARRAY_BUFFER,
                pos_min,
                pos_max,
            )
        }
        if has_uv:
            attributes["TEXCOORD_0"] = buffer.add_accessor(
                pack_floats(texcoords),
                COMPONENT_FLOAT,
                "VEC2",
                len(vertices),
                TARGET_ARRAY_BUFFER,
            )

        skin_index = None
        has_weights = bool(info.node_hashes) and any(vertex_weight_records(vertex, info.node_hashes) for vertex in vertices)
        if has_weights:
            payloads, mesh_weighted_vertices, mesh_max_influences = build_joint_weight_payloads(vertices, info.node_hashes)
            weighted_mesh_count += 1
            weighted_vertex_count += mesh_weighted_vertices
            max_influence_count = max(max_influence_count, mesh_max_influences)
            joint_component = COMPONENT_UNSIGNED_BYTE if len(info.node_hashes) <= 255 else COMPONENT_UNSIGNED_SHORT
            attributes["JOINTS_0"] = buffer.add_accessor(
                pack_unsigned(payloads["JOINTS_0"], joint_component),  # type: ignore[arg-type]
                joint_component,
                "VEC4",
                len(vertices),
                TARGET_ARRAY_BUFFER,
            )
            attributes["WEIGHTS_0"] = buffer.add_accessor(
                pack_floats(payloads["WEIGHTS_0"]),  # type: ignore[arg-type]
                COMPONENT_FLOAT,
                "VEC4",
                len(vertices),
                TARGET_ARRAY_BUFFER,
            )
            if "JOINTS_1" in payloads:
                attributes["JOINTS_1"] = buffer.add_accessor(
                    pack_unsigned(payloads["JOINTS_1"], joint_component),  # type: ignore[arg-type]
                    joint_component,
                    "VEC4",
                    len(vertices),
                    TARGET_ARRAY_BUFFER,
                )
                attributes["WEIGHTS_1"] = buffer.add_accessor(
                    pack_floats(payloads["WEIGHTS_1"]),  # type: ignore[arg-type]
                    COMPONENT_FLOAT,
                    "VEC4",
                    len(vertices),
                    TARGET_ARRAY_BUFFER,
                )

            joint_nodes = [ensure_joint_node(node_hash) for node_hash in info.node_hashes]
            referenced_joint_count += len(joint_nodes)
            inverse_bind: list[float] = []
            for node_hash in info.node_hashes:
                global_matrix = mbn_global.get(node_hash.upper(), IDENTITY_MAT4)
                inverse_bind.extend(gltf_matrix_from_row_major(affine_inverse(global_matrix)))
            inverse_bind_accessor = buffer.add_accessor(
                pack_floats(inverse_bind),
                COMPONENT_FLOAT,
                "MAT4",
                len(joint_nodes),
            )
            gltf.setdefault("skins", []).append(
                {
                    "name": f"{obj_identifier(info.mesh_name, f'mesh_{mesh_index}')}_identity_skin",
                    "joints": joint_nodes,
                    "inverseBindMatrices": inverse_bind_accessor,
                    "extras": {
                        "source": "XMPR node hashes",
                        "semantic": "MBN bind skin for static weight preservation"
                        if mbn_bind_pose
                        else "identity bind skin for static weight preservation",
                        "node_hashes": info.node_hashes,
                        "missing_mbn_node_hashes": [
                            node_hash
                            for node_hash in info.node_hashes
                            if node_hash.upper() not in mbn_bind_pose
                        ],
                    },
                }
            )
            skin_index = len(gltf["skins"]) - 1

        primitive: dict[str, Any] = {
            "attributes": attributes,
            "material": ensure_material(material_name_for_mesh(info, material_name_overrides)),
            "mode": MODE_POINTS if not faces else MODE_TRIANGLES,
            "extras": {
                "source": info.source,
                "mesh_name": info.mesh_name,
                "material_name": info.material_name,
                "position_semantic": info.geometry.position_semantic,
            },
        }
        if faces:
            indices = [index - 1 for face in faces for index in face]
            index_component = COMPONENT_UNSIGNED_SHORT if max(indices, default=0) <= 65535 else COMPONENT_UNSIGNED_INT
            primitive["indices"] = buffer.add_accessor(
                pack_unsigned(indices, index_component),
                index_component,
                "SCALAR",
                len(indices),
                TARGET_ELEMENT_ARRAY_BUFFER,
                [min(indices)] if indices else None,
                [max(indices)] if indices else None,
            )

        gltf["meshes"].append(
            {
                "name": obj_identifier(info.mesh_name, f"mesh_{mesh_index}"),
                "primitives": [primitive],
                "extras": {"source": info.source, "node_hashes": info.node_hashes},
            }
        )
        gltf_mesh_index = len(gltf["meshes"]) - 1
        mesh_node: dict[str, Any] = {
            "name": obj_identifier(info.mesh_name, f"mesh_{mesh_index}"),
            "mesh": gltf_mesh_index,
            "extras": {"source": info.source},
        }
        if skin_index is not None:
            mesh_node["skin"] = skin_index
        gltf["nodes"].append(mesh_node)
        root_nodes.append(len(gltf["nodes"]) - 1)

    gltf["buffers"][0]["byteLength"] = len(buffer.buffer)
    if not gltf["materials"]:
        del gltf["materials"]
    if not gltf.get("images"):
        gltf.pop("images", None)
    if not gltf.get("textures"):
        gltf.pop("textures", None)
    if not gltf.get("samplers"):
        gltf.pop("samplers", None)

    bin_path.write_bytes(bytes(buffer.buffer))
    path.write_text(json.dumps(gltf, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "gltf": str(path),
        "bin": str(bin_path),
        "mesh_count": len(gltf["meshes"]),
        "primitive_count": sum(len(mesh["primitives"]) for mesh in gltf["meshes"]),
        "material_count": len(gltf.get("materials", [])),
        "texture_count": len(gltf.get("textures", [])),
        "skin_count": len(gltf.get("skins", [])),
        "joint_node_count": len(joint_node_by_hash),
        "referenced_joint_count": referenced_joint_count,
        "mbn_bind_node_count": len(mbn_bind_pose),
        "mbn_roots": [str(root) for root in roots],
        "missing_mbn_joint_count": len(missing_mbn_joint_hashes),
        "missing_mbn_joint_hashes": sorted(missing_mbn_joint_hashes),
        "weighted_mesh_count": weighted_mesh_count,
        "weighted_vertex_count": weighted_vertex_count,
        "max_influence_count": max_influence_count,
        "notes": [
            "Static glTF export preserves decoded weights without executing action or animation files.",
            "Joint nodes use MBN bind transforms when .mbn files are present; missing nodes use identity fallbacks.",
        ],
    }


def command_export_gltf(args: argparse.Namespace) -> int:
    paths = iter_prm_inputs(args.inputs)
    meshes = [decode_mesh(path, args.triangulation, not args.keep_degenerate_faces) for path in paths]
    summary = write_gltf(Path(args.out), meshes, mbn_roots=[Path(item) for item in args.mbn_root])
    manifest_path = Path(args.json) if args.json else Path(args.out).with_suffix(".gltf.json")
    manifest = {
        **summary,
        "mesh_count": len(meshes),
        "meshes": [asdict(mesh[0]) for mesh in meshes],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote glTF: {args.out}")
    print(f"Binary: {summary['bin']}")
    print(f"Meshes: {summary['mesh_count']}")
    print(f"Weighted vertices: {summary['weighted_vertex_count']}")
    print(f"Manifest: {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export decoded Gundam AGE PSP meshes to static glTF 2.0.")
    parser.add_argument("inputs", nargs="+", help=".prm files or directories")
    parser.add_argument("--out", required=True, help="glTF output path")
    parser.add_argument("--json", help="summary manifest output path")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--keep-degenerate-faces", action="store_true")
    parser.add_argument("--mbn-root", action="append", default=[], help="directory containing static .mbn bind files")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_export_gltf(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())





