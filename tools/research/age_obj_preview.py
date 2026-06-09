#!/usr/bin/env python3
"""Render simple orthographic OBJ previews for topology validation.

This intentionally uses Matplotlib as an independent common-format consumer.
It validates and displays exported OBJ positions/faces; it does not decode any
Gundam AGE game format and does not attempt UV-textured rendering.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402


def load_obj_geometry(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "v" and len(parts) >= 4:
            vertex = tuple(float(value) for value in parts[1:4])
            if not all(math.isfinite(value) for value in vertex):
                raise ValueError(f"{path}:{line_number}: non-finite vertex")
            vertices.append(vertex)  # type: ignore[arg-type]
        elif parts[0] == "f" and len(parts) >= 4:
            indices = []
            for token in parts[1:]:
                raw_index = int(token.split("/", 1)[0])
                index = raw_index - 1 if raw_index > 0 else len(vertices) + raw_index
                if index < 0 or index >= len(vertices):
                    raise ValueError(f"{path}:{line_number}: face index {raw_index} is out of range")
                indices.append(index)
            for index in range(1, len(indices) - 1):
                faces.append((indices[0], indices[index], indices[index + 1]))
    if not vertices:
        raise ValueError(f"{path}: OBJ contains no vertices")
    if not faces:
        raise ValueError(f"{path}: OBJ contains no faces")
    return vertices, faces


def age_to_plot(point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (x, z, y)


def set_equal_limits(axis, vertices: list[tuple[float, float, float]]) -> None:
    mins = [min(vertex[index] for vertex in vertices) for index in range(3)]
    maxs = [max(vertex[index] for vertex in vertices) for index in range(3)]
    centers = [(mins[index] + maxs[index]) * 0.5 for index in range(3)]
    radius = max(maxs[index] - mins[index] for index in range(3)) * 0.55
    radius = max(radius, 1e-3)
    axis.set_xlim(centers[0] - radius, centers[0] + radius)
    axis.set_ylim(centers[1] - radius, centers[1] + radius)
    axis.set_zlim(centers[2] - radius, centers[2] + radius)
    axis.set_box_aspect((1, 1, 1))


def render_preview(input_path: Path, output_path: Path, dpi: int = 180) -> dict:
    vertices, faces = load_obj_geometry(input_path)
    plot_vertices = [age_to_plot(vertex) for vertex in vertices]
    polygons = [[plot_vertices[index] for index in face] for face in faces]

    figure = plt.figure(figsize=(12, 4), facecolor="#f3f4f6")
    views = [
        ("Front", 0, -90),
        ("Side", 0, 0),
        ("Perspective", 22, -55),
    ]
    for panel, (title, elevation, azimuth) in enumerate(views, 1):
        axis = figure.add_subplot(1, 3, panel, projection="3d")
        collection = Poly3DCollection(
            polygons,
            facecolor="#6f8798",
            edgecolor="#26343d",
            linewidth=0.18,
            alpha=1.0,
        )
        axis.add_collection3d(collection)
        set_equal_limits(axis, plot_vertices)
        axis.view_init(elev=elevation, azim=azimuth)
        axis.set_title(title, fontsize=9)
        axis.set_axis_off()

    figure.suptitle(f"{input_path.name} | {len(vertices)} vertices | {len(faces)} triangles", fontsize=10)
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(figure)
    return {
        "input": str(input_path),
        "output": str(output_path),
        "vertices": len(vertices),
        "triangles": len(faces),
        "renderer": "matplotlib",
        "renderer_scope": "untextured orthographic topology preview",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render an untextured three-view preview of an exported OBJ.")
    parser.add_argument("input", help="OBJ input")
    parser.add_argument("--out", required=True, help="PNG output")
    parser.add_argument("--dpi", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    result = render_preview(Path(args.input), Path(args.out), args.dpi)
    print(f"Wrote preview: {result['output']}")
    print(f"Vertices: {result['vertices']}")
    print(f"Triangles: {result['triangles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




