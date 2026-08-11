from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from union_auto_sampler import (
    WindowInfo,
    absolute_point,
    get_cursor_relative_to_window,
    list_windows,
    load_config as load_sampler_config,
    screenshot_window,
    wait_for_hotkey,
)


DEFAULT_CONFIG = Path("data") / "game_progress_query.config.json"
DEFAULT_OUTPUT_DIR = Path("data") / "game_progress_queries"
DEFAULT_SAMPLER_CONFIG = Path("data") / "union_auto_sampler.config.json"
DEFAULT_AHK_EXE = Path(r"C:\Program Files\AutoHotkey\v2\AutoHotkey64_UIA.exe")
DEFAULT_AHK_SCRIPT = Path("click_union.ahk")
DEFAULT_NODE_EXE = Path(os.environ.get("NODE_EXE", "node"))
DEFAULT_ZDJL_CLICK_SCRIPT = Path("zdjl_click.js")
DEFAULT_ZDJL_TASK_FILE = Path("data") / "zdjl_task.json"
DEFAULT_ZDJL_RESULT_FILE = Path("data") / "zdjl_result.json"
DEFAULT_UNION_TEMPLATE = Path("data") / "templates" / "union_entry_shield.png"
DEFAULT_MAA_TEMPLATE_DIR = Path("data") / "templates" / "maa_nikke"
DEFAULT_MAA_UNION_TEMPLATE = DEFAULT_MAA_TEMPLATE_DIR / "lianmeng.png"
DEFAULT_MAA_RAID_TEMPLATE = DEFAULT_MAA_TEMPLATE_DIR / "lianmengzhann.png"
DEFAULT_MAA_RAID_LOCKED_TEMPLATE = DEFAULT_MAA_TEMPLATE_DIR / "lianmengzhannoopen.png"

DEFAULT_CONFIG_DATA: dict[str, Any] = {
    "version": 24,
    "process_name": "nikke.exe",
    "require_admin": True,
    "autohotkey_exe": str(DEFAULT_AHK_EXE),
    "autohotkey_script": str(DEFAULT_AHK_SCRIPT),
    "autohotkey_elevated": True,
    "node_exe": str(DEFAULT_NODE_EXE),
    "zdjl_click_script": str(DEFAULT_ZDJL_CLICK_SCRIPT),
    "zdjl_task_file": str(DEFAULT_ZDJL_TASK_FILE),
    "zdjl_result_file": str(DEFAULT_ZDJL_RESULT_FILE),
    "zdjl_task_status": "pending_image_click",
    "zdjl_wait_seconds": 8.0,
    "image_match": {
        "enabled": True,
        "threshold": 0.7,
        "scales": [0.85, 0.90, 1.00, 1.10, 1.20],
        "stride": 6,
        "templates": {
            "union_entry": [
                str(DEFAULT_UNION_TEMPLATE),
                {"path": str(DEFAULT_MAA_UNION_TEMPLATE), "threshold": 0.62},
            ],
            "union_raid_entry": {"path": str(DEFAULT_MAA_RAID_TEMPLATE), "threshold": 0.62},
            "union_raid_no_open": {"path": str(DEFAULT_MAA_RAID_LOCKED_TEMPLATE), "threshold": 0.60},
        },
        "regions": {
            "union_entry": [0.55, 0.20, 1.0, 0.58],
            "union_raid_entry": [0.35, 0.65, 0.65, 0.94],
            "union_raid_no_open": [0.35, 0.65, 0.65, 0.94],
        },
    },
    "game_executable": "",
    "game_arguments": [],
    "window_title": "",
    "window_wait_seconds": 90,
    "step_wait_seconds": 1.0,
    "startup_wait_seconds": 12.0,
    "navigation": [
        {
            "name": "联盟入口",
            "image_template": "union_entry",
            "point": [0.9120, 0.3950],
            "wait_seconds": 4.0,
            "click_method": "sampler_pyautogui",
            "click_count": 1,
            "press_seconds": 0.18,
        },
        {
            "name": "联盟突袭入口",
            "image_template": "union_raid_entry",
            "blocked_template": "union_raid_no_open",
            "blocked_message": "联盟突袭入口未开放或处于锁定状态，已停止查询。",
            "point": [0.5000, 0.8350],
            "wait_seconds": 3.0,
            "click_method": "sampler_pyautogui",
            "click_count": 1,
            "press_seconds": 0.18,
        },
    ],
    "boss_capture": {
        "enabled": True,
        "pre_navigation": [
            {
                "name": "跳过击杀结算",
                "point": [0.7100, 0.7100],
                "wait_seconds": 1.5,
                "click_method": "sampler_pyautogui",
                "click_count": 1,
                "press_seconds": 0.12,
                "condition": {
                    "type": "color_ratio",
                    "region": [0.4800, 0.6500, 0.8800, 0.7600],
                    "color": "orange",
                    "threshold": 0.08,
                },
            },
            {
                "name": "确认击杀奖励",
                "point": [0.5000, 0.7100],
                "wait_seconds": 1.8,
                "click_method": "sampler_pyautogui",
                "click_count": 1,
                "press_seconds": 0.12,
                "condition": {
                    "type": "color_ratio",
                    "region": [0.3000, 0.6500, 0.7000, 0.7600],
                    "color": "blue",
                    "threshold": 0.08,
                },
            },
        ],
        "wait_seconds": 1.2,
        "click_method": "sampler_pyautogui",
        "press_seconds": 0.12,
        "stages": [
            {"label": "I", "point": [0.2700, 0.3460]},
            {"label": "II", "point": [0.3860, 0.3460]},
            {"label": "III", "point": [0.5010, 0.3460]},
            {"label": "IV", "point": [0.6170, 0.3460]},
            {"label": "V", "point": [0.7300, 0.3460]},
        ],
        "screenshot_box": [0.0000, 0.3000, 1.0000, 0.8100],
        "send_composite": True,
    },
    "after_capture_navigation": [
        {
            "name": "返回主页",
            "point": [0.2740, 0.9420],
            "wait_seconds": 1.0,
            "click_method": "sampler_pyautogui",
            "click_count": 1,
            "press_seconds": 0.12,
        },
    ],
    "screenshot_box": None,
}


