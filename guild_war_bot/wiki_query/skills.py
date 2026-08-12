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
      技能N名称/爆裂技能 | <名称>
      技能N图标 | <图标>
      冷却时间  | <无/秒>
      技能类型  | <被动/主动/爆裂>
      lv1 | <技能效果文本> ... lv10 | <数值>
      技能描述（lv10)） | <满级描述>
    """
    name, skill_type, cooldown, desc, desc_lv10 = "", "", "", "", ""
    # 名称标签兼容「爆裂技能名称」与「爆裂技能」两种写法
    name_labels = {name_label}
    if name_label == "爆裂技能名称":
        name_labels.add("爆裂技能")
    found_name = False
    for row in block_rows:
        cells = _row_values(row)
        if not cells:
            continue
        label = cells[0]
        value = cells[1] if len(cells) > 1 else ""
        if label in name_labels and value:
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

    边界：技能1名称 -> 技能2名称 -> 爆裂技能名称/爆裂技能 -> 普攻(或结束)。
    注意：部分角色（尤其在线新数据）爆裂块标签是「爆裂技能」而非「爆裂技能名称」。
    """
    name_rows: list[tuple[int, str]] = []
    end_row = len(rows)
    for i, row in enumerate(rows):
        cells = _row_values(row)
        if not cells:
            continue
        label = cells[0]
        if label in ("技能1名称", "技能2名称", "爆裂技能名称", "爆裂技能"):
            name_rows.append((i, label))
        elif label == "普攻" and end_row == len(rows):
            end_row = i

    blocks: dict[str, tuple[int, int]] = {}
    for idx, (start, label) in enumerate(name_rows):
        end = name_rows[idx + 1][0] if idx + 1 < len(name_rows) else end_row
        blocks[label] = (start, end)
    return blocks


def _rows_to_skills(rows: list[list[dict[str, Any]]]) -> dict[str, dict[str, str]] | None:
    """从 baseData 行列表解析技能组（本地缓存与在线数据共用）。"""
    ranges = _skill_block_ranges(rows)
    result: dict[str, dict[str, str]] = {}
    for label, name_labels in (
        ("技能1", ("技能1名称",)),
        ("技能2", ("技能2名称",)),
        ("爆裂技能", ("爆裂技能名称", "爆裂技能")),
    ):
        span = None
        for nl in name_labels:
            if nl in ranges:
                span = ranges[nl]
                break
        if not span:
            continue
        block = _parse_skill_block(rows[span[0] : span[1]], name_labels[0])
        if block and block["name"]:
            result[label] = block
    return result or None


def fetch_skills(content_id: int | None) -> dict[str, dict[str, str]] | None:
    """按 gamekeeContentId 提取技能组。

    返回 {"技能1": {...}, "技能2": {...}, "爆裂技能": {...}}；缓存缺失返回 None。
    """
    rows = _load_content_rows(content_id)
    if rows is None:
        return None
    return _rows_to_skills(rows)


def fetch_skills_online(content_id: int | None) -> dict[str, dict[str, str]] | None:
    """在线兜底：按 content_id 从 GameKee 拉取并解析技能组。"""
    from .online import fetch_online_payload

    if not content_id:
        return None
    payload = fetch_online_payload(content_id)
    if not payload or not payload.get("baseData"):
        return None
    rows = [row for row in payload["baseData"] if isinstance(row, list)]
    return _rows_to_skills(rows)


def fetch_skills_from_dictionary(rec: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    """从增强词典的 skills 字段提取技能组（Codex 已内置）。

    返回 {"技能1": {...}, "技能2": {...}, "爆裂技能": {...}}；字段缺失返回 None。
    effect 为 "待确认" 时保留空串，由调用方决定是否回退缓存解析。
    """
    raw = rec.get("skills")
    if not isinstance(raw, dict):
        return None
    mapping = {"skill1": "技能1", "skill2": "技能2", "burstSkill": "爆裂技能"}
    result: dict[str, dict[str, str]] = {}
    for key, label in mapping.items():
        block = raw.get(key)
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or "").strip()
        if not name:
            continue
        effect = str(block.get("effect") or "").strip()
        if effect == "待确认":
            effect = ""
        result[label] = {
            "name": name,
            "type": str(block.get("type") or "").strip(),
            "cooldown": str(block.get("cooldown") or "").strip(),
            "desc": effect,
            "desc_lv10": "",
        }
    return result or None


