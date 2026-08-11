from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from guild_war_bot.core import GuildWarBot


@dataclass(frozen=True)
class IncomingMessage:
    raw_text: str
    command: str
    sender_name: str
    sender_qq: str
    is_admin: bool
    event: dict


class ReplyPort(Protocol):
    def send_text(self, message: str) -> None:
        ...

    def send_image(self, image_path: Path, caption: str = "") -> None:
        ...


@dataclass(frozen=True)
class SkillContext:
    bot: GuildWarBot
    reply: ReplyPort


class BotSkill(Protocol):
    name: str
    commands: set[str]

    def matches(self, message: IncomingMessage) -> bool:
        ...

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        ...
