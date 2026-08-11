from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from guild_war_bot.union_suite import DEFAULT_DB_PATH, UnionRaidSuite, raid_day_date


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = ROOT / "data" / "raid_day_samples"
DEFAULT_DEBUG_DIR = ROOT / "data" / "flow1_debug"
DEFAULT_SOURCE = "flow1_sampler"
DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
DEFAULT_TESSDATA = ROOT / "data" / "tessdata"
DEFAULT_ALIAS_PATH = ROOT / "data" / "flow1_name_aliases.json"
DEFAULT_SAMPLE_DB_PATH = ROOT / "data" / "union_sample.db"
DEFAULT_WECHAT_OCR_PACKAGE_DIR = Path(r"D:\Codex\Hard\wechat_ocr_pkg")
DEFAULT_WECHAT_OCR_WECHAT_DIRS = [
    Path(r"S:\[Chat]Tencent\Weixin\4.1.9.62"),
    Path(r"S:\[Chat]Tencent\QQ\versions\9.9.26-44725\resources\app"),
]
DEFAULT_WECHAT_OCR_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Tencent" / "WeChat" / "XPlugin" / "Plugins" / "WeChatOCR" / "7079" / "extracted",
    Path(os.environ.get("APPDATA", "")) / "Tencent" / "xwechat" / "xplugin" / "Plugins" / "WeChatOcr" / "8082" / "extracted",
]
DEFAULT_ASSET_ROOT = Path("D:/Codex") / "\u4f9d\u8d56" / "Nikke\u7d20\u6750\u91c7\u6837" / "\u8054\u76df\u91c7\u6837"
DEFAULT_RAID_ASSET_DIR = DEFAULT_ASSET_ROOT / "\u8054\u76df\u7a81\u88ad"
DEFAULT_FLOW1_ASSET_DIR = DEFAULT_RAID_ASSET_DIR / "\u91c7\u96c6\u94fe\u8def1"
OPERATION_LOG_PATH: Path | None = None
DEFAULT_DAMAGE_VALUES = [
    "2,354,369,175",
    "1,538,157,240",
    "1,569,579,475",
    "1,118,659,860",
    "1,677,989,700",
    "2,354,369,175",
]
DEFAULT_BOSS_NAMES = [
    "\u514b\u62c9\u80af",
    "\u666e\u62c9\u7279",
    "\u94c1\u5320",
    "\u5929\u8f89",
    "\u6b93\u5dfe",
    "\u514b\u62c9\u80af",
]
CHAR_TIE_PRIORITY = {
    "0": 0,
    "6": 1,
    "8": 2,
    "9": 3,
    "3": 4,
    "5": 5,
    "2": 6,
    "4": 7,
    "7": 8,
    "1": 9,
    ",": 10,
}


@dataclass(frozen=True)
class MemberCandidate:
    id: int
    name: str
    active: bool
    group_card: str = ""


@dataclass
class RaidDayRecord:
    session_id: str
    page_index: int
    row_index: int
    raid_day: int | None
    battle_date: str
    member_raw: str
    member_name: str
    member_id: int | None
    member_match: str
    boss_raw: str
    boss_name: str
    boss_level: int | None
    boss_label: str
    damage: int | None
    damage_raw: str
    damage_method: str
    row_hash: str
    row_image_path: str
    field_image_paths: dict[str, str] = field(default_factory=dict)
    ocr_raw: dict[str, str] = field(default_factory=dict)


