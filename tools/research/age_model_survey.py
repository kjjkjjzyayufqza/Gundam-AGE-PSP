#!/usr/bin/env python3
"""Survey Gundam AGE PSP model headers across XPCK archives.

This tool does not extract binary assets. It reads XPCK archives, inspects
embedded `.prm`/`XMPR` files in memory, and reports XPVB/XPVI header patterns
so model decoding assumptions can be checked against more than one sample.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from age_xmpr_tool import parse_attributes  # noqa: E402
from age_xpck_tool import XpckError, decompress_level5, iter_candidate_files, parse_xpck, read_file  # noqa: E402


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def classify_position_format(attributes: list) -> str:
    attr = next((item for item in attributes if item.slot == 0), None)
    if not attr or (attr.count == 0 and attr.size == 0):
        return "absent"
    if attr.size == 12 and attr.type == 2:
        return "float32x3"
    if attr.size == 16 and attr.type == 2:
        return "float32x4_xyz"
    if attr.size == 6 and attr.type == 2:
        return "s16_normx3"
    return f"unsupported_count{attr.count}_size{attr.size}_type{attr.type}"


def classify_uv0_format(attributes: list) -> str:
    attr = next((item for item in attributes if item.slot == 4), None)
    if not attr or (attr.count == 0 and attr.size == 0):
        return "absent"
    if attr.size == 8 and attr.type == 2:
        return "float32x2"
    if attr.size == 4 and attr.type == 2:
        return "u16_normx2"
    return f"unsupported_count{attr.count}_size{attr.size}_type{attr.type}"


def parse_prm_summary(prm: bytes, source: str) -> dict:
    warnings: list[str] = []
    if len(prm) < 0x54 or prm[:4] != b"XMPR":
        raise XpckError("not an XMPR PRM payload")

    xprm_offset = u32(prm, 0x04)
    if xprm_offset <= 0 or xprm_offset + 0x14 > len(prm) or prm[xprm_offset : xprm_offset + 4] != b"XPRM":
        raise XpckError(f"XPRM header not found at declared offset 0x{xprm_offset:X}")

    xpvb_rel = u32(prm, xprm_offset + 0x04)
    xpvb_len = u32(prm, xprm_offset + 0x08)
    xpvi_rel = u32(prm, xprm_offset + 0x0C)
    xpvi_len = u32(prm, xprm_offset + 0x10)

    xpvb_offset = xprm_offset + xpvb_rel
    xpvi_offset = xprm_offset + xpvi_rel
    if xpvb_offset + min(xpvb_len, 0x10) > len(prm) or prm[xpvb_offset : xpvb_offset + 4] != b"XPVB":
        raise XpckError(f"XPVB block missing at 0x{xpvb_offset:X}")
    if xpvi_offset + min(xpvi_len, 0x0C) > len(prm) or prm[xpvi_offset : xpvi_offset + 4] != b"XPVI":
        raise XpckError(f"XPVI block missing at 0x{xpvi_offset:X}")

    att_off, unk_off, vtx_off, stride, vertex_count = struct.unpack_from("<HHHHI", prm, xpvb_offset + 0x04)
    xpvb = prm[xpvb_offset : xpvb_offset + xpvb_len]
    att_method = "unread"
    attributes = []
    position_format = "unread"
    uv0_format = "unread"
    try:
        att_method, att = decompress_level5(xpvb[att_off:unk_off])
        attributes = parse_attributes(att)
        position_format = classify_position_format(attributes)
        uv0_format = classify_uv0_format(attributes)
    except Exception as exc:
        warnings.append(f"attribute table decode failed: {exc}")

    primitive_type, faces_offset, face_count = struct.unpack_from("<HHI", prm, xpvi_offset + 0x04)
    has_embedded_index_payload = xpvi_len > 0x0C and faces_offset >= 0x0C

    return {
        "source": source,
        "size": len(prm),
        "xprm_offset": xprm_offset,
        "xpvb": {
            "offset": xpvb_offset,
            "length": xpvb_len,
            "att_buffer_offset": att_off,
            "unknown_offset": unk_off,
            "vertex_buffer_offset": vtx_off,
            "stride": stride,
            "vertex_count": vertex_count,
            "att_compression": att_method,
            "attributes": [asdict(item) for item in attributes],
            "position_format": position_format,
            "uv0_format": uv0_format,
        },
        "xpvi": {
            "offset": xpvi_offset,
            "length": xpvi_len,
            "primitive_type": primitive_type,
            "faces_offset": faces_offset,
            "face_count": face_count,
            "has_embedded_index_payload": has_embedded_index_payload,
        },
        "warnings": warnings,
    }


def pattern_key(prm: dict) -> str:
    xpvi = prm["xpvi"]
    return (
        f"prim={xpvi['primitive_type']};len={xpvi['length']};"
        f"faces_off={xpvi['faces_offset']};faces={xpvi['face_count']};embedded={xpvi['has_embedded_index_payload']}"
    )


def survey_archive(path: Path) -> dict:
    archive = parse_xpck(path)
    data = read_file(path)
    prms = []
    failures = []
    for entry in archive.entries:
        if not entry.valid_range or not entry.name.lower().endswith(".prm"):
            continue
        source = f"{path}!{entry.name}"
        try:
            payload = data[entry.absolute_offset : entry.end_offset]
            prms.append(parse_prm_summary(payload, source))
        except Exception as exc:
            failures.append({"source": source, "error": str(exc)})
    return {
        "archive": str(path),
        "file_count": archive.header.file_count,
        "prm_count": len(prms),
        "failed_prm_count": len(failures),
        "prms": prms,
        "failures": failures,
    }


def command_survey(args: argparse.Namespace) -> int:
    inputs = [Path(item) for item in args.inputs]
    archives = list(iter_candidate_files(inputs, {ext.lower() for ext in args.extensions}, args.limit_archives))
    archive_records = []
    failures = []
    for archive_path in archives:
        try:
            archive_records.append(survey_archive(archive_path))
        except Exception as exc:
            failures.append({"archive": str(archive_path), "error": str(exc)})

    prm_records = [prm for archive in archive_records for prm in archive["prms"]]
    xpvi_patterns = Counter(pattern_key(prm) for prm in prm_records)
    position_formats = Counter(prm["xpvb"]["position_format"] for prm in prm_records)
    uv0_formats = Counter(prm["xpvb"]["uv0_format"] for prm in prm_records)

    summary = {
        "inputs": [str(path) for path in inputs],
        "archive_count": len(archive_records),
        "archive_failures": failures,
        "archives_with_prm": sum(1 for archive in archive_records if archive["prm_count"]),
        "prm_count": len(prm_records),
        "failed_prm_count": sum(archive["failed_prm_count"] for archive in archive_records),
        "xpvi_patterns": dict(sorted(xpvi_patterns.items())),
        "position_formats": dict(sorted(position_formats.items())),
        "uv0_formats": dict(sorted(uv0_formats.items())),
        "archives": archive_records,
        "notes": [
            "Survey reads PRM payloads in memory and does not extract binary assets.",
            "XPVI pattern prim=2;len=12;faces_off=0;faces=0;embedded=False supports the AGE PSP no-index triangle-strip hypothesis.",
        ],
    }

    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(text, encoding="utf-8")
    else:
        print(text)

    print(f"Archives scanned: {summary['archive_count']}")
    print(f"Archives with PRM: {summary['archives_with_prm']}")
    print(f"PRMs surveyed: {summary['prm_count']}")
    print(f"Manifest: {args.json}" if args.json else "Manifest: stdout")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Survey Gundam AGE PSP XMPR/XPVB/XPVI headers across XPCK archives.")
    parser.add_argument("inputs", nargs="+", help="XPCK archives or directories to scan")
    parser.add_argument("--extensions", nargs="+", default=[".xc"], help="XPCK extensions to include")
    parser.add_argument("--limit-archives", type=int, help="limit number of archives scanned")
    parser.add_argument("--json", help="write survey JSON manifest")
    parser.set_defaults(func=command_survey)
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




