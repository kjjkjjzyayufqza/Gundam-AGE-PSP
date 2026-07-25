#!/usr/bin/env python3
"""Render textured model previews via Blender headless CLI.

Host process (this file):
  - resolves Blender executable
  - accepts glTF / OBJ exports under outputs/
  - launches: blender --background --python <worker> -- <args>
  - writes PNG previews next to models or to --out

Worker process (runs inside Blender):
  - imports glTF (preferred) or OBJ
  - frames camera on mesh bounds
  - uses emission materials so textures show without scene lights
  - renders front / side / perspective stills (or a contact sheet)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent

DEFAULT_BLENDER_CANDIDATES = [
    Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
    Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
    Path(r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"),
    Path(r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"),
    Path(r"C:\Program Files\Blender Foundation\Blender 3.4\blender.exe"),
]


def find_blender(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"Blender not found: {path}")
        return path

    env = os.environ.get("BLENDER_EXE") or os.environ.get("BLENDER")
    if env:
        path = Path(env)
        if path.is_file():
            return path

    which = shutil.which("blender")
    if which:
        return Path(which)

    for candidate in DEFAULT_BLENDER_CANDIDATES:
        if candidate.is_file():
            return candidate

    foundation = Path(r"C:\Program Files\Blender Foundation")
    if foundation.is_dir():
        matches = sorted(foundation.rglob("blender.exe"), reverse=True)
        if matches:
            return matches[0]

    raise FileNotFoundError(
        "Blender executable not found. Install Blender or pass --blender / set BLENDER_EXE."
    )


def discover_model_inputs(path: Path) -> list[Path]:
    path = path.resolve()
    if path.is_file():
        if path.suffix.lower() in {".gltf", ".glb", ".obj"}:
            return [path]
        raise ValueError(f"unsupported model file: {path}")

    preferred: list[Path] = []
    for pattern in ("**/*.gltf", "**/*.glb", "**/*.obj"):
        preferred.extend(sorted(path.glob(pattern)))
        if preferred:
            break
    # Prefer models/ subdir results when both exist.
    models_dir = [p for p in preferred if "models" in p.parts]
    if models_dir:
        # One primary model per package: pick first gltf, else first obj, under models/
        gltfs = [p for p in models_dir if p.suffix.lower() in {".gltf", ".glb"}]
        if gltfs:
            return [gltfs[0]]
        return [models_dir[0]]
    if not preferred:
        raise FileNotFoundError(f"no glTF/OBJ under {path}")
    return [preferred[0]]


def default_out_path(model_path: Path, out_dir: Path | None) -> Path:
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{model_path.stem}_blender_preview.png"
    return model_path.with_name(f"{model_path.stem}_blender_preview.png")


def blender_worker_source() -> str:
    # Executed only inside Blender; kept as a string so the host tool is self-contained.
    return r'''
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args(argv: list[str]) -> argparse.Namespace:
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="Blender worker for AGE model previews")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--views", default="perspective", help="comma list: front,side,perspective,contact")
    parser.add_argument("--engine", default="auto", choices=["auto", "EEVEE", "CYCLES", "WORKBENCH"])
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)


def import_model(path: Path) -> list:
    suffix = path.suffix.lower()
    if suffix in {".gltf", ".glb"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    else:
        raise RuntimeError(f"unsupported input: {path}")

    # Prefer rest-pose armature evaluation so skinned glTF meshes land in world
    # space. Hide non-mesh helpers from rendering only.
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            obj.hide_render = True
            if hasattr(obj.data, "pose_position"):
                obj.data.pose_position = "REST"
        elif obj.type != "MESH":
            obj.hide_render = True
            obj.hide_viewport = True

    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.data is not None and len(obj.data.vertices) > 0
    ]
    if not meshes:
        raise RuntimeError(f"no mesh objects imported from {path}")

    # Bake skinning into mesh data so framing/render use the same geometry.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.hide_viewport = False
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    try:
        bpy.ops.object.convert(target="MESH")
    except Exception:
        pass

    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.data is not None and len(obj.data.vertices) > 0
    ]
    meshes = sorted(meshes, key=lambda obj: len(obj.data.vertices), reverse=True)
    if len(meshes) > 1:
        top = len(meshes[0].data.vertices)
        meshes = [obj for obj in meshes if len(obj.data.vertices) >= max(8, top // 20)]
    return meshes


def mesh_bounds(mesh_objects) -> tuple[Vector, Vector, Vector, float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    accum = Vector((0.0, 0.0, 0.0))
    count = 0
    for obj in mesh_objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            matrix = evaluated.matrix_world
            for vertex in mesh.vertices:
                world = matrix @ vertex.co
                mins.x = min(mins.x, world.x)
                mins.y = min(mins.y, world.y)
                mins.z = min(mins.z, world.z)
                maxs.x = max(maxs.x, world.x)
                maxs.y = max(maxs.y, world.y)
                maxs.z = max(maxs.z, world.z)
                accum += world
                count += 1
        finally:
            evaluated.to_mesh_clear()
    if count == 0:
        raise RuntimeError("mesh bounds empty")
    # Prefer vertex centroid for look-at; AABB often includes sparse outliers.
    centroid = accum / float(count)
    aabb_center = (mins + maxs) * 0.5
    # Blend toward centroid so empty AABB padding does not push the model off-frame.
    center = centroid * 0.75 + aabb_center * 0.25
    size = maxs - mins
    # Distance uses full AABB so nothing is clipped.
    span = max(size.x, size.y, size.z, 1e-3)
    return mins, maxs, center, span


def force_emission_textures() -> int:
    converted = 0
    for material in bpy.data.materials:
        if material is None:
            continue
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        image_node = next((n for n in nodes if n.bl_idname == "ShaderNodeTexImage" and getattr(n, "image", None)), None)
        if image_node is None:
            continue
        image = image_node.image
        nodes.clear()
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.image = image
        emit = nodes.new(type="ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        out = nodes.new(type="ShaderNodeOutputMaterial")
        links.new(tex.outputs["Color"], emit.inputs["Color"])
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        converted += 1
    return converted


def choose_engine(preferred: str) -> str:
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    if preferred == "CYCLES" and "CYCLES" in engines:
        return "CYCLES"
    if preferred == "WORKBENCH" and "BLENDER_WORKBENCH" in engines:
        return "BLENDER_WORKBENCH"
    if preferred == "EEVEE":
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if name in engines:
                return name
    for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"):
        if name in engines:
            return name
    return bpy.context.scene.render.engine


def setup_camera(center: Vector, span: float, view: str, aspect: float):
    camera_data = bpy.data.cameras.new(f"Camera_{view}")
    camera = bpy.data.objects.new(f"Camera_{view}", camera_data)
    bpy.context.collection.objects.link(camera)
    # Perspective framing is more reliable across Blender versions than ortho_scale.
    camera_data.type = "PERSP"
    camera_data.lens = 50.0
    camera_data.clip_start = 0.001
    camera_data.clip_end = max(span * 200.0, 100.0)

    # Fit full AABB with moderate padding: large enough for head/wings,
    # tight enough that the unit fills most of the frame for ID.
    fov = camera_data.angle
    dist = (span * 0.5) / max(math.tan(fov * 0.5), 1e-4) * 1.65
    dist = max(dist, span * 1.35)

    if view == "front":
        location = center + Vector((0.0, -dist, 0.0))
    elif view == "side":
        location = center + Vector((dist, 0.0, 0.0))
    else:
        location = center + Vector((dist * 0.7, -dist * 0.9, dist * 0.28))

    camera.location = location
    direction = center - camera.location
    if direction.length < 1e-8:
        direction = Vector((0.0, -1.0, 0.0))
    camera.rotation_euler = direction.normalized().to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    return camera


def setup_render(width: int, height: int, samples: int, engine: str, filepath: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = engine
    if engine.startswith("BLENDER_EEVEE"):
        if hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "taa_render_samples"):
                scene.eevee.taa_render_samples = samples
            elif hasattr(scene.eevee, "taa_samples"):
                scene.eevee.taa_samples = samples
    if engine == "CYCLES" and hasattr(scene, "cycles"):
        scene.cycles.samples = samples
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = False
    scene.world.color = (0.78, 0.82, 0.86)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = False
    if hasattr(scene.view_settings, "view_transform"):
        scene.view_settings.view_transform = "Standard"
    scene.render.filepath = str(filepath)
    scene.render.image_settings.file_format = "PNG"


def render_views(args: argparse.Namespace) -> dict:
    input_path = Path(args.input)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    meshes = import_model(input_path)
    mins, maxs, center, span = mesh_bounds(meshes)
    converted = force_emission_textures()
    engine = choose_engine(args.engine)

    views = [v.strip().lower() for v in args.views.split(",") if v.strip()]
    if not views:
        views = ["perspective"]

    rendered: list[str] = []
    if "contact" in views or len([v for v in views if v != "contact"]) > 1:
        # multi stills then composite is heavy; render perspective + front + side to separate files
        base = out_path.with_suffix("")
        mapping = {
            "front": base.with_name(base.name + "_front.png"),
            "side": base.with_name(base.name + "_side.png"),
            "perspective": base.with_name(base.name + "_perspective.png"),
        }
        selected = [v for v in ("front", "side", "perspective") if v in views or "contact" in views]
        aspect = float(args.width) / float(max(args.height, 1))
        for view in selected:
            setup_camera(center, span, view, aspect)
            target = mapping[view] if "contact" in views or len(selected) > 1 else out_path
            setup_render(args.width, args.height, args.samples, engine, target)
            bpy.ops.render.render(write_still=True)
            rendered.append(str(target))
        # If only one non-contact view requested, ensure primary out_path exists.
        if "contact" not in views and len(selected) == 1 and rendered:
            primary = Path(rendered[0])
            if primary.resolve() != out_path.resolve():
                out_path.write_bytes(primary.read_bytes())
                rendered = [str(out_path)]
        elif "contact" in views or len(selected) > 1:
            # Simple horizontal contact sheet via bpy compositing is complex; use first as main
            # and keep all paths. Also write primary perspective (or first) to --out.
            preferred = None
            for key in ("perspective", "front", "side"):
                candidate = mapping.get(key)
                if candidate and candidate.is_file():
                    preferred = candidate
                    break
            if preferred is not None:
                out_path.write_bytes(preferred.read_bytes())
                if str(out_path) not in rendered:
                    rendered.insert(0, str(out_path))
    else:
        view = views[0]
        if view not in {"front", "side", "perspective"}:
            view = "perspective"
        aspect = float(args.width) / float(max(args.height, 1))
        setup_camera(center, span, view, aspect)
        setup_render(args.width, args.height, args.samples, engine, out_path)
        bpy.ops.render.render(write_still=True)
        rendered = [str(out_path)]

    result = {
        "input": str(input_path),
        "output": str(out_path),
        "rendered": rendered,
        "mesh_count": len(meshes),
        "span": span,
        "bounds_min": [mins.x, mins.y, mins.z],
        "bounds_max": [maxs.x, maxs.y, maxs.z],
        "emission_materials": converted,
        "engine": engine,
        "ok": out_path.is_file(),
    }
    print("AGE_BLENDER_PREVIEW_JSON:" + json.dumps(result))
    return result


def main() -> int:
    args = parse_args(sys.argv)
    render_views(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_worker_script(path: Path) -> Path:
    path.write_text(blender_worker_source(), encoding="utf-8")
    return path


def run_blender_preview(
    model_path: Path,
    out_path: Path,
    *,
    blender: Path | None = None,
    width: int = 1400,
    height: int = 900,
    samples: int = 16,
    views: str = "perspective",
    engine: str = "auto",
    timeout_sec: int = 300,
) -> dict[str, Any]:
    blender_exe = blender or find_blender()
    model_path = model_path.resolve()
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="age_blender_preview_") as tmp:
        worker = write_worker_script(Path(tmp) / "age_blender_preview_worker.py")
        cmd = [
            str(blender_exe),
            "--background",
            "--factory-startup",
            "--python",
            str(worker),
            "--",
            "--input",
            str(model_path),
            "--out",
            str(out_path),
            "--width",
            str(width),
            "--height",
            str(height),
            "--samples",
            str(samples),
            "--views",
            views,
            "--engine",
            engine,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )

    result: dict[str, Any] = {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-4000:],
        "output": str(out_path),
        "output_exists": out_path.is_file(),
        "blender": str(blender_exe),
        "input": str(model_path),
    }

    for line in (proc.stdout or "").splitlines():
        if line.startswith("AGE_BLENDER_PREVIEW_JSON:"):
            payload = json.loads(line[len("AGE_BLENDER_PREVIEW_JSON:") :])
            result["worker"] = payload
            break

    if proc.returncode != 0 or not out_path.is_file():
        raise RuntimeError(
            "Blender preview failed "
            f"(code={proc.returncode}, out_exists={out_path.is_file()}): "
            f"{(proc.stderr or proc.stdout or '')[-1000:]}"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="glTF/OBJ file or package directory containing models/")
    parser.add_argument("--out", help="PNG output path (default: next to model)")
    parser.add_argument("--out-dir", help="Directory for PNG when input is a package/dir")
    parser.add_argument("--blender", help="Path to blender.exe")
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument(
        "--views",
        default="front,side,perspective",
        help="Comma list: front,side,perspective,contact",
    )
    parser.add_argument("--engine", default="auto", choices=["auto", "EEVEE", "CYCLES", "WORKBENCH"])
    parser.add_argument("--json", help="Optional result JSON path")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    models = discover_model_inputs(Path(args.input))
    results = []
    for model in models:
        if args.out and len(models) == 1:
            out_path = Path(args.out)
        else:
            out_path = default_out_path(model, Path(args.out_dir) if args.out_dir else None)
        info = run_blender_preview(
            model,
            out_path,
            blender=Path(args.blender) if args.blender else None,
            width=args.width,
            height=args.height,
            samples=args.samples,
            views=args.views,
            engine=args.engine,
            timeout_sec=args.timeout,
        )
        results.append(info)
        print(f"preview: {info['output']}")

    payload = {"count": len(results), "results": results}
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"json: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
