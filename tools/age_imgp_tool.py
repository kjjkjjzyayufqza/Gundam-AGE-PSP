#!/usr/bin/env python3
"""Experimental IMGP texture inspector/exporter for Gundam AGE PSP.

Confirmed from local samples:
- IMGP payloads start with a 0x58-byte header.
- offset 0x58 contains three Level-5-compressed blocks:
  palette, tile table, and indexed tile pixel data.
- palettes are 4-byte colors; PSP tooling often describes the 32-bit word as
  ABGR, which appears on disk as little-endian RGBA bytes.
- pixels are 4bpp or 8bpp indexed data referenced by the tile table, then
  deswizzled from the PSP 16-byte x 8-row texture layout.

This exporter intentionally focuses on static color textures. It does not
decode model geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment check
    raise SystemExit("Pillow is required for PNG export: python -m pip install pillow") from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))
from age_xpck_tool import XpckError, decompress_level5, peek_level5_header  # noqa: E402


IMGP_MAGIC = b"IMGP"
HEADER_SIZE = 0x58


@dataclass
class ImgpHeader:
    path: str
    size: int
    version: str
    format_code: int
    bit_depth: int
    pitch_width: int
    width: int
    height: int
    data_start: int
    color_count: int
    palette_count: int
    palette_block_size_unaligned: int
    palette_block_size: int
    table_block_size: int
    pixel_block_offset: int
    pixel_block_size: int


@dataclass
class ImgpBlocks:
    palette_method: str
    palette_size: int
    table_method: str
    table_size: int
    pixel_method: str
    pixel_size: int
    tile_entry_size: int
    tile_count: int
    tile_size: int
    expected_tile_count: int
    pixel_layout: str
    row_bytes: int
    swizzle_block_width: int
    swizzle_block_height: int


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_imgp_header(path: Path, data: bytes) -> ImgpHeader:
    if len(data) < HEADER_SIZE:
        raise XpckError(f"too small for IMGP header: {len(data)} bytes")
    if data[:4] != IMGP_MAGIC:
        raise XpckError(f"not IMGP magic: {data[:4]!r}")

    version = data[4:8].rstrip(b"\x00").decode("ascii", errors="replace")
    data_start = read_u32(data, 0x1C)
    if data_start <= 0 or data_start >= len(data):
        data_start = HEADER_SIZE

    return ImgpHeader(
        path=str(path),
        size=len(data),
        version=version,
        format_code=data[0x0A],
        bit_depth=data[0x0D],
        pitch_width=read_u16(data, 0x0E),
        width=read_u16(data, 0x10),
        height=read_u16(data, 0x12),
        data_start=data_start,
        color_count=read_u16(data, 0x38),
        palette_count=read_u16(data, 0x3A),
        palette_block_size_unaligned=read_u32(data, 0x34),
        palette_block_size=read_u32(data, 0x40),
        table_block_size=read_u32(data, 0x44),
        pixel_block_offset=read_u32(data, 0x48),
        pixel_block_size=read_u32(data, 0x4C),
    )


def read_block(data: bytes, start: int, size: int, label: str) -> tuple[str, bytes]:
    if start < 0 or size < 0 or start + size > len(data):
        raise XpckError(f"{label} block range is outside file: start=0x{start:X}, size={size}")
    block = data[start : start + size]
    return decompress_level5(block)


def parse_tile_table(table: bytes) -> tuple[list[int], int]:
    if len(table) >= 2 and struct.unpack_from("<H", table, 0)[0] == 0x0453:
        entries = [struct.unpack_from("<I", table, off)[0] for off in range(8, len(table) - 3, 4)]
        return entries, 4
    entries = [struct.unpack_from("<H", table, off)[0] for off in range(0, len(table) - 1, 2)]
    return entries, 2


def build_ordered_tiles(entries: list[int], pixel_data: bytes, tile_size: int, entry_size: int) -> bytes:
    out = bytearray()
    empty = b"\x00" * tile_size
    empty_marker = 0xFFFFFFFF if entry_size == 4 else 0xFFFF
    for entry in entries:
        if entry == empty_marker:
            out.extend(empty)
            continue
        start = entry * tile_size
        end = start + tile_size
        if end > len(pixel_data):
            out.extend(empty)
        else:
            out.extend(pixel_data[start:end])
    return bytes(out)


def palette_to_rgba(palette: bytes, color_count: int, order: str) -> list[tuple[int, int, int, int]]:
    colors = []
    max_colors = min(color_count, len(palette) // 4)
    for i in range(max_colors):
        c0, c1, c2, c3 = palette[i * 4 : i * 4 + 4]
        if order == "bgra":
            colors.append((c2, c1, c0, c3))
        else:
            colors.append((c0, c1, c2, c3))
    if not colors:
        colors.append((0, 0, 0, 0))
    return colors


def tile_indices(tile: bytes, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        return list(tile[:64])
    if bit_depth == 4:
        pixels: list[int] = []
        for byte in tile[:32]:
            pixels.append(byte & 0x0F)
            pixels.append((byte >> 4) & 0x0F)
        return pixels[:64]
    raise XpckError(f"unsupported IMGP bit depth {bit_depth}; expected 4 or 8")


def indexed_row_bytes(width: int, bit_depth: int) -> int:
    return (width * bit_depth + 7) // 8


def psp_deswizzle_index_bytes(
    swizzled: bytes,
    width: int,
    height: int,
    bit_depth: int,
    block_width: int = 16,
    block_height: int = 8,
) -> bytes:
    """Convert PSP swizzled indexed texture bytes to linear row-major bytes."""
    row_bytes = indexed_row_bytes(width, bit_depth)
    linear = bytearray(row_bytes * height)
    src_offset = 0
    block_cols = math.ceil(row_bytes / block_width)
    block_rows = math.ceil(height / block_height)

    for block_y in range(block_rows):
        for block_x in range(block_cols):
            for y in range(block_height):
                dst_y = block_y * block_height + y
                if dst_y < height:
                    dst_offset = dst_y * row_bytes + block_x * block_width
                    copy_size = min(block_width, row_bytes - block_x * block_width)
                    chunk = swizzled[src_offset : src_offset + copy_size]
                    linear[dst_offset : dst_offset + len(chunk)] = chunk
                src_offset += block_width

    return bytes(linear)


def render_linear_indexed(
    index_bytes: bytes,
    width: int,
    height: int,
    bit_depth: int,
    palette: list[tuple[int, int, int, int]],
) -> Image.Image:
    pixels: list[tuple[int, int, int, int]] = []
    expected_pixels = width * height

    if bit_depth == 8:
        for index in index_bytes[:expected_pixels]:
            pixels.append(palette[index] if index < len(palette) else (255, 0, 255, 255))
    elif bit_depth == 4:
        for byte in index_bytes[: indexed_row_bytes(width, bit_depth) * height]:
            for index in (byte & 0x0F, (byte >> 4) & 0x0F):
                pixels.append(palette[index] if index < len(palette) else (255, 0, 255, 255))
                if len(pixels) == expected_pixels:
                    break
            if len(pixels) == expected_pixels:
                break
    else:
        raise XpckError(f"unsupported IMGP bit depth {bit_depth}; expected 4 or 8")

    if len(pixels) < expected_pixels:
        pixels.extend([(0, 0, 0, 0)] * (expected_pixels - len(pixels)))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return image


def render_indexed_tiles(
    ordered_tiles: bytes,
    width: int,
    height: int,
    bit_depth: int,
    palette: list[tuple[int, int, int, int]],
) -> Image.Image:
    tile_size = 64 * bit_depth // 8
    tile_cols = math.ceil(width / 8)
    tile_rows = math.ceil(height / 8)
    pixels = [(0, 0, 0, 0)] * (width * height)

    for tile_index in range(tile_cols * tile_rows):
        tile_start = tile_index * tile_size
        tile = ordered_tiles[tile_start : tile_start + tile_size]
        if len(tile) < tile_size:
            break
        local_indices = tile_indices(tile, bit_depth)
        tile_x = tile_index % tile_cols
        tile_y = tile_index // tile_cols
        for y in range(8):
            dst_y = tile_y * 8 + y
            if dst_y >= height:
                continue
            for x in range(8):
                dst_x = tile_x * 8 + x
                if dst_x >= width:
                    continue
                index = local_indices[y * 8 + x]
                color = palette[index] if index < len(palette) else (255, 0, 255, 255)
                pixels[dst_y * width + dst_x] = color

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return image


def render_indexed_texture(
    ordered_tiles: bytes,
    width: int,
    height: int,
    bit_depth: int,
    palette: list[tuple[int, int, int, int]],
    pixel_layout: str,
) -> Image.Image:
    if pixel_layout == "psp-swizzled":
        linear = psp_deswizzle_index_bytes(ordered_tiles, width, height, bit_depth)
        return render_linear_indexed(linear, width, height, bit_depth, palette)
    if pixel_layout == "linear":
        return render_linear_indexed(ordered_tiles, width, height, bit_depth, palette)
    if pixel_layout == "tiled":
        return render_indexed_tiles(ordered_tiles, width, height, bit_depth, palette)
    raise XpckError(f"unsupported IMGP pixel layout {pixel_layout!r}")


def decode_imgp(
    path: Path,
    palette_order: str,
    pixel_layout: str = "psp-swizzled",
) -> tuple[ImgpHeader, ImgpBlocks, Image.Image]:
    data = path.read_bytes()
    header = parse_imgp_header(path, data)

    palette_start = header.data_start
    table_start = header.data_start + header.palette_block_size
    pixel_start = header.data_start + header.pixel_block_offset

    palette_method, palette = read_block(data, palette_start, header.palette_block_size, "palette")
    table_method, table = read_block(data, table_start, header.table_block_size, "tile table")
    pixel_method, pixel_data = read_block(data, pixel_start, header.pixel_block_size, "pixel")

    entries, entry_size = parse_tile_table(table)
    tile_size = 64 * header.bit_depth // 8
    expected_tile_count = math.ceil(header.width / 8) * math.ceil(header.height / 8)
    ordered_tiles = build_ordered_tiles(entries, pixel_data, tile_size, entry_size)
    rgba_palette = palette_to_rgba(palette, header.color_count, palette_order)
    image = render_indexed_texture(
        ordered_tiles,
        header.width,
        header.height,
        header.bit_depth,
        rgba_palette,
        pixel_layout,
    )

    blocks = ImgpBlocks(
        palette_method=palette_method,
        palette_size=len(palette),
        table_method=table_method,
        table_size=len(table),
        pixel_method=pixel_method,
        pixel_size=len(pixel_data),
        tile_entry_size=entry_size,
        tile_count=len(entries),
        tile_size=tile_size,
        expected_tile_count=expected_tile_count,
        pixel_layout=pixel_layout,
        row_bytes=indexed_row_bytes(header.width, header.bit_depth),
        swizzle_block_width=16 if pixel_layout == "psp-swizzled" else 0,
        swizzle_block_height=8 if pixel_layout == "psp-swizzled" else 0,
    )
    return header, blocks, image


def command_export(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.out)
    header, blocks, image = decode_imgp(input_path, args.palette_order, args.pixel_layout)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)

    manifest = {
        "header": asdict(header),
        "blocks": asdict(blocks),
        "png": str(output_path),
        "notes": [
            "Experimental IMGP decode; validated against local Gundam AGE PSP samples.",
            "Palette order defaults to little-endian RGBA bytes. Use --palette-order bgra if colors look channel-swapped.",
            "Default pixel layout applies PSP 16-byte x 8-row deswizzle after the Level-5 tile table is rebuilt.",
        ],
    }
    if args.json:
        json_path = Path(args.json)
    else:
        json_path = output_path.with_suffix(output_path.suffix + ".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote PNG: {output_path}")
    print(
        f"IMGP {header.width}x{header.height} {header.bit_depth}bpp "
        f"palette={blocks.palette_method}/{blocks.palette_size} "
        f"table={blocks.table_method}/{blocks.table_size} "
        f"pixels={blocks.pixel_method}/{blocks.pixel_size}"
    )
    print(f"Manifest: {json_path}")
    return 0


def command_batch_export(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.out_dir)
    files = sorted(input_dir.rglob(args.pattern))
    manifests = []
    failures = []

    for file_path in files:
        try:
            rel = file_path.relative_to(input_dir)
            png_path = (output_dir / rel).with_suffix(".png")
            json_path = png_path.with_suffix(".png.json")
            header, blocks, image = decode_imgp(file_path, args.palette_order, args.pixel_layout)
            png_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(png_path)
            item = {
                "source": str(file_path),
                "png": str(png_path),
                "header": asdict(header),
                "blocks": asdict(blocks),
            }
            json_path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
            manifests.append(item)
        except Exception as exc:  # keep batch conversion moving
            failures.append({"source": str(file_path), "error": str(exc)})

    summary = {"converted": len(manifests), "failed": len(failures), "items": manifests, "failures": failures}
    if args.json:
        summary_path = Path(args.json)
    else:
        summary_path = output_dir / "_imgp_batch_manifest.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Converted IMGP files: {len(manifests)}")
    if failures:
        print(f"Failures: {len(failures)}")
    print(f"Manifest: {summary_path}")
    return 1 if failures and args.fail_on_error else 0


def command_inspect(args: argparse.Namespace) -> int:
    header, blocks, _ = decode_imgp(Path(args.input), args.palette_order, args.pixel_layout)
    result = {"header": asdict(header), "blocks": asdict(blocks)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect/export Gundam AGE PSP IMGP textures.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="export one IMGP .xi file to PNG")
    export.add_argument("input", help="IMGP .xi path")
    export.add_argument("--out", required=True, help="PNG output path")
    export.add_argument("--json", help="JSON manifest path")
    export.add_argument("--palette-order", choices=["rgba", "bgra"], default="rgba")
    export.add_argument("--pixel-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    export.set_defaults(func=command_export)

    batch = subparsers.add_parser("batch-export", help="export IMGP .xi files under a directory")
    batch.add_argument("input_dir", help="directory containing extracted .xi files")
    batch.add_argument("--out-dir", required=True, help="PNG output directory")
    batch.add_argument("--pattern", default="*.xi", help="glob pattern relative to input directory")
    batch.add_argument("--json", help="summary manifest path")
    batch.add_argument("--palette-order", choices=["rgba", "bgra"], default="rgba")
    batch.add_argument("--pixel-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    batch.add_argument("--fail-on-error", action="store_true")
    batch.set_defaults(func=command_batch_export)

    inspect = subparsers.add_parser("inspect", help="print decoded IMGP metadata without writing PNG")
    inspect.add_argument("input", help="IMGP .xi path")
    inspect.add_argument("--palette-order", choices=["rgba", "bgra"], default="rgba")
    inspect.add_argument("--pixel-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    inspect.set_defaults(func=command_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())