class WeChatOCRClient:
    def __init__(
        self,
        package_dir: Path = DEFAULT_WECHAT_OCR_PACKAGE_DIR,
        wechat_dir: Path | None = None,
        ocr_dir: Path | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.package_dir = package_dir
        self.wechat_dir = wechat_dir or first_existing_dir(DEFAULT_WECHAT_OCR_WECHAT_DIRS, "mmmojo_64.dll")
        self.ocr_dir = ocr_dir or first_existing_dir(DEFAULT_WECHAT_OCR_DIRS, "WeChatOCR.exe")
        self.timeout = timeout
        self.manager: Any = None
        self.results: dict[str, dict[str, Any]] = {}
        self.events: dict[str, threading.Event] = {}
        self.available = False
        self.error = ""

    def start(self) -> bool:
        if self.available:
            return True
        try:
            if not self.package_dir.exists():
                raise FileNotFoundError(f"wechat_ocr package dir not found: {self.package_dir}")
            if str(self.package_dir) not in sys.path:
                sys.path.insert(0, str(self.package_dir))
            from wechat_ocr.ocr_manager import OcrManager

            self.manager = OcrManager(str(self.wechat_dir))
            self.manager.SetExePath(str(self.ocr_dir / "WeChatOCR.exe"))
            self.manager.SetUsrLibDir(str(self.wechat_dir))
            self.manager.SetOcrResultCallback(self._callback)
            self.manager.StartWeChatOCR()
            deadline = time.time() + self.timeout
            while not self.manager.m_connect_state.value and time.time() < deadline:
                time.sleep(0.1)
            if not self.manager.m_connect_state.value:
                raise TimeoutError(f"WeChat OCR service did not connect within {self.timeout:.1f}s")
            self.available = True
            log_step(f"wechat_ocr=enabled wechat_dir={self.wechat_dir} ocr_dir={self.ocr_dir}")
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.available = False
            log_step(f"wechat_ocr=disabled error={self.error}")
            self.stop()
            return False

    def stop(self) -> None:
        if self.manager is not None:
            try:
                self.manager.KillWeChatOCR()
            except Exception:
                pass
        self.manager = None
        self.available = False

    def recognize(self, image_path: Path) -> tuple[str, dict[str, Any]]:
        if not self.available and not self.start():
            return "", {}
        assert self.manager is not None
        key = str(image_path.resolve())
        event = threading.Event()
        self.events[key] = event
        try:
            self.manager.DoOCRTask(key)
            event.wait(self.timeout)
            payload = self.results.pop(key, {})
            text_value = collect_wechat_ocr_text(payload)
            return text_value, payload
        except Exception as exc:
            log_step(f"wechat_ocr_task_error image={image_path} error={type(exc).__name__}: {exc}")
            return "", {}
        finally:
            self.events.pop(key, None)

    def _callback(self, image_path: str, payload: dict[str, Any]) -> None:
        key = str(Path(image_path).resolve())
        self.results[key] = payload
        event = self.events.get(key)
        if event:
            event.set()


def first_existing_dir(candidates: list[Path], required_name: str) -> Path:
    for path in candidates:
        if (path / required_name).exists():
            return path
    raise FileNotFoundError(
        f"{required_name} not found. searched=" + "; ".join(str(path) for path in candidates)
    )


def collect_wechat_ocr_text(payload: dict[str, Any]) -> str:
    rows = payload.get("ocrResult") or []
    texts: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            value = clean_label(item.get("text", ""))
            if value:
                texts.append(value)
    return " ".join(texts).strip()


class DamageTemplateOCR:
    def __init__(self) -> None:
        self.templates: dict[str, list[tuple[int, ...]]] = {}

    @classmethod
    def from_default_reference(cls) -> "DamageTemplateOCR | None":
        image_path = default_flow1_damage_image()
        if not image_path.exists():
            return None
        reader = cls()
        reader.add_training_image(image_path, DEFAULT_DAMAGE_VALUES)
        return reader if reader.templates else None

    def add_training_image(self, image_path: Path, values: list[str]) -> None:
        image = Image.open(image_path).convert("RGB")
        rows = detect_record_rows(image)
        for row_rect, value in zip(rows, values):
            damage_crop = trim_damage_icon(crop_relative(image, row_rect, FIELD_RECTS["damage"]))
            segments = segment_damage_chars(damage_crop)
            if len(segments) != len(value):
                continue
            for char_box, char in zip(segments, value):
                self.templates.setdefault(char, []).append(char_signature(damage_crop, char_box))

    def read(self, crop: Image.Image) -> tuple[str, str]:
        if not self.templates:
            return "", "template-unavailable"
        crop = trim_damage_icon(crop)
        best_text = ""
        best_score = 10**9
        best_average = 0.0
        best_threshold = 0
        candidate_texts: list[str] = []
        for threshold in (100, 110, 90, 120, 80, 130, 70, 140):
            segments = segment_damage_chars(crop, threshold=threshold)
            if len(segments) < 5:
                continue
            chars: list[str] = []
            total = 0
            for box in segments:
                signature = char_signature(crop, box, threshold=threshold)
                score, char = self.match_char(signature)
                total += score
                chars.append(char)
            text = "".join(chars)
            if text:
                candidate_texts.append(text)
            if not valid_damage_text(text):
                continue
            average = total / max(1, len(chars))
            selection_score = average + abs(threshold - 100)
            if selection_score < best_score:
                best_text = text
                best_score = selection_score
                best_average = average
                best_threshold = threshold
        if best_text:
            best_text = repair_damage_tail(best_text, candidate_texts)
            return best_text, f"template:{best_average:.1f}@{best_threshold}"
        return "", "template-no-match"

    def match_char(self, signature: tuple[int, ...]) -> tuple[int, str]:
        best = (10**9, "?")
        for char, templates in self.templates.items():
            for template in templates:
                score = sum(a != b for a, b in zip(signature, template))
                if score < best[0] or (
                    score == best[0]
                    and CHAR_TIE_PRIORITY.get(char, 99) < CHAR_TIE_PRIORITY.get(best[1], 99)
                ):
                    best = (score, char)
        return best


class BossTemplateMatcher:
    def __init__(self) -> None:
        self.templates: list[tuple[str, str]] = []

    @classmethod
    def from_default_reference(cls) -> "BossTemplateMatcher | None":
        image_path = default_flow1_damage_image()
        if not image_path.exists():
            return None
        matcher = cls()
        matcher.add_training_image(image_path, DEFAULT_BOSS_NAMES)
        return matcher if matcher.templates else None

    def add_training_image(self, image_path: Path, names: list[str]) -> None:
        image = Image.open(image_path).convert("RGB")
        rows = detect_record_rows(image)
        for row_rect, name in zip(rows, names):
            avatar = crop_relative(image, row_rect, FIELD_RECTS["avatar"])
            self.templates.append((name, average_hash(avatar, size=16)))

    def match(self, avatar: Image.Image, max_distance: int = 78) -> str:
        if not self.templates:
            return ""
        candidate = average_hash(avatar, size=16)
        best = (10**9, "")
        for name, template_hash in self.templates:
            distance = hash_distance(candidate, template_hash)
            if distance < best[0]:
                best = (distance, name)
        return best[1] if best[0] <= max_distance else ""


class MemberNameTemplateMatcher:
    def __init__(self) -> None:
        self.templates: list[tuple[MemberCandidate, tuple[int, ...], str]] = []

    @classmethod
    def from_sample_db(
        cls,
        sample_db_path: Path,
        members: list[MemberCandidate],
    ) -> "MemberNameTemplateMatcher | None":
        if not sample_db_path.exists() or not members:
            return None
        matcher = cls()
        try:
            import sqlite3

            conn = sqlite3.connect(sample_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select member_name, raw_name, name_image_path
                from member_avatar_samples
                where trim(coalesce(name_image_path, '')) <> ''
                order by created_at desc
                """
            ).fetchall()
            conn.close()
        except Exception:
            return None

        seen: set[tuple[int, str]] = set()
        for row in rows:
            sample_text = f"{row['member_name'] or ''} {row['raw_name'] or ''}"
            member = resolve_sample_member(sample_text, members)
            if not member:
                continue
            image_path = Path(str(row["name_image_path"] or ""))
            if not image_path.is_absolute():
                image_path = ROOT / image_path
            if not image_path.exists():
                continue
            key = (member.id, str(image_path))
            if key in seen:
                continue
            seen.add(key)
            try:
                signature = text_image_signature(Image.open(image_path).convert("RGB"))
            except Exception:
                continue
            matcher.templates.append((member, signature, str(image_path)))
        return matcher if matcher.templates else None

    def match(
        self,
        crop: Image.Image,
        ocr_candidates: list[str] | None = None,
        max_distance: float = 0.208,
    ) -> MemberCandidate | None:
        if not self.templates:
            return None
        signature = text_image_signature(crop)
        scored = sorted(
            (
                signature_distance(signature, template),
                member.id,
                member,
                path,
            )
            for member, template, path in self.templates
        )
        if not scored:
            return None
        best_score, _best_id, best_member, _path = scored[0]
        if best_score > max_distance:
            return None
        distinct_scores = [
            score for score, _member_id, member, _path in scored
            if member.id != best_member.id
        ]
        next_score = distinct_scores[0] if distinct_scores else 1.0
        if next_score - best_score < 0.035:
            return None
        confident_template_only = best_score <= 0.19 and next_score - best_score >= 0.05
        if not confident_template_only and best_score > 0.135 and ocr_candidates and not any(
            likely_same_member_text(candidate, best_member.name)
            for candidate in ocr_candidates
        ):
            return None
        return MemberCandidate(
            best_member.id,
            best_member.name,
            best_member.active,
            f"name-template:{best_score:.3f}",
        )


FIELD_RECTS = {
    "avatar": (0.02, 0.24, 0.17, 0.92),
    "level": (0.02, 0.00, 0.17, 0.36),
    "member": (0.18, 0.12, 0.50, 0.43),
    "boss": (0.18, 0.54, 0.52, 0.88),
    "damage": (0.54, 0.08, 0.86, 0.47),
}


def default_flow1_damage_image() -> Path:
    return (
        Path("D:/Codex")
        / "\u4f9d\u8d56"
        / "Nikke\u7d20\u6750\u91c7\u6837"
        / "\u8054\u76df\u91c7\u6837"
        / "\u8054\u76df\u7a81\u88ad"
        / "\u91c7\u96c6\u94fe\u8def1"
        / "\u8054\u76df_\u8054\u76df\u7a81\u88ad_\u6d3b\u52a8\u4e3b\u9875_\u8054\u76df\u8bb0\u5f55_\u4f24\u5bb3\u660e\u7ec6.png"
    )


def scan_image(
    image_path: Path,
    db_path: Path,
    battle_date: str,
    raid_day: int | None,
    out_dir: Path,
    session_id: str | None = None,
    page_index: int = 1,
    aliases: dict[str, str] | None = None,
    damage_reader: DamageTemplateOCR | None = None,
    boss_matcher: BossTemplateMatcher | None = None,
    name_matcher: MemberNameTemplateMatcher | None = None,
    wechat_ocr: WeChatOCRClient | None = None,
) -> list[RaidDayRecord]:
    session_id = session_id or f"flow1_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    image = Image.open(image_path).convert("RGB")
    members = load_members(db_path)
    damage_reader = damage_reader or DamageTemplateOCR.from_default_reference()
    boss_matcher = boss_matcher or BossTemplateMatcher.from_default_reference()
    name_matcher = name_matcher or MemberNameTemplateMatcher.from_sample_db(DEFAULT_SAMPLE_DB_PATH, members)
    return capture_records_from_image(
        image=image,
        db_path=db_path,
        battle_date=battle_date,
        raid_day=raid_day,
        out_dir=out_dir,
        session_id=session_id,
        page_index=page_index,
        members=members,
        aliases=aliases if aliases is not None else parse_aliases([]),
        damage_reader=damage_reader,
        boss_matcher=boss_matcher,
        name_matcher=name_matcher,
        wechat_ocr=wechat_ocr,
    )


def capture_records_from_image(
    image: Image.Image,
    db_path: Path,
    battle_date: str,
    raid_day: int | None,
    out_dir: Path,
    session_id: str,
    page_index: int,
    members: list[MemberCandidate] | None = None,
    aliases: dict[str, str] | None = None,
    damage_reader: DamageTemplateOCR | None = None,
    boss_matcher: BossTemplateMatcher | None = None,
    name_matcher: MemberNameTemplateMatcher | None = None,
    wechat_ocr: WeChatOCRClient | None = None,
) -> list[RaidDayRecord]:
    members = members if members is not None else load_members(db_path)
    aliases = aliases if aliases is not None else parse_aliases([])
    damage_reader = damage_reader or DamageTemplateOCR.from_default_reference()
    boss_matcher = boss_matcher or BossTemplateMatcher.from_default_reference()
    name_matcher = name_matcher or MemberNameTemplateMatcher.from_sample_db(DEFAULT_SAMPLE_DB_PATH, members)
    temp_dir = out_dir / session_id / "_ocr_tmp"
    records: list[RaidDayRecord] = []
    for row_index, row_rect in enumerate(detect_record_rows(image), start=1):
        fields = {name: crop_relative(image, row_rect, rel) for name, rel in FIELD_RECTS.items()}
        row_image = image.crop(row_rect)
        if image_nonblank_score(row_image) < 8:
            continue
        paths = save_record_images(row_image, fields, out_dir, session_id, page_index, row_index)
        member_candidates = member_ocr_candidates(
            fields["member"],
            temp_dir,
            f"p{page_index}_r{row_index}_member",
            extended=False,
        )
        member = match_member_candidates(member_candidates, members, aliases)
        if not member:
            member_candidates = member_ocr_candidates(
                fields["member"],
                temp_dir,
                f"p{page_index}_r{row_index}_member",
                extended=True,
                initial_candidates=member_candidates,
            )
            member = match_member_candidates(member_candidates, members, aliases)
        member_wechat_raw = ""
        should_use_wechat = (
            wechat_ocr is not None
            and (
                not member
                or not member_candidates
                or candidate_quality(member_candidates[0]) < 4
                or str(getattr(member, "group_card", "") or "").startswith("fuzzy")
            )
        )
        if should_use_wechat:
            member_wechat_raw, member_wechat_payload = wechat_ocr.recognize(paths["member"])
            if member_wechat_raw:
                add_candidate(member_candidates, member_wechat_raw)
                member_candidates = sorted(
                    member_candidates,
                    key=lambda item: (candidate_quality(item), len(item)),
                    reverse=True,
                )
                member = match_member_candidates(member_candidates, members, aliases)
            if member_wechat_payload:
                log_step(
                    f"wechat_ocr_member page={page_index} row={row_index} text={member_wechat_raw}"
                )
        member_raw = member_candidates[0] if member_candidates else ""
        boss_raw = best_text_ocr(fields["boss"], temp_dir, f"p{page_index}_r{row_index}_boss", prefer_cjk=True)
        level_raw = level_ocr(fields["level"], temp_dir, f"p{page_index}_r{row_index}_level")
        damage_raw, damage_method = read_damage(fields["damage"], temp_dir, f"p{page_index}_r{row_index}_damage", damage_reader)
        if not member and name_matcher:
            member = name_matcher.match(fields["member"], member_candidates)
        boss_name = boss_matcher.match(fields["avatar"]) if boss_matcher else ""
        if not boss_name:
            boss_name = normalize_boss_name(boss_raw)
        boss_level = parse_int(level_raw)
        damage = parse_int(damage_raw)
        records.append(
            RaidDayRecord(
                session_id=session_id,
                page_index=page_index,
                row_index=row_index,
                raid_day=raid_day,
                battle_date=battle_date,
                member_raw=member_raw,
                member_name=member.name if member else clean_label(member_raw),
                member_id=member.id if member else None,
                member_match=member.group_card if member else "unmatched",
                boss_raw=boss_raw,
                boss_name=boss_name,
                boss_level=boss_level,
                boss_label=f"LV{boss_level}" if boss_level is not None else "",
                damage=damage,
                damage_raw=damage_raw,
                damage_method=damage_method,
                row_hash=average_hash(row_image, size=16),
                row_image_path=str(paths["row"]),
                field_image_paths={key: str(path) for key, path in paths.items() if key != "row"},
                ocr_raw={
                    "member": " | ".join(member_candidates),
                    "member_wechat": member_wechat_raw,
                    "boss": boss_raw,
                    "level": level_raw,
                    "damage": damage_raw,
                },
            )
        )
    try:
        temp_dir.rmdir()
    except OSError:
        pass
    return records


def detect_record_rows(image: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = image.size
    pixels = image.load()
    y_hits: list[int] = []
    badge_x_by_y: dict[int, list[int]] = {}
    x_start = max(0, int(width * 0.04))
    x_end = max(x_start + 1, int(width * 0.35))
    min_badge_per_row = max(8, int(width * 0.012))
    for y in range(height):
        xs: list[int] = []
        for x in range(x_start, x_end):
            r, g, b = pixels[x, y]
            is_red = r > 150 and g < 110 and b < 110 and r > g * 1.35 and r > b * 1.35
            is_blue = b > 125 and g > 80 and r < 90 and b > r * 1.5 and g > r * 1.2
            if is_red or is_blue:
                xs.append(x)
        if len(xs) >= min_badge_per_row:
            y_hits.append(y)
            badge_x_by_y[y] = xs

    groups = contiguous_groups(y_hits)
    starts = [start for start, end in groups if end - start >= 8]
    if not starts:
        return []
    diffs = [b - a for a, b in zip(starts, starts[1:]) if 80 <= b - a <= 160]
    spacing = round(statistics.median(diffs)) if diffs else round(height * 0.16)
    rows: list[tuple[int, int, int, int]] = []
    for start in starts:
        badge_xs: list[int] = []
        for y in range(start, min(height, start + 45)):
            badge_xs.extend(badge_x_by_y.get(y, []))
        if not badge_xs:
            continue
        # The day filter can contain a small red "HARD" badge. A real record row
        # has a dense red or blue LEVEL ribbon in the left avatar area.
        if min(badge_xs) > width * 0.25 or len(badge_xs) < max(300, int(width * 0.4)):
            continue
        left = max(0, min(badge_xs) - max(18, int(width * 0.035)))
        if left < width * 0.02:
            continue
        right = min(width, width - left + max(6, int(width * 0.02)))
        top = max(0, start - 8)
        bottom = min(height, top + spacing - 5)
        if bottom - top < 80:
            continue
        if bottom > height:
            continue
        rows.append((left, top, right, bottom))
    return rows


def crop_relative(image: Image.Image, row_rect: tuple[int, int, int, int], rel: tuple[float, float, float, float]) -> Image.Image:
    x1, y1, x2, y2 = row_rect
    width = x2 - x1
    height = y2 - y1
    box = (
        x1 + round(rel[0] * width),
        y1 + round(rel[1] * height),
        x1 + round(rel[2] * width),
        y1 + round(rel[3] * height),
    )
    return image.crop(box)


def segment_damage_chars(crop: Image.Image, threshold: int = 100) -> list[tuple[int, int, int, int]]:
    gray = ImageOps.grayscale(crop)
    width, height = gray.size
    pixels = gray.load()
    columns: list[int] = []
    for x in range(width):
        count = 0
        for y in range(height):
            if pixels[x, y] < threshold:
                count += 1
        columns.append(count)
    groups = []
    for x, count in enumerate(columns):
        if count >= 1:
            if not groups or x > groups[-1][1] + 1:
                groups.append([x, x])
            else:
                groups[-1][1] = x
    boxes: list[tuple[int, int, int, int]] = []
    for start, end in groups:
        xs: list[int] = []
        ys: list[int] = []
        for x in range(start, end + 1):
            for y in range(height):
                if pixels[x, y] < threshold:
                    xs.append(x)
                    ys.append(y)
        if len(xs) < 2:
            continue
        box = (max(0, min(xs) - 1), max(0, min(ys) - 1), min(width, max(xs) + 2), min(height, max(ys) + 2))
        boxes.append(box)
    return boxes


def trim_damage_icon(crop: Image.Image) -> Image.Image:
    segments = segment_damage_chars(crop, threshold=120)
    if len(segments) < 4:
        return crop
    first = segments[0]
    first_width = first[2] - first[0]
    if first_width < max(18, int(crop.width * 0.10)) or first[2] > crop.width * 0.36:
        return crop
    min_gap = max(10, int(crop.width * 0.045))
    for segment in segments[1:]:
        if segment[0] - first[2] >= min_gap:
            left = max(0, segment[0] - 2)
            return crop.crop((left, 0, crop.width, crop.height))
    return crop


def char_signature(crop: Image.Image, box: tuple[int, int, int, int], threshold: int = 100) -> tuple[int, ...]:
    gray = ImageOps.grayscale(crop)
    char = gray.crop(box)
    binary = char.point(lambda pixel: 0 if pixel < threshold else 255)
    resized = binary.resize((16, 24), Image.Resampling.NEAREST)
    return tuple(1 if pixel < 128 else 0 for pixel in resized.tobytes())


def read_damage(
    crop: Image.Image,
    temp_dir: Path,
    field_name: str,
    damage_reader: DamageTemplateOCR | None,
) -> tuple[str, str]:
    crop = trim_damage_icon(crop)
    if damage_reader:
        text, method = damage_reader.read(crop)
        if parse_int(text) is not None:
            return text, method
    text = numeric_ocr(crop, temp_dir, field_name, whitelist="0123456789,")
    return text, "tesseract"


def best_text_ocr(crop: Image.Image, temp_dir: Path, field_name: str, prefer_cjk: bool = False) -> str:
    candidates: list[str] = []
    for threshold in (None, 130, 150, 170):
        text = tesseract_ocr(crop, temp_dir, f"{field_name}_{threshold}", numeric=False, threshold=threshold)
        clean = clean_label(text)
        if clean and clean not in candidates:
            candidates.append(clean)
    if not candidates:
        return ""
    if prefer_cjk:
        return max(candidates, key=lambda item: (count_cjk(item), len(item)))
    return max(candidates, key=lambda item: (has_memberish_ascii(item), len(item)))


def member_ocr_candidates(
    crop: Image.Image,
    temp_dir: Path,
    field_name: str,
    extended: bool = True,
    initial_candidates: list[str] | None = None,
) -> list[str]:
    candidates: list[str] = list(initial_candidates or [])
    for threshold in (None, 130, 150, 170):
        text = tesseract_ocr(crop, temp_dir, f"{field_name}_{threshold}", numeric=False, threshold=threshold)
        add_candidate(candidates, text)
    if not extended:
        return sorted(
            candidates,
            key=lambda item: (candidate_quality(item), len(item)),
            reverse=True,
        )

    gray = ImageOps.grayscale(ImageOps.exif_transpose(crop))
    gray = ImageOps.autocontrast(gray)
    variants: list[tuple[str, Image.Image]] = []
    for scale in (6, 10):
        base = gray.resize((max(1, gray.width * scale), max(1, gray.height * scale)), Image.Resampling.LANCZOS)
        variants.append((f"gray{scale}", base))
        for threshold in (120, 150, 180):
            variants.append((f"bin{scale}_{threshold}", base.point(lambda pixel: 0 if pixel < threshold else 255)))

    for variant_name, image in variants:
        for lang in ("chi_sim+eng", "chi_tra+eng"):
            text = tesseract_prepared_ocr(image, temp_dir, f"{field_name}_{variant_name}_{lang}", lang=lang, psm="7")
            add_candidate(candidates, text)

    return sorted(
        candidates,
        key=lambda item: (candidate_quality(item), len(item)),
        reverse=True,
    )


def add_candidate(candidates: list[str], raw: str) -> None:
    clean = clean_label(raw)
    if clean and clean not in candidates:
        candidates.append(clean)


def candidate_quality(text: str) -> int:
    return count_cjk(text) * 3 + has_memberish_ascii(text) * 2


def numeric_ocr(crop: Image.Image, temp_dir: Path, field_name: str, whitelist: str = "0123456789") -> str:
    return tesseract_ocr(crop, temp_dir, field_name, numeric=True, threshold=None, whitelist=whitelist)


def level_ocr(crop: Image.Image, temp_dir: Path, field_name: str) -> str:
    text = tesseract_level_ocr(crop, temp_dir, field_name)
    value = parse_level_value(text)
    if value is not None and value >= 9:
        return str(value)
    for fallback in level_ocr_variants(crop, temp_dir, field_name):
        fallback_value = parse_level_value(fallback)
        if fallback_value in {0, 1}:
            return "10"
        if fallback_value is not None and 2 <= fallback_value <= 10:
            return str(fallback_value)
    fallback = numeric_ocr(crop, temp_dir, field_name)
    fallback_value = parse_level_value(fallback)
    if fallback_value is not None and fallback_value >= 9:
        return str(fallback_value)
    if value in {0, 1}:
        return "10"
    return str(value) if value is not None else fallback


def level_ocr_variants(crop: Image.Image, temp_dir: Path, field_name: str) -> list[str]:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(crop))
    gray = ImageOps.autocontrast(gray)
    scaled = gray.resize((max(1, gray.width * 8), max(1, gray.height * 8)), Image.Resampling.LANCZOS)
    results: list[str] = []
    for threshold in (180, 210, 150):
        processed = scaled.point(lambda pixel: 0 if pixel < threshold else 255)
        text = tesseract_prepared_ocr(processed, temp_dir, f"{field_name}_level_{threshold}", lang="eng", psm="7")
        if text:
            results.append(text)
    return results


def tesseract_level_ocr(crop: Image.Image, temp_dir: Path, field_name: str) -> str:
    tesseract = shutil.which("tesseract") or (str(DEFAULT_TESSERACT) if DEFAULT_TESSERACT.exists() else "")
    if not tesseract:
        return ""
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"ocr_{safe_name(field_name)}_{uuid.uuid4().hex}.png"
    gray = ImageOps.grayscale(ImageOps.exif_transpose(crop))
    gray = ImageOps.autocontrast(gray)
    gray = gray.resize((max(1, gray.width * 6), max(1, gray.height * 6)), Image.Resampling.LANCZOS)
    processed = gray.point(lambda pixel: 0 if pixel > 165 else 255)
    processed.save(image_path)
    cmd = [
        tesseract,
        str(image_path),
        "stdout",
        "-l",
        "eng",
        "--psm",
        "7",
        "--oem",
        "1",
        "-c",
        "tessedit_char_whitelist=0123456789",
    ]
    if DEFAULT_TESSDATA.exists():
        cmd.extend(["--tessdata-dir", str(DEFAULT_TESSDATA)])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return normalize_space(proc.stdout)
    except Exception:
        return ""
    finally:
        try:
            image_path.unlink()
        except OSError:
            pass


def tesseract_ocr(
    crop: Image.Image,
    temp_dir: Path,
    field_name: str,
    numeric: bool,
    threshold: int | None,
    whitelist: str | None = None,
) -> str:
    tesseract = shutil.which("tesseract") or (str(DEFAULT_TESSERACT) if DEFAULT_TESSERACT.exists() else "")
    if not tesseract:
        return ""
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"ocr_{safe_name(field_name)}_{uuid.uuid4().hex}.png"
    processed = preprocess_for_ocr(crop, numeric=numeric, threshold=threshold)
    processed.save(image_path)
    cmd = [
        tesseract,
        str(image_path),
        "stdout",
        "-l",
        "eng" if numeric else "chi_sim+eng",
        "--psm",
        "7",
        "--oem",
        "1",
        "-c",
        "load_system_dawg=0",
        "-c",
        "load_freq_dawg=0",
    ]
    if DEFAULT_TESSDATA.exists():
        cmd.extend(["--tessdata-dir", str(DEFAULT_TESSDATA)])
    if whitelist:
        cmd.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return normalize_space(proc.stdout)
    except Exception:
        return ""
    finally:
        try:
            image_path.unlink()
        except OSError:
            pass


def tesseract_prepared_ocr(
    image: Image.Image,
    temp_dir: Path,
    field_name: str,
    lang: str,
    psm: str,
) -> str:
    tesseract = shutil.which("tesseract") or (str(DEFAULT_TESSERACT) if DEFAULT_TESSERACT.exists() else "")
    if not tesseract:
        return ""
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"ocr_{safe_name(field_name)}_{uuid.uuid4().hex}.png"
    image.save(image_path)
    cmd = [
        tesseract,
        str(image_path),
        "stdout",
        "-l",
        lang,
        "--psm",
        psm,
        "--oem",
        "1",
        "-c",
        "load_system_dawg=0",
        "-c",
        "load_freq_dawg=0",
    ]
    if DEFAULT_TESSDATA.exists():
        cmd.extend(["--tessdata-dir", str(DEFAULT_TESSDATA)])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return normalize_space(proc.stdout)
    except Exception:
        return ""
    finally:
        try:
            image_path.unlink()
        except OSError:
            pass


def preprocess_for_ocr(crop: Image.Image, numeric: bool, threshold: int | None) -> Image.Image:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(crop))
    gray = ImageOps.autocontrast(gray)
    scale = 5 if numeric else 4
    gray = gray.resize((max(1, gray.width * scale), max(1, gray.height * scale)), Image.Resampling.LANCZOS)
    if threshold is not None:
        gray = gray.point(lambda pixel: 0 if pixel < threshold else 255)
    return gray


def save_record_images(
    row_image: Image.Image,
    fields: dict[str, Image.Image],
    out_dir: Path,
    session_id: str,
    page_index: int,
    row_index: int,
) -> dict[str, Path]:
    row_dir = out_dir / session_id / f"page_{page_index:02d}" / f"row_{row_index:02d}"
    row_dir.mkdir(parents=True, exist_ok=True)
    paths = {"row": row_dir / "row.png"}
    row_image.save(paths["row"])
    for name, image in fields.items():
        path = row_dir / f"{name}.png"
        image.save(path)
        paths[name] = path
    return paths


def load_members(db_path: Path) -> list[MemberCandidate]:
    suite = UnionRaidSuite(db_path)
    try:
        active = [
            MemberCandidate(member.id, member.name, bool(member.active), member.group_card or "")
            for member in suite.list_members()
            if member.active
        ]
        bound = [
            member for member in active
            if member.group_card.strip()
        ]
        return bound or active
    finally:
        suite.close()


def match_member_candidates(
    raw_values: list[str],
    members: list[MemberCandidate],
    aliases: dict[str, str],
) -> MemberCandidate | None:
    for raw in raw_values:
        member = match_member(raw, members, aliases)
        if member:
            return member

    best: tuple[float, str, MemberCandidate | None] = (0.0, "", None)
    for raw in raw_values:
        clean_raw = normalize_member_key(raw)
        if not clean_raw:
            continue
        for member in members:
            score = member_text_similarity(clean_raw, normalize_member_key(member.name))
            if score > best[0]:
                best = (score, raw, member)
    if best[2] and best[0] >= 0.68:
        member = best[2]
        return MemberCandidate(member.id, member.name, member.active, f"fuzzy-name:{best[0]:.2f}")
    return None


def match_member(raw: str, members: list[MemberCandidate], aliases: dict[str, str]) -> MemberCandidate | None:
    clean_raw = normalize_member_key(raw)
    if not clean_raw:
        return None
    alias_name = aliases.get(clean_raw) or aliases.get(raw.strip())
    if alias_name:
        for member in members:
            if member.name == alias_name:
                return MemberCandidate(member.id, member.name, member.active, "alias")
    for member in members:
        if normalize_member_key(member.name) == clean_raw:
            return MemberCandidate(member.id, member.name, member.active, "exact")
    for member in members:
        key = normalize_member_key(member.name)
        if len(key) >= 3 and len(clean_raw) >= 3 and (key in clean_raw or clean_raw in key):
            return MemberCandidate(member.id, member.name, member.active, "substring")
    best: tuple[float, MemberCandidate | None] = (0.0, None)
    for member in members:
        key = normalize_member_key(member.name)
        if not key or count_cjk(key) or count_cjk(clean_raw):
            continue
        ratio = difflib.SequenceMatcher(a=clean_raw, b=key).ratio()
        if ratio > best[0]:
            best = (ratio, member)
    if best[1] and best[0] >= 0.78:
        member = best[1]
        return MemberCandidate(member.id, member.name, member.active, f"fuzzy:{best[0]:.2f}")
    return None


def import_records(db_path: Path, records: list[RaidDayRecord], source: str, replace: bool) -> dict[str, int]:
    suite = UnionRaidSuite(db_path)
    try:
        return suite.import_flow1_records([asdict(record) for record in records], source=source, replace=replace)
    finally:
        suite.close()


def is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def process_name_for_hwnd(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        return ""
    return ""


def find_game_window(explicit_title: str = "") -> Any | None:
    from union_auto_sampler import list_windows

    windows = list_windows()
    title = explicit_title.strip().lower()
    if title:
        for window in windows:
            if title in window.title.lower():
                return window
        return None

    for window in windows:
        if process_name_for_hwnd(window.hwnd).lower() == "nikke.exe":
            return window
    for window in windows:
        normalized_title = window.title.lower()
        if "nikke" in normalized_title or "胜利女神" in window.title:
            return window
    return None


def log_step(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [flow1] {message}"
    print(line, flush=True)
    if OPERATION_LOG_PATH:
        OPERATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OPERATION_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def set_operation_log(path: Path | None) -> None:
    global OPERATION_LOG_PATH
    OPERATION_LOG_PATH = path
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [flow1] log_start={path}\n",
            encoding="utf-8",
        )


def scan_game(args: argparse.Namespace) -> list[RaidDayRecord]:
    from union_auto_sampler import (
        click_window,
        screenshot_window,
    )

    if not args.allow_non_admin and not is_admin():
        raise RuntimeError("scan-game 需要管理员权限。请从管理台按钮或 start-flow1-sampler-visible.bat 启动。")

    window = find_game_window(args.window_title)
    if not window:
        raise RuntimeError("找不到 NIKKE/nikke.exe 游戏窗口。请先启动游戏，并停在联盟突袭页面附近。")
    log_step(f"目标窗口：{window.title} rect={window.rect} client={window.client_rect}")
    session_id = args.session_id or f"flow1_game_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    members = load_members(Path(args.db))
    aliases = parse_aliases(args.name_alias)
    damage_reader = DamageTemplateOCR.from_default_reference()
    boss_matcher = BossTemplateMatcher.from_default_reference()
    name_matcher = MemberNameTemplateMatcher.from_sample_db(DEFAULT_SAMPLE_DB_PATH, members)

    if not args.skip_open_record:
        opened = open_record_panel(window, args)
        if not opened:
            raise RuntimeError(
                "未能打开联盟记录弹窗。请把游戏停在主页、联盟页或联盟突袭主页后重试；"
                "如果你已经手动打开弹窗，再勾选“已打开记录”。"
            )
        time.sleep(args.wait_seconds)
    else:
        log_step("已跳过打开联盟记录入口，请确认游戏内记录弹窗已经打开。")

    if not args.skip_day_select:
        log_step(f"选择按天/第 {args.raid_day} 天。")
        click_window(window, parse_point(args.day_tab_point))
        time.sleep(0.4)
        if args.raid_day == 1:
            click_window(window, parse_point(args.day1_point))
            time.sleep(0.4)
        elif args.raid_day == 2:
            click_window(window, parse_point(args.day2_point))
            time.sleep(0.4)

    all_records: list[RaidDayRecord] = []
    seen: set[tuple[Any, ...]] = set()
    stale_pages = 0
    for page_index in range(1, args.pages + 1):
        log_step(f"截取第 {page_index} 屏。")
        screenshot = screenshot_window(window)
        visible_rows = detect_record_rows(screenshot)
        screenshot_path = out_dir / session_id / f"page_{page_index:02d}" / "screen.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(screenshot_path)
        page_records = capture_records_from_image(
            image=screenshot,
            db_path=Path(args.db),
            battle_date=args.battle_date,
            raid_day=args.raid_day,
            out_dir=out_dir,
            session_id=session_id,
            page_index=page_index,
            members=members,
            aliases=aliases,
            damage_reader=damage_reader,
            boss_matcher=boss_matcher,
            name_matcher=name_matcher,
            wechat_ocr=getattr(args, "wechat_ocr_client", None),
        )
        new_count = 0
        for record in page_records:
            key = dedupe_key(record)
            if key in seen:
                continue
            seen.add(key)
            all_records.append(record)
            new_count += 1
        log_step(f"第 {page_index} 屏识别 {len(page_records)} 行，新增 {new_count} 行，累计 {len(all_records)} 行。")
        if new_count == 0:
            stale_pages += 1
        else:
            stale_pages = 0
        if page_index >= args.pages or stale_pages >= args.stop_after_stale:
            break
        if args.use_drag_anchor:
            log_step(f"按住锚点拖动：{args.drag_anchor_start} -> {args.drag_anchor_end}。")
        else:
            log_step(f"按住第 {args.drag_start_row} 条记录拖动，目标距离 {args.drag_distance_rows:.2f} 行。")
        drag_plan_path = screenshot_path.parent / "drag_plan.png"
        controlled_next_group_drag(window, screenshot, visible_rows, args, drag_plan_path=drag_plan_path)
        time.sleep(args.wait_seconds)
    log_step(f"采样结束，共 {len(all_records)} 条去重记录。")
    return all_records


def open_record_panel(window: Any, args: argparse.Namespace) -> bool:
    from union_auto_sampler import click_window

    record_template = Path(args.record_template) if args.record_template else default_record_button_template()
    if record_panel_visible(window):
        log_step("检测到联盟记录弹窗已打开。")
        return True

    if click_template_if_found(
        window,
        record_template,
        threshold=args.template_threshold,
        label="联盟记录入口",
    ):
        time.sleep(max(0.3, args.wait_seconds))
        if record_panel_visible(window):
            return True
        log_step("已点击联盟记录入口，但尚未确认弹窗；继续尝试兜底入口。")

    union_template = Path(args.union_template) if args.union_template else default_union_entry_template()
    if click_template_if_found(
        window,
        union_template,
        threshold=min(args.template_threshold, 0.58),
        region=[0.70, 0.30, 1.00, 0.62],
        label="主页联盟入口",
    ):
        time.sleep(max(2.0, args.union_wait_seconds))
    elif args.union_point:
        log_step(f"主页联盟入口模板未命中，使用校准坐标点击：{args.union_point}")
        click_window(window, parse_point(args.union_point))
        time.sleep(max(2.0, args.union_wait_seconds))

    raid_template = Path(args.raid_entry_template) if args.raid_entry_template else default_raid_entry_template()
    if click_template_if_found(
        window,
        raid_template,
        threshold=min(args.template_threshold, 0.60),
        region=[0.00, 0.45, 1.00, 0.95],
        label="联盟突袭入口",
    ):
        time.sleep(max(1.5, args.raid_wait_seconds))
    elif args.raid_entry_point:
        log_step(f"联盟突袭入口模板未命中，使用校准坐标点击：{args.raid_entry_point}")
        click_window(window, parse_point(args.raid_entry_point))
        time.sleep(max(1.5, args.raid_wait_seconds))

    if click_template_if_found(
        window,
        record_template,
        threshold=args.template_threshold,
        label="联盟记录入口",
    ):
        time.sleep(max(0.3, args.wait_seconds))
        if record_panel_visible(window):
            return True

    if args.record_point:
        log_step(f"模板兜底未确认弹窗，使用备用坐标点击：{args.record_point}")
        click_window(window, parse_point(args.record_point))
        time.sleep(max(0.3, args.wait_seconds))
        return record_panel_visible(window)

    log_step("未能通过模板打开联盟记录弹窗。")
    return False


def record_panel_visible(window: Any) -> bool:
    from union_auto_sampler import screenshot_window

    image = screenshot_window(window).convert("RGB")
    rows = detect_record_rows(image)
    if len(rows) < 3:
        return False
    width, height = image.size
    header = image.crop(
        (
            round(width * 0.04),
            round(height * 0.13),
            round(width * 0.96),
            round(height * 0.32),
        )
    )
    pixels = list(header.getdata())
    if not pixels:
        return False
    blue = 0
    for red, green, blue_value in pixels:
        if blue_value >= 150 and green >= 100 and red <= 80:
            blue += 1
    return blue / len(pixels) >= 0.08


def calibrate_game(args: argparse.Namespace) -> int:
    from union_auto_sampler import (
        active_rect,
        activate_window,
        coordinate_diagnostics,
        screenshot_window,
    )

    window = find_game_window(args.window_title)
    if not window:
        raise RuntimeError("找不到 NIKKE/nikke.exe 游戏窗口。请先启动游戏，再打开校准向导。")
    activate_window(window.hwnd)

    session_dir = Path(args.out_dir) / args.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = session_dir / "window_start.png"
    screenshot_window(window).save(screenshot_path)

    log_step("流程1参数校准向导启动。")
    log_step("热键：F8=记录当前鼠标点，F7=跳过当前点，F3=退出。")
    log_step("请先手动把游戏切到提示要求的页面；向导只记录坐标，不会替你乱跳页面。")
    log_step(f"坐标诊断：{coordinate_diagnostics()}")
    log_step(f"目标窗口：{window.title} window={window.rect} client={active_rect(window)}")
    log_step(f"初始窗口截图：{screenshot_path.resolve()}")

    settings = load_flow1_settings(Path(args.db))
    captured: dict[str, str] = {}
    previews: dict[str, str] = {}

    point_steps = [
        (
            "flow1_union_point",
            "主页联盟入口",
            "手动停在游戏主页，把鼠标放到右侧 RAID/联盟入口的可点击中心，然后按 F8。",
        ),
        (
            "flow1_raid_entry_point",
            "联盟突袭入口",
            "手动进入联盟主页，把鼠标放到“联盟突袭”活动卡中心，然后按 F8。",
        ),
        (
            "flow1_record_point",
            "联盟记录入口",
            "手动进入联盟突袭活动主页，把鼠标放到“联盟记录”按钮中心，然后按 F8。",
        ),
        (
            "flow1_day_tab_point",
            "按天筛选按钮",
            "打开联盟记录弹窗，把鼠标放到“天/按天”筛选按钮中心，然后按 F8。",
        ),
        (
            "flow1_day1_point",
            "第1天选项",
            "展开按天筛选下拉层，把鼠标放到“第1天”选项中心，然后按 F8。",
        ),
        (
            "flow1_day2_point",
            "第2天选项",
            "展开按天筛选下拉层，把鼠标放到“第2天”选项中心，然后按 F8。",
        ),
        (
            "flow1_drag_anchor_start",
            "拖动起点锚点",
            "让列表完整显示一页，把鼠标放到第6条记录上适合按住的位置，然后按 F8。",
        ),
        (
            "flow1_drag_anchor_end",
            "拖动终点锚点",
            "把鼠标放到上方安全停靠线位置，也就是慢拖结束后松手的位置，然后按 F8。",
        ),
    ]

    for key, label, instruction in point_steps:
        point = capture_calibration_point(window, label, instruction, session_dir)
        if point is None:
            continue
        text = format_rel_point(point)
        captured[key] = text
        preview_path = session_dir / f"{safe_name(key)}.png"
        save_calibration_point_preview(window, label, point, preview_path)
        previews[key] = str(preview_path.resolve())
        log_step(f"已记录 {label}：{text}")

    if "flow1_drag_anchor_start" in captured and "flow1_drag_anchor_end" in captured:
        captured["flow1_use_drag_anchor"] = "1"
        if not args.no_test_drag:
            log_step("锚点已记录。按 F8 立即执行一次慢拖测试，按 F7 跳过测试，按 F3 退出。")
            if wait_for_calibration_choice() == "capture":
                start = parse_point(captured["flow1_drag_anchor_start"])
                end = parse_point(captured["flow1_drag_anchor_end"])
                if valid_anchor_points(start, end):
                    log_step(
                        "执行慢拖测试："
                        f"{captured['flow1_drag_anchor_start']} -> {captured['flow1_drag_anchor_end']}，"
                        f"{args.drag_steps} 步/{args.drag_duration_seconds:.1f}s，松手延迟 {args.drag_hold_seconds:.2f}s。"
                    )
                    controlled_drag_relative(
                        window,
                        start,
                        end,
                        duration_seconds=args.drag_duration_seconds,
                        steps=args.drag_steps,
                        hold_seconds=args.drag_hold_seconds,
                    )
                else:
                    log_step("锚点不是有效的向上拖动，已跳过慢拖测试。")

    if captured:
        captured["flow1_drag_duration_seconds"] = str(args.drag_duration_seconds)
        captured["flow1_drag_steps"] = str(args.drag_steps)
        captured["flow1_drag_hold_seconds"] = str(args.drag_hold_seconds)
        settings.update(captured)
        if not args.no_save:
            save_flow1_settings(Path(args.db), settings)
            log_step("校准参数已保存到管理后台。刷新后台页面即可看到新值。")
        else:
            log_step("已按 --no-save 跳过保存，仅输出校准结果。")
    else:
        log_step("没有记录任何新坐标，后台参数未变更。")

    summary_path = session_dir / "calibration_settings.json"
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {
            "title": window.title,
            "rect": window.rect,
            "client_rect": window.client_rect,
            "active_rect": active_rect(window),
        },
        "captured": captured,
        "settings": settings,
        "previews": previews,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log_step(f"校准结果文件：{summary_path.resolve()}")
    return 0


def capture_calibration_point(
    window: Any,
    label: str,
    instruction: str,
    session_dir: Path,
) -> list[float] | None:
    from union_auto_sampler import get_cursor_relative_to_window, screenshot_window

    activate_for_calibration(window)
    log_step("")
    log_step(f"校准：{label}")
    log_step(instruction)
    log_step("F8=记录，F7=跳过，F3=退出。")
    choice = wait_for_calibration_choice()
    if choice == "skip":
        log_step(f"已跳过：{label}")
        return None
    point = get_cursor_relative_to_window(window)
    screenshot_path = session_dir / f"{safe_name(label)}_raw.png"
    screenshot_window(window).save(screenshot_path)
    log_step(f"{label}原始截图：{screenshot_path.resolve()}")
    return point


def activate_for_calibration(window: Any) -> None:
    try:
        from union_auto_sampler import activate_window

        activate_window(window.hwnd)
    except Exception:
        pass


def wait_for_calibration_choice() -> str:
    import ctypes

    user32 = ctypes.windll.user32
    keys = {
        "capture": 0x77,  # F8
        "skip": 0x76,  # F7
        "abort": 0x72,  # F3
    }
    for vk in keys.values():
        while user32.GetAsyncKeyState(vk) & 0x8000:
            time.sleep(0.03)
    while True:
        if user32.GetAsyncKeyState(keys["abort"]) & 0x8000:
            raise KeyboardInterrupt("用户按下 F3，已退出校准。")
        if user32.GetAsyncKeyState(keys["skip"]) & 0x8000:
            while user32.GetAsyncKeyState(keys["skip"]) & 0x8000:
                time.sleep(0.03)
            return "skip"
        if user32.GetAsyncKeyState(keys["capture"]) & 0x8000:
            while user32.GetAsyncKeyState(keys["capture"]) & 0x8000:
                time.sleep(0.03)
            return "capture"
        time.sleep(0.03)


def format_rel_point(point: list[float]) -> str:
    return f"{float(point[0]):.4f},{float(point[1]):.4f}"


def load_flow1_settings(db_path: Path) -> dict[str, str]:
    suite = UnionRaidSuite(db_path)
    try:
        return suite.flow1_settings()
    finally:
        suite.close()


def save_flow1_settings(db_path: Path, settings: dict[str, str]) -> None:
    suite = UnionRaidSuite(db_path)
    try:
        suite.save_flow1_settings(settings)
    finally:
        suite.close()


def save_calibration_point_preview(window: Any, label: str, point: list[float], output_path: Path) -> None:
    from union_auto_sampler import screenshot_window

    image = screenshot_window(window)
    draw = ImageDraw.Draw(image)
    width, height = image.size
    x = round(point[0] * width)
    y = round(point[1] * height)
    draw.line((x - 28, y, x + 28, y), fill="#FF3030", width=5)
    draw.line((x, y - 28, x, y + 28), fill="#FF3030", width=5)
    draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline="#7CFF4D", width=4)
    draw.text((min(width - 120, x + 12), min(height - 24, y + 12)), safe_name(label) or "point", fill="#7CFF4D")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def controlled_next_group_drag(
    window: Any,
    screenshot: Image.Image,
    rows: list[tuple[int, int, int, int]],
    args: argparse.Namespace,
    drag_plan_path: Path | None = None,
) -> None:
    if getattr(args, "use_drag_anchor", False):
        try:
            start = parse_point(args.drag_anchor_start)
            end = parse_point(args.drag_anchor_end)
        except (AttributeError, TypeError, ValueError) as exc:
            log_step(f"锚点参数无效，回退行检测拖动：{type(exc).__name__}: {exc}")
        else:
            if valid_anchor_points(start, end):
                if drag_plan_path:
                    save_drag_anchor_image(screenshot, rows, start, end, drag_plan_path)
                    log_step(f"锚点拖动计划图：{drag_plan_path.resolve()}")
                log_step(
                    "使用锚点拖动："
                    f"start=({start[0]:.3f},{start[1]:.3f}) -> "
                    f"end=({end[0]:.3f},{end[1]:.3f})。"
                )
                controlled_drag_relative(
                    window,
                    start,
                    end,
                    duration_seconds=args.drag_duration_seconds,
                    steps=args.drag_steps,
                    hold_seconds=args.drag_hold_seconds,
                )
                return
            log_step(f"锚点参数不在有效范围或不是向上拖动，回退行检测拖动：start={start} end={end}")

    plan = compute_drag_plan(screenshot.size, rows, args)
    if plan:
        if drag_plan_path:
            save_drag_plan_image(screenshot, rows, plan, drag_plan_path)
            log_step(f"拖动计划图：{drag_plan_path.resolve()}")
        log_step(
            f"检测到 {len(rows)} 条可见记录，拖动起点=第 {plan['drag_row']} 条 "
            f"y={plan['start_y']}，行距={plan['spacing']}，目标距离={plan['target_distance']}，"
            f"安全上限={plan['top_safe_y']}，终点 y={plan['end_y']}。"
        )
        if plan["start_y"] - plan["end_y"] >= plan["spacing"]:
            controlled_drag_pixels(
                window,
                plan["x"],
                plan["start_y"],
                plan["x"],
                plan["end_y"],
                duration_seconds=args.drag_duration_seconds,
                steps=args.drag_steps,
                hold_seconds=args.drag_hold_seconds,
            )
            return

    start = parse_point(args.scroll_start)
    end = parse_point(args.scroll_end)
    controlled_drag_relative(
        window,
        start,
        end,
        duration_seconds=args.drag_duration_seconds,
        steps=args.drag_steps,
        hold_seconds=args.drag_hold_seconds,
    )


def valid_anchor_points(start: list[float], end: list[float]) -> bool:
    if len(start) < 2 or len(end) < 2:
        return False
    values = [start[0], start[1], end[0], end[1]]
    if not all(0.0 <= item <= 1.0 for item in values):
        return False
    return start[1] > end[1] + 0.05


def controlled_drag_relative(
    window: Any,
    start: list[float],
    end: list[float],
    duration_seconds: float,
    steps: int,
    hold_seconds: float,
) -> None:
    from union_auto_sampler import active_rect

    left, top, right, bottom = active_rect(window)
    width = right - left
    height = bottom - top
    controlled_drag_pixels(
        window,
        round(start[0] * width),
        round(start[1] * height),
        round(end[0] * width),
        round(end[1] * height),
        duration_seconds=duration_seconds,
        steps=steps,
        hold_seconds=hold_seconds,
    )


def compute_drag_plan(
    image_size: tuple[int, int],
    rows: list[tuple[int, int, int, int]],
    args: argparse.Namespace,
) -> dict[str, int] | None:
    _width, height = image_size
    if len(rows) < 2:
        return None
    starts = [row[1] for row in rows]
    spacing = round(statistics.median([b - a for a, b in zip(starts, starts[1:])]))
    drag_row_index = min(max(1, int(args.drag_start_row)), len(rows)) - 1
    reference = rows[drag_row_index]
    x = round(reference[0] + (reference[2] - reference[0]) * 0.55)
    start_y = round(reference[1] + (reference[3] - reference[1]) * 0.45)
    distance_rows = float(args.drag_distance_rows)
    target_distance = round(spacing * max(1.0, distance_rows))
    top_safe_y = round(height * float(args.drag_end_safe_ratio))
    end_y = max(top_safe_y, start_y - target_distance)
    return {
        "x": x,
        "start_y": start_y,
        "end_y": end_y,
        "spacing": spacing,
        "target_distance": target_distance,
        "top_safe_y": top_safe_y,
        "drag_row": drag_row_index + 1,
    }


def save_drag_plan_image(
    screenshot: Image.Image,
    rows: list[tuple[int, int, int, int]],
    plan: dict[str, int],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = screenshot.copy()
    draw = ImageDraw.Draw(image)
    for index, row in enumerate(rows, start=1):
        color = "#7CFF4D" if index == plan["drag_row"] else "#FFE34D"
        draw.rectangle(row, outline=color, width=3)
        draw.text((row[0] + 6, row[1] + 6), str(index), fill=color)
    x = plan["x"]
    start_y = plan["start_y"]
    end_y = plan["end_y"]
    draw.line((x, start_y, x, end_y), fill="#FF3030", width=10)
    draw.ellipse((x - 12, start_y - 12, x + 12, start_y + 12), fill="#7CFF4D")
    draw.ellipse((x - 12, end_y - 12, x + 12, end_y + 12), fill="#7CFF4D")
    draw.text((max(0, x - 160), max(0, end_y - 30)), f"end y={end_y}", fill="#7CFF4D")
    draw.text((max(0, x - 160), min(image.height - 24, start_y + 12)), f"start row {plan['drag_row']} y={start_y}", fill="#7CFF4D")
    image.save(output_path)


def save_drag_anchor_image(
    screenshot: Image.Image,
    rows: list[tuple[int, int, int, int]],
    start: list[float],
    end: list[float],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = screenshot.copy()
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for index, row in enumerate(rows, start=1):
        color = "#7CFF4D" if index == 6 else "#FFE34D"
        draw.rectangle(row, outline=color, width=3)
        draw.text((row[0] + 6, row[1] + 6), str(index), fill=color)
    start_x = round(start[0] * width)
    start_y = round(start[1] * height)
    end_x = round(end[0] * width)
    end_y = round(end[1] * height)
    draw.line((start_x, start_y, end_x, end_y), fill="#FF3030", width=10)
    draw.ellipse((start_x - 12, start_y - 12, start_x + 12, start_y + 12), fill="#7CFF4D")
    draw.ellipse((end_x - 12, end_y - 12, end_x + 12, end_y + 12), fill="#7CFF4D")
    draw.text((max(0, start_x - 165), min(height - 24, start_y + 12)), f"anchor start {start[0]:.2f},{start[1]:.2f}", fill="#7CFF4D")
    draw.text((max(0, end_x - 165), max(0, end_y - 30)), f"anchor end {end[0]:.2f},{end[1]:.2f}", fill="#7CFF4D")
    image.save(output_path)


def controlled_drag_pixels(
    window: Any,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration_seconds: float,
    steps: int,
    hold_seconds: float,
) -> None:
    from union_auto_sampler import active_rect, activate_window

    import ctypes

    activate_window(window.hwnd)
    left, top, _right, _bottom = active_rect(window)
    sx = left + start_x
    sy = top + start_y
    ex = left + end_x
    ey = top + end_y
    user32 = ctypes.windll.user32
    steps = max(12, int(steps))
    duration_seconds = max(0.3, float(duration_seconds))
    log_step(f"拖动坐标：({start_x},{start_y}) -> ({end_x},{end_y})，{steps} 步/{duration_seconds:.1f}s。")
    user32.SetCursorPos(sx, sy)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.20)
    for index in range(1, steps + 1):
        t = index / steps
        x = round(sx + (ex - sx) * t)
        y = round(sy + (ey - sy) * t)
        user32.SetCursorPos(x, y)
        time.sleep(duration_seconds / steps)
    time.sleep(max(0.0, float(hold_seconds)))
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def click_template_if_found(
    window: Any,
    template_path: Path,
    threshold: float,
    region: list[float] | None = None,
    label: str = "模板",
) -> bool:
    if not template_path.exists():
        log_step(f"{label}模板不存在：{template_path}")
        return False
    from union_auto_sampler import absolute_point, click_window, screenshot_window

    screenshot = screenshot_window(window)
    match = locate_template_match(
        screenshot,
        Image.open(template_path).convert("RGB"),
        threshold,
        region=region,
    )
    if not match:
        log_step(f"{label}模板未命中：{template_path}")
        return False
    center = (match[0], match[1])
    width, height = screenshot.size
    rel = [center[0] / width, center[1] / height]
    log_step(f"{label}模板命中：rel=({rel[0]:.4f},{rel[1]:.4f}) score={match[2]:.3f}")
    click_window(window, rel)
    return True


def locate_template_center(image: Image.Image, template: Image.Image, threshold: float) -> tuple[int, int] | None:
    match = locate_template_match(image, template, threshold)
    if not match:
        return None
    return match[0], match[1]


def locate_template_match(
    image: Image.Image,
    template: Image.Image,
    threshold: float,
    region: list[float] | None = None,
) -> tuple[int, int, float] | None:
    try:
        import numpy as np
    except Exception:
        return None
    source_image = ImageOps.grayscale(image)
    full_width, full_height = source_image.size
    offset_x = 0
    offset_y = 0
    if region:
        x1, y1, x2, y2 = region
        offset_x = round(x1 * full_width)
        offset_y = round(y1 * full_height)
        source_image = source_image.crop(
            (
                offset_x,
                offset_y,
                round(x2 * full_width),
                round(y2 * full_height),
            )
        )
    source = np.asarray(source_image, dtype="float32")
    best: tuple[float, int, int, int, int] | None = None
    for scale in (0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40):
        tw = max(12, round(template.width * scale))
        th = max(12, round(template.height * scale))
        if th > source.shape[0] or tw > source.shape[1]:
            continue
        tpl = np.asarray(ImageOps.grayscale(template.resize((tw, th))), dtype="float32")
        found = best_template_position(source, tpl)
        if found is None:
            continue
        score, x, y = found
        if best is None or score > best[0]:
            best = (score, x, y, tw, th)
    if best is None or best[0] < threshold:
        return None
    score, x, y, tw, th = best
    return offset_x + x + tw // 2, offset_y + y + th // 2, score


def best_template_position(source: Any, tpl: Any) -> tuple[float, int, int] | None:
    try:
        import numpy as np
    except Exception:
        return None
    h, w = source.shape
    th, tw = tpl.shape
    if th > h or tw > w:
        return None
    tpl_norm = tpl - float(tpl.mean())
    tpl_den = float(np.sqrt((tpl_norm * tpl_norm).sum()))
    if tpl_den <= 1e-6:
        return None
    step = max(2, min(th, tw) // 14)
    best = (-1.0, 0, 0)
    for y in range(0, h - th + 1, step):
        for x in range(0, w - tw + 1, step):
            score = template_score(source, tpl_norm, tpl_den, x, y, tw, th)
            if score > best[0]:
                best = (score, x, y)
    _, rough_x, rough_y = best
    for y in range(max(0, rough_y - step), min(h - th, rough_y + step) + 1, 2):
        for x in range(max(0, rough_x - step), min(w - tw, rough_x + step) + 1, 2):
            score = template_score(source, tpl_norm, tpl_den, x, y, tw, th)
            if score > best[0]:
                best = (score, x, y)
    return best


def template_score(source: Any, tpl_norm: Any, tpl_den: float, x: int, y: int, width: int, height: int) -> float:
    try:
        import numpy as np
    except Exception:
        return -1.0
    patch = source[y : y + height, x : x + width]
    patch_norm = patch - float(patch.mean())
    patch_den = float(np.sqrt((patch_norm * patch_norm).sum()))
    if patch_den <= 1e-6:
        return -1.0
    return float((patch_norm * tpl_norm).sum() / (patch_den * tpl_den))


def default_record_button_template() -> Path:
    return DEFAULT_FLOW1_ASSET_DIR / "\u8054\u76df_\u8054\u76df\u7a81\u88ad_\u6d3b\u52a8\u4e3b\u9875_\u8054\u76df\u8bb0\u5f55.png"


def default_union_entry_template() -> Path:
    return DEFAULT_ASSET_ROOT / "\u4e3b\u9875_\u5165\u53e3_\u8054\u76df\u5165\u53e3_\u6587\u672c.png"


def default_raid_entry_template() -> Path:
    return DEFAULT_RAID_ASSET_DIR / "\u8054\u76df_\u5165\u53e32_\u8054\u76df\u7a81\u88ad.png"


def dedupe_key(record: RaidDayRecord) -> tuple[Any, ...]:
    return (
        record.member_id or normalize_member_key(record.member_raw),
        record.damage,
        normalize_space(record.boss_name),
        record.boss_level,
    )


def write_json(records: list[RaidDayRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(records),
        "records": [asdict(record) for record in records],
        "attendance": attendance_summary(records),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_records_csv(records: list[RaidDayRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "battle_date",
        "raid_day",
        "member_name",
        "member_id",
        "member_raw",
        "member_match",
        "boss_level",
        "boss_name",
        "damage",
        "damage_raw",
        "damage_method",
        "page_index",
        "row_index",
        "row_image_path",
        "avatar_image_path",
        "level_image_path",
        "member_image_path",
        "boss_image_path",
        "damage_image_path",
        "member_ocr_candidates",
        "member_wechat_ocr_raw",
        "boss_ocr_raw",
        "level_ocr_raw",
        "damage_ocr_raw",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {
                "battle_date": record.battle_date,
                "raid_day": record.raid_day,
                "member_name": record.member_name,
                "member_id": record.member_id,
                "member_raw": record.member_raw,
                "member_match": record.member_match,
                "boss_level": record.boss_level,
                "boss_name": record.boss_name,
                "damage": record.damage,
                "damage_raw": record.damage_raw,
                "damage_method": record.damage_method,
                "page_index": record.page_index,
                "row_index": record.row_index,
                "row_image_path": record.row_image_path,
                "avatar_image_path": record.field_image_paths.get("avatar", ""),
                "level_image_path": record.field_image_paths.get("level", ""),
                "member_image_path": record.field_image_paths.get("member", ""),
                "boss_image_path": record.field_image_paths.get("boss", ""),
                "damage_image_path": record.field_image_paths.get("damage", ""),
                "member_ocr_candidates": record.ocr_raw.get("member", ""),
                "member_wechat_ocr_raw": record.ocr_raw.get("member_wechat", ""),
                "boss_ocr_raw": record.ocr_raw.get("boss", ""),
                "level_ocr_raw": record.ocr_raw.get("level", ""),
                "damage_ocr_raw": record.ocr_raw.get("damage", ""),
            }
            writer.writerow(row)


def write_attendance_csv(records: list[RaidDayRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["member", "member_id", "attacks", "damage"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in attendance_summary(records):
            writer.writerow(row)


def update_debug_latest(
    session_id: str,
    json_out: Path,
    records_csv: Path,
    attendance_csv: Path,
    log_path: Path | None,
) -> None:
    DEFAULT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    latest_paths = DEFAULT_DEBUG_DIR / "latest_paths.txt"
    rows = [
        f"session_id={session_id}",
        f"session_dir={json_out.parent.resolve()}",
        f"records_csv={records_csv.resolve()}",
        f"attendance_csv={attendance_csv.resolve()}",
        f"records_json={json_out.resolve()}",
    ]
    if log_path:
        rows.append(f"operation_log={log_path.resolve()}")
    latest_paths.write_text("\n".join(rows) + "\n", encoding="utf-8")
    copy_targets = [
        (records_csv, DEFAULT_DEBUG_DIR / "latest_records.csv"),
        (attendance_csv, DEFAULT_DEBUG_DIR / "latest_attendance.csv"),
        (json_out, DEFAULT_DEBUG_DIR / "latest_records.json"),
    ]
    if log_path and log_path.exists():
        copy_targets.append((log_path, DEFAULT_DEBUG_DIR / "latest_operation.log"))
    for source, target in copy_targets:
        if source.exists():
            shutil.copy2(source, target)


def attendance_summary(records: list[RaidDayRecord]) -> list[dict[str, Any]]:
    by_member: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record.member_name or record.member_raw or "UNMATCHED"
        item = by_member.setdefault(name, {"member": name, "member_id": record.member_id, "attacks": 0, "damage": 0})
        item["attacks"] += 1
        item["damage"] += int(record.damage or 0)
    return sorted(by_member.values(), key=lambda item: (-int(item["damage"]), str(item["member"])))


def parse_aliases(values: list[str] | None) -> dict[str, str]:
    aliases: dict[str, str] = load_aliases(DEFAULT_ALIAS_PATH)
    for value in values or []:
        if "=" not in value:
            continue
        raw, name = value.split("=", 1)
        aliases[normalize_member_key(raw)] = name.strip()
    return aliases


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    aliases: dict[str, str] = {}
    if isinstance(payload, dict):
        items = payload.items()
    elif isinstance(payload, list):
        items = (
            (str(item.get("raw") or ""), str(item.get("name") or ""))
            for item in payload
            if isinstance(item, dict)
        )
    else:
        return aliases
    for raw, name in items:
        if str(raw).strip() and str(name).strip():
            aliases[normalize_member_key(str(raw))] = str(name).strip()
    return aliases


def parse_point(text: str) -> list[float]:
    left, right = text.split(",", 1)
    return [float(left), float(right)]


def parse_int(raw: str | None) -> int | None:
    text = normalize_space(raw or "").replace(",", "")
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group(0))


def parse_level_value(raw: str | None) -> int | None:
    original = normalize_space(raw or "")
    text = original.upper()
    if not text:
        return None
    if "10" in text:
        return 10
    match = re.search(r"\d", text)
    if match:
        return int(match.group(0))
    original_tail = original.split("LEVEL", 1)[-1] if "LEVEL" in original else original
    if "b" in original_tail or "f" in original_tail:
        return 6
    tail = text.split("LEVEL", 1)[-1] if "LEVEL" in text else text
    if "B" in tail:
        return 8
    if "G" in tail or "F" in tail:
        return 6
    if "S" in tail:
        return 5
    return None


def valid_damage_text(raw: str) -> bool:
    text = normalize_space(raw)
    if not re.fullmatch(r"\d[\d,]+", text):
        return False
    if "," not in text:
        return True
    parts = text.split(",")
    return 1 <= len(parts[0]) <= 3 and all(len(part) == 3 and part.isdigit() for part in parts[1:])


def repair_damage_tail(best_text: str, candidate_texts: list[str]) -> str:
    best_parts = best_text.split(",")
    if len(best_parts) < 3 or len(best_parts[-1]) != 3:
        return best_text
    best_tail = best_parts[-1]
    if best_tail.endswith("00"):
        return best_text
    for candidate in candidate_texts:
        parts = candidate.split(",")
        if len(parts) != len(best_parts) or len(parts[-1]) != 3:
            continue
        if parts[-1] == best_tail or not parts[-1].endswith("00"):
            continue
        stable = parts[0] == best_parts[0] and parts[-2] == best_parts[-2]
        if stable:
            repaired = list(best_parts)
            repaired[-1] = parts[-1]
            return ",".join(repaired)
    return best_text


def clean_label(raw: str) -> str:
    text = normalize_space(raw)
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff.\- ]+", "", text)
    return normalize_space(text)


def normalize_boss_name(raw: str) -> str:
    text = clean_label(raw)
    aliases = [
        ("\u514b\u62c9", "\u514b\u62c9\u80af"),
        ("\u666e\u62c9", "\u666e\u62c9\u7279"),
        ("\u94c1", "\u94c1\u5320"),
        ("\u5929", "\u5929\u8f89"),
        ("\u73b2\u5dfe", "\u6b93\u5dfe"),
        ("\u6b93", "\u6b93\u5dfe"),
    ]
    for needle, value in aliases:
        if needle in text:
            return value
    return text


def normalize_member_key(raw: str) -> str:
    text = clean_label(raw).upper()
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def resolve_sample_member(sample_text: str, members: list[MemberCandidate]) -> MemberCandidate | None:
    sample_key = normalize_member_key(sample_text)
    if not sample_key:
        return None
    for member in members:
        key = normalize_member_key(member.name)
        if key and (key == sample_key or key in sample_key or sample_key in key):
            return member
    best: tuple[float, MemberCandidate | None] = (0.0, None)
    for member in members:
        score = member_text_similarity(sample_key, normalize_member_key(member.name))
        if score > best[0]:
            best = (score, member)
    return best[1] if best[0] >= 0.82 else None


def likely_same_member_text(raw: str, member_name: str) -> bool:
    raw_key = normalize_member_key(raw)
    member_key = normalize_member_key(member_name)
    if not raw_key or not member_key:
        return False
    if raw_key == member_key or raw_key in member_key or member_key in raw_key:
        return True
    return member_text_similarity(raw_key, member_key) >= 0.62


def member_text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 3 and len(right) >= 3 and (left in right or right in left):
        return 0.92
    ratio = difflib.SequenceMatcher(a=left, b=right).ratio()
    left_cjk = count_cjk(left)
    right_cjk = count_cjk(right)
    if left_cjk and right_cjk:
        overlap = cjk_multiset_overlap(left, right)
        shorter = max(1, min(left_cjk, right_cjk))
        overlap_ratio = overlap / shorter
        ratio = max(ratio, overlap_ratio * 0.74)
        if shorter <= 4 and overlap >= 2:
            ratio = max(ratio, 0.69)
    return ratio


def cjk_multiset_overlap(left: str, right: str) -> int:
    counts: dict[str, int] = {}
    for char in right:
        if "\u4e00" <= char <= "\u9fff":
            counts[char] = counts.get(char, 0) + 1
    overlap = 0
    for char in left:
        if "\u4e00" <= char <= "\u9fff" and counts.get(char, 0) > 0:
            counts[char] -= 1
            overlap += 1
    return overlap


def normalize_space(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").replace("\r", " ").replace("\n", " ")).strip()


def count_cjk(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def has_memberish_ascii(text: str) -> int:
    return 1 if re.search(r"[A-Za-z0-9]{3,}", text) else 0


def image_nonblank_score(image: Image.Image) -> float:
    gray = ImageOps.grayscale(image.resize((32, 32)))
    low, high = gray.getextrema()
    return float(high - low)


def text_image_signature(image: Image.Image, size: tuple[int, int] = (96, 24)) -> tuple[int, ...]:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(image))
    gray = ImageOps.autocontrast(gray)
    box = text_content_box(gray)
    if box:
        gray = gray.crop(box)
    canvas = Image.new("L", (max(1, gray.width) + 8, max(1, gray.height) + 8), 255)
    canvas.paste(gray, (4, 4))
    resized = canvas.resize(size, Image.Resampling.LANCZOS)
    return tuple(1 if pixel < 170 else 0 for pixel in resized.tobytes())


def text_content_box(image: Image.Image, threshold: int = 165) -> tuple[int, int, int, int] | None:
    gray = ImageOps.grayscale(image)
    width, height = gray.size
    pixels = gray.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            if pixels[x, y] < threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (
        max(0, min(xs) - 2),
        max(0, min(ys) - 2),
        min(width, max(xs) + 3),
        min(height, max(ys) + 3),
    )


def signature_distance(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if len(left) != len(right) or not left:
        return 1.0
    return sum(a != b for a, b in zip(left, right)) / len(left)


def average_hash(image: Image.Image, size: int = 8) -> str:
    gray = ImageOps.grayscale(ImageOps.exif_transpose(image).resize((size, size), Image.Resampling.LANCZOS))
    pixels = list(gray.tobytes())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hash_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return 10**9
    return (int(left, 16) ^ int(right, 16)).bit_count()


def contiguous_groups(values: list[int]) -> list[tuple[int, int]]:
    groups: list[list[int]] = []
    for value in values:
        if not groups or value > groups[-1][1] + 1:
            groups.append([value, value])
        else:
            groups[-1][1] = value
    return [(start, end) for start, end in groups]


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", text)[:80]


def default_battle_date(raid_day: int | None) -> str:
    if raid_day:
        return raid_day_date(raid_day).isoformat()
    return date.today().isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NIKKE union raid flow1 day-record sampler")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_image_parser = sub.add_parser("scan-image", help="scan a saved flow1 record image")
    scan_image_parser.add_argument("image", type=Path)
    add_common_args(scan_image_parser)

    scan_sample_parser = sub.add_parser("scan-sample", help="scan bundled flow1 sample material")
    add_common_args(scan_sample_parser)

    calibrate_parser = sub.add_parser("calibrate-game", help="interactive flow1 coordinate and drag-anchor calibration")
    calibrate_parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    calibrate_parser.add_argument("--out-dir", type=Path, default=DEFAULT_DEBUG_DIR / "calibration")
    calibrate_parser.add_argument("--session-id", default="")
    calibrate_parser.add_argument("--window-title", default="")
    calibrate_parser.add_argument("--drag-duration-seconds", type=float, default=1.4)
    calibrate_parser.add_argument("--drag-steps", type=int, default=56)
    calibrate_parser.add_argument("--drag-hold-seconds", type=float, default=0.35)
    calibrate_parser.add_argument("--no-test-drag", action="store_true")
    calibrate_parser.add_argument("--no-save", action="store_true")

    scan_game_parser = sub.add_parser("scan-game", help="scan the live game window")
    add_common_args(scan_game_parser)
    scan_game_parser.add_argument("--window-title", default="")
    scan_game_parser.add_argument("--pages", type=int, default=12)
    scan_game_parser.add_argument("--stop-after-stale", type=int, default=2)
    scan_game_parser.add_argument("--wait-seconds", type=float, default=0.8)
    scan_game_parser.add_argument("--skip-open-record", action="store_true")
    scan_game_parser.add_argument("--skip-day-select", action="store_true")
    scan_game_parser.add_argument("--record-template", default="")
    scan_game_parser.add_argument("--union-template", default="")
    scan_game_parser.add_argument("--raid-entry-template", default="")
    scan_game_parser.add_argument("--union-point", default="0.912,0.395")
    scan_game_parser.add_argument("--raid-entry-point", default="0.50,0.835")
    scan_game_parser.add_argument("--record-point", default="")
    scan_game_parser.add_argument("--template-threshold", type=float, default=0.72)
    scan_game_parser.add_argument("--union-wait-seconds", type=float, default=4.0)
    scan_game_parser.add_argument("--raid-wait-seconds", type=float, default=3.0)
    scan_game_parser.add_argument("--day-tab-point", default="0.34,0.225")
    scan_game_parser.add_argument("--day1-point", default="0.16,0.278")
    scan_game_parser.add_argument("--day2-point", default="0.31,0.278")
    scan_game_parser.add_argument("--allow-non-admin", action="store_true")
    scan_game_parser.add_argument("--scroll-rows", type=int, default=6)
    scan_game_parser.add_argument("--drag-start-row", type=int, default=6)
    scan_game_parser.add_argument("--drag-distance-rows", type=float, default=6.1)
    scan_game_parser.add_argument("--drag-end-safe-ratio", type=float, default=0.16)
    scan_game_parser.add_argument("--use-drag-anchor", action="store_true")
    scan_game_parser.add_argument("--drag-anchor-start", default="0.53,0.79")
    scan_game_parser.add_argument("--drag-anchor-end", default="0.53,0.25")
    scan_game_parser.add_argument("--scroll-start", default="0.60,0.80")
    scan_game_parser.add_argument("--scroll-end", default="0.60,0.42")
    scan_game_parser.add_argument("--drag-duration-seconds", type=float, default=1.4)
    scan_game_parser.add_argument("--drag-steps", type=int, default=56)
    scan_game_parser.add_argument("--drag-hold-seconds", type=float, default=0.35)
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--raid-day", type=int, default=1)
    parser.add_argument("--battle-date", default="")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--attendance-csv-out", type=Path, default=None)
    parser.add_argument("--import-db", action="store_true")
    parser.add_argument("--no-replace", action="store_true")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--name-alias", action="append", default=[])
    parser.add_argument("--disable-wechat-ocr", action="store_true")
    parser.add_argument("--wechat-ocr-timeout", type=float, default=8.0)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "battle_date"):
        args.battle_date = args.battle_date or default_battle_date(args.raid_day)
    if not args.session_id:
        prefix = {
            "calibrate-game": "flow1_calibrate",
            "scan-image": "flow1_image",
            "scan-sample": "flow1_sample",
            "scan-game": "flow1_game",
        }.get(args.command, "flow1")
        args.session_id = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    operation_log = Path(args.out_dir) / args.session_id / "operation.log"
    set_operation_log(operation_log)
    log_step(f"command={args.command} session_id={args.session_id}")
    if hasattr(args, "battle_date"):
        log_step(f"battle_date={args.battle_date} raid_day={args.raid_day} out_dir={Path(args.out_dir).resolve()}")
    else:
        log_step(f"out_dir={Path(args.out_dir).resolve()}")
    if args.command == "calibrate-game":
        return calibrate_game(args)
    aliases = parse_aliases(args.name_alias)
    wechat_ocr = None if args.disable_wechat_ocr else WeChatOCRClient(timeout=args.wechat_ocr_timeout)
    if wechat_ocr is not None:
        wechat_ocr.start()
    if args.command == "scan-image":
        log_step(f"scan_image={args.image}")
        try:
            records = scan_image(
                image_path=args.image,
                db_path=args.db,
                battle_date=args.battle_date,
                raid_day=args.raid_day,
                out_dir=args.out_dir,
                session_id=args.session_id,
                aliases=aliases,
                wechat_ocr=wechat_ocr if wechat_ocr and wechat_ocr.available else None,
            )
        finally:
            if wechat_ocr:
                wechat_ocr.stop()
    elif args.command == "scan-sample":
        sample_image = default_flow1_damage_image()
        log_step(f"scan_sample={sample_image}")
        try:
            records = scan_image(
                image_path=sample_image,
                db_path=args.db,
                battle_date=args.battle_date,
                raid_day=args.raid_day,
                out_dir=args.out_dir,
                session_id=args.session_id,
                aliases=aliases,
                wechat_ocr=wechat_ocr if wechat_ocr and wechat_ocr.available else None,
            )
        finally:
            if wechat_ocr:
                wechat_ocr.stop()
    elif args.command == "scan-game":
        try:
            setattr(args, "wechat_ocr_client", wechat_ocr if wechat_ocr and wechat_ocr.available else None)
            records = scan_game(args)
        finally:
            if wechat_ocr:
                wechat_ocr.stop()
    else:
        if wechat_ocr:
            wechat_ocr.stop()
        raise ValueError(args.command)

    session_id = records[0].session_id if records else (args.session_id or f"flow1_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    json_out = args.json_out or (args.out_dir / session_id / "records.json")
    csv_out = args.csv_out or (args.out_dir / session_id / "records.csv")
    attendance_csv_out = args.attendance_csv_out or (args.out_dir / session_id / "attendance.csv")
    write_json(records, json_out)
    write_records_csv(records, csv_out)
    write_attendance_csv(records, attendance_csv_out)
    log_step(f"records={len(records)}")
    log_step(f"json={json_out.resolve()}")
    log_step(f"csv={csv_out.resolve()}")
    log_step(f"attendance_csv={attendance_csv_out.resolve()}")
    log_step(f"operation_log={operation_log.resolve()}")
    log_step(f"latest_paths={(DEFAULT_DEBUG_DIR / 'latest_paths.txt').resolve()}")
    unmatched = sum(1 for record in records if not record.member_id)
    log_step(f"unmatched={unmatched}")
    if args.import_db:
        result = import_records(args.db, records, args.source, replace=not args.no_replace)
        log_step("import=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    update_debug_latest(args.session_id, json_out, csv_out, attendance_csv_out, operation_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