@dataclass(frozen=True)
class QueryResult:
    image_path: Path
    window_title: str
    captured_at: str
    image_paths: list[Path] | None = None


@dataclass(frozen=True)
class TemplateSpec:
    path: Path
    threshold: float
    region: list[float] | None = None


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if not path.exists():
        save_config(path, DEFAULT_CONFIG_DATA)
        return json.loads(json.dumps(DEFAULT_CONFIG_DATA, ensure_ascii=False))
    current = json.loads(path.read_text(encoding="utf-8-sig"))
    migrated = migrate_config(current)
    config = deep_merge(DEFAULT_CONFIG_DATA, migrated)
    if config != current:
        save_config(path, config)
    return config


def migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    version = int(result.get("version", 0) or 0)
    if version < 2:
        result["version"] = 2
        result.setdefault("process_name", "nikke.exe")
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["name"] = "联盟入口"
            first["wait_seconds"] = 1.0
            result["navigation"] = [first]
        else:
            result["navigation"] = DEFAULT_CONFIG_DATA["navigation"]
        result["step_wait_seconds"] = 1.0
        version = 2
    if version < 3:
        result["version"] = 3
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["point"] = [0.9120, 0.4050]
            first["extra_points"] = [
                [0.9000, 0.3900],
                [0.9120, 0.4250],
                [0.9250, 0.4050],
            ]
            first["click_interval_seconds"] = 0.25
            first["wait_seconds"] = 1.0
            result["navigation"] = [first]
        version = 3
    if version < 4:
        result["version"] = 4
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first.pop("extra_points", None)
            first.pop("click_interval_seconds", None)
            first["point"] = [0.9120, 0.4050]
            first["wait_seconds"] = 4.0
            first["click_method"] = "native"
            first["click_count"] = 1
            result["navigation"] = [first]
        version = 4
    if version < 5:
        result["version"] = 5
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "nkas_pyautogui"
            first["wait_seconds"] = 4.0
            first["click_count"] = 1
            result["navigation"] = [first]
        version = 5
    if version < 6:
        result["version"] = 6
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "sendinput"
            first["wait_seconds"] = 4.0
            first["click_count"] = 1
            result["navigation"] = [first]
        version = 6
    if version < 7:
        result["version"] = 7
        version = 7
    if version < 8:
        result["version"] = 8
        version = 8
    if version < 9:
        result["version"] = 9
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "pydirectinput"
            first["press_seconds"] = 0.12
            first["wait_seconds"] = 4.0
            result["navigation"] = [first]
        version = 9
    if version < 10:
        result["version"] = 10
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["point"] = [0.9120, 0.3950]
            first["click_method"] = "sampler_pyautogui"
            first["press_seconds"] = 0.10
            first["wait_seconds"] = 4.0
            first["click_count"] = 1
            result["navigation"] = [first]
        version = 10
    if version < 11:
        result["version"] = 11
        result.setdefault("autohotkey_exe", str(DEFAULT_AHK_EXE))
        result.setdefault("autohotkey_script", str(DEFAULT_AHK_SCRIPT))
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "autohotkey"
            first["press_seconds"] = 0.12
            result["navigation"] = [first]
        version = 11
    if version < 12:
        result["version"] = 12
        current_ahk = str(result.get("autohotkey_exe", ""))
        if not current_ahk or current_ahk.endswith("AutoHotkey64_UIA.exe"):
            result["autohotkey_exe"] = str(Path(r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"))
        version = 12
    if version < 13:
        result["version"] = 13
        result["autohotkey_exe"] = str(DEFAULT_AHK_EXE)
        result["autohotkey_elevated"] = True
        version = 13
    if version < 14:
        result["version"] = 14
        result["node_exe"] = str(DEFAULT_NODE_EXE)
        result["zdjl_click_script"] = str(DEFAULT_ZDJL_CLICK_SCRIPT)
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "zdjl"
            first["press_seconds"] = 0.12
            result["navigation"] = [first]
        version = 14
    if version < 15:
        result["version"] = 15
        result["zdjl_task_file"] = str(DEFAULT_ZDJL_TASK_FILE)
        result["zdjl_result_file"] = str(DEFAULT_ZDJL_RESULT_FILE)
        result["zdjl_task_status"] = "pending_image_click"
        result["zdjl_wait_seconds"] = 8.0
        version = 15
    if version < 16:
        result["version"] = 16
        result["require_admin"] = True
        navigation = result.get("navigation")
        if isinstance(navigation, list) and navigation:
            first = dict(navigation[0])
            first["click_method"] = "sampler_pyautogui"
            first["press_seconds"] = 0.18
            first["wait_seconds"] = 4.0
            first["click_count"] = 1
            result["navigation"] = [first]
        version = 16
    if version < 17:
        result["version"] = 17
        navigation = result.get("navigation")
        first_step = DEFAULT_CONFIG_DATA["navigation"][0]
        if isinstance(navigation, list) and navigation:
            first_step = dict(navigation[0])
        result["navigation"] = [
            first_step,
            dict(DEFAULT_CONFIG_DATA["navigation"][1]),
        ]
        result["boss_capture"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["boss_capture"], ensure_ascii=False)
        )
        version = 17
    if version < 18:
        result["version"] = 18
        navigation = result.get("navigation")
        first_step = DEFAULT_CONFIG_DATA["navigation"][0]
        if isinstance(navigation, list) and navigation:
            first_step = dict(navigation[0])
        result["navigation"] = [
            first_step,
            dict(DEFAULT_CONFIG_DATA["navigation"][1]),
        ]
        result["boss_capture"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["boss_capture"], ensure_ascii=False)
        )
        version = 18
    if version < 19:
        result["version"] = 19
        result["boss_capture"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["boss_capture"], ensure_ascii=False)
        )
        result["after_capture_navigation"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["after_capture_navigation"], ensure_ascii=False)
        )
        version = 19
    if version < 20:
        result["version"] = 20
        result["boss_capture"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["boss_capture"], ensure_ascii=False)
        )
        result["after_capture_navigation"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["after_capture_navigation"], ensure_ascii=False)
        )
        version = 20
    if version < 21:
        result["version"] = 21
        result["boss_capture"] = json.loads(
            json.dumps(DEFAULT_CONFIG_DATA["boss_capture"], ensure_ascii=False)
        )
        version = 21
    if version < 22:
        result["version"] = 22
        image_match = dict(result.get("image_match") or {})
        templates = dict(image_match.get("templates") or {})
        default_templates = DEFAULT_CONFIG_DATA["image_match"]["templates"]
        templates["union_entry"] = merge_template_values(
            templates.get("union_entry"),
            default_templates["union_entry"],
        )
        templates["union_raid_entry"] = default_templates["union_raid_entry"]
        templates["union_raid_no_open"] = default_templates["union_raid_no_open"]
        image_match["templates"] = templates

        regions = dict(image_match.get("regions") or {})
        for key, value in DEFAULT_CONFIG_DATA["image_match"]["regions"].items():
            regions.setdefault(key, value)
        image_match["regions"] = regions
        image_match.setdefault("scales", DEFAULT_CONFIG_DATA["image_match"]["scales"])
        image_match.setdefault("stride", DEFAULT_CONFIG_DATA["image_match"]["stride"])
        result["image_match"] = image_match

        navigation = result.get("navigation")
        if isinstance(navigation, list) and len(navigation) >= 2:
            raid_step = dict(navigation[1])
            raid_step.setdefault("image_template", "union_raid_entry")
            raid_step.setdefault("blocked_template", "union_raid_no_open")
            raid_step.setdefault(
                "blocked_message",
                "联盟突袭入口未开放或处于锁定状态，已停止查询。",
            )
            navigation[1] = raid_step
            result["navigation"] = navigation
        version = 22
    if version < 23:
        result["version"] = 23
        image_match = dict(result.get("image_match") or {})
        templates = dict(image_match.get("templates") or {})
        default_templates = DEFAULT_CONFIG_DATA["image_match"]["templates"]
        templates["union_entry"] = merge_template_values(
            templates.get("union_entry"),
            default_templates["union_entry"],
        )
        templates["union_raid_entry"] = default_templates["union_raid_entry"]
        templates["union_raid_no_open"] = default_templates["union_raid_no_open"]
        image_match["templates"] = templates

        regions = dict(image_match.get("regions") or {})
        regions["union_entry"] = DEFAULT_CONFIG_DATA["image_match"]["regions"]["union_entry"]
        regions["union_raid_entry"] = DEFAULT_CONFIG_DATA["image_match"]["regions"]["union_raid_entry"]
        regions["union_raid_no_open"] = DEFAULT_CONFIG_DATA["image_match"]["regions"]["union_raid_no_open"]
        image_match["regions"] = regions
        image_match["scales"] = DEFAULT_CONFIG_DATA["image_match"]["scales"]
        image_match["stride"] = DEFAULT_CONFIG_DATA["image_match"]["stride"]
        result["image_match"] = image_match

        navigation = result.get("navigation")
        if isinstance(navigation, list) and len(navigation) >= 2:
            raid_step = dict(navigation[1])
            raid_step["image_template"] = "union_raid_entry"
            raid_step["blocked_template"] = "union_raid_no_open"
            raid_step["blocked_message"] = "联盟突袭入口未开放或处于锁定状态，已停止查询。"
            navigation[1] = raid_step
            result["navigation"] = navigation
        version = 23
    if version < 24:
        result["version"] = 24
        image_match = dict(result.get("image_match") or {})
        templates = dict(image_match.get("templates") or {})
        default_templates = DEFAULT_CONFIG_DATA["image_match"]["templates"]
        templates["union_entry"] = merge_template_values(
            templates.get("union_entry"),
            default_templates["union_entry"],
        )
        templates["union_raid_entry"] = default_templates["union_raid_entry"]
        templates["union_raid_no_open"] = default_templates["union_raid_no_open"]
        image_match["templates"] = templates
        result["image_match"] = image_match
    return result


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_template_values(*values: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item is None or item == "":
                continue
            if isinstance(item, dict):
                key_value = item.get("path") or item.get("template")
                key = normalize_template_key(key_value) if key_value else json.dumps(item, ensure_ascii=False, sort_keys=True)
            else:
                key = normalize_template_key(item)
            if key in seen:
                if isinstance(item, dict):
                    for index, current in enumerate(merged):
                        current_key = (
                            normalize_template_key(current.get("path") or current.get("template"))
                            if isinstance(current, dict)
                            else normalize_template_key(current)
                        )
                        if current_key == key:
                            merged[index] = item
                            break
                continue
            seen.add(key)
            merged.append(item)
    return merged


def normalize_template_key(value: Any) -> str:
    return str(value).replace("\\", "/").lower()


def validate_point(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) < 2:
        raise RuntimeError(f"尚未校准“{name}”坐标，请先运行 calibrate。")
    point = [float(value[0]), float(value[1])]
    if not all(0.0 <= item <= 1.0 for item in point):
        raise RuntimeError(f"“{name}”坐标超出窗口范围，请重新校准。")
    return point


def find_game_window(config: dict[str, Any]) -> WindowInfo | None:
    process_name = str(config.get("process_name", "")).strip().lower()
    if process_name:
        for window in list_windows():
            if window_process_name(window.hwnd).lower() == process_name:
                return window

    sampler_config = load_sampler_config(DEFAULT_SAMPLER_CONFIG)
    configured = str(config.get("window_title", "")).strip()
    keywords = [configured] if configured else list(
        sampler_config.get("window_title_keywords") or []
    )
    for keyword in keywords:
        keyword = str(keyword).strip().lower()
        if not keyword:
            continue
        for window in list_windows():
            if keyword in window.title.lower():
                return window
    return None


def window_process_name(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""
        handle = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def start_game_if_needed(config: dict[str, Any]) -> None:
    executable = str(config.get("game_executable", "")).strip()
    if not executable:
        return
    path = Path(os.path.expandvars(executable)).expanduser()
    if not path.exists():
        raise RuntimeError(f"游戏启动程序不存在：{path}")
    arguments = [str(item) for item in config.get("game_arguments", [])]
    subprocess.Popen(
        [str(path), *arguments],
        cwd=str(path.parent),
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    time.sleep(max(0.0, float(config.get("startup_wait_seconds", 12.0))))


def wait_for_game_window(config: dict[str, Any]) -> WindowInfo:
    deadline = time.monotonic() + max(
        1.0, float(config.get("window_wait_seconds", 90))
    )
    while time.monotonic() < deadline:
        window = find_game_window(config)
        if window and window.title:
            return window
        time.sleep(1.0)
    raise RuntimeError(
        "未找到 NIKKE 游戏窗口。请先启动游戏，或在配置中填写 game_executable。"
    )


def capture_progress(
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> QueryResult:
    config = load_config(config_path)
    if bool(config.get("require_admin", True)) and not is_running_as_admin():
        raise RuntimeError(
            "当前机器人不是管理员权限。请右键/双击启动脚本并在 UAC 弹窗中选择“是”，"
            "否则 Windows 可能会拦截对 NIKKE 的点击。"
        )
    window = find_game_window(config)
    if not window or not window.title:
        start_game_if_needed(config)
        window = wait_for_game_window(config)

    focus_game_window(window.hwnd)
    default_wait = max(0.0, float(config.get("step_wait_seconds", 2.0)))
    for step in config.get("navigation", []):
        name = str(step.get("name", "未命名步骤"))
        execute_click_step(window, config, step, name, default_wait, default_method="sendinput")

    output_dir.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    boss_paths = capture_boss_progress_images(window, config, output_dir, captured_at)
    if boss_paths:
        boss_config = config.get("boss_capture") or {}
        if boss_config.get("send_composite", True):
            image_path = compose_boss_preview(boss_paths, output_dir, captured_at)
        else:
            image_path = boss_paths[-1]
    else:
        image = crop_relative_box(screenshot_window(window), config.get("screenshot_box"))
        filename = datetime.now().strftime("guild_war_progress_%Y%m%d_%H%M%S.png")
        image_path = (output_dir / filename).resolve()
        image.save(image_path)
    run_navigation_steps(window, config, config.get("after_capture_navigation", []), default_wait)
    return QueryResult(
        image_path=image_path,
        window_title=window.title,
        captured_at=captured_at,
        image_paths=[image_path],
    )


def capture_boss_progress_images(
    window: WindowInfo,
    config: dict[str, Any],
    output_dir: Path,
    captured_at: str,
) -> list[Path]:
    boss_config = config.get("boss_capture") or {}
    if not boss_config.get("enabled", False):
        return []
    stages = boss_config.get("stages") or []
    if not isinstance(stages, list) or not stages:
        return []

    pre_navigation = boss_config.get("pre_navigation") or []
    run_navigation_steps(window, config, pre_navigation, default_wait=1.0)

    method = str(boss_config.get("click_method", "sampler_pyautogui")).strip().lower()
    press_seconds = max(0.01, float(boss_config.get("press_seconds", 0.12)))
    wait_seconds = max(0.0, float(boss_config.get("wait_seconds", 1.2)))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths: list[Path] = []
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            continue
        label = str(stage.get("label") or index)
        point = validate_point(stage.get("point"), f"Boss {label}")
        click_game_window(window, point, config=config, method=method, press_seconds=press_seconds)
        time.sleep(wait_seconds)
        image = crop_relative_box(screenshot_window(window), boss_config.get("screenshot_box"))
        safe_label = "".join(ch for ch in label if ch.isalnum()) or str(index)
        path = (output_dir / f"guild_war_boss_{index}_{safe_label}_{timestamp}.png").resolve()
        image.save(path)
        paths.append(path)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Boss {label} 截图已保存：{path}",
            flush=True,
        )
    return paths


def run_navigation_steps(
    window: WindowInfo,
    config: dict[str, Any],
    steps: Any,
    default_wait: float,
) -> None:
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("name", "未命名步骤"))
        condition = step.get("condition")
        if condition and not step_condition_matches(window, condition):
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] 跳过条件步骤：{name}",
                flush=True,
            )
            continue
        execute_click_step(window, config, step, name, default_wait)


