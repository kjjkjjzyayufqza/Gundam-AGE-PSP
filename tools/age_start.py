#!/usr/bin/env python3
"""Stable command entrypoint for Gundam AGE PSP asset research tools.

This file is intentionally thin. It keeps the user-facing commands short while
delegating all real parsing/conversion work to the focused research modules.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))


def add_asset_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", help="XPCK archive path")
    parser.add_argument("--out-dir", required=True, help="pipeline output directory")
    parser.add_argument("--name", help="base name for OBJ/glTF output")
    parser.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    parser.add_argument("--texture-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    parser.add_argument("--overwrite", action="store_true")


def append_if(argv: list[str], flag: str, value: str | None) -> None:
    if value:
        argv.extend([flag, value])


def append_bool(argv: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        argv.append(flag)


def command_asset(args: argparse.Namespace) -> int:
    import age_asset_pipeline

    argv = [
        "from-xpck",
        args.input,
        "--out-dir",
        args.out_dir,
        "--triangulation",
        args.triangulation,
        "--texture-layout",
        args.texture_layout,
    ]
    append_if(argv, "--name", args.name)
    append_bool(argv, "--overwrite", args.overwrite)
    return age_asset_pipeline.main(argv)


def command_character(args: argparse.Namespace) -> int:
    import age_asset_pipeline

    argv = [
        "from-character",
        args.input,
        "--out-dir",
        args.out_dir,
        "--triangulation",
        args.triangulation,
        "--texture-layout",
        args.texture_layout,
        "--animation-policy",
        args.animation_policy,
    ]
    append_if(argv, "--name", args.name)
    append_bool(argv, "--overwrite", args.overwrite)
    return age_asset_pipeline.main(argv)


def command_map_survey(args: argparse.Namespace) -> int:
    from research import age_map_survey

    argv = [
        "--input-root",
        args.input_root,
        "--out-root",
        args.out_root,
        "--triangulation",
        args.triangulation,
        "--texture-layout",
        args.texture_layout,
    ]
    for pattern in (args.include or ["*.xc"]):
        argv.extend(["--include", pattern])
    for pattern in args.exclude:
        argv.extend(["--exclude", pattern])
    append_bool(argv, "--overwrite", args.overwrite)
    append_bool(argv, "--cleanup-samples", args.cleanup_samples)
    return age_map_survey.main(argv)


def command_xpck_extract(args: argparse.Namespace) -> int:
    import age_xpck_tool

    argv = ["extract", args.input, "--out", args.out]
    append_bool(argv, "--overwrite", args.overwrite)
    return age_xpck_tool.main(argv)


def command_index(args: argparse.Namespace) -> int:
    import age_asset_index

    argv = [
        *args.inputs,
        "--json",
        args.json,
        "--markdown",
        args.markdown,
        "--extensions",
        args.extensions,
    ]
    append_if(argv, "--compact-json", args.compact_json)
    for pattern in args.include:
        argv.extend(["--include", pattern])
    for pattern in args.exclude:
        argv.extend(["--exclude", pattern])
    for root in args.pipeline_root:
        argv.extend(["--pipeline-root", root])
    append_if(argv, "--limit", str(args.limit) if args.limit is not None else None)
    append_if(argv, "--sample-limit", str(args.sample_limit) if args.sample_limit is not None else None)
    return age_asset_index.main(argv)


def command_fx_index(args: argparse.Namespace) -> int:
    import age_fx_index

    argv: list[str] = ["--json", args.json]
    if args.unpack_root:
        argv.insert(0, args.unpack_root)
    append_if(argv, "--markdown", args.markdown)
    append_bool(argv, "--native-only", args.native_only)
    append_bool(argv, "--no-members", args.no_members)
    append_if(argv, "--member-limit", str(args.member_limit) if args.member_limit is not None else None)
    return age_fx_index.main(argv)


def command_preview(args: argparse.Namespace) -> int:
    import age_blender_preview

    argv = [args.input]
    append_if(argv, "--out", args.out)
    append_if(argv, "--out-dir", args.out_dir)
    append_if(argv, "--blender", args.blender)
    append_if(argv, "--width", str(args.width) if args.width is not None else None)
    append_if(argv, "--height", str(args.height) if args.height is not None else None)
    append_if(argv, "--samples", str(args.samples) if args.samples is not None else None)
    append_if(argv, "--views", args.views)
    append_if(argv, "--engine", args.engine)
    append_if(argv, "--json", args.json)
    append_if(argv, "--timeout", str(args.timeout) if args.timeout is not None else None)
    return age_blender_preview.main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gundam AGE PSP asset tool entrypoint.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    asset = subparsers.add_parser("asset", help="extract one XPCK and export textures/models")
    add_asset_options(asset)
    asset.set_defaults(func=command_asset)

    character = subparsers.add_parser("character", help="extract one character XPCK; animation stays opt-in")
    add_asset_options(character)
    character.add_argument("--animation-policy", choices=["none", "best", "all"], default="none")
    character.set_defaults(func=command_character)

    map_parser = subparsers.add_parser("map", help="map survey commands")
    map_sub = map_parser.add_subparsers(dest="map_command", required=True)

    survey = map_sub.add_parser("survey", help="run large-sample map survey")
    survey.add_argument("--input-root", required=True)
    survey.add_argument("--out-root", required=True)
    survey.add_argument("--include", action="append", default=[])
    survey.add_argument("--exclude", action="append", default=[])
    survey.add_argument("--triangulation", choices=["strip", "list", "points"], default="strip")
    survey.add_argument("--texture-layout", choices=["psp-swizzled", "tiled", "linear"], default="psp-swizzled")
    survey.add_argument("--overwrite", action="store_true")
    survey.add_argument("--cleanup-samples", action="store_true")
    survey.set_defaults(func=command_map_survey)

    xpck = subparsers.add_parser("xpck", help="XPCK archive commands")
    xpck_sub = xpck.add_subparsers(dest="xpck_command", required=True)

    extract = xpck_sub.add_parser("extract", help="extract one XPCK archive")
    extract.add_argument("input")
    extract.add_argument("--out", required=True)
    extract.add_argument("--overwrite", action="store_true")
    extract.set_defaults(func=command_xpck_extract)

    index = subparsers.add_parser("index", help="build model/texture archive index")
    index.add_argument("inputs", nargs="+", help="XPCK archive files or directories")
    index.add_argument("--json", required=True)
    index.add_argument("--compact-json")
    index.add_argument("--markdown", required=True)
    index.add_argument("--include", action="append", default=[])
    index.add_argument("--exclude", action="append", default=[])
    index.add_argument("--extensions", default=".xc,.xb,.xa,.xk,.xi,.xq,.xv,.bin,.npcbin")
    index.add_argument("--pipeline-root", action="append", default=[])
    index.add_argument("--limit", type=int)
    index.add_argument("--sample-limit", type=int, default=30)
    index.set_defaults(func=command_index)

    fx_index = subparsers.add_parser(
        "fx-index",
        help="inventory age-fx from game-native effect_config.cfg.bin + XPCK member tables",
    )
    fx_index.add_argument(
        "unpack_root",
        nargs="?",
        help="unpacked root containing psp/ and cmn/ (optional if auto-discoverable)",
    )
    fx_index.add_argument("--json", required=True)
    fx_index.add_argument("--markdown")
    fx_index.add_argument("--native-only", action="store_true")
    fx_index.add_argument("--no-members", action="store_true")
    fx_index.add_argument("--member-limit", type=int)
    fx_index.set_defaults(func=command_fx_index)

    preview = subparsers.add_parser(
        "preview",
        help="render glTF/OBJ preview PNG via Blender headless CLI",
    )
    preview.add_argument("input", help="glTF/OBJ path or package directory containing models/")
    preview.add_argument("--out", help="PNG output path")
    preview.add_argument("--out-dir", help="PNG output directory")
    preview.add_argument("--blender", help="path to blender.exe")
    preview.add_argument("--width", type=int, default=1400)
    preview.add_argument("--height", type=int, default=900)
    preview.add_argument("--samples", type=int, default=16)
    preview.add_argument("--views", default="front,side,perspective")
    preview.add_argument("--engine", default="auto", choices=["auto", "EEVEE", "CYCLES", "WORKBENCH"])
    preview.add_argument("--json", help="write result JSON")
    preview.add_argument("--timeout", type=int, default=300)
    preview.set_defaults(func=command_preview)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())




