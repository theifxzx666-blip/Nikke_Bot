from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


DEFAULT_AFFIX_CATALOG = Path(__file__).resolve().parents[2] / "data" / "equipment_affix_catalog.json"
FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\NotoSansCJK-Regular.ttc"),
    Path(r"C:\Windows\Fonts\SourceHanSansCN-Regular.otf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
)


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def best_values_by_type(rows: list[dict[str, Any]]) -> dict[str, float]:
    best: dict[str, float] = {}
    for row in rows:
        name = str(row.get("affix_type") or "")
        best[name] = max(best.get(name, float("-inf")), float(row.get("affix_value") or 0))
    return best


class AffixCatalog:
    def __init__(self, catalog_path: Path = DEFAULT_AFFIX_CATALOG) -> None:
        self.rules: dict[str, dict[str, Any]] = load_json(catalog_path) if catalog_path.exists() else {}

    def normalize_type(self, text: str) -> str | None:
        compact = "".join(str(text).split())
        for name, rule in self.rules.items():
            if compact == name or compact in (rule.get("aliases") or []):
                return name
        return None

    def tier(self, affix_type: str, value: float) -> int:
        from .ocr import infer_tier

        return infer_tier(self.rules.get(affix_type, {}), value)

    def font(self, size: int):
        for path in FONT_CANDIDATES:
            if path.exists():
                return ImageFont.truetype(str(path), size)
        return ImageFont.load_default()

    def render_card(self, character: dict[str, Any], rows: list[dict[str, Any]], out: Path, portrait: Path | None = None) -> Path:
        width = 1200
        height = 220 + max(1, len(rows)) * 58
        image = Image.new("RGB", (width, height), (20, 27, 40))
        draw = ImageDraw.Draw(image)
        if portrait and portrait.exists():
            art = Image.open(portrait).convert("RGB")
            art.thumbnail((180, 190))
            image.paste(art, (28, 20))
        name = str(character.get("cnName") or character.get("name") or "未知角色")
        draw.text((240, 35), name, fill=(245, 245, 245), font=self.font(40))
        totals: dict[str, float] = {}
        for row in rows:
            affix_type = str(row.get("affix_type") or "")
            totals[affix_type] = totals.get(affix_type, 0.0) + float(row.get("affix_value") or 0)
        total_parts = [f"{name} {value:g}%" for name, value in totals.items()]
        total_text = " / ".join(total_parts[:4])
        if len(total_parts) > 4:
            total_text += f" / 等{len(total_parts)}项"
        draw.text((240, 95), f"词条合计：{total_text or '暂无'}", fill=(170, 180, 195), font=self.font(20))
        core = [str(name) for name in character.get("core_affixes", [])][:5]
        draw.text((240, 138), f"核心属性：{' / '.join(core) or '待配置'}", fill=(50, 150, 255), font=self.font(21))
        best_by_type = best_values_by_type(rows)
        for index, row in enumerate(rows):
            y = 190 + index * 58
            name = str(row.get("affix_type") or "")
            color = (50, 150, 255) if float(row.get("affix_value") or 0) == best_by_type.get(name) else (245, 245, 245)
            tier = f"{row.get('tier')}阶" if int(row.get("tier") or 0) else "阶数待确认"
            text = f"装备 {row.get('slot', '?')}   {name}   {row.get('value_text', '')}   {tier}"
            draw.text((42, y), text, fill=color, font=self.font(25))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        image.save(out, "PNG")
        return Path(out)

    def render_compare(self, rows: list[dict[str, Any]], out: Path, selected: str | None = None) -> Path:
        rows = sorted(rows, key=lambda row: (-int(row.get("tier") or 0), -float(row.get("affix_value") or 0)))[:10]
        columns = (("角色", 230), ("词条", 250), ("数值", 150), ("阶数", 100), ("装备", 100))
        image = Image.new("RGB", (sum(size for _, size in columns) + 60, 90 + len(rows) * 58), (20, 27, 40))
        draw = ImageDraw.Draw(image)
        x = 30
        for title, size in columns:
            draw.text((x, 24), title, fill=(170, 180, 195), font=self.font(23))
            x += size
        for index, row in enumerate(rows):
            y = 78 + index * 58
            active = selected and row.get("character_name") == selected
            tier = f"{row.get('tier')}阶" if int(row.get("tier") or 0) else "待确认"
            values = (row.get("character_name", ""), row.get("affix_type", ""), row.get("value_text", ""), tier, row.get("slot", ""))
            x = 30
            for value, (_, size) in zip(values, columns):
                draw.text((x, y), str(value), fill=(50, 150, 255) if active else (245, 245, 245), font=self.font(22))
                x += size
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        image.save(out, "PNG")
        return Path(out)

    def export_xlsx(self, rows: list[dict[str, Any]], out: Path) -> Path:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise RuntimeError("未安装 openpyxl，无法导出 Excel") from exc
        book = Workbook()
        sheet = book.active
        sheet.title = "词条统计"
        headers = ("用户QQ", "角色ID", "角色名", "装备槽位", "词条类型", "词条值", "原始值", "阶数", "更新时间")
        sheet.append(headers)
        for row in rows:
            sheet.append(tuple(row.get(key, "") for key in ("user_id", "character_id", "character_name", "slot", "affix_type", "affix_value", "value_text", "tier", "updated_at")))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            letter = column[0].column_letter
            sheet.column_dimensions[letter].width = min(28, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        book.save(out)
        return Path(out)
