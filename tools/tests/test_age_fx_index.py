from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from age_fx_index import (  # noqa: E402
    EFFECT_CONFIG_TAG,
    build_fx_inventory,
    crc32_ascii,
    discover_default_unpack_root,
    parse_effect_config_file,
)


def _pack_effect_config(base_path: str, pairs: list[tuple[str, str]]) -> bytes:
    """Build a minimal Level-5-like effect_config blob for unit tests."""
    string_blob = bytearray()
    offsets: dict[str, int] = {}

    def add_string(text: str) -> int:
        if text in offsets:
            return offsets[text]
        off = len(string_blob)
        string_blob.extend(text.encode("ascii") + b"\x00")
        offsets[text] = off
        return off

    add_string(base_path)
    records = bytearray()
    # Prefix with BEGIN tag so the layout resembles the real file.
    records.extend(struct.pack("<I", crc32_ascii("EFFECT_CONFIG_BEGIN")))
    records.extend(struct.pack("<I", 0xFFFF0101))

    for effect_id, archive_name in pairs:
        name_off = add_string(effect_id)
        archive_off = add_string(archive_name)
        records.extend(
            struct.pack(
                "<IIIIII",
                EFFECT_CONFIG_TAG,
                0x5155140F,
                0xFFFFFF15,
                name_off,
                crc32_ascii(effect_id),
                0,
            )
        )
        records.extend(struct.pack("<I", archive_off))
        records.extend(b"\x00" * 44)  # pad toward observed 0x48-ish stride

    string_table_offset = 16 + len(records)
    header = struct.pack("<IIII", len(pairs), string_table_offset, 0, 0)
    trailer = b"".join(
        name.encode("ascii") + b"\x00"
        for name in (
            "EFFECT_CONFIG_BASE_FILE_PATH",
            "EFFECT_CONFIG_BEGIN",
            "EFFECT_CONFIG",
            "EFFECT_CONFIG_END",
            "EFFECT_CONFIG_INDEX_BEGIN",
            "EFFECT_CONFIG_INDEX",
            "EFFECT_CONFIG_INDEX_END",
        )
    )
    return header + bytes(records) + bytes(string_blob) + trailer


class AgeFxIndexUnitTests(unittest.TestCase):
    def test_parse_effect_config_extracts_ids_and_archives(self) -> None:
        blob = _pack_effect_config(
            "#/eff/",
            [
                ("eb000010", "eb000010.xc"),
                ("esga0125b", "esga0125b.xc"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "effect_config.cfg.bin"
            path.write_bytes(blob)
            doc = parse_effect_config_file(path)

        self.assertEqual(doc.base_path, "#/eff/")
        self.assertIn("eb000010.xc", doc.archive_names)
        self.assertIn("esga0125b.xc", doc.archive_names)
        ids = {entry.effect_id: entry.archive_name for entry in doc.entries}
        self.assertEqual(ids.get("eb000010"), "eb000010.xc")
        self.assertEqual(ids.get("esga0125b"), "esga0125b.xc")
        self.assertEqual(crc32_ascii("eb000010"), zlib.crc32(b"eb000010") & 0xFFFFFFFF)

    def test_build_fx_inventory_uses_native_config_not_path_scan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_dir = root / "cmn" / "res" / "eff"
            eff_dir = root / "psp" / "eff"
            cfg_dir.mkdir(parents=True)
            eff_dir.mkdir(parents=True)
            cfg_dir.joinpath("effect_config.cfg.bin").write_bytes(
                _pack_effect_config("#/eff/", [("eb000200", "eb000200.xc")])
            )
            # Provide a tiny non-XPCK placeholder; member inspect should fail softly.
            (eff_dir / "eb000200.xc").write_bytes(b"not-xpck")
            (eff_dir / "disk_only_extra.xc").write_bytes(b"not-xpck")

            inventory = build_fx_inventory(root, include_disk_only=True, inspect_members=True)
            names = {row["archive_name"] for row in inventory["archives"]}
            self.assertIn("eb000200.xc", names)
            self.assertIn("disk_only_extra.xc", names)
            native_row = next(row for row in inventory["archives"] if row["archive_name"] == "eb000200.xc")
            self.assertIn("effect_config.cfg.bin", native_row["sources"])
            self.assertEqual(native_row["effect_ids"], ["eb000200"])
            self.assertTrue(inventory["game_native_lists"]["effect_config"]["path"].endswith("effect_config.cfg.bin"))


@unittest.skipUnless(discover_default_unpack_root() is not None, "local AGE unpack root not available")
class AgeFxIndexLiveDataTests(unittest.TestCase):
    def test_live_effect_config_resolves_real_prm_or_xi(self) -> None:
        unpack = discover_default_unpack_root()
        assert unpack is not None
        inventory = build_fx_inventory(
            unpack,
            include_disk_only=False,
            inspect_members=True,
            member_limit=25,
        )
        self.assertGreater(inventory["summary"]["native_config_archive_count"], 0)
        self.assertGreater(inventory["summary"]["resolved_archive_count"], 0)
        useful = [
            row
            for row in inventory["archives"]
            if row.get("members")
            and row["members"].get("parse_ok")
            and (row["members"].get("model_count", 0) > 0 or row["members"].get("texture_count", 0) > 0)
        ]
        self.assertGreaterEqual(len(useful), 1, "expected at least one FX archive with models or textures")
        sample = useful[0]
        self.assertTrue(sample["archive_name"].endswith(".xc"))
        self.assertTrue(sample["on_disk"])
        members = sample["members"]
        self.assertTrue(members["model_count"] > 0 or members["texture_count"] > 0)


if __name__ == "__main__":
    unittest.main()
