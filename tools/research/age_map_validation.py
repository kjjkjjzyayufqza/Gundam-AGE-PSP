#!/usr/bin/env python3
"""Batch validation/reporting for AGE PSP map-model exports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from age_asset_pipeline import run_pipeline  # noqa: E402
from age_xpck_tool import extract_archive  # noqa: E402


def build_pipeline_args(
    archive_path: Path,
    out_dir: Path,
    triangulation: str,
    texture_layout: str,
    overwrite: bool,
) -> argparse.Namespace:
    return argparse.Namespace(
        input=str(archive_path),
        out_dir=str(out_dir),
        extract_dir=str(out_dir / "extracted"),
        json=None,
        name=archive_path.stem,
        triangulation=triangulation,
        keep_degenerate_faces=False,
        texture_pattern="*.xi",
        texture_layout=texture_layout,
        skip_textures=False,
        skip_models=False,
        skip_materials=False,
        mbn_root=[],
        skeleton_archive=[],
        skeleton_survey=[],
        overwrite=overwrite,
    )


def export_archive(
    archive_path: Path,
    out_dir: Path,
    triangulation: str,
    texture_layout: str,
    overwrite: bool,
) -> dict[str, Any]:
    args = build_pipeline_args(archive_path, out_dir, triangulation, texture_layout, overwrite)
    extracted_dir = Path(args.extract_dir)
    extract_manifest = extract_archive(archive_path, extracted_dir, overwrite)
    manifest = run_pipeline(args, extracted_dir, "xpck_archive")
    manifest["xpck"] = {
        "file_count": extract_manifest["archive"]["header"]["file_count"],
        "written_files": len(extract_manifest["written_files"]),
        "manifest": str(extracted_dir / "_xpck_manifest.json"),
    }
    manifest_path = out_dir / "_asset_pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter(str(item.get(key) or "unknown") for item in items)
    return dict(sorted(counter.items()))


def is_collision_like_mesh(mesh_name: str | None, material_name: str | None) -> bool:
    mesh_value = (mesh_name or "").lower()
    material_value = (material_name or "").lower()
    return mesh_value.startswith("col_") or material_value.startswith("cl.")


def is_aux_like_name(mesh_name: str | None, material_name: str | None) -> bool:
    merged = f"{mesh_name or ''} {material_name or ''}".lower()
    return any(token in merged for token in ("camer", "eye", "shadow"))


def is_effect_like_name(mesh_name: str | None, material_name: str | None) -> bool:
    merged = f"{mesh_name or ''} {material_name or ''}".lower()
    return any(token in merged for token in ("-tm", "_tm", "add", "aof"))


def summarize_manifest(manifest: dict[str, Any], report_root: Path) -> dict[str, Any]:
    output_dir = Path(manifest["output_dir"])
    textures = manifest.get("textures") or {}
    materials = manifest.get("materials") or {}
    models = manifest.get("models") or {}
    gltf = models.get("gltf") or {}
    mtl_records = materials.get("mtl_records") or []
    mesh_records = models.get("meshes") or []
    texture_items = textures.get("items") or []

    resolved = [item for item in mtl_records if item.get("map_Kd")]
    unresolved = [item for item in mtl_records if not item.get("map_Kd")]
    texture_sizes = Counter(
        f"{item['header']['width']}x{item['header']['height']}@{item['header']['bit_depth']}"
        for item in texture_items
        if item.get("header")
    )
    pixel_layouts = Counter(
        str((item.get("blocks") or {}).get("pixel_layout") or "unknown")
        for item in texture_items
    )
    uv_formats = Counter(str((item.get("xpvb") or {}).get("uv0_format") or "unknown") for item in mesh_records)
    position_formats = Counter(
        str((item.get("xpvb") or {}).get("position_format") or "unknown")
        for item in mesh_records
    )
    confidence = Counter(str(item.get("texture_mapping_confidence") or "unknown") for item in mtl_records)
    triangle_total = sum(int(((item.get("geometry") or {}).get("nondegenerate_face_count") or 0)) for item in mesh_records)
    mesh_by_material: dict[str, list[dict[str, Any]]] = {}
    for mesh in mesh_records:
        mesh_by_material.setdefault(str(mesh.get("material_name") or ""), []).append(mesh)

    absent_uv_meshes = [mesh for mesh in mesh_records if str((mesh.get("xpvb") or {}).get("uv0_format")) == "absent"]
    absent_uv_collision_meshes = [
        mesh
        for mesh in absent_uv_meshes
        if is_collision_like_mesh(str(mesh.get("mesh_name") or ""), str(mesh.get("material_name") or ""))
    ]
    absent_uv_non_collision_meshes = [
        mesh
        for mesh in absent_uv_meshes
        if not is_collision_like_mesh(str(mesh.get("mesh_name") or ""), str(mesh.get("material_name") or ""))
    ]

    unresolved_used = []
    unresolved_collision = []
    unresolved_aux = []
    unresolved_visual = []
    unresolved_visual_effect = []
    unresolved_visual_plain = []
    unresolved_visual_effect_faces = 0
    unresolved_visual_plain_faces = 0
    for item in unresolved:
        material_name = str(item.get("material_name") or "")
        used_meshes = mesh_by_material.get(material_name, [])
        if used_meshes:
            unresolved_used.append(item)
        if used_meshes and all(
            is_collision_like_mesh(str(mesh.get("mesh_name") or ""), material_name) for mesh in used_meshes
        ):
            unresolved_collision.append(item)
        elif used_meshes and all(
            is_aux_like_name(str(mesh.get("mesh_name") or ""), material_name) for mesh in used_meshes
        ):
            unresolved_aux.append(item)
        elif used_meshes:
            unresolved_visual.append(item)
            if all(is_effect_like_name(str(mesh.get("mesh_name") or ""), material_name) for mesh in used_meshes):
                unresolved_visual_effect.append(item)
                unresolved_visual_effect_faces += sum(
                    int((mesh.get("geometry") or {}).get("nondegenerate_face_count") or 0) for mesh in used_meshes
                )
            else:
                unresolved_visual_plain.append(item)
                unresolved_visual_plain_faces += sum(
                    int((mesh.get("geometry") or {}).get("nondegenerate_face_count") or 0) for mesh in used_meshes
                )

    return {
        "name": output_dir.name,
        "source": manifest["source"],
        "output_dir": str(output_dir),
        "output_dir_relative": os.path.relpath(output_dir, report_root).replace("\\", "/"),
        "mesh_count": int(models.get("mesh_count") or 0),
        "texture_count": int(textures.get("converted") or 0),
        "material_count": int(materials.get("material_count") or 0),
        "resolved_material_count": len(resolved),
        "unresolved_material_count": len(unresolved),
        "unresolved_used_material_count": len(unresolved_used),
        "unresolved_collision_material_count": len(unresolved_collision),
        "unresolved_aux_material_count": len(unresolved_aux),
        "unresolved_visual_material_count": len(unresolved_visual),
        "unresolved_visual_effect_material_count": len(unresolved_visual_effect),
        "unresolved_visual_plain_material_count": len(unresolved_visual_plain),
        "unresolved_visual_effect_face_count": unresolved_visual_effect_faces,
        "unresolved_visual_plain_face_count": unresolved_visual_plain_faces,
        "unresolved_visual_plain_face_ratio": (unresolved_visual_plain_faces / triangle_total) if triangle_total else 0.0,
        "gltf_texture_count": int(gltf.get("texture_count") or 0),
        "weighted_vertex_count": int((models.get("weights") or {}).get("weighted_vertex_count") or 0),
        "skin_count": int(gltf.get("skin_count") or 0),
        "triangle_count": triangle_total,
        "absent_uv_mesh_count": len(absent_uv_meshes),
        "absent_uv_collision_mesh_count": len(absent_uv_collision_meshes),
        "absent_uv_non_collision_mesh_count": len(absent_uv_non_collision_meshes),
        "uv_formats": dict(sorted(uv_formats.items())),
        "position_formats": dict(sorted(position_formats.items())),
        "texture_mapping_confidence": dict(sorted(confidence.items())),
        "texture_sizes": dict(sorted(texture_sizes.items())),
        "pixel_layouts": dict(sorted(pixel_layouts.items())),
        "gltf_path": str(output_dir / "models" / f"{Path(manifest['source']).stem}_{manifest['triangulation']}.gltf"),
        "gltf_relative": os.path.relpath(
            output_dir / "models" / f"{Path(manifest['source']).stem}_{manifest['triangulation']}.gltf",
            report_root,
        ).replace("\\", "/"),
        "mtl_relative": os.path.relpath(
            output_dir / "models" / f"{Path(manifest['source']).stem}.mtl",
            report_root,
        ).replace("\\", "/"),
        "texture_relatives": [
            os.path.relpath(Path(item["png"]), report_root).replace("\\", "/")
            for item in texture_items
            if item.get("png")
        ],
        "unresolved_visual_materials": [str(item.get("material_name") or "") for item in unresolved_visual],
        "notes": [
            "Map exports remain static only; weights and skins should stay at zero.",
            "Resolved material count comes from emitted MTL map_Kd records, not from visual proof.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AGE PSP Map Validation Report",
        "",
        f"Generated on `{report['generated_at']}` from `{report['input_root']}`.",
        f"Texture layout: `{report['texture_layout']}`.",
        "",
        "## Summary",
        "",
        "| Sample | Textures | Materials | Resolved `map_Kd` | Unresolved | Visual Unresolved | Meshes | Triangles | UV Formats | Notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for sample in report["samples"]:
        uv_formats = ", ".join(f"{key}:{value}" for key, value in sample["uv_formats"].items())
        notes = []
        if sample["weighted_vertex_count"]:
            notes.append(f"unexpected weighted vertices={sample['weighted_vertex_count']}")
        if sample["skin_count"]:
            notes.append(f"unexpected skins={sample['skin_count']}")
        if sample["unresolved_visual_plain_material_count"]:
            notes.append(
                f"plain unresolved={sample['unresolved_visual_plain_material_count']} ({sample['unresolved_visual_plain_face_ratio']:.2%} faces)"
            )
        elif sample["unresolved_visual_effect_material_count"]:
            notes.append(f"effect unresolved={sample['unresolved_visual_effect_material_count']}")
        elif sample["unresolved_material_count"]:
            notes.append("only helper/aux unresolved")
        if sample["absent_uv_non_collision_mesh_count"]:
            notes.append(f"non-collision absent_uv={sample['absent_uv_non_collision_mesh_count']}")
        if not notes:
            notes.append("static textured export")
        lines.append(
            "| "
            + " | ".join(
                [
                    sample["name"],
                    str(sample["texture_count"]),
                    str(sample["material_count"]),
                    str(sample["resolved_material_count"]),
                    str(sample["unresolved_material_count"]),
                    str(sample["unresolved_visual_material_count"]),
                    str(sample["mesh_count"]),
                    str(sample["triangle_count"]),
                    uv_formats or "none",
                    "; ".join(notes),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Samples",
            "",
        ]
    )
    for sample in report["samples"]:
        lines.extend(
            [
                f"### `{sample['name']}`",
                "",
                f"- Source: `{sample['source']}`",
                f"- Output: `{sample['output_dir_relative']}`",
                f"- glTF: `{sample['gltf_relative']}`",
                f"- MTL: `{sample['mtl_relative']}`",
                f"- Texture sizes: `{json.dumps(sample['texture_sizes'], ensure_ascii=False)}`",
                f"- Mapping confidence: `{json.dumps(sample['texture_mapping_confidence'], ensure_ascii=False)}`",
                f"- Pixel layouts: `{json.dumps(sample['pixel_layouts'], ensure_ascii=False)}`",
                f"- Absent UV meshes: `{sample['absent_uv_mesh_count']}` total, `{sample['absent_uv_collision_mesh_count']}` collision-like, `{sample['absent_uv_non_collision_mesh_count']}` non-collision-like",
                f"- Unresolved materials: `{sample['unresolved_material_count']}` total, `{sample['unresolved_collision_material_count']}` collision-like, `{sample['unresolved_aux_material_count']}` aux-like, `{sample['unresolved_visual_material_count']}` visual-like",
                f"- Visual unresolved split: `{sample['unresolved_visual_effect_material_count']}` effect-like, `{sample['unresolved_visual_plain_material_count']}` plain-like",
                f"- Plain unresolved face coverage: `{sample['unresolved_visual_plain_face_count']}` / `{sample['triangle_count']}` faces (`{sample['unresolved_visual_plain_face_ratio']:.2%}`)",
                f"- Unresolved visual materials: `{', '.join(sample['unresolved_visual_materials']) if sample['unresolved_visual_materials'] else 'none'}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Notes",
            "",
            "- This report proves batch conversion and emitted texture bindings across more map samples.",
            "- It does not by itself prove final visual correctness; use the generated HTML viewer and screenshots for textured inspection.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    cards = []
    for sample in report["samples"]:
        thumbs = "\n".join(
            f'<img src="{escape(path)}" alt="{escape(sample["name"])} texture" loading="lazy">'
            for path in sample["texture_relatives"][:12]
        )
        cards.append(
            f"""
            <section class="card">
              <div class="card-header">
                <div>
                  <h2>{escape(sample["name"])}</h2>
                  <p>{escape(sample["source"])}</p>
                </div>
                <div class="stats">
                  <span>tex {sample["texture_count"]}</span>
                  <span>mat {sample["material_count"]}</span>
                  <span>resolved {sample["resolved_material_count"]}</span>
                  <span>tri {sample["triangle_count"]}</span>
                </div>
              </div>
              <model-viewer
                src="{escape(sample["gltf_relative"])}"
                camera-controls
                auto-rotate
                shadow-intensity="1"
                exposure="1.1"
                interaction-prompt="none"
                touch-action="pan-y"
              ></model-viewer>
              <div class="meta">
                <a href="{escape(sample["gltf_relative"])}">glTF</a>
                <a href="{escape(sample["mtl_relative"])}">MTL</a>
                <span>uv {escape(json.dumps(sample["uv_formats"], ensure_ascii=False))}</span>
                <span>map {escape(json.dumps(sample["texture_mapping_confidence"], ensure_ascii=False))}</span>
              </div>
              <div class="thumbs">{thumbs}</div>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AGE PSP Map Validation</title>
  <script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fa;
      --panel: #ffffff;
      --border: #d0d7de;
      --text: #24292f;
      --muted: #57606a;
      --accent: #0969da;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .lead {{
      margin: 0 0 24px;
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 20px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .card-header {{
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .card-header h2 {{
      margin: 0 0 4px;
      font-size: 20px;
    }}
    .card-header p {{
      margin: 0;
      color: var(--muted);
      word-break: break-all;
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .stats span,
    .meta span,
    .meta a {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #f6f8fa;
      color: var(--text);
      text-decoration: none;
      white-space: nowrap;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0;
    }}
    model-viewer {{
      width: 100%;
      height: 360px;
      background: linear-gradient(180deg, #eef2f7 0%, #dce6f0 100%);
      border: 1px solid var(--border);
      border-radius: 6px;
    }}
    .thumbs {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .thumbs img {{
      width: 100%;
      aspect-ratio: 1;
      object-fit: contain;
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 4px;
      image-rendering: pixelated;
    }}
  </style>
</head>
<body>
  <main>
    <h1>AGE PSP Map Validation</h1>
    <p class="lead">
      Generated {escape(report["generated_at"])}. This page is for textured review:
      model-viewer cards load exported map glTF, while thumbnails show exported PNG textures.
      Texture layout: {escape(report["texture_layout"])}.
    </p>
    <div class="grid">
      {''.join(cards)}
    </div>
  </main>
</body>
</html>
"""


def build_report(
    inputs: list[Path],
    out_root: Path,
    triangulation: str,
    texture_layout: str,
    overwrite: bool,
) -> dict[str, Any]:
    samples = []
    for archive_path in inputs:
        sample_dir = out_root / "samples" / archive_path.stem
        manifest = export_archive(archive_path, sample_dir, triangulation, texture_layout, overwrite)
        samples.append(summarize_manifest(manifest, out_root))
    return {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_root": str(inputs[0].parent) if inputs else "",
        "triangulation": triangulation,
        "texture_layout": texture_layout,
        "sample_count": len(samples),
        "samples": samples,
        "notes": [
            "This report is intended for map-model conversion checks.",
            "Use the HTML viewer over local HTTP so model-viewer can load glTF and texture assets.",
        ],
    }


def command_validate(args: argparse.Namespace) -> int:
    inputs = [Path(item) for item in args.inputs]
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    report = build_report(inputs, out_root, args.triangulation, args.texture_layout, args.overwrite)

    json_path = out_root / "map_validation_report.json"
    md_path = out_root / "MAP_VALIDATION_REPORT.md"
    html_path = out_root / "map_validation_viewer.html"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")

    print(f"Samples: {report['sample_count']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(f"HTML: {html_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-run AGE PSP map archive exports and build validation reports.")
    parser.add_argument("inputs", nargs="+", help="map .xc archives")
    parser.add_argument("--out-root", required=True, help="root output directory for samples and reports")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--texture-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    parser.add_argument("--overwrite", action="store_true")
    parser.set_defaults(func=command_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




