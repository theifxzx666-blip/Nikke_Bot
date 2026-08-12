# -*- coding: utf-8 -*-
"""本地角色数据索引（WikiIndex）。

启动时一次性加载 Nikke_Wiki/data 的增强词典与别名表，构建三张内存索引：
  - by_name   : 英文名 -> record
  - by_cnname : 中文名 -> record
  - by_alias  : 别名   -> 正式名（用于黑话/昵称归一化）

数据文件缺失或损坏时降级为"空索引"，由调用方决定是否提示，不抛异常。
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(r"F:\Codex\Nikke\Nikke_Wiki\data")

# 角色卡摘要用到的字段（存在才展示，缺失自动跳过）
_CARD_FIELDS: tuple[tuple[str, str], ...] = (
    ("cnName", "名称"),
    ("class", "职业"),
    ("burst", "爆裂"),
    ("element", "元素"),
    ("weapon", "武器"),
    ("squad", "部队"),
    ("manufacturer", "阵营"),
    ("rarity", "稀有度"),
    ("cnReleased", "国服"),
)


@dataclass
class WikiIndex:
    data_dir: Path = DEFAULT_DATA_DIR
    characters: list[dict[str, Any]] = field(default_factory=list)
    by_name: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_cnname: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_alias: dict[str, str] = field(default_factory=dict)

    def load(self) -> bool:
        """加载本地数据。返回是否成功（文件缺失/损坏返回 False 并降级为空索引）。"""
        try:
            self.characters = _load_json(self.data_dir / "nikke_character_dictionary_enhanced.json")
            aliases = _load_json(self.data_dir / "nikke_character_aliases.json")
        except Exception as exc:  # noqa: BLE001
            logger.warning("WikiIndex 加载失败，降级为空索引: %s", exc)
            self.characters, self.by_name, self.by_cnname, self.by_alias = [], {}, {}, {}
            return False

        self.by_name = {}
        self.by_cnname = {}
        for rec in self.characters:
            name = str(rec.get("name") or "").strip()
            cn = str(rec.get("cnName") or "").strip()
            if name:
                self.by_name[name] = rec
            if cn:
                self.by_cnname[cn] = rec

        # 合并机器人侧补充角色（不修改 Nikke_Wiki，避免被 Codex 更新覆盖）
        for rec in self._load_extra_characters():
            name = str(rec.get("name") or "").strip()
            cn = str(rec.get("cnName") or "").strip()
            if name:
                self.by_name[name] = rec
            if cn:
                self.by_cnname[cn] = rec

        self.by_alias = {}
        if isinstance(aliases, dict):
            for formal, alias_list in aliases.items():
                if not isinstance(alias_list, list):
                    continue
                for alias in alias_list:
                    key = str(alias).strip()
                    if key and key not in self.by_alias:
                        self.by_alias[key] = str(formal)

        # 合并机器人侧补充别名（不修改 Nikke_Wiki，避免被 Codex 更新覆盖）
        extra = self._load_extra_aliases()
        if extra:
            for formal, alias_list in extra.items():
                if not isinstance(alias_list, list):
                    continue
                for alias in alias_list:
                    key = str(alias).strip()
                    if key and key not in self.by_alias:
                        self.by_alias[key] = str(formal)

        logger.info("WikiIndex 加载完成: %d 角色, %d 别名", len(self.characters), len(self.by_alias))
        return True

    def _load_extra_characters(self) -> list[dict[str, Any]]:
        """加载机器人侧补充角色 data/characters_extra.json。"""
        extra_path = Path(__file__).resolve().parents[2] / "data" / "characters_extra.json"
        try:
            if extra_path.exists():
                data = _load_json(extra_path)
                if isinstance(data, list):
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("补充角色表加载失败: %s", exc)
        return []

    def _load_extra_aliases(self) -> dict[str, list[str]]:
        """加载机器人侧补充别名表 data/character_aliases_extra.json。"""
        extra_path = Path(__file__).resolve().parents[2] / "data" / "character_aliases_extra.json"
        try:
            if extra_path.exists():
                data = _load_json(extra_path)
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("补充别名表加载失败: %s", exc)
        return {}

    def lookup(self, query: str) -> dict[str, Any] | None:
        """按 英文名 / 中文名 / 别名 顺序查找，返回角色记录或 None。

        精确匹配失败时，尝试去标点匹配（normalize_query 会移除冒号等标点，
        而补充词典中的名称保留冒号，如「拉普拉斯：究极英雄」）。
        """
        q = query.strip()
        if not q:
            return None
        for table in (self.by_cnname, self.by_name):
            if q in table:
                return table[q]
        formal = self.by_alias.get(q)
        if formal:
            return self.by_cnname.get(formal) or self.by_name.get(formal)
        # 去标点匹配（normalize 已移除冒号，而词典/补充词典名称保留冒号）
        q_norm = "".join(ch for ch in q if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
        if q_norm:
            for table in (self.by_cnname, self.by_name):
                for key, rec in table.items():
                    key_norm = "".join(ch for ch in key if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
                    if key_norm == q_norm:
                        return rec
        # 兜底：形态角色倒序/部分匹配（覆盖社区简称，如「女仆马斯特」→「马斯特：浪漫的女仆」、
        # 「暗影红莲」→「红莲：暗影」、「冬日甜心迪塞尔」→「迪塞尔：冬日甜心」）
        if q_norm and len(q_norm) >= 4:
            for cn, rec in self.by_cnname.items():
                if "：" not in cn:
                    continue
                base, variant = cn.split("：", 1)
                base_n = "".join(ch for ch in base if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
                var_n = "".join(ch for ch in variant if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
                if not base_n or not var_n:
                    continue
                # 倒序：形态词 + 基础名（如 浪漫的女仆马斯特）
                if q_norm == var_n + base_n:
                    return rec
                # 部分：query 含基础名，剩余部分 ⊆ 形态词（如 女仆马斯特）
                if base_n in q_norm:
                    rest = q_norm.replace(base_n, "", 1)
                    if rest and len(rest) >= 2 and rest in var_n:
                        return rec
        return None

    def card_text(self, rec: dict[str, Any]) -> str:
        """生成角色卡短文本（仅展示存在的字段）。"""
        lines = []
        for field_key, label in _CARD_FIELDS:
            value = str(rec.get(field_key) or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        return "\n".join(lines)


def _load_json(path: Path) -> Any:
    """读取 JSON，兼容 UTF-8 BOM。"""
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def default_index() -> WikiIndex:
    """构造并加载默认索引（可被环境变量 NIKKE_WIKI_DATA_DIR 覆盖数据目录）。"""
    data_dir = Path(os.environ.get("NIKKE_WIKI_DATA_DIR") or DEFAULT_DATA_DIR)
    idx = WikiIndex(data_dir=data_dir)
    idx.load()
    return idx
