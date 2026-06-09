"""Survey MBN static bind bones inside AGE PSP XPCK archives."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from age_xpck_tool import iter_candidate_files, parse_xpck, read_file  # noqa: E402


def read_mbn_header(data: bytes) -> tuple[str, str | None] | None:
    if len(data) < 0x48:
        return None
    bone_id, parent_id = struct.unpack_from("<II", data, 0)
    return f"{bone_id:08X}", f"{parent_id:08X}" if parent_id else None


def survey_archive(path: Path) -> dict[str, Any]:
    archive = parse_xpck(path)
    data = read_file(path)
    bones = []
    failures = []
    for entry in archive.entries:
        if not entry.valid_range or not entry.name.lower().endswith(".mbn"):
            continue
        try:
            header = read_mbn_header(data[entry.absolute_offset : entry.end_offset])
            if header is None:
                failures.append({"entry": entry.name, "error": "too small for MBN"})
                continue
            bone_hash, parent_hash = header
            bones.append({"entry": entry.name, "bone_hash": bone_hash, "parent_hash": parent_hash})
        except Exception as exc:
            failures.append({"entry": entry.name, "error": str(exc)})
    return {
        "archive": str(path),
        "file_count": archive.header.file_count,
        "mbn_count": len(bones),
        "bone_hashes": [bone["bone_hash"] for bone in bones],
        "bones": bones,
        "failures": failures,
    }


def archive_match_candidates(archives: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    if not wanted:
        return []
    candidates = []
    for archive in archives:
        hashes = {value.upper() for value in archive.get("bone_hashes", [])}
        matched = sorted(hashes & wanted)
        if not matched:
            continue
        candidates.append(
            {
                "archive": archive["archive"],
                "matched_hash_count": len(matched),
                "coverage": len(matched) / len(wanted),
                "mbn_count": archive["mbn_count"],
                "matched_hashes": matched,
            }
        )
    return sorted(candidates, key=lambda item: (item["matched_hash_count"], item["coverage"], -item["mbn_count"]), reverse=True)


def greedy_archive_cover(candidates: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    remaining = set(wanted)
    selected = []
    while remaining:
        best = None
        best_new: set[str] = set()
        for candidate in candidates:
            new_hashes = set(candidate["matched_hashes"]) & remaining
            if best is None or (len(new_hashes), candidate["matched_hash_count"], -candidate["mbn_count"]) > (
                len(best_new),
                best["matched_hash_count"],
                -best["mbn_count"],
            ):
                best = candidate
                best_new = new_hashes
        if best is None or not best_new:
            break
        selected.append(
            {
                "archive": best["archive"],
                "new_hash_count": len(best_new),
                "remaining_after": len(remaining - best_new),
                "new_hashes": sorted(best_new),
            }
        )
        remaining -= best_new
    return selected


def build_survey(inputs: list[Path], extensions: set[str], hashes: list[str], limit_archives: int | None = None) -> dict[str, Any]:
    wanted = {value.upper() for value in hashes}
    archives = []
    failures = []
    by_hash: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in iter_candidate_files(inputs, extensions, limit_archives):
        try:
            record = survey_archive(path)
            archives.append(record)
            for bone in record["bones"]:
                by_hash[bone["bone_hash"]].append({"archive": record["archive"], "entry": bone["entry"]})
        except Exception as exc:
            failures.append({"archive": str(path), "error": str(exc)})

    unique_hashes = set(by_hash)
    matches = {
        value: by_hash.get(value, [])
        for value in sorted(wanted)
    }
    candidates = archive_match_candidates(archives, wanted)
    cover = greedy_archive_cover(candidates, wanted)
    return {
        "inputs": [str(path) for path in inputs],
        "archive_count": len(archives),
        "archive_failures": failures,
        "archives_with_mbn": sum(1 for item in archives if item["mbn_count"]),
        "mbn_count": sum(item["mbn_count"] for item in archives),
        "unique_bone_hash_count": len(unique_hashes),
        "queried_hashes": sorted(wanted),
        "matched_hash_count": sum(1 for value in wanted if by_hash.get(value)),
        "unmatched_hashes": sorted(value for value in wanted if not by_hash.get(value)),
        "archive_match_candidates": candidates[:100],
        "greedy_archive_cover": cover,
        "matches": matches,
        "archives": archives,
        "notes": [
            "Survey reads MBN headers in memory and does not extract binary assets.",
            "Bone hashes are first u32 in .mbn; parent hash is second u32.",
        ],
    }


def command_survey(args: argparse.Namespace) -> int:
    inputs = [Path(item) for item in args.inputs]
    hashes = args.hashes or []
    if args.hash_file:
        hashes.extend(
            line.strip()
            for line in Path(args.hash_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    survey = build_survey(inputs, {ext.lower() for ext in args.extensions}, hashes, args.limit_archives)
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(survey, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print(json.dumps(survey, indent=2, ensure_ascii=False))
    print(f"Archives scanned: {survey['archive_count']}")
    print(f"Archives with MBN: {survey['archives_with_mbn']}")
    print(f"MBNs: {survey['mbn_count']}")
    print(f"Matched hashes: {survey['matched_hash_count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Survey MBN bind bones inside AGE PSP XPCK archives.")
    parser.add_argument("inputs", nargs="+", help="XPCK archives or directories")
    parser.add_argument("--extensions", nargs="+", default=[".xc"], help="XPCK extensions")
    parser.add_argument("--hashes", nargs="*", default=[], help="bone hashes to locate")
    parser.add_argument("--hash-file", help="newline-separated bone hashes")
    parser.add_argument("--limit-archives", type=int)
    parser.add_argument("--json", help="JSON output path")
    parser.set_defaults(func=command_survey)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




