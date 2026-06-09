from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from research.age_mbn_survey import archive_match_candidates, greedy_archive_cover, read_mbn_header  # noqa: E402


class MbnSurveyTests(unittest.TestCase):
    def test_read_mbn_header(self) -> None:
        data = bytearray(0x48)
        struct.pack_into("<II", data, 0, 0xAAAABBBB, 0xCCCCDDDD)
        self.assertEqual(read_mbn_header(bytes(data)), ("AAAABBBB", "CCCCDDDD"))

    def test_read_mbn_header_zero_parent(self) -> None:
        data = bytearray(0x48)
        struct.pack_into("<II", data, 0, 0xAAAABBBB, 0)
        self.assertEqual(read_mbn_header(bytes(data)), ("AAAABBBB", None))

    def test_archive_match_candidates_and_cover(self) -> None:
        archives = [
            {"archive": "a.xc", "mbn_count": 2, "bone_hashes": ["AAAABBBB", "CCCCDDDD"]},
            {"archive": "b.xc", "mbn_count": 3, "bone_hashes": ["AAAABBBB", "11112222", "33334444"]},
            {"archive": "c.xc", "mbn_count": 1, "bone_hashes": ["99990000"]},
        ]
        wanted = {"AAAABBBB", "CCCCDDDD", "11112222"}

        candidates = archive_match_candidates(archives, wanted)
        cover = greedy_archive_cover(candidates, wanted)

        self.assertEqual(candidates[0]["archive"], "a.xc")
        self.assertEqual(candidates[0]["matched_hash_count"], 2)
        self.assertEqual(cover[0]["archive"], "a.xc")
        self.assertEqual(cover[0]["new_hash_count"], 2)
        self.assertEqual(cover[1]["archive"], "b.xc")
        self.assertEqual(cover[1]["remaining_after"], 0)


if __name__ == "__main__":
    unittest.main()



