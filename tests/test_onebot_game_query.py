from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from guild_war_bot.onebot_http import (
    command_text_from_event,
    handle_onebot_event,
    normalize_adapter_command,
    send_image_reply,
)


class OneBotGameQueryTests(unittest.TestCase):
    def test_normalize_game_query_command(self) -> None:
        self.assertEqual(
            normalize_adapter_command(" /会战进度查询 "),
            "会战进度查询",
        )

    def test_group_slash_command_is_accepted_without_at_segment(self) -> None:
        event = {
            "message_type": "group",
            "self_id": 478287351,
            "message": [
                {"type": "text", "data": {"text": " /会战进度查询"}},
            ],
        }
        self.assertEqual(command_text_from_event(event), "/会战进度查询")

    @patch("guild_war_bot.onebot_http.post_json")
    def test_send_group_image_uses_onebot_segments(self, post_json) -> None:
        send_image_reply(
            {"message_type": "group", "group_id": 123},
            Path("D:/screens/progress.png"),
            "完成",
        )
        url, payload = post_json.call_args.args
        self.assertTrue(url.endswith("/send_group_msg"))
        self.assertEqual(payload["group_id"], 123)
        self.assertEqual(payload["message"][0]["type"], "text")
        self.assertEqual(payload["message"][1]["type"], "image")
        self.assertTrue(payload["message"][1]["data"]["file"].startswith("file:///"))

    @patch("guild_war_bot.skills.game_progress.threading.Thread")
    def test_game_query_dispatches_to_skill(self, thread_cls) -> None:
        bot = Mock()
        event = {
            "post_type": "message",
            "message_type": "group",
            "group_id": 123,
            "user_id": 456,
            "sender": {"nickname": "tester"},
            "message": [
                {"type": "text", "data": {"text": " /会战进度查询"}},
            ],
        }
        reply = handle_onebot_event(bot, event)
        self.assertIn("正在进入游戏", reply)
        thread_cls.assert_called_once()
        bot.handle_message.assert_not_called()

    def test_guild_war_text_command_dispatches_to_skill(self) -> None:
        bot = Mock()
        bot.summary.return_value = "skill reply"
        event = {
            "post_type": "message",
            "message_type": "group",
            "group_id": 123,
            "user_id": 456,
            "sender": {"nickname": "tester"},
            "message": [
                {"type": "text", "data": {"text": " /查刀"}},
            ],
        }
        self.assertEqual(handle_onebot_event(bot, event), "skill reply")
        bot.summary.assert_called_once()
        bot.handle_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
