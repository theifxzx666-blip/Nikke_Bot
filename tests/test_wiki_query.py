# -*- coding: utf-8 -*-
"""P1 本地角色查询技能测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from guild_war_bot.skills.nikke_wiki import NikkeWikiSkill
from guild_war_bot.wiki_query import WikiIndex, normalize_query, summarize_character
from guild_war_bot.wiki_query.normalizer import extract_after_keyword
from guild_war_bot.wiki_query.summarize import not_found_text

DATA_DIR = Path(r"F:\Codex\Nikke\Nikke_Wiki\data")


@pytest.fixture(scope="module")
def index() -> WikiIndex:
    idx = WikiIndex(data_dir=DATA_DIR)
    assert idx.load(), "本地数据加载失败，无法测试"
    return idx


class TestWikiIndex:
    def test_load_has_characters(self, index: WikiIndex):
        assert len(index.characters) > 100  # 增强词典应包含 191 角色
        assert len(index.by_name) > 100
        assert len(index.by_cnname) > 100

    def test_lookup_by_cnname(self, index: WikiIndex):
        rec = index.lookup("红莲")
        assert rec is not None
        assert rec.get("name") or rec.get("cnName")

    def test_lookup_by_name(self, index: WikiIndex):
        rec = index.lookup("Laplace")
        assert rec is not None

    def test_lookup_by_alias(self, index: WikiIndex):
        # 别名表命中（如 2B -> 2B）
        rec = index.lookup("2B")
        assert rec is not None

    def test_lookup_unknown_returns_none(self, index: WikiIndex):
        assert index.lookup("不存在的角色XYZ") is None

    def test_card_text_contains_name(self, index: WikiIndex):
        rec = index.lookup("红莲")
        text = index.card_text(rec)
        assert "职业" in text or "爆裂" in text


class TestNormalizer:
    def test_strip_at_and_slash(self):
        assert normalize_query("/角色 红莲") == "角色 红莲"
        assert normalize_query("／角色　红莲") == "角色 红莲"

    def test_fullwidth_to_halfwidth(self):
        assert normalize_query("红莲！") == "红莲"

    def test_extract_after_keyword(self):
        assert extract_after_keyword("/角色 红莲", ("角色",)) == "红莲"
        assert extract_after_keyword("查角色 神罚", ("角色", "查角色")) == "神罚"
        assert extract_after_keyword("/角色", ("角色",)) == ""
        assert extract_after_keyword("/查刀", ("角色",)) is None


class TestSummarize:
    def test_summarize_character(self, index: WikiIndex):
        rec = index.lookup("红莲")
        text = summarize_character(index, rec)
        assert "红莲" in text
        assert "\n" in text  # 多行角色卡

    def test_not_found_text(self):
        assert "没查到" in not_found_text("XYZ")


class TestNikkeWikiSkill:
    def test_matches_role(self):
        skill = NikkeWikiSkill()
        from guild_war_bot.skills.base import IncomingMessage

        msg = IncomingMessage(
            raw_text="/角色 红莲", command="角色 红莲",
            sender_name="t", sender_qq="1", is_admin=False, event={},
        )
        assert skill.matches(msg)

    def test_handle_role_found(self, index: WikiIndex):
        skill = NikkeWikiSkill()
        skill._index = index
        from guild_war_bot.skills.base import IncomingMessage, SkillContext

        msg = IncomingMessage(
            raw_text="/角色 红莲", command="角色 红莲",
            sender_name="t", sender_qq="1", is_admin=False, event={},
        )
        result = skill.handle(msg, SkillContext(bot=None, reply=None))  # type: ignore[arg-type]
        assert result is not None
        assert "红莲" in result

    def test_handle_role_not_found(self, index: WikiIndex):
        skill = NikkeWikiSkill()
        skill._index = index
        from guild_war_bot.skills.base import IncomingMessage, SkillContext

        msg = IncomingMessage(
            raw_text="/角色 不存在的角色XYZ", command="角色 不存在的角色XYZ",
            sender_name="t", sender_qq="1", is_admin=False, event={},
        )
        result = skill.handle(msg, SkillContext(bot=None, reply=None))  # type: ignore[arg-type]
        assert result is not None
        assert "没查到" in result


class TestSkillFetch:
    """技能组解析测试（依赖 GameKee 内容缓存）。"""

    def test_fetch_skills_red_lotus(self):
        from guild_war_bot.wiki_query.skills import fetch_skills, format_skills_text

        # 红莲 gamekeeContentId=152335，缓存应存在
        skills = fetch_skills(152335)
        assert skills is not None
        assert "技能1" in skills and "爆裂技能" in skills
        assert skills["技能1"]["name"]
        text = format_skills_text(skills)
        assert "技能1：" in text

    def test_fetch_skills_missing_cache(self):
        from guild_war_bot.wiki_query.skills import fetch_skills

        # 不存在的 contentId 返回 None，不抛异常
        assert fetch_skills(999999999) is None
        assert fetch_skills(None) is None


class TestOnlineFallback:
    """P2 在线兜底测试（依赖 GameKee 网络，可跳过）。"""

    def test_search_role_online(self):
        from guild_war_bot.wiki_query.online import search_role

        role = search_role("红莲")
        if role is None:
            import pytest
            pytest.skip("GameKee 网络不可用")
        assert role.get("content_id")

    def test_online_skill_fallback(self):
        from guild_war_bot.wiki_query.skills import fetch_skills_online

        skills = fetch_skills_online(713891)  # 拉普拉斯：究极英雄
        if skills is None:
            import pytest
            pytest.skip("GameKee 网络不可用")
        assert "技能1" in skills

    def test_search_role_with_colon(self):
        from guild_war_bot.wiki_query.online import search_role

        # 冒号被 normalize 去掉后仍能在线匹配
        role = search_role("拉普拉斯究极英雄")
        if role is None:
            import pytest
            pytest.skip("GameKee 网络不可用")
        assert "究极英雄" in str(role.get("name"))
