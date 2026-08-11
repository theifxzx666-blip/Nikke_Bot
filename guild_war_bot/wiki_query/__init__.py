# -*- coding: utf-8 -*-
"""wiki_query：本地 NIKKE 资料检索服务（P1 本地角色查询）。

数据源只读引用 Nikke_Wiki/data（F 盘），不写入、不复制。
本包为查询类技能提供统一的索引、别名归一化与摘要生成。
"""

from .index import WikiIndex, default_index
from .normalizer import normalize_query
from .skills import resolve_skills
from .summarize import summarize_character

__all__ = ["WikiIndex", "default_index", "normalize_query", "summarize_character", "resolve_skills"]
