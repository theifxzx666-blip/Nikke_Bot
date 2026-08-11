from __future__ import annotations

import unittest
from unittest.mock import Mock

from guild_war_bot.skills.base import IncomingMessage, SkillContext
from guild_war_bot.skills.guild_war import (
    GuildWarAdminSkill,
    GuildWarAttackRecordSkill,
    GuildWarAttackStatusSkill,
)


class NullReply:
    def send_text(self, message: str) -> None:
        raise AssertionError("unexpected async text reply")

    def send_image(self, image_path, caption: str = "") -> None:
        raise AssertionError("unexpected async image reply")


def message(text: str, *, is_admin: bool = False) -> IncomingMessage:
    return IncomingMessage(
        raw_text=text,
        command=text.strip().lstrip("/／").strip(),
        sender_name="群名片",
        sender_qq="10001",
        is_admin=is_admin,
        event={},
    )


class GuildWarSkillTests(unittest.TestCase):
    def test_attack_status_skill_handles_member_report(self) -> None:
        bot = Mock()
        bot.member_report.return_value = "member report"
        skill = GuildWarAttackStatusSkill()

        reply = skill.handle(message("/查刀 Alice"), SkillContext(bot=bot, reply=NullReply()))

        self.assertEqual(reply, "member report")
        bot.member_report.assert_called_once_with("Alice")

    def test_attack_record_skill_resolves_sender_and_records_damage(self) -> None:
        bot = Mock()
        bot.resolve_member_name.return_value = "Alice"
        bot.record_attack.return_value = "recorded"
        skill = GuildWarAttackRecordSkill()

        reply = skill.handle(message("/出刀 1200w"), SkillContext(bot=bot, reply=NullReply()))

        self.assertEqual(reply, "recorded")
        bot.resolve_member_name.assert_called_once_with("群名片", "10001")
        bot.record_attack.assert_called_once_with("Alice", damage=12_000_000, note="1200w")

    def test_admin_skill_rejects_non_admin_reset(self) -> None:
        bot = Mock()
        skill = GuildWarAdminSkill()

        reply = skill.handle(message("/重置今日"), SkillContext(bot=bot, reply=NullReply()))

        self.assertEqual(reply, "只有管理员可以使用这条指令。")
        bot.reset_day.assert_not_called()

    def test_admin_skill_allows_proxy_attack_record(self) -> None:
        bot = Mock()
        bot.record_attack.return_value = "proxy recorded"
        skill = GuildWarAdminSkill()

        reply = skill.handle(
            message("/代出刀 Alice 3500万", is_admin=True),
            SkillContext(bot=bot, reply=NullReply()),
        )

        self.assertEqual(reply, "proxy recorded")
        bot.record_attack.assert_called_once_with("Alice", damage=35_000_000)


if __name__ == "__main__":
    unittest.main()
