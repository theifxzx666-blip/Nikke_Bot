# -*- coding: utf-8 -*-
"""NIKKE 游戏查询技能：/角色 <名>、/wiki <关键词>。

P1 实现本地角色卡查询（WikiIndex 秒回）；
P2 起接入 GameKee 在线兜底（nikke-wiki-search 技能）。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from guild_war_bot.core import normalize_command

from ..wiki_query import WikiIndex, default_index, normalize_query, resolve_skills, summarize_character
from ..wiki_query.normalizer import extract_after_keyword
from ..wiki_query.skills import format_skills_text
from ..wiki_query.summarize import character_portrait_path, not_found_text
from .base import IncomingMessage, SkillContext

_ROLE_KEYWORDS: tuple[str, ...] = ("角色", "查角色", "角色卡", "是谁")
_WIKI_KEYWORDS: tuple[str, ...] = ("wiki", "查")


class NikkeWikiSkill:
    name: str = "nikke_wiki"
    commands: ClassVar[set[str]] = {"角色", "wiki"}
    _index: WikiIndex | None = None

    @classmethod
    def _get_index(cls) -> WikiIndex:
        if cls._index is None:
            cls._index = default_index()
        return cls._index

    def matches(self, message: IncomingMessage) -> bool:
        content = normalize_command(message.raw_text or message.command)
        return extract_after_keyword(content, _ROLE_KEYWORDS) is not None or extract_after_keyword(
            content, _WIKI_KEYWORDS
        ) is not None

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        content = normalize_command(message.raw_text or message.command)

        # /角色 <名>：本地角色卡查询
        role_arg = extract_after_keyword(content, _ROLE_KEYWORDS)
        if role_arg is not None:
            return self._handle_role(role_arg, context)

        # /wiki <词>：P1 先用本地索引；P2 接在线兜底
        wiki_arg = extract_after_keyword(content, _WIKI_KEYWORDS)
        if wiki_arg is not None:
            return self._handle_wiki(wiki_arg, context)

        return None

    def _handle_role(self, arg: str, context: SkillContext) -> str:
        query = normalize_query(arg)
        if not query:
            return "用法：/角色 <名字>，例如 /角色 红莲"
        index = self._get_index()
        rec = index.lookup(query)
        if rec is None:
            return not_found_text(query)
        return self._reply_with_portrait(rec, context)

    def _handle_wiki(self, arg: str, context: SkillContext) -> str:
        query = normalize_query(arg)
        if not query:
            return "用法：/wiki <关键词>"
        index = self._get_index()
        rec = index.lookup(query)
        if rec is None:
            # P2 起改为调用 GameKee 在线检索
            return not_found_text(query)
        return self._reply_with_portrait(rec, context)

    def _reply_with_portrait(self, rec: dict, context: SkillContext) -> str:
        """返回角色卡文本（含技能组），并尝试发送本地立绘。"""
        parts = [summarize_character(self._get_index(), rec)]
        skills = resolve_skills(rec)
        if skills:
            parts.append("")
            parts.append(format_skills_text(skills))
        text = "\n".join(parts)
        path = character_portrait_path(rec)
        if path and context.reply is not None:
            try:
                context.reply.send_image(Path(path))
            except Exception:
                # 立绘发送失败不阻断文本回复
                pass
        return text
