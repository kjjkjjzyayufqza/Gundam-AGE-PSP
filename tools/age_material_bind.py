#!/usr/bin/env python3
"""Build a material binding manifest for Gundam AGE PSP extracted archives.

Native game binding (Level-5 CHRP00 / RES, matching StudioEleven layout):

1. `RES.bin` decompresses to `CHRP00`.
2. Section type 240 (`TextureData`) lists texture slots in archive order.
3. Section type 290 (`MaterialData`) names each material and links image slots
   by CRC32 to a `TextureData` entry.
4. The matching `TextureData` array index selects `NNN.xi` (same index order).

`.txp` CRC32 words still identify material / `_texproj0` owners and link
same-stem `.mtr`/`.atr` parameter files, but TXP stem is NOT used as the
primary texture-image index (that mismatch is what broke human faces/bodies).
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
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

# StudioEleven RESType values used by AGE PSP CHRP00.
RES_TYPE_MATERIAL1 = 220
RES_TYPE_MATERIAL2 = 230
RES_TYPE_TEXTURE_DATA = 240
RES_TYPE_MATERIAL_DATA = 290

MATERIAL_DATA_SIZE = 224
IMAGE_ENTRY_SIZE = 52


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


def build_string_crc_map(payload: bytes, string_offset: int) -> dict[int, str]:
    """CRC32(on-disk bytes) -> string for the CHRP string pool and ASCII runs.

    AGE stores Shift-JIS text; material names are ASCII so CRC(raw) matches
    CRC(Shift-JIS encode of the decoded name). Hashing raw pool bytes avoids
    encode/decode round-trips breaking non-ASCII texture names.
    """
    out: dict[int, str] = {}
    if 0 <= string_offset < len(payload):
        blob = payload[string_offset:]
        i = 0
        while i < len(blob):
            if blob[i] == 0:
                i += 1
                continue
            end = blob.find(b"\x00", i)
            if end < 0:
                end = len(blob)
            raw = blob[i:end]
            try:
                text = raw.decode("shift_jis")
            except Exception:
                text = raw.decode("latin1", errors="replace")
            if raw:
                out[zlib.crc32(raw) & 0xFFFFFFFF] = text
            i = end + 1
    for item in ascii_strings(payload):
        out.setdefault(crc32_string(item["value"]), item["value"])
    return out


def parse_chrp_sections(payload: bytes) -> dict:
    """Parse CHRP00 material/texture tables (StudioEleven RES header layout)."""
    if len(payload) < 20 or payload[:4] != b"CHRP":
        return {"ok": False, "error": "not_chrp", "texture_data": [], "material_data": [], "sections": []}

    string_offset = struct.unpack_from("<H", payload, 8)[0] << 2
    mat_table_offset = struct.unpack_from("<H", payload, 12)[0] << 2
    mat_table_count = struct.unpack_from("<H", payload, 14)[0]
    node_table_offset = struct.unpack_from("<H", payload, 16)[0] << 2
    node_table_count = struct.unpack_from("<H", payload, 18)[0]

    sections = []
    for base, count, group in (
        (mat_table_offset, mat_table_count, "material"),
        (node_table_offset, node_table_count, "node"),
    ):
        for i in range(count):
            entry_off = base + i * 8
            if entry_off + 8 > len(payload):
                break
            data_off_q, entry_count, res_type, length = struct.unpack_from("<HHHH", payload, entry_off)
            sections.append(
                {
                    "group": group,
                    "data_offset": data_off_q << 2,
                    "count": entry_count,
                    "type": res_type,
                    "length": length,
                }
            )

    strings = build_string_crc_map(payload, string_offset)

    texture_data = []
    material_data = []
    for section in sections:
        if section["count"] <= 0:
            continue
        data_offset = section["data_offset"]
        length = section["length"]
        if section["type"] == RES_TYPE_TEXTURE_DATA and length >= 8:
            for i in range(section["count"]):
                base = data_offset + i * length
                if base + 8 > len(payload):
                    break
                name_crc = struct.unpack_from("<I", payload, base)[0]
                texture_data.append(
                    {
                        "index": i,
                        "name_crc": name_crc,
                        "name_crc_hex": f"0x{name_crc:08X}",
                        "name": strings.get(name_crc),
                    }
                )
        elif section["type"] == RES_TYPE_MATERIAL_DATA and length >= MATERIAL_DATA_SIZE:
            for i in range(section["count"]):
                base = data_offset + i * length
                if base + MATERIAL_DATA_SIZE > len(payload):
                    break
                name_crc = struct.unpack_from("<I", payload, base)[0]
                name1_crc = struct.unpack_from("<I", payload, base + 8)[0]
                name2_crc = struct.unpack_from("<I", payload, base + 12)[0]
                images = []
                pos = base + 16
                for image_index in range(4):
                    if pos + IMAGE_ENTRY_SIZE > len(payload):
                        break
                    image_crc, enabled = struct.unpack_from("<Ii", payload, pos)
                    images.append(
                        {
                            "index": image_index,
                            "name_crc": image_crc,
                            "name_crc_hex": f"0x{image_crc:08X}",
                            "name": strings.get(image_crc),
                            "enabled": enabled != 0,
                        }
                    )
                    pos += IMAGE_ENTRY_SIZE
                material_data.append(
                    {
                        "index": i,
                        "name_crc": name_crc,
                        "name_crc_hex": f"0x{name_crc:08X}",
                        "name": strings.get(name_crc),
                        "material_data_name1": strings.get(name1_crc),
                        "material_data_name2": strings.get(name2_crc),
                        "images": images,
                    }
                )

    return {
        "ok": True,
        "string_offset": string_offset,
        "sections": sections,
        "texture_data": texture_data,
        "material_data": material_data,
        "string_count": len(strings),
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


def sorted_xi_files(root: Path) -> list[Path]:
    return sorted(root.glob("*.xi"), key=lambda p: p.name)


def build_material_records(
    root: Path,
    classes: dict,
    txp_records: list[dict],
    chrp: dict,
) -> list[dict]:
    by_material_txp = {record["owner_material"]: record for record in txp_records if record["owner_material"]}
    xi_files = sorted_xi_files(root)
    texture_by_crc: dict[int, dict] = {
        int(item["name_crc"]): item for item in chrp.get("texture_data") or [] if item.get("name_crc") is not None
    }

    materials = unique_preserve_order(
        [item["name"] for item in (chrp.get("material_data") or []) if item.get("name")]
        + classes["materials"]
        + [record["owner_material"] for record in txp_records if record["owner_material"]]
    )
    texture_names = classes["texture_name_candidates"]
    material_data_by_name = {
        item["name"]: item for item in (chrp.get("material_data") or []) if item.get("name")
    }

    records = []
    for material in materials:
        txp = by_material_txp.get(material)
        stem = txp["stem"] if txp else None
        chrp_entry = material_data_by_name.get(material)
        xi_path = None
        texture_index = None
        texture_crc = None
        texture_name = None
        confidence = "unresolved"
        binding_confidence = "resource_string_only"

        if chrp_entry:
            binding_confidence = "chrp_material_data"
            for image in chrp_entry.get("images") or []:
                if not image.get("enabled"):
                    continue
                image_crc = int(image["name_crc"])
                if image_crc == 0:
                    continue
                texture_slot = texture_by_crc.get(image_crc)
                if texture_slot is None:
                    continue
                texture_index = int(texture_slot["index"])
                texture_crc = image_crc
                texture_name = texture_slot.get("name") or image.get("name")
                if 0 <= texture_index < len(xi_files):
                    xi_path = str(xi_files[texture_index])
                    confidence = "chrp_material_data_texture_index"
                break

        # Fallback only when CHRP did not resolve an image: same-stem TXP/XI.
        # This preserves older 1:1 archives if MaterialData is missing, but does
        # not override a successful CHRP link.
        if xi_path is None and stem is not None:
            xi_path = xi_for_stem(root, stem)
            if xi_path:
                confidence = "txp_stem_xi_match"
                binding_confidence = "crc32_txp_owner" if txp else binding_confidence

        records.append(
            {
                "material_name": material,
                "material_base": material_base(material),
                "texture_name_candidates": texture_candidates_for_material(material, texture_names),
                "txp": txp,
                "mtr_path": file_if_exists(root / f"{stem}.mtr") if stem else None,
                "atr_path": file_if_exists(root / f"{stem}.atr") if stem else None,
                "xi_path_by_txp_stem": xi_for_stem(root, stem) if stem else None,
                "xi_path": xi_path,
                "xi_path_by_chrp": xi_path if confidence == "chrp_material_data_texture_index" else None,
                "texture_index": texture_index,
                "texture_crc": f"0x{texture_crc:08X}" if texture_crc is not None else None,
                "texture_name": texture_name,
                "texture_image_binding_confidence": confidence,
                "binding_confidence": binding_confidence,
            }
        )
    return records


def build_image_order_candidates(root: Path, texture_names: list[str]) -> list[dict]:
    xi_files = sorted_xi_files(root)
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
        xi_path = None
        if material:
            xi_path = material.get("xi_path") or material.get("xi_path_by_txp_stem")
        meshes.append(
            {
                "source": str(path),
                "mesh_name": info.mesh_name,
                "material_name": info.material_name,
                "material_bound": material is not None,
                "texture_name_candidates": material["texture_name_candidates"] if material else [],
                "xi_path_by_txp_stem": material.get("xi_path_by_txp_stem") if material else None,
                "xi_path": xi_path,
                "texture_image_binding_confidence": material.get("texture_image_binding_confidence") if material else "unresolved",
                "position_semantic": info.geometry.position_semantic,
                "vertex_count": info.vertex_count,
            }
        )
    return meshes


def apply_mesh_name_texture_candidates(
    material_records: list[dict], mesh_records: list[dict], image_order_candidates: list[dict]
) -> None:
    texture_name_set = {str(item["texture_name"]) for item in image_order_candidates if item.get("texture_name")}
    mesh_names_by_material: dict[str, list[str]] = {}
    for mesh in mesh_records:
        material_name = str(mesh["material_name"])
        mesh_names_by_material.setdefault(material_name, [])
        mesh_name = str(mesh["mesh_name"])
        if mesh_name not in mesh_names_by_material[material_name]:
            mesh_names_by_material[material_name].append(mesh_name)

    for record in material_records:
        if record.get("xi_path"):
            continue
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
    chrp = parse_chrp_sections(res_payload) if res_payload else {"ok": False, "texture_data": [], "material_data": []}
    if chrp.get("ok"):
        # Prefer CHRP string pool CRC map for TXP owner resolution.
        string_by_crc.update(build_string_crc_map(res_payload, int(chrp.get("string_offset") or 0)))
    txp_records = probe_txp_files(root, string_by_crc)
    material_records = build_material_records(root, classes, txp_records, chrp)
    image_order_candidates = build_image_order_candidates(root, classes["texture_name_candidates"])
    mesh_records = build_mesh_records(root, material_records)
    apply_mesh_name_texture_candidates(material_records, mesh_records, image_order_candidates)
    # Re-resolve XI paths for materials that only gained texture_name_candidates.
    xi_files = sorted_xi_files(root)
    xi_by_texture_name = {
        item["texture_name"]: item.get("xi_path_by_resource_order") for item in image_order_candidates
    }
    for record in material_records:
        if record.get("xi_path"):
            continue
        texture_name = (record.get("texture_name_candidates") or [None])[0]
        if texture_name and xi_by_texture_name.get(texture_name):
            record["xi_path"] = xi_by_texture_name[texture_name]
            if record["texture_image_binding_confidence"] == "unresolved":
                record["texture_image_binding_confidence"] = "resource_order_heuristic"
    mesh_records = build_mesh_records(root, material_records)
    return {
        "root": str(root),
        "res_path": str(res_path) if res_path else None,
        "res_compression": res_compression,
        "resource_strings": classes,
        "chrp": {
            "ok": bool(chrp.get("ok")),
            "texture_data": chrp.get("texture_data") or [],
            "material_data": chrp.get("material_data") or [],
            "texture_count": len(chrp.get("texture_data") or []),
            "material_count": len(chrp.get("material_data") or []),
            "xi_count": len(xi_files),
        },
        "txp_records": txp_records,
        "materials": material_records,
        "meshes": mesh_records,
        "image_order_candidates": image_order_candidates,
        "notes": [
            "Primary texture binding uses CHRP00 MaterialData image CRC -> TextureData index -> NNN.xi.",
            "This matches Level-5 RES layout documented by StudioEleven (types 240/290).",
            "TXP CRC32 still identifies material/texproj owners and same-stem MTR/ATR links.",
            "TXP stem -> XI is only a fallback when CHRP MaterialData does not resolve an image.",
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
