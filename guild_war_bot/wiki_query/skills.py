# -*- coding: utf-8 -*-
"""角色技能组解析：从 GameKee 内容详情缓存提取技能1/技能2/爆裂技能。

数据源：Nikke_Wiki/cache/gamekee_content_details/content_<gamekeeContentId>.json
缓存缺失时返回空技能组，由调用方提示"技能资料暂未收录"。
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GAMEKEE_CACHE_DIR = Path(r"F:\Codex\Nikke\Nikke_Wiki\cache\gamekee_content_details")


def _load_content_rows(content_id: int | None) -> list[list[dict[str, Any]]] | None:
    """读取内容详情缓存并返回 baseData 行列表；缺失/损坏返回 None。"""
    if not content_id:
        return None
    path = GAMEKEE_CACHE_DIR / f"content_{content_id}.json"
    if not path.exists():
        logger.info("GameKee 内容缓存缺失: %s", path)
        return None
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        inner = json.loads(data.get("content") or "{}")
        base = inner.get("baseData") or []
        return [row for row in base if isinstance(row, list)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("GameKee 内容解析失败 %s: %s", path, exc)
        return None


def _row_value(row: list[dict[str, Any]]) -> str:
    """取行中第一个有值的单元格（标签行本身返回标签）。"""
    if not row:
        return ""
    return str(row[0].get("value") or "").strip() if isinstance(row[0], dict) else ""


def _row_values(row: list[dict[str, Any]]) -> list[str]:
    """取行中所有单元格的值。"""
    return [str(cell.get("value") or "").strip() for cell in row if isinstance(cell, dict)]


def _parse_skill_block(
    block_rows: list[list[dict[str, Any]]],
    name_label: str,
) -> dict[str, str] | None:
    """从技能块的行列表中解析（名称/类型/冷却/描述）。

    块结构（block_rows 为该技能块边界内的行）：
      技能N名称 | <名称>
      技能N图标 | <图标>
      冷却时间  | <无/秒>
      技能类型  | <被动/主动/爆裂>
      lv1 | <技能效果文本> ... lv10 | <数值>
      技能描述（lv10)） | <满级描述>
    """
    name, skill_type, cooldown, desc, desc_lv10 = "", "", "", "", ""
    found_name = False
    for row in block_rows:
        cells = _row_values(row)
        if not cells:
            continue
        label = cells[0]
        value = cells[1] if len(cells) > 1 else ""
        if label == name_label and value:
            name = value
            found_name = True
        elif label == "冷却时间" and value:
            cooldown = value
        elif label == "技能类型" and value:
            skill_type = value
        elif label == "lv1" and value:
            # lv1 行是技能效果文本（最简描述）
            desc = value
        elif label == "技能描述（lv10)）" and value:
            desc_lv10 = value
    if not found_name:
        return None
    return {
        "name": name,
        "type": skill_type,
        "cooldown": cooldown,
        "desc": desc,
        "desc_lv10": desc_lv10,
    }


def _skill_block_ranges(rows: list[list[dict[str, Any]]]) -> dict[str, tuple[int, int]]:
    """按名称标签切分技能块边界，返回 {块标签: (start, end)}。

    边界：技能1名称 -> 技能2名称 -> 爆裂技能名称 -> 普攻(或结束)。
    """
    name_rows: list[tuple[int, str]] = []
    end_row = len(rows)
    for i, row in enumerate(rows):
        cells = _row_values(row)
        if not cells:
            continue
        label = cells[0]
        if label in ("技能1名称", "技能2名称", "爆裂技能名称"):
            name_rows.append((i, label))
        elif label == "普攻" and end_row == len(rows):
            end_row = i

    blocks: dict[str, tuple[int, int]] = {}
    for idx, (start, label) in enumerate(name_rows):
        end = name_rows[idx + 1][0] if idx + 1 < len(name_rows) else end_row
        blocks[label] = (start, end)
    return blocks


def fetch_skills(content_id: int | None) -> dict[str, dict[str, str]] | None:
    """按 gamekeeContentId 提取技能组。

    返回 {"技能1": {...}, "技能2": {...}, "爆裂技能": {...}}；缓存缺失返回 None。
    """
    rows = _load_content_rows(content_id)
    if rows is None:
        return None
    ranges = _skill_block_ranges(rows)
    result: dict[str, dict[str, str]] = {}
    for label, name_label in (
        ("技能1", "技能1名称"),
        ("技能2", "技能2名称"),
        ("爆裂技能", "爆裂技能名称"),
    ):
        span = ranges.get(name_label)
        if not span:
            continue
        block = _parse_skill_block(rows[span[0] : span[1]], name_label)
        if block and block["name"]:
            result[label] = block
    return result or None


def format_skills_text(skills: dict[str, dict[str, str]]) -> str:
    """把技能组格式化为角色卡可读文本。"""
    if not skills:
        return "技能资料暂未收录"
    lines = []
    for label in ("技能1", "技能2", "爆裂技能"):
        block = skills.get(label)
        if not block:
            continue
        name = block.get("name", "")
        parts = [f"{label}：{name}"]
        if block.get("type"):
            parts.append(block["type"])
        if block.get("cooldown"):
            parts.append(f"冷却{block['cooldown']}")
        lines.append(" ".join(parts))
        desc = block.get("desc") or block.get("desc_lv10") or ""
        if desc:
            # 技能描述可能很长，只展示前 2 行
            desc_lines = [ln.strip() for ln in desc.splitlines() if ln.strip()]
            lines.append("　" + " ".join(desc_lines[:2])[:120])
    return "\n".join(lines) if lines else "技能资料暂未收录"
