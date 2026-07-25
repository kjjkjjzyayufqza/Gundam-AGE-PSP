#!/usr/bin/env python3
"""Inventory Gundam AGE PSP effect (age-fx) archives from game-native lists.

Primary game-native sources under an unpacked resource root:

- ``cmn/res/eff/effect_config.cfg.bin`` — Level-5 binary CFG with
  ``EFFECT_CONFIG`` / ``EFFECT_CONFIG_INDEX`` tags and a string table of
  effect IDs + ``.xc`` archive names under base path ``#/eff/``.
- ``cmn/res/eff/effect_define_field.cfg.bin`` — smaller field-effect subset.
- Per-archive XPCK filename tables — native member lists for ``.prm`` / ``.xi``.

This module is intentionally separate from the path-scanned
``age_asset_index`` so game-native tables are not confused with the research
index tool.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from age_xpck_tool import XpckError, parse_xpck  # noqa: E402

EFFECT_CONFIG_TAG = zlib.crc32(b"EFFECT_CONFIG") & 0xFFFFFFFF
EFFECT_CONFIG_INDEX_TAG = zlib.crc32(b"EFFECT_CONFIG_INDEX") & 0xFFFFFFFF
EFFECT_CONFIG_BEGIN_TAG = zlib.crc32(b"EFFECT_CONFIG_BEGIN") & 0xFFFFFFFF
EFFECT_CONFIG_END_TAG = zlib.crc32(b"EFFECT_CONFIG_END") & 0xFFFFFFFF
EFFECT_CONFIG_INDEX_BEGIN_TAG = zlib.crc32(b"EFFECT_CONFIG_INDEX_BEGIN") & 0xFFFFFFFF
EFFECT_CONFIG_INDEX_END_TAG = zlib.crc32(b"EFFECT_CONFIG_INDEX_END") & 0xFFFFFFFF
EFFECT_CONFIG_BASE_FILE_PATH_TAG = zlib.crc32(b"EFFECT_CONFIG_BASE_FILE_PATH") & 0xFFFFFFFF

MODEL_SUFFIXES = {".prm"}
TEXTURE_SUFFIXES = {".xi"}
MATERIAL_SUFFIXES = {".mtr", ".atr", ".txp"}
SKELETON_SUFFIXES = {".mbn"}
ARCHIVE_SUFFIXES = {".xc", ".xb", ".xa", ".xv", ".xk"}


@dataclass
class EffectConfigEntry:
    effect_id: str
    archive_name: str | None
    name_string_offset: int
    archive_string_offset: int | None
    name_crc32: int
    record_offset: int


@dataclass
class EffectConfigDocument:
    path: str
    size: int
    header_count: int
    string_table_offset: int
    base_path: str | None
    strings: list[str]
    entries: list[EffectConfigEntry]
    archive_names: list[str]


class EffectConfigError(RuntimeError):
    pass


def crc32_ascii(text: str) -> int:
    return zlib.crc32(text.encode("ascii")) & 0xFFFFFFFF


def read_c_string(blob: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(blob):
        raise EffectConfigError(f"string offset out of range: {offset}")
    end = blob.find(b"\x00", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("ascii", errors="replace")


def parse_string_table(data: bytes, table_offset: int) -> tuple[str | None, dict[int, str], list[str]]:
    if table_offset < 0 or table_offset >= len(data):
        raise EffectConfigError(f"invalid string table offset: {table_offset}")

    by_offset: dict[int, str] = {}
    ordered: list[str] = []
    cursor = table_offset
    base_path: str | None = None

    while cursor < len(data):
        if data[cursor] == 0:
            cursor += 1
            continue
        # Stop when remaining bytes no longer look like ASCII config strings.
        if data[cursor] < 0x20 or data[cursor] > 0x7E:
            break
        end = data.find(b"\x00", cursor)
        if end < 0:
            break
        text = data[cursor:end].decode("ascii", errors="replace")
        if text in {
            "EFFECT_CONFIG_BASE_FILE_PATH",
            "EFFECT_CONFIG_BEGIN",
            "EFFECT_CONFIG",
            "EFFECT_CONFIG_END",
            "EFFECT_CONFIG_INDEX_BEGIN",
            "EFFECT_CONFIG_INDEX",
            "EFFECT_CONFIG_INDEX_END",
        }:
            # Tag-name trailer after the string pool.
            break
        rel = cursor - table_offset
        by_offset[rel] = text
        ordered.append(text)
        if text.startswith("#/") and base_path is None:
            base_path = text
        cursor = end + 1

    return base_path, by_offset, ordered


def parse_effect_config_records(
    data: bytes,
    string_table_offset: int,
    strings_by_offset: dict[int, str],
) -> list[EffectConfigEntry]:
    entries: list[EffectConfigEntry] = []
    # Walk 4-byte aligned words for EFFECT_CONFIG tags that introduce records.
    limit = max(0, string_table_offset - 8)
    offset = 0
    while offset + 24 <= limit:
        tag = struct.unpack_from("<I", data, offset)[0]
        if tag != EFFECT_CONFIG_TAG:
            offset += 4
            continue

        # Observed record: tag, type, flags, name_off, name_crc, pad, archive_off, ...
        name_off = struct.unpack_from("<I", data, offset + 12)[0]
        name_crc = struct.unpack_from("<I", data, offset + 16)[0]
        archive_off = struct.unpack_from("<I", data, offset + 24)[0]

        effect_id = strings_by_offset.get(name_off)
        archive_name = strings_by_offset.get(archive_off)
        if effect_id is None:
            offset += 4
            continue
        if crc32_ascii(effect_id) != name_crc:
            # Skip false-positive tag alignments.
            offset += 4
            continue
        if archive_name is not None and not archive_name.endswith(".xc"):
            archive_name = None

        entries.append(
            EffectConfigEntry(
                effect_id=effect_id,
                archive_name=archive_name,
                name_string_offset=name_off,
                archive_string_offset=archive_off if archive_name is not None else None,
                name_crc32=name_crc,
                record_offset=offset,
            )
        )
        offset += 4

    # Prefer first occurrence per effect id.
    dedup: dict[str, EffectConfigEntry] = {}
    for entry in entries:
        dedup.setdefault(entry.effect_id, entry)
    return list(dedup.values())


def parse_effect_config_file(path: Path) -> EffectConfigDocument:
    data = path.read_bytes()
    if len(data) < 16:
        raise EffectConfigError(f"file too small: {path}")

    header_count, string_table_offset, _mid, _low = struct.unpack_from("<IIII", data, 0)
    if string_table_offset <= 0 or string_table_offset >= len(data):
        raise EffectConfigError(f"invalid string table offset in {path}: {string_table_offset}")

    base_path, by_offset, ordered = parse_string_table(data, string_table_offset)
    entries = parse_effect_config_records(data, string_table_offset, by_offset)
    archive_names = sorted({name for name in ordered if name.lower().endswith(".xc")})

    return EffectConfigDocument(
        path=str(path),
        size=len(data),
        header_count=header_count,
        string_table_offset=string_table_offset,
        base_path=base_path,
        strings=ordered,
        entries=entries,
        archive_names=archive_names,
    )


def find_resource_roots(start: Path) -> dict[str, Path]:
    """Locate common unpacked AGE roots under a user-supplied path."""
    start = start.resolve()
    result: dict[str, Path] = {}
    candidates = [start]
    if start.is_dir():
        candidates.extend([p for p in start.iterdir() if p.is_dir()])

    for root in candidates:
        psp = root / "psp"
        cmn = root / "cmn"
        if psp.is_dir():
            result.setdefault("psp", psp)
        if cmn.is_dir():
            result.setdefault("cmn", cmn)
        # Allow passing the parent that contains 资源解包 / unpack folders.
        for child in root.iterdir() if root.is_dir() else []:
            if not child.is_dir():
                continue
            if (child / "psp").is_dir():
                result.setdefault("psp", child / "psp")
            if (child / "cmn").is_dir():
                result.setdefault("cmn", child / "cmn")
    return result


def discover_default_unpack_root() -> Path | None:
    """Best-effort local discovery used by tests and offline verification."""
    ppsspp = Path(r"D:\PPSSPP")
    if not ppsspp.is_dir():
        return None
    for child in ppsspp.iterdir():
        if not child.is_dir() or not child.name.upper().startswith("AGE"):
            continue
        for sub in child.iterdir():
            if sub.is_dir() and (sub / "psp").is_dir() and (sub / "cmn").is_dir():
                return sub
    return None


def resolve_archive_path(eff_root: Path, archive_name: str) -> Path | None:
    direct = eff_root / archive_name
    if direct.is_file():
        return direct
    matches = list(eff_root.rglob(archive_name))
    if not matches:
        return None
    # Prefer shallowest match for stable inventory.
    matches.sort(key=lambda path: (len(path.parts), str(path).lower()))
    return matches[0]


def classify_entry_name(name: str) -> str:
    lower = name.lower()
    suffix = Path(lower).suffix
    if suffix in MODEL_SUFFIXES:
        return "model"
    if suffix in TEXTURE_SUFFIXES:
        return "texture"
    if suffix in MATERIAL_SUFFIXES:
        return "material"
    if suffix in SKELETON_SUFFIXES:
        return "skeleton"
    if suffix in ARCHIVE_SUFFIXES or lower == "res.bin":
        return "nested_or_resource"
    return "other"


def summarize_xpck_members(archive_path: Path) -> dict[str, Any]:
    try:
        archive = parse_xpck(archive_path)
    except (XpckError, OSError) as exc:
        return {
            "archive": str(archive_path),
            "parse_ok": False,
            "error": str(exc),
            "model_files": [],
            "texture_files": [],
            "material_files": [],
            "skeleton_files": [],
            "all_entries": [],
            "model_count": 0,
            "texture_count": 0,
        }

    models: list[str] = []
    textures: list[str] = []
    materials: list[str] = []
    skeletons: list[str] = []
    all_entries: list[dict[str, Any]] = []
    for entry in archive.entries:
        kind = classify_entry_name(entry.name)
        all_entries.append(
            {
                "name": entry.name,
                "kind": kind,
                "size": entry.size,
                "detected_type": entry.detected_type,
            }
        )
        if kind == "model":
            models.append(entry.name)
        elif kind == "texture":
            textures.append(entry.name)
        elif kind == "material":
            materials.append(entry.name)
        elif kind == "skeleton":
            skeletons.append(entry.name)

    return {
        "archive": str(archive_path),
        "parse_ok": True,
        "error": None,
        "file_count": archive.header.file_count,
        "name_table_compression": archive.name_table_compression,
        "model_files": models,
        "texture_files": textures,
        "material_files": materials,
        "skeleton_files": skeletons,
        "all_entries": all_entries,
        "model_count": len(models),
        "texture_count": len(textures),
        "material_count": len(materials),
        "skeleton_count": len(skeletons),
    }


def build_fx_inventory(
    unpack_root: Path,
    *,
    include_disk_only: bool = True,
    inspect_members: bool = True,
    member_limit: int | None = None,
) -> dict[str, Any]:
    unpack_root = unpack_root.resolve()
    roots = find_resource_roots(unpack_root)
    psp = roots.get("psp")
    cmn = roots.get("cmn")
    if psp is None or cmn is None:
        raise EffectConfigError(
            f"could not locate psp/ and cmn/ under {unpack_root}; "
            "pass the unpacked resource root that contains both folders"
        )

    eff_root = psp / "eff"
    cfg_path = cmn / "res" / "eff" / "effect_config.cfg.bin"
    field_cfg_path = cmn / "res" / "eff" / "effect_define_field.cfg.bin"
    load_info_path = cmn / "res" / "eff" / "load_effect_chara_info.cfg.bin"

    if not cfg_path.is_file():
        raise EffectConfigError(f"missing game-native effect config: {cfg_path}")

    config = parse_effect_config_file(cfg_path)
    field_config = parse_effect_config_file(field_cfg_path) if field_cfg_path.is_file() else None

    # Map archive basename -> effect ids from native config.
    archive_to_effects: dict[str, list[str]] = {}
    for entry in config.entries:
        if not entry.archive_name:
            continue
        archive_to_effects.setdefault(entry.archive_name, []).append(entry.effect_id)

    native_archives = list(config.archive_names)
    if field_config is not None:
        for name in field_config.archive_names:
            if name not in native_archives:
                native_archives.append(name)
        for entry in field_config.entries:
            if entry.archive_name:
                archive_to_effects.setdefault(entry.archive_name, []).append(entry.effect_id)

    disk_archives = sorted({path.name: path for path in eff_root.rglob("*.xc")}.values(), key=lambda p: str(p).lower()) if eff_root.is_dir() else []
    disk_by_name = {path.name: path for path in disk_archives}

    inventory_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    inspected_count = 0

    def add_row(archive_name: str, sources: list[str]) -> None:
        nonlocal inspected_count
        if archive_name in seen:
            return
        seen.add(archive_name)
        resolved = resolve_archive_path(eff_root, archive_name) if eff_root.is_dir() else None
        row: dict[str, Any] = {
            "archive_name": archive_name,
            "sources": sources,
            "effect_ids": sorted(set(archive_to_effects.get(archive_name, []))),
            "resolved_path": str(resolved) if resolved is not None else None,
            "on_disk": resolved is not None,
        }
        if inspect_members and resolved is not None:
            if member_limit is not None and inspected_count >= member_limit:
                row["members"] = None
                row["members_skipped"] = True
            else:
                row["members"] = summarize_xpck_members(resolved)
                row["members_skipped"] = False
                inspected_count += 1
        else:
            row["members"] = None
            row["members_skipped"] = not inspect_members
        inventory_rows.append(row)

    for name in native_archives:
        sources = ["effect_config.cfg.bin"]
        if field_config is not None and name in field_config.archive_names:
            sources.append("effect_define_field.cfg.bin")
        add_row(name, sources)

    if include_disk_only:
        for path in disk_archives:
            if path.name not in seen:
                add_row(path.name, ["psp/eff_directory"])

    model_archives = [
        row
        for row in inventory_rows
        if row.get("members") and row["members"].get("model_count", 0) > 0
    ]
    texture_archives = [
        row
        for row in inventory_rows
        if row.get("members") and row["members"].get("texture_count", 0) > 0
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unpack_root": str(unpack_root),
        "psp_root": str(psp),
        "cmn_root": str(cmn),
        "eff_root": str(eff_root),
        "game_native_lists": {
            "effect_config": {
                "path": config.path,
                "size": config.size,
                "header_count": config.header_count,
                "string_table_offset": config.string_table_offset,
                "base_path": config.base_path,
                "effect_entry_count": len(config.entries),
                "archive_name_count": len(config.archive_names),
                "tags": {
                    "EFFECT_CONFIG": f"{EFFECT_CONFIG_TAG:08x}",
                    "EFFECT_CONFIG_INDEX": f"{EFFECT_CONFIG_INDEX_TAG:08x}",
                    "EFFECT_CONFIG_BASE_FILE_PATH": f"{EFFECT_CONFIG_BASE_FILE_PATH_TAG:08x}",
                },
            },
            "effect_define_field": None
            if field_config is None
            else {
                "path": field_config.path,
                "size": field_config.size,
                "effect_entry_count": len(field_config.entries),
                "archive_name_count": len(field_config.archive_names),
            },
            "load_effect_chara_info": {
                "path": str(load_info_path),
                "present": load_info_path.is_file(),
                "role": "character effect load helper; not a global FX archive catalog",
            },
        },
        "summary": {
            "native_config_archive_count": len(native_archives),
            "disk_eff_archive_count": len(disk_archives),
            "inventory_archive_count": len(inventory_rows),
            "resolved_archive_count": sum(1 for row in inventory_rows if row["on_disk"]),
            "missing_archive_count": sum(1 for row in inventory_rows if not row["on_disk"]),
            "inspected_with_models": len(model_archives),
            "inspected_with_textures": len(texture_archives),
        },
        "effect_entries": [asdict(entry) for entry in config.entries],
        "archives": inventory_rows,
        "notes": [
            "effect_config.cfg.bin is the game-native logical FX catalog (effect id -> .xc name).",
            "psp/eff may contain additional archives not referenced by effect_config (evt packs, variants).",
            "Complete model/texture members for each .xc come from that archive's native XPCK filename table.",
            "Project age_asset_index is a research scanner, not a game-native list.",
        ],
    }


def inventory_to_markdown(inventory: dict[str, Any], sample_limit: int = 40) -> str:
    summary = inventory["summary"]
    native = inventory["game_native_lists"]["effect_config"]
    lines = [
        "# AGE FX Native Index Inventory",
        "",
        f"Generated: `{inventory['generated_at']}`",
        "",
        "## Game-native list",
        "",
        f"- Config: `{native['path']}`",
        f"- Base path tag: `{native.get('base_path')}`",
        f"- Effect entries: `{native['effect_entry_count']}`",
        f"- Unique `.xc` names in config string table: `{native['archive_name_count']}`",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"| --- | ---: |",
        f"| Native config archives | {summary['native_config_archive_count']} |",
        f"| Disk `psp/eff` archives | {summary['disk_eff_archive_count']} |",
        f"| Inventory rows | {summary['inventory_archive_count']} |",
        f"| Resolved on disk | {summary['resolved_archive_count']} |",
        f"| Missing on disk | {summary['missing_archive_count']} |",
        f"| Inspected with models | {summary['inspected_with_models']} |",
        f"| Inspected with textures | {summary['inspected_with_textures']} |",
        "",
        "## Sample archives",
        "",
        "| Archive | Sources | Effects | Models | Textures | Path |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in inventory["archives"][:sample_limit]:
        members = row.get("members") or {}
        lines.append(
            "| {archive} | {sources} | {effects} | {models} | {textures} | `{path}` |".format(
                archive=row["archive_name"],
                sources=",".join(row["sources"]),
                effects=len(row.get("effect_ids") or []),
                models=members.get("model_count", "-"),
                textures=members.get("texture_count", "-"),
                path=row.get("resolved_path") or "",
            )
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in inventory.get("notes", []))
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "unpack_root",
        nargs="?",
        help="Unpacked AGE resource root containing psp/ and cmn/ (optional if discoverable)",
    )
    parser.add_argument("--json", required=True, help="Write inventory JSON")
    parser.add_argument("--markdown", help="Write inventory Markdown summary")
    parser.add_argument(
        "--native-only",
        action="store_true",
        help="Only include archives named by effect_config / effect_define_field",
    )
    parser.add_argument(
        "--no-members",
        action="store_true",
        help="Do not open XPCK archives to list .prm/.xi members",
    )
    parser.add_argument(
        "--member-limit",
        type=int,
        default=None,
        help="Optional cap on how many archives get XPCK member inspection",
    )
    args = parser.parse_args(argv)

    unpack_root: Path | None
    if args.unpack_root:
        unpack_root = Path(args.unpack_root)
    else:
        unpack_root = discover_default_unpack_root()
        if unpack_root is None:
            print("PSP_RESOURCE_ROOT unavailable: pass unpack root containing psp/ and cmn/", file=sys.stderr)
            return 2

    inventory = build_fx_inventory(
        unpack_root,
        include_disk_only=not args.native_only,
        inspect_members=not args.no_members,
        member_limit=args.member_limit,
    )

    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(f"wrote {json_path}")

    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(inventory_to_markdown(inventory), encoding="utf-8")
        print(f"wrote {md_path}")

    summary = inventory["summary"]
    print(
        "native={native} disk={disk} resolved={resolved} models={models} textures={textures}".format(
            native=summary["native_config_archive_count"],
            disk=summary["disk_eff_archive_count"],
            resolved=summary["resolved_archive_count"],
            models=summary["inspected_with_models"],
            textures=summary["inspected_with_textures"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
