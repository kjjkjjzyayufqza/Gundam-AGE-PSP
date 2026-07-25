#!/usr/bin/env python3
"""Audit the repository for game assets before committing.

Two jobs:
  1. Summarise what lives under outputs/ so its deletion is an informed choice.
  2. List every file git would actually commit, flagged by extension, so no
     extracted game asset slips into the repository.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Extensions that mean extracted or converted game content.
ASSET_EXTENSIONS = {
    ".prm", ".xi", ".mbn", ".txp", ".mtr", ".atr", ".cmn", ".mtn2", ".mtninf",
    ".xc", ".xb", ".xa", ".xv", ".xk", ".xq", ".xr",
    ".png", ".jpg", ".jpeg", ".dds", ".tga",
    ".obj", ".mtl", ".gltf", ".glb", ".fbx", ".dae", ".bin",
    ".iso", ".cso", ".pmf", ".at3", ".wav",
}


def summarize_outputs() -> None:
    root = REPO / "outputs"
    print("=" * 60)
    if not root.is_dir():
        print("outputs/ : absent")
        return

    counts: Counter[str] = Counter()
    total_bytes = 0
    total_files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        total_files += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        counts[path.suffix.lower() or "(none)"] += 1

    print(f"outputs/ : {total_files} files, {total_bytes / (1024 * 1024):.1f} MB")
    for ext, count in counts.most_common(15):
        marker = "  <-- game asset" if ext in ASSET_EXTENSIONS else ""
        print(f"    {ext:<10} {count:>6}{marker}")

    print("\n  top-level subdirectories:")
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sum(1 for _ in child.rglob("*") if _.is_file())
        print(f"    {child.name:<22} {files:>6} files")


def git_tracked_and_staged() -> list[str]:
    """Files git currently knows about plus anything not ignored."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def audit_commit_set() -> int:
    print("=" * 60)
    files = git_tracked_and_staged()
    print(f"files git would track/commit: {len(files)}")

    suspicious: list[tuple[str, int]] = []
    counts: Counter[str] = Counter()
    for rel in files:
        suffix = Path(rel).suffix.lower()
        counts[suffix or "(none)"] += 1
        if suffix in ASSET_EXTENSIONS:
            path = REPO / rel
            size = path.stat().st_size if path.is_file() else 0
            suspicious.append((rel, size))

    print("\n  by extension:")
    for ext, count in counts.most_common():
        print(f"    {ext:<10} {count:>5}")

    # Also flag anything unusually large, whatever its extension.
    large: list[tuple[str, int]] = []
    for rel in files:
        path = REPO / rel
        if path.is_file():
            size = path.stat().st_size
            if size > 512 * 1024:
                large.append((rel, size))

    if suspicious:
        print(f"\n  ASSET-LIKE FILES ({len(suspicious)}):")
        for rel, size in sorted(suspicious):
            print(f"    {rel}  ({size} B)")
    else:
        print("\n  no asset-like extensions in the commit set")

    if large:
        print(f"\n  FILES OVER 512 KB ({len(large)}):")
        for rel, size in sorted(large, key=lambda x: -x[1]):
            print(f"    {rel}  ({size / 1024:.0f} KB)")
    else:
        print("  no files over 512 KB")

    return 1 if suspicious else 0


def main() -> int:
    summarize_outputs()
    return audit_commit_set()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
