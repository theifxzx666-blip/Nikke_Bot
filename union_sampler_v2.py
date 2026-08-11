from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab, ImageOps


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "data" / "union_sampler_v2.config.json"
DEFAULT_OUT = ROOT / "data" / "v2_samples"
DEFAULT_DB = ROOT / "data" / "union_sample_v2.db"


DEFAULTS: dict[str, Any] = {
    "capture": {
        "select_window_by_click": True,
        "countdown_seconds": 2,
        "settle_seconds": 2.0,
        "expected_members": 32,
        "max_pages": 12,
        "stop_after_no_new_pages": 3,
        "open_folder_after_scan": True,
    },
    "scroll": {
        "enabled": True,
        "start": [0.50, 0.80],
        "end": [0.50, 0.42],
        "duration_seconds": 1.40,
        "steps": 70,
        "settle_seconds": 1.20,
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
        "engine": "tesseract",
        "tesseract_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "tessdata_dir": str(ROOT / "data" / "tessdata"),
        "language": "chi_sim+eng",
        "numeric_language": "eng",
        "psm": 7,
    },
    "identity": {
        "distance_threshold": 120,
    },
}


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int]


@dataclass
class MemberRow:
    page: int
    row: int
    identity: str
    name: str
    power: int | None
    level: int | None
    online: str
    paths: dict[str, Path]
    ocr_raw: dict[str, str]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        save_config(DEFAULTS, path)
        return json.loads(json.dumps(DEFAULTS))
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return deep_merge(json.loads(json.dumps(DEFAULTS)), data)


