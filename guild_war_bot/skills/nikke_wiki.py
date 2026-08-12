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
from ..wiki_query.skills import fetch_favorite_item, format_favorite_text, format_skills_text
from ..wiki_query.summarize import character_portrait_path, not_found_text
from .base import IncomingMessage, SkillContext

_ROLE_KEYWORDS: tuple[str, ...] = ("角色", "查角色", "角色卡", "是谁")
_WIKI_KEYWORDS: tuple[str, ...] = ("wiki", "查")
_META_KEYWORDS: tuple[str, ...] = ("培养", "培养建议", "加点", "怎么培养", "养成", "养成建议")
META_CROP_DIR = Path(__file__).resolve().parents[2] / "data" / "meta_crops"


class NikkeWikiSkill:
    name: str = "nikke_wiki"
    commands: ClassVar[set[str]] = {"角色", "wiki", "培养"}
    _index: WikiIndex | None = None

    @classmethod
    def _get_index(cls) -> WikiIndex:
        if cls._index is None:
            cls._index = default_index()
        return cls._index

    def matches(self, message: IncomingMessage) -> bool:
        content = normalize_command(message.raw_text or message.command)
        return (
            extract_after_keyword(content, _ROLE_KEYWORDS) is not None
            or extract_after_keyword(content, _WIKI_KEYWORDS) is not None
            or extract_after_keyword(content, _META_KEYWORDS) is not None
        )

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        content = normalize_command(message.raw_text or message.command)

        # /角色 <名>：本地角色卡查询
        role_arg = extract_after_keyword(content, _ROLE_KEYWORDS)
        if role_arg is not None:
            return self._handle_role(role_arg, context)

        # /培养 <名>：培养建议（屑夫蒂一图流，P3）
        meta_arg = extract_after_keyword(content, _META_KEYWORDS)
        if meta_arg is not None:
            return self._handle_meta(meta_arg, context)

        # /wiki <词>：P1 先用本地索引；P2 接在线兜底
        wiki_arg = extract_after_keyword(content, _WIKI_KEYWORDS)
        if wiki_arg is not None:
            return self._handle_wiki(wiki_arg, context)

        return None

    def _handle_role(self, arg: str, context: SkillContext) -> str:
        query = normalize_query(arg)
        if not query:
            return "用法：/角色 <名字>，例如 /角色 红莲；培养建议用 /养成 <名字>"
        index = self._get_index()
        rec = index.lookup(query)
        if rec is None:
            return self._handle_online(query, context)
        return self._reply_with_portrait(rec, context)

    def _handle_meta(self, arg: str, context: SkillContext) -> str:
        """培养建议查询（屑夫蒂一图流 P3）：返回文本 + 调试期附原图区块截图。"""
        from ..wiki_query.meta import format_meta_text, load_meta, missing_text

        query = normalize_query(arg)
        if not query:
            return "用法：/养成 <角色名>，例如 /养成 红莲"
        meta = load_meta()
        text = format_meta_text(meta, query)
        if text is None:
            return missing_text(query)
        self._send_meta_crop(query, context)
        return text

    def _send_meta_crop(self, name: str, context: SkillContext) -> None:
        """发送角色在屑夫蒂一图流中的原图区块（立绘+养成方案）。"""
        if context.reply is None or not META_CROP_DIR.exists():
            return
        # 文件名安全化（与 build_character_meta.py 一致）
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "", name)
        path = META_CROP_DIR / f"{safe}.png"
        if not path.exists():
            return
        try:
            context.reply.send_image(path)
        except Exception:
            pass

    def _handle_wiki(self, arg: str, context: SkillContext) -> str:
        query = normalize_query(arg)
        if not query:
            return "用法：/wiki <关键词>"
        index = self._get_index()
        rec = index.lookup(query)
        if rec is None:
            # P2：GameKee 在线兜底
            return self._handle_online(query, context)
        return self._reply_with_portrait(rec, context)

    def _handle_online(self, query: str, context: SkillContext) -> str:
        """GameKee 在线兜底：搜索角色、拉取技能、下载立绘并发送。"""
        from ..wiki_query.online import (
            download_portrait,
            fetch_online_payload,
            format_online_profile,
            search_role,
        )
        from ..wiki_query.skills import fetch_skills_online, format_skills_text

        role = search_role(query)
        if role is None:
            return not_found_text(query)
        content_id = role.get("content_id")
        name = str(role.get("name") or query).strip()
        if not content_id:
            return f"角色「{name}」在 GameKee 已找到，但暂无详情数据。"
        skills = fetch_skills_online(content_id)
        if not skills:
            return f"角色「{name}」已找到，但技能资料暂未收录（GameKee 在线获取失败）。"

        # 基本属性（角色卡头部）
        profile = ""
        payload = fetch_online_payload(content_id)
        if payload and payload.get("baseData"):
            profile = format_online_profile(payload["baseData"])

        # 下载立绘并发送
        if context.reply is not None:
            try:
                out_dir = Path(__file__).resolve().parents[2] / "data" / "online_portraits"
                portrait = download_portrait(role, out_dir, name)
                if portrait:
                    context.reply.send_image(portrait)
            except Exception:
                # 立绘下载/发送失败不阻断技能回复
                pass

        parts = [f"【{name}】（GameKee 在线数据）"]
        if profile:
            parts.append(profile)
        parts.append("")
        parts.append(format_skills_text(skills))
        return "\n".join(parts)

    def _reply_with_portrait(self, rec: dict, context: SkillContext) -> str:
        """返回角色卡文本（含技能组与珍藏品），并尝试发送本地立绘。"""
        parts = [summarize_character(self._get_index(), rec)]
        fav = fetch_favorite_item(rec)
        if fav:
            parts.append("")
            parts.append(format_favorite_text(fav))
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
