"""Build a static model catalog from AGE PSP model survey JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
from typing import Any


def path_parts(path: str) -> list[str]:
    return list(PureWindowsPath(path).parts)


def archive_area(path: str) -> str:
    parts = [part.lower() for part in path_parts(path)]
    if "psp" in parts:
        index = parts.index("psp")
        if index + 1 < len(parts):
            return parts[index + 1]
    return PureWindowsPath(path).parent.name.lower()


def archive_family(path: str) -> str:
    parsed = PureWindowsPath(path)
    candidates = [parsed.parent.name.lower(), parsed.stem.lower()]
    for value in candidates:
        match = re.match(r"([a-z]+)\d+", value)
        if match:
            return match.group(1)
    match = re.match(r"([a-z]+)", parsed.stem.lower())
    return match.group(1) if match else "unknown"


def archive_variant(path: str) -> str:
    stem = PureWindowsPath(path).stem.lower()
    match = re.search(r"_p(\d+)$", stem)
    if not match:
        return "non_part_archive"
    return "base_p000" if match.group(1) == "000" else "part_variant"


def archive_category(path: str) -> str:
    area = archive_area(path)
    family = archive_family(path)
    if area == "map":
        return "map"
    if family == "ms":
        return "mobile_suit"
    if family == "ue":
        return "ue_unit"
    if family == "bs":
        return "vehicle_or_ship"
    if family in {"hu", "np"}:
        return "human_or_npc"
    if area == "chr":
        return f"chr_{family}"
    return area or "unknown"


def prm_vertex_count(prm: dict[str, Any]) -> int:
    return int(prm.get("xpvb", {}).get("vertex_count") or 0)


def prm_position_format(prm: dict[str, Any]) -> str:
    return str(prm.get("xpvb", {}).get("position_format") or "unknown")


def prm_uv0_format(prm: dict[str, Any]) -> str:
    return str(prm.get("xpvb", {}).get("uv0_format") or "unknown")


def prm_has_weights(prm: dict[str, Any]) -> bool:
    attrs = prm.get("xpvb", {}).get("attributes") or []
    for attr in attrs:
        if int(attr.get("slot", -1)) == 7 and int(attr.get("count", 0)) > 0 and int(attr.get("size", 0)) > 0:
            return True
    return False


def archive_summary(archive: dict[str, Any]) -> dict[str, Any]:
    prms = archive.get("prms") or []
    vertex_count = sum(prm_vertex_count(prm) for prm in prms)
    weighted_prms = sum(1 for prm in prms if prm_has_weights(prm))
    return {
        "archive": archive["archive"],
        "area": archive_area(archive["archive"]),
        "family": archive_family(archive["archive"]),
        "category": archive_category(archive["archive"]),
        "variant": archive_variant(archive["archive"]),
        "file_count": int(archive.get("file_count") or 0),
        "prm_count": int(archive.get("prm_count") or 0),
        "failed_prm_count": int(archive.get("failed_prm_count") or 0),
        "vertex_count": vertex_count,
        "weighted_prm_count": weighted_prms,
        "has_weights": weighted_prms > 0,
        "position_formats": dict(Counter(prm_position_format(prm) for prm in prms)),
        "uv0_formats": dict(Counter(prm_uv0_format(prm) for prm in prms)),
    }


def aggregate_group(name: str, archives: list[dict[str, Any]], sample_limit: int) -> dict[str, Any]:
    prms = sum(item["prm_count"] for item in archives)
    weighted_archives = sum(1 for item in archives if item["has_weights"])
    position_formats: Counter[str] = Counter()
    uv0_formats: Counter[str] = Counter()
    variants: Counter[str] = Counter()
    families: Counter[str] = Counter()
    for item in archives:
        position_formats.update(item["position_formats"])
        uv0_formats.update(item["uv0_formats"])
        variants[item["variant"]] += 1
        families[item["family"]] += 1
    top = sorted(archives, key=lambda item: (item["vertex_count"], item["prm_count"]), reverse=True)[:sample_limit]
    return {
        "name": name,
        "archive_count": len(archives),
        "prm_count": prms,
        "vertex_count": sum(item["vertex_count"] for item in archives),
        "weighted_archive_count": weighted_archives,
        "weighted_prm_count": sum(item["weighted_prm_count"] for item in archives),
        "position_formats": dict(sorted(position_formats.items())),
        "uv0_formats": dict(sorted(uv0_formats.items())),
        "variants": dict(sorted(variants.items())),
        "families": dict(sorted(families.items())),
        "samples_by_vertices": top,
    }


def build_catalog(survey: dict[str, Any], sample_limit: int = 10) -> dict[str, Any]:
    archives = [archive_summary(item) for item in survey.get("archives", []) if int(item.get("prm_count") or 0) > 0]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in archives:
        by_category[item["category"]].append(item)
        by_family[item["family"]].append(item)

    return {
        "source_inputs": survey.get("inputs", []),
        "archive_count": len(survey.get("archives", [])),
        "archives_with_prm": len(archives),
        "prm_count": sum(item["prm_count"] for item in archives),
        "vertex_count": sum(item["vertex_count"] for item in archives),
        "weighted_archive_count": sum(1 for item in archives if item["has_weights"]),
        "weighted_prm_count": sum(item["weighted_prm_count"] for item in archives),
        "category_count": len(by_category),
        "family_count": len(by_family),
        "categories": [
            aggregate_group(name, items, sample_limit)
            for name, items in sorted(by_category.items())
        ],
        "families": [
            aggregate_group(name, items, sample_limit)
            for name, items in sorted(by_family.items())
        ],
        "notes": [
            "Catalog is derived from survey JSON; it does not extract binary assets.",
            "Weighted archives are identified by active XPVB slot 7 records.",
            "Samples are sorted by decoded vertex count and are intended as export candidates.",
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


def catalog_to_markdown(catalog: dict[str, Any]) -> str:
    rows = [["Category", "Archives", "PRMs", "Vertices", "Weighted Archives", "Top Sample"]]
    for item in sorted(catalog["categories"], key=lambda entry: entry["vertex_count"], reverse=True):
        sample = item["samples_by_vertices"][0]["archive"] if item["samples_by_vertices"] else ""
        rows.append(
            [
                item["name"],
                str(item["archive_count"]),
                str(item["prm_count"]),
                str(item["vertex_count"]),
                str(item["weighted_archive_count"]),
                sample,
            ]
        )

    family_rows = [["Family", "Archives", "PRMs", "Vertices", "Weighted Archives", "Top Sample"]]
    for item in sorted(catalog["families"], key=lambda entry: entry["vertex_count"], reverse=True)[:20]:
        sample = item["samples_by_vertices"][0]["archive"] if item["samples_by_vertices"] else ""
        family_rows.append(
            [
                item["name"],
                str(item["archive_count"]),
                str(item["prm_count"]),
                str(item["vertex_count"]),
                str(item["weighted_archive_count"]),
                sample,
            ]
        )

    return "\n\n".join(
        [
            "# Gundam AGE PSP Static Model Catalog",
            "Derived from `outputs/manifests/psp_xc_model_survey_all.json`.",
            "No binary assets are extracted by this catalog step.",
            "## Summary",
            markdown_table(
                [
                    ["Archives with PRM", "PRMs", "Vertices", "Weighted Archives", "Weighted PRMs"],
                    [
                        str(catalog["archives_with_prm"]),
                        str(catalog["prm_count"]),
                        str(catalog["vertex_count"]),
                        str(catalog["weighted_archive_count"]),
                        str(catalog["weighted_prm_count"]),
                    ],
                ]
            ),
            "## Categories",
            markdown_table(rows),
            "## Top Families",
            markdown_table(family_rows),
            "## Notes",
            "\n".join(f"- {note}" for note in catalog["notes"]),
            "",
        ]
    )


def command_catalog(args: argparse.Namespace) -> int:
    survey = json.loads(Path(args.survey).read_text(encoding="utf-8"))
    catalog = build_catalog(survey, args.sample_limit)
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(catalog_to_markdown(catalog), encoding="utf-8")
    print(f"Archives with PRM: {catalog['archives_with_prm']}")
    print(f"PRMs: {catalog['prm_count']}")
    print(f"Vertices: {catalog['vertex_count']}")
    print(f"Weighted archives: {catalog['weighted_archive_count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build static model catalog from AGE PSP survey JSON.")
    parser.add_argument("survey", help="survey JSON from age_model_survey.py")
    parser.add_argument("--json", help="catalog JSON output path")
    parser.add_argument("--markdown", help="catalog Markdown output path")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.set_defaults(func=command_catalog)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




