#!/usr/bin/env python3
"""Probe Gundam AGE PSP material/resource parameter files.

This is intentionally descriptive rather than authoritative. It records stable
evidence from small parameter files so material binding can be reverse
engineered without repeatedly opening hex dumps.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from age_xpck_tool import XpckError, decompress_level5  # noqa: E402


PARAM_EXTENSIONS = {".mtr", ".atr", ".txp", ".cmn", ".bin"}


@dataclass
class StringHit:
    offset: int
    value: str


def read_ascii_prefix(data: bytes, limit: int = 16) -> str:
    raw = data[:limit].split(b"\x00", 1)[0]
    return "".join(chr(byte) if 0x20 <= byte <= 0x7E else "." for byte in raw)


def words_u32(data: bytes, limit: int = 16) -> list[int]:
    count = min(len(data) // 4, limit)
    return list(struct.unpack_from("<" + "I" * count, data, 0)) if count else []


def floats_f32(data: bytes, limit: int = 16) -> list[float]:
    count = min(len(data) // 4, limit)
    return list(struct.unpack_from("<" + "f" * count, data, 0)) if count else []


def ascii_strings(data: bytes, min_length: int = 4) -> list[StringHit]:
    pattern = rb"[\x20-\x7e]{" + str(min_length).encode("ascii") + rb",}"
    return [
        StringHit(offset=match.start(), value=match.group().decode("ascii", errors="replace"))
        for match in re.finditer(pattern, data)
    ]


def crc32_string(value: str) -> int:
    return zlib.crc32(value.encode("shift-jis")) & 0xFFFFFFFF


def resource_crc_map_for_dir(root: Path) -> dict[int, str]:
    for name in ("RES.dec.bin", "RES.bin"):
        path = root / name
        if not path.exists():
            continue
        data = path.read_bytes()
        if data[:4] != b"CHRP":
            try:
                _, data = decompress_level5(data)
            except Exception:
                continue
        strings = ascii_strings(data)
        return {crc32_string(item.value): item.value for item in strings}
    return {}


def probe_txp(data: bytes, string_by_crc: dict[int, str] | None = None) -> dict:
    result: dict = {}
    if len(data) >= 8:
        result["hash_words"] = list(struct.unpack_from("<II", data, 0))
        result["hash_hex"] = [f"0x{value:08X}" for value in result["hash_words"]]
        if string_by_crc:
            result["crc32_matches"] = [
                {"hash": f"0x{value:08X}", "string": string_by_crc.get(value)}
                for value in result["hash_words"]
            ]
    if len(data) >= 36:
        result["uv_scale_candidate"] = list(struct.unpack_from("<ff", data, 28))
    return result


def probe_magic_payload(data: bytes) -> dict:
    if len(data) < 12:
        return {}
    payload_offset = struct.unpack_from("<I", data, 8)[0]
    if payload_offset > len(data):
        payload = b""
    else:
        payload = data[payload_offset:]
    return {
        "tag": read_ascii_prefix(data, 8),
        "payload_offset": payload_offset,
        "payload_size": len(payload),
        "payload_hex": payload.hex(" "),
        "payload_u16_le": list(struct.unpack_from("<" + "H" * (len(payload) // 2), payload, 0)) if len(payload) >= 2 else [],
        "payload_u32_le": list(struct.unpack_from("<" + "I" * (len(payload) // 4), payload, 0)) if len(payload) >= 4 else [],
        "note": "Payload field semantics are not confirmed; values are exposed for diffing.",
    }


def probe_cmn(data: bytes, string_by_crc: dict[int, str] | None = None) -> dict:
    if len(data) < 12:
        return {}
    value_word, key_crc, flags = struct.unpack_from("<III", data, 0)
    value_float = struct.unpack_from("<f", data, 0)[0]
    return {
        "value_word": value_word,
        "value_hex": f"0x{value_word:08X}",
        "value_float_candidate": value_float,
        "key_crc32": f"0x{key_crc:08X}",
        "key_crc32_match": string_by_crc.get(key_crc) if string_by_crc else None,
        "flags_or_type": flags,
        "note": "CMN word1 matches CRC32 of CHRP00 parameter names in sampled files; value/type semantics are still under study.",
    }


def probe_res_payload(data: bytes) -> dict:
    payload = data
    compression = "already_decompressed_or_unknown"
    if data[:4] != b"CHRP" and len(data) >= 4:
        try:
            compression, payload = decompress_level5(data)
        except Exception:
            payload = data
    return {
        "compression": compression,
        "payload_size": len(payload),
        "payload_magic": read_ascii_prefix(payload, 8),
        "strings": [asdict(hit) for hit in ascii_strings(payload)],
    }


def probe_file(path: Path, string_by_crc: dict[int, str] | None = None) -> dict:
    data = path.read_bytes()
    item = {
        "path": str(path),
        "size": len(data),
        "extension": path.suffix.lower(),
        "magic_ascii": read_ascii_prefix(data, 12),
        "first_u32_le": words_u32(data),
        "first_f32_le": floats_f32(data),
    }

    suffix = path.suffix.lower()
    if suffix == ".txp":
        item["txp"] = probe_txp(data, string_by_crc)
    if suffix in {".mtr", ".atr"}:
        item["tagged_payload"] = probe_magic_payload(data)
    if suffix == ".cmn":
        item["cmn"] = probe_cmn(data, string_by_crc)
    if path.name.lower() in {"res.bin", "res.dec.bin"}:
        item["resource"] = probe_res_payload(data)

    return item


def iter_inputs(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in path.rglob("*")
                    if child.is_file()
                    and (child.suffix.lower() in PARAM_EXTENSIONS or child.name.lower() in {"res.bin", "res.dec.bin"})
                )
            )
        else:
            paths.append(path)
    return paths


def command_probe(args: argparse.Namespace) -> int:
    results = []
    failures = []
    crc_cache: dict[Path, dict[int, str]] = {}
    for path in iter_inputs(args.inputs):
        try:
            parent = path.parent.resolve()
            if parent not in crc_cache:
                crc_cache[parent] = resource_crc_map_for_dir(parent)
            results.append(probe_file(path, crc_cache[parent]))
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})

    manifest = {"count": len(results), "failed": len(failures), "items": results, "failures": failures}
    text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(text, encoding="utf-8")
        print(f"Probed files: {len(results)}")
        if failures:
            print(f"Failures: {len(failures)}")
        print(f"Manifest: {json_path}")
    else:
        print(text)
    return 1 if failures and args.fail_on_error else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Gundam AGE PSP material/resource parameter files.")
    parser.add_argument("inputs", nargs="+", help="files or directories to inspect")
    parser.add_argument("--json", help="write JSON manifest")
    parser.add_argument("--fail-on-error", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_probe(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())




