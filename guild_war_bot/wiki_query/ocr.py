from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - optional runtime dependency
    RapidOCR = None


VALUE_RE = re.compile(r"(?P<value>\d+(?:[.,·]\d+)?)\s*(?P<unit>%|％|倍|秒)?")
TIER_RE = re.compile(r"(?:T\s*(?P<tier_t>1[0-5]|[0-9])|第?\s*(?P<tier_cn>1[0-5]|[0-9])\s*阶)", re.IGNORECASE)


@dataclass(frozen=True)
class OCRText:
    text: str
    confidence: float
    center_y: float
    height: float


@dataclass(frozen=True)
class AffixHit:
    slot: int
    affix_type: str
    affix_value: float
    value_text: str
    tier: int
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "affix_type": self.affix_type,
            "affix_value": self.affix_value,
            "value_text": self.value_text,
            "tier": self.tier,
            "confidence": self.confidence,
        }


class AffixOCR:
    def __init__(self, catalog: dict[str, dict[str, Any]]) -> None:
        self.catalog = catalog
        self.aliases = sorted(
            (
                (str(alias), name)
                for name, rule in catalog.items()
                for alias in [name, *(rule.get("aliases") or [])]
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        self.engine = RapidOCR() if RapidOCR is not None else None

    def preprocess(self, path: Path) -> Image.Image:
        image = ImageOps.exif_transpose(Image.open(path).convert("RGB"))
        max_side = max(image.size)
        if max_side > 2200:
            ratio = 2200 / max_side
            image = image.resize((int(image.width * ratio), int(image.height * ratio)))
        return image

    @staticmethod
    def variants(image: Image.Image) -> list[Image.Image]:
        gray = ImageOps.grayscale(image)
        enhanced = ImageEnhance.Contrast(gray).enhance(1.8)
        return [image, gray, enhanced]

    def recognize_items(self, image: Image.Image) -> list[OCRText]:
        if self.engine is None:
            raise RuntimeError("未安装 rapidocr-onnxruntime，请先安装 OCR 依赖")
        image_array = np.asarray(image)
        if image_array.ndim == 3:
            image_array = image_array[:, :, ::-1]
        result, _ = self.engine(image_array)
        items: list[OCRText] = []
        for row in result or []:
            box, recognized_text, confidence = row[0], row[1], row[2]
            ys = [float(point[1]) for point in box]
            items.append(OCRText(str(recognized_text), float(confidence), sum(ys) / len(ys), max(ys) - min(ys)))
        return items

    @staticmethod
    def group_lines(items: list[OCRText]) -> list[list[OCRText]]:
        lines: list[list[OCRText]] = []
        for item in sorted(items, key=lambda value: value.center_y):
            if not lines:
                lines.append([item])
                continue
            line_center = sum(value.center_y for value in lines[-1]) / len(lines[-1])
            tolerance = max(8.0, item.height * 0.65)
            if abs(item.center_y - line_center) <= tolerance:
                lines[-1].append(item)
            else:
                lines.append([item])
        return lines

    def parse_line(self, slot: int, text: str, confidence: float) -> AffixHit | None:
        normalized = self.normalize(text)
        affix_type = next((name for alias, name in self.aliases if self.normalize(alias) in normalized), None)
        tier_match = TIER_RE.search(normalized)
        value_source = TIER_RE.sub("", normalized)
        match = VALUE_RE.search(value_source)
        if not affix_type or not match:
            return None
        value = float(match.group("value").replace(",", ".").replace("·", "."))
        unit = match.group("unit") or self.catalog[affix_type].get("unit", "")
        explicit_tier = int(tier_match.group("tier_t") or tier_match.group("tier_cn")) if tier_match else None
        tier = explicit_tier if explicit_tier is not None else infer_tier(self.catalog[affix_type], value)
        return AffixHit(slot, affix_type, value, f"{value:g}{unit}", tier, confidence)

    @staticmethod
    def normalize(text: str) -> str:
        text = text.replace("％", "%").replace("，", ".").replace("。", ".")
        text = text.replace("O", "0").replace("o", "0")
        return re.sub(r"\s+", "", text)

    def _parse_items(self, items: list[OCRText], slot: int) -> tuple[list[AffixHit], list[str]]:
        lines = self.group_lines(items)
        candidates: list[tuple[str, float]] = []
        line_texts: list[str] = []
        for line in lines:
            text = " ".join(item.text for item in line)
            confidence = sum(item.confidence for item in line) / len(line)
            line_texts.append(text)
            candidates.append((text, confidence))
        for index in range(len(lines) - 1):
            pair = lines[index] + lines[index + 1]
            candidates.append((" ".join(item.text for item in pair), sum(item.confidence for item in pair) / len(pair)))

        best: dict[tuple[str, float], AffixHit] = {}
        for text, confidence in candidates:
            hit = self.parse_line(slot, text, confidence)
            if hit is None:
                continue
            key = (hit.affix_type, hit.affix_value)
            if key not in best or hit.confidence > best[key].confidence:
                best[key] = hit
        return list(best.values()), line_texts

    def process(self, path: Path, slot: int = 1) -> dict[str, Any]:
        image = self.preprocess(path)
        attempts = [self._parse_items(self.recognize_items(variant), slot) for variant in self.variants(image)]
        hits, raw_lines = max(
            attempts,
            key=lambda result: (
                len(result[0]),
                sum(hit.confidence for hit in result[0]) / len(result[0]) if result[0] else 0.0,
            ),
        )
        rows = [hit.as_dict() for hit in hits]
        confidence = sum(hit.confidence for hit in hits) / len(hits) if hits else 0.0
        needs_review = not rows or confidence < 0.80 or any(hit.tier == 0 for hit in hits)
        return {
            "status": "needs_review" if needs_review else "success",
            "raw_text": "\n".join(raw_lines),
            "rows": rows,
            "confidence": confidence,
        }


def infer_tier(rule: dict[str, Any], value: float) -> int:
    for tier, configured_values in (rule.get("tier_values") or {}).items():
        values = configured_values if isinstance(configured_values, list) else [configured_values]
        if any(abs(float(candidate) - value) <= 0.01 for candidate in values):
            parsed = int(tier)
            return parsed if 0 <= parsed <= 15 else 0
    return 0
