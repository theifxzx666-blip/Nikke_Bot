from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import warnings
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageGrab, ImageOps

from union_member_sampler import UnionSampler, parse_int


warnings.filterwarnings("ignore", category=DeprecationWarning)

DPI_SCALE = 1.0


def enable_dpi_awareness() -> None:
    global DPI_SCALE
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # Per-monitor v2 when available. Fallbacks cover older Windows builds.
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    DPI_SCALE = detect_dpi_scale()


def detect_dpi_scale() -> float:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        dpi_x = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        user32.ReleaseDC(0, hdc)
        if dpi_x:
            return round(dpi_x / 96.0, 4)
    except Exception:
        pass
    return 1.0


enable_dpi_awareness()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


DEFAULT_DB = Path("data") / "union_sample.db"
DEFAULT_OUT_DIR = Path("data") / "auto_samples"
DEFAULT_CONFIG = Path("data") / "union_auto_sampler.config.json"
STABLE_NAVIGATION = {
    "union_button": [0.9065, 0.3924],
    "members_tab": [0.5006, 0.2815],
    "members_tab_box": [0.347, 0.2484, 0.6389, 0.3067],
}


DEFAULT_CONFIG_DATA: dict[str, Any] = {
    "version": 2,
    "window_title_keywords": ["胜利女神", "NIKKE", "新的希望"],
    "navigation": {
        "enabled": True,
        "union_button": None,
        "members_tab": None,
        "click_delay_seconds": 1.4,
        "verify_members_tab": True,
        "members_tab_box": None,
    },
    "capture": {
        "countdown_seconds": 3,
        "select_window_by_click": True,
        "page_wait_seconds": 1.0,
        "max_pages": 12,
        "expected_members": 32,
        "stop_after_no_new_pages": 2,
        "scroll_mode": "single_row",
        "drag_scroll": {"start": [0.50, 0.80], "end": [0.50, 0.42], "duration_seconds": 1.40, "steps": 70},
        "row_nudge_scroll": {"start": [0.50, 0.67], "end": [0.50, 0.645], "duration_seconds": 0.45, "steps": 24},
        "scroll_verify_attempts": 4,
        "member_hash_max_distance": 120,
    },
    "input": {
        "backend": "foreground_cursor",
        "coordinate_conversion": "none",
        "move_pause_seconds": 0.35,
        "move_steps": 24,
        "move_duration_seconds": 0.35,
    },
    "layout": {
        "list": {
            "x": 0.043,
            "y": 0.378,
            "w": 0.908,
            "row_h": 0.096,
            "gap": 0.007,
            "rows": 5,
            "auto_detect_y": True,
            "detect_threshold": 0.86,
            "detect_tolerance_px": 14,
        },
        "fields": {
            "avatar": {"x": 0.020, "y": 0.035, "w": 0.175, "h": 0.920},
            "level": {"x": 0.085, "y": 0.610, "w": 0.065, "h": 0.260},
            "name": {"x": 0.180, "y": 0.455, "w": 0.365, "h": 0.445},
            "power": {"x": 0.580, "y": 0.075, "w": 0.095, "h": 0.330},
            "online": {"x": 0.720, "y": 0.480, "w": 0.160, "h": 0.350},
        },
    },
    "ocr": {
        "engine": "auto",
        "tesseract_path": "",
        "tessdata_dir": "",
        "language": "chi_sim+eng",
        "numeric_language": "eng",
        "psm": 7,
    },
}


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class RowCapture:
    session_id: str
    page_index: int
    row_index: int
    name: str
    raw_name: str
    power: int | None
    level: int | None
    online_text: str
    avatar_hash: str
    row_path: Path
    avatar_path: Path
    name_path: Path
    power_path: Path
    online_path: Path
    level_path: Path
    ocr_engine: str
    ocr_raw: dict[str, str]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def coordinate_diagnostics() -> str:
    parts = [f"dpi_scale={DPI_SCALE}"]
    try:
        import ctypes

        user32 = ctypes.windll.user32
        parts.append(f"screen={user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}")
    except Exception:
        pass
    try:
        import pyautogui

        size = pyautogui.size()
        parts.append(f"pyautogui={size.width}x{size.height}")
    except Exception:
        pass
    try:
        img = ImageGrab.grab()
        parts.append(f"imagegrab={img.width}x{img.height}")
    except Exception:
        pass
    return " ".join(parts)


def is_key_down(vk_code: int) -> bool:
    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)


def check_runtime_controls() -> None:
    if is_key_down(0x72):  # F3
        raise KeyboardInterrupt("用户按下 F3，已停止。")
    if is_key_down(0x71):  # F2
        log("F2 已按下，暂停中；松开 F2 继续，按 F3 停止。")
        while is_key_down(0x71):
            if is_key_down(0x72):
                raise KeyboardInterrupt("用户按下 F3，已停止。")
            time.sleep(0.08)
        log("F2 已松开，继续。")


