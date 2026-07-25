#!/usr/bin/env python3
"""Print per-mesh vertex/face counts from the Python decoder for Rust parity checks."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "outputs" / "manifests" / "age_viewer_groundtruth.json"


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for sample in data["samples"]:
        name = Path(sample["archive"]).name
        meshes = [m for m in sample["meshes"] if "error" not in m]
        total_v = sum(m["vertex_count"] for m in meshes)
        total_f = sum(m["face_count"] for m in meshes)
        print(f"{name}: meshes={len(meshes)} vertices={total_v} faces={total_f}")
        for m in meshes:
            print(
                f"    {m['file']:<10} v={m['vertex_count']:<6} f={m['face_count']:<6} "
                f"stride={m['stride']:<3} pos={m['position_format']:<14} uv={m['uv0_format']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