def execute_click_step(
    window: WindowInfo,
    config: dict[str, Any],
    step: dict[str, Any],
    name: str,
    default_wait: float,
    default_method: str = "sampler_pyautogui",
) -> None:
    point = validate_point(step.get("point"), name)
    blocked_template = str(step.get("blocked_template") or "")
    if blocked_template and image_match_step_point(window, config, blocked_template, f"{name}-锁定检测"):
        raise RuntimeError(str(step.get("blocked_message") or f"{name} 当前不可点击。"))

    image_template = str(step.get("image_template") or "")
    if image_template:
        point = image_match_step_point(window, config, image_template, name) or point
    method = str(step.get("click_method", default_method)).strip().lower()
    press_seconds = max(0.01, float(step.get("press_seconds", 0.12)))
    click_count = max(1, int(step.get("click_count", 1)))
    for _ in range(click_count):
        click_game_window(window, point, config=config, method=method, press_seconds=press_seconds)
    time.sleep(max(0.0, float(step.get("wait_seconds", default_wait))))


def step_condition_matches(window: WindowInfo, condition: Any) -> bool:
    if not isinstance(condition, dict):
        return True
    condition_type = str(condition.get("type") or "").strip().lower()
    if condition_type == "color_ratio":
        image = screenshot_window(window).convert("RGB")
        region = [float(item) for item in condition.get("region", [])[:4]]
        if len(region) != 4:
            return False
        color = str(condition.get("color") or "").strip().lower()
        threshold = float(condition.get("threshold", 0.08))
        ratio = color_ratio(image, region, color)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] 条件检测："
            f"type=color_ratio color={color} ratio={ratio:.3f} threshold={threshold:.3f}",
            flush=True,
        )
        return ratio >= threshold
    return True


