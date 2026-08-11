from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from guild_war_bot.service_http import BridgeOutbox, handle_bridge_command
from guild_war_bot.skills.registry import SkillDispatchResult


class EmptyRegistry:
    def dispatch(self, message, context):
        return SkillDispatchResult(handled=False)


class EchoSkillRegistry:
    def dispatch(self, message, context):
        if message.command != "桥接图片":
            return SkillDispatchResult(handled=False)
        context.reply.send_text("异步文字")
        context.reply.send_image(Path("tests/data/progress.png"), "异步图片")
        return SkillDispatchResult(handled=True, reply="已入队")


class AstrBotBridgeServiceTests(unittest.TestCase):
    def test_bridge_dispatches_guild_war_text_command_to_skill(self) -> None:
        bot = Mock()
        bot.summary.return_value = "今日 10/90 刀"

        result = handle_bridge_command(
            bot,
            {
                "text": "/查刀",
                "sender_name": "tester",
                "sender_qq": "123456",
                "is_admin": False,
                "session_id": "s1",
            },
            outbox=BridgeOutbox(),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["handled"])
        self.assertEqual(result["reply"], "今日 10/90 刀")
        bot.summary.assert_called_once()
        bot.handle_message.assert_not_called()

    def test_bridge_falls_back_to_core_bot_for_unknown_command(self) -> None:
        bot = Mock()
        bot.handle_message.return_value = "fallback reply"

        result = handle_bridge_command(
            bot,
            {
                "text": "/未知命令",
                "sender_name": "tester",
                "sender_qq": "123456",
                "is_admin": False,
                "session_id": "s1x",
            },
            outbox=BridgeOutbox(),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["handled"])
        self.assertEqual(result["reply"], "fallback reply")
        bot.handle_message.assert_called_once_with(
            "tester",
            "/未知命令",
            is_admin=False,
            sender_qq="123456",
        )

    def test_bridge_outbox_collects_skill_replies(self) -> None:
        bot = Mock()
        outbox = BridgeOutbox()

        result = handle_bridge_command(
            bot,
            {
                "text": "/桥接图片",
                "sender_name": "tester",
                "session_id": "s2",
            },
            registry=EchoSkillRegistry(),
            outbox=outbox,
        )
        messages = [message.to_json() for message in outbox.read_after("s2")]

        self.assertEqual(result["reply"], "已入队")
        self.assertEqual(messages[0]["type"], "text")
        self.assertEqual(messages[0]["text"], "异步文字")
        self.assertEqual(messages[1]["type"], "image")
        self.assertEqual(messages[1]["caption"], "异步图片")
        self.assertTrue(messages[1]["path"].endswith("tests\\data\\progress.png"))
        bot.handle_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