def save_config(config: dict[str, Any], path: Path = DEFAULT_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def enable_dpi_awareness() -> None:
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def active_rect(window: WindowInfo) -> tuple[int, int, int, int]:
    return window.client_rect or window.rect


def get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    p1 = wintypes.POINT(rect.left, rect.top)
    p2 = wintypes.POINT(rect.right, rect.bottom)
    user32.ClientToScreen(hwnd, ctypes.byref(p1))
    user32.ClientToScreen(hwnd, ctypes.byref(p2))
    return (p1.x, p1.y, p2.x, p2.y)


def foreground_window() -> WindowInfo | None:
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
    return WindowInfo(hwnd, buff.value, (rect.left, rect.top, rect.right, rect.bottom), get_client_rect(hwnd))


def pick_window_by_f8() -> WindowInfo | None:
    log("将鼠标悬停到游戏窗口内，按 F8 捕获窗口。")
    wait_for_key(0x77)
    return foreground_window()


def wait_for_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    while True:
        if user32.GetAsyncKeyState(vk) & 0x8000:
            while user32.GetAsyncKeyState(vk) & 0x8000:
                time.sleep(0.03)
            return
        time.sleep(0.03)


def check_stop_keys() -> None:
    user32 = ctypes.windll.user32
    if user32.GetAsyncKeyState(0x72) & 0x8000:  # F3
        raise KeyboardInterrupt("用户按下 F3，停止。")
    while user32.GetAsyncKeyState(0x71) & 0x8000:  # F2
        time.sleep(0.10)


def screenshot_window(window: WindowInfo) -> Image.Image:
    left, top, right, bottom = active_rect(window)
    if right <= left or bottom <= top:
        raise RuntimeError(f"Invalid window rect: {active_rect(window)}")
    return ImageGrab.grab((left, top, right, bottom)).convert("RGB")


def rel_point(window: WindowInfo, point: list[float]) -> tuple[int, int]:
    left, top, right, bottom = active_rect(window)
    return round(left + point[0] * (right - left)), round(top + point[1] * (bottom - top))


def drag(window: WindowInfo, config: dict[str, Any]) -> None:
    import pyautogui

    pyautogui.FAILSAFE = False
    scroll = config["scroll"]
    start = rel_point(window, scroll["start"])
    end = rel_point(window, scroll["end"])
    steps = max(6, int(scroll.get("steps", 40)))
    duration = max(0.05, float(scroll.get("duration_seconds", 1.0)))
    pyautogui.moveTo(*start, duration=0.15)
    time.sleep(0.08)
    pyautogui.mouseDown()
    for i in range(1, steps + 1):
        check_stop_keys()
        t = i / steps
        x = round(start[0] + (end[0] - start[0]) * t)
        y = round(start[1] + (end[1] - start[1]) * t)
        pyautogui.moveTo(x, y, duration=0)
        time.sleep(duration / steps)
    pyautogui.mouseUp()
    time.sleep(float(scroll.get("settle_seconds", 1.0)))


def rect_from_rel(parent: tuple[int, int, int, int], rel: dict[str, float]) -> tuple[int, int, int, int]:
    x, y, w, h = parent
    return (
        round(x + rel["x"] * w),
        round(y + rel["y"] * h),
        round(x + (rel["x"] + rel["w"]) * w),
        round(y + (rel["y"] + rel["h"]) * h),
    )


def detect_row_tops(image: Image.Image, config: dict[str, Any]) -> list[int] | None:
    cfg = config["layout"]["list"]
    if not cfg.get("auto_detect_y", True):
        return None
    width, height = image.size
    list_x = round(cfg["x"] * width)
    list_y = round(cfg["y"] * height)
    list_w = round(cfg["w"] * width)
    row_h = round(cfg["row_h"] * height)
    gap = round(cfg["gap"] * height)
    rows = int(cfg["rows"])
    pitch = row_h + gap
    threshold = float(cfg.get("detect_threshold", 0.86))
    tolerance = int(cfg.get("detect_tolerance_px", 14))

    xs = list(range(list_x + round(list_w * 0.035), list_x + list_w - round(list_w * 0.035), 4))
    if not xs:
        return None
    scan_top = max(0, list_y - max(tolerance * 2, 24))
    scan_bottom = min(height - 1, round(height * 0.92))
    groups: list[list[tuple[float, int]]] = []
    for y in range(scan_top, scan_bottom):
        count = 0
        for x in xs:
            r, g, b = image.getpixel((x, y))
            if 175 <= r <= 235 and 175 <= g <= 235 and 175 <= b <= 235 and max(r, g, b) - min(r, g, b) < 18:
                count += 1
        score = count / len(xs)
        if score >= threshold:
            if not groups or y - groups[-1][-1][1] > 6:
                groups.append([(score, y)])
            else:
                groups[-1].append((score, y))
    peaks = [max(g)[1] for g in groups]
    for candidate in peaks:
        matches = 0
        for index in range(rows):
            expected = candidate + index * pitch
            if any(abs(p - expected) <= tolerance for p in peaks):
                matches += 1
        if matches >= min(rows, 4):
            return [candidate + index * pitch for index in range(rows)]
    return None


def row_rects(image: Image.Image, config: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    cfg = config["layout"]["list"]
    width, height = image.size
    x = round(cfg["x"] * width)
    y = round(cfg["y"] * height)
    w = round(cfg["w"] * width)
    row_h = round(cfg["row_h"] * height)
    gap = round(cfg["gap"] * height)
    rows = int(cfg["rows"])
    tops = detect_row_tops(image, config) or [y + i * (row_h + gap) for i in range(rows)]
    rects = []
    for top in tops:
        bottom = min(height, top + row_h)
        if bottom - top >= row_h * 0.55:
            rects.append((x, top, x + w, bottom))
    return rects


def crop_fields(image: Image.Image, row_rect: tuple[int, int, int, int], config: dict[str, Any]) -> dict[str, Image.Image]:
    x1, y1, x2, y2 = row_rect
    parent = (x1, y1, x2 - x1, y2 - y1)
    fields = {"row": image.crop(row_rect)}
    for key, rel in config["layout"]["fields"].items():
        fields[key] = image.crop(rect_from_rel(parent, rel))
    return fields


def nonblank(img: Image.Image) -> float:
    gray = ImageOps.grayscale(img.resize((32, 32)))
    lo, hi = gray.getextrema()
    return float(hi - lo)


def ahash(img: Image.Image, size: int = 16) -> str:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(img)).resize((size, size), Image.Resampling.LANCZOS)
    pix = list(gray.getdata())
    avg = sum(pix) / len(pix)
    bits = "".join("1" if p >= avg else "0" for p in pix)
    return f"{int(bits, 2):0{size * size // 4}x}"


def identity(fields: dict[str, Image.Image]) -> str:
    # 头像+名称+战力+等级，降低同头像误判。
    return "|".join(ahash(fields[key]) for key in ("avatar", "name", "power", "level"))


def hash_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    pa = a.split("|")
    pb = b.split("|")
    if len(pa) != len(pb):
        return 10**9
    return sum((int(x, 16) ^ int(y, 16)).bit_count() for x, y in zip(pa, pb))


def seen_before(candidate: str, known: list[str], threshold: int) -> bool:
    return any(hash_distance(candidate, item) <= threshold for item in known)


def preprocess_text(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(img))
    gray = ImageOps.autocontrast(gray)
    gray = gray.resize((gray.width * 3, gray.height * 3), Image.Resampling.LANCZOS)
    return gray.point(lambda p: 255 if p > 155 else 0)


def ocr(img: Image.Image, field: str, config: dict[str, Any], temp: Path) -> str:
    cfg = config["ocr"]
    if str(cfg.get("engine", "tesseract")).lower() in {"none", "off"}:
        return ""
    exe = str(cfg.get("tesseract_path") or shutil.which("tesseract") or "")
    if not exe or not Path(exe).exists():
        return ""
    temp.mkdir(parents=True, exist_ok=True)
    path = temp / f"{field}_{uuid.uuid4().hex}.png"
    numeric = field in {"power", "level"}
    if numeric:
        ImageOps.exif_transpose(img).save(path)
    else:
        preprocess_text(img).save(path)
    cmd = [exe, str(path), "stdout", "-l", cfg["numeric_language" if numeric else "language"], "--psm", str(cfg.get("psm", 7))]
    tessdata = str(cfg.get("tessdata_dir", "")).strip()
    if tessdata:
        cmd += ["--tessdata-dir", tessdata]
    if numeric:
        cmd += ["-c", "tessedit_char_whitelist=0123456789"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        return re.sub(r"\s+", " ", result.stdout or "").strip()
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def parse_int(text: str) -> int | None:
    digits = re.sub(r"\D+", "", text or "")
    return int(digits) if digits else None


def normalize_online(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    m = re.search(r"(\d+)(分钟|小时|天)", text)
    if m:
        return f"{m.group(1)}{m.group(2)}前"
    return text


def display_name(raw: str, ident: str) -> str:
    raw = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_*.\- ]+", "", raw or "").strip()
    if not raw:
        return f"pending-{ident[:8]}"
    if re.fullmatch(r"\*{2,}", raw):
        return f"anonymous-{ident[:8]}"
    return raw


def save_fields(fields: dict[str, Image.Image], out_dir: Path, session: str, page: int, row: int) -> dict[str, Path]:
    row_dir = out_dir / session / f"page_{page:02d}" / f"row_{row:02d}"
    row_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, img in fields.items():
        path = row_dir / f"{key}.png"
        img.save(path)
        paths[key] = path
    return paths


def extract_rows(image: Image.Image, config: dict[str, Any], out_dir: Path, session: str, page: int) -> list[MemberRow]:
    rows: list[MemberRow] = []
    temp = out_dir / session / "_ocr_tmp"
    for idx, rect in enumerate(row_rects(image, config), start=1):
        fields = crop_fields(image, rect, config)
        if nonblank(fields["row"]) < 8:
            continue
        ident = identity(fields)
        paths = save_fields(fields, out_dir, session, page, idx)
        raw_name = ocr(fields["name"], "name", config, temp)
        raw_power = ocr(fields["power"], "power", config, temp)
        raw_level = ocr(fields["level"], "level", config, temp)
        raw_online = ocr(fields["online"], "online", config, temp)
        rows.append(
            MemberRow(
                page=page,
                row=idx,
                identity=ident,
                name=display_name(raw_name, ident),
                power=parse_int(raw_power),
                level=parse_int(raw_level),
                online=normalize_online(raw_online),
                paths=paths,
                ocr_raw={"name": raw_name, "power": raw_power, "level": raw_level, "online": raw_online},
            )
        )
    try:
        temp.rmdir()
    except OSError:
        pass
    return rows


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table if not exists member_samples (
              session text, page integer, row integer, identity text,
              name text, power integer, level integer, online text,
              row_path text, avatar_path text, name_path text, power_path text,
              online_path text, level_path text, ocr_raw text, created_at text,
              unique(session, page, row)
            )
            """
        )


def save_rows(path: Path, rows: list[MemberRow]) -> None:
    init_db(path)
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(path) as conn:
        for row in rows:
            conn.execute(
                """
                insert or replace into member_samples values
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.paths["row"].parts[-4],
                    row.page,
                    row.row,
                    row.identity,
                    row.name,
                    row.power,
                    row.level,
                    row.online,
                    str(row.paths["row"]),
                    str(row.paths["avatar"]),
                    str(row.paths["name"]),
                    str(row.paths["power"]),
                    str(row.paths["online"]),
                    str(row.paths["level"]),
                    json.dumps(row.ocr_raw, ensure_ascii=False),
                    now,
                ),
            )