def color_ratio(image: Any, region: list[float], color: str) -> float:
    x1, y1, x2, y2 = region
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        return 0.0
    width, height = image.size
    crop = image.crop(
        (
            round(x1 * width),
            round(y1 * height),
            round(x2 * width),
            round(y2 * height),
        )
    )
    get_pixels = getattr(crop, "get_flattened_data", crop.getdata)
    pixels = list(get_pixels())
    if not pixels:
        return 0.0
    matched = 0
    for red, green, blue in pixels:
        if color == "orange" and red > 190 and 75 <= green <= 175 and blue < 80:
            matched += 1
        elif color == "blue" and blue > 140 and green > 120 and red < 100:
            matched += 1
    return matched / len(pixels)


def compose_boss_preview(image_paths: list[Path], output_dir: Path, captured_at: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    if not image_paths:
        raise RuntimeError("没有可合成的 Boss 截图。")

    images = [Image.open(path).convert("RGB") for path in image_paths]
    labels = ["I", "II", "III", "IV", "V"]
    target_width = max(image.width for image in images)
    padding = 18
    title_height = 46
    row_gap = 14
    widths: list[int] = []
    heights: list[int] = []
    scaled_images = []
    for image in images:
        if image.width != target_width:
            ratio = target_width / max(1, image.width)
            image = image.resize((target_width, round(image.height * ratio)))
        scaled_images.append(image)
        widths.append(image.width)
        heights.append(image.height)

    canvas_width = target_width + padding * 2
    canvas_height = padding + sum(title_height + height + row_gap for height in heights) + padding - row_gap
    canvas = Image.new("RGB", (canvas_width, canvas_height), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    y = padding
    for index, image in enumerate(scaled_images):
        label = labels[index] if index < len(labels) else str(index + 1)
        draw.text((padding, y + 12), f"Boss {label}", fill=(255, 196, 70), font=font)
        y += title_height
        canvas.paste(image, (padding, y))
        y += image.height + row_gap

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = (output_dir / f"guild_war_boss_preview_{timestamp}.png").resolve()
    canvas.save(path)
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Boss 合成预览已保存：{path}",
        flush=True,
    )
    return path


def crop_relative_box(image: Any, box: Any) -> Any:
    if box is None:
        return image
    if not isinstance(box, list) or len(box) < 4:
        raise RuntimeError("screenshot_box 格式错误，应为 [x1, y1, x2, y2]。")
    width, height = image.size
    x1, y1, x2, y2 = [float(value) for value in box[:4]]
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise RuntimeError("screenshot_box 必须是 0 到 1 之间的有效相对区域。")
    return image.crop(
        (
            round(x1 * width),
            round(y1 * height),
            round(x2 * width),
            round(y2 * height),
        )
    )


def click_game_window(
    window: WindowInfo,
    rel_point: list[float],
    config: dict[str, Any],
    method: str = "pydirectinput",
    press_seconds: float = 0.12,
) -> None:
    focus_game_window(window.hwnd)
    x, y = absolute_point(window, rel_point)
    before = get_cursor_pos()
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 点击坐标："
        f"method={method} rel={rel_point} screen=({x},{y}) "
        f"before={before} rect={window.client_rect or window.rect}",
        flush=True,
    )
    if method == "pyautogui":
        pyautogui_click(x, y)
    elif method == "zdjl":
        zdjl_click(config, x, y, press_seconds=press_seconds)
    elif method == "autohotkey":
        autohotkey_click(config, x, y, press_seconds=press_seconds)
    elif method == "sampler_pyautogui":
        sampler_pyautogui_click(x, y, press_seconds=press_seconds)
    elif method == "pydirectinput":
        pydirectinput_click(x, y, press_seconds=press_seconds)
    elif method == "native":
        native_mouse_click(x, y)
    elif method == "postmessage":
        post_message_click(window.hwnd, x, y)
    else:
        sendinput_click(x, y)
        post_message_click(window.hwnd, x, y)
    after = get_cursor_pos()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 点击后鼠标位置：{after}", flush=True)


