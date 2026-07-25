#!/usr/bin/env python3
"""Capture ground-truth AGE format facts for the Rust age_viewer port.

Writes JSON to outputs/manifests/age_viewer_groundtruth.json so the Rust
implementation can be compared against the validated Python decoders.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

from age_imgp_tool import decode_imgp  # noqa: E402
from age_xmpr_tool import decode_mesh  # noqa: E402
from age_xpck_tool import extract_archive, parse_xpck  # noqa: E402

ROOT = Path(r"D:\PPSSPP\AGE解包\资源解包\psp")
OUT = TOOLS.parent / "outputs" / "manifests" / "age_viewer_groundtruth.json"
WORK = TOOLS.parent / "outputs" / "_groundtruth_extract"

SAMPLES = [
    ROOT / "chr" / "ms001000" / "ms001000_p000.xc",
    ROOT / "chr" / "ms008000" / "ms008000_p000.xc",
    ROOT / "map" / "e1101.xc",
]


def summarize(archive_path: Path) -> dict:
    record: dict = {"archive": str(archive_path), "exists": archive_path.exists()}
    if not archive_path.exists():
        return record

    parsed = parse_xpck(archive_path)
    record["header"] = {
        "file_count": parsed.header.file_count,
        "variant_nibble": parsed.header.variant_nibble,
        "file_info_offset": parsed.header.file_info_offset,
        "filename_table_offset": parsed.header.filename_table_offset,
        "data_offset": parsed.header.data_offset,
    }
    record["name_table_compression"] = parsed.name_table_compression
    record["entries"] = [
        {
            "index": e.index,
            "name": e.name,
            "crc32": f"0x{e.crc32:08X}",
            "offset": e.absolute_offset,
            "size": e.size,
            "type": e.detected_type,
        }
        for e in parsed.entries
    ]

    extract_dir = WORK / archive_path.stem
    extract_archive(archive_path, extract_dir, overwrite=True)

    meshes = []
    for prm in sorted(extract_dir.rglob("*.prm")):
        try:
            info, verts, faces = decode_mesh(prm, "strip")
            meshes.append(
                {
                    "file": prm.name,
                    "mesh_name": info.mesh_name,
                    "material_name": info.material_name,
                    "vertex_count": len(verts),
                    "face_count": len(faces),
                    "stride": info.xpvb.stride,
                    "position_format": info.xpvb.position_format,
                    "uv0_format": info.xpvb.uv0_format,
                    "att_compression": info.xpvb.att_compression,
                    "vertex_compression": info.xpvb.vertex_compression,
                    "attributes": [
                        {
                            "slot": a.slot,
                            "count": a.count,
                            "offset": a.offset,
                            "size": a.size,
                            "type": a.type,
                        }
                        for a in info.xpvb.attributes
                    ],
                    "node_hashes": info.node_hashes,
                    "bounds_min": info.geometry.bounds_min,
                    "bounds_max": info.geometry.bounds_max,
                    "first_vertices": [
                        {"pos": list(v.position), "uv": list(v.uv0) if v.uv0 else None}
                        for v in verts[:3]
                    ],
                    "first_faces": [list(f) for f in faces[:3]],
                }
            )
        except Exception as exc:
            meshes.append({"file": prm.name, "error": str(exc)})
    record["meshes"] = meshes

    textures = []
    for xi in sorted(extract_dir.rglob("*.xi")):
        try:
            header, blocks, image = decode_imgp(xi, "rgba", "psp-swizzled")
            px = list(image.getdata())
            textures.append(
                {
                    "file": xi.name,
                    "width": header.width,
                    "height": header.height,
                    "bit_depth": header.bit_depth,
                    "format_code": header.format_code,
                    "color_count": header.color_count,
                    "palette_method": blocks.palette_method,
                    "table_method": blocks.table_method,
                    "pixel_method": blocks.pixel_method,
                    "tile_entry_size": blocks.tile_entry_size,
                    "first_pixels": [list(p) for p in px[:4]],
                    "center_pixel": list(px[(header.height // 2) * header.width + header.width // 2]),
                }
            )
        except Exception as exc:
            textures.append({"file": xi.name, "error": str(exc)})
    record["textures"] = textures

    record["txp_files"] = sorted(p.name for p in extract_dir.rglob("*.txp"))
    record["mbn_count"] = len(list(extract_dir.rglob("*.mbn")))
    return record


def main() -> int:
    result = {"resource_root": str(ROOT), "samples": [summarize(p) for p in SAMPLES]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    for sample in result["samples"]:
        if not sample.get("exists"):
            print(f"MISSING {sample['archive']}")
            continue
        print(
            f"{Path(sample['archive']).name}: entries={sample['header']['file_count']} "
            f"meshes={len(sample['meshes'])} textures={len(sample['textures'])} "
            f"names={sample['name_table_compression']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