def scan_game(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    out_dir = Path(args.out_dir)
    db_path = Path(args.db)
    session = args.session or datetime.now().strftime("game_%Y%m%d_%H%M%S")
    window = pick_window_by_f8() if config["capture"].get("select_window_by_click", True) else foreground_window()
    if not window:
        raise SystemExit("No window captured.")
    log(f"窗口: {window.title} client={active_rect(window)}")
    for sec in range(int(config["capture"].get("countdown_seconds", 2)), 0, -1):
        log(f"{sec} 秒后开始采样。请确认已经在 联盟 -> 队员 页面。")
        time.sleep(1)

    known: list[str] = []
    threshold = int(config["identity"].get("distance_threshold", 120))
    expected = int(config["capture"].get("expected_members", 32))
    max_pages = int(args.pages or config["capture"].get("max_pages", 12))
    if not args.pages and expected:
        max_pages = max(max_pages, expected)
    no_new = 0
    stop_no_new = int(config["capture"].get("stop_after_no_new_pages", 3))

    for page in range(1, max_pages + 1):
        check_stop_keys()
        time.sleep(float(config["capture"].get("settle_seconds", 2.0)))
        image = screenshot_window(window)
        session_dir = out_dir / session
        session_dir.mkdir(parents=True, exist_ok=True)
        page_path = session_dir / f"page_{page:02d}.png"
        image.save(page_path)
        rows = extract_rows(image, config, out_dir, session, page)
        save_rows(db_path, rows)

        inserted = 0
        for row in rows:
            if not seen_before(row.identity, known, threshold):
                known.append(row.identity)
                inserted += 1
        if inserted:
            no_new = 0
        else:
            no_new += 1
        log(f"page {page}/{max_pages}: rows={len(rows)} new={inserted} total={len(known)}/{expected} image={page_path}")
        for row in rows:
            state = "new" if not seen_before(row.identity, known[:-inserted] if inserted else known, threshold) else "seen"
            log(f"  {state} r{row.row}: {row.name} power={row.power or '-'} level={row.level or '-'} online={row.online or '-'}")
        if expected and len(known) >= expected:
            log("目标成员数已采满。")
            break
        if no_new >= stop_no_new:
            log("连续无新增，停止。")
            break
        if page >= max_pages or not config["scroll"].get("enabled", True):
            break
        log("滚动到下一屏...")
        drag(window, config)

    if config["capture"].get("open_folder_after_scan", True):
        subprocess.Popen(["explorer", str(out_dir / session)])
    return 0


def scan_image(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    session = args.session or datetime.now().strftime("img_%Y%m%d_%H%M%S")
    image = Image.open(args.image).convert("RGB")
    rows = extract_rows(image, config, Path(args.out_dir), session, int(args.page))
    save_rows(Path(args.db), rows)
    for row in rows:
        log(f"r{row.row}: {row.name} power={row.power or '-'} level={row.level or '-'} online={row.online or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("init")
    game = sub.add_parser("scan-game")
    game.add_argument("--pages", type=int)
    game.add_argument("--session")
    img = sub.add_parser("scan-image")
    img.add_argument("image")
    img.add_argument("--page", type=int, default=1)
    img.add_argument("--session")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        save_config(load_config(Path(args.config)), Path(args.config))
        log(f"配置已写入: {args.config}")
        return 0
    if args.cmd == "scan-game":
        return scan_game(args)
    if args.cmd == "scan-image":
        return scan_image(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
