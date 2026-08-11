# -*- coding: utf-8 -*-
"""角色卡摘要生成。

P1 阶段只输出文本角色卡；图片/详细立绘等留到后续阶段。
"""

from __future__ import annotations

from typing import Any

from .index import WikiIndex


def summarize_character(index: WikiIndex, rec: dict[str, Any]) -> str:
    """由角色记录生成群内角色卡文本。"""
    name = str(rec.get("cnName") or rec.get("name") or "未知角色")
    card = index.card_text(rec)
    if not card:
        return f"【{name}】暂无资料。"
    return f"【{name}】\n{card}"


def not_found_text(query: str) -> str:
    """未命中时的友好提示（不编造）。"""
    return f"角色「{query}」暂时没查到资料，指挥官再核对一下名字？也可以试试 /wiki <关键词> 在线查询。"