def is_running_as_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def image_match_step_point(
    window: WindowInfo,
    config: dict[str, Any],
    template_key: str,
    step_name: str,
) -> list[float] | None:
    image_config = config.get("image_match") or {}
    if not image_config.get("enabled", False):
        return None
    specs = template_specs(image_config, template_key)
    if not specs:
        return None

    screenshot = screenshot_window(window).convert("RGB")
    scales = [float(item) for item in image_config.get("scales", [0.90, 1.00, 1.10])]
    stride = max(1, int(image_config.get("stride", 8)))
    best: tuple[int, int, float, Path] | None = None
    missing: list[Path] = []
    for spec in specs:
        if not spec.path.exists():
            missing.append(spec.path)
            continue
        match = locate_template(
            screenshot,
            spec.path,
            threshold=spec.threshold,
            region=spec.region,
            scales=scales,
            stride=stride,
        )
        if not match:
            continue
        x, y, score = match
        if best is None or score > best[2]:
            best = (x, y, score, spec.path)

    for path in missing:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] 识图模板不存在：{path}",
            flush=True,
        )
    if not best:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] 识图未命中：step={step_name} key={template_key}",
            flush=True,
        )
        return None
    x, y, score, template_path = best
    width, height = screenshot.size
    rel = [x / width, y / height]
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 识图命中："
        f"step={step_name} template={template_path.name} "
        f"rel=({rel[0]:.4f},{rel[1]:.4f}) score={score:.3f}",
        flush=True,
    )
    return rel


