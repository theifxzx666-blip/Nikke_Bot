# -*- coding: utf-8 -*-
"""角色培养建议（屑夫蒂一图流 P3）。

数据源：data/character_meta.json（人工录入，结构见文件头注释）。
/培养 <角色名> 查询；无数据时提示待录入。
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

META_PATH = Path(__file__).resolve().parents[2] / "data" / "character_meta.json"


def load_meta() -> dict[str, dict[str, Any]]:
    """加载培养建议表 {角色中文名/别名: {tier, skill, gear, note, ...}}。"""
    try:
        if META_PATH.exists():
            with io.open(META_PATH, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("培养建议表加载失败: %s", exc)
    return {}


def find_meta(meta: dict[str, dict[str, Any]], query: str) -> dict[str, Any] | None:
    """按角色名/别名查找培养建议。"""
    if not query:
        return None
    q = query.strip()
    if q in meta:
        return meta[q]
    # 去标点匹配（与 WikiIndex.lookup 对齐）
    q_norm = "".join(ch for ch in q if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    for key, rec in meta.items():
        key_norm = "".join(ch for ch in key if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
        if key_norm == q_norm:
            return rec
    return None


def format_meta_text(meta: dict[str, dict[str, Any]], query: str) -> str | None:
    """生成培养建议文本；无数据返回 None（由调用方提示）。"""
    rec = find_meta(meta, query)
    if rec is None:
        return None
    lines = [f"【{rec.get('name', query)}】培养建议"]
    tier = rec.get("tier")
    if tier:
        lines.append(f"强度评级：{tier}")
    skill = rec.get("skill")
    if skill:
        lines.append(f"技能加点：{skill}")
    gear = rec.get("gear")
    if gear:
        lines.append(f"装备：{gear}")
    gear_stat = rec.get("gear_stat")
    if gear_stat:
        lines.append(f"词条：{gear_stat}")
    cube = rec.get("cube")
    if cube:
        lines.append(f"魔方：{cube}")
    collection = rec.get("collection")
    if collection:
        lines.append(f"收藏品：{collection}")
    team = rec.get("team")
    if team:
        lines.append(f"配队推荐：{team}")
    note = rec.get("note")
    if note:
        lines.append(f"备注：{note}")
    return "\n".join(lines)


def missing_text(query: str) -> str:
    return f"角色「{query}」的培养建议暂未收录（屑夫蒂一图流录入中）。"
