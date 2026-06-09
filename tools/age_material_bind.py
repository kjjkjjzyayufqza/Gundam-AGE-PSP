#!/usr/bin/env python3
"""Build a material binding manifest for Gundam AGE PSP extracted archives.

This tool records relationships that are supported by local evidence:
- PRM mesh names and material names decoded from XMPR.
- CHRP00 strings decompressed from RES.bin/RES.dec.bin.
- TXP hash words matched to CHRP00 strings using CRC32.

It does not claim to fully decode MTRP00/ATRP01. Those files are linked by
numbered stem when TXP proves the material name.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from age_xmpr_tool import decode_mesh  # noqa: E402
from age_xpck_tool import XpckError, decompress_level5  # noqa: E402


KNOWN_RESOURCE_KEYS = {
    "bb_ref_bone",
    "bb_size_x",
    "bb_size_y",
    "bb_size_z",
    "flw_cmr_type",
    "mesh_sort",
    "scale_base_one",
}


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def is_texture_projection_string(value: str | None) -> bool:
    return bool(value and "_texproj" in value)


def is_material_string(value: str | None) -> bool:
    if not value or is_texture_projection_string(value):
        return False
    if value in KNOWN_RESOURCE_KEYS or value.startswith("out_"):
        return False
    return value.startswith("DefaultLib.") or ("." in value and value.endswith("-"))


def ascii_strings(data: bytes, min_length: int = 4) -> list[dict]:
    pattern = rb"[\x20-\x7e]{" + str(min_length).encode("ascii") + rb",}"
    return [
        {"offset": match.start(), "value": match.group().decode("ascii", errors="replace")}
        for match in re.finditer(pattern, data)
    ]


def crc32_string(value: str) -> int:
    return zlib.crc32(value.encode("shift-jis")) & 0xFFFFFFFF


def read_res_payload(root: Path) -> tuple[Path | None, bytes, str]:
    for name in ("RES.dec.bin", "RES.bin"):
        path = root / name
        if not path.exists():
            continue
        data = path.read_bytes()
        if data[:4] == b"CHRP":
            return path, data, "already_decompressed"
        try:
            method, payload = decompress_level5(data)
            return path, payload, method
        except Exception:
            continue
    return None, b"", "missing"


def material_base(material_name: str) -> str:
    if material_name.startswith("DefaultLib."):
        material_name = material_name[len("DefaultLib.") :]
    material_name = material_name.rstrip("-")
    return material_name.split("-")[0]


def texture_candidates_for_material(material_name: str, texture_names: list[str]) -> list[str]:
    base = material_base(material_name)
    candidates = []
    for name in texture_names:
        if name == base or name.startswith(base + "_") or base.startswith(name):
            candidates.append(name)
    return candidates


def classify_resource_strings(strings: list[dict]) -> dict:
    values = [item["value"] for item in strings]
    materials = [value for value in values if is_material_string(value)]
    texprojs = [value for value in values if is_texture_projection_string(value)]
    meshes = [value for value in values if "_output." in value]
    texture_names = [
        value
        for value in values
        if "_" in value
        and not is_material_string(value)
        and not is_texture_projection_string(value)
        and "_output." not in value
        and value not in KNOWN_RESOURCE_KEYS
        and not value.startswith("out_")
        and not value.startswith(("c_", "l_", "r_"))
    ]
    return {
        "materials": materials,
        "texture_projections": texprojs,
        "mesh_names": meshes,
        "texture_name_candidates": texture_names,
        "all_strings": values,
    }


def probe_txp_files(root: Path, string_by_crc: dict[int, str]) -> list[dict]:
    records = []
    for path in sorted(root.glob("*.txp")):
        data = path.read_bytes()
        if len(data) < 8:
            continue
        hash_words = list(struct.unpack_from("<II", data, 0))
        matches = [{"hash": f"0x{word:08X}", "string": string_by_crc.get(word)} for word in hash_words]
        uv_scale = list(struct.unpack_from("<ff", data, 28)) if len(data) >= 36 else None
        owner_material = next((match["string"] for match in matches if is_material_string(match["string"])), None)
        texproj = next((match["string"] for match in matches if is_texture_projection_string(match["string"])), None)
        records.append(
            {
                "stem": path.stem,
                "path": str(path),
                "hash_words": [f"0x{word:08X}" for word in hash_words],
                "crc32_matches": matches,
                "owner_material": owner_material,
                "texture_projection": texproj,
                "uv_scale_candidate": uv_scale,
            }
        )
    return records


def file_if_exists(path: Path) -> str | None:
    return str(path) if path.exists() else None


def xi_for_stem(root: Path, stem: str | None) -> str | None:
    if stem is None:
        return None
    return file_if_exists(root / f"{stem}.xi")


def build_material_records(root: Path, classes: dict, txp_records: list[dict]) -> list[dict]:
    by_material = {record["owner_material"]: record for record in txp_records if record["owner_material"]}
    materials = unique_preserve_order(classes["materials"] + [record["owner_material"] for record in txp_records if record["owner_material"]])
    texture_names = classes["texture_name_candidates"]
    records = []
    for material in materials:
        txp = by_material.get(material)
        stem = txp["stem"] if txp else None
        xi_path = xi_for_stem(root, stem)
        records.append(
            {
                "material_name": material,
                "material_base": material_base(material),
                "texture_name_candidates": texture_candidates_for_material(material, texture_names),
                "txp": txp,
                "mtr_path": file_if_exists(root / f"{stem}.mtr") if stem else None,
                "atr_path": file_if_exists(root / f"{stem}.atr") if stem else None,
                "xi_path_by_txp_stem": xi_path,
                "texture_image_binding_confidence": "txp_stem_xi_match" if xi_path else "unresolved",
                "binding_confidence": "crc32_txp_owner" if txp else "resource_string_only",
            }
        )
    return records


def build_image_order_candidates(root: Path, texture_names: list[str]) -> list[dict]:
    xi_files = sorted(root.glob("*.xi"))
    pairs = []
    for index, texture_name in enumerate(texture_names):
        pairs.append(
            {
                "texture_name": texture_name,
                "xi_path_by_resource_order": str(xi_files[index]) if index < len(xi_files) else None,
                "confidence": "resource_order_heuristic",
            }
        )
    return pairs


def build_mesh_records(root: Path, material_records: list[dict]) -> list[dict]:
    materials_by_name = {record["material_name"]: record for record in material_records}
    meshes = []
    for path in sorted(root.glob("*.prm")):
        info, _, _ = decode_mesh(path, "points")
        material = materials_by_name.get(info.material_name)
        meshes.append(
            {
                "source": str(path),
                "mesh_name": info.mesh_name,
                "material_name": info.material_name,
                "material_bound": material is not None,
                "texture_name_candidates": material["texture_name_candidates"] if material else [],
                "xi_path_by_txp_stem": material["xi_path_by_txp_stem"] if material else None,
                "position_semantic": info.geometry.position_semantic,
                "vertex_count": info.vertex_count,
            }
        )
    return meshes


def apply_mesh_name_texture_candidates(material_records: list[dict], mesh_records: list[dict], image_order_candidates: list[dict]) -> None:
    texture_name_set = {str(item["texture_name"]) for item in image_order_candidates if item.get("texture_name")}
    mesh_names_by_material: dict[str, list[str]] = {}
    for mesh in mesh_records:
        material_name = str(mesh["material_name"])
        mesh_names_by_material.setdefault(material_name, [])
        mesh_name = str(mesh["mesh_name"])
        if mesh_name not in mesh_names_by_material[material_name]:
            mesh_names_by_material[material_name].append(mesh_name)

    for record in material_records:
        if record["texture_name_candidates"]:
            continue
        material_name = str(record["material_name"])
        mesh_names = mesh_names_by_material.get(material_name, [])
        candidates = [name for name in mesh_names if name in texture_name_set]
        if not candidates:
            continue
        record["texture_name_candidates"] = candidates
        if record["texture_image_binding_confidence"] == "unresolved":
            record["texture_image_binding_confidence"] = "mesh_name_resource_order_candidate"
        record["binding_confidence"] = f"{record['binding_confidence']}+mesh_name_texture_candidate"


def build_manifest(root: Path) -> dict:
    res_path, res_payload, res_compression = read_res_payload(root)
    strings = ascii_strings(res_payload) if res_payload else []
    classes = classify_resource_strings(strings)
    string_by_crc = {crc32_string(item["value"]): item["value"] for item in strings}
    txp_records = probe_txp_files(root, string_by_crc)
    material_records = build_material_records(root, classes, txp_records)
    image_order_candidates = build_image_order_candidates(root, classes["texture_name_candidates"])
    mesh_records = build_mesh_records(root, material_records)
    apply_mesh_name_texture_candidates(material_records, mesh_records, image_order_candidates)
    mesh_records = build_mesh_records(root, material_records)
    return {
        "root": str(root),
        "res_path": str(res_path) if res_path else None,
        "res_compression": res_compression,
        "resource_strings": classes,
        "txp_records": txp_records,
        "materials": material_records,
        "meshes": mesh_records,
        "image_order_candidates": image_order_candidates,
        "notes": [
            "TXP owner bindings are confirmed by CRC32 matches against CHRP00 strings.",
            "Texture image file mapping first uses direct numbered stem matches such as 001.txp -> 001.xi when present.",
            "Texture resource-order candidates are retained as a fallback because CHRP00 texture names do not yet carry direct XI paths.",
            "MTRP00 and ATRP01 files are linked by numbered stem after TXP identifies the material owner.",
        ],
    }


def command_build(args: argparse.Namespace) -> int:
    root = Path(args.input)
    manifest = build_manifest(root)
    text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(text, encoding="utf-8")
        print(f"Materials: {len(manifest['materials'])}")
        print(f"Meshes: {len(manifest['meshes'])}")
        print(f"Manifest: {json_path}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Gundam AGE PSP material binding manifest.")
    parser.add_argument("input", help="extracted XPCK directory")
    parser.add_argument("--json", help="write JSON manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_build(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())





