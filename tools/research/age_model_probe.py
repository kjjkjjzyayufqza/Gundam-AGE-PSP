#!/usr/bin/env python3
"""Probe Gundam AGE PSP XMPR/XPRM model candidate files.

This is an evidence-gathering tool, not a final model exporter. It records
the fields currently visible in .prm files and extracts candidate XPVB/XPVI
layout information so the mesh format can be refined without hand-copying
hex dumps.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path


MAGIC_RE = re.compile(rb"XMPR|XPRM|XPVB|XPVI|XPV.")


@dataclass
class MagicHit:
    offset: int
    magic: str
    u32: list[int]


@dataclass
class XpvbProbe:
    offset: int
    header_size: int
    field_04_high: int
    data_offset: int
    field_08_high: int
    count_word: int
    data_size_word: int
    data_start: int
    likely_data_end: int
    format_words: list[int]


@dataclass
class XpviProbe:
    offset: int
    word_04: int
    word_08: int
    word_0c: int
    word_10: int
    word_14: int
    word_18: int
    word_1c: int


@dataclass
class XmprProbe:
    path: str
    size: int
    top_header_size: int | None
    top_words_08_3c: list[int]
    magic_hits: list[MagicHit]
    xpvb: list[XpvbProbe]
    xpvi: list[XpviProbe]


def read_u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, offset)[0]


def read_u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from("<H", data, offset)[0]


def probe_file(path: Path) -> XmprProbe:
    data = path.read_bytes()
    top_header_size = read_u32(data, 4) if data[:4] == b"XMPR" else None
    top_words = [read_u32(data, off) for off in range(0x08, min(0x40, len(data) - 3), 4)]

    hits: list[MagicHit] = []
    xpvb: list[XpvbProbe] = []
    xpvi: list[XpviProbe] = []

    for match in MAGIC_RE.finditer(data):
        offset = match.start()
        magic = match.group().decode("latin1", errors="replace")
        words = [read_u32(data, offset + i) for i in range(0, min(0x20, len(data) - offset), 4)]
        hits.append(MagicHit(offset=offset, magic=magic, u32=words))

        if match.group() == b"XPVB":
            packed_04 = read_u32(data, offset + 4)
            packed_08 = read_u32(data, offset + 8)
            header_size = packed_04 & 0xFFFF
            field_04_high = (packed_04 >> 16) & 0xFFFF
            data_offset = packed_08 & 0xFFFF
            field_08_high = (packed_08 >> 16) & 0xFFFF
            data_start = offset + data_offset
            data_size_word = read_u32(data, offset + 0x10)
            xpvb.append(
                XpvbProbe(
                    offset=offset,
                    header_size=header_size,
                    field_04_high=field_04_high,
                    data_offset=data_offset,
                    field_08_high=field_08_high,
                    count_word=read_u32(data, offset + 0x0C),
                    data_size_word=data_size_word,
                    data_start=data_start,
                    likely_data_end=min(len(data), data_start + data_size_word),
                    format_words=[read_u32(data, offset + off) for off in range(0x14, 0x2C, 4)],
                )
            )
        elif match.group() == b"XPVI":
            xpvi.append(
                XpviProbe(
                    offset=offset,
                    word_04=read_u32(data, offset + 0x04),
                    word_08=read_u32(data, offset + 0x08),
                    word_0c=read_u32(data, offset + 0x0C),
                    word_10=read_u32(data, offset + 0x10),
                    word_14=read_u32(data, offset + 0x14),
                    word_18=read_u32(data, offset + 0x18),
                    word_1c=read_u32(data, offset + 0x1C),
                )
            )

    return XmprProbe(
        path=str(path),
        size=len(data),
        top_header_size=top_header_size,
        top_words_08_3c=top_words,
        magic_hits=hits,
        xpvb=xpvb,
        xpvi=xpvi,
    )


def iter_inputs(inputs: list[str]) -> list[Path]:
    result: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            result.extend(sorted(path.rglob("*.prm")))
        else:
            result.append(path)
    return result


def command_probe(args: argparse.Namespace) -> int:
    probes = [asdict(probe_file(path)) for path in iter_inputs(args.inputs)]
    result = {"count": len(probes), "probes": probes}
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"XMPR probes: {len(probes)}")
    for probe in probes[: args.print_files]:
        print(f"{probe['path']} size={probe['size']} top_header=0x{(probe['top_header_size'] or 0):X}")
        for block in probe["xpvb"]:
            print(
                "  XPVB "
                f"off=0x{block['offset']:X} header=0x{block['header_size']:X} "
                f"field04_hi=0x{block['field_04_high']:X} data_off=0x{block['data_offset']:X} "
                f"field08_hi=0x{block['field_08_high']:X} count_word={block['count_word']} "
                f"data_size_word={block['data_size_word']} data=0x{block['data_start']:X}-0x{block['likely_data_end']:X}"
            )
        for block in probe["xpvi"]:
            print(
                "  XPVI "
                f"off=0x{block['offset']:X} w04={block['word_04']} "
                f"w1c={block['word_1c']}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Gundam AGE PSP XMPR .prm model candidates.")
    parser.add_argument("inputs", nargs="+", help=".prm files or directories")
    parser.add_argument("--json", help="write JSON probe report")
    parser.add_argument("--print-files", type=int, default=20)
    parser.set_defaults(func=command_probe)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




