from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from game_progress_query import (
    DEFAULT_CONFIG_DATA,
    compose_boss_preview,
    color_ratio,
    crop_relative_box,
    locate_template,
    is_running_as_admin,
    load_config,
    migrate_config,
    run_navigation_steps,
    template_specs,
    validate_point,
)


class GameProgressQueryTests(unittest.TestCase):
    def test_load_config_creates_default_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query.json"
            config = load_config(path)
            self.assertTrue(path.exists())
            self.assertEqual(config["version"], 24)
            self.assertTrue(config["require_admin"])
            self.assertIn("AutoHotkey64_UIA.exe", config["autohotkey_exe"])
            self.assertTrue(config["zdjl_click_script"].endswith("zdjl_click.js"))
            self.assertTrue(config["zdjl_task_file"].endswith("zdjl_task.json"))
            self.assertTrue(config["zdjl_result_file"].endswith("zdjl_result.json"))
            self.assertEqual(config["process_name"], "nikke.exe")
            self.assertEqual(
                config["navigation"][0]["point"],
                DEFAULT_CONFIG_DATA["navigation"][0]["point"],
            )
            self.assertEqual(config["navigation"][1]["name"], "联盟突袭入口")
            self.assertEqual(config["navigation"][1]["point"], [0.5000, 0.8350])
            self.assertEqual(len(config["boss_capture"]["stages"]), 5)
            self.assertEqual(config["boss_capture"]["pre_navigation"][0]["name"], "跳过击杀结算")
            self.assertEqual(config["boss_capture"]["stages"][0]["point"], [0.2700, 0.3460])
            self.assertEqual(config["after_capture_navigation"][0]["name"], "返回主页")
            self.assertIn("union_raid_entry", config["image_match"]["templates"])
            self.assertEqual(config["navigation"][1]["image_template"], "union_raid_entry")
            self.assertEqual(config["navigation"][1]["blocked_template"], "union_raid_no_open")

    def test_legacy_config_migrates_to_union_click_flow(self) -> None:
        config = migrate_config(
            {
                "version": 1,
                "navigation": [
                    {"name": "联盟入口", "point": [0.9, 0.4], "wait_seconds": 2.0},
                    {"name": "旧步骤", "point": None, "wait_seconds": 2.0},
                ],
            }
        )
        self.assertEqual(config["version"], 24)
        self.assertEqual(config["process_name"], "nikke.exe")
        self.assertEqual(len(config["navigation"]), 2)
        self.assertEqual(config["navigation"][0]["wait_seconds"], 4.0)
        self.assertEqual(config["zdjl_wait_seconds"], 8.0)
        self.assertEqual(config["navigation"][0]["point"], [0.9120, 0.3950])
        self.assertNotIn("extra_points", config["navigation"][0])
        self.assertEqual(config["navigation"][0]["wait_seconds"], 4.0)

    def test_v2_config_migrates_to_python_union_click(self) -> None:
        config = migrate_config(
            {
                "version": 2,
                "process_name": "nikke.exe",
                "navigation": [
                    {"name": "联盟入口", "point": [0.9065, 0.3924], "wait_seconds": 1.0},
                ],
            }
        )
        self.assertEqual(config["version"], 24)
        self.assertEqual(config["navigation"][0]["point"], [0.9120, 0.3950])
        self.assertEqual(config["navigation"][0]["click_method"], "sampler_pyautogui")
        self.assertEqual(config["navigation"][0]["wait_seconds"], 4.0)
        self.assertEqual(config["navigation"][0]["press_seconds"], 0.18)
        self.assertEqual(config["navigation"][1]["name"], "联盟突袭入口")
        self.assertTrue(config["boss_capture"]["send_composite"])
        self.assertEqual(config["after_capture_navigation"][0]["point"], [0.2740, 0.9420])

    def test_v21_config_migrates_to_maa_template_matching(self) -> None:
        config = migrate_config(
            {
                "version": 21,
                "image_match": {
                    "enabled": True,
                    "threshold": 0.7,
                    "templates": {"union_entry": "data/templates/union_entry_shield.png"},
                    "regions": {"union_entry": [0.55, 0.25, 1.0, 0.55]},
                },
                "navigation": [
                    {"name": "联盟入口", "point": [0.912, 0.395]},
                    {"name": "联盟突袭入口", "point": [0.5, 0.835]},
                ],
            }
        )

        self.assertEqual(config["version"], 24)
        self.assertIsInstance(config["image_match"]["templates"]["union_entry"], list)
        self.assertIn("union_raid_entry", config["image_match"]["templates"])
        self.assertEqual(config["image_match"]["templates"]["union_raid_entry"]["threshold"], 0.62)
        self.assertEqual(config["navigation"][1]["image_template"], "union_raid_entry")
        self.assertEqual(config["navigation"][1]["blocked_template"], "union_raid_no_open")

    def test_v22_config_migrates_template_threshold_overrides(self) -> None:
        config = migrate_config(
            {
                "version": 22,
                "image_match": {
                    "enabled": True,
                    "threshold": 0.7,
                    "templates": {
                        "union_entry": [
                            "data/templates/union_entry_shield.png",
                            "data/templates/maa_nikke/lianmeng.png",
                        ],
                        "union_raid_entry": "data/templates/maa_nikke/lianmengzhann.png",
                        "union_raid_no_open": "data/templates/maa_nikke/lianmengzhannoopen.png",
                    },
                    "regions": {},
                },
                "navigation": [
                    {"name": "联盟入口", "point": [0.912, 0.395]},
                    {"name": "联盟突袭入口", "point": [0.5, 0.835]},
                ],
            }
        )

        self.assertEqual(config["version"], 24)
        self.assertEqual(config["image_match"]["templates"]["union_raid_entry"]["threshold"], 0.62)
        self.assertEqual(config["image_match"]["templates"]["union_raid_no_open"]["threshold"], 0.60)

    def test_v23_config_deduplicates_template_paths(self) -> None:
        config = migrate_config(
            {
                "version": 23,
                "image_match": {
                    "templates": {
                        "union_entry": [
                            "data/templates/union_entry_shield.png",
                            "data/templates/maa_nikke/lianmeng.png",
                            {"path": "data/templates/maa_nikke/lianmeng.png", "threshold": 0.62},
                        ],
                    },
                },
            }
        )

        self.assertEqual(config["version"], 24)
        entries = config["image_match"]["templates"]["union_entry"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(str(entries[0]).replace("\\", "/"), "data/templates/union_entry_shield.png")
        self.assertIsInstance(entries[1], dict)
        self.assertEqual(str(entries[1]["path"]).replace("\\", "/"), "data/templates/maa_nikke/lianmeng.png")
        self.assertEqual(entries[1]["threshold"], 0.62)

    def test_validate_point_rejects_uncalibrated_step(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "校准"):
            validate_point(None, "联盟突袭入口")

    def test_validate_point_accepts_relative_coordinates(self) -> None:
        self.assertEqual(validate_point([0.25, 0.75], "测试"), [0.25, 0.75])

    def test_admin_check_returns_bool(self) -> None:
        self.assertIsInstance(is_running_as_admin(), bool)

    def test_crop_relative_box(self) -> None:
        image = Image.new("RGB", (100, 200), "black")
        cropped = crop_relative_box(image, [0.25, 0.10, 0.75, 0.60])
        self.assertEqual(cropped.size, (50, 100))

    def test_template_specs_accept_multiple_templates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = root / "one.png"
            two = root / "two.png"
            config = {
                "threshold": 0.7,
                "templates": {
                    "union_entry": [
                        {"path": str(one), "threshold": 0.8, "region": [0.1, 0.2, 0.3, 0.4]},
                        str(two),
                    ]
                },
                "regions": {"union_entry": [0.5, 0.6, 0.7, 0.8]},
            }

            specs = template_specs(config, "union_entry")

            self.assertEqual(len(specs), 2)
            self.assertEqual(specs[0].path, one)
            self.assertEqual(specs[0].threshold, 0.8)
            self.assertEqual(specs[0].region, [0.1, 0.2, 0.3, 0.4])
            self.assertEqual(specs[1].path, two)
            self.assertEqual(specs[1].threshold, 0.7)
            self.assertEqual(specs[1].region, [0.5, 0.6, 0.7, 0.8])

    def test_locate_template_matches_alpha_maa_template(self) -> None:
        template = Path("data/templates/maa_nikke/lianmeng.png")
        if not template.exists():
            self.skipTest("MAA union template is not available")

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Image.new("RGB", (320, 180), (22, 22, 22))
            icon = Image.open(template).convert("RGBA")
            screenshot.paste(icon, (230, 55), icon)
            match = locate_template(
                screenshot,
                template,
                threshold=0.62,
                region=[0.55, 0.20, 1.0, 0.58],
                scales=[1.0],
                stride=4,
            )

            self.assertIsNotNone(match)
            x, y, score = match
            self.assertAlmostEqual(x, 230 + icon.width // 2, delta=3)
            self.assertAlmostEqual(y, 55 + icon.height // 2, delta=3)
            self.assertGreaterEqual(score, 0.62)

    def test_compose_boss_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for index in range(5):
                path = root / f"boss_{index}.png"
                Image.new("RGB", (80, 40), (index * 20, 20, 20)).save(path)
                paths.append(path)
            preview = compose_boss_preview(paths, root, "2026-06-12 00:00:00")
            self.assertTrue(preview.exists())
            with Image.open(preview) as image:
                self.assertGreater(image.height, 200)

    def test_run_navigation_steps_ignores_invalid_container(self) -> None:
        run_navigation_steps(None, {}, None, 0.0)

    def test_enemy_defeated_button_color_detection(self) -> None:
        skip_page = Path(r"C:\Users\1E_6\AppData\Local\Temp\QQ_1781251930237.png")
        confirm_page = Path(r"C:\Users\1E_6\AppData\Local\Temp\QQ_1781252010611.png")
        normal_page = Path(r"C:\Users\1E_6\AppData\Local\Temp\QQ_1781249435436.png")
        if not (skip_page.exists() and confirm_page.exists() and normal_page.exists()):
            self.skipTest("local QQ screenshots are not available")

        self.assertGreater(
            color_ratio(Image.open(skip_page).convert("RGB"), [0.48, 0.65, 0.88, 0.76], "orange"),
            0.08,
        )
        self.assertGreater(
            color_ratio(Image.open(confirm_page).convert("RGB"), [0.30, 0.65, 0.70, 0.76], "blue"),
            0.08,
        )
        self.assertLess(
            color_ratio(Image.open(normal_page).convert("RGB"), [0.48, 0.65, 0.88, 0.76], "orange"),
            0.08,
        )


if __name__ == "__main__":
    unittest.main()