def template_specs(image_config: dict[str, Any], template_key: str) -> list[TemplateSpec]:
    templates = image_config.get("templates") or {}
    value = templates.get(template_key)
    if value is None:
        return []
    regions = image_config.get("regions") or {}
    default_region = relative_box(regions.get(template_key))
    default_threshold = float(image_config.get("threshold", 0.7))
    items = value if isinstance(value, list) else [value]
    specs: list[TemplateSpec] = []
    for item in items:
        threshold = default_threshold
        region = default_region
        path_value = item
        if isinstance(item, dict):
            path_value = item.get("path") or item.get("template")
            if item.get("threshold") is not None:
                threshold = float(item["threshold"])
            if item.get("region") is not None:
                region = relative_box(item.get("region"))
        if not path_value:
            continue
        specs.append(
            TemplateSpec(
                path=resolve_workspace_path(Path(str(path_value))),
                threshold=threshold,
                region=region,
            )
        )
    return specs


def relative_box(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    region = [float(item) for item in value[:4]]
    if not (0.0 <= region[0] < region[2] <= 1.0 and 0.0 <= region[1] < region[3] <= 1.0):
        return None
    return region


def locate_template(
    screenshot: Any,
    template_path: Path,
    threshold: float,
    region: list[float] | None = None,
    scales: list[float] | None = None,
    stride: int = 8,
) -> tuple[int, int, float] | None:
    try:
        import numpy as np
    except Exception as exc:
        print(f"numpy 不可用，跳过识图：{exc}", flush=True)
        return None

    template_image = read_image(template_path)
    full_width, full_height = screenshot.size
    offset_x = 0
    offset_y = 0
    search_image = screenshot
    if region:
        x1, y1, x2, y2 = region
        offset_x = round(x1 * full_width)
        offset_y = round(y1 * full_height)
        search_image = screenshot.crop(
            (
                offset_x,
                offset_y,
                round(x2 * full_width),
                round(y2 * full_height),
            )
        )

    scale_values = scales or [0.90, 1.00, 1.10]
    cv2_match = locate_template_cv2(search_image, template_image, offset_x, offset_y, scale_values)
    if cv2_match and cv2_match[2] >= threshold:
        return cv2_match

    template = template_image.convert("RGB")
    search_gray = np.asarray(search_image.convert("L"), dtype=np.float32)
    best: tuple[int, int, int, int, float] | None = None
    for scale in scale_values:
        tw = max(12, round(template.width * scale))
        th = max(12, round(template.height * scale))
        if tw >= search_image.width or th >= search_image.height:
            continue
        tpl = template.resize((tw, th)).convert("L")
        tpl_gray = np.asarray(tpl, dtype=np.float32)
        found = find_best_template(search_gray, tpl_gray, stride=stride)
        if found is None:
            continue
        x, y, score = found
        if best is None or score > best[4]:
            best = (x, y, tw, th, score)
    if best is None or best[4] < threshold:
        return None
    x, y, tw, th, score = best
    return offset_x + x + tw // 2, offset_y + y + th // 2, score


def locate_template_cv2(
    search_image: Any,
    template_image: Any,
    offset_x: int,
    offset_y: int,
    scales: list[float],
) -> tuple[int, int, float] | None:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None

    search = np.asarray(search_image.convert("RGB"))
    search = cv2.cvtColor(search, cv2.COLOR_RGB2GRAY)
    best: tuple[int, int, int, int, float] | None = None
    alpha = template_image.getchannel("A") if template_image.mode == "RGBA" else None
    for scale in scales:
        tw = max(8, round(template_image.width * scale))
        th = max(8, round(template_image.height * scale))
        if tw >= search_image.width or th >= search_image.height:
            continue
        resized = template_image.resize((tw, th))
        template = np.asarray(resized.convert("RGB"))
        template = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
        mask = None
        method = cv2.TM_CCOEFF_NORMED
        if alpha is not None:
            alpha_resized = alpha.resize((tw, th))
            mask = np.asarray(alpha_resized)
            if mask.size and int(mask.max()) > 0:
                method = cv2.TM_CCORR_NORMED
            else:
                mask = None
        result = cv2.matchTemplate(search, template, method, mask=mask)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if best is None or float(max_val) > best[4]:
            best = (int(max_loc[0]), int(max_loc[1]), tw, th, float(max_val))
    if best is None:
        return None
    x, y, tw, th, score = best
    return offset_x + x + tw // 2, offset_y + y + th // 2, score


def read_image(path: Path) -> Any:
    from PIL import Image

    return Image.open(path)


def find_best_template(search_gray: Any, tpl_gray: Any, stride: int = 8) -> tuple[int, int, float] | None:
    import numpy as np

    sh, sw = search_gray.shape
    th, tw = tpl_gray.shape
    if th > sh or tw > sw:
        return None
    tpl = tpl_gray - float(tpl_gray.mean())
    tpl_norm = float(np.sqrt(np.sum(tpl * tpl)))
    if tpl_norm <= 1e-6:
        return None
    best_score = -1.0
    best_xy = (0, 0)
    # The search region is small; stride narrows coarse search before local refinement.
    stride = max(1, int(stride))
    for y in range(0, sh - th + 1, stride):
        for x in range(0, sw - tw + 1, stride):
            patch = search_gray[y : y + th, x : x + tw]
            patch = patch - float(patch.mean())
            denom = float(np.sqrt(np.sum(patch * patch)) * tpl_norm)
            if denom <= 1e-6:
                continue
            score = float(np.sum(patch * tpl) / denom)
            if score > best_score:
                best_score = score
                best_xy = (x, y)
    x, y = best_xy
    for yy in range(max(0, y - 8), min(sh - th, y + 8) + 1, 2):
        for xx in range(max(0, x - 8), min(sw - tw, x + 8) + 1, 2):
            patch = search_gray[yy : yy + th, xx : xx + tw]
            patch = patch - float(patch.mean())
            denom = float(np.sqrt(np.sum(patch * patch)) * tpl_norm)
            if denom <= 1e-6:
                continue
            score = float(np.sum(patch * tpl) / denom)
            if score > best_score:
                best_score = score
                best_xy = (xx, yy)
    return best_xy[0], best_xy[1], best_score


def zdjl_click(config: dict[str, Any], x: int, y: int, press_seconds: float = 0.12) -> None:
    task_file = resolve_workspace_path(
        Path(str(config.get("zdjl_task_file") or DEFAULT_ZDJL_TASK_FILE))
    )
    result_file = resolve_workspace_path(
        Path(str(config.get("zdjl_result_file") or DEFAULT_ZDJL_RESULT_FILE))
    )
    task_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)

    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "status": str(config.get("zdjl_task_status") or "pending_image_click"),
        "x": int(x),
        "y": int(y),
        "duration_ms": max(10, round(press_seconds * 1000)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    result_file.write_text(
        json.dumps({"id": task_id, "status": "waiting"}, ensure_ascii=False),
        encoding="utf-8",
    )
    task_file.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 已写入自动精灵任务："
        f"id={task_id} task={task_file}",
        flush=True,
    )
    wait_for_zdjl_result(
        result_file,
        task_id=task_id,
        timeout=max(1.0, float(config.get("zdjl_wait_seconds", 8.0))),
    )


