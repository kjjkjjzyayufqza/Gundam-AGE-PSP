#!/usr/bin/env python3
"""Verify the committed git tree contains no game assets, and report its size."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ASSET_EXTENSIONS = {
    ".prm", ".xi", ".mbn", ".txp", ".mtr", ".atr", ".cmn", ".mtn2", ".mtninf",
    ".mtminf", ".imminf", ".imm2",
    ".xc", ".xb", ".xa", ".xv", ".xk", ".xq", ".xr",
    ".png", ".jpg", ".jpeg", ".dds", ".tga",
    ".obj", ".mtl", ".gltf", ".glb", ".fbx", ".dae", ".bin",
    ".iso", ".cso", ".pmf", ".at3", ".wav",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def main() -> int:
    entries = [
        line.split("\t", 1)
        for line in git("ls-tree", "-r", "-l", "HEAD").splitlines()
        if line.strip()
    ]

    counts: Counter[str] = Counter()
    total = 0
    offenders: list[str] = []
    largest: list[tuple[int, str]] = []

    for meta, path in entries:
        parts = meta.split()
        size = int(parts[3]) if parts[3].isdigit() else 0
        total += size
        suffix = Path(path).suffix.lower()
        counts[suffix or "(none)"] += 1
        largest.append((size, path))
        if suffix in ASSET_EXTENSIONS:
            offenders.append(f"{path} ({size} B)")

    print(f"HEAD tree: {len(entries)} files, {total / 1024:.0f} KB")
    for ext, count in counts.most_common():
        print(f"    {ext:<10} {count:>4}")

    print("\n  largest committed files:")
    for size, path in sorted(largest, reverse=True)[:8]:
        print(f"    {size / 1024:>8.1f} KB  {path}")

    if offenders:
        print(f"\n  FAIL: {len(offenders)} asset-like files committed:")
        for item in offenders:
            print(f"    {item}")
        return 1

    print("\n  PASS: no game asset extensions in the committed tree")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