def _has_treasure(rec: dict[str, Any]) -> bool:
    """判断角色是否有珍藏品。

    词典 favoriteItem.status=已确认 优先；其次用缓存探测——
    缓存内容里存在「珍藏品名称」非空值即视为有珍藏品（词典可能滞后）。
    """
    fav = rec.get("favoriteItem")
    if isinstance(fav, dict) and fav.get("status") == "已确认":
        return True
    # 缓存探测：珍藏品名称标签有实际值
    rows = _load_content_rows(rec.get("gamekeeContentId"))
    if rows is None:
        return False
    for row in rows:
        cells = _row_values(row)
        if cells and cells[0] == "珍藏品名称":
            return bool(len(cells) > 1 and cells[1].strip())
    return False


def resolve_skills(rec: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    """获取角色技能组。

    优先级：
      1. 角色有珍藏品（词典已确认 或 缓存探测到）且内容缓存可解析 → 用缓存
         （缓存含 lv10 珍藏品强化效果，词典只存 lv1 效果）
      2. 否则用词典内置 skills，effect 缺失时回退缓存补齐。
    """
    if _has_treasure(rec):
        cached = fetch_skills(rec.get("gamekeeContentId"))
        if cached:
            return cached

    base = fetch_skills_from_dictionary(rec)
    if base is None:
        return fetch_skills(rec.get("gamekeeContentId"))

    # 检查是否有 effect 待确认的技能块
    needs_cache = any(not block.get("desc") for block in base.values())
    if not needs_cache:
        return base

    cached = fetch_skills(rec.get("gamekeeContentId")) or {}
    for label, block in base.items():
        if block.get("desc"):
            continue
        cached_block = cached.get(label)
        if cached_block and cached_block.get("desc"):
            block["desc"] = cached_block["desc"]
    return base


def fetch_favorite_item(rec: dict[str, Any]) -> dict[str, str] | None:
    """从角色记录/内容缓存提取珍藏品基本信息（名称/稀有度/简介）。

    返回 {"name": ..., "rarity": ..., "desc": ...}；无珍藏品返回 None。
    """
    fav = rec.get("favoriteItem")
    if isinstance(fav, dict) and fav.get("status") == "已确认":
        name = str(fav.get("itemName") or "").strip()
        if name and name != "珍藏品（名称待确认）":
            return {
                "name": name,
                "rarity": str(fav.get("rarity") or "").strip(),
                "desc": str(fav.get("desc") or "").strip(),
            }

    # 从内容缓存补全（珍藏品名称/稀有度/简介）
    rows = _load_content_rows(rec.get("gamekeeContentId"))
    if rows is None:
        return None
    name = rarity = desc = ""
    for row in rows:
        cells = _row_values(row)
        if not cells:
            continue
        label, value = cells[0], (cells[1] if len(cells) > 1 else "")
        if label == "珍藏品名称" and value:
            name = value
        elif label == "珍藏品稀有度" and value and not rarity:
            rarity = value
        elif label == "珍藏品简介" and value and not desc:
            desc = value
    if not name:
        return None
    return {"name": name, "rarity": rarity, "desc": desc}


def format_favorite_text(item: dict[str, str]) -> str:
    """把珍藏品信息格式化为可读文本。"""
    if not item:
        return ""
    lines = [f"珍藏品：{item.get('name', '')}"]
    if item.get("rarity"):
        lines.append(f"稀有度：{item['rarity']}")
    if item.get("desc"):
        lines.append(f"简介：{item['desc']}")
    return "\n".join(lines)


def format_skills_text(skills: dict[str, dict[str, str]]) -> str:
    """把技能组格式化为角色卡可读文本（技能块间空行分隔，描述完整展示）。"""
    if not skills:
        return "技能资料暂未收录"
    blocks: list[str] = []
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
        block_lines = [" ".join(parts)]
        desc = block.get("desc") or ""
        desc_lv10 = block.get("desc_lv10") or ""
        if desc:
            # 描述完整展示：保留所有行，统一用「　」前缀
            desc_lines = [ln.strip() for ln in desc.splitlines() if ln.strip()]
            block_lines.extend(f"　{ln}" for ln in desc_lines)
        if desc_lv10 and desc_lv10 != desc:
            # 珍藏品强化效果（lv10）——仅在存在且与普通描述不同时展示；
            # 与普通效果之间空 1 行分隔
            block_lines.append("")
            block_lines.append("　【珍藏品强化】")
            lv10_lines = [ln.strip() for ln in desc_lv10.splitlines() if ln.strip()]
            block_lines.extend(f"　{ln}" for ln in lv10_lines)
        blocks.append("\n".join(block_lines))
    # 技能块之间空 2 行分隔（\n\n\n = 两个空行）
    return "\n\n\n".join(blocks) if blocks else "技能资料暂未收录"