def controlled_sleep(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        check_runtime_controls()
        time.sleep(min(0.08, max(0.0, end - time.time())))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if not path.exists():
        save_config(path, DEFAULT_CONFIG_DATA)
        return json.loads(json.dumps(DEFAULT_CONFIG_DATA, ensure_ascii=False))
    current = json.loads(path.read_text(encoding="utf-8-sig"))
    merged = deep_merge(DEFAULT_CONFIG_DATA, current)
    if int(current.get("version", 0) or 0) < 2:
        merged["version"] = 2
        merged["window_title_keywords"] = DEFAULT_CONFIG_DATA["window_title_keywords"]
        merged["navigation"]["enabled"] = True
        merged["capture"] = deep_merge(DEFAULT_CONFIG_DATA["capture"], current.get("capture", {}))
    if repair_navigation_config(merged):
        log("检测到无效点击坐标，已自动恢复稳定坐标。")
    if merged != current:
        save_config(path, merged)
    return merged


def valid_rel_point(point: Any) -> bool:
    if not isinstance(point, list) or len(point) < 2:
        return False
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return False
    return 0.02 <= x <= 0.98 and 0.02 <= y <= 0.98


def valid_rel_box(box: Any) -> bool:
    if not isinstance(box, list) or len(box) < 4:
        return False
    try:
        x1, y1, x2, y2 = [float(value) for value in box[:4]]
    except (TypeError, ValueError):
        return False
    return 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0 and (x2 - x1) >= 0.03 and (y2 - y1) >= 0.02


def repair_navigation_config(config: dict[str, Any]) -> bool:
    nav = config.setdefault("navigation", {})
    changed = False
    if not valid_rel_point(nav.get("union_button")):
        nav["union_button"] = list(STABLE_NAVIGATION["union_button"])
        changed = True
    if not valid_rel_point(nav.get("members_tab")):
        nav["members_tab"] = list(STABLE_NAVIGATION["members_tab"])
        changed = True
    if not valid_rel_box(nav.get("members_tab_box")):
        nav["members_tab_box"] = list(STABLE_NAVIGATION["members_tab_box"])
        changed = True
    return changed


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_auto_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            create table if not exists auto_scan_sessions (
                id text primary key,
                started_at text not null,
                source text not null,
                window_title text not null default '',
                window_rect text not null default '',
                config_json text not null default ''
            );

            create table if not exists member_avatar_samples (
                id integer primary key autoincrement,
                session_id text not null,
                member_name text not null,
                raw_name text not null default '',
                avatar_hash text not null,
                page_index integer not null,
                row_index integer not null,
                row_image_path text not null,
                avatar_image_path text not null,
                name_image_path text not null,
                power_image_path text not null,
                online_image_path text not null,
                level_image_path text not null,
                ocr_engine text not null default '',
                ocr_raw_json text not null default '{}',
                created_at text not null,
                unique(session_id, page_index, row_index)
            );

            create index if not exists idx_member_avatar_samples_hash
                on member_avatar_samples(avatar_hash);
            create index if not exists idx_member_avatar_samples_member
                on member_avatar_samples(member_name);
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_session(db_path: Path, session_id: str, source: str, window: WindowInfo | None, config: dict[str, Any]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            insert or replace into auto_scan_sessions(
                id, started_at, source, window_title, window_rect, config_json
            )
            values(?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                now_text(),
                source,
                window.title if window else "",
                json.dumps(window.rect, ensure_ascii=False) if window else "",
                json.dumps(config, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_row(db_path: Path, row: RowCapture) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            insert or replace into member_avatar_samples(
                session_id, member_name, raw_name, avatar_hash, page_index, row_index,
                row_image_path, avatar_image_path, name_image_path, power_image_path,
                online_image_path, level_image_path, ocr_engine, ocr_raw_json, created_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.session_id,
                row.name,
                row.raw_name,
                row.avatar_hash,
                row.page_index,
                row.row_index,
                str(row.row_path),
                str(row.avatar_path),
                str(row.name_path),
                str(row.power_path),
                str(row.online_path),
                str(row.level_path),
                row.ocr_engine,
                json.dumps(row.ocr_raw, ensure_ascii=False),
                now_text(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def detect_row_top_positions(
    image: Image.Image,
    list_x: int,
    list_y: int,
    list_w: int,
    row_h: int,
    gap: int,
    rows: int,
    list_cfg: dict[str, Any],
) -> list[int] | None:
    width, height = image.size
    pitch = row_h + gap
    threshold = float(list_cfg.get("detect_threshold", 0.86))
    tolerance = int(list_cfg.get("detect_tolerance_px", 14))
    scan_left = max(0, list_x + round(list_w * 0.035))
    scan_right = min(width, list_x + list_w - round(list_w * 0.035))
    step = 4
    sample_x = list(range(scan_left, scan_right, step))
    if not sample_x:
        return None

    scan_top = max(0, list_y - max(tolerance * 2, 24))
    scan_bottom = min(height - 1, round(height * 0.92))
    groups: list[list[tuple[float, int]]] = []
    for y in range(scan_top, scan_bottom):
        gray_border = 0
        for x in sample_x:
            r, g, b = image.getpixel((x, y))
            if 175 <= r <= 235 and 175 <= g <= 235 and 175 <= b <= 235 and max(r, g, b) - min(r, g, b) < 18:
                gray_border += 1
        score = gray_border / len(sample_x)
        if score >= threshold:
            if not groups or y - groups[-1][-1][1] > 6:
                groups.append([(score, y)])
            else:
                groups[-1].append((score, y))

    peaks = [max(group)[1] for group in groups]
    if not peaks:
        return None

    min_matches = min(rows, 4)
    for candidate in peaks:
        matched = 0
        for index in range(rows):
            expected = candidate + index * pitch
            if any(abs(peak - expected) <= tolerance for peak in peaks):
                matched += 1
        if matched >= min_matches:
            return [candidate + index * pitch for index in range(rows)]
    return None


def row_rects(image: Image.Image, config: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    list_cfg = config["layout"]["list"]
    width, height = image.size
    list_x = round(list_cfg["x"] * width)
    list_y = round(list_cfg["y"] * height)
    list_w = round(list_cfg["w"] * width)
    row_h = round(list_cfg["row_h"] * height)
    gap = round(list_cfg["gap"] * height)
    rows = int(list_cfg["rows"])
    detected_tops = None
    if list_cfg.get("auto_detect_y", True):
        detected_tops = detect_row_top_positions(image, list_x, list_y, list_w, row_h, gap, rows, list_cfg)
    if detected_tops:
        return [(list_x, y, list_x + list_w, y + row_h) for y in detected_tops]
    return [
        (list_x, list_y + i * (row_h + gap), list_x + list_w, list_y + i * (row_h + gap) + row_h)
        for i in range(rows)
    ]


def rect_from_relative(parent: tuple[int, int, int, int], rel: dict[str, float]) -> tuple[int, int, int, int]:
    x, y, w, h = parent
    return (
        round(x + rel["x"] * w),
        round(y + rel["y"] * h),
        round(x + (rel["x"] + rel["w"]) * w),
        round(y + (rel["y"] + rel["h"]) * h),
    )


def crop_fields(page_img: Image.Image, row_rect: tuple[int, int, int, int], config: dict[str, Any]) -> dict[str, Image.Image]:
    x1, y1, x2, y2 = row_rect
    parent = (x1, y1, x2 - x1, y2 - y1)
    fields = {"row": page_img.crop(row_rect)}
    for name, rel in config["layout"]["fields"].items():
        fields[name] = page_img.crop(rect_from_relative(parent, rel))
    return fields


def image_nonblank_score(img: Image.Image) -> float:
    gray = ImageOps.grayscale(img.resize((32, 32)))
    low, high = gray.getextrema()
    return float(high - low)


def average_hash(img: Image.Image, size: int = 8) -> str:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(img).resize((size, size), Image.Resampling.LANCZOS))
    pixels = list(gray.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


def stable_image_fingerprint(img: Image.Image) -> str:
    return average_hash(ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(img))), size=16)


def member_identity_fingerprint(fields: dict[str, Image.Image]) -> str:
    return "|".join([
        stable_image_fingerprint(fields["avatar"]),
        stable_image_fingerprint(fields["name"]),
        stable_image_fingerprint(fields["power"]),
        stable_image_fingerprint(fields["level"]),
    ])


def hash_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    left_parts = left.split("|")
    right_parts = right.split("|")
    if len(left_parts) != len(right_parts):
        return 10**9
    total = 0
    for a, b in zip(left_parts, right_parts):
        if len(a) != len(b):
            return 10**9
        total += (int(a, 16) ^ int(b, 16)).bit_count()
    return total


def hash_seen(candidate: str, known_hashes: set[str], max_distance: int) -> bool:
    return any(hash_distance(candidate, known) <= max_distance for known in known_hashes)


def save_fields(fields: dict[str, Image.Image], out_dir: Path, session_id: str, page_index: int, row_index: int) -> dict[str, Path]:
    row_dir = out_dir / session_id / f"page_{page_index:02d}" / f"row_{row_index:02d}"
    row_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, img in fields.items():
        path = row_dir / f"{name}.png"
        img.save(path)
        paths[name] = path
    return paths


def preprocess_for_ocr(img: Image.Image, numeric: bool = False) -> Image.Image:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(img))
    gray = ImageOps.autocontrast(gray)
    scale = 4 if numeric else 3
    gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
    if numeric:
        return gray
    return gray.point(lambda p: 255 if p > 155 else 0)


def tesseract_language(config: dict[str, Any], field_name: str) -> str:
    ocr_cfg = config["ocr"]
    if any(key in field_name for key in ("power", "level")):
        return str(ocr_cfg.get("numeric_language", "eng"))
    return str(ocr_cfg.get("language", "chi_sim+eng"))


def tesseract_extra_args(config: dict[str, Any], field_name: str) -> list[str]:
    ocr_cfg = config["ocr"]
    args: list[str] = []
    tessdata_dir = str(ocr_cfg.get("tessdata_dir", "")).strip()
    if tessdata_dir:
        args.extend(["--tessdata-dir", tessdata_dir])
    if any(key in field_name for key in ("power", "level")):
        args.extend(["-c", "tessedit_char_whitelist=0123456789"])
    return args


def ocr_image(img: Image.Image, config: dict[str, Any], temp_dir: Path, field_name: str) -> tuple[str, str]:
    ocr_cfg = config["ocr"]
    engine = str(ocr_cfg.get("engine", "auto")).lower()
    tesseract = str(ocr_cfg.get("tesseract_path", "")).strip() or shutil.which("tesseract")
    if engine in {"none", "off", "disabled"}:
        return "", "none"
    if engine in {"auto", "tesseract"} and tesseract:
        temp_dir.mkdir(parents=True, exist_ok=True)
        image_path = temp_dir / f"ocr_{field_name}_{uuid.uuid4().hex}.png"
        numeric = any(key in field_name for key in ("power", "level"))
        if numeric:
            ImageOps.exif_transpose(img).save(image_path)
        else:
            preprocess_for_ocr(img, numeric=False).save(image_path)
        cmd = [
            tesseract,
            str(image_path),
            "stdout",
            "-l",
            tesseract_language(config, field_name),
            "--psm",
            str(ocr_cfg.get("psm", 7)),
        ]
        cmd.extend(tesseract_extra_args(config, field_name))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
            return normalize_ocr_text(proc.stdout or ""), "tesseract"
        except Exception as exc:
            return "", f"tesseract-error:{type(exc).__name__}"
        finally:
            try:
                image_path.unlink()
            except OSError:
                pass
    return "", "no-ocr-engine"


def normalize_ocr_text(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_name(raw: str) -> str:
    text = normalize_ocr_text(raw).replace("＊", "*").replace("﹡", "*")
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_*·.\- ]+", "", text)
    return text.strip()


def parse_online_text(raw: str) -> str:
    text = normalize_ocr_text(raw)
    text = text.replace("分种", "分钟").replace("分钟前前", "分钟前")
    match = re.search(r"(\d+)\s*(分钟|小时|天)\s*前", text)
    if match:
        return f"{match.group(1)}{match.group(2)}前"
    if "刚" in text:
        return "刚刚"
    if "在线" in text:
        return "在线"
    if "离线" in text:
        return "离线"
    return text


def member_name_from_ocr(raw_name: str, avatar_hash: str) -> str:
    name = clean_name(raw_name)
    if not name:
        return f"待识别-{avatar_hash[:8]}"
    if re.fullmatch(r"\*{2,}", name):
        return f"匿名-{avatar_hash[:8]}"
    return name


def capture_rows_from_image(image: Image.Image, session_id: str, page_index: int, config: dict[str, Any], out_dir: Path) -> list[RowCapture]:
    rows: list[RowCapture] = []
    temp_dir = out_dir / session_id / "_ocr_tmp"
    for row_index, row_rect in enumerate(row_rects(image, config), start=1):
        fields = crop_fields(image, row_rect, config)
        if image_nonblank_score(fields["row"]) < 8:
            continue
        paths = save_fields(fields, out_dir, session_id, page_index, row_index)
        avatar_hash = member_identity_fingerprint(fields)
        name_raw, name_engine = ocr_image(fields["name"], config, temp_dir, f"p{page_index}_r{row_index}_name")
        power_raw, power_engine = ocr_image(fields["power"], config, temp_dir, f"p{page_index}_r{row_index}_power")
        online_raw, online_engine = ocr_image(fields["online"], config, temp_dir, f"p{page_index}_r{row_index}_online")
        level_raw, level_engine = ocr_image(fields["level"], config, temp_dir, f"p{page_index}_r{row_index}_level")
        raw_name = clean_name(name_raw)
        name = member_name_from_ocr(raw_name, avatar_hash)
        ocr_engine = name_engine
        if power_engine != name_engine:
            ocr_engine = f"{name_engine}/{power_engine}"
        rows.append(
            RowCapture(
                session_id=session_id,
                page_index=page_index,
                row_index=row_index,
                name=name,
                raw_name=raw_name,
                power=parse_int(power_raw),
                level=parse_int(level_raw),
                online_text=parse_online_text(online_raw),
                avatar_hash=avatar_hash,
                row_path=paths["row"],
                avatar_path=paths["avatar"],
                name_path=paths["name"],
                power_path=paths["power"],
                online_path=paths["online"],
                level_path=paths["level"],
                ocr_engine=ocr_engine,
                ocr_raw={"name": name_raw, "power": power_raw, "online": online_raw, "level": level_raw},
            )
        )
    try:
        temp_dir.rmdir()
    except OSError:
        pass
    return rows


def page_avatar_hashes(image: Image.Image, config: dict[str, Any]) -> list[str]:
    hashes: list[str] = []
    for row_rect in row_rects(image, config):
        fields = crop_fields(image, row_rect, config)
        if image_nonblank_score(fields["row"]) < 8:
            continue
        hashes.append(member_identity_fingerprint(fields))
    return hashes


def save_rows_to_db(db_path: Path, rows: list[RowCapture], known_hashes: set[str] | None = None, max_distance: int = 0) -> tuple[int, int]:
    sampler = UnionSampler(db_path)
    ensure_auto_tables(db_path)
    inserted = 0
    duplicate = 0
    try:
        for row in rows:
            if known_hashes is not None and hash_seen(row.avatar_hash, known_hashes, max_distance):
                duplicate += 1
            else:
                inserted += 1
                if known_hashes is not None:
                    known_hashes.add(row.avatar_hash)
            note = f"auto avatar={row.avatar_hash} row={row.row_path}"
            if row.raw_name and row.raw_name != row.name:
                note = f"raw_name={row.raw_name}; {note}"
            sampler.upsert_member(row.name, power=row.power, level=row.level, online_text=row.online_text, note=note)
            record_row(db_path, row)
    finally:
        sampler.close()
    return inserted, duplicate


def print_scan_table(rows: list[RowCapture], known_before: set[str]) -> None:
    for row in rows:
        state = "新增" if row.avatar_hash not in known_before else "重复"
        print(
            f"    {state} r{row.row_index}: {row.name} "
            f"战力={row.power or '-'} 等级={row.level or '-'} 在线={row.online_text or '-'} "
            f"头像={row.avatar_hash[:8]} OCR={row.ocr_engine}",
            flush=True,
        )


def scan_image(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    db_path = Path(args.db)
    session_id = args.session or datetime.now().strftime("img_%Y%m%d_%H%M%S")
    ensure_auto_tables(db_path)
    record_session(db_path, session_id, f"image:{args.image}", None, config)
    image = Image.open(args.image).convert("RGB")
    rows = capture_rows_from_image(image, session_id, int(args.page), config, Path(args.out_dir))
    known: set[str] = set()
    save_rows_to_db(db_path, rows, known)
    log(f"图片采样完成：{len(rows)} 行，session={session_id}")
    print_scan_table(rows, set())
    return 0


def scan_game(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config))
        db_path = Path(args.db)
        out_dir = Path(args.out_dir)
        session_id = args.session or datetime.now().strftime("game_%Y%m%d_%H%M%S")
        if args.pick_window or config["capture"].get("select_window_by_click", True):
            window = pick_window_by_user_click()
        else:
            window = find_target_window(args.window_title or "", config)
        if not window:
            raise SystemExit("找不到游戏窗口。请先打开游戏，或用 union_auto_sampler.py windows 查看窗口标题。")

        log("运行控制：按住 F2 暂停，按 F3 立即停止。")
        log(f"坐标诊断：{coordinate_diagnostics()}")
        log(f"目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
        save_target_preview(window, out_dir)
        log(f"本次会话：{session_id}")
        countdown(int(config["capture"].get("countdown_seconds", 3)))
        activate_window(window.hwnd)

        if not args.skip_navigation:
            ensure_navigation_ready(window, config, Path(args.config))
            navigate_to_member_page(window, config)
        else:
            log("已按参数跳过自动导航，请确认当前已经在 联盟 -> 队员 页面。")

        ensure_auto_tables(db_path)
        record_session(db_path, session_id, "game-window", window, config)
        known_hashes: set[str] = set()
        page_signatures: set[str] = set()
        total_rows = 0
        total_new = 0
        no_new_pages = 0
        expected_members = int(args.expected_members or config["capture"].get("expected_members", 0) or 0)
        max_pages = int(args.pages or config["capture"].get("max_pages", 12))
        scroll_mode = str(config["capture"].get("scroll_mode", "single_row")).lower()
        if expected_members > 0 and not args.pages:
            rows_per_page = max(1, int(config["layout"]["list"].get("rows", 5)))
            step_rows = 1 if scroll_mode == "single_row" else max(1, rows_per_page - 1)
            max_pages = max(max_pages, math.ceil(max(0, expected_members - rows_per_page) / step_rows) + 3)
        stop_after_no_new = int(config["capture"].get("stop_after_no_new_pages", 2))
        member_hash_max_distance = int(config["capture"].get("member_hash_max_distance", 0))

        for page_index in range(1, max_pages + 1):
            check_runtime_controls()
            log(f"第 {page_index}/{max_pages} 页：截图中...")
            image = screenshot_window(window)
            page_dir = out_dir / session_id
            page_dir.mkdir(parents=True, exist_ok=True)
            page_path = page_dir / f"page_{page_index:02d}.png"
            image.save(page_path)

            rows = capture_rows_from_image(image, session_id, page_index, config, out_dir)
            page_hashes = [row.avatar_hash for row in rows]
            signature = "|".join(row.avatar_hash for row in rows)
            known_before = set(known_hashes)
            inserted, duplicate = save_rows_to_db(db_path, rows, known_hashes, member_hash_max_distance)
            total_rows += len(rows)
            total_new += inserted

            log(f"第 {page_index} 页：识别行={len(rows)}，新增头像={inserted}，重复头像={duplicate}，截图={page_path}")
            if expected_members > 0:
                log(f"采样进度：唯一成员 {len(known_hashes)}/{expected_members}")
            print_scan_table(rows, known_before)

            if inserted == 0:
                no_new_pages += 1
            else:
                no_new_pages = 0

            if page_index > 1 and signature in page_signatures and (
                scroll_mode != "single_row" or (expected_members > 0 and len(known_hashes) >= expected_members)
            ):
                log("检测到整页重复，停止采样。")
                break
            page_signatures.add(signature)

            if no_new_pages >= stop_after_no_new:
                log(f"连续 {no_new_pages} 页没有新增头像，判断已到底，停止采样。")
                break

            if expected_members > 0 and len(known_hashes) >= expected_members:
                log(f"已采满目标成员数 {expected_members}，停止采样。")
                break

            if page_index >= max_pages:
                break

            log("滚动到下一屏...")
            scroll_to_next_batch(window, config, page_hashes)

        log(f"采样完成：总行数={total_rows}，唯一头像/成员候选={len(known_hashes)}，本次新增={total_new}")
        log(f"数据已写入：{db_path}")
        log("打开校对页：start-union-sampler-web.cmd 或 http://127.0.0.1:8791/")
        return 0
    except KeyboardInterrupt as exc:
        log(str(exc) if str(exc) else "已停止。")
        return 130


def assisted_scan(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config))
        db_path = Path(args.db)
        out_dir = Path(args.out_dir)
        session_id = args.session or datetime.now().strftime("assist_%Y%m%d_%H%M%S")
        interval = float(args.interval)
        max_pages = int(args.pages)

        log("半自动采样模式：脚本不会点击游戏，也不会滚动。")
        log("请先手动进入游戏的 联盟 -> 队员 页面。")
        log("然后保持 CMD 有键盘焦点，把鼠标悬停到游戏窗口内部，按 F8 捕获窗口。")
        window = pick_window_by_user_click()
        if not window:
            raise SystemExit("没有捕获到窗口。")

        log("运行控制：按住 F2 暂停，按 F3 立即停止。")
        save_target_preview(window, out_dir)
        ensure_auto_tables(db_path)
        record_session(db_path, session_id, "assisted-game-window", window, config)

        known_hashes: set[str] = set()
        page_signatures: set[str] = set()
        total_rows = 0
        total_new = 0
        no_new_pages = 0
        stop_after_no_new = int(config["capture"].get("stop_after_no_new_pages", 2))
        member_hash_max_distance = int(config["capture"].get("member_hash_max_distance", 0))

        for page_index in range(1, max_pages + 1):
            check_runtime_controls()
            log(f"第 {page_index}/{max_pages} 页：截图采样中...")
            image = screenshot_window(window)
            page_dir = out_dir / session_id
            page_dir.mkdir(parents=True, exist_ok=True)
            page_path = page_dir / f"page_{page_index:02d}.png"
            image.save(page_path)

            rows = capture_rows_from_image(image, session_id, page_index, config, out_dir)
            signature = "|".join(row.avatar_hash for row in rows)
            known_before = set(known_hashes)
            inserted, duplicate = save_rows_to_db(db_path, rows, known_hashes, member_hash_max_distance)
            total_rows += len(rows)
            total_new += inserted

            log(f"第 {page_index} 页：识别行={len(rows)}，新增头像={inserted}，重复头像={duplicate}，截图={page_path}")
            print_scan_table(rows, known_before)

            if inserted == 0:
                no_new_pages += 1
            else:
                no_new_pages = 0
            if page_index > 1 and signature in page_signatures:
                log("检测到整页重复，停止采样。")
                break
            page_signatures.add(signature)
            if no_new_pages >= stop_after_no_new:
                log(f"连续 {no_new_pages} 页没有新增头像，判断已到底，停止采样。")
                break
            if page_index >= max_pages:
                break

            log(f"请在 {interval:.0f} 秒内手动滚动到下一屏。脚本不会操作鼠标。")
            controlled_sleep(interval)

        log(f"半自动采样完成：总行数={total_rows}，唯一头像/成员候选={len(known_hashes)}，本次新增={total_new}")
        log(f"数据已写入：{db_path}")
        log("打开校对页：start-union-sampler-web.cmd 或 http://127.0.0.1:8791/")
        return 0
    except KeyboardInterrupt as exc:
        log(str(exc) if str(exc) else "已停止。")
        return 130


def countdown(seconds: int) -> None:
    for value in range(seconds, 0, -1):
        check_runtime_controls()
        log(f"{value} 秒后开始，请不要移动游戏窗口...")
        controlled_sleep(1)


def ensure_navigation_ready(window: WindowInfo, config: dict[str, Any], config_path: Path) -> None:
    nav = config.get("navigation") or {}
    if not nav.get("enabled"):
        log("自动导航已关闭，将停留在当前页面采样。")
        return
    if nav.get("union_button") and nav.get("members_tab"):
        return
    log("首次使用需要校准两个点击点。只需校准一次。")
    log("请把鼠标移动到游戏主界面的【联盟】入口图标中央，然后直接按 F8。")
    wait_for_hotkey(0x77)
    union_button = get_cursor_relative_to_window(window)
    log(f"已记录 联盟入口 坐标：{union_button}")
    save_calibration_preview(window, {"union_button": union_button}, Path("data") / "auto_samples", "calibration_union_preview.png")
    log("现在请手动进入联盟页面，把鼠标移动到【队员】页签中央，然后直接按 F8。")
    wait_for_hotkey(0x77)
    members_tab = get_cursor_relative_to_window(window)
    log(f"已记录 队员页签 坐标：{members_tab}")
    log("为了做区块校验，请把鼠标移动到【队员】页签左上角，然后按 F8。")
    wait_for_hotkey(0x77)
    tab_top_left = get_cursor_relative_to_window(window)
    log("请把鼠标移动到【队员】页签右下角，然后按 F8。")
    wait_for_hotkey(0x77)
    tab_bottom_right = get_cursor_relative_to_window(window)
    members_tab_box = normalize_rel_box(tab_top_left, tab_bottom_right)
    log(f"已记录 队员页签区块：{members_tab_box}")
    nav["union_button"] = union_button
    nav["members_tab"] = members_tab
    nav["members_tab_box"] = members_tab_box
    nav["enabled"] = True
    config["navigation"] = nav
    save_config(config_path, config)
    save_calibration_preview(window, nav, Path("data") / "auto_samples", "calibration_members_preview.png")
    log(f"校准已保存：{config_path}")


def navigate_to_member_page(window: WindowInfo, config: dict[str, Any]) -> None:
    nav = config.get("navigation") or {}
    if not nav.get("enabled"):
        return
    union_button = nav.get("union_button")
    members_tab = nav.get("members_tab")
    if not union_button or not members_tab:
        log("自动导航缺少坐标，跳过点击。")
        return
    delay = float(nav.get("click_delay_seconds", 1.4))
    state, score = detect_members_tab_state(window, nav)
    log(f"导航前页面检测：members_tab_state={state} blue_score={score:.3f}")
    if state == "selected":
        log("当前已经在队员页，跳过自动点击。")
        return
    if state == "visible":
        log("当前已经在联盟页面，跳过联盟入口，直接点击队员页签。")
    else:
        log(f"自动点击：联盟入口 rel={union_button} abs={absolute_point(window, union_button)}")
        click_window(window, union_button)
        controlled_sleep(delay)
    log(f"自动点击：队员页签 rel={members_tab} abs={absolute_point(window, members_tab)}")
    click_window(window, members_tab)
    controlled_sleep(delay)
    if nav.get("verify_members_tab", True):
        ok, score = verify_members_tab_selected(window, nav)
        if ok:
            log(f"队员页签区块校验通过：blue_score={score:.3f}")
        else:
            log(f"警告：队员页签区块校验未通过：blue_score={score:.3f}。仍会继续采样，请观察是否点错页面。")


def find_target_window(title_keyword: str, config: dict[str, Any]) -> WindowInfo | None:
    windows = list_windows()
    keywords = [title_keyword] if title_keyword else list(config.get("window_title_keywords") or [])
    for keyword in keywords:
        keyword = keyword.strip().lower()
        if not keyword:
            continue
        for window in windows:
            if keyword in window.title.lower():
                return window
    return foreground_window()


def pick_window_by_user_click() -> WindowInfo | None:
    log("请保持这个 CMD 窗口有键盘焦点，不要点击游戏。")
    log("只把鼠标悬停到游戏窗口内部任意位置，然后按 F8 捕获目标窗口。")
    wait_for_hotkey(0x77)
    window = window_from_cursor()
    if window:
        log(f"已捕获目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
    return window


def window_from_cursor() -> WindowInfo | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    hwnd = user32.WindowFromPoint(point)
    if not hwnd:
        return None
    root = user32.GetAncestor(hwnd, 2)
    if root:
        hwnd = root
    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(hwnd, buff.value, (rect.left, rect.top, rect.right, rect.bottom), get_client_screen_rect(hwnd))


def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    top_left = wintypes.POINT(client.left, client.top)
    bottom_right = wintypes.POINT(client.right, client.bottom)
    user32.ClientToScreen(hwnd, ctypes.byref(top_left))
    user32.ClientToScreen(hwnd, ctypes.byref(bottom_right))
    return (top_left.x, top_left.y, bottom_right.x, bottom_right.y)


def list_windows() -> list[WindowInfo]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    windows: list[WindowInfo] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left > 80 and rect.bottom - rect.top > 80:
            windows.append(WindowInfo(hwnd, buff.value, (rect.left, rect.top, rect.right, rect.bottom), get_client_screen_rect(hwnd)))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return windows


def foreground_window() -> WindowInfo | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(hwnd, buff.value, (rect.left, rect.top, rect.right, rect.bottom), get_client_screen_rect(hwnd))


def activate_window(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    else:
        user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetActiveWindow(hwnd)
    time.sleep(0.25)


def screenshot_window(window: WindowInfo) -> Image.Image:
    left, top, right, bottom = active_rect(window)
    return ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")


def save_target_preview(window: WindowInfo, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "last_target_window.png"
    screenshot_window(window).save(path)
    log(f"目标窗口预览已保存：{path}")


def save_calibration_preview(window: WindowInfo, nav: dict[str, Any], out_dir: Path, filename: str = "calibration_preview.png") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    image = screenshot_window(window)
    draw = ImageDraw.Draw(image)
    w, h = image.size

    def draw_cross(rel: list[float], color: str, label: str) -> None:
        x = round(rel[0] * w)
        y = round(rel[1] * h)
        draw.line((x - 18, y, x + 18, y), fill=color, width=4)
        draw.line((x, y - 18, x, y + 18), fill=color, width=4)
        draw.text((x + 8, y + 8), label, fill=color)

    if nav.get("union_button"):
        draw_cross(nav["union_button"], "red", "union")
    if nav.get("members_tab"):
        draw_cross(nav["members_tab"], "blue", "members")
    if nav.get("members_tab_box"):
        b = nav["members_tab_box"]
        rect = (round(b[0] * w), round(b[1] * h), round(b[2] * w), round(b[3] * h))
        draw.rectangle(rect, outline="lime", width=4)
    path = out_dir / filename
    image.save(path)
    log(f"校准预览已保存：{path}")


def absolute_point(window: WindowInfo, rel_point: list[float]) -> tuple[int, int]:
    left, top, right, bottom = active_rect(window)
    return round(left + rel_point[0] * (right - left)), round(top + rel_point[1] * (bottom - top))


def active_rect(window: WindowInfo) -> tuple[int, int, int, int]:
    return window.client_rect or window.rect


def normalize_rel_box(a: list[float], b: list[float]) -> list[float]:
    x1, y1 = min(a[0], b[0]), min(a[1], b[1])
    x2, y2 = max(a[0], b[0]), max(a[1], b[1])
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def crop_relative_box(image: Image.Image, box: list[float]) -> Image.Image:
    w, h = image.size
    if w <= 0 or h <= 0 or len(box) < 4:
        return Image.new("RGB", (1, 1), "black")
    x1 = max(0, min(w, round(float(box[0]) * w)))
    y1 = max(0, min(h, round(float(box[1]) * h)))
    x2 = max(0, min(w, round(float(box[2]) * w)))
    y2 = max(0, min(h, round(float(box[3]) * h)))
    if x2 <= x1 or y2 <= y1:
        return Image.new("RGB", (1, 1), "black")
    return image.crop((x1, y1, x2, y2))


def blue_score(img: Image.Image) -> float:
    if img.width <= 0 or img.height <= 0:
        return 0.0
    pixels = list(img.convert("RGB").resize((80, 40), Image.Resampling.LANCZOS).getdata())
    if not pixels:
        return 0.0
    blueish = 0
    for r, g, b in pixels:
        if b > 130 and g > 110 and b > r * 1.25:
            blueish += 1
    return blueish / len(pixels)


def dark_tab_score(img: Image.Image) -> float:
    if img.width <= 0 or img.height <= 0:
        return 0.0
    pixels = list(img.convert("RGB").resize((80, 40), Image.Resampling.LANCZOS).getdata())
    if not pixels:
        return 0.0
    dark = 0
    for r, g, b in pixels:
        if r < 85 and g < 85 and b < 90:
            dark += 1
    return dark / len(pixels)


def detect_members_tab_state(window: WindowInfo, nav: dict[str, Any]) -> tuple[str, float]:
    box = nav.get("members_tab_box")
    if not box:
        return "unknown", 0.0
    image = screenshot_window(window)
    crop = crop_relative_box(image, box)
    b_score = blue_score(crop)
    if b_score >= 0.18:
        return "selected", b_score
    d_score = dark_tab_score(crop)
    if d_score >= 0.20:
        return "visible", b_score
    return "unknown", b_score


def verify_members_tab_selected(window: WindowInfo, nav: dict[str, Any]) -> tuple[bool, float]:
    box = nav.get("members_tab_box")
    if not box:
        return True, 1.0
    image = screenshot_window(window)
    crop = crop_relative_box(image, box)
    score = blue_score(crop)
    return score >= 0.18, score


def click_window(window: WindowInfo, rel_point: list[float]) -> None:
    activate_window(window.hwnd)
    x, y = absolute_point(window, rel_point)
    log(f"点击坐标：rel={rel_point} screen=({x},{y}) rect={active_rect(window)}")
    foreground_cursor_click(x, y)


def foreground_cursor_click(x: int, y: int) -> None:
    check_runtime_controls()
    if pyautogui_click(x, y):
        return
    move_cursor_visible(x, y)
    controlled_sleep(float(load_config().get("input", {}).get("move_pause_seconds", 0.35)))
    check_runtime_controls()
    import ctypes

    user32 = ctypes.windll.user32
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    controlled_sleep(0.10)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def pyautogui_click(x: int, y: int) -> bool:
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        x, y = to_pyautogui_point(x, y)
        cfg = load_config().get("input", {})
        duration = max(0.05, float(cfg.get("move_duration_seconds", 0.35)))
        pause = max(0.05, float(cfg.get("move_pause_seconds", 0.35)))
        pyautogui.moveTo(x, y, duration=duration)
        controlled_sleep(pause)
        check_runtime_controls()
        pyautogui.mouseDown()
        controlled_sleep(0.10)
        pyautogui.mouseUp()
        return True
    except Exception as exc:
        log(f"pyautogui 点击失败，回退 ctypes：{type(exc).__name__}: {exc}")
        return False


def move_cursor_visible(x: int, y: int) -> None:
    if pyautogui_move(x, y):
        return
    import ctypes
    from ctypes import wintypes

    cfg = load_config().get("input", {})
    steps = max(1, int(cfg.get("move_steps", 24)))
    duration = max(0.01, float(cfg.get("move_duration_seconds", 0.35)))
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    sx, sy = int(point.x), int(point.y)
    for i in range(1, steps + 1):
        check_runtime_controls()
        t = i / steps
        nx = round(sx + (x - sx) * t)
        ny = round(sy + (y - sy) * t)
        user32.SetCursorPos(nx, ny)
        controlled_sleep(duration / steps)


def pyautogui_move(x: int, y: int) -> bool:
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        x, y = to_pyautogui_point(x, y)
        duration = max(0.05, float(load_config().get("input", {}).get("move_duration_seconds", 0.35)))
        pyautogui.moveTo(x, y, duration=duration)
        return True
    except Exception:
        return False


def drag_scroll_window(window: WindowInfo, config: dict[str, Any], drag_key: str = "drag_scroll") -> None:
    if pynput_drag_scroll(window, config, drag_key):
        return
    import ctypes

    drag = config["capture"].get(drag_key, {})
    start = drag.get("start", [0.50, 0.82])
    end = drag.get("end", [0.50, 0.28])
    duration = float(drag.get("duration_seconds", 0.45))
    steps = max(6, int(drag.get("steps", 24)))
    sx, sy = absolute_point(window, start)
    ex, ey = absolute_point(window, end)
    user32 = ctypes.windll.user32
    move_cursor_visible(sx, sy)
    controlled_sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    for i in range(1, steps + 1):
        check_runtime_controls()
        t = i / steps
        x = round(sx + (ex - sx) * t)
        y = round(sy + (ey - sy) * t)
        user32.SetCursorPos(x, y)
        controlled_sleep(duration / steps)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def pynput_drag_scroll(window: WindowInfo, config: dict[str, Any], drag_key: str = "drag_scroll") -> bool:
    try:
        from pynput.mouse import Button, Controller

        drag = config["capture"].get(drag_key, {})
        start = drag.get("start", [0.50, 0.82])
        end = drag.get("end", [0.50, 0.28])
        duration = float(drag.get("duration_seconds", 0.45))
        steps = max(6, int(drag.get("steps", 24)))
        sx, sy = absolute_point(window, start)
        ex, ey = absolute_point(window, end)
        sx, sy = to_pyautogui_point(sx, sy)
        ex, ey = to_pyautogui_point(ex, ey)
        mouse = Controller()
        mouse.position = (sx, sy)
        controlled_sleep(0.08)
        mouse.press(Button.left)
        for i in range(1, steps + 1):
            check_runtime_controls()
            t = i / steps
            mouse.position = (round(sx + (ex - sx) * t), round(sy + (ey - sy) * t))
            controlled_sleep(duration / steps)
        mouse.release(Button.left)
        return True
    except Exception as exc:
        log(f"pynput 拖拽失败，回退 ctypes：{type(exc).__name__}: {exc}")
        return False


def scroll_to_next_batch(window: WindowInfo, config: dict[str, Any], previous_hashes: list[str]) -> None:
    wait_seconds = float(config["capture"].get("page_wait_seconds", 1.0))
    attempts = max(0, int(config["capture"].get("scroll_verify_attempts", 2)))
    scroll_mode = str(config["capture"].get("scroll_mode", "single_row")).lower()
    max_distance = int(config["capture"].get("member_hash_max_distance", 0))
    log("滚动到下一组成员...")
    drag_scroll_window(window, config, "drag_scroll")
    controlled_sleep(wait_seconds)
    if not previous_hashes:
        return
    previous_set = set(previous_hashes)
    for attempt in range(1, attempts + 1):
        probe = screenshot_window(window)
        current_hashes = page_avatar_hashes(probe, config)
        if scroll_mode == "single_row":
            new_count = sum(1 for item in current_hashes if not hash_seen(item, previous_set, max_distance))
            overlap_count = len(current_hashes) - new_count
            if new_count >= 1:
                log(f"滚动校验通过：单行步进，新增 {new_count} 行，重叠 {overlap_count} 行。")
                return
            log(f"滚动校验：未发现新成员，补滑 {attempt}/{attempts}。")
            drag_scroll_window(window, config, "row_nudge_scroll")
            controlled_sleep(wait_seconds)
            continue
        overlap = sum(1 for item in current_hashes[:2] if hash_seen(item, previous_set, max_distance))
        if overlap <= 1:
            log(f"滚动校验通过：顶部重叠 {overlap} 行，安全采样。")
            return
        log(f"滚动校验：顶部仍有 {overlap} 行旧成员，补滑 {attempt}/{attempts}。")
        drag_scroll_window(window, config, "row_nudge_scroll")
        controlled_sleep(wait_seconds)


def to_pyautogui_point(x: int, y: int) -> tuple[int, int]:
    mode = str(load_config().get("input", {}).get("coordinate_conversion", "none")).lower()
    if mode in {"", "none", "off", "false", "0"}:
        return x, y
    try:
        import pyautogui

        pg = pyautogui.size()
        img = ImageGrab.grab()
        sx = img.width / pg.width if pg.width else 1.0
        sy = img.height / pg.height if pg.height else 1.0
        if abs(sx - 1.0) > 0.02 or abs(sy - 1.0) > 0.02:
            return round(x / sx), round(y / sy)
    except Exception:
        pass
    return x, y


def get_cursor_relative_to_window(window: WindowInfo) -> list[float]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    left, top, right, bottom = active_rect(window)
    x = (point.x - left) / max(1, right - left)
    y = (point.y - top) / max(1, bottom - top)
    return [round(max(0.0, min(1.0, x)), 4), round(max(0.0, min(1.0, y)), 4)]


def wait_for_hotkey(vk_code: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    while user32.GetAsyncKeyState(vk_code) & 0x8000:
        time.sleep(0.03)
    log("等待 F8...")
    while True:
        if user32.GetAsyncKeyState(vk_code) & 0x8000:
            time.sleep(0.12)
            while user32.GetAsyncKeyState(vk_code) & 0x8000:
                time.sleep(0.03)
            return
        time.sleep(0.03)


def print_windows(_args: argparse.Namespace) -> int:
    for window in list_windows():
        print(f"{window.hwnd}\twindow={window.rect}\tclient={active_rect(window)}\t{window.title}")
    return 0


def init_config(args: argparse.Namespace) -> int:
    path = Path(args.config)
    if path.exists() and not args.force:
        log(f"配置已存在：{path}")
        return 0
    save_config(path, DEFAULT_CONFIG_DATA)
    log(f"已创建配置：{path}")
    return 0


def calibrate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    window = find_target_window(args.window_title or "", config)
    if not window:
        raise SystemExit("找不到游戏窗口。请先打开游戏，或用 windows 命令查看窗口标题。")
    log(f"坐标诊断：{coordinate_diagnostics()}")
    log(f"目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
    nav = config.setdefault("navigation", {})
    nav["union_button"] = None
    nav["members_tab"] = None
    nav["members_tab_box"] = None
    nav["enabled"] = True
    save_config(config_path, config)
    activate_window(window.hwnd)
    ensure_navigation_ready(window, config, config_path)
    log("坐标重新校准完成。以后自动采样会直接使用这组坐标。")
    return 0


def test_clicks(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    window = pick_window_by_user_click()
    if not window:
        raise SystemExit("没有捕获到窗口。")
    save_target_preview(window, Path(args.out_dir))
    log(f"坐标诊断：{coordinate_diagnostics()}")
    log(f"目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
    nav = config.get("navigation") or {}
    if not nav.get("union_button") or not nav.get("members_tab"):
        raise SystemExit("还没有保存坐标。请先在菜单里选择 Recalibrate。")
    activate_window(window.hwnd)
    log(f"测试点击联盟入口：rel={nav['union_button']} abs={absolute_point(window, nav['union_button'])}")
    click_window(window, nav["union_button"])
    time.sleep(1.5)
    log(f"测试点击队员页签：rel={nav['members_tab']} abs={absolute_point(window, nav['members_tab'])}")
    click_window(window, nav["members_tab"])
    time.sleep(1.0)
    ok, score = verify_members_tab_selected(window, nav)
    log(f"队员页签蓝色校验：ok={ok} blue_score={score:.3f}")
    log("测试完成。如果游戏没有任何反馈，说明输入方式被窗口拒收或坐标不在目标位置。")
    return 0


def test_clicks_v2(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    window = pick_window_by_user_click()
    if not window:
        raise SystemExit("No target window captured.")
    save_target_preview(window, Path(args.out_dir))
    log(f"坐标诊断：{coordinate_diagnostics()}")
    log(f"目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
    nav = config.get("navigation") or {}
    if not nav.get("union_button") or not nav.get("members_tab"):
        raise SystemExit("No saved coordinates. Please run Recalibrate first.")
    activate_window(window.hwnd)
    navigate_to_member_page(window, config)
    ok, score = verify_members_tab_selected(window, nav)
    log(f"队员页签蓝色校验：ok={ok} blue_score={score:.3f}")
    log("测试完成。")
    return 0


def mouse_self_test(_args: argparse.Namespace) -> int:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    start = (int(point.x), int(point.y))
    log(f"鼠标自检开始。当前位置={start}")
    log("3 秒后鼠标应移动一个小方形轨迹，然后回到原位。按 F3 可停止。")
    countdown(3)
    path = [
        (start[0] + 120, start[1]),
        (start[0] + 120, start[1] + 80),
        (start[0], start[1] + 80),
        start,
    ]
    for target in path:
        check_runtime_controls()
        log(f"移动鼠标到 {target}")
        move_cursor_visible(target[0], target[1])
        controlled_sleep(0.25)
        user32.GetCursorPos(ctypes.byref(point))
        log(f"系统回报当前位置=({int(point.x)}, {int(point.y)})")
    log("鼠标自检结束。如果你肉眼没有看到鼠标移动，说明当前环境阻止了脚本控制光标。")
    return 0


def click_current_test(_args: argparse.Namespace) -> int:
    import ctypes
    from ctypes import wintypes

    log("当前光标点击测试。")
    log("请把鼠标移动到游戏里一个确定能点的按钮上，然后按 F8。")
    wait_for_hotkey(0x77)
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    x, y = int(point.x), int(point.y)
    log(f"将在当前位置点击一次：({x}, {y})")
    controlled_sleep(0.4)
    foreground_cursor_click(x, y)
    log("点击已发送。如果游戏没有任何反馈，说明游戏不接收脚本鼠标点击事件。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIKKE 联盟队员自动采样工具")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init-config", help="创建默认配置")
    init.add_argument("--force", action="store_true")

    sub.add_parser("windows", help="列出当前可见窗口")

    cal = sub.add_parser("calibrate", help="重新校准联盟入口、队员页签和页签区块")
    cal.add_argument("--window-title", default="")

    sub.add_parser("test-clicks", help="捕获窗口后测试已保存的联盟/队员点击坐标")
    sub.add_parser("mouse-test", help="测试脚本是否能移动系统鼠标")
    sub.add_parser("click-current", help="在当前鼠标位置点击一次，用于测试游戏是否接收点击")

    img = sub.add_parser("scan-image", help="从已有队员页截图采样")
    img.add_argument("image")
    img.add_argument("--page", type=int, default=1)
    img.add_argument("--session")

    game = sub.add_parser("scan-game", help="从当前游戏窗口自动采样")
    game.add_argument("--window-title", default="")
    game.add_argument("--pages", type=int)
    game.add_argument("--expected-members", type=int, default=0)
    game.add_argument("--session")
    game.add_argument("--skip-navigation", action="store_true")
    game.add_argument("--pick-window", action="store_true", help="点击游戏窗口来捕获目标窗口")

    assist = sub.add_parser("assist-scan", help="无点击半自动采样：用户手动滚动，脚本定时截图录入")
    assist.add_argument("--pages", type=int, default=20)
    assist.add_argument("--interval", type=float, default=5.0)
    assist.add_argument("--session")

    args = parser.parse_args(argv)
    if args.command == "init-config":
        return init_config(args)
    if args.command == "windows":
        return print_windows(args)
    if args.command == "calibrate":
        return calibrate(args)
    if args.command == "test-clicks":
        return test_clicks_v2(args)
    if args.command == "mouse-test":
        return mouse_self_test(args)
    if args.command == "click-current":
        return click_current_test(args)
    if args.command == "scan-image":
        return scan_image(args)
    if args.command == "scan-game":
        return scan_game(args)
    if args.command == "assist-scan":
        return assisted_scan(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