def resolve_workspace_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def wait_for_zdjl_result(path: Path, task_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_value = ""
    while time.monotonic() < deadline:
        if path.exists():
            last_value = path.read_text(encoding="utf-8-sig").strip()
            if last_value:
                try:
                    result = json.loads(last_value)
                except json.JSONDecodeError:
                    result = {}
                if result.get("id") == task_id:
                    status = str(result.get("status", "")).lower()
                    if status == "done":
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] 自动精灵点击完成：{result}",
                            flush=True,
                        )
                        return
                    if status == "error":
                        raise RuntimeError(
                            f"自动精灵点击失败：{result.get('message') or result}"
                        )
        time.sleep(0.2)
    raise RuntimeError(
        "等待自动精灵点击超时。请确认自动精灵脚本正在运行，并按顺序配置 "
        f"zdjl_wait_task.js -> 点击图片 -> zdjl_mark_done.js。最后结果：{last_value}"
    )


def autohotkey_click(config: dict[str, Any], x: int, y: int, press_seconds: float = 0.12) -> None:
    ahk_exe = Path(str(config.get("autohotkey_exe") or DEFAULT_AHK_EXE))
    ahk_script = Path(str(config.get("autohotkey_script") or DEFAULT_AHK_SCRIPT))
    if not ahk_script.is_absolute():
        ahk_script = Path(__file__).resolve().parent / ahk_script
    if not ahk_exe.exists():
        raise RuntimeError(f"AutoHotkey 可执行文件不存在：{ahk_exe}")
    if not ahk_script.exists():
        raise RuntimeError(f"AutoHotkey 脚本不存在：{ahk_script}")
    process_name = str(config.get("process_name", "nikke.exe"))
    press_ms = max(10, round(press_seconds * 1000))
    result_file = Path(__file__).resolve().parent / "data" / "ahk_click_union.result"
    if result_file.exists():
        result_file.unlink()
    args = [str(ahk_exe), str(ahk_script), process_name, str(int(x)), str(int(y)), str(press_ms), str(result_file)]
    if config.get("autohotkey_elevated", False):
        quoted = " ".join(powershell_quote(arg) for arg in args[1:])
        ps_command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"Start-Process -FilePath {powershell_quote(str(ahk_exe))} -ArgumentList {powershell_quote(quoted)} -Verb RunAs -WindowStyle Hidden",
        ]
        completed = subprocess.run(
            ps_command,
            cwd=str(Path(__file__).resolve().parent),
            timeout=30,
            capture_output=True,
            text=True,
        )
        wait_for_ahk_result(result_file, timeout=15)
    else:
        completed = subprocess.run(
            args,
            cwd=str(Path(__file__).resolve().parent),
            timeout=10,
            capture_output=True,
            text=True,
        )
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] AutoHotkey退出码：{completed.returncode}",
        flush=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"AutoHotkey 点击失败，exit={completed.returncode} stderr={completed.stderr.strip()}"
        )


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def wait_for_ahk_result(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8-sig").strip()
            if value != "0":
                raise RuntimeError(f"AutoHotkey 点击失败，result={value}")
            return
        time.sleep(0.2)
    raise RuntimeError(f"等待 AutoHotkey 结果超时：{path}")


def focus_game_window(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    vk_menu = 0x12
    keyeventf_keyup = 0x0002
    sw_minimize = 6
    sw_restore = 9

    def bypass_foreground_lock() -> None:
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)

    bypass_foreground_lock()
    time.sleep(0.2)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    else:
        user32.ShowWindow(hwnd, sw_restore)
    time.sleep(0.2)
    if user32.SetForegroundWindow(hwnd) == 0:
        bypass_foreground_lock()
        time.sleep(0.2)
        user32.ShowWindow(hwnd, sw_minimize)
        time.sleep(0.2)
        user32.ShowWindow(hwnd, sw_restore)
        time.sleep(0.2)
        user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetActiveWindow(hwnd)
    time.sleep(0.35)


def pyautogui_click(x: int, y: int) -> None:
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.moveTo(int(x), int(y), duration=0.05)
        time.sleep(0.10)
        pyautogui.click(int(x), int(y))
        time.sleep(0.20)
    except Exception:
        native_mouse_click(x, y)


def sampler_pyautogui_click(x: int, y: int, press_seconds: float = 0.10) -> None:
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.moveTo(int(x), int(y), duration=0.35)
        time.sleep(0.35)
        pyautogui.mouseDown()
        time.sleep(press_seconds)
        pyautogui.mouseUp()
    except Exception as exc:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] sampler_pyautogui失败，回退ctypes："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        native_mouse_click(x, y)


