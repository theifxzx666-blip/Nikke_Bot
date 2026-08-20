from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from guild_war_bot.wiki_query.catalog import AffixCatalog, best_values_by_type
from guild_war_bot.wiki_query.equipment_session import SessionManager, Step, parse_affix_command
from guild_war_bot.wiki_query.equipment_store import EquipmentStore
from guild_war_bot.wiki_query.ocr import AffixOCR, OCRText, infer_tier


class EquipmentAffixTests(unittest.TestCase):
    def test_store_confirm_and_user_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = EquipmentStore(Path(temp) / "equipment.db")
            rows = [{"slot": 1, "affix_type": "攻击力", "affix_value": 8.2, "value_text": "8.2%", "tier": 2}]
            self.assertEqual(store.commit_affixes("100", "laplace", "拉普拉斯", rows), 1)
            self.assertEqual(len(store.list_affixes("100")), 1)
            self.assertEqual(store.list_affixes("200"), [])
            rows[0]["affix_value"] = 9.1
            store.commit_affixes("100", "laplace", "拉普拉斯", rows)
            self.assertEqual(store.list_affixes("100")[0]["affix_value"], 9.1)

    def test_session_restores_and_reaches_confirm(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp:
                store = EquipmentStore(Path(temp) / "equipment.db")
                manager = SessionManager(store, timeout_seconds=1800)
                await manager.start("100", {"id": "laplace", "name": "拉普拉斯"}, 2)
                first = await manager.add_result("100", "one.png", [{"slot": 1}])
                self.assertEqual(first.step, Step.WAITING_SCREENSHOT_N)
                restored = SessionManager(store)
                session = await restored.get("100")
                self.assertEqual(session.step, Step.WAITING_SCREENSHOT_N)
                final = await restored.add_result("100", "two.png", [{"slot": 2}])
                self.assertEqual(final.step, Step.WAITING_CONFIRM)

        asyncio.run(scenario())

    def test_ocr_normalizes_alias_and_explicit_tier(self) -> None:
        catalog = {"攻击力": {"aliases": ["攻击"], "unit": "%", "tier_values": {}}}
        ocr = AffixOCR(catalog)
        hit = ocr.parse_line(2, "攻击 8.0％ 第15阶", 0.93)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.affix_type, "攻击力")
        self.assertEqual(hit.tier, 15)

    def test_tier_is_unknown_without_calibrated_values(self) -> None:
        self.assertEqual(infer_tier({"tier_values": {}}, 8.2), 0)

    def test_group_lines_and_adjacent_line_parsing(self) -> None:
        catalog = {"攻击力": {"aliases": ["攻击"], "unit": "%", "tier_values": {}}}
        ocr = AffixOCR(catalog)
        hits, _ = ocr._parse_items([
            OCRText("攻击力", 0.94, 10, 10),
            OCRText("8.2%", 0.91, 30, 10),
        ], 1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].affix_value, 8.2)

    def test_empty_ocr_does_not_advance_session(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp:
                store = EquipmentStore(Path(temp) / "equipment.db")
                manager = SessionManager(store)
                await manager.start("100", {"id": "laplace", "name": "拉普拉斯"}, 4)
                session = await manager.add_result("100", "empty.png", [])
                self.assertEqual(session.step, Step.WAITING_SCREENSHOT_N)
                self.assertEqual(session.payload["images"], [])

        asyncio.run(scenario())

    def test_manual_correction_can_reach_confirm(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp:
                store = EquipmentStore(Path(temp) / "equipment.db")
                manager = SessionManager(store)
                await manager.start("100", {"id": "laplace", "name": "拉普拉斯"}, 2)
                await manager.correct_row("100", {"slot": 1, "affix_type": "攻击力", "affix_value": 8.2, "tier": 0})
                session = await manager.correct_row("100", {"slot": 2, "affix_type": "防御力", "affix_value": 4.1, "tier": 15})
                self.assertEqual(session.step, Step.WAITING_CONFIRM)

        asyncio.run(scenario())

    def test_store_accepts_tier_15_and_rejects_16(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = EquipmentStore(Path(temp) / "equipment.db")
            row = {"slot": 1, "affix_type": "攻击力", "affix_value": 8.2, "value_text": "8.2%", "tier": 15}
            self.assertEqual(store.commit_affixes("100", "laplace", "拉普拉斯", [row]), 1)
            row["tier"] = 16
            with self.assertRaises(ValueError):
                store.commit_affixes("100", "laplace", "拉普拉斯", [row])

    def test_ocr_cache_returns_id_and_review_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image_path = root / "sample.png"
            Image.new("RGB", (10, 10)).save(image_path)
            store = EquipmentStore(root / "equipment.db")
            result = {"status": "needs_review", "rows": [{"slot": 1}], "confidence": 0.7, "raw_text": "x"}
            ocr_id = store.save_ocr("100", image_path, result)
            cached = store.cached_ocr("100", image_path)
            self.assertEqual(cached["ocr_id"], ocr_id)
            self.assertEqual(cached["status"], "needs_review")

    def test_existing_tier_constraint_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "equipment.db"
            db = sqlite3.connect(path)
            try:
                db.executescript("""
                    CREATE TABLE users(user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT);
                    CREATE TABLE characters(character_id TEXT PRIMARY KEY, character_name TEXT NOT NULL UNIQUE, wiki_name TEXT NOT NULL DEFAULT '');
                    CREATE TABLE equipment_affixes(
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, character_id TEXT NOT NULL,
                        slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5), affix_type TEXT NOT NULL,
                        affix_value REAL NOT NULL, value_text TEXT NOT NULL DEFAULT '',
                        tier INTEGER NOT NULL CHECK(tier BETWEEN 0 AND 3), source_ocr_id INTEGER,
                        created_at TEXT, updated_at TEXT, UNIQUE(user_id, character_id, slot, affix_type));
                """)
                db.commit()
            finally:
                db.close()
            store = EquipmentStore(path)
            row = {"slot": 1, "affix_type": "攻击力", "affix_value": 8.2, "value_text": "8.2%", "tier": 15}
            self.assertEqual(store.commit_affixes("100", "laplace", "拉普拉斯", [row]), 1)

    def test_character_catalog_defaults_to_four_slots(self) -> None:
        catalog = json.loads(Path("data/character_equip_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["_default"]["slots"], [1, 2, 3, 4])

    def test_command_prefixes(self) -> None:
        for prefix in ("#", "/", "＃", "／"):
            self.assertEqual(parse_affix_command(f"{prefix}词条统计 攻击力"), ("词条统计", "攻击力"))
        self.assertIsNone(parse_affix_command("词条统计 攻击力"))

    def test_card_highlight_compares_within_same_type(self) -> None:
        rows = [
            {"affix_type": "攻击力", "affix_value": 8.2},
            {"affix_type": "攻击力", "affix_value": 6.1},
            {"affix_type": "暴击率", "affix_value": 4.0},
        ]
        self.assertEqual(best_values_by_type(rows), {"攻击力": 8.2, "暴击率": 4.0})

    def test_catalog_renders_card_and_exports_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            catalog = AffixCatalog(Path("data/equipment_affix_catalog.json"))
            rows = [{"slot": 1, "affix_type": "攻击力", "affix_value": 8.2, "value_text": "8.2%", "tier": 2}]
            card = catalog.render_card(
                {"cnName": "拉普拉斯", "core_affixes": ["攻击力", "优越代码伤害", "最大装弹数", "蓄力速度", "蓄力伤害"]},
                rows,
                out_dir / "card.png",
            )
            self.assertTrue(card.exists())
            with Image.open(card) as image:
                self.assertGreater(image.width, 800)
            try:
                workbook = catalog.export_xlsx(rows, out_dir / "rows.xlsx")
            except RuntimeError as exc:
                self.skipTest(str(exc))
            self.assertTrue(workbook.exists())


if __name__ == "__main__":
    unittest.main()
