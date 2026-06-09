#!/usr/bin/env python3
"""Inspect and extract Level-5 XPCK archives used by Gundam AGE PSP.

The tool is intentionally conservative:
- it parses XPCK directory metadata;
- it decompresses the XPCK name table for Level-5 no-compression, LZ10, and
  zlib payloads;
- it never writes outside the requested output directory;
- it does not claim to decode model or texture payloads by itself.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


XPCK_MAGIC = b"XPCK"
HEADER_STRUCT = struct.Struct("<4sBBHHHHHI")
ENTRY_STRUCT = struct.Struct("<IHHHBB")
HEADER_SIZE = HEADER_STRUCT.size
ENTRY_SIZE = ENTRY_STRUCT.size

COMPRESSION_METHODS = {
    0: "none",
    1: "lz10",
    2: "huffman4",
    3: "huffman8",
    4: "rle",
    5: "zlib",
}

KNOWN_MAGICS = {
    b"XPCK": "xpck_archive",
    b"IMGP": "image_imgp_candidate",
    b"IMGC": "image_imgc",
    b"IMGV": "image_imgv",
    b"IMGA": "image_imga",
    b"ANMC": "animation_anmc",
    b"MINA": "animation_mina_candidate",
    b"RES\x00": "resource_table_candidate",
    b"\x89PNG": "png",
    b"CRID": "criware_utf_or_media",
    b"AFS2": "criware_afs2",
    b"@UTF": "criware_utf",
}


class XpckError(RuntimeError):
    pass


@dataclass
class XpckHeader:
    file_count: int
    fc1: int
    fc2: int
    variant_nibble: int
    file_info_offset: int
    filename_table_offset: int
    data_offset: int
    file_info_size: int
    filename_table_size: int
    data_size: int


@dataclass
class XpckEntry:
    index: int
    name: str
    crc32: int
    name_offset: int
    relative_offset: int
    absolute_offset: int
    size: int
    end_offset: int
    valid_range: bool
    magic_hex: str
    magic_ascii: str
    detected_type: str


@dataclass
class XpckArchive:
    path: str
    size: int
    header: XpckHeader
    name_table_compression: str
    name_table_decompressed_size: int
    entries: list[XpckEntry]


def read_file(path: Path) -> bytes:
    with path.open("rb") as fh:
        return fh.read()


def parse_header(data: bytes) -> XpckHeader:
    if len(data) < HEADER_SIZE:
        raise XpckError(f"too small for XPCK header: {len(data)} bytes")

    magic, fc1, fc2, info_u, name_u, data_u, info_size_u, name_size_u, data_size_u = HEADER_STRUCT.unpack_from(data, 0)
    if magic != XPCK_MAGIC:
        raise XpckError(f"not XPCK magic: {magic!r}")

    file_count = ((fc2 & 0x0F) << 8) | fc1
    return XpckHeader(
        file_count=file_count,
        fc1=fc1,
        fc2=fc2,
        variant_nibble=(fc2 & 0xF0) >> 4,
        file_info_offset=info_u << 2,
        filename_table_offset=name_u << 2,
        data_offset=data_u << 2,
        file_info_size=info_size_u << 2,
        filename_table_size=name_size_u << 2,
        data_size=data_size_u << 2,
    )


def peek_level5_header(payload: bytes) -> tuple[int, int]:
    if len(payload) < 4:
        raise XpckError("Level-5 compressed payload is shorter than 4 bytes")
    word = struct.unpack_from("<I", payload, 0)[0]
    return word & 0x7, word >> 3


def decompress_lz10(payload: bytes) -> bytes:
    method, expected_size = peek_level5_header(payload)
    if method != 1:
        raise XpckError(f"not Level-5 LZ10 payload, method={method}")

    out = bytearray()
    pos = 4
    while len(out) < expected_size:
        if pos >= len(payload):
            raise XpckError("truncated LZ10 flag byte")
        flags = payload[pos]
        pos += 1

        for bit in range(7, -1, -1):
            if len(out) >= expected_size:
                break

            if flags & (1 << bit):
                if pos + 1 >= len(payload):
                    raise XpckError("truncated LZ10 back-reference")
                b1 = payload[pos]
                b2 = payload[pos + 1]
                pos += 2
                count = (b1 >> 4) + 3
                disp = (((b1 & 0x0F) << 8) | b2) + 1
                if disp > len(out):
                    raise XpckError(f"invalid LZ10 displacement {disp} at output {len(out)}")
                for _ in range(count):
                    out.append(out[-disp])
                    if len(out) >= expected_size:
                        break
            else:
                if pos >= len(payload):
                    raise XpckError("truncated LZ10 literal")
                out.append(payload[pos])
                pos += 1

    return bytes(out)


def decompress_huffman(payload: bytes, bit_depth: int) -> bytes:
    method, expected_size = peek_level5_header(payload)
    expected_method = 2 if bit_depth == 4 else 3
    if method != expected_method:
        raise XpckError(f"not Level-5 Huffman{bit_depth} payload, method={method}")

    pos = 4
    if pos + 2 > len(payload):
        raise XpckError("truncated Huffman tree header")
    tree_size = payload[pos]
    tree_root = payload[pos + 1]
    pos += 2

    tree_end = pos + tree_size * 2
    if tree_end > len(payload):
        raise XpckError("truncated Huffman tree")
    tree = payload[pos:tree_end]
    pos = tree_end

    symbol_count = expected_size * 8 // bit_depth
    symbols = bytearray()
    node = tree_root
    next_index = 0
    bit_index = 0
    code = 0

    while len(symbols) < symbol_count:
        if bit_index % 32 == 0:
            if pos + 4 > len(payload):
                raise XpckError("truncated Huffman bitstream")
            code = struct.unpack_from("<I", payload, pos)[0]
            pos += 4

        next_index += ((node & 0x3F) << 1) + 2
        bit = (code >> (31 - (bit_index % 32))) & 1
        direction = 1 if bit else 2
        leaf = ((node >> 5 >> direction) & 1) != 0
        child_index = next_index - direction
        if child_index < 0 or child_index >= len(tree):
            raise XpckError("Huffman tree traversal left the tree buffer")
        node = tree[child_index]
        if leaf:
            symbols.append(node)
            node = tree_root
            next_index = 0
        bit_index += 1

    if bit_depth == 8:
        return bytes(symbols[:expected_size])

    out = bytearray(expected_size)
    for i in range(expected_size):
        out[i] = symbols[2 * i] | (symbols[2 * i + 1] << 4)
    return bytes(out)


def decompress_rle(payload: bytes) -> bytes:
    method, expected_size = peek_level5_header(payload)
    if method != 4:
        raise XpckError(f"not Level-5 RLE payload, method={method}")

    out = bytearray()
    pos = 4
    while len(out) < expected_size:
        if pos >= len(payload):
            raise XpckError("truncated RLE flag")
        flag = payload[pos]
        pos += 1
        if flag & 0x80:
            if pos >= len(payload):
                raise XpckError("truncated RLE repeated byte")
            repetitions = (flag & 0x7F) + 3
            out.extend([payload[pos]] * repetitions)
            pos += 1
        else:
            length = flag + 1
            if pos + length > len(payload):
                raise XpckError("truncated RLE literal bytes")
            out.extend(payload[pos : pos + length])
            pos += length

    return bytes(out[:expected_size])


def decompress_level5(payload: bytes) -> tuple[str, bytes]:
    method, expected_size = peek_level5_header(payload)
    method_name = COMPRESSION_METHODS.get(method, f"unknown_{method}")

    if method == 0:
        return method_name, payload[4 : 4 + expected_size]
    if method == 1:
        return method_name, decompress_lz10(payload)
    if method == 2:
        return method_name, decompress_huffman(payload, 4)
    if method == 3:
        return method_name, decompress_huffman(payload, 8)
    if method == 4:
        return method_name, decompress_rle(payload)
    if method == 5:
        return method_name, zlib.decompress(payload[4:])

    raise XpckError(f"unsupported Level-5 compression method {method} ({method_name})")


def read_c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return f"entry_{offset:08x}.bin"
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    raw = data[offset:end]
    if not raw:
        return f"entry_{offset:08x}.bin"
    return raw.decode("ascii", errors="replace").replace("\\", "/")


def describe_magic(blob: bytes) -> tuple[str, str, str]:
    head = blob[:16]
    magic4 = head[:4]
    magic_hex = head[:8].hex(" ").upper()
    magic_ascii = "".join(chr(b) if 32 <= b <= 126 else "." for b in head[:8])
    detected = KNOWN_MAGICS.get(magic4)
    if detected is None:
        if len(blob) >= 4:
            method, size = peek_level5_header(blob)
            if method in COMPRESSION_METHODS and 0 <= size <= max(0, len(blob) * 256):
                detected = f"level5_compressed_{COMPRESSION_METHODS[method]}"
        if detected is None:
            detected = "unknown"
    return magic_hex, magic_ascii, detected


def parse_xpck(path: Path) -> XpckArchive:
    data = read_file(path)
    header = parse_header(data)

    if header.file_info_offset + header.file_count * ENTRY_SIZE > len(data):
        raise XpckError("entry table extends beyond file")
    if header.filename_table_offset + header.filename_table_size > len(data):
        raise XpckError("filename table extends beyond file")

    raw_name_table = data[
        header.filename_table_offset : header.filename_table_offset + header.filename_table_size
    ]
    compression, names = decompress_level5(raw_name_table)

    entries: list[XpckEntry] = []
    for index in range(header.file_count):
        entry_offset = header.file_info_offset + index * ENTRY_SIZE
        crc32, name_offset, off_low, size_low, off_high, size_high = ENTRY_STRUCT.unpack_from(data, entry_offset)
        relative_offset = (((off_high << 16) | off_low) << 2)
        size = (size_high << 16) | size_low
        absolute_offset = header.data_offset + relative_offset
        end_offset = absolute_offset + size
        valid_range = 0 <= absolute_offset <= end_offset <= len(data)
        child = data[absolute_offset:end_offset] if valid_range else b""
        magic_hex, magic_ascii, detected_type = describe_magic(child)
        entries.append(
            XpckEntry(
                index=index,
                name=read_c_string(names, name_offset),
                crc32=crc32,
                name_offset=name_offset,
                relative_offset=relative_offset,
                absolute_offset=absolute_offset,
                size=size,
                end_offset=end_offset,
                valid_range=valid_range,
                magic_hex=magic_hex,
                magic_ascii=magic_ascii,
                detected_type=detected_type,
            )
        )

    return XpckArchive(
        path=str(path),
        size=len(data),
        header=header,
        name_table_compression=compression,
        name_table_decompressed_size=len(names),
        entries=entries,
    )


def is_xpck_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == XPCK_MAGIC
    except OSError:
        return False


def iter_candidate_files(paths: Iterable[Path], extensions: set[str] | None, limit: int | None) -> Iterable[Path]:
    yielded = 0
    for path in paths:
        if path.is_dir():
            iterator = (p for p in path.rglob("*") if p.is_file())
        else:
            iterator = iter([path])

        for item in iterator:
            if extensions is not None and item.suffix.lower() not in extensions:
                continue
            if not is_xpck_file(item):
                continue
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def sanitize_output_name(name: str, fallback: str) -> Path:
    clean_parts = []
    for raw_part in name.replace("\\", "/").split("/"):
        part = raw_part.strip().strip(".")
        if not part:
            continue
        part = "".join(ch if ch not in '<>:"|?*' and ord(ch) >= 32 else "_" for ch in part)
        clean_parts.append(part)
    if not clean_parts:
        clean_parts = [fallback]
    return Path(*clean_parts)


def ensure_inside(base: Path, target: Path) -> None:
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise XpckError(f"refusing to write outside output directory: {target}") from exc


def extract_archive(archive_path: Path, out_dir: Path, overwrite: bool) -> dict:
    archive = parse_xpck(archive_path)
    data = read_file(archive_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for entry in archive.entries:
        if not entry.valid_range:
            continue
        rel = sanitize_output_name(entry.name, f"entry_{entry.index:04d}.bin")
        target = out_dir / rel
        ensure_inside(out_dir, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise XpckError(f"output exists, use --overwrite: {target}")
        target.write_bytes(data[entry.absolute_offset : entry.end_offset])
        written.append(str(target))

    manifest = {
        "archive": asdict(archive),
        "output_dir": str(out_dir),
        "written_files": written,
    }
    manifest_path = out_dir / "_xpck_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def decompress_level5_file(input_path: Path, output_path: Path, overwrite: bool) -> dict:
    payload = read_file(input_path)
    method, expected_size = peek_level5_header(payload)
    method_name, decompressed = decompress_level5(payload)
    if output_path.exists() and not overwrite:
        raise XpckError(f"output exists, use --overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(decompressed)
    return {
        "input": str(input_path),
        "output": str(output_path),
        "method": method,
        "method_name": method_name,
        "expected_size": expected_size,
        "actual_size": len(decompressed),
    }


def command_inspect(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.inputs]
    extensions = None
    if args.extensions:
        extensions = {ext if ext.startswith(".") else f".{ext}" for ext in args.extensions.lower().split(",")}

    archives = []
    errors = []
    for path in iter_candidate_files(paths, extensions, args.limit):
        try:
            archive = parse_xpck(path)
            item = asdict(archive)
            if args.max_entries is not None:
                item["entries"] = item["entries"][: args.max_entries]
            archives.append(item)
        except Exception as exc:  # report and continue for batch scans
            errors.append({"path": str(path), "error": str(exc)})

    result = {
        "archive_count": len(archives),
        "archives": archives,
        "errors": errors,
    }

    if args.json:
        output = Path(args.json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"XPCK archives parsed: {len(archives)}")
    if errors:
        print(f"Errors: {len(errors)}", file=sys.stderr)
    for archive in archives[: args.print_archives]:
        header = archive["header"]
        print(
            f"{archive['path']} | entries={header['file_count']} "
            f"names={archive['name_table_compression']} size={archive['size']}"
        )
        for entry in archive["entries"][: args.print_entries]:
            print(
                f"  [{entry['index']:04d}] {entry['name']} "
                f"off=0x{entry['absolute_offset']:X} size={entry['size']} "
                f"type={entry['detected_type']} magic={entry['magic_ascii']}"
            )

    return 1 if errors and args.fail_on_error else 0


def command_extract(args: argparse.Namespace) -> int:
    manifest = extract_archive(Path(args.input), Path(args.out), args.overwrite)
    print(f"Wrote {len(manifest['written_files'])} files to {manifest['output_dir']}")
    print(f"Manifest: {Path(args.out) / '_xpck_manifest.json'}")
    return 0


def command_decompress_l5(args: argparse.Namespace) -> int:
    result = decompress_level5_file(Path(args.input), Path(args.out), args.overwrite)
    print(
        f"Wrote {result['actual_size']} bytes to {result['output']} "
        f"(method={result['method_name']}, expected={result['expected_size']})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and extract Gundam AGE PSP XPCK archives.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="scan files or directories for XPCK archives")
    inspect.add_argument("inputs", nargs="+", help="file or directory paths")
    inspect.add_argument("--json", help="write JSON manifest")
    inspect.add_argument("--extensions", default=".xc,.xb,.xa,.xk,.xi,.xq,.xv,.bin,.npcbin", help="comma-separated extensions; empty string scans all")
    inspect.add_argument("--limit", type=int, help="maximum number of XPCK archives to parse")
    inspect.add_argument("--max-entries", type=int, help="truncate entries stored in JSON")
    inspect.add_argument("--print-archives", type=int, default=10, help="archives to print to stdout")
    inspect.add_argument("--print-entries", type=int, default=12, help="entries per archive to print to stdout")
    inspect.add_argument("--fail-on-error", action="store_true", help="return non-zero if any archive fails")
    inspect.set_defaults(func=command_inspect)

    extract = subparsers.add_parser("extract", help="extract one XPCK archive")
    extract.add_argument("input", help="XPCK archive path")
    extract.add_argument("--out", required=True, help="output directory")
    extract.add_argument("--overwrite", action="store_true", help="replace existing extracted files")
    extract.set_defaults(func=command_extract)

    decomp = subparsers.add_parser("decompress-l5", help="decompress one Level-5 compressed payload")
    decomp.add_argument("input", help="input payload path")
    decomp.add_argument("--out", required=True, help="output file")
    decomp.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    decomp.set_defaults(func=command_decompress_l5)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "inspect" and args.extensions == "":
        args.extensions = None
    try:
        return args.func(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())




