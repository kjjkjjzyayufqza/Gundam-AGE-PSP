#!/usr/bin/env python3
"""Build a model/texture index for Gundam AGE PSP XPCK archives."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research.age_static_model_catalog import archive_area, archive_category, archive_family, archive_variant  # noqa: E402
from age_xpck_tool import XpckArchive, XpckError, iter_candidate_files, parse_xpck  # noqa: E402


MODEL_SUFFIXES = {".prm"}
TEXTURE_SUFFIXES = {".xi"}
MATERIAL_SUFFIXES = {".mtr", ".atr", ".txp"}
SKELETON_SUFFIXES = {".mbn"}
ANIMATION_SUFFIXES = {".mtn2", ".mtninf"}
ARCHIVE_EXTENSIONS = ".xc,.xb,.xa,.xk,.xi,.xq,.xv,.bin,.npcbin"


def parse_extensions(value: str) -> set[str] | None:
    if value == "":
        return None
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def normalize_for_match(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def matches_any(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return False
    value = normalize_for_match(path)
    name = path.name.lower()
    return any(fnmatch.fnmatch(value, pattern.lower().replace("\\", "/")) or fnmatch.fnmatch(name, pattern.lower()) for pattern in patterns)


def relpath_or_abs(path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
        except ValueError:
            continue
    return str(path)


def entry_suffix(name: str) -> str:
    return PureWindowsPath(name.replace("/", "\\")).suffix.lower()


def select_entries(entries: list[dict[str, Any]], suffixes: set[str]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry_suffix(str(entry.get("name") or "")) in suffixes]


def summarize_pipeline_manifest(path: Path) -> dict[str, Any] | None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    source = str(manifest.get("source") or "")
    if not source:
        return None

    models = manifest.get("models") or {}
    textures = manifest.get("textures") or {}
    materials = manifest.get("materials") or {}
    gltf = models.get("gltf") or {}
    mtl_records = materials.get("mtl_records") or []
    resolved = [item for item in mtl_records if item.get("map_Kd")]
    unresolved = [item for item in mtl_records if not item.get("map_Kd")]

    return {
        "source": source,
        "source_stem": PureWindowsPath(source).stem.lower(),
        "manifest": str(path),
        "output_dir": str(path.parent),
        "mesh_count": int(models.get("mesh_count") or 0),
        "texture_count": int(textures.get("converted") or 0),
        "material_count": int(materials.get("material_count") or 0),
        "resolved_material_count": len(resolved),
        "unresolved_material_count": len(unresolved),
        "unresolved_material_names": [str(item.get("material_name") or "") for item in unresolved],
        "obj_paths": [str(item.get("obj")) for item in models.get("items", []) if item.get("obj")],
        "gltf_path": str(gltf.get("path") or "") if gltf.get("path") else "",
        "texture_pngs": [str(item.get("png")) for item in textures.get("items", []) if item.get("png")],
    }


def collect_pipeline_manifests(roots: list[Path]) -> dict[str, list[dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for root in roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("_asset_pipeline_manifest.json"))
        for path in paths:
            item = summarize_pipeline_manifest(path)
            if not item:
                continue
            by_key[str(PureWindowsPath(item["source"]).stem).lower()].append(item)
            by_key[str(Path(item["source"]).resolve()).lower()].append(item)
    return by_key


def pipeline_exports_for(path: Path, by_key: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    exact = str(path.resolve()).lower()
    stem = path.stem.lower()
    seen: set[str] = set()
    items = []
    for key in (exact, stem):
        for item in by_key.get(key, []):
            manifest = item["manifest"]
            if manifest not in seen:
                seen.add(manifest)
                items.append(item)
    return items


def archive_to_index_item(
    archive_path: Path,
    archive: XpckArchive,
    input_roots: list[Path],
    pipeline_by_key: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    entries = [asdict(entry) for entry in archive.entries]
    models = select_entries(entries, MODEL_SUFFIXES)
    textures = select_entries(entries, TEXTURE_SUFFIXES)
    materials = select_entries(entries, MATERIAL_SUFFIXES)
    skeletons = select_entries(entries, SKELETON_SUFFIXES)
    animations = select_entries(entries, ANIMATION_SUFFIXES)
    resources = [entry for entry in entries if str(entry.get("name") or "").replace("\\", "/").lower().endswith("res.bin")]
    nested_archives = [entry for entry in entries if entry.get("detected_type") == "xpck_archive"]
    suffix_counts = Counter(entry_suffix(str(entry.get("name") or "")) or "(none)" for entry in entries)
    type_counts = Counter(str(entry.get("detected_type") or "unknown") for entry in entries)
    exports = pipeline_exports_for(archive_path, pipeline_by_key)

    return {
        "archive": str(archive_path),
        "archive_relative": relpath_or_abs(archive_path, input_roots),
        "stem": archive_path.stem,
        "extension": archive_path.suffix.lower(),
        "size": archive.size,
        "area": archive_area(str(archive_path)),
        "family": archive_family(str(archive_path)),
        "category": archive_category(str(archive_path)),
        "variant": archive_variant(str(archive_path)),
        "file_count": archive.header.file_count,
        "name_table_compression": archive.name_table_compression,
        "model_count": len(models),
        "texture_count": len(textures),
        "material_count": len(materials),
        "skeleton_count": len(skeletons),
        "animation_count": len(animations),
        "resource_count": len(resources),
        "nested_xpck_count": len(nested_archives),
        "model_files": [entry["name"] for entry in models],
        "texture_files": [entry["name"] for entry in textures],
        "material_files": [entry["name"] for entry in materials],
        "skeleton_files": [entry["name"] for entry in skeletons],
        "animation_files": [entry["name"] for entry in animations],
        "resource_files": [entry["name"] for entry in resources],
        "nested_xpck_files": [entry["name"] for entry in nested_archives],
        "entry_suffix_counts": dict(sorted(suffix_counts.items())),
        "entry_type_counts": dict(sorted(type_counts.items())),
        "pipeline_exports": exports,
        "has_model_and_texture": bool(models and textures),
        "entries": entries,
    }


def error_item(path: Path, input_roots: list[Path], error: Exception) -> dict[str, Any]:
    return {
        "archive": str(path),
        "archive_relative": relpath_or_abs(path, input_roots),
        "stem": path.stem,
        "extension": path.suffix.lower(),
        "status": "error",
        "error": f"{type(error).__name__}: {error}",
    }


def build_group_summaries(archives: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in archives:
        grouped[str(item.get(key) or "unknown")].append(item)
    rows = []
    for name, items in sorted(grouped.items()):
        rows.append(
            {
                "name": name,
                "archive_count": len(items),
                "model_count": sum(int(item.get("model_count") or 0) for item in items),
                "texture_count": sum(int(item.get("texture_count") or 0) for item in items),
                "material_count": sum(int(item.get("material_count") or 0) for item in items),
                "model_texture_archive_count": sum(1 for item in items if item.get("has_model_and_texture")),
                "pipeline_export_count": sum(len(item.get("pipeline_exports") or []) for item in items),
            }
        )
    return rows


def build_index(
    inputs: list[Path],
    include: list[str],
    exclude: list[str],
    extensions: set[str] | None,
    limit: int | None,
    pipeline_roots: list[Path],
) -> dict[str, Any]:
    pipeline_by_key = collect_pipeline_manifests(pipeline_roots)
    candidates = [
        path
        for path in iter_candidate_files(inputs, extensions, limit)
        if (not include or matches_any(path, include)) and not matches_any(path, exclude)
    ]

    archives = []
    errors = []
    for path in candidates:
        try:
            archives.append(archive_to_index_item(path, parse_xpck(path), inputs, pipeline_by_key))
        except Exception as exc:
            errors.append(error_item(path, inputs, exc))

    archives.sort(key=lambda item: item["archive"].lower())
    category_summaries = build_group_summaries(archives, "category")
    family_summaries = build_group_summaries(archives, "family")
    suffix_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for archive in archives:
        suffix_counts.update(archive["entry_suffix_counts"])
        type_counts.update(archive["entry_type_counts"])

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": [str(path) for path in inputs],
        "include": include,
        "exclude": exclude,
        "extensions": sorted(extensions) if extensions is not None else None,
        "archive_count": len(archives),
        "error_count": len(errors),
        "model_archive_count": sum(1 for item in archives if item["model_count"] > 0),
        "texture_archive_count": sum(1 for item in archives if item["texture_count"] > 0),
        "model_texture_archive_count": sum(1 for item in archives if item["has_model_and_texture"]),
        "model_count": sum(item["model_count"] for item in archives),
        "texture_count": sum(item["texture_count"] for item in archives),
        "material_count": sum(item["material_count"] for item in archives),
        "skeleton_count": sum(item["skeleton_count"] for item in archives),
        "animation_count": sum(item["animation_count"] for item in archives),
        "nested_xpck_count": sum(item["nested_xpck_count"] for item in archives),
        "pipeline_export_count": sum(len(item["pipeline_exports"]) for item in archives),
        "entry_suffix_counts": dict(sorted(suffix_counts.items())),
        "entry_type_counts": dict(sorted(type_counts.items())),
        "categories": category_summaries,
        "families": family_summaries,
        "archives": archives,
        "errors": errors,
        "notes": [
            "Index parses XPCK directory metadata only; it does not extract binary assets.",
            "Archive entries include model .prm, texture .xi, material .mtr/.atr/.txp, skeleton .mbn, and animation files.",
            "pipeline_exports are attached from existing _asset_pipeline_manifest.json files when --pipeline-root is provided.",
        ],
    }


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for row_index, row in enumerate(rows):
        lines.append("| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)) + " |")
        if row_index == 0:
            lines.append("| " + " | ".join("-" * widths[index] for index in range(len(row))) + " |")
    return "\n".join(lines)


def summary_rows(items: list[dict[str, Any]], title: str) -> str:
    rows = [[title, "Archives", "Models", "Textures", "Materials", "Model+Texture", "Exports"]]
    for item in sorted(items, key=lambda row: (-int(row["model_texture_archive_count"]), row["name"]))[:40]:
        rows.append(
            [
                str(item["name"]),
                str(item["archive_count"]),
                str(item["model_count"]),
                str(item["texture_count"]),
                str(item["material_count"]),
                str(item["model_texture_archive_count"]),
                str(item["pipeline_export_count"]),
            ]
        )
    return markdown_table(rows)


def archive_rows(archives: list[dict[str, Any]], *, by: str, limit: int) -> str:
    rows = [["Archive", "Category", "Models", "Textures", "Materials", "Exports"]]
    sorted_archives = sorted(archives, key=lambda item: (-int(item[by]), item["archive_relative"]))[:limit]
    for item in sorted_archives:
        rows.append(
            [
                str(item["archive_relative"]),
                str(item["category"]),
                str(item["model_count"]),
                str(item["texture_count"]),
                str(item["material_count"]),
                str(len(item["pipeline_exports"])),
            ]
        )
    return markdown_table(rows)


def index_to_markdown(index: dict[str, Any], sample_limit: int = 30) -> str:
    archives = index["archives"]
    return "\n\n".join(
        [
            "# Gundam AGE PSP Asset Index",
            f"Generated: `{index['generated_at']}`.",
            "This index lists XPCK archives and their model/texture/material entries. It does not extract assets.",
            "## Summary",
            markdown_table(
                [
                    ["Archives", "Errors", "Model Archives", "Texture Archives", "Model+Texture", "Models", "Textures", "Materials", "Pipeline Exports"],
                    [
                        str(index["archive_count"]),
                        str(index["error_count"]),
                        str(index["model_archive_count"]),
                        str(index["texture_archive_count"]),
                        str(index["model_texture_archive_count"]),
                        str(index["model_count"]),
                        str(index["texture_count"]),
                        str(index["material_count"]),
                        str(index["pipeline_export_count"]),
                    ],
                ]
            ),
            "## Categories",
            summary_rows(index["categories"], "Category"),
            "## Families",
            summary_rows(index["families"], "Family"),
            f"## Top Archives By Model Count",
            archive_rows(archives, by="model_count", limit=sample_limit),
            f"## Top Archives By Texture Count",
            archive_rows(archives, by="texture_count", limit=sample_limit),
            "## Notes",
            "\n".join(f"- {note}" for note in index["notes"]),
            "",
        ]
    )


def compact_index(index: dict[str, Any]) -> dict[str, Any]:
    archives = []
    for item in index["archives"]:
        archives.append(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "entries",
                    "entry_suffix_counts",
                    "entry_type_counts",
                }
            }
        )
    result = {
        key: value
        for key, value in index.items()
        if key
        not in {
            "archives",
        }
    }
    result["archives"] = archives
    result["notes"] = list(index["notes"]) + [
        "Compact index omits raw XPCK entry offset/size records but keeps model/texture/material file lists.",
    ]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Gundam AGE PSP model/texture archive index.")
    parser.add_argument("inputs", nargs="+", help="XPCK archive files or directories")
    parser.add_argument("--include", action="append", default=[], help="glob include filter; matches full path or filename")
    parser.add_argument("--exclude", action="append", default=[], help="glob exclude filter; matches full path or filename")
    parser.add_argument("--extensions", default=ARCHIVE_EXTENSIONS, help="comma-separated candidate archive extensions; empty scans all")
    parser.add_argument("--limit", type=int, help="limit number of candidate XPCK files")
    parser.add_argument("--pipeline-root", action="append", default=[], help="directory containing _asset_pipeline_manifest.json files")
    parser.add_argument("--json", required=True, help="JSON output path")
    parser.add_argument("--compact-json", help="compact JSON output path without per-entry offset records")
    parser.add_argument("--markdown", required=True, help="Markdown output path")
    parser.add_argument("--sample-limit", type=int, default=30, help="rows in top-archive markdown tables")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    extensions = parse_extensions(args.extensions)
    inputs = [Path(value) for value in args.inputs]
    pipeline_roots = [Path(value) for value in args.pipeline_root]

    try:
        index = build_index(inputs, args.include, args.exclude, extensions, args.limit, pipeline_roots)
    except XpckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    json_path = Path(args.json)
    compact_json_path = Path(args.compact_json) if args.compact_json else None
    markdown_path = Path(args.markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    if compact_json_path:
        compact_json_path.parent.mkdir(parents=True, exist_ok=True)
        compact_json_path.write_text(json.dumps(compact_index(index), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(index_to_markdown(index, args.sample_limit), encoding="utf-8")
    print(f"Archives: {index['archive_count']}")
    print(f"Model+texture archives: {index['model_texture_archive_count']}")
    print(f"JSON: {json_path}")
    if compact_json_path:
        print(f"Compact JSON: {compact_json_path}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





