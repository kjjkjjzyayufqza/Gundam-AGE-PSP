#!/usr/bin/env python3
"""One-command Gundam AGE PSP static asset extraction pipeline.

The lower-level tools remain the source of truth. This wrapper coordinates the
common workflow for one XPCK archive or one already extracted directory:

1. Extract XPCK contents, if an archive path is given.
2. Export IMGP `.xi` textures to PNG.
3. Export XMPR `.prm` meshes to OBJ plus a JSON manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from age_imgp_tool import decode_imgp  # noqa: E402
from age_gltf_tool import write_gltf  # noqa: E402
from age_material_bind import build_manifest as build_material_manifest  # noqa: E402
from age_pose_export import (  # noqa: E402
    animation_node_names,
    export_posed_obj,
    select_representative_frame,
)
from age_xmpr_tool import (  # noqa: E402
    decode_mesh,
    obj_identifier,
    weight_manifest_summary,
    write_obj,
    write_weight_manifest,
)
from age_xpck_tool import XpckError, extract_archive  # noqa: E402


MODEL_ARCHIVE_RE = re.compile(r"^(?P<prefix>.+)_p\d+$", re.IGNORECASE)
TOOLS_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = TOOLS_DIR.parent
MESH_TEXTURE_MAPPINGS = TOOLS_DIR / "data" / "mesh_texture_mappings.json"
ANIMATION_PROBE_PROJECT = TOOLS_DIR / "StudioElevenAnimationProbe" / "StudioElevenAnimationProbe.csproj"
ANIMATION_PROBE_DLL = (
    TOOLS_DIR / "StudioElevenAnimationProbe" / "bin" / "Release" / "net9.0" / "StudioElevenAnimationProbe.dll"
)


def model_archive_prefix(path: Path) -> str:
    match = MODEL_ARCHIVE_RE.fullmatch(path.stem)
    if not match:
        raise XpckError(f"character model archive name must end with _p<digits>: {path.name}")
    return match.group("prefix")


def discover_animation_archives(model_archive: Path) -> list[Path]:
    prefix = model_archive_prefix(model_archive)
    pattern = re.compile(rf"^{re.escape(prefix)}_(?:s|v)\d+$", re.IGNORECASE)
    return sorted(
        path
        for path in model_archive.parent.glob(f"{prefix}_*.xc")
        if path.is_file() and pattern.fullmatch(path.stem)
    )


def discover_embedded_animations(extracted_dir: Path) -> list[Path]:
    return sorted(path for path in extracted_dir.rglob("*.mtn2") if path.is_file())


def model_node_hashes(model_manifest: dict) -> set[str]:
    models = model_manifest.get("models") or model_manifest
    return {
        str(node_hash).upper()
        for mesh in models.get("meshes", [])
        for node_hash in mesh.get("node_hashes", [])
        if node_hash
    }


def animation_node_hashes(animation_data: dict) -> set[str]:
    return animation_node_names(animation_data)


def compatibility_record(model_nodes: set[str], animation_nodes: set[str]) -> dict:
    normalized_model = {name.upper() for name in model_nodes}
    normalized_animation = {name.upper() for name in animation_nodes}
    overlap = normalized_model & normalized_animation
    return {
        "model_node_count": len(normalized_model),
        "animation_node_count": len(normalized_animation),
        "overlap_count": len(overlap),
        "model_coverage": len(overlap) / len(normalized_model) if normalized_model else 0.0,
        "animation_coverage": len(overlap) / len(normalized_animation) if normalized_animation else 0.0,
        "overlap_hashes": sorted(overlap),
    }


def ensure_animation_probe(rebuild: bool = False) -> dict:
    should_build = rebuild or not ANIMATION_PROBE_DLL.exists()
    record = {
        "project": str(ANIMATION_PROBE_PROJECT),
        "dll": str(ANIMATION_PROBE_DLL),
        "build_requested": should_build,
        "command": None,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
    }
    if not should_build:
        return record
    if not ANIMATION_PROBE_PROJECT.exists():
        raise XpckError(f"StudioElevenAnimationProbe project not found: {ANIMATION_PROBE_PROJECT}")

    command = ["dotnet", "build", str(ANIMATION_PROBE_PROJECT), "-c", "Release", "--nologo"]
    record["command"] = command
    try:
        completed = subprocess.run(
            command,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise XpckError(f"failed to launch dotnet for animation probe build: {exc}") from exc
    record.update(
        {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    )
    if completed.returncode != 0 or not ANIMATION_PROBE_DLL.exists():
        raise XpckError(
            "StudioElevenAnimationProbe build failed; inspect animation_probe_build in the pipeline manifest"
        )
    return record


def run_animation_probe(input_path: Path, output_path: Path) -> tuple[dict, dict]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["dotnet", str(ANIMATION_PROBE_DLL), str(input_path), str(output_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise XpckError(f"failed to launch StudioElevenAnimationProbe: {exc}") from exc
    record = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "input": str(input_path),
        "output": str(output_path),
    }
    if completed.returncode != 0 or not output_path.exists():
        raise XpckError(
            f"StudioElevenAnimationProbe failed for {input_path}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return json.loads(output_path.read_text(encoding="utf-8")), record


def parse_pose_frame(value: str, animation_data: dict, relevant_nodes: set[str]) -> tuple[float, str]:
    if value.lower() == "auto":
        return float(select_representative_frame(animation_data, relevant_nodes)), "auto_representative"
    try:
        return float(value), "explicit"
    except ValueError as exc:
        raise XpckError(f"--pose-frame must be 'auto' or a number, got {value!r}") from exc


def animation_rank(record: dict) -> tuple[float, int, str, str]:
    compatibility = record["compatibility"]
    return (
        -compatibility["model_coverage"],
        -compatibility["overlap_count"],
        record["archive"].lower(),
        record["mtn2"].lower(),
    )


def export_character_animations(
    args: argparse.Namespace,
    model_archive: Path,
    extracted_dir: Path,
    out_dir: Path,
    pipeline_manifest: dict,
) -> dict:
    if args.animation_policy == "none":
        return {
            "policy": "none",
            "discovered_archives": [],
            "candidates": [],
            "selected": [],
            "failures": [],
            "notes": ["Animation processing disabled by --animation-policy none."],
        }

    embedded_animations = discover_embedded_animations(extracted_dir)
    explicit_archives = [Path(path) for path in (args.animation_archive or [])]
    animation_archives = sorted(dict.fromkeys(explicit_archives or discover_animation_archives(model_archive)))
    model_nodes = model_node_hashes(pipeline_manifest)
    result = {
        "policy": args.animation_policy,
        "pose_frame_request": args.pose_frame,
        "rotation_mode": args.rotation_mode,
        "model_node_count": len(model_nodes),
        "model_node_hashes": sorted(model_nodes),
        "embedded_animations": [str(path) for path in embedded_animations],
        "discovered_archives": [str(path) for path in animation_archives],
        "animation_probe_build": None,
        "candidates": [],
        "selected": [],
        "failures": [],
        "notes": [
            "Animation discovery includes .mtn2 files embedded in the model XPCK and same-prefix sibling archives.",
            "Filename discovery requires the same prefix as the _pNNN model archive.",
            "Pose compatibility is accepted only when XMTN and XMPR node hashes overlap.",
            "Automatic frame selection maximizes visible relevant BoneScale tracks, then prefers scale near 1.0.",
        ],
    }
    if not embedded_animations and not animation_archives:
        result["notes"].append("No embedded .mtn2 or sibling _sNNN.xc/_vNNN.xc animation archives were found.")
        return result

    try:
        result["animation_probe_build"] = ensure_animation_probe(args.rebuild_animation_probe)
    except Exception as exc:
        result["failures"].append({"stage": "animation_probe_build", "error": str(exc)})
        return result

    animation_root = out_dir / "animations"
    for mtn_path in embedded_animations:
        relative_mtn = mtn_path.relative_to(extracted_dir)
        animation_json = (animation_root / model_archive.stem / "parsed" / relative_mtn).with_suffix(
            ".animation.json"
        )
        try:
            animation_data, probe_record = run_animation_probe(mtn_path, animation_json)
            animation_nodes = animation_node_hashes(animation_data)
            compatibility = compatibility_record(model_nodes, animation_nodes)
            frame, frame_selection = parse_pose_frame(args.pose_frame, animation_data, model_nodes)
            result["candidates"].append(
                {
                    "source_kind": "embedded_model_archive",
                    "archive": str(model_archive),
                    "archive_file_count": pipeline_manifest["xpck"]["file_count"],
                    "extracted_dir": str(extracted_dir),
                    "mtn2": str(mtn_path),
                    "animation_json": str(animation_json),
                    "animation_name": animation_data.get("AnimationName"),
                    "frame_count": animation_data.get("FrameCount"),
                    "frame": frame,
                    "frame_selection": frame_selection,
                    "probe": probe_record,
                    "compatibility": compatibility,
                }
            )
        except Exception as exc:
            result["failures"].append(
                {
                    "stage": "animation_parse",
                    "source_kind": "embedded_model_archive",
                    "archive": str(model_archive),
                    "mtn2": str(mtn_path),
                    "error": str(exc),
                }
            )

    for archive_path in animation_archives:
        archive_out = animation_root / archive_path.stem
        animation_extracted = archive_out / "extracted"
        try:
            extract_manifest = extract_archive(archive_path, animation_extracted, args.overwrite)
        except Exception as exc:
            result["failures"].append(
                {"stage": "animation_archive_extract", "archive": str(archive_path), "error": str(exc)}
            )
            continue

        mtn_paths = sorted(animation_extracted.rglob("*.mtn2"))
        if not mtn_paths:
            result["failures"].append(
                {
                    "stage": "animation_discovery",
                    "archive": str(archive_path),
                    "error": "archive contains no .mtn2 files",
                }
            )
            continue

        for mtn_path in mtn_paths:
            relative_mtn = mtn_path.relative_to(animation_extracted)
            animation_json = (archive_out / "parsed" / relative_mtn).with_suffix(".animation.json")
            try:
                animation_data, probe_record = run_animation_probe(mtn_path, animation_json)
                animation_nodes = animation_node_hashes(animation_data)
                compatibility = compatibility_record(model_nodes, animation_nodes)
                frame, frame_selection = parse_pose_frame(args.pose_frame, animation_data, model_nodes)
                result["candidates"].append(
                    {
                        "source_kind": "sibling_animation_archive",
                        "archive": str(archive_path),
                        "archive_file_count": extract_manifest["archive"]["header"]["file_count"],
                        "extracted_dir": str(animation_extracted),
                        "mtn2": str(mtn_path),
                        "animation_json": str(animation_json),
                        "animation_name": animation_data.get("AnimationName"),
                        "frame_count": animation_data.get("FrameCount"),
                        "frame": frame,
                        "frame_selection": frame_selection,
                        "probe": probe_record,
                        "compatibility": compatibility,
                    }
                )
            except Exception as exc:
                result["failures"].append(
                    {
                        "stage": "animation_parse",
                        "source_kind": "sibling_animation_archive",
                        "archive": str(archive_path),
                        "mtn2": str(mtn_path),
                        "error": str(exc),
                    }
                )

    compatible = sorted(
        (record for record in result["candidates"] if record["compatibility"]["overlap_count"] > 0),
        key=animation_rank,
    )
    selected_candidates = compatible[:1] if args.animation_policy == "best" else compatible
    mtl_path = (pipeline_manifest.get("materials") or {}).get("mtl")
    mtllib = Path(mtl_path).name if mtl_path else None
    model_dir = out_dir / "models"
    name = args.name or extracted_dir.name
    for candidate in selected_candidates:
        frame = candidate["frame"]
        frame_tag = f"{frame:g}".replace("-", "m").replace(".", "p")
        animation_stem = Path(candidate["archive"]).stem
        mtn_stem = Path(candidate["mtn2"]).stem
        pose_stem = f"{name}_{animation_stem}_{mtn_stem}_f{frame_tag}_pose"
        obj_path = model_dir / f"{pose_stem}.obj"
        pose_manifest_path = obj_path.with_suffix(".obj.json")
        try:
            pose_manifest = export_posed_obj(
                root=extracted_dir,
                animation_json=Path(candidate["animation_json"]),
                frame=frame,
                out_path=obj_path,
                manifest_path=pose_manifest_path,
                triangulation=args.triangulation,
                keep_degenerate_faces=args.keep_degenerate_faces,
                mtllib=mtllib,
                rotation_mode=args.rotation_mode,
            )
            selected = dict(candidate)
            selected["pose"] = {
                "obj": str(obj_path),
                "manifest": str(pose_manifest_path),
                "mesh_count": pose_manifest["mesh_count"],
                "transformed_vertices": pose_manifest["transformed_vertices"],
                "rotation_mode": pose_manifest["rotation_mode"],
            }
            result["selected"].append(selected)
        except Exception as exc:
            result["failures"].append(
                {
                    "stage": "pose_export",
                    "archive": candidate["archive"],
                    "mtn2": candidate["mtn2"],
                    "error": str(exc),
                }
            )
    return result


def export_textures(extracted_dir: Path, texture_dir: Path, pattern: str, pixel_layout: str) -> dict:
    items = []
    failures = []
    for xi_path in sorted(extracted_dir.rglob(pattern)):
        try:
            rel = xi_path.relative_to(extracted_dir)
            png_path = (texture_dir / rel).with_suffix(".png")
            json_path = png_path.with_suffix(".png.json")
            header, blocks, image = decode_imgp(xi_path, "rgba", pixel_layout)
            png_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(png_path)
            item = {
                "source": str(xi_path),
                "png": str(png_path),
                "header": asdict(header),
                "blocks": asdict(blocks),
            }
            json_path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
            items.append(item)
        except Exception as exc:  # keep broad archive batches moving
            failures.append({"source": str(xi_path), "error": str(exc)})

    return {
        "converted": len(items),
        "failed": len(failures),
        "items": items,
        "failures": failures,
    }


def export_models(
    extracted_dir: Path,
    model_dir: Path,
    name: str,
    triangulation: str,
    skip_degenerate_faces: bool,
    mtllib: str | None,
    material_records: list[dict] | None = None,
    material_name_overrides: dict[str, str] | None = None,
    mbn_roots: list[Path] | None = None,
) -> dict:
    meshes = []
    failures = []
    for prm_path in sorted(extracted_dir.rglob("*.prm")):
        try:
            meshes.append(decode_mesh(prm_path, triangulation, skip_degenerate_faces))
        except Exception as exc:
            failures.append({"source": str(prm_path), "error": str(exc)})

    model_dir.mkdir(parents=True, exist_ok=True)
    obj_path = model_dir / f"{name}_{triangulation}.obj"
    obj_manifest_path = obj_path.with_suffix(".obj.json")
    weights_manifest_path = obj_path.with_suffix(".weights.json")
    gltf_path = model_dir / f"{name}_{triangulation}.gltf"
    weights_summary = None
    gltf_summary = None
    if meshes:
        write_obj(obj_path, meshes, mtllib, material_name_overrides)
        weights_manifest = write_weight_manifest(weights_manifest_path, meshes, obj_path)
        weights_summary = weight_manifest_summary(weights_manifest, weights_manifest_path)
        gltf_summary = write_gltf(
            gltf_path,
            meshes,
            material_records,
            material_name_overrides,
            mbn_roots=mbn_roots or [extracted_dir],
        )

    manifest = {
        "obj": str(obj_path) if meshes else None,
        "mtllib": mtllib,
        "weights": weights_summary,
        "gltf": gltf_summary,
        "mesh_count": len(meshes),
        "failed": len(failures),
        "meshes": [asdict(mesh[0]) for mesh in meshes],
        "failures": failures,
    }
    obj_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def skeleton_archives_from_survey(path: Path) -> list[Path]:
    survey = json.loads(path.read_text(encoding="utf-8"))
    return [
        Path(item["archive"])
        for item in survey.get("greedy_archive_cover", [])
        if item.get("archive")
    ]


def normalized_path_key(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(Path(path)).replace("\\", "/").lower()


def archive_override_keys(args: argparse.Namespace, extracted_dir: Path) -> list[str]:
    keys = []
    for value in (getattr(args, "name", None), getattr(args, "input", None), extracted_dir.name):
        if not value:
            continue
        stem = Path(str(value)).stem
        if stem and stem not in keys:
            keys.append(stem)
    return keys


def mapping_entries(data: dict) -> dict:
    return data.get("archives") or data


def load_mesh_texture_mapping(args: argparse.Namespace, extracted_dir: Path) -> dict:
    if not MESH_TEXTURE_MAPPINGS.exists():
        return {}
    data = json.loads(MESH_TEXTURE_MAPPINGS.read_text(encoding="utf-8"))
    archives = mapping_entries(data)
    for key in archive_override_keys(args, extracted_dir):
        if key in archives:
            mapping = dict(archives[key])
            mapping["archive_key"] = key
            mapping["mapping_file"] = str(MESH_TEXTURE_MAPPINGS)
            if data.get("schema"):
                mapping["schema"] = data["schema"]
            if data.get("notes"):
                mapping["mapping_notes"] = data["notes"]
            return mapping
    return {}


def export_materials(extracted_dir: Path, material_dir: Path) -> dict:
    material_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_material_manifest(extracted_dir)
    manifest_path = material_dir / "_material_binding_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "manifest": str(manifest_path),
        "material_count": len(manifest["materials"]),
        "mesh_count": len(manifest["meshes"]),
        "materials": manifest["materials"],
        "image_order_candidates": manifest["image_order_candidates"],
        "notes": manifest["notes"],
    }


def source_matches(mapping_source: str | None, mesh_source: str | None) -> bool:
    mapping_key = normalized_path_key(mapping_source)
    if not mapping_key:
        return True
    mesh_key = normalized_path_key(mesh_source)
    if not mesh_key:
        return False
    return mesh_key == mapping_key or mesh_key.endswith("/" + mapping_key) or Path(mesh_key).name == Path(mapping_key).name


def matching_mesh_texture_entries(material_manifest: dict, mesh_texture_mapping: dict) -> list[tuple[dict, dict]]:
    requested = mesh_texture_mapping.get("mesh_textures") or []
    if not requested:
        return []

    matches = []
    for entry in requested:
        entry_mesh = entry.get("mesh_name")
        entry_material = entry.get("material_name")
        entry_source = entry.get("source")
        for mesh in material_manifest.get("meshes", []):
            if entry_source and not source_matches(entry_source, mesh.get("source")):
                continue
            if entry_mesh and str(mesh.get("mesh_name") or "") != str(entry_mesh):
                continue
            if entry_material and str(mesh.get("material_name") or "") != str(entry_material):
                continue
            matches.append((mesh, entry))
    return matches


def write_mtl(
    model_dir: Path,
    name: str,
    material_manifest: dict,
    texture_manifest: dict | None,
    mesh_texture_mapping: dict | None = None,
) -> tuple[Path, list[dict], dict[str, str]]:
    model_dir.mkdir(parents=True, exist_ok=True)
    mtl_path = model_dir / f"{name}.mtl"
    extracted_dir = Path(material_manifest.get("root") or ".")
    texture_by_source = {}
    if texture_manifest:
        for item in texture_manifest.get("items", []):
            texture_by_source[normalized_path_key(item.get("source"))] = item.get("png")

    xi_by_texture_name = {
        item["texture_name"]: item.get("xi_path_by_resource_order")
        for item in material_manifest.get("image_order_candidates", [])
    }

    lines = [
        "# Experimental MTL generated from Gundam AGE PSP material binding evidence",
        "# TXP owner bindings use CRC32-confirmed CHRP00 strings.",
        "# Texture image mapping prefers direct TXP/XI numbered-stem matches, then falls back to resource order.",
        "# Mesh texture mappings are explicit model-to-texture assignments recorded for textured review.",
    ]
    records = []
    matched_overrides = matching_mesh_texture_entries(material_manifest, mesh_texture_mapping or {})
    overridden_sources = {
        key
        for mesh, _override in matched_overrides
        for key in [normalized_path_key(mesh.get("source"))]
        if key
    }
    meshes_by_material: dict[str, list[dict]] = {}
    for mesh in material_manifest.get("meshes", []):
        meshes_by_material.setdefault(str(mesh.get("material_name") or ""), []).append(mesh)

    def append_record(
        raw_material_name: str,
        obj_material_name: str,
        texture_name: str | None,
        xi_path: str | None,
        texture_mapping_confidence: str,
        extra: dict | None = None,
    ) -> None:
        png_path = texture_by_source.get(normalized_path_key(xi_path))
        rel_png = None
        confidence = texture_mapping_confidence
        if png_path:
            rel_png = os.path.relpath(Path(png_path), model_dir).replace("\\", "/")
        else:
            confidence = "unresolved"

        lines.append("")
        lines.append(f"newmtl {obj_material_name}")
        lines.append("Kd 1.000000 1.000000 1.000000")
        lines.append("Ka 0.000000 0.000000 0.000000")
        lines.append("Ks 0.000000 0.000000 0.000000")
        lines.append("d 1.000000")
        if rel_png:
            lines.append(f"map_Kd {rel_png}")
        else:
            lines.append("# map_Kd unresolved")

        record = {
            "material_name": raw_material_name,
            "obj_material_name": obj_material_name,
            "texture_name_candidate": texture_name,
            "xi_path": xi_path,
            "png_path": png_path,
            "map_Kd": rel_png,
            "texture_mapping_confidence": confidence,
        }
        if extra:
            record.update(extra)
        records.append(record)

    for material in material_manifest.get("materials", []):
        raw_material_name = str(material.get("material_name") or "")
        material_meshes = meshes_by_material.get(raw_material_name, [])
        if material_meshes and all(normalized_path_key(mesh.get("source")) in overridden_sources for mesh in material_meshes):
            continue
        material_name = obj_identifier(material.get("material_name", ""), "default_material")
        texture_name = (material.get("texture_name_candidates") or [None])[0]
        xi_path = material.get("xi_path_by_txp_stem")
        texture_mapping_confidence = material.get("texture_image_binding_confidence") or "unresolved"
        if not xi_path and texture_name:
            xi_path = xi_by_texture_name.get(texture_name)
            texture_mapping_confidence = "resource_order_heuristic" if xi_path else "unresolved"
        append_record(
            raw_material_name=material.get("material_name"),
            obj_material_name=material_name,
            texture_name=texture_name,
            xi_path=xi_path,
            texture_mapping_confidence=texture_mapping_confidence,
        )

    material_name_overrides: dict[str, str] = {}
    for mesh, override in matched_overrides:
        raw_material_name = str(mesh.get("material_name") or "")
        mesh_name = str(mesh.get("mesh_name") or "")
        obj_material_name = obj_identifier(
            str(override.get("obj_material_name") or f"{raw_material_name}__{mesh_name}"),
            "default_material",
        )
        texture_value = override.get("texture")
        xi_path = str(extracted_dir / texture_value) if texture_value else None
        append_record(
            raw_material_name=raw_material_name,
            obj_material_name=obj_material_name,
            texture_name=override.get("texture_name") or texture_value,
            xi_path=xi_path,
            texture_mapping_confidence=str(override.get("confidence") or "mesh_texture_mapping"),
            extra={
                "mesh_name": mesh_name,
                "source": mesh.get("source"),
                "mesh_texture_mapping": True,
                "mapping_reason": override.get("reason"),
                "mapping_file": (mesh_texture_mapping or {}).get("mapping_file"),
            },
        )
        source_key = normalized_path_key(mesh.get("source"))
        if source_key:
            material_name_overrides[source_key] = obj_material_name
        material_name_overrides[f"mesh:{mesh_name}|material:{raw_material_name}"] = obj_material_name

    mtl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mtl_path, records, material_name_overrides


def run_pipeline(args: argparse.Namespace, extracted_dir: Path, source_kind: str) -> dict:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    textures = None
    if not args.skip_textures:
        textures = export_textures(extracted_dir, out_dir / "textures", args.texture_pattern, args.texture_layout)

    materials = None
    material_manifest = None
    mesh_texture_mapping = load_mesh_texture_mapping(args, extracted_dir)
    if not args.skip_materials:
        material_manifest = build_material_manifest(extracted_dir)
        material_dir = out_dir / "materials"
        material_dir.mkdir(parents=True, exist_ok=True)
        material_manifest_path = material_dir / "_material_binding_manifest.json"
        material_manifest_path.write_text(json.dumps(material_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        materials = {
            "manifest": str(material_manifest_path),
            "material_count": len(material_manifest["materials"]),
            "mesh_count": len(material_manifest["meshes"]),
            "materials": material_manifest["materials"],
            "image_order_candidates": material_manifest["image_order_candidates"],
            "notes": material_manifest["notes"],
        }
        if mesh_texture_mapping:
            materials["mesh_texture_mapping"] = mesh_texture_mapping

    name = args.name or extracted_dir.name
    model_dir = out_dir / "models"
    mbn_roots = [extracted_dir]
    skeleton_archives = []
    for extra_root in getattr(args, "mbn_root", []) or []:
        mbn_roots.append(Path(extra_root))
    for archive in getattr(args, "skeleton_archive", []) or []:
        archive_path = Path(archive)
        skeleton_dir = out_dir / "skeletons" / archive_path.stem
        extract_archive(archive_path, skeleton_dir, args.overwrite)
        mbn_roots.append(skeleton_dir)
        skeleton_archives.append({"archive": str(archive_path), "extracted_dir": str(skeleton_dir)})
    for survey_path in getattr(args, "skeleton_survey", []) or []:
        for archive_path in skeleton_archives_from_survey(Path(survey_path)):
            skeleton_dir = out_dir / "skeletons" / archive_path.stem
            extract_archive(archive_path, skeleton_dir, args.overwrite)
            mbn_roots.append(skeleton_dir)
            skeleton_archives.append(
                {"archive": str(archive_path), "extracted_dir": str(skeleton_dir), "source_survey": str(survey_path)}
            )
    mtl_path = None
    mtl_records = []
    material_name_overrides = {}
    if material_manifest and textures and not args.skip_models:
        mtl_path, mtl_records, material_name_overrides = write_mtl(
            model_dir,
            name,
            material_manifest,
            textures,
            mesh_texture_mapping,
        )
        materials["mtl"] = str(mtl_path)  # type: ignore[index]
        materials["mtl_records"] = mtl_records  # type: ignore[index]
        materials["material_name_overrides"] = material_name_overrides  # type: ignore[index]

    models = None
    if not args.skip_models:
        models = export_models(
            extracted_dir,
            model_dir,
            name,
            args.triangulation,
            not args.keep_degenerate_faces,
            str(mtl_path.name) if mtl_path else None,
            mtl_records,
            material_name_overrides,
            mbn_roots,
        )

    manifest = {
        "source": str(args.input),
        "source_kind": source_kind,
        "extracted_dir": str(extracted_dir),
        "output_dir": str(out_dir),
        "triangulation": args.triangulation,
        "keep_degenerate_faces": args.keep_degenerate_faces,
        "texture_layout": args.texture_layout,
        "textures": textures,
        "models": models,
        "materials": materials,
        "skeleton_archives": skeleton_archives,
        "mbn_roots": [str(path) for path in mbn_roots],
        "notes": [
            "Textures are PNG exports from IMGP; the default texture layout applies PSP 16-byte x 8-row deswizzle.",
            "OBJ vertex records are decoded from XPVB; inspect models.meshes[].geometry.position_semantic before treating them as confirmed position geometry.",
            "Faces remain experimental when inferred from PSP XPVI primitive type 2.",
            "Material bindings include CRC32-confirmed TXP owner strings and direct TXP/XI numbered-stem texture matches where present.",
        ],
    }
    manifest_path = Path(args.json) if args.json else out_dir / "_asset_pipeline_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def command_from_xpck(args: argparse.Namespace) -> int:
    archive_path = Path(args.input)
    out_dir = Path(args.out_dir)
    extracted_dir = Path(args.extract_dir) if args.extract_dir else out_dir / "extracted"
    extract_manifest = extract_archive(archive_path, extracted_dir, args.overwrite)
    manifest = run_pipeline(args, extracted_dir, "xpck_archive")
    manifest["xpck"] = {
        "file_count": extract_manifest["archive"]["header"]["file_count"],
        "written_files": len(extract_manifest["written_files"]),
        "manifest": str(extracted_dir / "_xpck_manifest.json"),
    }
    manifest_path = Path(args.json) if args.json else out_dir / "_asset_pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Extracted files: {len(extract_manifest['written_files'])}")
    print(f"Textures: {manifest['textures']['converted'] if manifest['textures'] else 'skipped'}")
    print(f"Meshes: {manifest['models']['mesh_count'] if manifest['models'] else 'skipped'}")
    print(f"Materials: {manifest['materials']['material_count'] if manifest['materials'] else 'skipped'}")
    print(f"Manifest: {manifest_path}")
    return 0


def command_from_character(args: argparse.Namespace) -> int:
    archive_path = Path(args.input)
    out_dir = Path(args.out_dir)
    extracted_dir = Path(args.extract_dir) if args.extract_dir else out_dir / "extracted"
    extract_manifest = extract_archive(archive_path, extracted_dir, args.overwrite)
    manifest = run_pipeline(args, extracted_dir, "character_xpck_archive")
    manifest["xpck"] = {
        "file_count": extract_manifest["archive"]["header"]["file_count"],
        "written_files": len(extract_manifest["written_files"]),
        "manifest": str(extracted_dir / "_xpck_manifest.json"),
    }
    manifest["animations"] = export_character_animations(
        args,
        archive_path,
        extracted_dir,
        out_dir,
        manifest,
    )
    manifest_path = Path(args.json) if args.json else out_dir / "_asset_pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Extracted files: {len(extract_manifest['written_files'])}")
    print(f"Textures: {manifest['textures']['converted'] if manifest['textures'] else 'skipped'}")
    print(f"Meshes: {manifest['models']['mesh_count'] if manifest['models'] else 'skipped'}")
    print(f"Materials: {manifest['materials']['material_count'] if manifest['materials'] else 'skipped'}")
    print(f"Animation candidates: {len(manifest['animations']['candidates'])}")
    print(f"Posed models: {len(manifest['animations']['selected'])}")
    print(f"Animation failures: {len(manifest['animations']['failures'])}")
    print(f"Manifest: {manifest_path}")
    return 1 if args.fail_on_animation_error and manifest["animations"]["failures"] else 0


def command_from_dir(args: argparse.Namespace) -> int:
    extracted_dir = Path(args.input)
    manifest = run_pipeline(args, extracted_dir, "extracted_directory")
    print(f"Textures: {manifest['textures']['converted'] if manifest['textures'] else 'skipped'}")
    print(f"Meshes: {manifest['models']['mesh_count'] if manifest['models'] else 'skipped'}")
    print(f"Materials: {manifest['materials']['material_count'] if manifest['materials'] else 'skipped'}")
    print(f"Manifest: {Path(args.json) if args.json else Path(args.out_dir) / '_asset_pipeline_manifest.json'}")
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", help="XPCK archive or extracted directory")
    parser.add_argument("--out-dir", required=True, help="pipeline output directory")
    parser.add_argument("--json", help="pipeline manifest path")
    parser.add_argument("--name", help="base name for OBJ output")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--keep-degenerate-faces", action="store_true")
    parser.add_argument("--texture-pattern", default="*.xi", help="texture glob under extracted directory")
    parser.add_argument(
        "--texture-layout",
        choices=["psp-swizzled", "tiled", "linear"],
        default="psp-swizzled",
        help="IMGP indexed pixel layout; tiled reproduces the earlier no-deswizzle output",
    )
    parser.add_argument("--skip-textures", action="store_true")
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-materials", action="store_true")
    parser.add_argument("--mbn-root", action="append", default=[], help="additional directory containing .mbn bind files")
    parser.add_argument("--skeleton-archive", action="append", default=[], help="additional XPCK archive to extract for .mbn bind files")
    parser.add_argument("--skeleton-survey", action="append", default=[], help="MBN survey JSON with greedy_archive_cover")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Gundam AGE PSP archive/texture/model extraction in one command.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    from_xpck = subparsers.add_parser("from-xpck", help="extract an XPCK archive, then export textures and models")
    add_common_args(from_xpck)
    from_xpck.add_argument("--extract-dir", help="override extracted file directory")
    from_xpck.add_argument("--overwrite", action="store_true", help="overwrite extracted files")
    from_xpck.set_defaults(func=command_from_xpck)

    from_character = subparsers.add_parser(
        "from-character",
        help="extract a character model XPCK; optionally apply compatible XMTN animation",
    )
    add_common_args(from_character)
    from_character.add_argument("--extract-dir", help="override extracted model file directory")
    from_character.add_argument("--overwrite", action="store_true", help="overwrite extracted files")
    from_character.add_argument(
        "--animation-policy",
        choices=["best", "all", "none"],
        default="none",
        help="default to static assets only; explicitly request best/all to export experimental poses",
    )
    from_character.add_argument(
        "--animation-archive",
        action="append",
        help="explicit animation XPCK; repeat to override sibling auto-discovery",
    )
    from_character.add_argument(
        "--pose-frame",
        default="auto",
        help="animation frame number or 'auto' for a representative visible frame",
    )
    from_character.add_argument(
        "--rotation-mode",
        choices=["studioeleven", "inverse"],
        default="studioeleven",
        help="StudioEleven quaternion convention or inverse Metanoia diagnostic",
    )
    from_character.add_argument("--rebuild-animation-probe", action="store_true")
    from_character.add_argument("--fail-on-animation-error", action="store_true")
    from_character.set_defaults(func=command_from_character)

    from_dir = subparsers.add_parser("from-dir", help="export textures and models from an already extracted directory")
    add_common_args(from_dir)
    from_dir.set_defaults(func=command_from_dir)

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





