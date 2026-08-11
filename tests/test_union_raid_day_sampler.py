from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from guild_war_bot.union_suite import UnionRaidSuite
from union_raid_day_sampler import DEFAULT_TESSERACT, scan_image, write_attendance_csv, write_records_csv


def flow1_damage_image() -> Path:
    return (
        Path("D:/Codex")
        / "\u4f9d\u8d56"
        / "Nikke\u7d20\u6750\u91c7\u6837"
        / "\u8054\u76df\u91c7\u6837"
        / "\u8054\u76df\u7a81\u88ad"
        / "\u91c7\u96c6\u94fe\u8def1"
        / "\u8054\u76df_\u8054\u76df\u7a81\u88ad_\u6d3b\u52a8\u4e3b\u9875_\u8054\u76df\u8bb0\u5f55_\u4f24\u5bb3\u660e\u7ec6.png"
    )


@unittest.skipUnless(
    flow1_damage_image().exists() and (DEFAULT_TESSERACT.exists() or shutil.which("tesseract")),
    "flow1 material and tesseract are required",
)
class UnionRaidDaySamplerTests(unittest.TestCase):
    def test_scan_image_reads_flow1_damage_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = UnionRaidSuite(root / "guild_war.db", root / "sample.db")
            try:
                suite.add_member("HANSON", None, None, None)
                suite.add_member("NING", None, None, None)
            finally:
                suite.close()

            records = scan_image(
                flow1_damage_image(),
                db_path=root / "guild_war.db",
                battle_date="2026-06-12",
                raid_day=1,
                out_dir=root / "samples",
                session_id="unit_flow1",
            )
            records_csv = root / "records.csv"
            attendance_csv = root / "attendance.csv"
            write_records_csv(records, records_csv)
            write_attendance_csv(records, attendance_csv)
            records_csv_bytes = records_csv.read_bytes()
            records_csv_header = records_csv.read_text(encoding="utf-8-sig").splitlines()[0]
            attendance_csv_header = attendance_csv.read_text(encoding="utf-8-sig").splitlines()[0]

        self.assertEqual(len(records), 6)
        self.assertTrue(records_csv_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertIn("member_name", records_csv_header)
        self.assertIn("attacks", attendance_csv_header)
        self.assertEqual(
            [record.damage for record in records],
            [2354369175, 1538157240, 1569579475, 1118659860, 1677989700, 2354369175],
        )
        self.assertEqual([record.boss_name for record in records], ["克拉肯", "普拉特", "铁匠", "天辉", "殓巾", "克拉肯"])
        self.assertEqual([record.boss_level for record in records], [10, 10, 10, 10, 10, 9])
        self.assertEqual(sum(1 for record in records if record.member_id), 4)

    def test_import_flow1_records_is_replaceable_and_allows_day1_shortfall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = UnionRaidSuite(root / "guild_war.db", root / "sample.db")
            try:
                suite.add_member("HANSON", None, None, None)
                suite.add_member("NING", None, None, None)
            finally:
                suite.close()

            records = scan_image(
                flow1_damage_image(),
                db_path=root / "guild_war.db",
                battle_date="2026-06-12",
                raid_day=1,
                out_dir=root / "samples",
                session_id="unit_flow1_import",
            )

            suite = UnionRaidSuite(root / "guild_war.db", root / "sample.db")
            try:
                first = suite.import_flow1_records([record.__dict__ for record in records])
                second = suite.import_flow1_records([record.__dict__ for record in records])
                attacks = suite.list_attacks(limit=20)
                attendance = {row["member"].name: row for row in suite.attendance_rows()}
            finally:
                suite.close()

        self.assertEqual(first["inserted"], 4)
        self.assertEqual(first["skipped_unmatched"], 2)
        self.assertEqual(second["inserted"], 4)
        self.assertEqual(len(attacks), 4)
        self.assertEqual(attendance["HANSON"]["d1"], 3)
        self.assertEqual(attendance["NING"]["d1"], 1)
        self.assertGreater(attendance["NING"]["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
