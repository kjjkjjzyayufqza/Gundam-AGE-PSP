#!/usr/bin/env python3
"""Large-sample survey runner for AGE PSP map archives."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.age_map_report import export_archive, summarize_manifest  # noqa: E402


def collect_inputs(input_root: Path, include: list[str], exclude: list[str]) -> list[Path]:
    matched: dict[Path, None] = {}
    for pattern in include:
        for path in sorted(input_root.glob(pattern)):
            if path.is_file():
                matched[path] = None
    excluded: set[Path] = set()
    for pattern in exclude:
        excluded.update(path for path in input_root.glob(pattern) if path.is_file())
    return [path for path in sorted(matched) if path not in excluded]


def classify_archive(path: Path) -> str:
    stem = path.stem.lower()
    if "chr" in stem:
        return "chr_companion"
    if stem.endswith("sky"):
        return "sky"
    if stem.startswith("fe"):
        return "fe"
    if stem and stem[0].isalpha():
        return stem[0]
    return "other"


def cleanup_summary_paths(summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(summary)
    summary["output_dir"] = None
    summary["output_dir_relative"] = None
    summary["gltf_path"] = None
    summary["gltf_relative"] = None
    summary["mtl_relative"] = None
    summary["texture_relatives"] = []
    return summary


def build_error_summary(
    archive_path: Path,
    sample_dir: Path,
    out_root: Path,
    error: Exception,
    index: int,
) -> dict[str, Any]:
    return {
        "name": archive_path.stem,
        "source": str(archive_path),
        "source_name": archive_path.name,
        "sample_index": index,
        "archive_group": classify_archive(archive_path),
        "status": "error",
        "error_message": f"{type(error).__name__}: {error}",
        "output_dir": str(sample_dir),
        "output_dir_relative": str(sample_dir.relative_to(out_root)).replace("\\", "/"),
        "mesh_count": 0,
        "texture_count": 0,
        "material_count": 0,
        "resolved_material_count": 0,
        "unresolved_material_count": 0,
        "unresolved_used_material_count": 0,
        "unresolved_collision_material_count": 0,
        "unresolved_aux_material_count": 0,
        "unresolved_visual_material_count": 0,
        "unresolved_visual_effect_material_count": 0,
        "unresolved_visual_plain_material_count": 0,
        "unresolved_visual_effect_face_count": 0,
        "unresolved_visual_plain_face_count": 0,
        "unresolved_visual_plain_face_ratio": 0.0,
        "gltf_texture_count": 0,
        "weighted_vertex_count": 0,
        "skin_count": 0,
        "triangle_count": 0,
        "absent_uv_mesh_count": 0,
        "absent_uv_collision_mesh_count": 0,
        "absent_uv_non_collision_mesh_count": 0,
        "uv_formats": {},
        "position_formats": {},
        "texture_mapping_confidence": {},
        "texture_sizes": {},
        "pixel_layouts": {},
        "gltf_path": None,
        "gltf_relative": None,
        "mtl_relative": None,
        "texture_relatives": [],
        "unresolved_visual_materials": [],
        "notes": ["sample export failed before summary completed"],
    }


def build_group_summaries(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(str(sample["archive_group"]), []).append(sample)

    results = []
    for key in sorted(grouped):
        rows = grouped[key]
        ok_rows = [row for row in rows if row.get("status", "ok") == "ok"]
        results.append(
            {
                "archive_group": key,
                "sample_count": len(rows),
                "failed_count": sum(1 for row in rows if row.get("status") == "error"),
                "plain_problem_count": sum(1 for row in ok_rows if row["unresolved_visual_plain_material_count"] > 0),
                "effect_only_problem_count": sum(
                    1
                    for row in ok_rows
                    if row["unresolved_visual_plain_material_count"] == 0 and row["unresolved_visual_material_count"] > 0
                ),
                "clean_visual_count": sum(1 for row in ok_rows if row["unresolved_visual_material_count"] == 0),
                "unexpected_weight_count": sum(1 for row in ok_rows if row["weighted_vertex_count"] > 0),
                "unexpected_skin_count": sum(1 for row in ok_rows if row["skin_count"] > 0),
                "max_plain_face_ratio": max((float(row["unresolved_visual_plain_face_ratio"]) for row in ok_rows), default=0.0),
            }
        )
    return results


def build_report(
    inputs: list[Path],
    out_root: Path,
    triangulation: str,
    texture_layout: str,
    overwrite: bool,
    cleanup_samples: bool,
) -> dict[str, Any]:
    scratch_root = out_root / "samples"
    scratch_root.mkdir(parents=True, exist_ok=True)
    samples = []
    for index, archive_path in enumerate(inputs, start=1):
        sample_dir = scratch_root / archive_path.stem
        try:
            manifest = export_archive(archive_path, sample_dir, triangulation, texture_layout, overwrite)
            summary = summarize_manifest(manifest, out_root)
            summary["archive_group"] = classify_archive(archive_path)
            summary["source_name"] = archive_path.name
            summary["sample_index"] = index
            summary["status"] = "ok"
            if cleanup_samples:
                summary = cleanup_summary_paths(summary)
                shutil.rmtree(sample_dir, ignore_errors=True)
        except Exception as exc:
            summary = build_error_summary(archive_path, sample_dir, out_root, exc, index)
        samples.append(summary)

    ranked_plain = sorted(
        [row for row in samples if row.get("status", "ok") == "ok" and row["unresolved_visual_plain_material_count"] > 0],
        key=lambda row: (-float(row["unresolved_visual_plain_face_ratio"]), row["name"]),
    )
    ranked_effect_only = sorted(
        [
            row
            for row in samples
            if row.get("status", "ok") == "ok"
            and row["unresolved_visual_plain_material_count"] == 0
            and row["unresolved_visual_effect_material_count"] > 0
        ],
        key=lambda row: (-int(row["unresolved_visual_effect_face_count"]), row["name"]),
    )
    return {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_root": str(inputs[0].parent) if inputs else "",
        "triangulation": triangulation,
        "texture_layout": texture_layout,
        "cleanup_samples": cleanup_samples,
        "sample_count": len(samples),
        "failed_sample_count": sum(1 for row in samples if row.get("status") == "error"),
        "group_summaries": build_group_summaries(samples),
        "plain_problem_count": len(ranked_plain),
        "effect_only_problem_count": len(ranked_effect_only),
        "clean_visual_count": sum(
            1 for row in samples if row.get("status", "ok") == "ok" and row["unresolved_visual_material_count"] == 0
        ),
        "top_plain_samples": ranked_plain[:20],
        "top_effect_only_samples": ranked_effect_only[:20],
        "samples": samples,
        "notes": [
            "This survey is intended for large-sample map conversion checks.",
            "When cleanup_samples=true, per-sample extracted assets are deleted after summary collection.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AGE PSP Map Survey Report",
        "",
        f"Generated on `{report['generated_at']}` from `{report['input_root']}`.",
        f"Texture layout: `{report['texture_layout']}`.",
        f"Cleanup samples: `{report['cleanup_samples']}`.",
        "",
        "## Totals",
        "",
        f"- Samples: `{report['sample_count']}`",
        f"- Failed samples: `{report['failed_sample_count']}`",
        f"- Clean visual exports: `{report['clean_visual_count']}`",
        f"- Plain unresolved samples: `{report['plain_problem_count']}`",
        f"- Effect-only unresolved samples: `{report['effect_only_problem_count']}`",
        "",
        "## Groups",
        "",
        "| Group | Samples | Failed | Clean Visual | Plain Problems | Effect Only | Unexpected Weights | Unexpected Skins | Max Plain Ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in report["group_summaries"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    group["archive_group"],
                    str(group["sample_count"]),
                    str(group["failed_count"]),
                    str(group["clean_visual_count"]),
                    str(group["plain_problem_count"]),
                    str(group["effect_only_problem_count"]),
                    str(group["unexpected_weight_count"]),
                    str(group["unexpected_skin_count"]),
                    f"{group['max_plain_face_ratio']:.2%}",
                ]
            )
            + " |"
        )

    lines.extend(["", "## Top Plain Samples", ""])
    if not report["top_plain_samples"]:
        lines.append("- none")
    else:
        for sample in report["top_plain_samples"]:
            lines.append(
                f"- `{sample['name']}`: plain `{sample['unresolved_visual_plain_material_count']}`, "
                f"faces `{sample['unresolved_visual_plain_face_count']}` / `{sample['triangle_count']}` "
                f"(`{sample['unresolved_visual_plain_face_ratio']:.2%}`), "
                f"materials `{', '.join(sample['unresolved_visual_materials'])}`"
            )

    lines.extend(["", "## Top Effect-Only Samples", ""])
    if not report["top_effect_only_samples"]:
        lines.append("- none")
    else:
        for sample in report["top_effect_only_samples"]:
            lines.append(
                f"- `{sample['name']}`: effect `{sample['unresolved_visual_effect_material_count']}`, "
                f"faces `{sample['unresolved_visual_effect_face_count']}`, "
                f"materials `{', '.join(sample['unresolved_visual_materials'])}`"
            )
    lines.append("")
    return "\n".join(lines)


def command_survey(args: argparse.Namespace) -> int:
    input_root = Path(args.input_root)
    inputs = collect_inputs(input_root, args.include, args.exclude)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    report = build_report(
        inputs=inputs,
        out_root=out_root,
        triangulation=args.triangulation,
        texture_layout=args.texture_layout,
        overwrite=args.overwrite,
        cleanup_samples=args.cleanup_samples,
    )

    json_path = out_root / "map_survey_report.json"
    md_path = out_root / "MAP_SURVEY_REPORT.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"Samples: {report['sample_count']}")
    print(f"Plain problems: {report['plain_problem_count']}")
    print(f"Effect-only problems: {report['effect_only_problem_count']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Large-sample survey for AGE PSP map archives.")
    parser.add_argument("--input-root", required=True, help="directory containing map .xc archives")
    parser.add_argument("--out-root", required=True, help="root output directory for survey reports")
    parser.add_argument("--include", action="append", default=["*.xc"], help="glob pattern to include (repeatable)")
    parser.add_argument("--exclude", action="append", default=[], help="glob pattern to exclude (repeatable)")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--texture-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--cleanup-samples", action="store_true")
    parser.set_defaults(func=command_survey)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