def pydirectinput_click(x: int, y: int, press_seconds: float = 0.12) -> None:
    try:
        import pydirectinput

        pydirectinput.PAUSE = 0.05
        pydirectinput.moveTo(int(x), int(y), duration=0.05)
        time.sleep(0.10)
        pydirectinput.mouseDown(button="left")
        time.sleep(press_seconds)
        pydirectinput.mouseUp(button="left")
    except Exception as exc:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] pydirectinput失败，回退SendInput："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        sendinput_click(x, y)


def get_cursor_pos() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def sendinput_click(x: int, y: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    virtual_x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    virtual_y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    virtual_w = max(1, user32.GetSystemMetrics(78) - 1)  # SM_CXVIRTUALSCREEN
    virtual_h = max(1, user32.GetSystemMetrics(79) - 1)  # SM_CYVIRTUALSCREEN
    abs_x = round((int(x) - virtual_x) * 65535 / virtual_w)
    abs_y = round((int(y) - virtual_y) * 65535 / virtual_h)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

    mouse = 0
    move = 0x0001
    absolute = 0x8000
    virtual_desktop = 0x4000
    left_down = 0x0002
    left_up = 0x0004

    events = (INPUT * 3)(
        INPUT(mouse, INPUTUNION(MOUSEINPUT(abs_x, abs_y, 0, move | absolute | virtual_desktop, 0, 0))),
        INPUT(mouse, INPUTUNION(MOUSEINPUT(0, 0, 0, left_down, 0, 0))),
        INPUT(mouse, INPUTUNION(MOUSEINPUT(0, 0, 0, left_up, 0, 0))),
    )
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] SendInput sent={sent} "
        f"virtual=({virtual_x},{virtual_y},{virtual_w},{virtual_h}) abs=({abs_x},{abs_y})",
        flush=True,
    )
    if sent != 3:
        native_mouse_click(x, y)
    if distance(get_cursor_pos(), (int(x), int(y))) > 8:
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.10)
        down_up = (INPUT * 2)(
            INPUT(mouse, INPUTUNION(MOUSEINPUT(0, 0, 0, left_down, 0, 0))),
            INPUT(mouse, INPUTUNION(MOUSEINPUT(0, 0, 0, left_up, 0, 0))),
        )
        sent2 = user32.SendInput(len(down_up), down_up, ctypes.sizeof(INPUT))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SetCursorPos兜底 sent={sent2}", flush=True)
    time.sleep(0.25)


def distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def native_mouse_click(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.10)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.12)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.20)


def post_message_click(hwnd: int, screen_x: int, screen_y: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    point = wintypes.POINT(int(screen_x), int(screen_y))
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    lparam = (int(point.y) << 16) | (int(point.x) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)  # WM_MOUSEMOVE
    user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
    time.sleep(0.08)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
    time.sleep(0.12)


def calibrate(config_path: Path) -> int:
    config = load_config(config_path)
    window = find_game_window(config)
    if not window or not window.title:
        raise RuntimeError("未找到 NIKKE 游戏窗口，请先启动游戏并停留在主界面。")

    print(f"已找到游戏窗口：{window.title}")
    print("校准期间请保持本终端有键盘焦点，只移动鼠标，不要点击游戏。")
    navigation = config.get("navigation", [])
    for step in navigation:
        name = str(step.get("name", "未命名步骤"))
        print(f"请手动把游戏切到可看到“{name}”的页面。")
        print(f"把鼠标悬停在“{name}”中央，然后按 F8。")
        wait_for_hotkey(0x77)
        step["point"] = get_cursor_relative_to_window(window)
        print(f"已记录 {name}：{step['point']}")

    config["navigation"] = navigation
    save_config(config_path, config)
    print(f"校准已保存：{config_path.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIKKE 会战进度截图工具")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init-config", help="创建默认配置")
    sub.add_parser("calibrate", help="通过 F8 记录页面导航坐标")
    sub.add_parser("run", help="进入会战进度页并截图")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if args.command == "init-config":
        save_config(config_path, load_config(config_path))
        print(f"配置文件：{config_path.resolve()}")
        return 0
    if args.command == "calibrate":
        return calibrate(config_path)
    if args.command == "run":
        result = capture_progress(config_path, Path(args.output_dir))
        print(result.image_path)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
